from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, Field

from .domain_packs import DomainPack
from .retrieval import (
    CrossProjectRetrievalCandidate,
    CrossProjectRetrievalReport,
    CrossProjectSourceKind,
    retrieve_cross_project_assets,
)
from .reusable_assets import ReusableAsset


class CrossProjectRecommendation(BaseModel):
    artifact_type: Literal["cross_project_recommendation"] = "cross_project_recommendation"
    candidate_id: str
    title: str
    source_kind: CrossProjectSourceKind
    source_ref: str
    origin_project_id: str = ""
    rank: int = 0
    total_score: float
    similarity_score: float
    trust_score: float
    prior_usefulness_score: float
    provenance_score: float
    reason: str
    provenance_summary: str = ""
    review_status: Literal["pending_review", "accepted_after_review", "overridden_by_human"] = "pending_review"
    notes: str = ""
    signals: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)

    def accept(self, *, notes: str | None = None) -> "CrossProjectRecommendation":
        update: dict[str, object] = {"review_status": "accepted_after_review"}
        if notes is not None:
            update["notes"] = notes
        return self.model_copy(update=update)

    def override(self, *, notes: str | None = None) -> "CrossProjectRecommendation":
        update: dict[str, object] = {"review_status": "overridden_by_human"}
        if notes is not None:
            update["notes"] = notes
        return self.model_copy(update=update)


class CrossProjectRecommendationReport(BaseModel):
    query: str
    current_project_id: str
    retrieval_report: CrossProjectRetrievalReport
    recommendations: list[CrossProjectRecommendation] = Field(default_factory=list)


def _trust_score(candidate: CrossProjectRetrievalCandidate) -> float:
    return candidate.trust_score


def _provenance_summary(candidate: CrossProjectRetrievalCandidate) -> str:
    details: list[str] = []
    if candidate.origin_project_id:
        details.append(f"origin project {candidate.origin_project_id}")
    if candidate.trust_level:
        details.append(f"trust={candidate.trust_level}")
    if candidate.reuse_status:
        details.append(f"reuse={candidate.reuse_status}")
    if candidate.provenance_reasons:
        details.append(candidate.provenance_reasons[0])
    return "; ".join(details)


def _candidate_reason(candidate: CrossProjectRetrievalCandidate) -> str:
    signals = [*candidate.match_reasons, *candidate.provenance_reasons]
    if candidate.prior_usefulness_score > 0:
        signals.append(f"prior usefulness score {candidate.prior_usefulness_score:.2f} from prior project reuse")
    if candidate.source_kind == CrossProjectSourceKind.domain_pack:
        signals.append("domain pack packages reusable workflow knowledge")
    if candidate.source_kind == CrossProjectSourceKind.shared_domain:
        signals.append("shared-domain asset is eligible for cross-project reuse")
    if candidate.source_kind == CrossProjectSourceKind.project_local:
        signals.append("project-local asset can seed a local proof workflow")
    if candidate.source_kind == CrossProjectSourceKind.prior_project:
        signals.append("prior-project asset preserves cross-project evidence")
    return "; ".join(signal for signal in signals if signal)


def _rank_recommendations(
    candidates: Sequence[CrossProjectRetrievalCandidate],
) -> list[CrossProjectRecommendation]:
    recommendations = []
    for candidate in candidates:
        trust_score = _trust_score(candidate)
        total_score = min(
            1.0,
            (candidate.similarity_score * 0.34)
            + (trust_score * 0.34)
            + (candidate.prior_usefulness_score * 0.18)
            + (candidate.provenance_score * 0.14),
        )
        recommendations.append(
            CrossProjectRecommendation(
                candidate_id=candidate.id,
                title=candidate.title,
                source_kind=candidate.source_kind,
                source_ref=candidate.source_ref,
                origin_project_id=candidate.origin_project_id,
                rank=candidate.rank,
                total_score=total_score,
                similarity_score=candidate.similarity_score,
                trust_score=trust_score,
                prior_usefulness_score=candidate.prior_usefulness_score,
                provenance_score=candidate.provenance_score,
                reason=_candidate_reason(candidate),
                provenance_summary=_provenance_summary(candidate),
                signals=[*candidate.match_reasons, *candidate.provenance_reasons],
                payload=candidate.payload,
            )
        )

    recommendations.sort(
        key=lambda recommendation: (
            -recommendation.total_score,
            -recommendation.trust_score,
            -recommendation.prior_usefulness_score,
            -recommendation.provenance_score,
            -recommendation.similarity_score,
            recommendation.source_kind.value,
            recommendation.title.lower(),
            recommendation.candidate_id,
        )
    )
    return [recommendation.model_copy(update={"rank": index}) for index, recommendation in enumerate(recommendations, start=1)]


def recommend_cross_project_assets(
    *,
    current_project_id: str,
    query: str | None = None,
    current_project_assets: Sequence[ReusableAsset] | None = None,
    shared_assets: Sequence[ReusableAsset] | None = None,
    prior_project_assets: Sequence[ReusableAsset] | None = None,
    domain_packs: Sequence[DomainPack] | None = None,
    prior_usefulness: Mapping[str, float] | None = None,
    limit: int = 10,
) -> CrossProjectRecommendationReport:
    retrieval_report = retrieve_cross_project_assets(
        current_project_id=current_project_id,
        query=query,
        current_project_assets=current_project_assets,
        shared_assets=shared_assets,
        prior_project_assets=prior_project_assets,
        domain_packs=domain_packs,
        prior_usefulness=prior_usefulness,
        limit=limit,
    )
    recommendations = _rank_recommendations(retrieval_report.candidates)
    return CrossProjectRecommendationReport(
        query=retrieval_report.query,
        current_project_id=current_project_id,
        retrieval_report=retrieval_report,
        recommendations=recommendations,
    )


__all__ = [
    "CrossProjectRecommendation",
    "CrossProjectRecommendationReport",
    "recommend_cross_project_assets",
]
