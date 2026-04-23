from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TheoremStatus(str, Enum):
    imported = "imported"
    verified = "verified"
    assumed = "assumed"
    draft = "draft"
    blocked = "blocked"
    failed = "failed"


class TrustLevel(str, Enum):
    foundational = "foundational"
    project_verified = "project_verified"
    external_reference = "external_reference"
    temporary_admit = "temporary_admit"


class TheoremProvenanceKind(str, Enum):
    local = "local"
    imported = "imported"


class TheoremReviewState(str, Enum):
    draft = "draft"
    candidate = "candidate"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class ProofObligationStatus(str, Enum):
    open = "open"
    closed = "closed"
    blocked = "blocked"


class BlockerStatus(str, Enum):
    active = "active"
    resolved = "resolved"


class EventRecord(BaseModel):
    id: str
    kind: str
    entity_id: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TheoremContract(BaseModel):
    id: str
    kind: Literal["theorem", "lemma", "proposition", "corollary", "result"] = "theorem"
    name: str
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    status: TheoremStatus = TheoremStatus.draft
    trust_level: TrustLevel = TrustLevel.temporary_admit
    provenance_kind: TheoremProvenanceKind = TheoremProvenanceKind.local
    review_state: TheoremReviewState = TheoremReviewState.draft
    dependencies: list[str] = Field(default_factory=list)
    source_ref: str = "internal/project"
    grounded_reference_ids: list[str] = Field(default_factory=list)
    grounded_theorem_ids: list[str] = Field(default_factory=list)
    local_usage_notes: list[str] = Field(default_factory=list)
    imported_usage_notes: list[str] = Field(default_factory=list)
    created_by: str = "human"
    updated_by: str = "human"
    contributors: list[str] = Field(default_factory=list)
    supersedes_version: int | None = None
    notes: str = ""
    version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProofObligation(BaseModel):
    id: str
    goal_statement: str
    source_step_id: str | None = None
    required_for: str | None = None
    status: ProofObligationStatus = ProofObligationStatus.open
    priority: Literal["low", "medium", "high"] = "medium"
    blocking_reason: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BlockerRecord(BaseModel):
    id: str
    scope: str
    description: str
    failure_type: str
    related_steps: list[str] = Field(default_factory=list)
    related_contracts: list[str] = Field(default_factory=list)
    status: BlockerStatus = BlockerStatus.active
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProjectSnapshot(BaseModel):
    project_id: str
    active_theorem: str | None = None
    current_goals: list[str] = Field(default_factory=list)
    validated_results: list[str] = Field(default_factory=list)
    open_obligations: list[str] = Field(default_factory=list)
    active_blockers: list[str] = Field(default_factory=list)
    recently_used_results: list[str] = Field(default_factory=list)
    unresolved_trust_sensitive_calls: list[str] = Field(default_factory=list)
    next_promising_routes: list[str] = Field(default_factory=list)
    publication_view_id: str | None = None
    publication_audience: str | None = None
    publication_claim_ids: list[str] = Field(default_factory=list)
    publication_release_ids: list[str] = Field(default_factory=list)
    publication_bundle_snapshot_ids: list[str] = Field(default_factory=list)
    handoff_note: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ProjectState(BaseModel):
    project_id: str
    current_theorem: str | None = None
    current_context: list[str] = Field(default_factory=list)
    open_goals: list[str] = Field(default_factory=list)
    open_obligations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    failed_routes: list[str] = Field(default_factory=list)
    session_history: list[str] = Field(default_factory=list)
    latest_snapshot_id: str | None = None
    recent_theorem_usage: list[str] = Field(default_factory=list)
    unresolved_trust_sensitive_calls: list[str] = Field(default_factory=list)
