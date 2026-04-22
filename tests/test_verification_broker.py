from __future__ import annotations

from proof_cli.verification_broker import (
    VerificationBackendCapability,
    VerificationBackendCategory,
    VerificationBroker,
    VerificationBrokerDecision,
    build_default_verification_broker,
    default_backend_adapters,
    route_verification_fragment,
)
from proof_cli.verification_ir import (
    VerificationAssumption,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationQuantifiedGoal,
    VerificationScope,
    VerificationSideCondition,
    VerificationSourceKind,
    VerificationTheoremApplication,
    VerificationTranslationStatus,
)


def _fragment(
    *,
    source_type: VerificationSourceKind,
    source_id: str,
    statement: str,
    notes: str = "",
    theorem_applications: list[VerificationTheoremApplication] | None = None,
    side_conditions: list[VerificationSideCondition] | None = None,
    assumptions: list[VerificationAssumption] | None = None,
    quantified_goals: list[VerificationQuantifiedGoal] | None = None,
) -> VerificationFragment:
    scope = VerificationScope(project_id="proj_1", theorem_id="thm_main", goal_id="goal_main", route_id="route_1")
    return VerificationFragment(
        source_type=source_type,
        source_id=source_id,
        scope=scope,
        status=VerificationFragmentStatus.queued_for_verification,
        translation_status=VerificationTranslationStatus.translated,
        theorem_applications=theorem_applications or [],
        side_conditions=side_conditions or [],
        assumptions=assumptions or [],
        quantified_goals=quantified_goals or [VerificationQuantifiedGoal(statement=statement)],
        provenance=VerificationProvenance(
            source_kind=source_type,
            source_id=source_id,
            source_label=source_id,
            source_scope=scope,
            derived_from_ids=[source_id],
            machine_path=["inspect fragment", "select backend"],
        ),
        notes=notes,
    )


def test_default_backend_adapters_expose_backend_capabilities() -> None:
    adapters = default_backend_adapters()
    profile = {adapter.category: set(adapter.capabilities) for adapter in adapters}

    assert profile[VerificationBackendCategory.proof_assistant] >= {
        VerificationBackendCapability.proof_search,
        VerificationBackendCapability.trust_sensitive_check,
        VerificationBackendCapability.quantifier_reasoning,
    }
    assert profile[VerificationBackendCategory.smt] >= {
        VerificationBackendCapability.quantifier_reasoning,
        VerificationBackendCapability.arithmetic_reasoning,
    }
    assert profile[VerificationBackendCategory.symbolic] >= {
        VerificationBackendCapability.symbolic_rewriting,
    }
    assert profile[VerificationBackendCategory.lightweight] >= {
        VerificationBackendCapability.lightweight_check,
    }

    round_tripped = [adapter.model_validate_json(adapter.model_dump_json()) for adapter in adapters]
    assert round_tripped == adapters


def test_broker_routes_fragile_theorem_application_to_proof_assistant() -> None:
    fragment = _fragment(
        source_type=VerificationSourceKind.theorem_application,
        source_id="fragile_application",
        statement="forall x, P x -> Q x",
        theorem_applications=[
            VerificationTheoremApplication(
                theorem_id="thm_bridge",
                theorem_name="Bridge theorem",
                statement="apply bridge theorem",
                assumptions_used=["A"],
                side_conditions=["domain is inhabited"],
                fragile=True,
                notes="fragile theorem application",
                reasoning_path=["goal_main", "step_1"],
            )
        ],
        side_conditions=[VerificationSideCondition(statement="domain is inhabited", origin="explicit side condition")],
    )

    broker = build_default_verification_broker()
    routed, decision = broker.route_fragment(fragment)

    assert routed.backend_target == VerificationBackendCategory.proof_assistant.value
    assert routed.status == VerificationFragmentStatus.queued_for_verification
    assert routed.translation_status == VerificationTranslationStatus.pending
    assert decision.backend_target == VerificationBackendCategory.proof_assistant
    assert decision.adapter_id == "proof_assistant.default"
    assert decision.required_capabilities[:2] == [
        VerificationBackendCapability.dependency_sanity,
        VerificationBackendCapability.proof_search,
    ]
    assert VerificationBackendCapability.trust_sensitive_check in decision.matched_capabilities
    assert "proof-assistant" in decision.reason


def test_broker_routes_quantified_arithmetic_obligations_to_smt() -> None:
    fragment = _fragment(
        source_type=VerificationSourceKind.proof_obligation,
        source_id="obl_arith",
        statement="forall n, n + 1 > n",
        quantified_goals=[VerificationQuantifiedGoal(statement="forall n, n + 1 > n")],
        assumptions=[VerificationAssumption(statement="n is a natural number")],
    )

    broker = VerificationBroker()
    decision = broker.select(fragment)

    assert decision.backend_target == VerificationBackendCategory.smt
    assert decision.adapter_id == "smt.default"
    assert decision.required_capabilities == [
        VerificationBackendCapability.dependency_sanity,
        VerificationBackendCapability.quantifier_reasoning,
        VerificationBackendCapability.arithmetic_reasoning,
    ]
    assert "SMT" in decision.reason


def test_broker_routes_rewrite_focused_steps_to_symbolic_and_round_trips_decision() -> None:
    fragment = _fragment(
        source_type=VerificationSourceKind.proof_step,
        source_id="step_rewrite",
        statement="rewrite x + 0 = x",
        notes="rewrite-oriented proof step",
    )

    decision = VerificationBroker().select(fragment)
    reloaded = VerificationBrokerDecision.model_validate_json(decision.model_dump_json())

    assert decision.backend_target == VerificationBackendCategory.symbolic
    assert decision.adapter_id == "symbolic.default"
    assert decision.required_capabilities == [
        VerificationBackendCapability.dependency_sanity,
        VerificationBackendCapability.symbolic_rewriting,
    ]
    assert reloaded == decision


def test_broker_defaults_low_risk_imported_results_to_lightweight_review() -> None:
    fragment = _fragment(
        source_type=VerificationSourceKind.imported_result,
        source_id="imported_result_1",
        statement="catalogued imported result",
        notes="review-only imported result",
    )

    routed, decision = route_verification_fragment(fragment)

    assert routed.backend_target == VerificationBackendCategory.lightweight.value
    assert decision.backend_target == VerificationBackendCategory.lightweight
    assert decision.adapter_id == "lightweight.default"
    assert decision.required_capabilities == [
        VerificationBackendCapability.dependency_sanity,
        VerificationBackendCapability.lightweight_check,
    ]

