from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .domain import TheoremContract, TheoremProvenanceKind, TheoremReviewState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReferenceSourceType(str, Enum):
    standard_reference = "standard_reference"
    research_paper = "research_paper"
    textbook = "textbook"
    survey = "survey"
    monograph = "monograph"
    website = "website"
    other = "other"


class ReferenceReviewStatus(str, Enum):
    candidate = "candidate"
    approved = "approved"
    rejected = "rejected"
    deferred = "deferred"


class ReferenceTrustLevel(str, Enum):
    foundational = "foundational"
    standard_reference = "standard_reference"
    external_research_source = "external_research_source"
    tentative_source = "tentative_source"


class CitationProvenanceKind(str, Enum):
    imported = "imported"
    adapted = "adapted"
    project_original = "project_original"
    conditional = "conditional"


class ReferenceRecord(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int
    source_type: ReferenceSourceType = ReferenceSourceType.other
    origin: str = ""
    bibliographic_source: str = ""
    identifier: str = ""
    url: str = ""
    notes: str = ""
    review_status: ReferenceReviewStatus = ReferenceReviewStatus.candidate
    trust_level: ReferenceTrustLevel = ReferenceTrustLevel.tentative_source
    is_callable: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReferenceReviewRecord(BaseModel):
    id: str
    reference_id: str
    previous_status: ReferenceReviewStatus | None = None
    review_status: ReferenceReviewStatus
    trust_level: ReferenceTrustLevel = ReferenceTrustLevel.tentative_source
    is_callable: bool = False
    reviewer: str = "human"
    rationale: str = ""
    created_at: datetime = Field(default_factory=utc_now)


def normalize_citation_provenance(
    *,
    theorem: TheoremContract | None = None,
    provenance_kind: TheoremProvenanceKind | None = None,
    review_state: TheoremReviewState | None = None,
    notes: str = "",
) -> CitationProvenanceKind:
    if theorem is not None:
        provenance_kind = theorem.provenance_kind
        review_state = theorem.review_state
        notes = theorem.notes
    if provenance_kind == TheoremProvenanceKind.imported:
        if review_state == TheoremReviewState.approved:
            return CitationProvenanceKind.imported
        return CitationProvenanceKind.conditional
    if review_state in {TheoremReviewState.candidate, TheoremReviewState.superseded}:
        return CitationProvenanceKind.conditional
    if notes.strip():
        return CitationProvenanceKind.adapted
    return CitationProvenanceKind.project_original


@dataclass(frozen=True)
class ReferenceReviewResult:
    allowed: bool
    message: str
