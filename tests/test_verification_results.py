from pathlib import Path

from proof_cli.blockers import add_blocker, list_blockers
from proof_cli.domain import BlockerRecord, BlockerStatus, ProofObligation, ProofObligationStatus, TheoremContract, TheoremStatus, TrustLevel, TheoremProvenanceKind, TheoremReviewState
from proof_cli.obligations import add_obligation, list_obligations
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
from proof_cli.verification_results import VerificationResultRecord, list_verification_results, record_verification_result


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


def test_record_verification_result_strengthens_state_and_resolves_blocker(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    store_contract(store, _contract())
    add_obligation(store, _obligation())
    add_blocker(store, _blocker())
    note_unresolved_trust_call(store, "thm_bridge")

    fragment = _fragment()
    result = _result(fragment).accept(notes="accepted after stronger checking")

    record = record_verification_result(store, fragment, result)
    state = load_state(store)
    contract = get_contract(store, "thm_bridge")
    obligations = list_obligations(store)
    blockers = list_blockers(store)
    summary = summarize_state(store)
    snapshot = build_snapshot(store, handoff_note="resume after accepted machine check")

    assert record.effect == "strengthening"
    assert record.result.id == result.id
    assert any(entry.startswith("verification_result:") for entry in state.session_history)
    assert state.unresolved_trust_sensitive_calls == []
    assert contract is not None
    assert record.summary() in contract.local_usage_notes
    assert obligations[0].status == ProofObligationStatus.closed
    assert blockers[0].status == BlockerStatus.resolved
    assert any(reference == f"supporting_ref:{result.id}" for reference in blockers[0].related_contracts)
    assert summary["verification_result_summaries"] == [record.summary()]
    assert summary["verification_results"][0]["review_status"] == VerificationReviewStatus.accepted_after_review.value
    assert summary["verification_results"][0]["result_status"] == VerificationFragmentStatus.machine_checked.value
    assert record.summary() in snapshot.validated_results


def test_record_verification_result_weakens_state_and_keeps_blocker_active(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    store_contract(store, _contract())
    add_obligation(store, _obligation())
    add_blocker(store, _blocker())

    fragment = _fragment(status=VerificationFragmentStatus.stale_after_change)
    result = _result(fragment).reject(notes="reviewer rejected the stale machine-check result")

    record = record_verification_result(store, fragment, result)
    state = load_state(store)
    blockers = list_blockers(store)
    obligations = list_obligations(store)
    summary = summarize_state(store)

    assert record.effect == "weakening"
    assert state.unresolved_trust_sensitive_calls == ["thm_bridge"]
    assert blockers[0].status == BlockerStatus.active
    assert any(entry.startswith("verification:blk_bridge:") for entry in state.failed_routes)
    assert obligations[0].status == ProofObligationStatus.blocked
    assert summary["verification_results"][0]["review_status"] == VerificationReviewStatus.rejected_by_human.value
    assert summary["verification_results"][0]["result_status"] == VerificationFragmentStatus.stale_after_change.value
    assert "verification:" in blockers[0].description
    assert list_verification_results(store)[0].result.id == result.id
