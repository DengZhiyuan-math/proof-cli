from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import utc_now


class VerificationSourceKind(str, Enum):
    theorem_contract = "theorem_contract"
    proof_obligation = "proof_obligation"
    theorem_application = "theorem_application"
    proof_step = "proof_step"
    imported_result = "imported_result"


class VerificationFragmentStatus(str, Enum):
    queued_for_verification = "queued_for_verification"
    machine_checked = "machine_checked"
    backend_failed = "backend_failed"
    translation_failed = "translation_failed"
    stale_after_change = "stale_after_change"
    rejected_by_human = "rejected_by_human"
    accepted_after_review = "accepted_after_review"


class VerificationTranslationStatus(str, Enum):
    pending = "pending"
    translated = "translated"
    translation_failed = "translation_failed"


class VerificationReviewStatus(str, Enum):
    pending_review = "pending_review"
    accepted_after_review = "accepted_after_review"
    rejected_by_human = "rejected_by_human"


class VerificationScope(BaseModel):
    project_id: str
    theorem_id: str | None = None
    goal_id: str | None = None
    obligation_id: str | None = None
    blocker_id: str | None = None
    proof_step_id: str | None = None
    route_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class VerificationAssumption(BaseModel):
    statement: str
    source_id: str | None = None
    required: bool = True


class VerificationQuantifiedGoal(BaseModel):
    statement: str
    quantifiers: list[str] = Field(default_factory=list)
    free_variables: list[str] = Field(default_factory=list)


class VerificationSideCondition(BaseModel):
    statement: str
    origin: str = ""
    satisfied_by: list[str] = Field(default_factory=list)


class VerificationTheoremApplication(BaseModel):
    theorem_id: str
    theorem_name: str = ""
    statement: str = ""
    assumptions_used: list[str] = Field(default_factory=list)
    side_conditions: list[str] = Field(default_factory=list)
    fragile: bool = False
    notes: str = ""
    reasoning_path: list[str] = Field(default_factory=list)


class VerificationDependencyVersion(BaseModel):
    dependency_id: str
    version: int
    kind: Literal[
        "theorem_contract",
        "proof_obligation",
        "imported_result",
        "proof_step",
        "external_reference",
    ] = "theorem_contract"
    digest: str = ""


class VerificationProvenance(BaseModel):
    source_kind: VerificationSourceKind
    source_id: str
    source_label: str = ""
    source_scope: VerificationScope | None = None
    derived_from_ids: list[str] = Field(default_factory=list)
    machine_path: list[str] = Field(default_factory=list)
    reviewed_by: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class VerificationArtifact(BaseModel):
    kind: str
    uri: str
    description: str = ""


class VerificationResult(BaseModel):
    id: str = Field(default_factory=lambda: f"vchk_{uuid.uuid4().hex[:12]}")
    fragment_id: str
    backend: str
    summary: str
    artifacts: list[VerificationArtifact] = Field(default_factory=list)
    review_status: VerificationReviewStatus = VerificationReviewStatus.pending_review
    notes: str = ""
    checked_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def accept(self, *, notes: str | None = None) -> "VerificationResult":
        update: dict[str, Any] = {"review_status": VerificationReviewStatus.accepted_after_review}
        if notes is not None:
            update["notes"] = notes
        update["checked_at"] = utc_now()
        return self.model_copy(update=update)

    def reject(self, *, notes: str | None = None) -> "VerificationResult":
        update: dict[str, Any] = {"review_status": VerificationReviewStatus.rejected_by_human}
        if notes is not None:
            update["notes"] = notes
        update["checked_at"] = utc_now()
        return self.model_copy(update=update)


class VerificationFragment(BaseModel):
    id: str = Field(default_factory=lambda: f"vfrag_{uuid.uuid4().hex[:12]}")
    source_type: VerificationSourceKind
    source_id: str
    scope: VerificationScope
    ir_version: int = 1
    status: VerificationFragmentStatus = VerificationFragmentStatus.queued_for_verification
    translation_status: VerificationTranslationStatus = VerificationTranslationStatus.pending
    backend_target: str | None = None
    assumptions: list[VerificationAssumption] = Field(default_factory=list)
    quantified_goals: list[VerificationQuantifiedGoal] = Field(default_factory=list)
    theorem_applications: list[VerificationTheoremApplication] = Field(default_factory=list)
    side_conditions: list[VerificationSideCondition] = Field(default_factory=list)
    dependency_versions: list[VerificationDependencyVersion] = Field(default_factory=list)
    provenance: VerificationProvenance
    result_id: str | None = None
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def _transition(self, **updates: Any) -> "VerificationFragment":
        updates.setdefault("updated_at", utc_now())
        return self.model_copy(update=updates)

    def queue_for_verification(self, *, backend_target: str | None = None) -> "VerificationFragment":
        update: dict[str, Any] = {
            "status": VerificationFragmentStatus.queued_for_verification,
            "translation_status": VerificationTranslationStatus.pending,
        }
        if backend_target is not None:
            update["backend_target"] = backend_target
        return self._transition(**update)

    def record_translation_success(self, *, backend_target: str | None = None) -> "VerificationFragment":
        update: dict[str, Any] = {
            "translation_status": VerificationTranslationStatus.translated,
            "status": VerificationFragmentStatus.queued_for_verification,
        }
        if backend_target is not None:
            update["backend_target"] = backend_target
        return self._transition(**update)

    def record_translation_failure(self, reason: str) -> "VerificationFragment":
        notes = reason if not self.notes else f"{self.notes}; {reason}"
        return self._transition(
            status=VerificationFragmentStatus.translation_failed,
            translation_status=VerificationTranslationStatus.translation_failed,
            notes=notes,
        )

    def record_machine_check(self, *, result_id: str, backend_target: str | None = None) -> "VerificationFragment":
        update: dict[str, Any] = {
            "status": VerificationFragmentStatus.machine_checked,
            "translation_status": VerificationTranslationStatus.translated,
            "result_id": result_id,
        }
        if backend_target is not None:
            update["backend_target"] = backend_target
        return self._transition(**update)

    def record_backend_failure(self, reason: str, *, backend_target: str | None = None) -> "VerificationFragment":
        notes = reason if not self.notes else f"{self.notes}; {reason}"
        update: dict[str, Any] = {
            "status": VerificationFragmentStatus.backend_failed,
            "notes": notes,
        }
        if backend_target is not None:
            update["backend_target"] = backend_target
        return self._transition(**update)

    def mark_stale_after_change(
        self,
        *,
        changed_dependency_versions: list[VerificationDependencyVersion] | None = None,
        reason: str = "",
    ) -> "VerificationFragment":
        update: dict[str, Any] = {
            "status": VerificationFragmentStatus.stale_after_change,
        }
        if changed_dependency_versions is not None:
            update["dependency_versions"] = list(changed_dependency_versions)
        if reason:
            update["notes"] = reason if not self.notes else f"{self.notes}; {reason}"
        return self._transition(**update)

    def accept_after_review(self, *, result_id: str | None = None, notes: str = "") -> "VerificationFragment":
        update: dict[str, Any] = {
            "status": VerificationFragmentStatus.accepted_after_review,
        }
        if result_id is not None:
            update["result_id"] = result_id
        if notes:
            update["notes"] = notes if not self.notes else f"{self.notes}; {notes}"
        return self._transition(**update)

    def reject_by_human(self, *, result_id: str | None = None, notes: str = "") -> "VerificationFragment":
        update: dict[str, Any] = {
            "status": VerificationFragmentStatus.rejected_by_human,
        }
        if result_id is not None:
            update["result_id"] = result_id
        if notes:
            update["notes"] = notes if not self.notes else f"{self.notes}; {notes}"
        return self._transition(**update)


class FormalizationRecommendation(BaseModel):
    fragment_id: str
    rank: int
    reason: str
    confidence: float = 0.0
    suggested_backend: str | None = None
    notes: str = ""


__all__ = [
    "FormalizationRecommendation",
    "VerificationArtifact",
    "VerificationAssumption",
    "VerificationDependencyVersion",
    "VerificationFragment",
    "VerificationFragmentStatus",
    "VerificationProvenance",
    "VerificationQuantifiedGoal",
    "VerificationResult",
    "VerificationReviewStatus",
    "VerificationScope",
    "VerificationSideCondition",
    "VerificationSourceKind",
    "VerificationTheoremApplication",
    "VerificationTranslationStatus",
]
