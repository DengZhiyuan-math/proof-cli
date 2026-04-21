from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field

from .bugs import ProofBugReport, ProofBugSeverity, ProofBugStatus
from .domain import utc_now


class EvidenceReviewRecommendation(str, Enum):
    accept = "accept"
    revise = "revise"
    block = "block"


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _recommendation_for_report(report: ProofBugReport) -> EvidenceReviewRecommendation:
    if report.status in {ProofBugStatus.dismissed, ProofBugStatus.superseded, ProofBugStatus.repaired}:
        return EvidenceReviewRecommendation.accept
    if report.status == ProofBugStatus.confirmed:
        return EvidenceReviewRecommendation.block
    if report.severity in {ProofBugSeverity.high, ProofBugSeverity.critical}:
        return EvidenceReviewRecommendation.block
    return EvidenceReviewRecommendation.revise


class EvidenceChain(BaseModel):
    id: str = Field(default_factory=lambda: f"evi_{uuid.uuid4().hex[:12]}")
    bug_report_id: str
    bug_type: str
    bug_status: ProofBugStatus
    description: str
    reasoning_path: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    review_recommendation: EvidenceReviewRecommendation
    linked_contract_ids: list[str] = Field(default_factory=list)
    linked_obligation_ids: list[str] = Field(default_factory=list)
    linked_blocker_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def from_bug_report(cls, report: ProofBugReport) -> "EvidenceChain":
        reasoning_path = list(report.reasoning_path) or [report.id]
        return cls(
            bug_report_id=report.id,
            bug_type=report.bug_type.value,
            bug_status=report.status,
            description=report.description,
            reasoning_path=_unique(reasoning_path),
            missing_conditions=_unique(report.missing_conditions),
            review_recommendation=_recommendation_for_report(report),
            linked_contract_ids=_unique(report.linked_contract_ids),
            linked_obligation_ids=_unique(report.linked_obligation_ids),
            linked_blocker_ids=_unique(report.linked_blocker_ids),
            evidence=list(report.evidence),
        )


def build_evidence_chains(reports: Iterable[ProofBugReport]) -> list[EvidenceChain]:
    return [EvidenceChain.from_bug_report(report) for report in reports if report.status == ProofBugStatus.suspected]


__all__ = [
    "EvidenceChain",
    "EvidenceReviewRecommendation",
    "build_evidence_chains",
]
