import threading
from pathlib import Path

import pytest

from proof_cli.domain import ProofMapNodeKind, utc_now
from proof_cli.domain import DependencyPin
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    compute_interface_fingerprint,
    create_node,
    decide_acceptance,
    decide_reference_review,
    dependency_pin_is_current,
    get_acceptance_state,
    get_accepted_interface_fingerprint,
    get_dependency_pin,
    get_frontier,
    get_integrity_state,
    get_node,
    get_reference_review_state,
    get_workflow_state,
    list_candidate_proofs,
    list_dependency_pins,
    list_nodes,
    release_node,
    require_node,
    submit_candidate_proof,
)
from proof_cli.storage import ensure_project, get_active_claim, get_current_candidate_proof, mark_claim_released, read_state
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
        content="## Proof\n\nBy direct computation, ...",
    )

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
            scoping_rationale="scoped correctly", content="proof text",
        )
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
            content="proof text",
        )
    assert exc_info.value.code == "SCOPING_RATIONALE_REQUIRED"


def test_submit_without_active_claim_raises_no_active_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as exc_info:
        submit_candidate_proof(
            store,
            "clm_1",
            claimant_id="agent_a",
            session_id="sess_1",
            scoping_rationale="scoped correctly",
            content="proof text",
        )
    assert exc_info.value.code == "NO_ACTIVE_CLAIM"


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
        content="proof text",
    )

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
        content="v1 attempt",
    )

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    second = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="second attempt",
        content="v2 attempt",
    )

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
        content="proof text",
    )

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
        content="proof text",
    )


def test_new_node_starts_unreviewed(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_decide_acceptance_requires_confirmation(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    with pytest.raises(ProofMapError) as exc_info:
        decide_acceptance(store, "clm_1", "accept", reviewer_id="researcher", rationale="looks right")
    assert exc_info.value.code == "CONFIRMATION_REQUIRED"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_decide_acceptance_invalid_decision_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    with pytest.raises(ProofMapError) as exc_info:
        decide_acceptance(store, "clm_1", "approve", reviewer_id="researcher", confirmed=True)
    assert exc_info.value.code == "INVALID_DECISION"


def test_decide_acceptance_on_nonexistent_node_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        decide_acceptance(store, "does_not_exist", "accept", reviewer_id="researcher", confirmed=True)
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
        decide_acceptance(store, "ref_1", "accept", reviewer_id="researcher", confirmed=True)
    assert exc_info.value.code == "IMMUTABLE_NODE"


def test_accept_sets_acceptance_state_to_accepted(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    record = decide_acceptance(
        store, "clm_1", "accept", reviewer_id="researcher", rationale="checks out", confirmed=True
    )

    assert record.decision.value == "approved"
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_revision_requested_keeps_node_open_for_a_fresh_claim_submit_cycle(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    decide_acceptance(store, "clm_1", "revision-requested", reviewer_id="researcher", confirmed=True)

    assert get_acceptance_state(store, "clm_1") == "unreviewed"
    # same node id, not a new one: a fresh claim/submit cycle is possible
    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    second = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="addressed the reviewer's feedback",
        content="revised proof text",
    )
    assert second.node_id == "clm_1"
    assert second.version == 2


def test_reject_is_permanent_and_never_touches_failed_routes(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)

    before = read_state(store)
    assert "clm_1" not in before.failed_routes

    record = decide_acceptance(
        store, "clm_1", "reject", reviewer_id="researcher", rationale="the argument has a gap", confirmed=True
    )

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
        content="proof text",
    )
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

    record = decide_reference_review(
        store, "ref_1", "reference-review", reviewer_id="researcher", rationale="trustworthy source", confirmed=True
    )

    assert record.kind.value == "reference_review"
    assert get_reference_review_state(store, "ref_1") == "reviewed"
    # acceptance_state is untouched by a Reference review decision
    assert get_acceptance_state(store, "ref_1") == "unreviewed"


def test_decide_reference_review_requires_confirmation(tmp_path: Path):
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
        decide_reference_review(store, "ref_1", "reference-review", reviewer_id="researcher")
    assert exc_info.value.code == "CONFIRMATION_REQUIRED"
    assert get_reference_review_state(store, "ref_1") == "unreviewed"


def test_decide_reference_review_on_non_imported_result_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as exc_info:
        decide_reference_review(store, "clm_1", "reference-review", reviewer_id="researcher", confirmed=True)
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
    decide_reference_review(store, "ref_1", "reference-review", reviewer_id="researcher", confirmed=True)

    with pytest.raises(ProofMapError) as exc_info:
        decide_acceptance(store, "ref_1", "accept", reviewer_id="researcher", confirmed=True)
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
        content="proof text",
    )
    assert get_workflow_state(store, "clm_1") == "review-needed"

    decide_acceptance(store, "clm_1", "revision-requested", reviewer_id="researcher", confirmed=True)
    assert get_workflow_state(store, "clm_1") == "revision-requested"

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    assert get_workflow_state(store, "clm_1") == "claimed"

    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="addressed feedback",
        content="revised proof text",
    )
    assert get_workflow_state(store, "clm_1") == "review-needed"

    decide_acceptance(store, "clm_1", "accept", reviewer_id="researcher", confirmed=True)
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
        content="proof text",
    )
    decide_acceptance(store, "lem_base", "accept", reviewer_id="researcher", confirmed=True)

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

    decide_reference_review(store, "ref_1", "reference-review", reviewer_id="researcher", confirmed=True)

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
    decide_reference_review(store, "ref_1", "reference-review", reviewer_id="researcher", confirmed=True)
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
        content="proof text",
    )
    decide_acceptance(store, "lem_base", "accept", reviewer_id="researcher", confirmed=True)

    frontier_ids = {node.id for node in get_frontier(store)}
    assert frontier_ids == {"lem_base", "clm_open", "clm_blocked"}


def test_compute_interface_fingerprint_ignores_whitespace_differences(tmp_path: Path):
    a = compute_interface_fingerprint("claim", "A  implies   B", ["  A  "])
    b = compute_interface_fingerprint("claim", "A implies B", ["A"])
    assert a == b


def test_compute_interface_fingerprint_differs_for_substantive_change(tmp_path: Path):
    a = compute_interface_fingerprint("claim", "A implies B", ["A"])
    b = compute_interface_fingerprint("claim", "A implies C", ["A"])
    assert a != b

    c = compute_interface_fingerprint("claim", "A implies B", ["A", "B"])
    assert a != c


def _accept_via_full_cycle(store, node_id: str, *, claimant: str = "agent_a", session: str = "sess_1") -> None:
    claim_node(store, node_id, claimant_id=claimant, session_id=session)
    submit_candidate_proof(
        store,
        node_id,
        claimant_id=claimant,
        session_id=session,
        scoping_rationale="scoped correctly",
        content="proof text",
    )
    decide_acceptance(store, node_id, "accept", reviewer_id="researcher", confirmed=True)


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
        content="proof text",
    )
    assert get_accepted_interface_fingerprint(store, "clm_1") is None


def test_interface_fingerprint_persisted_on_candidate_proof_at_accept_time(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A implies B", assumptions=["A"])
    _accept_via_full_cycle(store, "clm_1")

    expected = compute_interface_fingerprint("claim", "A implies B", ["A"])
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
        content="proof text",
    )

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

    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text",
    )

    pin = get_dependency_pin(store, "clm_1", "ref_1")
    assert pin is not None
    assert pin.pinned_version is None
    assert pin.pinned_fingerprint is None


def test_dependency_pin_is_refreshed_not_accumulated_across_submissions(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="first attempt",
        content="v1 text",
    )
    first_pin = get_dependency_pin(store, "clm_1", "lem_base")
    assert first_pin.pinned_version is None  # lem_base isn't accepted yet

    _accept_via_full_cycle(store, "lem_base", claimant="agent_c", session="sess_3")

    decide_acceptance(store, "clm_1", "revision-requested", reviewer_id="researcher", confirmed=True)
    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="second attempt",
        content="v2 text",
    )

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
        content="proof text",
    )
    create_node(store, node_id="clm_1", kind="claim", statement="Depends on base", dependencies=["lem_base"])

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_b",
        session_id="sess_2",
        scoping_rationale="scoped correctly",
        content="proof text",
    )

    pin = get_dependency_pin(store, "clm_1", "lem_base")
    assert pin is not None
    assert pin.pinned_version is None
    assert pin.pinned_fingerprint is None


def test_claim_on_rejected_node_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store)
    decide_acceptance(store, "clm_1", "reject", reviewer_id="researcher", confirmed=True)

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
        scoping_rationale="first attempt", content="v1 text",
    )
    decide_acceptance(store, "clm_1", "revision-requested", reviewer_id="researcher", confirmed=True)

    v1 = get_current_candidate_proof(store, "clm_1")
    assert v1.review_record_id is not None

    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")
    submit_candidate_proof(
        store, "clm_1", claimant_id="agent_b", session_id="sess_2",
        scoping_rationale="second attempt", content="v2 text",
    )

    v2 = get_current_candidate_proof(store, "clm_1")
    assert v2.review_record_id is None
    assert get_workflow_state(store, "clm_1") == "review-needed"
