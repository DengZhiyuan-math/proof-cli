from __future__ import annotations

from .domain import ProofObligation, ProofObligationStatus, ProjectState
from .proof_state import (
    add_obligation as _add_obligation,
    load_state,
    record_candidate_reference as _record_candidate_reference,
    record_failed_route as _record_failed_route,
    record_supporting_reference as _record_supporting_reference,
    save_state,
)
from .storage import ProjectStore, append_event, list_obligations as _list_obligations, store_obligation


def _route_tokens(kind: str, reference_ids: list[str] | None) -> list[str]:
    return [f"{kind}_ref:{reference_id}" for reference_id in reference_ids or []]


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def add_obligation(
    store: ProjectStore,
    obligation: ProofObligation,
    *,
    candidate_reference_ids: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    failed_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> ProofObligation:
    obligation = _add_obligation(
        store,
        obligation,
        candidate_reference_ids=candidate_reference_ids,
        supporting_reference_ids=supporting_reference_ids,
        failed_reference_ids=failed_reference_ids,
        route_notes=route_notes,
    )
    for reference_id in candidate_reference_ids or []:
        _record_candidate_reference(
            store,
            target_kind="obligation",
            target_id=obligation.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    for reference_id in supporting_reference_ids or []:
        _record_supporting_reference(
            store,
            target_kind="obligation",
            target_id=obligation.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    for reference_id in failed_reference_ids or []:
        _record_failed_route(
            store,
            f"obligation:{obligation.id}:{reference_id}",
            target_kind="obligation",
            target_id=obligation.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    return obligation


def list_obligations(store: ProjectStore) -> list[ProofObligation]:
    return _list_obligations(store)


def close_obligation(
    store: ProjectStore,
    obligation_id: str,
    rationale: str | None = None,
    *,
    supporting_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> ProofObligation:
    obligations = list_obligations(store)
    for obligation in obligations:
        if obligation.id == obligation_id:
            _extend_unique(obligation.dependencies, _route_tokens("supporting", supporting_reference_ids))
            if route_notes:
                _extend_unique(obligation.dependencies, [f"route_note:{route_notes}"])
            for reference_id in supporting_reference_ids or []:
                _record_supporting_reference(
                    store,
                    target_kind="obligation",
                    target_id=obligation.id,
                    reference_id=reference_id,
                    notes=route_notes or (rationale or ""),
                )
            obligation.status = ProofObligationStatus.closed
            obligation.blocking_reason = rationale
            store_obligation(store, obligation)
            append_event(
                store,
                "obligation_closed",
                f"closed obligation {obligation_id}",
                entity_id=obligation_id,
                payload=obligation.model_dump(mode="json"),
            )
            state = load_state(store)
            if obligation_id in state.open_obligations:
                state.open_obligations.remove(obligation_id)
                save_state(store, state, message=f"closed obligation {obligation_id}")
            return obligation
    raise KeyError(obligation_id)


def block_obligation(
    store: ProjectStore,
    obligation_id: str,
    reason: str,
    *,
    failed_reference_ids: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> ProofObligation:
    obligations = list_obligations(store)
    for obligation in obligations:
        if obligation.id == obligation_id:
            _extend_unique(obligation.dependencies, _route_tokens("failed", failed_reference_ids))
            _extend_unique(obligation.dependencies, _route_tokens("supporting", supporting_reference_ids))
            if route_notes:
                _extend_unique(obligation.dependencies, [f"route_note:{route_notes}"])
            for reference_id in failed_reference_ids or []:
                _record_failed_route(
                    store,
                    f"obligation:{obligation.id}:{reference_id}",
                    target_kind="obligation",
                    target_id=obligation.id,
                    reference_id=reference_id,
                    notes=route_notes or reason,
                )
            obligation.status = ProofObligationStatus.blocked
            obligation.blocking_reason = reason if not route_notes else f"{reason}; {route_notes}"
            store_obligation(store, obligation)
            append_event(
                store,
                "obligation_blocked",
                f"blocked obligation {obligation_id}",
                entity_id=obligation_id,
                payload=obligation.model_dump(mode="json"),
            )
            return obligation
    raise KeyError(obligation_id)
