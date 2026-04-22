from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from .verification_broker import (
    VerificationBackendCategory,
    VerificationBroker,
    build_default_verification_broker,
)
from .verification_ir import (
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationSourceKind,
    VerificationScope,
)


_STATUS_SEVERITY: dict[VerificationFragmentStatus, float] = {
    VerificationFragmentStatus.backend_failed: 1.0,
    VerificationFragmentStatus.translation_failed: 0.95,
    VerificationFragmentStatus.stale_after_change: 0.9,
    VerificationFragmentStatus.rejected_by_human: 0.8,
    VerificationFragmentStatus.machine_checked: 0.65,
    VerificationFragmentStatus.accepted_after_review: 0.45,
    VerificationFragmentStatus.queued_for_verification: 0.6,
}

_SOURCE_SEVERITY: dict[VerificationSourceKind, float] = {
    VerificationSourceKind.theorem_application: 1.0,
    VerificationSourceKind.proof_obligation: 0.82,
    VerificationSourceKind.proof_step: 0.76,
    VerificationSourceKind.theorem_contract: 0.68,
    VerificationSourceKind.imported_result: 0.5,
}

_BACKEND_SUITABILITY: dict[VerificationBackendCategory, float] = {
    VerificationBackendCategory.proof_assistant: 1.0,
    VerificationBackendCategory.smt: 0.86,
    VerificationBackendCategory.symbolic: 0.72,
    VerificationBackendCategory.lightweight: 0.56,
}


def _clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _dedupe(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def _fragment_text(fragment: VerificationFragment) -> str:
    theorem_applications = " ".join(application.statement for application in fragment.theorem_applications)
    quantified_goals = " ".join(goal.statement for goal in fragment.quantified_goals)
    side_conditions = " ".join(condition.statement for condition in fragment.side_conditions)
    assumptions = " ".join(assumption.statement for assumption in fragment.assumptions)
    return " ".join(
        part
        for part in [
            fragment.source_type.value,
            fragment.source_id,
            fragment.notes,
            theorem_applications,
            quantified_goals,
            side_conditions,
            assumptions,
            fragment.provenance.source_label,
        ]
        if part
    ).lower()


def _fragment_severity(fragment: VerificationFragment) -> tuple[float, list[str]]:
    base = _STATUS_SEVERITY.get(fragment.status, 0.5)
    source = _SOURCE_SEVERITY.get(fragment.source_type, 0.5)
    score = (base * 0.65) + (source * 0.35)
    reasons = [
        f"status {fragment.status.value} contributes {base:.2f} severity",
        f"source type {fragment.source_type.value} contributes {source:.2f} severity",
    ]

    if fragment.status in {
        VerificationFragmentStatus.backend_failed,
        VerificationFragmentStatus.translation_failed,
        VerificationFragmentStatus.stale_after_change,
        VerificationFragmentStatus.rejected_by_human,
    }:
        score += 0.08
        reasons.append("fragment is already in a failure or stale state")

    if fragment.source_type == VerificationSourceKind.theorem_application and fragment.theorem_applications:
        score += 0.05
        reasons.append("theorem application fragments are high-value escalation candidates")

    if fragment.source_type == VerificationSourceKind.proof_obligation and fragment.side_conditions:
        score += 0.03
        reasons.append("proof obligations with explicit side conditions tend to hide risk")

    return _clamp(score), reasons


def _fragility_score(fragment: VerificationFragment) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    text = _fragment_text(fragment)

    fragile_applications = [application for application in fragment.theorem_applications if application.fragile]
    if fragile_applications:
        score += 0.58
        reasons.append("fragile theorem application detected")
        if any(application.side_conditions for application in fragile_applications):
            score += 0.08
            reasons.append("fragile theorem application also carries explicit side conditions")

    if fragment.side_conditions:
        score += min(0.32, 0.08 * len(fragment.side_conditions))
        reasons.append(f"{len(fragment.side_conditions)} explicit side condition(s) increase fragility")

    if "fragile" in text or "blocked" in text or "gap" in text or "missing" in text:
        score += 0.12
        reasons.append("fragment text mentions a fragile or incomplete proof shape")

    if fragment.translation_status.value == "translation_failed":
        score += 0.12
        reasons.append("translation failure is a strong fragility signal")

    return _clamp(score), reasons


def _dependency_keys(fragment: VerificationFragment) -> list[str]:
    keys = [
        fragment.id,
        fragment.source_id,
        fragment.scope.theorem_id or "",
        fragment.scope.obligation_id or "",
        fragment.scope.proof_step_id or "",
    ]
    keys.extend(dependency.dependency_id for dependency in fragment.dependency_versions)
    return _dedupe(keys)


def _centrality_score(
    fragment: VerificationFragment,
    dependency_centrality: Mapping[str, float] | None,
) -> tuple[float, list[str]]:
    dependency_centrality = dependency_centrality or {}
    matched: list[float] = []
    matched_keys: list[str] = []
    for key in _dependency_keys(fragment):
        if key in dependency_centrality:
            matched.append(_clamp(dependency_centrality[key]))
            matched_keys.append(key)

    reasons: list[str] = []
    if matched:
        score = max(matched)
        reasons.append(
            f"dependency centrality matched {', '.join(matched_keys)} with peak score {score:.2f}"
        )
        return score, reasons

    dependency_count = len(fragment.dependency_versions)
    if dependency_count:
        score = _clamp(0.18 + (0.11 * dependency_count))
        reasons.append(f"fragment has {dependency_count} tracked dependency version(s)")
        return score, reasons

    reasons.append("fragment has no dependency centrality signal")
    return 0.0, reasons


def _failure_history_score(
    fragment: VerificationFragment,
    failure_history: Mapping[str, int] | None,
) -> tuple[float, list[str]]:
    failure_history = failure_history or {}
    keys = _dependency_keys(fragment)
    keys.extend([fragment.scope.theorem_id or "", fragment.scope.proof_step_id or "", fragment.scope.obligation_id or ""])
    count = max((failure_history.get(key, 0) for key in keys), default=0)
    if count <= 0:
        return 0.0, ["no repeated failure history recorded"]

    score = _clamp(1.0 - (0.5 ** count))
    return score, [f"repeated failure history found {count} time(s)"]


def _backend_suitability(
    fragment: VerificationFragment,
    *,
    broker: VerificationBroker,
) -> tuple[VerificationBackendCategory, float, list[str]]:
    decision = broker.select(fragment)
    score = _BACKEND_SUITABILITY.get(decision.backend_target, 0.5)
    reasons = [f"backend target {decision.backend_target.value} selected by broker"]
    if decision.reason:
        reasons.append(decision.reason)
    return decision.backend_target, score, reasons


class FormalizationRecommendation(BaseModel):
    artifact_type: Literal["formalization_recommendation"] = "formalization_recommendation"
    fragment_id: str
    source_kind: VerificationSourceKind
    source_id: str
    scope: VerificationScope
    rank: int
    total_score: float
    severity_score: float
    fragility_score: float
    dependency_centrality_score: float
    failure_history_score: float
    backend_suitability_score: float
    reason: str
    confidence: float = 0.0
    suggested_backend: str | None = None
    escalation_recommended: bool = True
    manual_override_allowed: bool = True
    review_status: Literal["pending_review", "accepted_after_review", "overridden_by_human"] = "pending_review"
    notes: str = ""
    signals: list[str] = Field(default_factory=list)

    def accept(self, *, notes: str | None = None) -> "FormalizationRecommendation":
        update: dict[str, object] = {"review_status": "accepted_after_review"}
        if notes is not None:
            update["notes"] = notes
        return self.model_copy(update=update)

    def override(self, *, notes: str | None = None) -> "FormalizationRecommendation":
        update: dict[str, object] = {"review_status": "overridden_by_human"}
        if notes is not None:
            update["notes"] = notes
        return self.model_copy(update=update)


def recommend_formalization_candidate(
    fragment: VerificationFragment,
    *,
    dependency_centrality: Mapping[str, float] | None = None,
    failure_history: Mapping[str, int] | None = None,
    broker: VerificationBroker | None = None,
) -> FormalizationRecommendation:
    broker = broker or build_default_verification_broker()
    severity_score, severity_signals = _fragment_severity(fragment)
    fragility_score, fragility_signals = _fragility_score(fragment)
    dependency_centrality_score, centrality_signals = _centrality_score(fragment, dependency_centrality)
    failure_history_score, failure_signals = _failure_history_score(fragment, failure_history)
    backend_target, backend_suitability_score, backend_signals = _backend_suitability(fragment, broker=broker)

    total_score = _clamp(
        (severity_score * 0.32)
        + (fragility_score * 0.26)
        + (dependency_centrality_score * 0.2)
        + (failure_history_score * 0.12)
        + (backend_suitability_score * 0.1)
    )
    confidence = _clamp(
        0.34
        + (0.42 * total_score)
        + (0.06 * int(bool(fragment.theorem_applications)))
        + (0.05 * int(bool(fragment.side_conditions)))
        + (0.04 * int(bool(fragment.dependency_versions)))
    )

    signals = _dedupe(
        [
            *severity_signals,
            *fragility_signals,
            *centrality_signals,
            *failure_signals,
            *backend_signals,
        ]
    )
    reason = "; ".join(signals)
    escalation_recommended = total_score >= 0.6 or severity_score >= 0.85 or fragility_score >= 0.6 or failure_history_score >= 0.75

    return FormalizationRecommendation(
        fragment_id=fragment.id,
        source_kind=fragment.source_type,
        source_id=fragment.source_id,
        scope=fragment.scope,
        rank=0,
        total_score=total_score,
        severity_score=severity_score,
        fragility_score=fragility_score,
        dependency_centrality_score=dependency_centrality_score,
        failure_history_score=failure_history_score,
        backend_suitability_score=backend_suitability_score,
        reason=reason,
        confidence=confidence,
        suggested_backend=backend_target.value,
        escalation_recommended=escalation_recommended,
        signals=signals,
    )


def rank_formalization_candidates(
    fragments: Sequence[VerificationFragment],
    *,
    dependency_centrality: Mapping[str, float] | None = None,
    failure_history: Mapping[str, int] | None = None,
    broker: VerificationBroker | None = None,
) -> list[FormalizationRecommendation]:
    recommendations = [
        recommend_formalization_candidate(
            fragment,
            dependency_centrality=dependency_centrality,
            failure_history=failure_history,
            broker=broker,
        )
        for fragment in fragments
    ]
    recommendations.sort(
        key=lambda recommendation: (
            -recommendation.total_score,
            -recommendation.severity_score,
            -recommendation.fragility_score,
            -recommendation.dependency_centrality_score,
            -recommendation.failure_history_score,
            -recommendation.backend_suitability_score,
            recommendation.fragment_id,
        )
    )
    return [recommendation.model_copy(update={"rank": index}) for index, recommendation in enumerate(recommendations, start=1)]


__all__ = [
    "FormalizationRecommendation",
    "rank_formalization_candidates",
    "recommend_formalization_candidate",
]
