from __future__ import annotations

from typing import Literal

from .domain import BlockerRecord, BlockerStatus
from .proof_state import (
    add_blocker as _add_blocker,
    load_state,
    record_candidate_reference as _record_candidate_reference,
    record_failed_route as _record_failed_route,
    record_supporting_reference as _record_supporting_reference,
    save_state,
)
from .storage import ProjectStore, append_event, list_blockers as _list_blockers, store_blocker


def _route_tokens(kind: str, reference_ids: list[str] | None) -> list[str]:
    return [f"{kind}_ref:{reference_id}" for reference_id in reference_ids or []]


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def add_blocker(
    store: ProjectStore,
    blocker: BlockerRecord,
    *,
    candidate_reference_ids: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    failed_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> BlockerRecord:
    blocker = _add_blocker(
        store,
        blocker,
        candidate_reference_ids=candidate_reference_ids,
        supporting_reference_ids=supporting_reference_ids,
        failed_reference_ids=failed_reference_ids,
        route_notes=route_notes,
    )
    for reference_id in candidate_reference_ids or []:
        _record_candidate_reference(
            store,
            target_kind="blocker",
            target_id=blocker.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    for reference_id in supporting_reference_ids or []:
        _record_supporting_reference(
            store,
            target_kind="blocker",
            target_id=blocker.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    for reference_id in failed_reference_ids or []:
        _record_failed_route(
            store,
            f"blocker:{blocker.id}:{reference_id}",
            target_kind="blocker",
            target_id=blocker.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    return blocker


def list_blockers(store: ProjectStore) -> list[BlockerRecord]:
    return _list_blockers(store)


def record_failed_route(
    store: ProjectStore,
    route: str,
    *,
    target_kind: Literal["goal", "obligation", "blocker"] = "blocker",
    target_id: str = "",
    reference_id: str = "",
    reference_title: str = "",
    notes: str = "",
) -> None:
    _record_failed_route(
        store,
        route,
        target_kind=target_kind,
        target_id=target_id,
        reference_id=reference_id,
        reference_title=reference_title,
        notes=notes,
    )


def resolve_blocker(
    store: ProjectStore,
    blocker_id: str,
    rationale: str | None = None,
    *,
    supporting_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> BlockerRecord:
    blockers = list_blockers(store)
    for blocker in blockers:
        if blocker.id == blocker_id:
            _extend_unique(blocker.related_contracts, _route_tokens("supporting", supporting_reference_ids))
            if route_notes:
                _extend_unique(blocker.related_steps, [f"route_note:{route_notes}"])
                blocker.description = f"{blocker.description} (literature: {route_notes})"
            for reference_id in supporting_reference_ids or []:
                _record_supporting_reference(
                    store,
                    target_kind="blocker",
                    target_id=blocker.id,
                    reference_id=reference_id,
                    notes=route_notes or (rationale or ""),
                )
            blocker.status = BlockerStatus.resolved
            blocker.description = blocker.description if rationale is None else f"{blocker.description} (resolved: {rationale})"
            store_blocker(store, blocker)
            append_event(
                store,
                "blocker_resolved",
                f"resolved blocker {blocker_id}",
                entity_id=blocker_id,
                payload=blocker.model_dump(mode="json"),
            )
            state = load_state(store)
            if blocker_id in state.blockers:
                state.blockers.remove(blocker_id)
                save_state(store, state, message=f"resolved blocker {blocker_id}")
            return blocker
    raise KeyError(blocker_id)
