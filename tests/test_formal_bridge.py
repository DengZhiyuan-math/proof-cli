from __future__ import annotations

from proof_cli.domain import ProofObligation, ProofObligationStatus, TheoremContract, TheoremStatus
from proof_cli.formal_bridge import (
    FormalBridgeProofStep,
    FormalBridgeTranslationFailure,
    machine_check_trace,
    translate_proof_obligation,
    translate_proof_step,
    translate_selection,
    translate_theorem_contract,
)
from proof_cli.verification_ir import (
    VerificationArtifact,
    VerificationFragmentStatus,
    VerificationSourceKind,
    VerificationTranslationStatus,
)


def _theorem_contract() -> TheoremContract:
    return TheoremContract(
        id="thm_bridge",
        name="Bridge theorem",
        statement="forall x, P x -> Q x",
        assumptions=["A", "B"],
        exports=["Q"],
        status=TheoremStatus.verified,
        dependencies=["thm_lemma", "ext_reference"],
        notes="bridge theorem contract",
    )


def _obligation() -> ProofObligation:
    return ProofObligation(
        id="obl_bridge",
        goal_statement="show the bridge condition",
        source_step_id="step_apply_bridge",
        required_for="thm_bridge",
        status=ProofObligationStatus.blocked,
        blocking_reason="standard step requires an explicit side condition",
        dependencies=["thm_lemma", "obl_support"],
    )


def _step() -> FormalBridgeProofStep:
    return FormalBridgeProofStep(
        id="step_apply_bridge",
        statement="standard bridge step from A to B",
        theorem_id="thm_bridge",
        goal_id="goal_main",
        assumptions=["A"],
        dependencies=["thm_bridge", "obl_bridge"],
        side_conditions=["domain is inhabited"],
        fragile=True,
        notes="fragile theorem application escalated for machine checking",
        route_id="route_1",
    )


def test_translate_theorem_contract_preserves_provenance_and_dependencies() -> None:
    translation = translate_theorem_contract(_theorem_contract(), project_id="proj_1", route_id="route_contract")

    assert translation.ok is True
    fragment = translation.fragment
    assert fragment is not None
    assert fragment.source_type == VerificationSourceKind.theorem_contract
    assert fragment.source_id == "thm_bridge"
    assert fragment.scope.project_id == "proj_1"
    assert fragment.scope.theorem_id == "thm_bridge"
    assert fragment.scope.route_id == "route_contract"
    assert fragment.provenance.source_id == "thm_bridge"
    assert fragment.provenance.source_scope == fragment.scope
    assert fragment.provenance.derived_from_ids == ["thm_bridge", "thm_lemma", "ext_reference"]
    assert [assumption.statement for assumption in fragment.assumptions] == ["A", "B"]
    assert fragment.quantified_goals[0].statement == "forall x, P x -> Q x"
    assert [dep.dependency_id for dep in fragment.dependency_versions] == ["thm_lemma", "ext_reference"]
    assert fragment.status == VerificationFragmentStatus.queued_for_verification
    assert fragment.translation_status == VerificationTranslationStatus.translated


def test_translate_proof_obligation_records_blocking_reason_as_explicit_side_condition() -> None:
    translation = translate_proof_obligation(_obligation(), project_id="proj_1", theorem_id="thm_bridge")

    assert translation.ok is True
    fragment = translation.fragment
    assert fragment is not None
    assert fragment.source_type == VerificationSourceKind.proof_obligation
    assert fragment.scope.obligation_id == "obl_bridge"
    assert fragment.scope.theorem_id == "thm_bridge"
    assert fragment.quantified_goals[0].statement == "show the bridge condition"
    assert fragment.side_conditions[0].statement == "standard step requires an explicit side condition"
    assert fragment.provenance.derived_from_ids == ["obl_bridge", "thm_lemma", "obl_support", "step_apply_bridge"]
    assert [assumption.statement for assumption in fragment.assumptions] == ["thm_lemma", "obl_support"]
    assert fragment.theorem_applications[0].fragile is True
    assert fragment.theorem_applications[0].statement == "show the bridge condition"


def test_translate_fragile_proof_step_expands_standard_reasoning_into_machine_checkable_form() -> None:
    translation = translate_proof_step(_step(), project_id="proj_1")

    assert translation.ok is True
    fragment = translation.fragment
    assert fragment is not None
    assert fragment.source_type == VerificationSourceKind.proof_step
    assert fragment.scope.proof_step_id == "step_apply_bridge"
    assert fragment.scope.goal_id == "goal_main"
    assert fragment.provenance.source_label == "fragile theorem application escalated for machine checking"
    assert fragment.provenance.derived_from_ids == ["step_apply_bridge", "thm_bridge", "goal_main", "obl_bridge"]
    assert fragment.theorem_applications[0].fragile is True
    assert fragment.theorem_applications[0].assumptions_used == ["A"]
    assert [condition.statement for condition in fragment.side_conditions] == [
        "domain is inhabited",
        "justify the compressed step: standard bridge step from A to B",
    ]
    assert fragment.dependency_versions[0].dependency_id == "step_apply_bridge"


def test_translate_selection_keeps_failures_explicit_and_serializable() -> None:
    failing_step = FormalBridgeProofStep(
        id="step_missing_statement",
        statement="",
        theorem_id="thm_bridge",
        goal_id="goal_main",
        dependencies=["thm_bridge"],
        notes="missing statement should be reported explicitly",
    )

    batch = translate_selection(
        [_theorem_contract(), _obligation(), _step(), failing_step],
        project_id="proj_1",
        route_id="route_batch",
    )

    assert len(batch.fragments) == 3
    assert len(batch.failures) == 1
    failure = batch.failures[0]
    assert isinstance(failure, FormalBridgeTranslationFailure)
    assert failure.source_kind == VerificationSourceKind.proof_step
    assert failure.source_id == "step_missing_statement"
    assert failure.provenance.source_scope is not None
    assert failure.provenance.source_scope.proof_step_id == "step_missing_statement"
    assert failure.provenance.source_scope.route_id == "route_batch"
    assert failure.reason == "proof step is missing a statement"
    assert "statement" in failure.lossy_fields

    reloaded = FormalBridgeTranslationFailure.model_validate_json(failure.model_dump_json())
    assert reloaded == failure


def test_machine_check_trace_links_back_to_fragment_and_is_serializable() -> None:
    fragment = translate_theorem_contract(_theorem_contract(), project_id="proj_1").fragment
    assert fragment is not None

    trace = machine_check_trace(fragment, backend="lean4", summary="machine check succeeded")
    reloaded = VerificationArtifact.model_validate_json(trace.model_dump_json())

    assert reloaded == trace
    assert trace.uri == f"verification://{fragment.id}/lean4"
    assert trace.kind == "machine-check-trace"
