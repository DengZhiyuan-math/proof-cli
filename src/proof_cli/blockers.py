from __future__ import annotations

from typing import Literal

from .domain import BlockerRecord
from .proof_state import (
    add_blocker as _add_blocker,
    record_candidate_reference as _record_candidate_reference,
    record_failed_route as _record_failed_route,
    record_supporting_reference as _record_supporting_reference,
)
from .storage import ProjectStore, list_blockers as _list_blockers


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
