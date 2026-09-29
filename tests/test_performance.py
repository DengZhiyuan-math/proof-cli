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

import proof_cli.reviews as reviews
import proof_cli.storage as storage
from _proofs import submit_proof
from _researcher import researcher
from proof_cli.proof_map import (
    create_node,
    get_acceptance_state,
    get_blocked_reason,
    get_frontier,
    get_integrity_state,
    get_workflow_state,
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
