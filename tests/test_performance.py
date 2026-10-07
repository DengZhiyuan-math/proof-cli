"""One read, one pass (#43): no DDL on a current schema, and reads that stay linear in the map.

The wall-clock benchmark on a 200-node chain runs with PROOF_BENCHMARK=1;
the default suite checks the same thing machine-independently, by counting
SQL statements and reviews.jsonl reads: doubling the chain may at most
roughly double them.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

import proof_cli.proof_map as proof_map
import proof_cli.reviews as reviews
import proof_cli.storage as storage
from _proofs import submit_proof
from _researcher import researcher
from proof_cli.proof_map import (
    counting_upstream_visits,
    create_node,
    get_acceptance_state,
    get_blocked_reason,
    get_frontier,
    get_integrity_state,
    get_reference_review_state,
    get_workflow_state,
    list_nodes,
    open_challenge,
)
from proof_cli.storage import ensure_project, read_scope


@pytest.fixture
def statements(monkeypatch):
    """Every SQL statement run on a connection opened from here on."""
    seen: list[str] = []
    real_connect = storage.connect

    def traced(path):
        conn = real_connect(path)
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(storage, "connect", traced)
    return seen


@pytest.fixture
def review_reads(monkeypatch):
    """Every reviews.jsonl read from here on, by path."""
    seen: list[Path] = []
    real_read = reviews._read_file

    def counted(path):
        seen.append(path)
        return real_read(path)

    monkeypatch.setattr(reviews, "_read_file", counted)
    return seen


def _accepted_chain(root: Path, length: int):
    """n0 <- n1 <- ... : every node Accepted, each resting on the one before."""
    store = ensure_project(root)
    previous = None
    for index in range(length):
        node_id = f"n{index}"
        create_node(store, node_id=node_id, kind="lemma", statement=f"s{index}", dependencies=[previous] if previous else None)
        submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="r", content=f"proof {index}")
        researcher(store).decide_acceptance(node_id, "accept")
        previous = node_id
    return store


def _node_show(store, node_id: str) -> None:
    """What `proof node show` computes."""
    with read_scope():
        get_workflow_state(store, node_id)
        get_acceptance_state(store, node_id)
        get_integrity_state(store, node_id)
        get_blocked_reason(store, node_id)


# -- connect() -------------------------------------------------------------------------


def test_connect_runs_no_ddl_once_the_schema_is_current(tmp_path: Path, statements):
    store = ensure_project(tmp_path)
    store.connect().close()  # the schema is applied
    statements.clear()

    store.connect().close()

    assert statements == ["PRAGMA user_version", "PRAGMA schema_version"]


def test_a_dropped_trigger_is_recreated_on_the_next_connect(tmp_path: Path):
    """Any DDL moves SQLite's schema cookie, so a hand-edited schema is re-checked, not trusted."""
    store = ensure_project(tmp_path)
    raw = sqlite3.connect(store.db_path)
    raw.execute("DROP TRIGGER review_history_no_update")
    raw.commit()
    raw.close()

    with store.connect() as conn:
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert "review_history_no_update" in names


def test_a_release_with_different_ddl_reapplies_it(tmp_path: Path, monkeypatch, statements):
    store = ensure_project(tmp_path)
    monkeypatch.setattr(storage, "_SCHEMA_DDL_DIGEST", storage._SCHEMA_DDL_DIGEST ^ 1)
    statements.clear()

    store.connect().close()

    assert any(statement.lstrip().upper().startswith("CREATE TABLE") for statement in statements)


def test_a_project_stamped_before_snapshot_dependencies_gains_the_column(tmp_path: Path):
    """A project an older release migrated and stamped, before #96's `candidate_proofs.dependencies`,
    gets the column on its next connect: the added columns are part of the DDL fingerprint."""
    store = ensure_project(tmp_path)
    raw = sqlite3.connect(store.db_path)
    raw.execute("ALTER TABLE candidate_proofs DROP COLUMN dependencies")
    raw.commit()
    cookie = raw.execute("PRAGMA schema_version").fetchone()[0]
    older_digest = storage._SCHEMA_DDL_DIGEST ^ 1  # the older release's DDL, without the column
    raw.execute(f"PRAGMA user_version = {(older_digest ^ cookie) & 0x7FFFFFFF}")  # current, as that release saw it
    raw.commit()
    raw.close()

    with store.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidate_proofs)")}
    assert "dependencies" in columns


def test_a_project_stamped_before_side_documents_gains_the_table(tmp_path: Path):
    """A project an older release migrated and stamped, before #39's `side_documents` table,
    gets the table on its next connect: its DDL is part of the fingerprint."""
    store = ensure_project(tmp_path)
    raw = sqlite3.connect(store.db_path)
    raw.execute("DROP TABLE side_documents")
    raw.commit()
    cookie = raw.execute("PRAGMA schema_version").fetchone()[0]
    older_digest = storage._SCHEMA_DDL_DIGEST ^ 1  # the older release's DDL, without the table
    raw.execute(f"PRAGMA user_version = {(older_digest ^ cookie) & 0x7FFFFFFF}")  # current, as that release saw it
    raw.commit()
    raw.close()

    with store.connect() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "side_documents" in tables


# -- reads stay linear -----------------------------------------------------------------


def _read_cost(root: Path, length: int, statements: list[str], review_reads: list[Path]) -> dict[str, int]:
    store = _accepted_chain(root, length)
    cost = {}
    statements.clear()
    review_reads.clear()
    get_frontier(store)
    cost["frontier statements"], cost["frontier review reads"] = len(statements), len(review_reads)
    statements.clear()
    review_reads.clear()
    _node_show(store, f"n{length - 1}")
    cost["node show statements"], cost["node show review reads"] = len(statements), len(review_reads)
    return cost


def test_the_frontier_and_a_node_read_grow_linearly_with_the_chain(tmp_path: Path, statements, review_reads):
    """The last node's integrity walks the whole chain: once per read, not once per node it asks about."""
    small = _read_cost(tmp_path / "small", 20, statements, review_reads)
    large = _read_cost(tmp_path / "large", 40, statements, review_reads)

    for measure in small:
        assert large[measure] <= 2.5 * small[measure], (measure, small[measure], large[measure])


def _provisional_chain(root: Path, length: int):
    """c0 <- c1 <- ... <- top: every Claim unaccepted, its snapshot passed by the Verifier, so each is Provisional
    on all below it (ADR-0021), and one Definition every Claim names, edited once."""
    from proof_cli import definitions
    from proof_cli.proof_map import record_evidence_check, restate_node

    store = ensure_project(root)
    definitions.add_definition(store, "unit", term="Unit", text="u", created_by="dec-1")
    previous = None
    for index in range(length):
        node_id = f"c{index}"
        create_node(store, node_id=node_id, kind="claim", statement=f"s{index}", dependencies=[previous] if previous else None,
                    definitions=["unit"], created_by="dec-1")
        previous = node_id
    restate_node(store, "c0", statement="s0, restated", reason="clearer", by="dec-1")
    definitions.edit_definition(store, "unit", text="u'", edited_by="dec-1", reason="clearer")
    for index in range(length):
        proof = submit_proof(store, f"c{index}", claimant_id="agent_a", scoping_rationale="r", content=f"proof {index}")
        record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", notes="no objections")
    create_node(store, node_id="top", kind="lemma", statement="t", dependencies=[previous])
    return store


@pytest.fixture
def events_read(monkeypatch):
    """How many event rows the proof map has read from here on: a scan of the log per node is quadratic in rows even
    when it is one statement."""
    seen = [0]
    real_list_events = proof_map.list_events

    def counted(store):
        found = real_list_events(store)
        seen[0] += len(found)
        return found

    monkeypatch.setattr(proof_map, "list_events", counted)
    return seen


def _provisional_read_cost(root: Path, length: int, statements: list[str], events_read: list[int]) -> dict[str, int]:
    from proof_cli.proof_map import conditional_on, fixed_by, is_provisional, verdicts

    store = _provisional_chain(root, length)
    cost = {}
    statements.clear()
    events_read[0] = 0
    assert [node.id for node in get_frontier(store)] == ["top"]
    cost["frontier statements"], cost["frontier events read"] = len(statements), events_read[0]
    statements.clear()
    events_read[0] = 0
    with read_scope():
        for node in list_nodes(store):
            get_integrity_state(store, node.id), is_provisional(store, node.id), conditional_on(store, node.id)
            fixed_by(store, node.id), verdicts(store, node.id)
    cost["node list statements"], cost["node list events read"] = len(statements), events_read[0]
    return cost


def test_provisional_and_unfixed_reads_grow_linearly_with_the_chain(tmp_path: Path, statements, events_read):
    """Restatements, fixing decisions and verdicts are indexed once per read, not scanned once per node (ADR-0021)."""
    small = _provisional_read_cost(tmp_path / "small", 20, statements, events_read)
    large = _provisional_read_cost(tmp_path / "large", 40, statements, events_read)

    for measure in small:
        assert large[measure] <= 2.5 * small[measure], (measure, small[measure], large[measure])


def test_a_write_inside_a_read_scope_is_seen_by_the_reads_after_it(tmp_path: Path):
    store = _accepted_chain(tmp_path, 2)
    with read_scope():
        assert get_acceptance_state(store, "n1") == "accepted"
        submit_proof(store, "n1", claimant_id="agent_a", scoping_rationale="r", content="proof 1, revised")
        assert get_workflow_state(store, "n1") == "review-needed"
        researcher(store).decide_acceptance("n1", "reject")
        assert get_acceptance_state(store, "n1") == "rejected"


@pytest.mark.skipif(not os.environ.get("PROOF_BENCHMARK"), reason="wall-clock benchmark: set PROOF_BENCHMARK=1")
def test_benchmark_a_200_node_chain(tmp_path: Path):
    store = _accepted_chain(tmp_path, 200)

    started = time.perf_counter()
    get_frontier(store)
    frontier = time.perf_counter() - started
    started = time.perf_counter()
    _node_show(store, "n199")
    node_show = time.perf_counter() - started

    assert frontier < 1.0, frontier
    assert node_show < 0.3, node_show


# -- one topological pass per read (#108) ----------------------------------------------

CHAIN = 200


def _chain_with_claims(root: Path, length: int):
    store = _accepted_chain(root, length)
    for index in range(length):
        create_node(store, node_id=f"c{index}", kind="claim", statement=f"c{index}", dependencies=[f"n{index}"])
    return store


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    """A 200-node Accepted chain with an open claim hanging off every link, built once.

    Whether claim c<i> is blocked asks whether n<i> is settled, which means
    walking everything above n<i>: walked per node, one read costs n^2/2
    visits; in one pass, each link is visited once."""
    return _chain_with_claims(tmp_path_factory.mktemp("chain"), CHAIN)


def _page(read: str):
    def run(store) -> None:
        ReviewApp = pytest.importorskip("proof_web.server").ReviewApp  # the page (proof-web), when it is installed

        app = ReviewApp(store)
        try:
            app.map() if read == "map" else app.node(f"n{CHAIN - 1}")
        finally:
            app.close()

    return run


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(get_frontier, id="frontier"),
        pytest.param(lambda store: _node_show(store, f"n{CHAIN - 1}"), id="node show"),
        pytest.param(lambda store: _node_show(store, f"c{CHAIN - 1}"), id="node show, a blocked leaf"),
        pytest.param(_page("map"), id="/api/map"),
        pytest.param(_page("node"), id="/api/node"),
    ],
)
def test_one_read_visits_each_upstream_node_once(chain, read):
    """Each node's integrity is worked out once per read, and its dependents reuse it: O(n), not O(n^2)."""
    with counting_upstream_visits() as visits:
        read(chain)

    assert 0 < visits.count <= CHAIN, visits.count


def _scaled_dag(root: Path, copies: int):
    """A scaled sample map: `copies` gadgets, each resting on the one before, so the map is deep and wide.

        I<k> (imported, Reference-reviewed) <- A<k> <- B<k> <- D<k> <- E<k> (review-needed) <- F<k>
                                     D<k-1> <-'   '-- C<k> <-'  '-- R<k> (Rejected)
                                         B<k> <- G<k>, I<k> <- H<k> <- J<k> (open claims)
    An open Challenge on B2, B5, ..., the second gadget's I found no longer callable, and A0
    revised and re-Accepted, so the pins on it lag.

    Stands in for the sample proof map fixture of #98 (PR #104) with `copies=n`, which isn't on
    this branch's base yet; it can replace this once both land.
    """
    store = ensure_project(root)
    decide = researcher(store)

    def node(node_id, kind, dependencies, outcome=None):
        create_node(store, node_id=node_id, kind=kind, statement=f"statement of {node_id}", dependencies=dependencies)
        if outcome is not None:
            submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="r", content=f"proof of {node_id}")
        if outcome in ("accept", "reject"):
            decide.decide_acceptance(node_id, outcome)

    for k in range(copies):
        create_node(store, node_id=f"I{k}", kind="imported_result", statement=f"known result {k}", source_locator="doi:10.0000/x", source_version="v1")
        decide.decide_reference_review(f"I{k}")
        node(f"A{k}", "lemma", [f"I{k}"] + ([f"D{k - 1}"] if k else []), "accept")
        node(f"B{k}", "lemma", [f"A{k}"], "accept")
        node(f"C{k}", "claim", [f"A{k}"], "accept")
        node(f"D{k}", "lemma", [f"B{k}", f"C{k}"], "accept")
        node(f"E{k}", "lemma", [f"D{k}"], "submit")
        node(f"F{k}", "claim", [f"E{k}"])
        node(f"G{k}", "claim", [f"B{k}"])
        node(f"H{k}", "claim", [f"I{k}"])
        node(f"J{k}", "claim", [f"H{k}"])
        node(f"R{k}", "claim", [f"D{k}"], "reject")
    for k in range(2, copies, 3):
        open_challenge(store, f"B{k}", opened_by="agent_b", rationale="a hypothesis may be missing")
    if copies > 1:
        decide.decide_reference_review("I1", "no-longer-callable", rationale="the source has a gap")
    # a proof-only revision of A0: B0's and C0's pins now lag its accepted version (#23)
    submit_proof(store, "A0", claimant_id="agent_a", scoping_rationale="r", content="proof of A0, shorter")
    decide.decide_acceptance("A0", "accept")
    return store


def _walk_per_node(store, node_id: str) -> str | None:
    """The derivation before #108: a fresh reachability walk for every node asked about,
    reporting a Challenge over a stale or lagging pin."""
    visited: set[str] = set()
    pending = [node_id]
    found = None
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        if proof_map.has_open_challenge(store, current_id):
            return "challenged"
        node = proof_map.get_node(store, current_id)
        if node is None:
            continue
        if node.kind.value == "imported_result" and proof_map._no_longer_callable(store, current_id):
            return "challenged"
        for dependency_id in node.dependencies:
            pin = proof_map.get_dependency_pin(store, current_id, dependency_id)
            if pin is not None and (not proof_map.dependency_pin_is_current(store, pin) or proof_map.dependency_pin_lags(store, pin)):
                found = "stale"
            pending.append(dependency_id)
    return found


def _axes(store, node) -> tuple:
    imported = node.kind.value == "imported_result"
    return (
        get_workflow_state(store, node.id),
        get_blocked_reason(store, node.id),
        get_reference_review_state(store, node.id) if imported else get_acceptance_state(store, node.id),
        get_integrity_state(store, node.id),
    )


def test_the_one_pass_derives_exactly_what_a_walk_per_node_does(tmp_path: Path, monkeypatch):
    store = _scaled_dag(tmp_path, copies=4)

    with read_scope():
        one_pass = {node.id: _axes(store, node) for node in list_nodes(store)}
        frontier = [node.id for node in get_frontier(store)]

    with monkeypatch.context() as patched:
        patched.setattr(proof_map, "_upstream_cause", _walk_per_node)
        per_node = {node.id: _axes(store, node) for node in list_nodes(store)}  # no scope: nothing shared
        per_node_frontier = [node.id for node in get_frontier(store)]

    assert one_pass == per_node
    assert frontier == per_node_frontier
    # the scaled map exercises every value the pass derives
    assert {axes[3] for axes in one_pass.values()} == {"current", "potentially-stale", "challenged"}
    assert {axes[1] for axes in one_pass.values()} >= {None, "not-accepted", "dependency-challenged", "dependency-stale", "dependency-not-callable"}


def test_a_dependency_cycle_is_answered_by_plain_reachability(tmp_path: Path):
    """No service makes a cycle, but a hand-edited map may have one: the pass must still end, and agree."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="bad", kind="imported_result", statement="withdrawn", source_locator="doi:10.0000/y", source_version="v1")
    researcher(store).decide_reference_review("bad", "no-longer-callable", rationale="gap")
    create_node(store, node_id="a", kind="claim", statement="a")
    create_node(store, node_id="b", kind="claim", statement="b", dependencies=["a"])
    create_node(store, node_id="c", kind="claim", statement="c", dependencies=["bad"])
    a = proof_map.get_node(store, "a")
    storage.update_proof_map_node(store, a.model_copy(update={"dependencies": ["b"]}))  # a <- b <- a

    with read_scope():
        assert proof_map._is_downstream_of_challenge_or_stale_pin(store, "b") is False
        assert proof_map._is_downstream_of_challenge_or_stale_pin(store, "a") is False

    storage.update_proof_map_node(store, a.model_copy(update={"dependencies": ["b", "c"]}))  # and a <- c <- bad
    with read_scope():
        assert proof_map._is_downstream_of_challenge_or_stale_pin(store, "b") is True
        assert proof_map._is_downstream_of_challenge_or_stale_pin(store, "a") is True


@pytest.mark.skipif(not os.environ.get("PROOF_BENCHMARK"), reason="wall-clock benchmark: set PROOF_BENCHMARK=1")
def test_benchmark_the_frontier_of_a_1000_node_chain(tmp_path: Path, capsys):
    """Records the time; asserts only the visit count, which doesn't depend on the machine."""
    length = 1000
    store = _chain_with_claims(tmp_path, length)

    with counting_upstream_visits() as visits:
        started = time.perf_counter()
        frontier = get_frontier(store)
        elapsed = time.perf_counter() - started

    with capsys.disabled():
        print(f"\n1000-node chain: get_frontier {elapsed:.3f}s, {visits.count} upstream visits, {len(frontier)} on the frontier")
    assert visits.count <= length


# -- Trust rules (ADR-0014): the rule set is read once per read, whatever the map's size ---------------


def test_a_map_read_folds_the_trust_rules_once(tmp_path: Path, review_reads):
    """Every imported result's state consults the rules in force; one page read folds the file once, not per node."""
    from proof_cli.references import ReferenceRecord, ReferenceSourceType
    from proof_cli.storage import import_reference
    ReviewApp = pytest.importorskip("proof_web.server").ReviewApp  # the page (proof-web), when it is installed

    store = ensure_project(tmp_path)
    import_reference(store, ReferenceRecord(id="book", title="A Book", year=2000, source_type=ReferenceSourceType.textbook))
    for k in range(30):
        create_node(store, node_id=f"ref{k}", kind="imported_result", statement=f"result {k}", source_locator=f"Thm {k}", source_version="v1", reference_id="book")
    researcher(store).declare_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="standard textbooks")
    app = ReviewApp(store)
    try:
        review_reads.clear()
        nodes = app.map()["nodes"]
    finally:
        app.close()

    assert all(n["acceptance_state"] == "trusted-by-rule" for n in nodes)
    assert [path.name for path in review_reads].count("trust-rules.jsonl") <= 1
