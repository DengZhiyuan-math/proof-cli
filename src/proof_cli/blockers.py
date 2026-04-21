from __future__ import annotations

from .domain import BlockerRecord, BlockerStatus
from .proof_state import add_blocker as _add_blocker, record_failed_route as _record_failed_route, load_state, save_state
from .storage import ProjectStore, append_event, list_blockers as _list_blockers, store_blocker


def add_blocker(store: ProjectStore, blocker: BlockerRecord) -> BlockerRecord:
    return _add_blocker(store, blocker)


def list_blockers(store: ProjectStore) -> list[BlockerRecord]:
    return _list_blockers(store)


def record_failed_route(store: ProjectStore, route: str) -> None:
    _record_failed_route(store, route)


def resolve_blocker(store: ProjectStore, blocker_id: str, rationale: str | None = None) -> BlockerRecord:
    blockers = list_blockers(store)
    for blocker in blockers:
        if blocker.id == blocker_id:
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

