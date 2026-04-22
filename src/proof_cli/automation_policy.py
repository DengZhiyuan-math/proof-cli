from __future__ import annotations

from datetime import datetime
from enum import Enum
import uuid
from typing import Any

from pydantic import BaseModel, Field

from .automation import AutomationActionType, AutomationPolicyDecision, AutomationRiskLevel
from .domain import utc_now


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class AutomationTheoremCentrality(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AutomationProjectPhase(str, Enum):
    exploration = "exploration"
    development = "development"
    validation = "validation"
    stabilization = "stabilization"


class AutomationBackendAvailability(str, Enum):
    unavailable = "unavailable"
    limited = "limited"
    available = "available"
    trusted = "trusted"


_RISK_RANK = {
    AutomationRiskLevel.low: 0,
    AutomationRiskLevel.medium: 1,
    AutomationRiskLevel.high: 2,
    AutomationRiskLevel.trust_sensitive: 3,
}

_CENTRALITY_RANK = {
    AutomationTheoremCentrality.low: 0,
    AutomationTheoremCentrality.medium: 1,
    AutomationTheoremCentrality.high: 2,
    AutomationTheoremCentrality.critical: 3,
}

_PROJECT_PHASE_RANK = {
    AutomationProjectPhase.exploration: 0,
    AutomationProjectPhase.development: 1,
    AutomationProjectPhase.validation: 2,
    AutomationProjectPhase.stabilization: 3,
}

_BACKEND_AVAILABILITY_RANK = {
    AutomationBackendAvailability.unavailable: 0,
    AutomationBackendAvailability.limited: 1,
    AutomationBackendAvailability.available: 2,
    AutomationBackendAvailability.trusted: 3,
}


class AutomationPolicyDecisionRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("policy_decision"))
    profile_id: str
    project_id: str | None = None
    action_type: AutomationActionType
    decision: AutomationPolicyDecision
    reason: str = ""
    risk_level: AutomationRiskLevel = AutomationRiskLevel.low
    theorem_centrality: AutomationTheoremCentrality = AutomationTheoremCentrality.medium
    project_phase: AutomationProjectPhase = AutomationProjectPhase.development
    backend_availability: AutomationBackendAvailability = AutomationBackendAvailability.available
    reversible: bool = True
    matched_rules: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class AutomationPolicyProfile(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("policy"))
    name: str
    project_id: str | None = None
    allowed_actions: list[AutomationActionType] = Field(default_factory=list)
    approval_required_for: list[AutomationActionType] = Field(default_factory=list)
    forbidden_actions: list[AutomationActionType] = Field(default_factory=list)
    risk_allow_max: AutomationRiskLevel = AutomationRiskLevel.medium
    centrality_allow_max: AutomationTheoremCentrality = AutomationTheoremCentrality.medium
    minimum_project_phase_for_auto_allow: AutomationProjectPhase = AutomationProjectPhase.validation
    minimum_backend_availability_for_auto_allow: AutomationBackendAvailability = AutomationBackendAvailability.available
    allow_reversible_only: bool = False
    notes: str = ""

    def decide(
        self,
        action_type: AutomationActionType,
        *,
        risk_level: AutomationRiskLevel = AutomationRiskLevel.low,
        theorem_centrality: AutomationTheoremCentrality = AutomationTheoremCentrality.medium,
        project_phase: AutomationProjectPhase = AutomationProjectPhase.development,
        backend_availability: AutomationBackendAvailability = AutomationBackendAvailability.available,
        reversible: bool = True,
    ) -> AutomationPolicyDecisionRecord:
        reasons: list[str] = []
        matched_rules: list[str] = []

        if action_type in self.forbidden_actions:
            return AutomationPolicyDecisionRecord(
                profile_id=self.id,
                project_id=self.project_id,
                action_type=action_type,
                decision=AutomationPolicyDecision.deny,
                reason=f"{action_type.value} is forbidden by policy",
                risk_level=risk_level,
                theorem_centrality=theorem_centrality,
                project_phase=project_phase,
                backend_availability=backend_availability,
                reversible=reversible,
                matched_rules=["forbidden_actions"],
            )

        if self.allowed_actions and action_type not in self.allowed_actions:
            return AutomationPolicyDecisionRecord(
                profile_id=self.id,
                project_id=self.project_id,
                action_type=action_type,
                decision=AutomationPolicyDecision.deny,
                reason=f"{action_type.value} is not allowed by this policy profile",
                risk_level=risk_level,
                theorem_centrality=theorem_centrality,
                project_phase=project_phase,
                backend_availability=backend_availability,
                reversible=reversible,
                matched_rules=["allowed_actions"],
            )

        if action_type in self.approval_required_for:
            matched_rules.append("approval_required_for")
            reasons.append(f"{action_type.value} requires approval")

        if _RISK_RANK[risk_level] > _RISK_RANK[self.risk_allow_max]:
            matched_rules.append("risk_allow_max")
            reasons.append(f"risk level {risk_level.value} exceeds auto-allow threshold {self.risk_allow_max.value}")

        if _CENTRALITY_RANK[theorem_centrality] > _CENTRALITY_RANK[self.centrality_allow_max]:
            matched_rules.append("centrality_allow_max")
            reasons.append(
                f"theorem centrality {theorem_centrality.value} exceeds auto-allow threshold {self.centrality_allow_max.value}"
            )

        if _PROJECT_PHASE_RANK[project_phase] < _PROJECT_PHASE_RANK[self.minimum_project_phase_for_auto_allow]:
            matched_rules.append("minimum_project_phase_for_auto_allow")
            reasons.append(
                f"project phase {project_phase.value} is below the auto-allow threshold {self.minimum_project_phase_for_auto_allow.value}"
            )

        if _BACKEND_AVAILABILITY_RANK[backend_availability] < _BACKEND_AVAILABILITY_RANK[self.minimum_backend_availability_for_auto_allow]:
            matched_rules.append("minimum_backend_availability_for_auto_allow")
            reasons.append(
                f"backend availability {backend_availability.value} is below the auto-allow threshold {self.minimum_backend_availability_for_auto_allow.value}"
            )

        if self.allow_reversible_only and not reversible:
            matched_rules.append("allow_reversible_only")
            reasons.append("policy only allows reversible actions")

        if reasons:
            return AutomationPolicyDecisionRecord(
                profile_id=self.id,
                project_id=self.project_id,
                action_type=action_type,
                decision=AutomationPolicyDecision.requires_review,
                reason="; ".join(reasons),
                risk_level=risk_level,
                theorem_centrality=theorem_centrality,
                project_phase=project_phase,
                backend_availability=backend_availability,
                reversible=reversible,
                matched_rules=matched_rules,
            )

        return AutomationPolicyDecisionRecord(
            profile_id=self.id,
            project_id=self.project_id,
            action_type=action_type,
            decision=AutomationPolicyDecision.allow,
            reason=f"{action_type.value} is allowed under the current policy profile",
            risk_level=risk_level,
            theorem_centrality=theorem_centrality,
            project_phase=project_phase,
            backend_availability=backend_availability,
            reversible=reversible,
            matched_rules=["auto_allow"],
        )


class AutomationPolicyRegistry(BaseModel):
    default_profile: AutomationPolicyProfile
    project_profiles: dict[str, AutomationPolicyProfile] = Field(default_factory=dict)
    profile_by_name: dict[str, AutomationPolicyProfile] = Field(default_factory=dict)
    notes: str = ""

    def register_profile(self, profile: AutomationPolicyProfile) -> "AutomationPolicyRegistry":
        updated = dict(self.profile_by_name)
        updated[profile.name] = profile
        return self.model_copy(update={"profile_by_name": updated})

    def set_project_profile(self, project_id: str, profile: AutomationPolicyProfile) -> "AutomationPolicyRegistry":
        project_profile = profile.model_copy(update={"project_id": project_id})
        updated_projects = dict(self.project_profiles)
        updated_projects[project_id] = project_profile
        updated_names = dict(self.profile_by_name)
        updated_names[project_profile.name] = project_profile
        return self.model_copy(update={"project_profiles": updated_projects, "profile_by_name": updated_names})

    def resolve(self, project_id: str) -> AutomationPolicyProfile:
        return self.project_profiles.get(project_id, self.default_profile)


def build_policy_profile(
    name: str = "bounded_local_reasoning",
    *,
    project_id: str | None = None,
    allowed_actions: list[AutomationActionType] | None = None,
    approval_required_for: list[AutomationActionType] | None = None,
    forbidden_actions: list[AutomationActionType] | None = None,
    risk_allow_max: AutomationRiskLevel = AutomationRiskLevel.medium,
    centrality_allow_max: AutomationTheoremCentrality = AutomationTheoremCentrality.medium,
    minimum_project_phase_for_auto_allow: AutomationProjectPhase = AutomationProjectPhase.validation,
    minimum_backend_availability_for_auto_allow: AutomationBackendAvailability = AutomationBackendAvailability.available,
    allow_reversible_only: bool = False,
    notes: str = "",
) -> AutomationPolicyProfile:
    return AutomationPolicyProfile(
        name=name,
        project_id=project_id,
        allowed_actions=list(allowed_actions or []),
        approval_required_for=list(approval_required_for or []),
        forbidden_actions=list(forbidden_actions or []),
        risk_allow_max=risk_allow_max,
        centrality_allow_max=centrality_allow_max,
        minimum_project_phase_for_auto_allow=minimum_project_phase_for_auto_allow,
        minimum_backend_availability_for_auto_allow=minimum_backend_availability_for_auto_allow,
        allow_reversible_only=allow_reversible_only,
        notes=notes,
    )


def build_default_policy_registry() -> AutomationPolicyRegistry:
    default_profile = build_policy_profile(
        allowed_actions=[
            AutomationActionType.inspect_state,
            AutomationActionType.retrieve_assets,
            AutomationActionType.check_policy,
            AutomationActionType.generate_plan,
            AutomationActionType.request_review,
            AutomationActionType.execute_task,
            AutomationActionType.record_trace,
            AutomationActionType.publish_reusable_outcome,
            AutomationActionType.rollback,
            AutomationActionType.interrupt,
        ],
        approval_required_for=[
            AutomationActionType.publish_reusable_outcome,
            AutomationActionType.execute_task,
            AutomationActionType.rollback,
        ],
        notes="default bounded supervised automation policy",
    )
    return AutomationPolicyRegistry(default_profile=default_profile)


__all__ = [
    "AutomationBackendAvailability",
    "AutomationPolicyDecisionRecord",
    "AutomationPolicyProfile",
    "AutomationPolicyRegistry",
    "AutomationProjectPhase",
    "AutomationTheoremCentrality",
    "build_default_policy_registry",
    "build_policy_profile",
]
