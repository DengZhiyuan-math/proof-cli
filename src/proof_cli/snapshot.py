from __future__ import annotations

from .domain import ProjectSnapshot
from .memory import (
    HandoffSnapshot,
    build_handoff_snapshot,
    record_handoff_snapshot,
    synchronize_proof_debug_history,
)
from .proof_state import build_snapshot
from .storage import ProjectStore, read_latest_snapshot


def create_snapshot(store: ProjectStore, note: str = "") -> ProjectSnapshot:
    synchronize_proof_debug_history(store)
    snapshot = build_snapshot(store, handoff_note=note)
    handoff_snapshot = build_handoff_snapshot(store, snapshot, handoff_note=note)
    record_handoff_snapshot(store, handoff_snapshot)
    return snapshot


def restore_snapshot(store: ProjectStore) -> HandoffSnapshot | None:
    synchronize_proof_debug_history(store)
    snapshot = read_latest_snapshot(store)
    if snapshot is None:
        return None
    return build_handoff_snapshot(store, snapshot, handoff_note=snapshot.handoff_note)
