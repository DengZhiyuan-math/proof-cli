from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .blockers import integrate_verification_result as _integrate_blocker_result
from .domain import TheoremContract, utc_now
from .obligations import block_obligation, close_obligation
from .proof_state import (
    clear_unresolved_trust_call,
    load_state,
    note_unresolved_trust_call,
    record_verification_result_entry,
    save_state,
)
from .storage import ProjectStore, append_event, get_contract, store_contract
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


def _record_or_default(value: str | None, fallback: str | None) -> str | None:
    return value if value is not None else fallback


def _update_contract(
    store: ProjectStore,
    theorem_id: str | None,
    record: VerificationResultRecord,
) -> None:
    if theorem_id is None:
        return
    contract = get_contract(store, theorem_id)
    if contract is None:
        return
    entry = record.summary()
    if entry not in contract.local_usage_notes:
        contract.local_usage_notes.append(entry)
    if record.notes:
        contract.notes = record.notes if not contract.notes else f"{contract.notes}; {record.notes}"
    contract.updated_at = utc_now()
    store_contract(store, contract)
    append_event(
        store,
        "verification_result_attached_to_contract",
        f"attached verification result {record.result.id} to theorem contract {theorem_id}",
        entity_id=theorem_id,
        payload={"contract": contract.model_dump(mode="json"), "verification_result": record.model_dump(mode="json")},
    )


def _update_obligation(
    store: ProjectStore,
    obligation_id: str | None,
    record: VerificationResultRecord,
) -> None:
    if obligation_id is None:
        return
    if record.effect == "strengthening":
        close_obligation(
            store,
            obligation_id,
            rationale=record.summary(),
            route_notes=f"machine-check result {record.result.id}",
        )
        return

    reason = record.summary()
    block_obligation(
        store,
        obligation_id,
        reason,
        route_notes=f"machine-check result {record.result.id}",
    )


def _update_state_for_effect(
    store: ProjectStore,
    theorem_id: str | None,
    record: VerificationResultRecord,
) -> None:
    if theorem_id is None:
        return
    if record.effect == "strengthening":
        clear_unresolved_trust_call(store, theorem_id)
    elif record.effect == "weakening":
        note_unresolved_trust_call(store, theorem_id)


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

    _update_contract(store, theorem_id, record)
    _update_obligation(store, obligation_id, record)
    _update_state_for_effect(store, theorem_id, record)

    if blocker_id is not None:
        _integrate_blocker_result(store, blocker_id, record)

    return record


def list_verification_results(store: ProjectStore) -> list[VerificationResultRecord]:
    state = load_state(store)
    from .proof_state import list_verification_result_records

    return list_verification_result_records(state)


__all__ = [
    "VerificationResultRecord",
    "list_verification_results",
    "record_verification_result",
]
