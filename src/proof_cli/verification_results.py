from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .domain import EvidenceOutcome, utc_now
from .proof_state import load_state, record_verification_result_entry, save_state
from .storage import ProjectStore, append_event
from .verification_ir import (
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationResult,
    VerificationReviewStatus,
    VerificationSourceKind,
    VerificationScope,
)

VERIFICATION_RESULT_EVENT_PREFIX = "verification_result:"


class VerificationResultRecord(BaseModel):
    result: VerificationResult
    result_status: VerificationFragmentStatus
    review_status: VerificationReviewStatus
    source_kind: VerificationSourceKind
    source_id: str
    scope: VerificationScope
    theorem_id: str | None = None
    obligation_id: str | None = None
    blocker_id: str | None = None
    proof_step_id: str | None = None
    route_id: str | None = None
    effect: Literal["strengthening", "weakening", "neutral"] = "neutral"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    def summary(self) -> str:
        targets: list[str] = []
        if self.theorem_id:
            targets.append(f"theorem={self.theorem_id}")
        if self.obligation_id:
            targets.append(f"obligation={self.obligation_id}")
        if self.blocker_id:
            targets.append(f"blocker={self.blocker_id}")
        if self.proof_step_id:
            targets.append(f"proof_step={self.proof_step_id}")
        if self.route_id:
            targets.append(f"route={self.route_id}")
        target_text = ", ".join(targets) if targets else "unlinked"
        note_text = f" - {self.notes}" if self.notes else ""
        return (
            f"{self.result.id} [{self.source_kind.value}:{self.source_id}] "
            f"{self.result_status.value}/{self.review_status.value} -> {self.effect} "
            f"({target_text}){note_text}"
        )


def _default_effect(
    *,
    result_status: VerificationFragmentStatus,
    review_status: VerificationReviewStatus,
) -> Literal["strengthening", "weakening", "neutral"]:
    if result_status == VerificationFragmentStatus.machine_checked and review_status == VerificationReviewStatus.accepted_after_review:
        return "strengthening"
    if result_status in {
        VerificationFragmentStatus.backend_failed,
        VerificationFragmentStatus.translation_failed,
        VerificationFragmentStatus.stale_after_change,
    }:
        return "weakening"
    if review_status == VerificationReviewStatus.rejected_by_human:
        return "weakening"
    return "neutral"


# A machine check's own status as an Evidence check outcome. Only what the
# machine did counts: the IR's review statuses are someone's judgment, and
# read as inconclusive here (ADR-0004 point 5).
_EVIDENCE_OUTCOMES = {
    VerificationFragmentStatus.machine_checked: EvidenceOutcome.passed,
    VerificationFragmentStatus.backend_failed: EvidenceOutcome.failed,
    VerificationFragmentStatus.translation_failed: EvidenceOutcome.error,
    VerificationFragmentStatus.stale_after_change: EvidenceOutcome.stale,
}
VERIFY_RUN_CHECKER = "proof verify run"


def evidence_outcome_for(status: VerificationFragmentStatus) -> EvidenceOutcome:
    """The Evidence check outcome a machine check with this status records (#27)."""
    return _EVIDENCE_OUTCOMES.get(status, EvidenceOutcome.inconclusive)


def _record_or_default(value: str | None, fallback: str | None) -> str | None:
    return value if value is not None else fallback


def record_verification_result(
    store: ProjectStore,
    fragment: VerificationFragment,
    result: VerificationResult,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    blocker_id: str | None = None,
    proof_step_id: str | None = None,
    route_id: str | None = None,
    notes: str = "",
) -> VerificationResultRecord:
    theorem_id = _record_or_default(theorem_id, fragment.scope.theorem_id)
    obligation_id = _record_or_default(obligation_id, fragment.scope.obligation_id)
    blocker_id = _record_or_default(blocker_id, fragment.scope.blocker_id)
    proof_step_id = _record_or_default(proof_step_id, fragment.scope.proof_step_id)
    route_id = _record_or_default(route_id, fragment.scope.route_id)
    effect = _default_effect(result_status=fragment.status, review_status=result.review_status)
    record = VerificationResultRecord(
        result=result,
        result_status=fragment.status,
        review_status=result.review_status,
        source_kind=fragment.source_type,
        source_id=fragment.source_id,
        scope=fragment.scope,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        blocker_id=blocker_id,
        proof_step_id=proof_step_id,
        route_id=route_id,
        effect=effect,
        notes=notes,
    )

    state = load_state(store)
    record_verification_result_entry(state, record)
    save_state(store, state, message=f"recorded verification result {result.id}")
    append_event(
        store,
        "verification_result_recorded",
        f"recorded verification result {result.id}",
        entity_id=result.id,
        payload={"verification_result": record.model_dump(mode="json")},
    )

    # Recorded, never acted on: a checker's output is advisory, like an
    # Evidence check. It closes, blocks or resolves nothing, and writes to no
    # theorem contract, obligation or blocker; the record above links them (#27).

    return record


def list_verification_results(store: ProjectStore) -> list[VerificationResultRecord]:
    state = load_state(store)
    from .proof_state import list_verification_result_records

    return list_verification_result_records(state)


__all__ = [
    "VERIFY_RUN_CHECKER",
    "VerificationResultRecord",
    "evidence_outcome_for",
    "list_verification_results",
    "record_verification_result",
]
