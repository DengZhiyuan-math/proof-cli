from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli.blockers import add_blocker, list_blockers
from proof_cli.domain import BlockerRecord, BlockerStatus, ProofObligation, ProofObligationStatus, TheoremContract, TheoremStatus, TrustLevel, TheoremProvenanceKind, TheoremReviewState
from proof_cli.cli import app
from proof_cli.obligations import add_obligation, list_obligations
from proof_cli.proof_map import claim_node, create_node, get_acceptance_state, list_evidence_checks, submit_candidate_proof
from proof_cli.proof_state import build_snapshot, load_state, note_unresolved_trust_call, summarize_state
from proof_cli.storage import ensure_project, get_contract, store_contract
from proof_cli.verification_ir import (
    VerificationArtifact,
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationQuantifiedGoal,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
    VerificationSideCondition,
    VerificationSourceKind,
    VerificationTheoremApplication,
    VerificationTranslationStatus,
)
from proof_cli.verification_results import VERIFY_RUN_CHECKER, VerificationResultRecord, evidence_outcome_for, list_verification_results, record_verification_result


def _contract() -> TheoremContract:
    return TheoremContract(
        id="thm_bridge",
        kind="theorem",
        name="Bridge theorem",
        statement="forall x, P x -> Q x",
        assumptions=["A"],
        exports=["Q"],
        status=TheoremStatus.draft,
        trust_level=TrustLevel.temporary_admit,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.draft,
        dependencies=["thm_lemma"],
    )


def _obligation() -> ProofObligation:
    return ProofObligation(
        id="obl_bridge",
        goal_statement="show the bridge condition",
        required_for="thm_bridge",
        status=ProofObligationStatus.open,
    )


def _blocker() -> BlockerRecord:
    return BlockerRecord(
        id="blk_bridge",
        scope="thm_bridge",
        description="bridge theorem needs machine-check confirmation",
        failure_type="missing_verification",
    )


def _fragment(status: VerificationFragmentStatus = VerificationFragmentStatus.machine_checked) -> VerificationFragment:
    scope = VerificationScope(
        project_id="proj_alpha",
        theorem_id="thm_bridge",
        obligation_id="obl_bridge",
        blocker_id="blk_bridge",
        proof_step_id="step_bridge",
        route_id="route_bridge",
        tags=["phase4", "verification"],
    )
    return VerificationFragment(
        source_type=VerificationSourceKind.proof_step,
        source_id="step_bridge",
        scope=scope,
        ir_version=1,
        status=status,
        translation_status=VerificationTranslationStatus.translated,
        backend_target="lean4",
        quantified_goals=[
            VerificationQuantifiedGoal(
                statement="forall x, P x -> Q x",
                quantifiers=["forall x"],
                free_variables=["x"],
            )
        ],
        theorem_applications=[
            VerificationTheoremApplication(
                theorem_id="thm_bridge",
                theorem_name="Bridge theorem",
                statement="apply bridge theorem after checking side condition",
                assumptions_used=["A"],
                side_conditions=["nonempty domain"],
                fragile=True,
                notes="fragile theorem application escalated for machine checking",
                reasoning_path=["goal_bridge", "step_bridge"],
            )
        ],
        side_conditions=[
            VerificationSideCondition(
                statement="domain is inhabited",
                origin="standard step converted into an explicit side condition",
                satisfied_by=["lemma_inhabited"],
            )
        ],
        dependency_versions=[
            VerificationDependencyVersion(
                dependency_id="thm_bridge",
                version=3,
                kind="theorem_contract",
                digest="sha256:abc123",
            )
        ],
        provenance=VerificationProvenance(
            source_kind=VerificationSourceKind.proof_step,
            source_id="step_bridge",
            source_label="apply bridge theorem",
            source_scope=scope,
            derived_from_ids=["goal_bridge", "step_bridge", "thm_bridge"],
            machine_path=["inspect state", "translate to ir", "run backend"],
            reviewed_by="researcher",
        ),
        notes="escalated from a fragile theorem application",
    )


def _result(fragment: VerificationFragment) -> VerificationResult:
    return VerificationResult(
        fragment_id=fragment.id,
        backend="lean4",
        summary="machine check completed for the bridge fragment",
        artifacts=[
            VerificationArtifact(
                kind="trace",
                uri="file:///tmp/lean4-trace.json",
                description="backend trace for review",
            )
        ],
        metadata={"backend_version": "4.0.0", "check_mode": "proof_fragment"},
    )


def test_verification_result_record_round_trips_with_explicit_status_fields() -> None:
    fragment = _fragment()
    record = VerificationResultRecord(
        result=_result(fragment).accept(notes="reviewed and accepted"),
        result_status=fragment.status,
        review_status=VerificationReviewStatus.accepted_after_review,
        source_kind=fragment.source_type,
        source_id=fragment.source_id,
        scope=fragment.scope,
        theorem_id=fragment.scope.theorem_id,
        obligation_id=fragment.scope.obligation_id,
        blocker_id=fragment.scope.blocker_id,
        proof_step_id=fragment.scope.proof_step_id,
        route_id=fragment.scope.route_id,
        effect="strengthening",
        notes="accepted after review",
    )

    reloaded = VerificationResultRecord.model_validate_json(record.model_dump_json())

    assert reloaded == record
    assert reloaded.result_status == VerificationFragmentStatus.machine_checked
    assert reloaded.review_status == VerificationReviewStatus.accepted_after_review
    assert "machine_checked/accepted_after_review" in reloaded.summary()


@pytest.mark.parametrize("status", [VerificationFragmentStatus.machine_checked, VerificationFragmentStatus.stale_after_change, VerificationFragmentStatus.backend_failed])
def test_a_machine_check_is_recorded_and_changes_nothing_it_names(tmp_path: Path, status) -> None:
    """A checker's output never closes, blocks or resolves anything, and writes to no
    theorem contract, obligation or blocker — not even a note (#27, ADR-0004 point 5)."""
    store = ensure_project(tmp_path)
    store_contract(store, _contract())
    add_obligation(store, _obligation())
    add_blocker(store, _blocker())
    note_unresolved_trust_call(store, "thm_bridge")
    before = (get_contract(store, "thm_bridge"), list_obligations(store), list_blockers(store), load_state(store).unresolved_trust_sensitive_calls, load_state(store).failed_routes)

    fragment = _fragment(status=status)
    result = _result(fragment).accept(notes="accepted after stronger checking")
    record = record_verification_result(store, fragment, result)

    after = (get_contract(store, "thm_bridge"), list_obligations(store), list_blockers(store), load_state(store).unresolved_trust_sensitive_calls, load_state(store).failed_routes)
    assert after == before
    assert list_verification_results(store)[0].result.id == result.id
    assert summarize_state(store)["verification_result_summaries"] == [record.summary()]
    assert record.summary() in build_snapshot(store).validated_results


def test_a_verification_never_reopens_what_a_researcher_resolved(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    store_contract(store, _contract())
    add_obligation(store, _obligation().model_copy(update={"status": ProofObligationStatus.resolved}))
    add_blocker(store, _blocker().model_copy(update={"status": BlockerStatus.resolved}))

    fragment = _fragment(status=VerificationFragmentStatus.backend_failed)
    record_verification_result(store, fragment, _result(fragment))

    assert list_obligations(store)[0].status == ProofObligationStatus.resolved
    assert list_blockers(store)[0].status == BlockerStatus.resolved


# -- a checker's output goes into the advisory Evidence path (#27) ----------------------

@pytest.mark.parametrize(
    "status, outcome",
    [
        (VerificationFragmentStatus.machine_checked, "passed"),
        (VerificationFragmentStatus.backend_failed, "failed"),
        (VerificationFragmentStatus.translation_failed, "error"),
        (VerificationFragmentStatus.stale_after_change, "stale"),
        (VerificationFragmentStatus.queued_for_verification, "inconclusive"),
        # someone's judgment, not the machine's: never a pass or a fail here
        (VerificationFragmentStatus.accepted_after_review, "inconclusive"),
        (VerificationFragmentStatus.rejected_by_human, "inconclusive"),
    ],
)
def test_every_machine_check_status_maps_to_an_evidence_outcome(status, outcome) -> None:
    assert evidence_outcome_for(status).value == outcome


def test_verify_run_records_its_outcome_as_an_evidence_check_and_decides_nothing(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="show the bridge condition")
    token = claim_node(store, "lem", claimant_id="agent_a", session_id="s").claim_token
    proof = submit_candidate_proof(store, "lem", claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content="proof", claim_token=token)
    add_obligation(store, _obligation())

    result = CliRunner().invoke(app, ["verify", "run", "obl_bridge", "--candidate-proof", proof.id, "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    (check,) = list_evidence_checks(store, proof.id)
    assert check.run_by == VERIFY_RUN_CHECKER
    assert get_acceptance_state(store, "lem") == "unreviewed"
    assert list_obligations(store)[0].status == ProofObligationStatus.open


def test_verify_run_refuses_an_unknown_candidate_proof_before_running(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    add_obligation(store, _obligation())

    result = CliRunner().invoke(app, ["verify", "run", "obl_bridge", "--candidate-proof", "nope", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "nope" in result.output
    assert list_verification_results(store) == []
