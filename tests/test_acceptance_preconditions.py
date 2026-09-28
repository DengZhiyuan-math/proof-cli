"""Human Review acceptance decisions only apply to a node awaiting review (issue #19)."""

import json
import threading
from pathlib import Path

import pytest

from _researcher import researcher

from proof_cli.collaboration import ReviewRecordKind, list_review_records
from proof_cli.commands import cmd_proof_verify_run
from proof_cli.exchange import export_exchange_bundle, import_exchange_bundle
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    decide_acceptance,
    get_acceptance_state,
    get_workflow_state,
    open_challenge,
    split_node,
)
from proof_cli.storage import ensure_project, get_current_candidate_proof
from proof_cli.theorems import add_theorem
from _proofs import submit_proof



def _submit(store, node_id: str, *, session: str = "sess_1") -> None:
    submit_proof(  # needs no claim (ADR-0010)
        store, node_id, claimant_id="agent_a", session_id=session, scoping_rationale="scoped", content=f"proof text ({session})")


def _awaiting_review(store, node_id: str = "clm_1", **node_fields) -> None:
    create_node(store, node_id=node_id, kind=node_fields.pop("kind", "claim"), statement=f"stmt {node_id}", **node_fields)
    _submit(store, node_id)
    assert get_workflow_state(store, node_id) == "review-needed"


def _decide(store, node_id: str, decision: str):
    return researcher(store).decide_acceptance(node_id, decision)


def _acceptance_records(store, node_id: str):
    return [
        record
        for record in list_review_records(store, object_type="proof_map_node", object_id=node_id)
        if record.kind == ReviewRecordKind.acceptance
    ]


@pytest.mark.parametrize("decision", ["accept", "revision-requested", "reject"])
def test_a_node_with_no_candidate_proof_cannot_be_decided(tmp_path: Path, decision: str):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as exc_info:
        _decide(store, "clm_1", decision)

    assert exc_info.value.code == "NOT_REVIEW_NEEDED"
    assert exc_info.value.details["workflow_state"] == "open"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"
    assert _acceptance_records(store, "clm_1") == []


def test_a_node_under_an_active_claim_cannot_be_decided(tmp_path: Path):
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    _decide(store, "clm_1", "revision-requested")
    claim_node(store, "clm_1", claimant_id="agent_b", session_id="sess_2")

    with pytest.raises(ProofMapError) as exc_info:
        _decide(store, "clm_1", "accept")

    assert exc_info.value.code == "NOT_REVIEW_NEEDED"
    assert exc_info.value.details["workflow_state"] == "claimed"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_a_node_with_unaccepted_dependencies_cannot_be_decided(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_dep", kind="lemma", statement="dependency")
    create_node(store, node_id="clm_1", kind="claim", statement="stmt", dependencies=["lem_dep"])
    _submit(store, "clm_1")
    assert get_workflow_state(store, "clm_1") == "blocked"

    with pytest.raises(ProofMapError) as exc_info:
        _decide(store, "clm_1", "accept")

    assert exc_info.value.code == "NOT_REVIEW_NEEDED"
    assert exc_info.value.details["workflow_state"] == "blocked"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


@pytest.mark.parametrize("first", ["accept", "revision-requested"])
@pytest.mark.parametrize("second", ["accept", "revision-requested", "reject"])
def test_a_second_decision_with_nothing_newly_submitted_is_refused(tmp_path: Path, first: str, second: str):
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    _decide(store, "clm_1", first)
    state_after_first = get_acceptance_state(store, "clm_1")

    with pytest.raises(ProofMapError) as exc_info:
        _decide(store, "clm_1", second)

    assert exc_info.value.code == "NOT_REVIEW_NEEDED"
    assert get_acceptance_state(store, "clm_1") == state_after_first
    assert len(_acceptance_records(store, "clm_1")) == 1


@pytest.mark.parametrize("second", ["accept", "revision-requested", "reject"])
def test_reject_is_terminal(tmp_path: Path, second: str):
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    _decide(store, "clm_1", "reject")

    with pytest.raises(ProofMapError) as exc_info:
        _decide(store, "clm_1", second)

    assert exc_info.value.code == "NODE_REJECTED"
    assert get_acceptance_state(store, "clm_1") == "rejected"
    assert len(_acceptance_records(store, "clm_1")) == 1


def test_revision_requested_then_a_fresh_submission_can_be_decided_again(tmp_path: Path):
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    _decide(store, "clm_1", "revision-requested")
    assert get_workflow_state(store, "clm_1") == "revision-requested"

    _submit(store, "clm_1", session="sess_2")
    assert get_workflow_state(store, "clm_1") == "review-needed"
    _decide(store, "clm_1", "accept")

    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_challenged_accepted_node_can_be_re_decided_after_resubmission(tmp_path: Path):
    """The one sanctioned way an Accepted node gets a new decision: a
    Challenge-driven reclaim and a fresh Candidate proof."""
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    _decide(store, "clm_1", "accept")
    open_challenge(store, "clm_1", opened_by="agent_b", rationale="step 3 looks wrong")
    _submit(store, "clm_1", session="sess_2")
    assert get_workflow_state(store, "clm_1") == "review-needed"

    _decide(store, "clm_1", "reject")

    assert get_acceptance_state(store, "clm_1") == "rejected"


def test_concurrent_decisions_on_one_submission_let_exactly_one_through(tmp_path: Path):
    """The precondition is checked inside the decision's own write
    transaction, so two reviewers racing on one submission can't both win."""
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    signed = [(decision, None) for decision in ("accept", "reject", "accept", "revision-requested")]
    barrier = threading.Barrier(len(signed))
    outcomes: list[str] = []
    lock = threading.Lock()

    def _race(decision: str, _unused) -> None:
        barrier.wait()
        try:
            decide_acceptance(store, "clm_1", decision, reviewer=f"reviewer {decision}")
            outcome = "ok"
        except ProofMapError as exc:
            outcome = exc.code
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=_race, args=pair) for pair in signed]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(outcomes) == len(signed)
    assert outcomes.count("ok") == 1
    assert set(outcomes) - {"ok"} <= {"NODE_REJECTED", "NOT_REVIEW_NEEDED"}
    assert len(_acceptance_records(store, "clm_1")) == 1


# -- no other path writes acceptance_state -------------------------------------


def test_split_promote_verify_and_exchange_import_never_write_acceptance_state(tmp_path: Path):
    store = ensure_project(tmp_path / "local")
    create_node(store, node_id="clm_parent", kind="claim", statement="parent")
    split_node(store, "clm_parent", [{"id": "clm_child", "statement": "child"}])
    assert get_acceptance_state(store, "clm_parent") == "unreviewed"
    assert get_acceptance_state(store, "clm_child") == "unreviewed"

    # promote refuses an unaccepted claim rather than accepting it along the way
    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("clm_child")
    assert exc_info.value.code == "NOT_ACCEPTED"
    assert get_acceptance_state(store, "clm_child") == "unreviewed"

    # the legacy theorem-contract verify path, on a contract sharing the node's id (the trust
    # commands themselves are gone, #37)
    add_theorem(store, theorem_id="clm_child", kind="lemma", name="child", statement="child")
    assert json.loads(cmd_proof_verify_run("clm_child", root=tmp_path / "local"))["machine_check_status"] == "queued_for_verification"
    assert get_acceptance_state(store, "clm_child") == "unreviewed"

    # exchange import of a project where the same node ids are Accepted
    foreign = ensure_project(tmp_path / "foreign")
    create_node(foreign, node_id="clm_foreign", kind="claim", statement="foreign")
    _submit(foreign, "clm_foreign")
    _decide(foreign, "clm_foreign", "accept")
    assert get_acceptance_state(foreign, "clm_foreign") == "accepted"
    import_exchange_bundle(store, export_exchange_bundle(foreign))
    assert get_acceptance_state(store, "clm_foreign") == "unreviewed"


def test_exchange_import_cannot_reopen_a_local_accepted_node_for_review(tmp_path: Path):
    """A hand-made bundle carrying only a newer Candidate proof for a node
    that's Accepted here would otherwise put it back in review-needed with
    no Challenge — a way around the one sanctioned re-decision route."""
    local = ensure_project(tmp_path / "local")
    _awaiting_review(local)
    _decide(local, "clm_1", "accept")

    foreign = ensure_project(tmp_path / "foreign")
    bundle = export_exchange_bundle(foreign)
    v1 = get_current_candidate_proof(local, "clm_1")
    bundle.candidate_proofs = [v1.model_copy(update={"id": "cp_foreign_v2", "version": 2, "review_record_id": None})]

    report = import_exchange_bundle(local, bundle)

    assert any("already exists here" in warning for warning in report.warnings)
    assert get_current_candidate_proof(local, "clm_1").id == v1.id
    assert get_workflow_state(local, "clm_1") == "open"
    with pytest.raises(ProofMapError) as exc_info:
        _decide(local, "clm_1", "revision-requested")
    assert exc_info.value.code == "NOT_REVIEW_NEEDED"
    assert get_acceptance_state(local, "clm_1") == "accepted"


# -- CLI contract ---------------------------------------------------------------


