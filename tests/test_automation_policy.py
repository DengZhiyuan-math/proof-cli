from __future__ import annotations

from proof_cli.automation import AutomationActionType, AutomationPolicyDecision, AutomationRiskLevel
from proof_cli.automation_policy import (
    AutomationBackendAvailability,
    AutomationPolicyRegistry,
    AutomationProjectPhase,
    AutomationTheoremCentrality,
    build_default_policy_registry,
    build_policy_profile,
)


def test_policy_profile_uses_explicit_thresholds_and_risk_axes() -> None:
    profile = build_policy_profile(
        project_id="proj_alpha",
        allowed_actions=[
            AutomationActionType.inspect_state,
            AutomationActionType.execute_task,
            AutomationActionType.publish_reusable_outcome,
        ],
        approval_required_for=[AutomationActionType.execute_task],
        forbidden_actions=[AutomationActionType.publish_reusable_outcome],
        risk_allow_max=AutomationRiskLevel.medium,
        centrality_allow_max=AutomationTheoremCentrality.medium,
        minimum_project_phase_for_auto_allow=AutomationProjectPhase.validation,
        minimum_backend_availability_for_auto_allow=AutomationBackendAvailability.available,
        allow_reversible_only=True,
    )

    allow_decision = profile.decide(
        AutomationActionType.inspect_state,
        risk_level=AutomationRiskLevel.low,
        theorem_centrality=AutomationTheoremCentrality.low,
        project_phase=AutomationProjectPhase.validation,
        backend_availability=AutomationBackendAvailability.trusted,
        reversible=True,
    )
    review_decision = profile.decide(
        AutomationActionType.execute_task,
        risk_level=AutomationRiskLevel.high,
        theorem_centrality=AutomationTheoremCentrality.critical,
        project_phase=AutomationProjectPhase.exploration,
        backend_availability=AutomationBackendAvailability.limited,
        reversible=False,
    )
    deny_decision = profile.decide(
        AutomationActionType.publish_reusable_outcome,
        risk_level=AutomationRiskLevel.low,
        theorem_centrality=AutomationTheoremCentrality.low,
        project_phase=AutomationProjectPhase.validation,
        backend_availability=AutomationBackendAvailability.trusted,
        reversible=True,
    )

    assert profile.project_id == "proj_alpha"
    assert profile.risk_allow_max == AutomationRiskLevel.medium
    assert profile.centrality_allow_max == AutomationTheoremCentrality.medium
    assert profile.minimum_project_phase_for_auto_allow == AutomationProjectPhase.validation
    assert profile.minimum_backend_availability_for_auto_allow == AutomationBackendAvailability.available
    assert allow_decision.decision == AutomationPolicyDecision.allow
    assert allow_decision.matched_rules == ["auto_allow"]
    assert review_decision.decision == AutomationPolicyDecision.requires_review
    assert "approval_required_for" in review_decision.matched_rules
    assert "risk_allow_max" in review_decision.matched_rules
    assert "centrality_allow_max" in review_decision.matched_rules
    assert "minimum_project_phase_for_auto_allow" in review_decision.matched_rules
    assert "minimum_backend_availability_for_auto_allow" in review_decision.matched_rules
    assert "allow_reversible_only" in review_decision.matched_rules
    assert deny_decision.decision == AutomationPolicyDecision.deny


def test_forbidden_actions_are_blocked_explicitly() -> None:
    profile = build_policy_profile(
        forbidden_actions=[AutomationActionType.interrupt],
        allowed_actions=[AutomationActionType.interrupt],
    )

    decision = profile.decide(AutomationActionType.interrupt)

    assert decision.decision == AutomationPolicyDecision.deny
    assert decision.reason == "interrupt is forbidden by policy"
    assert decision.matched_rules == ["forbidden_actions"]


def test_policy_registry_sets_policy_per_project() -> None:
    registry = build_default_policy_registry()
    strict_profile = build_policy_profile(
        name="strict_project_policy",
        project_id="proj_beta",
        allowed_actions=[AutomationActionType.inspect_state],
        approval_required_for=[AutomationActionType.inspect_state],
        minimum_project_phase_for_auto_allow=AutomationProjectPhase.stabilization,
        notes="project specific override",
    )

    updated = registry.register_profile(strict_profile)
    updated = updated.set_project_profile("proj_beta", strict_profile)

    assert registry.resolve("proj_beta").name == "bounded_local_reasoning"
    assert updated.resolve("proj_beta").project_id == "proj_beta"
    assert updated.resolve("proj_beta").name == "strict_project_policy"
    assert updated.resolve("proj_gamma").name == "bounded_local_reasoning"


def test_policy_decision_records_round_trip() -> None:
    profile = build_policy_profile(project_id="proj_gamma")
    decision = profile.decide(
        AutomationActionType.retrieve_assets,
        risk_level=AutomationRiskLevel.low,
        theorem_centrality=AutomationTheoremCentrality.low,
        project_phase=AutomationProjectPhase.validation,
        backend_availability=AutomationBackendAvailability.trusted,
        reversible=True,
    )

    reloaded = decision.model_validate_json(decision.model_dump_json())

    assert reloaded == decision
    assert reloaded.project_id == "proj_gamma"
    assert reloaded.profile_id == profile.id
    assert reloaded.decision == AutomationPolicyDecision.allow
