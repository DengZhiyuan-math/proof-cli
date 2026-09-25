import threading
from pathlib import Path

import pytest

from proof_cli.domain import ProofMapNodeKind, utc_now
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    get_node,
    list_nodes,
    release_node,
    require_node,
)
from proof_cli.storage import ensure_project, get_active_claim, mark_claim_released


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
    assert exc_info.value.details["claimant_id"] == "agent_a"
    assert exc_info.value.details["session_id"] == "sess_1"
    assert "claimed_at" in exc_info.value.details


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


def test_non_owner_release_without_force_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    with pytest.raises(ProofMapError) as exc_info:
        release_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")

    assert exc_info.value.code == "NOT_CLAIMANT"
    assert get_active_claim(store, "clm_1") is not None


def test_force_release_without_actor_or_reason_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    with pytest.raises(ProofMapError) as exc_info:
        release_node(store, "clm_1", claimant_id="researcher", session_id="sess_r", force=True)

    assert exc_info.value.code == "FORCE_RELEASE_REQUIRES_REASON"
    assert get_active_claim(store, "clm_1") is not None


def test_force_release_records_audit_trail(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    released = release_node(
        store,
        "clm_1",
        claimant_id="researcher",
        session_id="sess_r",
        force=True,
        actor="researcher",
        reason="agent went unresponsive",
    )

    assert released.released_by == "researcher"
    assert released.release_reason == "agent went unresponsive"
    assert released.claimant_id == "agent_a"  # original claimant is preserved for the audit trail
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


def test_concurrent_release_and_force_release_only_one_wins(tmp_path: Path):
    """Mirrors test_claim_concurrency_exactly_one_succeeds but for release:
    the owner releasing and a researcher force-releasing at the same moment
    must not both succeed and silently overwrite each other's audit trail."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    barrier = threading.Barrier(2)
    results: dict[str, tuple[str, str]] = {}

    def owner_release() -> None:
        barrier.wait()
        try:
            released = release_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
            results["owner"] = ("ok", released.released_by)
        except ProofMapError as exc:
            results["owner"] = ("error", exc.code)

    def force_release() -> None:
        barrier.wait()
        try:
            released = release_node(
                store,
                "clm_1",
                claimant_id="researcher",
                session_id="sess_r",
                force=True,
                actor="researcher",
                reason="stuck",
            )
            results["force"] = ("ok", released.released_by)
        except ProofMapError as exc:
            results["force"] = ("error", exc.code)

    threads = [threading.Thread(target=owner_release), threading.Thread(target=force_release)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    outcomes = [results["owner"][0], results["force"][0]]
    assert outcomes.count("ok") == 1
    assert outcomes.count("error") == 1
    assert get_active_claim(store, "clm_1") is None
