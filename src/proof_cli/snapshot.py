from __future__ import annotations

from .domain import ProjectSnapshot
from .proof_state import build_snapshot
from .storage import ProjectStore, read_latest_snapshot


def create_snapshot(store: ProjectStore, note: str = "") -> ProjectSnapshot:
    return build_snapshot(store, handoff_note=note)


def restore_snapshot(store: ProjectStore) -> ProjectSnapshot | None:
    return read_latest_snapshot(store)

