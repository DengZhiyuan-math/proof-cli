from __future__ import annotations

from .domain import ProjectSnapshot
from .memory import (
    HandoffSnapshot,
    build_handoff_snapshot,
    record_handoff_snapshot,
    synchronize_verification_history,
    synchronize_proof_debug_history,
)
from .publication import record_publication_bundle_snapshot
from .proof_state import build_snapshot
from .storage import ProjectStore, read_latest_snapshot


def _require_node(store: ProjectStore, node_id: str | None) -> None:
    if node_id is not None:
        from .proof_map import require_node

        require_node(store, node_id)


def create_snapshot(store: ProjectStore, note: str = "", *, node_id: str | None = None) -> ProjectSnapshot:
    """Snapshot the project and record a handoff; with `node_id`, a handoff scoped to that node (#45)."""
    _require_node(store, node_id)  # before anything is written
    synchronize_proof_debug_history(store)
    synchronize_verification_history(store)
    snapshot = build_snapshot(store, handoff_note=note)
    handoff_snapshot = build_handoff_snapshot(store, snapshot, handoff_note=note, node_id=node_id)
    record_handoff_snapshot(store, handoff_snapshot)
    record_publication_bundle_snapshot(store, snapshot.project_id, "handoff_snapshot", snapshot.model_dump(mode="json"))
    return snapshot


def restore_snapshot(store: ProjectStore, *, node_id: str | None = None) -> HandoffSnapshot | None:
    """Recover from the latest project snapshot; with `node_id`, with that node's memory scope (#45)."""
    _require_node(store, node_id)
    synchronize_proof_debug_history(store)
    synchronize_verification_history(store)
    snapshot = read_latest_snapshot(store)
    if snapshot is None:
        return None
    return build_handoff_snapshot(store, snapshot, handoff_note=snapshot.handoff_note, node_id=node_id)
