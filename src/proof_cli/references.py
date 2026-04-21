from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


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


@dataclass(frozen=True)
class ReferenceReviewResult:
    allowed: bool
    message: str
