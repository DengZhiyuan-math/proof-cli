import hashlib
import json
import threading
from pathlib import Path

import pytest

from _researcher import researcher

from proof_cli.domain import ProofMapNodeKind, utc_now
from proof_cli.domain import DependencyPin
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    compute_interface_fingerprint,
    create_node,
    dependency_pin_is_current,
    get_acceptance_state,
    get_accepted_interface_fingerprint,
    get_blocked_reason,
    get_challenge,
    get_dependency_pin,
    get_frontier,
    get_integrity_state,
    get_node,
    get_reference_review_state,
    get_workflow_state,
    has_open_challenge,
    list_candidate_proofs,
    list_challenges,
    list_dependency_pins,
    list_evidence_checks,
    list_nodes,
    open_challenge,
    record_evidence_check,
    release_node,
    require_node,
    split_node,
    submit_candidate_proof,
)
from proof_cli.collaboration import list_review_records
from proof_cli.storage import (
    list_events,
    ensure_project,
    get_active_claim,
    get_current_candidate_proof,
    mark_claim_released,
    read_state,
    upsert_dependency_pin,
)
from proof_cli.vault import read_candidate_proof_frontmatter


def test_create_and_get_node(tmp_path: Path):
    store = ensure_project(tmp_path)

    node = create_node(
        store,
        node_id="thm_main",
        kind=ProofMapNodeKind.theorem,
        statement="A implies B",
        assumptions=["A"],
    )

    assert node.kind == ProofMapNodeKind.theorem
    fetched = get_node(store, "thm_main")
    assert fetched is not None
    assert fetched.statement == "A implies B"
    assert fetched.assumptions == ["A"]


def test_get_node_missing_returns_none(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert get_node(store, "does_not_exist") is None


def test_require_node_missing_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        require_node(store, "does_not_exist")
    assert exc_info.value.code == "NODE_NOT_FOUND"


def test_exactly_one_theorem_node_per_project(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm_one", kind="theorem", statement="First theorem")

    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="thm_two", kind="theorem", statement="Second theorem")
    assert exc_info.value.code == "DUPLICATE_THEOREM"

    # The rejected attempt must not have been persisted.
    assert get_node(store, "thm_two") is None


def test_multiple_lemmas_and_claims_are_allowed(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Lemma one")
    create_node(store, node_id="lem_2", kind="lemma", statement="Lemma two")
    create_node(store, node_id="clm_1", kind="claim", statement="Claim one")

    nodes = list_nodes(store)
    assert {node.id for node in nodes} == {"lem_1", "lem_2", "clm_1"}


def test_creating_duplicate_node_id_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="First attempt")

    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="clm_1", kind="claim", statement="Second attempt")
    assert exc_info.value.code == "NODE_ALREADY_EXISTS"


def test_display_label_has_no_effect_on_kind_or_identity(tmp_path: Path):
    store = ensure_project(tmp_path)
    labeled = create_node(
        store,
        node_id="lem_labeled",
        kind="lemma",
        statement="A labeled lemma",
        display_label="Proposition",
    )
    unlabeled = create_node(
        store,
        node_id="lem_unlabeled",
        kind="lemma",
        statement="An unlabeled lemma",
    )

    assert labeled.kind == unlabeled.kind == ProofMapNodeKind.lemma
    assert labeled.display_label == "Proposition"
    assert unlabeled.display_label == ""


def test_dependencies_are_stored_as_bare_edges(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    node = create_node(
        store,
        node_id="clm_dependent",
        kind="claim",
        statement="Depends on the base lemma",
        dependencies=["lem_base"],
    )
    assert node.dependencies == ["lem_base"]


def test_invalid_kind_raises_proof_map_error_not_a_bare_value_error(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="clm_1", kind="proposition", statement="stmt")
    assert exc_info.value.code == "INVALID_KIND"
    assert get_node(store, "clm_1") is None


def test_dependency_on_nonexistent_node_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        create_node(
            store,
            node_id="clm_1",
            kind="claim",
            statement="Depends on a ghost",
            dependencies=["ghost_node"],
        )
    assert exc_info.value.code == "DEPENDENCY_NOT_FOUND"
    assert get_node(store, "clm_1") is None


def test_claim_unclaimed_node_succeeds(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    claim = claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")


    assert claim.node_id == "clm_1"
    assert claim.claimant_id == "agent_a"
    assert get_active_claim(store, "clm_1") is not None


def test_reclaiming_same_claimant_and_session_is_idempotent(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    first = claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    second = claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")


    assert first.id == second.id


def test_claiming_node_someone_else_holds_fails_with_conflict_details(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")

    assert exc_info.value.code == "CLAIM_CONFLICT"
    assert exc_info.value.details["assignee"] == "agent_a"
    assert exc_info.value.details["node_id"] == "clm_1"
    assert "claimed_at" in exc_info.value.details


def test_a_claim_is_taken_over_only_on_request(tmp_path: Path):
    """A claim is a planning signal (ADR-0010): a stale one is reassigned, not force-released."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    first = claim_node(store, "clm_1", claimant_id="agent_a")

    second = claim_node(store, "clm_1", claimant_id="agent_b", reassign=True)

    assert get_active_claim(store, "clm_1").id == second.id != first.id
    assert get_active_claim(store, "clm_1").claimant_id == "agent_b"
    assert any(event.kind == "proof_map_claim_reassigned" for event in list_events(store))


def test_claiming_nonexistent_node_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "does_not_exist", claimant_id="agent_a", session_id="sess_1")
    assert exc_info.value.code == "NODE_NOT_FOUND"


def test_owner_can_release_their_own_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    released = release_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    assert released.released_by == "agent_a"
    assert get_active_claim(store, "clm_1") is None

    # released, so it can be claimed again by someone else
    claim = claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    assert claim.claimant_id == "agent_b"


def test_anyone_can_clear_a_stale_claim_and_it_is_recorded(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    released = release_node(store, "clm_1", claimant_id="researcher", reason="agent went quiet")

    assert (released.claimant_id, released.released_by, released.release_reason) == ("agent_a", "researcher", "agent went quiet")
    assert get_active_claim(store, "clm_1") is None


def test_releasing_unclaimed_node_raises_no_active_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as exc_info:
        release_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    assert exc_info.value.code == "NO_ACTIVE_CLAIM"


def test_claims_have_no_expiry(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    # No expiry mechanism exists: a second claimant attempting the same node,
    # no matter how much time has notionally passed, still conflicts.
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    assert exc_info.value.code == "CLAIM_CONFLICT"


def test_claim_concurrency_exactly_one_succeeds(tmp_path: Path):
    """A genuine two-connection race, not sequential calls, per the ticket's
    explicit requirement that exclusivity come from the DB constraint."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    barrier = threading.Barrier(2)
    results: dict[str, tuple[str, str]] = {}

    def attempt(claimant_id: str) -> None:
        barrier.wait()
        try:
            claim = claim_node(store, "clm_1", claimant_id=claimant_id, session_id="sess")

            results[claimant_id] = ("ok", claim.claimant_id)
        except ProofMapError as exc:
            results[claimant_id] = ("error", exc.code)

    threads = [
        threading.Thread(target=attempt, args=("agent_a",)),
        threading.Thread(target=attempt, args=("agent_b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    outcomes = [results["agent_a"][0], results["agent_b"][0]]
    assert outcomes.count("ok") == 1
    assert outcomes.count("error") == 1

    loser = "agent_a" if results["agent_a"][0] == "error" else "agent_b"
    assert results[loser][1] == "CLAIM_CONFLICT"

    active = get_active_claim(store, "clm_1")
    assert active is not None
    assert active.claimant_id in {"agent_a", "agent_b"}


def test_mark_claim_released_is_a_no_op_on_an_already_released_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim = claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")


    first = mark_claim_released(store, claim.id, released_by="agent_a", reason="done", released_at=utc_now())
    second = mark_claim_released(store, claim.id, released_by="researcher", reason="force", released_at=utc_now())

    assert first is True
    assert second is False  # the claim was already released; this write must not silently win


def test_concurrent_releases_only_one_wins(tmp_path: Path):
    """Two people clearing the same claim at once: one records the release, the other finds none."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def release(who: str) -> None:
        barrier.wait()
        try:
            release_node(store, "clm_1", claimant_id=who)
            results[who] = "ok"
        except ProofMapError as exc:
            results[who] = exc.code

    threads = [threading.Thread(target=release, args=(who,)) for who in ("agent_a", "researcher")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results.values()) == ["NO_ACTIVE_CLAIM", "ok"]
    assert get_active_claim(store, "clm_1") is None


def test_submit_candidate_proof_writes_vault_file_and_index(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    record = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="This claim is a single algebraic step, no further decomposition needed.",
        content="## Proof\n\nBy direct computation, ...")

    assert record.node_id == "clm_1"
    assert record.version == 1
    assert record.file_path == "proofs/clm_1/v1.md"
    assert record.is_current is True

    vault_file = tmp_path / record.file_path
    assert vault_file.exists()
    text = vault_file.read_text(encoding="utf-8")
    assert "By direct computation" in text
    frontmatter = read_candidate_proof_frontmatter(vault_file)
    assert frontmatter["id"] == record.id
    assert frontmatter["node_id"] == "clm_1"
    assert "single algebraic step" in frontmatter["scoping_rationale"]


def test_submit_with_preexisting_vault_file_raises_proof_map_error_not_file_exists_error(tmp_path: Path):
    """A stray vault file at the next version's path (no matching sqlite row
    — e.g. left over from manual tampering or an interrupted run) must fail
    as a clean ProofMapError, not an uncaught FileExistsError that would
    surface as a raw traceback through the CLI's --json path."""
    from proof_cli.vault import candidate_proof_path

    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    stray_path = candidate_proof_path(store.root, "clm_1", 1)
    stray_path.parent.mkdir(parents=True, exist_ok=True)
    stray_path.write_text("leftover file", encoding="utf-8")

    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(
            store, "clm_1", claimant_id="agent_a", session_id="sess_1",
            scoping_rationale="scoped correctly", content="proof text")
    assert exc_info.value.code == "CANDIDATE_PROOF_VERSION_CONFLICT"


def test_submit_requires_scoping_rationale(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(
            store,
            "clm_1",
            claimant_id="agent_a",
            session_id="sess_1",
            scoping_rationale="   ",
            content="proof text")
    assert exc_info.value.code == "SCOPING_RATIONALE_REQUIRED"


def test_submitting_needs_no_claim_but_a_claimed_node_is_its_holders(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    submit_candidate_proof(store, "clm_1", claimant_id="agent_a", session_id="", scoping_rationale="scoped correctly", content="v1")

    create_node(store, node_id="clm_2", kind="claim", statement="stmt")
    claim_node(store, "clm_2", claimant_id="agent_b")
    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(store, "clm_2", claimant_id="agent_a", session_id="", scoping_rationale="scoped correctly", content="v1")
    assert (exc_info.value.code, exc_info.value.details["assignee"]) == ("NOT_CLAIMANT", "agent_b")


def test_submit_by_non_claimant_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(
            store,
            "clm_1",
            claimant_id="agent_b",
            session_id="sess_2",
            scoping_rationale="scoped correctly",
            content="proof text",
        )
    assert exc_info.value.code == "NOT_CLAIMANT"
    # the rightful claimant's claim must survive a rejected submit attempt
    active = get_active_claim(store, "clm_1")
    assert active is not None
    assert active.claimant_id == "agent_a"


def test_successful_submit_ends_the_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")

    # claim ends automatically; the node reads as review-needed via the
    # closest available signal (no active claim, a pending candidate proof) —
    # the full derived workflow_state axis lands in a later ticket.
    assert get_active_claim(store, "clm_1") is None
    current = get_current_candidate_proof(store, "clm_1")
    assert current is not None
    assert current.review_record_id is None

    # released, so someone else could claim it again
    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
def test_second_submission_creates_v2_alongside_untouched_v1(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    first = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="first attempt",
        content="v1 attempt")

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    second = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="second attempt",
        content="v2 attempt")

    assert first.version == 1
    assert second.version == 2

    v1_path = tmp_path / first.file_path
    v2_path = tmp_path / second.file_path
    assert v1_path.exists() and v2_path.exists()
    assert "v1 attempt" in v1_path.read_text(encoding="utf-8")
    assert "v2 attempt" in v2_path.read_text(encoding="utf-8")

    records = list_candidate_proofs(store, "clm_1")
    assert [r.version for r in records] == [1, 2]
    assert [r.is_current for r in records] == [False, True]

    current = get_current_candidate_proof(store, "clm_1")
    assert current is not None
    assert current.id == second.id


def test_renaming_vault_file_does_not_break_stable_id(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    record = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")

    original_path = tmp_path / record.file_path
    moved_path = tmp_path / "proofs" / "clm_1" / "renamed-by-obsidian.md"
    original_path.rename(moved_path)

    frontmatter = read_candidate_proof_frontmatter(moved_path)
    assert frontmatter["id"] == record.id  # id lives in the file, not derived from its path

    # the SQLite index is the real lookup surface for a review record and is
    # untouched by the rename on disk
    from proof_cli.proof_map import get_candidate_proof

    indexed = get_candidate_proof(store, record.id)
    assert indexed is not None
    assert indexed.id == record.id


def test_submit_on_imported_result_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )

    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(
            store,
            "ref_1",
            claimant_id="agent_a",
            session_id="sess_1",
            scoping_rationale="n/a",
            content="n/a",
        )
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_submit_on_nonexistent_node_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(
            store,
            "does_not_exist",
            claimant_id="agent_a",
            session_id="sess_1",
            scoping_rationale="scoped correctly",
            content="proof text",
        )
    assert exc_info.value.code == "NODE_NOT_FOUND"


def _submitted_claim(store, node_id: str = "clm_1"):
    create_node(store, node_id=node_id, kind="claim", statement="stmt")
    claim_node(store, node_id, claimant_id="agent_a", session_id="sess_1")
    return submit_candidate_proof(
        store,
        node_id,
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")


def test_new_node_starts_unreviewed(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_decide_acceptance_invalid_decision_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_acceptance("clm_1", "approve")
    assert exc_info.value.code == "INVALID_DECISION"


def test_decide_acceptance_on_nonexistent_node_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_acceptance("does_not_exist", "accept")
    assert exc_info.value.code == "NODE_NOT_FOUND"


def test_decide_acceptance_on_imported_result_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_acceptance("ref_1", "accept")
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_accept_sets_acceptance_state_to_accepted(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    record = researcher(store).decide_acceptance("clm_1", "accept", rationale="checks out")

    assert record.decision.value == "approved"
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_revision_requested_keeps_node_open_for_a_fresh_claim_submit_cycle(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    researcher(store).decide_acceptance("clm_1", "revision-requested")

    assert get_acceptance_state(store, "clm_1") == "unreviewed"
    # same node id, not a new one: a fresh claim/submit cycle is possible
    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    second = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="addressed the reviewer's feedback",
        content="revised proof text")
    assert second.node_id == "clm_1"
    assert second.version == 2


def test_reject_is_permanent_and_never_touches_failed_routes(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    before = read_state(store)
    assert "clm_1" not in before.failed_routes

    record = researcher(store).decide_acceptance("clm_1", "reject", rationale="the argument has a gap")

    assert record.decision.value == "rejected"
    assert get_acceptance_state(store, "clm_1") == "rejected"
    # the node and its full history remain queryable
    assert require_node(store, "clm_1") is not None
    assert len(list_candidate_proofs(store, "clm_1")) == 1
    # nothing was written to ProjectState.failed_routes for a node that already exists
    after = read_state(store)
    assert "clm_1" not in after.failed_routes
    assert after.failed_routes == before.failed_routes


def test_no_other_code_path_can_write_acceptance_state(tmp_path: Path):
    """Claiming and submitting are the only other node-lifecycle operations;
    neither one is capable of moving acceptance_state off `unreviewed` — the
    architectural guarantee this ticket exists to establish."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"

    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_create_imported_result_requires_source_locator_and_version(tmp_path: Path):
    store = ensure_project(tmp_path)

    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="ref_1", kind="imported_result", statement="An external theorem")
    assert exc_info.value.code == "IMPORTED_RESULT_REQUIRES_SOURCE"
    assert get_node(store, "ref_1") is None

    with pytest.raises(ProofMapError) as exc_info:
        create_node(
            store,
            node_id="ref_1",
            kind="imported_result",
            statement="An external theorem",
            source_locator="doi:10.1234/example",
        )
    assert exc_info.value.code == "IMPORTED_RESULT_REQUIRES_SOURCE"


def test_create_imported_result_with_source_fields_succeeds(tmp_path: Path):
    store = ensure_project(tmp_path)
    node = create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v2",
        trust_level="external_reference",
    )
    assert node.source_locator == "doi:10.1234/example"
    assert node.source_version == "v2"
    assert node.trust_level.value == "external_reference"


def test_create_imported_result_invalid_trust_level_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        create_node(
            store,
            node_id="ref_1",
            kind="imported_result",
            statement="An external theorem",
            source_locator="doi:10.1234/example",
            source_version="v1",
            trust_level="rock_solid",
        )
    assert exc_info.value.code == "INVALID_TRUST_LEVEL"


def test_claim_on_imported_result_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "ref_1", claimant_id="agent_a", session_id="sess_1")
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_mutating_an_imported_result_in_place_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="Original statement",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )

    with pytest.raises(ProofMapError) as exc_info:
        create_node(
            store,
            node_id="ref_1",
            kind="imported_result",
            statement="A corrected statement",
            source_locator="doi:10.1234/example",
            source_version="v2",
        )
    assert exc_info.value.code == "NODE_ALREADY_EXISTS"

    # the original is untouched by the rejected attempt
    unchanged = get_node(store, "ref_1")
    assert unchanged.statement == "Original statement"
    assert unchanged.source_version == "v1"


def test_source_correction_is_modeled_as_a_new_node_not_an_edit(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_v1",
        kind="imported_result",
        statement="Original statement",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    create_node(store, node_id="clm_dependent", kind="claim", statement="Uses ref_v1", dependencies=["ref_v1"])

    corrected = create_node(
        store,
        node_id="ref_v2",
        kind="imported_result",
        statement="A corrected statement",
        source_locator="doi:10.1234/example",
        source_version="v2",
    )

    assert corrected.id == "ref_v2"
    original = get_node(store, "ref_v1")
    assert original.statement == "Original statement"

    # the existing dependent keeps pointing at the old node until someone
    # deliberately migrates it
    dependent = get_node(store, "clm_dependent")
    assert dependent.dependencies == ["ref_v1"]


def test_decide_reference_review_grants_review_independent_of_acceptance_state(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )

    assert get_reference_review_state(store, "ref_1") == "unreviewed"
    assert get_acceptance_state(store, "ref_1") == "unreviewed"

    record = researcher(store).decide_reference_review("ref_1", "reference-review", rationale="trustworthy source")

    assert record.kind.value == "reference_review"
    assert get_reference_review_state(store, "ref_1") == "reviewed"
    # acceptance_state is untouched by a Reference review decision
    assert get_acceptance_state(store, "ref_1") == "unreviewed"


def test_decide_reference_review_on_non_imported_result_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_reference_review("clm_1", "reference-review")
    assert exc_info.value.code == "NOT_IMPORTED_RESULT"


def test_decide_acceptance_still_rejects_imported_result_after_reference_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    researcher(store).decide_reference_review("ref_1", "reference-review")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_acceptance("ref_1", "accept")
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_workflow_state_open_for_a_fresh_unclaimed_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    assert get_workflow_state(store, "clm_1") == "open"


def test_workflow_state_is_recomputed_across_the_full_lifecycle_not_stored(tmp_path: Path):
    """The ticket's own explicit test: mutate the underlying records and
    re-read workflow_state each time, confirming it's never read off a
    stored field."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    assert get_workflow_state(store, "clm_1") == "open"

    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    assert get_workflow_state(store, "clm_1") == "claimed"

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    assert get_workflow_state(store, "clm_1") == "review-needed"

    researcher(store).decide_acceptance("clm_1", "revision-requested")
    assert get_workflow_state(store, "clm_1") == "revision-requested"

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    assert get_workflow_state(store, "clm_1") == "claimed"

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="addressed feedback",
        content="revised proof text")
    assert get_workflow_state(store, "clm_1") == "review-needed"

    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_workflow_state(store, "clm_1") == "open"
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_workflow_state_blocked_on_unaccepted_local_dependency(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    assert get_workflow_state(store, "clm_1") == "blocked"

    claim_node(store, "lem_base", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "lem_base",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    researcher(store).decide_acceptance("lem_base", "accept")

    assert get_workflow_state(store, "clm_1") == "open"


def test_workflow_state_blocked_on_unreviewed_imported_result_dependency(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on ref_1", dependencies=["ref_1"])

    assert get_workflow_state(store, "clm_1") == "blocked"

    researcher(store).decide_reference_review("ref_1", "reference-review")

    assert get_workflow_state(store, "clm_1") == "open"


def test_workflow_state_for_imported_result_is_always_open_never_claimable(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    assert get_workflow_state(store, "ref_1") == "open"
    researcher(store).decide_reference_review("ref_1", "reference-review")
    assert get_workflow_state(store, "ref_1") == "open"


def test_integrity_state_is_current_by_default(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    assert get_integrity_state(store, "clm_1") == "current"


def test_frontier_lists_only_unclaimed_unblocked_nodes(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_blocked", kind="claim", statement="Blocked claim", dependencies=["lem_base"])
    create_node(store, node_id="clm_open", kind="claim", statement="Open claim")
    create_node(store, node_id="clm_claimed", kind="claim", statement="Claimed claim")
    claim_node(store, "clm_claimed", claimant_id="agent_a", session_id="sess_1")
    frontier_ids = {node.id for node in get_frontier(store)}
    assert frontier_ids == {"lem_base", "clm_open"}

    claim_node(store, "lem_base", claimant_id="agent_b", session_id="sess_2")
    submit_candidate_proof(
        store,
        "lem_base",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="scoped correctly",
        content="proof text")
    researcher(store).decide_acceptance("lem_base", "accept")

    # Accepted leaves the frontier; what it unblocked joins it
    frontier_ids = {node.id for node in get_frontier(store)}
    assert frontier_ids == {"clm_open", "clm_blocked"}

    claim_node(store, "clm_open", claimant_id="agent_c")
    submit_candidate_proof(store, "clm_open", claimant_id="agent_c", session_id="", scoping_rationale="r", content="p")
    create_node(store, node_id="ref_1", kind="imported_result", statement="known", source_locator="doi:x", source_version="v1")
    # awaiting review, and imported results, aren't there to pick up either
    assert {node.id for node in get_frontier(store)} == {"clm_blocked"}


def test_a_blocked_node_cant_be_claimed(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_blocked", kind="claim", statement="Blocked", dependencies=["lem_base"])
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "clm_blocked", claimant_id="agent_a")
    assert exc_info.value.code == "NODE_BLOCKED"


def test_compute_interface_fingerprint_ignores_whitespace_differences(tmp_path: Path):
    a = compute_interface_fingerprint("A  implies   B", ["  A  "])
    b = compute_interface_fingerprint("A implies B", ["A"])
    assert a == b


def test_compute_interface_fingerprint_differs_for_substantive_change(tmp_path: Path):
    a = compute_interface_fingerprint("A implies B", ["A"])
    b = compute_interface_fingerprint("A implies C", ["A"])
    assert a != b

    c = compute_interface_fingerprint("A implies B", ["A", "B"])
    assert a != c


def _accept_via_full_cycle(store, node_id: str, *, claimant: str = "agent_a", session: str = "sess_1") -> None:
    claim_node(store, node_id, claimant_id=claimant, session_id=session)
    submit_candidate_proof(
        store,
        node_id,
        claimant_id=claimant,
        session_id=session,
        scoping_rationale="scoped correctly",
        content="proof text")
    researcher(store).decide_acceptance(node_id, "accept")


def test_interface_fingerprint_is_unset_before_acceptance(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A implies B", assumptions=["A"])
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    assert get_accepted_interface_fingerprint(store, "clm_1") is None


def test_interface_fingerprint_persisted_on_candidate_proof_at_accept_time(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A implies B", assumptions=["A"])
    _accept_via_full_cycle(store, "clm_1")

    expected = compute_interface_fingerprint("A implies B", ["A"])
    fingerprint = get_accepted_interface_fingerprint(store, "clm_1")
    assert fingerprint == expected

    # persisted on the candidate_proof row itself, not recomputed per read
    current_proof = list_candidate_proofs(store, "clm_1")[-1]
    assert current_proof.interface_fingerprint == expected


def test_dependency_pin_for_local_target_records_pinned_version(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_base")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")

    pin = get_dependency_pin(store, "clm_1", "lem_base")
    assert pin is not None
    assert pin.pinned_version == 1
    assert pin.pinned_fingerprint == get_accepted_interface_fingerprint(store, "lem_base")


def test_dependency_pin_for_imported_result_target_has_no_version(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on ref_1", dependencies=["ref_1"])

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")

    pin = get_dependency_pin(store, "clm_1", "ref_1")
    assert pin is not None
    assert pin.pinned_version is None
    assert pin.pinned_fingerprint is None


def test_dependency_pin_is_refreshed_not_accumulated_across_submissions(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="first attempt",
        content="v1 text")
    first_pin = get_dependency_pin(store, "clm_1", "lem_base")
    assert first_pin.pinned_version is None  # lem_base isn't accepted yet

    _accept_via_full_cycle(store, "lem_base", claimant="agent_c", session="sess_3")

    researcher(store).decide_acceptance("clm_1", "revision-requested")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="second attempt",
        content="v2 text")

    second_pin = get_dependency_pin(store, "clm_1", "lem_base")
    assert second_pin.pinned_version == 1
    assert second_pin.id == first_pin.id  # refreshed in place, not a growing history
    assert list_dependency_pins(store, "clm_1") == [second_pin]


def test_dependency_pin_is_current_compares_by_fingerprint_not_version_number(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="A implies B", assumptions=["A"])
    _accept_via_full_cycle(store, "lem_base")
    fingerprint = get_accepted_interface_fingerprint(store, "lem_base")

    # a pin recording a version number that doesn't even exist, but the
    # correct, current fingerprint: still reads as current.
    stale_version_pin = DependencyPin(
        id="pin_test", node_id="clm_x", target_node_id="lem_base", pinned_version=999, pinned_fingerprint=fingerprint
    )
    assert dependency_pin_is_current(store, stale_version_pin) is True

    # the inverse: the "correct" version number but a fingerprint that no
    # longer matches — must read as not current, purely from the fingerprint.
    stale_fingerprint_pin = DependencyPin(
        id="pin_test_2",
        node_id="clm_x",
        target_node_id="lem_base",
        pinned_version=1,
        pinned_fingerprint="0" * 64,
    )
    assert dependency_pin_is_current(store, stale_fingerprint_pin) is False


def test_dependency_pin_is_current_true_for_imported_result_target(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    pin = DependencyPin(id="pin_ref", node_id="clm_x", target_node_id="ref_1", pinned_version=None, pinned_fingerprint=None)
    assert dependency_pin_is_current(store, pin) is True


def test_dependency_pin_is_current_false_when_never_pinned_a_fingerprint(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="A implies B")
    unpinned = DependencyPin(id="pin_none", node_id="clm_x", target_node_id="lem_base", pinned_version=None, pinned_fingerprint=None)
    assert dependency_pin_is_current(store, unpinned) is False


def test_pin_dependencies_leaves_pinned_version_none_for_submitted_but_unaccepted_target(tmp_path: Path):
    """A target with a *current* candidate proof that isn't yet Accepted must
    pin neither a version nor a fingerprint (ADR-0005 Rule 2: a pin captures
    a version that was current AND Accepted)."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    claim_node(store, "lem_base", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "lem_base",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="scoped correctly",
        content="proof text")

    pin = get_dependency_pin(store, "clm_1", "lem_base")
    assert pin is not None
    assert pin.pinned_version is None
    assert pin.pinned_fingerprint is None


def test_claim_on_rejected_node_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)
    researcher(store).decide_acceptance("clm_1", "reject")

    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    assert exc_info.value.code == "NODE_REJECTED"


def test_claim_on_accepted_node_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    _accept_via_full_cycle(store, "clm_1")

    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    assert exc_info.value.code == "NODE_ALREADY_ACCEPTED"

    # the interface fingerprint stays intact — no reclaim ever happened to
    # desync it from the node's still-"accepted" acceptance_state
    assert get_accepted_interface_fingerprint(store, "clm_1") is not None


def test_workflow_state_review_needed_after_reclaim_is_not_masked_by_a_stale_review(tmp_path: Path):
    """A prior revision_requested decision must not read as covering a
    resubmission that happened after it, purely because get_workflow_state
    now keys off the structural review_record_id link rather than wall-clock
    timestamps."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store, "clm_1", claimant_id="agent_a", session_id="sess_1",
        scoping_rationale="first attempt", content="v1 text")
    researcher(store).decide_acceptance("clm_1", "revision-requested")

    v1 = get_current_candidate_proof(store, "clm_1")
    assert v1.review_record_id is not None

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    submit_candidate_proof(
        store, "clm_1", claimant_id="agent_b", session_id="sess_2",
        scoping_rationale="second attempt", content="v2 text")

    v2 = get_current_candidate_proof(store, "clm_1")
    assert v2.review_record_id is None
    assert get_workflow_state(store, "clm_1") == "review-needed"


def _dependent_with_accepted_dependency(store, dependent_id: str = "clm_1", target_id: str = "lem_base"):
    """A dependent whose dependency is already Accepted at submission time,
    so pin_dependencies pins a real (non-None) version + fingerprint."""
    create_node(store, node_id=target_id, kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, target_id)
    create_node(store, node_id=dependent_id, kind="claim", statement="Depends on base", dependencies=[target_id])
    claim_node(store, dependent_id, claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        dependent_id,
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    return get_dependency_pin(store, dependent_id, target_id)


def test_revalidate_dependency_reaffirms_when_fingerprint_unchanged(tmp_path: Path):
    """The target's accepted version advancing past what was pinned, with an
    unchanged interface, isn't reachable end-to-end today — claim_node
    refuses to reclaim an already-Accepted node, so nothing can yet push a
    node past its first accepted version (that path is #25's Challenge
    territory). This ages the pin's version directly, via a real persisted
    row, to simulate that precondition against the real, current fingerprint
    the accept cycle actually computed."""
    store = ensure_project(tmp_path)
    pin = _dependent_with_accepted_dependency(store)
    assert pin.pinned_version == 1

    aged_pin = pin.model_copy(update={"pinned_version": 0})
    upsert_dependency_pin(store, aged_pin)
    assert get_dependency_pin(store, "clm_1", "lem_base").pinned_version == 0

    record = researcher(store).revalidate_dependency("clm_1", "lem_base", rationale="interface unchanged")

    assert record.kind.value == "dependency_revalidation"
    assert record.decision.value == "reaffirmed"

    refreshed = get_dependency_pin(store, "clm_1", "lem_base")
    assert refreshed.pinned_version == 1
    assert refreshed.pinned_fingerprint == get_accepted_interface_fingerprint(store, "lem_base")


def test_revalidate_dependency_never_touches_the_reviewing_nodes_own_acceptance_state(tmp_path: Path):
    store = ensure_project(tmp_path)
    _dependent_with_accepted_dependency(store)
    before = get_acceptance_state(store, "clm_1")

    researcher(store).revalidate_dependency("clm_1", "lem_base")

    assert get_acceptance_state(store, "clm_1") == before == "unreviewed"


def test_revalidate_dependency_rejected_when_fingerprint_changed(tmp_path: Path):
    store = ensure_project(tmp_path)
    _dependent_with_accepted_dependency(store)

    stale_pin = get_dependency_pin(store, "clm_1", "lem_base").model_copy(update={"pinned_fingerprint": "0" * 64})
    upsert_dependency_pin(store, stale_pin)

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).revalidate_dependency("clm_1", "lem_base")
    assert exc_info.value.code == "INTERFACE_CHANGED"


def test_revalidate_dependency_target_not_accepted_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).revalidate_dependency("clm_1", "lem_base")
    assert exc_info.value.code == "TARGET_NOT_ACCEPTED"


def test_revalidate_dependency_without_a_pin_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_base")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).revalidate_dependency("clm_1", "lem_base")
    assert exc_info.value.code == "NO_DEPENDENCY_PIN"


def test_revalidate_dependency_rejects_a_non_dependency(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_base")
    create_node(store, node_id="clm_1", kind="claim", statement="Unrelated claim")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).revalidate_dependency("clm_1", "lem_base")
    assert exc_info.value.code == "NOT_A_DEPENDENCY"


def test_revalidate_dependency_rejects_imported_result_target(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on ref_1", dependencies=["ref_1"])
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).revalidate_dependency("clm_1", "ref_1")
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_revalidate_dependency_pin_write_failure_leaves_no_review_record(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    pin = _dependent_with_accepted_dependency(store)
    aged_pin = pin.model_copy(update={"pinned_version": 0})
    upsert_dependency_pin(store, aged_pin)

    import proof_cli.proof_map as proof_map_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated pin-write failure")

    monkeypatch.setattr(proof_map_module, "upsert_dependency_pin", _boom)

    with pytest.raises(RuntimeError):
        researcher(store).revalidate_dependency("clm_1", "lem_base")

    # neither side of the write took effect
    assert get_dependency_pin(store, "clm_1", "lem_base").pinned_version == 0
    assert not any(
        record.kind is not None and record.kind.value == "dependency_revalidation"
        for record in list_review_records_for_test(store, "clm_1")
    )


def test_revalidate_dependency_review_write_failure_rolls_back_the_pin(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    pin = _dependent_with_accepted_dependency(store)
    aged_pin = pin.model_copy(update={"pinned_version": 0})
    upsert_dependency_pin(store, aged_pin)

    import proof_cli.authority as authority_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated review-write failure")

    # fails after the pin is already written on the transaction: the
    # decision's reviews.jsonl line is the last write before commit
    monkeypatch.setattr(authority_module, "append_entry", _boom)

    with pytest.raises(RuntimeError):
        researcher(store).revalidate_dependency("clm_1", "lem_base")

    # the transaction rolled back the pin — neither write stuck
    assert get_dependency_pin(store, "clm_1", "lem_base").pinned_version == 0
    assert not any(
        record.kind is not None and record.kind.value == "dependency_revalidation"
        and record.decision.value == "reaffirmed"
        for record in list_review_records_for_test(store, "clm_1")
    )
    # and no dangling request either — a `proposed_for_review` record with
    # no matching decision would itself be the "inconsistent state, not a
    # valid intermediate one" ADR-0005 says must never happen
    assert not any(
        record.kind is not None and record.kind.value == "dependency_revalidation"
        for record in list_review_records_for_test(store, "clm_1")
    )


def list_review_records_for_test(store, node_id: str):
    return list_review_records(store, object_type="proof_map_node", object_id=node_id)


def test_open_challenge_requires_no_permission_check(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_1")

    challenge = open_challenge(store, "lem_1", opened_by="any_agent_or_collaborator", rationale="looks fishy")

    assert challenge.target_node_id == "lem_1"
    assert challenge.status.value == "open"
    assert challenge.opened_by == "any_agent_or_collaborator"
    assert has_open_challenge(store, "lem_1") is True


def test_open_challenge_against_unaccepted_node_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Base lemma")

    with pytest.raises(ProofMapError) as exc_info:
        open_challenge(store, "lem_1", opened_by="agent_a")
    assert exc_info.value.code == "TARGET_NOT_ACCEPTED"


def test_open_challenge_against_imported_result_requires_reference_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )

    with pytest.raises(ProofMapError) as exc_info:
        open_challenge(store, "ref_1", opened_by="agent_a")
    assert exc_info.value.code == "TARGET_NOT_REVIEWED"

    researcher(store).decide_reference_review("ref_1", "reference-review")
    challenge = open_challenge(store, "ref_1", opened_by="agent_a")
    assert challenge.target_node_id == "ref_1"


def test_dismiss_challenge_on_already_dismissed_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_1")
    challenge = open_challenge(store, "lem_1", opened_by="agent_a")
    researcher(store).dismiss_challenge(challenge.id)

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).dismiss_challenge(challenge.id)
    assert exc_info.value.code == "CHALLENGE_NOT_OPEN"


def test_challenge_list_filters_by_target_and_status(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Lemma one")
    create_node(store, node_id="lem_2", kind="lemma", statement="Lemma two")
    _accept_via_full_cycle(store, "lem_1")
    _accept_via_full_cycle(store, "lem_2", claimant="agent_c", session="sess_3")

    c1 = open_challenge(store, "lem_1", opened_by="agent_a")
    open_challenge(store, "lem_2", opened_by="agent_b")
    researcher(store).dismiss_challenge(c1.id)

    assert {c.target_node_id for c in list_challenges(store, target_node_id="lem_2")} == {"lem_2"}
    assert {c.target_node_id for c in list_challenges(store, status="open")} == {"lem_2"}
    assert {c.target_node_id for c in list_challenges(store, status="dismissed")} == {"lem_1"}


def test_challenge_never_changes_the_targets_own_acceptance_state(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_1")

    open_challenge(store, "lem_1", opened_by="agent_a")

    assert get_acceptance_state(store, "lem_1") == "accepted"
    assert get_integrity_state(store, "lem_1") == "challenged"


def test_architecture_proving_challenge_propagation_and_clearing(tmp_path: Path):
    """The spec's own scenario: build L, M(->L), N(->M) from persisted
    primitives only; open a Challenge on L; assert L reads `challenged` and
    both M and N read `accepted` + `potentially-stale`, with nothing set
    directly. Dismiss the Challenge and assert every overlay clears
    automatically — nothing to clean up by hand."""
    store = ensure_project(tmp_path)

    create_node(store, node_id="L", kind="lemma", statement="L holds")
    _accept_via_full_cycle(store, "L", claimant="agent_l", session="sess_l")

    create_node(store, node_id="M", kind="lemma", statement="M holds, given L", dependencies=["L"])
    _accept_via_full_cycle(store, "M", claimant="agent_m", session="sess_m")

    create_node(store, node_id="N", kind="claim", statement="N holds, given M", dependencies=["M"])
    _accept_via_full_cycle(store, "N", claimant="agent_n", session="sess_n")

    # baseline: everything current, nothing stale
    assert get_integrity_state(store, "L") == "current"
    assert get_integrity_state(store, "M") == "current"
    assert get_integrity_state(store, "N") == "current"

    challenge = open_challenge(store, "L", opened_by="any_agent", rationale="counterexample found upstream")

    assert get_integrity_state(store, "L") == "challenged"

    assert get_acceptance_state(store, "M") == "accepted"
    assert get_integrity_state(store, "M") == "potentially-stale"

    assert get_acceptance_state(store, "N") == "accepted"
    assert get_integrity_state(store, "N") == "potentially-stale"

    # a fresh, not-yet-accepted node downstream of the Challenge reads
    # blocked with a distinct reason, not conflated with ordinary
    # not-yet-accepted blocking
    create_node(store, node_id="P", kind="claim", statement="P holds, given M", dependencies=["M"])
    assert get_workflow_state(store, "P") == "blocked"
    assert get_blocked_reason(store, "P") == "dependency-challenged"

    # accepted nodes' own workflow state is never dragged back to blocked
    assert get_workflow_state(store, "M") != "blocked"
    assert get_workflow_state(store, "N") != "blocked"

    researcher(store).dismiss_challenge(challenge.id, rationale="false alarm")

    # every overlay clears automatically — nothing cleaned up by hand
    assert get_integrity_state(store, "L") == "current"
    assert get_integrity_state(store, "M") == "current"
    assert get_integrity_state(store, "N") == "current"
    assert get_workflow_state(store, "P") != "blocked"
    assert get_blocked_reason(store, "P") is None


def test_ordinary_not_accepted_dependency_reads_blocked_with_a_different_reason(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    assert get_workflow_state(store, "clm_1") == "blocked"
    assert get_blocked_reason(store, "clm_1") == "not-accepted"


def test_reclaiming_a_challenged_accepted_node_is_permitted(tmp_path: Path):
    """The one sanctioned way to revise and re-Accept an Accepted node:
    open a Challenge against it first, which is what unlocks claim_node's
    otherwise-refused already-Accepted path."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_1")

    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "lem_1", claimant_id="agent_b", session_id="sess_2")
    assert exc_info.value.code == "NODE_ALREADY_ACCEPTED"

    open_challenge(store, "lem_1", opened_by="agent_a", rationale="might be wrong")

    claim = claim_node(store, "lem_1", claimant_id="agent_b", session_id="sess_2")

    assert claim.claimant_id == "agent_b"
    assert get_workflow_state(store, "lem_1") == "claimed"


def test_reaccepting_a_challenged_node_resolves_the_challenge_by_revision(tmp_path: Path):
    """Re-Accepting a revised Candidate proof is itself one of the sanctioned
    ways to resolve a Challenge (ADR-0005 Rule 4) — it must not require a
    separate `challenge dismiss` call afterward."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_1")

    challenge = open_challenge(store, "lem_1", opened_by="agent_a", rationale="might be wrong")
    assert get_integrity_state(store, "lem_1") == "challenged"

    claim_node(store, "lem_1", claimant_id="agent_b", session_id="sess_2")
    submit_candidate_proof(
        store, "lem_1", claimant_id="agent_b", session_id="sess_2",
        scoping_rationale="addressed the concern", content="revised proof")
    researcher(store).decide_acceptance("lem_1", "accept")

    assert has_open_challenge(store, "lem_1") is False
    assert get_challenge(store, challenge.id).status.value == "resolved-by-revision"
    assert get_integrity_state(store, "lem_1") == "current"


def test_reaffirming_reference_review_dismisses_the_challenge(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store, node_id="ref_1", kind="imported_result", statement="An external theorem",
        source_locator="doi:10.1234/example", source_version="v1",
    )
    researcher(store).decide_reference_review("ref_1", "reference-review")

    open_challenge(store, "ref_1", opened_by="agent_a", rationale="source retracted?")
    assert get_integrity_state(store, "ref_1") == "challenged"

    researcher(store).decide_reference_review("ref_1", "reference-review", rationale="still trustworthy")

    assert has_open_challenge(store, "ref_1") is False
    assert get_integrity_state(store, "ref_1") == "current"


def test_get_blocked_reason_matches_get_workflow_state_for_an_already_accepted_node(tmp_path: Path):
    """An already-Accepted node's own dependencies can become unresolved
    later (e.g. one of them gets Challenged) without dragging this node's
    *workflow* state back to `blocked` (ADR-0004). get_blocked_reason must
    agree: it's the documented explanation for get_workflow_state's
    `blocked`, so it must not return a reason when that axis doesn't."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    _accept_via_full_cycle(store, "lem_base")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])
    _accept_via_full_cycle(store, "clm_1")

    open_challenge(store, "lem_base", opened_by="agent_a", rationale="might be wrong")

    assert get_workflow_state(store, "clm_1") != "blocked"
    assert get_blocked_reason(store, "clm_1") is None


def test_stale_pin_reachability_walk_does_not_recurse_on_a_deep_chain(tmp_path: Path):
    """A long-running research project (this tool's explicit use case) can
    build a dependency chain hundreds of nodes deep. The Challenge/stale-pin
    reachability walk must handle that iteratively, not via direct recursion
    that would blow Python's default recursion limit."""
    from proof_cli.proof_map import _is_downstream_of_challenge_or_stale_pin

    store = ensure_project(tmp_path)
    depth = 1500
    create_node(store, node_id="n0", kind="lemma", statement="base")
    for i in range(1, depth):
        create_node(store, node_id=f"n{i}", kind="lemma", statement=f"stmt {i}", dependencies=[f"n{i - 1}"])

    assert _is_downstream_of_challenge_or_stale_pin(store, f"n{depth - 1}") is False


def test_promote_requires_claim_and_accepted(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Already a lemma")
    _accept_via_full_cycle(store, "lem_1")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("lem_1")
    assert exc_info.value.code == "NOT_A_CLAIM"

    create_node(store, node_id="clm_1", kind="claim", statement="Not yet accepted")
    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("clm_1")
    assert exc_info.value.code == "NOT_ACCEPTED"


def test_promote_changes_only_kind(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="clm_1",
        kind="claim",
        statement="A promotable claim",
        assumptions=["A"],
    )
    _accept_via_full_cycle(store, "clm_1")
    before = get_node(store, "clm_1")
    before_proofs = list_candidate_proofs(store, "clm_1")

    promoted = researcher(store).promote_to_lemma("clm_1")

    assert promoted.kind == ProofMapNodeKind.lemma
    assert promoted.id == before.id
    assert promoted.statement == before.statement
    assert promoted.assumptions == before.assumptions
    assert promoted.dependencies == before.dependencies
    assert promoted.created_at == before.created_at

    after = get_node(store, "clm_1")
    assert after.kind == ProofMapNodeKind.lemma
    assert after.statement == before.statement

    # Candidate-proof history is untouched, other than the interface
    # fingerprint deliberately kept in sync with the new kind (see the next test)
    after_proofs = list_candidate_proofs(store, "clm_1")
    assert len(after_proofs) == len(before_proofs)
    for before_proof, after_proof in zip(before_proofs, after_proofs):
        assert after_proof.model_copy(update={"interface_fingerprint": None}) == before_proof.model_copy(
            update={"interface_fingerprint": None}
        )


def test_promote_leaves_the_interface_fingerprint_alone(tmp_path: Path):
    """Promote is a relabel (story 25): kind is not part of the mathematical
    interface, so the fingerprint doesn't change, and a dependent pinning the
    node afterward sees it as current."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A promotable claim")
    _accept_via_full_cycle(store, "clm_1")
    before = get_accepted_interface_fingerprint(store, "clm_1")

    researcher(store).promote_to_lemma("clm_1")

    assert get_accepted_interface_fingerprint(store, "clm_1") == before == compute_interface_fingerprint(
        "A promotable claim", []
    )

    create_node(store, node_id="clm_2", kind="claim", statement="Depends on the promoted lemma", dependencies=["clm_1"])
    claim_node(store, "clm_2", claimant_id="agent_x", session_id="sess_x")
    submit_candidate_proof(
        store,
        "clm_2",
        claimant_id="agent_x",
        session_id="sess_x",
        scoping_rationale="scoped correctly",
        content="proof text")
    pin = get_dependency_pin(store, "clm_2", "clm_1")
    assert dependency_pin_is_current(store, pin) is True


def test_promote_does_not_make_an_existing_dependent_stale(tmp_path: Path):
    """The #22 audit's reproduction: B depends on C and is Accepted *before* C is promoted."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_c", kind="claim", statement="c holds")
    _accept_via_full_cycle(store, "clm_c")
    create_node(store, node_id="lem_b", kind="lemma", statement="b holds", dependencies=["clm_c"])
    _accept_via_full_cycle(store, "lem_b", claimant="agent_b", session="sess_b")
    assert get_integrity_state(store, "lem_b") == "current"

    researcher(store).promote_to_lemma("clm_c")

    assert get_integrity_state(store, "lem_b") == "current"
    assert dependency_pin_is_current(store, get_dependency_pin(store, "lem_b", "clm_c")) is True
    create_node(store, node_id="clm_top", kind="claim", statement="uses b", dependencies=["lem_b"])
    assert get_blocked_reason(store, "clm_top") is None


def _pre_22_fingerprint(kind: str, statement: str, assumptions: list[str]) -> str:
    """The fingerprint as computed before #22, with `kind` inside it — an
    independent re-implementation, so a regression in the src copy can't hide."""
    parts = [kind, " ".join(statement.split()), [" ".join(a.split()) for a in assumptions]]
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_pins_taken_before_22_stay_current(tmp_path: Path):
    """Existing projects store pins whose fingerprints include `kind`. Since
    #35 an Accepted node's own fingerprint is recomputed, kind-free; a
    stored pre-#22 pin of the same statement and assumptions — claim- or
    lemma-kind — is still the same interface, and a different one isn't."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_c", kind="claim", statement="c holds", assumptions=["h"])
    _accept_via_full_cycle(store, "clm_c")
    create_node(store, node_id="clm_b", kind="claim", statement="b holds", dependencies=["clm_c"])
    claim_node(store, "clm_b", claimant_id="agent_b", session_id="sess_b")
    submit_candidate_proof(
        store, "clm_b", claimant_id="agent_b", session_id="sess_b", scoping_rationale="scoped", content="proof")
    pin = get_dependency_pin(store, "clm_b", "clm_c")

    for legacy_kind in ("claim", "lemma"):
        upsert_dependency_pin(store, pin.model_copy(update={"pinned_fingerprint": _pre_22_fingerprint(legacy_kind, "c holds", ["h"])}))
        assert dependency_pin_is_current(store, get_dependency_pin(store, "clm_b", "clm_c")) is True

    upsert_dependency_pin(store, pin.model_copy(update={"pinned_fingerprint": _pre_22_fingerprint("claim", "c holds", ["h", "k"])}))
    assert dependency_pin_is_current(store, get_dependency_pin(store, "clm_b", "clm_c")) is False


def test_a_challenged_node_cannot_be_promoted(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A promotable claim")
    _accept_via_full_cycle(store, "clm_1")
    open_challenge(store, "clm_1", opened_by="agent_b", rationale="step 2 looks wrong")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("clm_1")

    assert exc_info.value.code == "NODE_CHALLENGED"
    assert get_node(store, "clm_1").kind == ProofMapNodeKind.claim


def test_promote_has_no_demote_path(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A promotable claim")
    _accept_via_full_cycle(store, "clm_1")
    researcher(store).promote_to_lemma("clm_1")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("clm_1")
    assert exc_info.value.code == "NOT_A_CLAIM"


def test_promote_on_nonexistent_node_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("does_not_exist")
    assert exc_info.value.code == "NODE_NOT_FOUND"


def test_split_creates_claim_children_with_derived_from(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="A big claim, too large to prove directly")

    children = split_node(
        store,
        "clm_parent",
        [
            {"id": "clm_child_1", "statement": "First sub-claim"},
            {"id": "clm_child_2", "statement": "Second sub-claim"},
        ],
        created_by="agent_a",
    )

    assert {c.id for c in children} == {"clm_child_1", "clm_child_2"}
    for child in children:
        assert child.kind == ProofMapNodeKind.claim
        assert child.derived_from == "clm_parent"
        assert child.created_by == "agent_a"

    parent = get_node(store, "clm_parent")
    assert set(parent.dependencies) == {"clm_child_1", "clm_child_2"}


def test_a_failed_split_leaves_no_child_and_does_not_touch_the_parent(tmp_path: Path):
    # issue #26: an ordinary input conflict partway through used to leave the earlier children behind
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="parent")
    create_node(store, node_id="existing", kind="claim", statement="already here")

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "clm_parent", [{"id": "first", "statement": "a"}, {"id": "existing", "statement": "b"}], created_by="agent_a")

    assert exc_info.value.code == "NODE_ALREADY_EXISTS"
    assert get_node(store, "first") is None
    assert not (tmp_path / "proofs" / "first").exists()
    assert get_node(store, "clm_parent").dependencies == []
    assert (tmp_path / "proofs" / "existing" / "proof.tex").exists()  # someone else's folder is left alone


def test_a_split_repeating_a_child_id_leaves_nothing(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="parent")

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "clm_parent", [{"id": "twin", "statement": "a"}, {"id": "twin", "statement": "b"}], created_by="agent_a")

    assert exc_info.value.code == "NODE_ALREADY_EXISTS"
    assert get_node(store, "twin") is None
    assert not (tmp_path / "proofs" / "twin").exists()
    assert get_node(store, "clm_parent").dependencies == []


def test_splitting_a_node_someone_else_holds_is_refused_unless_reassigned(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="parent")
    claim_node(store, "clm_parent", claimant_id="agent_b")

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "clm_parent", [{"id": "c1", "statement": "a"}], created_by="agent_a")
    assert (exc_info.value.code, exc_info.value.details["assignee"]) == ("NOT_CLAIMANT", "agent_b")
    assert get_node(store, "c1") is None
    assert get_node(store, "clm_parent").dependencies == []

    split_node(store, "clm_parent", [{"id": "c2", "statement": "b"}], created_by="agent_b")  # the holder may
    split_node(store, "clm_parent", [{"id": "c3", "statement": "c"}], created_by="agent_a", reassign=True)

    assert get_node(store, "clm_parent").dependencies == ["c2", "c3"]
    assert get_active_claim(store, "clm_parent").claimant_id == "agent_a"  # taken over though Blocked on c2, which `claim` would refuse
    (event,) = [e for e in list_events(store) if e.kind == "proof_map_claim_reassigned" and e.entity_id == "clm_parent"]
    assert event.payload["previous_claimant_id"] == "agent_b"


def test_split_requires_no_confirmation_argument(tmp_path: Path):
    """Split is ungated — unlike Accept/reject/dismiss/promote, there is no
    `confirmed` parameter to pass at all."""
    import inspect

    assert "confirmed" not in inspect.signature(split_node).parameters


def test_split_leaves_parents_preexisting_dependencies_untouched(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="A pre-existing dependency")
    create_node(
        store, node_id="clm_parent", kind="claim", statement="Depends on lem_base already", dependencies=["lem_base"]
    )

    split_node(store, "clm_parent", [{"id": "clm_child_1", "statement": "A sub-claim"}])

    parent = get_node(store, "clm_parent")
    assert "lem_base" in parent.dependencies
    assert "clm_child_1" in parent.dependencies
    assert len(parent.dependencies) == 2


def test_parent_blocked_until_children_accepted_then_still_needs_own_acceptance(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="A big claim")
    split_node(
        store,
        "clm_parent",
        [
            {"id": "clm_child_1", "statement": "First sub-claim"},
            {"id": "clm_child_2", "statement": "Second sub-claim"},
        ],
    )

    assert get_workflow_state(store, "clm_parent") == "blocked"

    _accept_via_full_cycle(store, "clm_child_1", claimant="agent_1", session="sess_1")
    assert get_workflow_state(store, "clm_parent") == "blocked"  # clm_child_2 still unaccepted

    _accept_via_full_cycle(store, "clm_child_2", claimant="agent_2", session="sess_2")

    # unblocked now that every child is Accepted, but never auto-accepted itself
    assert get_workflow_state(store, "clm_parent") == "open"
    assert get_acceptance_state(store, "clm_parent") == "unreviewed"

    # the parent still needs its own Candidate proof and Acceptance
    claim_node(store, "clm_parent", claimant_id="agent_p", session_id="sess_p")
    submit_candidate_proof(
        store,
        "clm_parent",
        claimant_id="agent_p",
        session_id="sess_p",
        scoping_rationale="the pieces combine",
        content="proof combining the two sub-claims")
    researcher(store).decide_acceptance("clm_parent", "accept")
    assert get_acceptance_state(store, "clm_parent") == "accepted"


def test_split_on_imported_result_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(
        store,
        node_id="ref_1",
        kind="imported_result",
        statement="An external theorem",
        source_locator="doi:10.1234/example",
        source_version="v1",
    )

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "ref_1", [{"id": "clm_child_1", "statement": "A sub-claim"}])
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_split_on_rejected_node_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_parent")
    researcher(store).decide_acceptance("clm_parent", "reject")

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "clm_parent", [{"id": "clm_child_1", "statement": "A sub-claim"}])
    assert exc_info.value.code == "NODE_REJECTED"


def test_split_on_accepted_node_is_refused_and_leaves_its_acceptance(tmp_path: Path):
    """New dependencies would void the signed interface: an Accepted node isn't split (#37)."""
    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_parent")
    researcher(store).decide_acceptance("clm_parent", "accept")

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "clm_parent", [{"id": "clm_child_1", "statement": "A sub-claim"}])
    assert exc_info.value.code == "NODE_ACCEPTED"
    assert get_acceptance_state(store, "clm_parent") == "accepted"
    assert get_node(store, "clm_parent").dependencies == []


def test_split_requires_at_least_one_child(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="A big claim")

    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "clm_parent", [])
    assert exc_info.value.code == "SPLIT_REQUIRES_CHILDREN"


def test_split_on_nonexistent_parent_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        split_node(store, "does_not_exist", [{"id": "clm_child_1", "statement": "A sub-claim"}])
    assert exc_info.value.code == "NODE_NOT_FOUND"


def test_derived_from_distinguishes_a_split_subclaim_from_a_coincidental_lemma(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="A big claim")
    split_node(store, "clm_parent", [{"id": "clm_child_1", "statement": "A sub-claim"}])
    create_node(store, node_id="lem_standalone", kind="lemma", statement="An independently authored lemma")

    assert get_node(store, "clm_child_1").derived_from == "clm_parent"
    assert get_node(store, "lem_standalone").derived_from is None


def test_record_evidence_check_attaches_to_a_specific_candidate_proof(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")

    check = record_evidence_check(store, proof.id, "passed", notes="ran the smt backend", run_by="ci-bot")

    assert check.candidate_proof_id == proof.id
    assert check.outcome.value == "passed"
    assert check.run_by == "ci-bot"
    assert list_evidence_checks(store, proof.id) == [check]


def test_record_evidence_check_accepts_every_outcome_value(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")

    for outcome in ["passed", "failed", "inconclusive", "error", "stale"]:
        check = record_evidence_check(store, proof.id, outcome)
        assert check.outcome.value == outcome


def test_record_evidence_check_invalid_outcome_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")

    with pytest.raises(ProofMapError) as exc_info:
        record_evidence_check(store, proof.id, "definitely-correct")
    assert exc_info.value.code == "INVALID_OUTCOME"


def test_record_evidence_check_requires_no_confirmation(tmp_path: Path):
    """Ungated: an automated checker records its own outcome, no
    `confirmed` parameter exists on this function at all."""
    import inspect

    assert "confirmed" not in inspect.signature(record_evidence_check).parameters


def test_decide_evidence_review_invalid_decision_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")
    check = record_evidence_check(store, proof.id, "passed")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_evidence_review(check.id, "approved")
    assert exc_info.value.code == "INVALID_DECISION"


def test_decide_evidence_review_records_trusted_or_unusable(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")
    check = record_evidence_check(store, proof.id, "passed")

    record = researcher(store).decide_evidence_review(check.id, "trusted", rationale="checked the backend logs")

    assert record.kind.value == "evidence_review"
    assert record.decision.value == "trusted"
    assert record.object_type == "evidence_check"
    assert record.object_id == check.id


def test_evidence_check_and_evidence_review_can_never_flip_acceptance_state(tmp_path: Path):
    """The ticket's own explicit requirement: attempt to flip
    acceptance_state via an Evidence check / evidence_review path and
    assert it's impossible."""
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")

    assert get_acceptance_state(store, "clm_1") == "unreviewed"

    # a glowing, fully-trusted "passed" check changes nothing about
    # acceptance_state — only decide_acceptance can, and nothing here calls it
    check = record_evidence_check(store, proof.id, "passed", notes="all backends agree", run_by="ci-bot")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"

    researcher(store).decide_evidence_review(check.id, "trusted", rationale="fully credible")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"

    # architecturally: evidence_review is recorded against object_type
    # "evidence_check", never "proof_map_node", so get_acceptance_state's
    # own query (object_type="proof_map_node", kind=acceptance) can't see it
    # no matter what decision it records — not just by convention.
    acceptance_records = [
        record
        for record in list_review_records(store, object_type="proof_map_node", object_id="clm_1")
        if record.kind is not None and record.kind.value == "acceptance"
    ]
    assert acceptance_records == []

    # even a "unusable" judgment doesn't retroactively do anything either
    failing_check = record_evidence_check(store, proof.id, "failed")
    researcher(store).decide_evidence_review(failing_check.id, "unusable")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_evidence_check_on_nonexistent_candidate_proof_raises_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        record_evidence_check(store, "does_not_exist", "passed")
    assert exc_info.value.code == "CANDIDATE_PROOF_NOT_FOUND"


def test_decide_evidence_review_on_nonexistent_check_raises_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_evidence_review("does_not_exist", "trusted")
    assert exc_info.value.code == "EVIDENCE_CHECK_NOT_FOUND"


def test_an_old_claim_survives_the_token_columns_removal(tmp_path: Path):
    """A pre-ADR-0010 database has `claims.token_hash`; it goes, the active claim stays."""
    import sqlite3

    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a")
    conn = sqlite3.connect(store.db_path)
    conn.execute("ALTER TABLE claims ADD COLUMN token_hash TEXT")
    conn.execute("UPDATE claims SET token_hash = 'old'")
    conn.commit()
    conn.close()

    assert get_active_claim(store, "clm_1").claimant_id == "agent_a"
    with store.connect() as conn:
        assert "token_hash" not in {row["name"] for row in conn.execute("PRAGMA table_info(claims)")}
