from __future__ import annotations

from .domain import ProjectSnapshot
from .memory import (
    HandoffSnapshot,
    build_handoff_snapshot,
    latest_handoff_snapshot,
    record_handoff_snapshot,
)
from .proof_state import build_snapshot
from .storage import ProjectStore, read_latest_snapshot


def create_snapshot(store: ProjectStore, note: str = "") -> ProjectSnapshot:
    snapshot = build_snapshot(store, handoff_note=note)
    handoff_snapshot = build_handoff_snapshot(store, snapshot, handoff_note=note)
    record_handoff_snapshot(store, handoff_snapshot)
    return snapshot


def restore_snapshot(store: ProjectStore) -> HandoffSnapshot | None:
    handoff_snapshot = latest_handoff_snapshot(store)
    if handoff_snapshot is not None:
        return handoff_snapshot
    snapshot = read_latest_snapshot(store)
    if snapshot is None:
        return None
    return build_handoff_snapshot(store, snapshot, handoff_note=snapshot.handoff_note)
