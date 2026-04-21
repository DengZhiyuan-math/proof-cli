from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import ProjectSnapshot, utc_now
from .storage import ProjectStore, read_state


class MemoryLayer(str, Enum):
    working = "working"
    semantic = "semantic"
    episodic = "episodic"
    procedural = "procedural"


class MemoryImportance(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class MemoryStatus(str, Enum):
    stable = "stable"
    tentative = "tentative"
    failed = "failed"
    tactic = "tactic"


class MemoryScope(BaseModel):
    project_id: str
    theorem_id: str | None = None
    goal_id: str | None = None
    obligation_id: str | None = None
    blocker_id: str | None = None
    route_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class LinkedProofState(BaseModel):
    theorem_id: str | None = None
    goal_id: str | None = None
    obligation_id: str | None = None
    blocker_id: str | None = None
    route_id: str | None = None
    snapshot_id: str | None = None
    notes: str = ""


class MemoryArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    layer: MemoryLayer
    status: MemoryStatus
    scope: MemoryScope
    content: str
    importance: MemoryImportance = MemoryImportance.medium
    linked_proof_state: LinkedProofState = Field(default_factory=LinkedProofState)
    source: Literal["manual", "snapshot", "recovery", "migration"] = "manual"
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class HandoffSnapshot(BaseModel):
    project_id: str
    project_snapshot: ProjectSnapshot
    working_context: list[str] = Field(default_factory=list)
    stable_facts: list[str] = Field(default_factory=list)
    failed_routes: list[str] = Field(default_factory=list)
    procedural_tactics: list[str] = Field(default_factory=list)
    unresolved_debts: list[str] = Field(default_factory=list)
    recent_attempts: list[str] = Field(default_factory=list)
    blocker_ids: list[str] = Field(default_factory=list)
    handoff_note: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class LayeredMemory(BaseModel):
    project_id: str
    version: int = 2
    working: list[MemoryArtifact] = Field(default_factory=list)
    semantic: list[MemoryArtifact] = Field(default_factory=list)
    episodic: list[MemoryArtifact] = Field(default_factory=list)
    procedural: list[MemoryArtifact] = Field(default_factory=list)
    handoff_snapshots: list[HandoffSnapshot] = Field(default_factory=list)
    tracked_symbols: list[str] = Field(default_factory=list)


_LAYER_DEFAULT_STATUS: dict[MemoryLayer, MemoryStatus] = {
    MemoryLayer.working: MemoryStatus.tentative,
    MemoryLayer.semantic: MemoryStatus.stable,
    MemoryLayer.episodic: MemoryStatus.failed,
    MemoryLayer.procedural: MemoryStatus.tactic,
}


def _project_id(store: ProjectStore) -> str:
    return read_state(store).project_id


def _memory_path(store: ProjectStore) -> Path:
    return store.root / ".proof" / "memory.json"


def _coerce_layer(layer: str | MemoryLayer) -> MemoryLayer:
    if isinstance(layer, MemoryLayer):
        return layer
    try:
        return MemoryLayer(layer)
    except ValueError as exc:
        raise ValueError(f"unknown memory layer: {layer}") from exc


def _coerce_importance(value: str | MemoryImportance) -> MemoryImportance:
    if isinstance(value, MemoryImportance):
        return value
    try:
        return MemoryImportance(value)
    except ValueError as exc:
        raise ValueError(f"unknown memory importance: {value}") from exc


def _artifact_payload(item: Any, layer: MemoryLayer, project_id: str) -> MemoryArtifact:
    if isinstance(item, MemoryArtifact):
        return item
    if isinstance(item, str):
        return MemoryArtifact(
            layer=layer,
            status=_LAYER_DEFAULT_STATUS[layer],
            scope=MemoryScope(project_id=project_id),
            content=item,
            source="migration",
        )
    if isinstance(item, dict):
        payload = dict(item)
        payload.setdefault("layer", layer.value)
        payload.setdefault("status", _LAYER_DEFAULT_STATUS[layer].value)
        if "scope" not in payload:
            payload["scope"] = {"project_id": project_id}
        elif isinstance(payload["scope"], dict):
            payload["scope"].setdefault("project_id", project_id)
        payload.setdefault("source", "migration")
        return MemoryArtifact.model_validate(payload)
    raise TypeError(f"unsupported memory artifact payload: {type(item)!r}")


def _coerce_handoff_snapshot(item: Any, project_id: str) -> HandoffSnapshot:
    if isinstance(item, HandoffSnapshot):
        return item
    if isinstance(item, dict):
        payload = dict(item)
        payload.setdefault("project_id", project_id)
        return HandoffSnapshot.model_validate(payload)
    raise TypeError(f"unsupported handoff snapshot payload: {type(item)!r}")


def load_memory(store: ProjectStore) -> LayeredMemory:
    path = _memory_path(store)
    project_id = _project_id(store)
    if not path.exists():
        return LayeredMemory(project_id=project_id)
    data = json.loads(path.read_text())
    layer_memory = LayeredMemory(project_id=data.get("project_id", project_id), version=int(data.get("version", 2)))
    for layer in (MemoryLayer.working, MemoryLayer.semantic, MemoryLayer.episodic, MemoryLayer.procedural):
        raw_entries = data.get(layer.value, [])
        entries = [_artifact_payload(item, layer, layer_memory.project_id) for item in raw_entries]
        setattr(layer_memory, layer.value, entries)
    layer_memory.handoff_snapshots = [
        _coerce_handoff_snapshot(item, layer_memory.project_id) for item in data.get("handoff_snapshots", [])
    ]
    layer_memory.tracked_symbols = list(data.get("tracked_symbols", []))
    return layer_memory


def save_memory(store: ProjectStore, memory: LayeredMemory) -> LayeredMemory:
    path = _memory_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    memory.project_id = _project_id(store)
    path.write_text(memory.model_dump_json(indent=2))
    return memory


def append_memory_artifact(
    store: ProjectStore,
    layer: str | MemoryLayer,
    entry: str,
    *,
    importance: str | MemoryImportance = MemoryImportance.medium,
    theorem_id: str | None = None,
    goal_id: str | None = None,
    obligation_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    status: MemoryStatus | str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration"] = "manual",
    tags: list[str] | None = None,
    notes: str = "",
) -> MemoryArtifact:
    memory = load_memory(store)
    layer_enum = _coerce_layer(layer)
    artifact = MemoryArtifact(
        layer=layer_enum,
        status=MemoryStatus(status) if isinstance(status, str) else (status or _LAYER_DEFAULT_STATUS[layer_enum]),
        scope=MemoryScope(
            project_id=memory.project_id,
            theorem_id=theorem_id,
            goal_id=goal_id,
            obligation_id=obligation_id,
            blocker_id=blocker_id,
            route_id=route_id,
            tags=list(tags or []),
        ),
        content=entry,
        importance=_coerce_importance(importance),
        linked_proof_state=LinkedProofState(
            theorem_id=theorem_id,
            goal_id=goal_id,
            obligation_id=obligation_id,
            blocker_id=blocker_id,
            route_id=route_id,
            snapshot_id=linked_snapshot_id,
            notes=notes,
        ),
        source=source,
        tags=list(tags or []),
    )
    getattr(memory, layer_enum.value).append(artifact)
    save_memory(store, memory)
    return artifact


def record_memory(
    store: ProjectStore,
    layer: str | MemoryLayer,
    entry: str,
    *,
    importance: str | MemoryImportance = MemoryImportance.medium,
    theorem_id: str | None = None,
    goal_id: str | None = None,
    obligation_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    status: MemoryStatus | str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration"] = "manual",
    tags: list[str] | None = None,
    notes: str = "",
) -> LayeredMemory:
    append_memory_artifact(
        store,
        layer,
        entry,
        importance=importance,
        theorem_id=theorem_id,
        goal_id=goal_id,
        obligation_id=obligation_id,
        blocker_id=blocker_id,
        route_id=route_id,
        linked_snapshot_id=linked_snapshot_id,
        status=status,
        source=source,
        tags=tags,
        notes=notes,
    )
    return load_memory(store)


def _matching_artifacts(
    store: ProjectStore,
    *,
    layer: str | MemoryLayer | None = None,
    status: MemoryStatus | str | None = None,
    theorem_id: str | None = None,
    goal_id: str | None = None,
    minimum_importance: str | MemoryImportance | None = None,
) -> list[MemoryArtifact]:
    memory = load_memory(store)
    if layer is None:
        candidates = [artifact for bucket in (memory.working, memory.semantic, memory.episodic, memory.procedural) for artifact in bucket]
    else:
        candidates = list(getattr(memory, _coerce_layer(layer).value))
    if status is not None:
        status_enum = MemoryStatus(status) if isinstance(status, str) else status
        candidates = [artifact for artifact in candidates if artifact.status == status_enum]
    if theorem_id is not None:
        candidates = [artifact for artifact in candidates if artifact.scope.theorem_id == theorem_id or artifact.linked_proof_state.theorem_id == theorem_id]
    if goal_id is not None:
        candidates = [artifact for artifact in candidates if artifact.scope.goal_id == goal_id or artifact.linked_proof_state.goal_id == goal_id]
    if minimum_importance is not None:
        rank = {MemoryImportance.low: 0, MemoryImportance.medium: 1, MemoryImportance.high: 2, MemoryImportance.critical: 3}
        threshold = _coerce_importance(minimum_importance)
        candidates = [artifact for artifact in candidates if rank[artifact.importance] >= rank[threshold]]
    return sorted(candidates, key=lambda artifact: (artifact.created_at, artifact.id))


def list_memory_artifacts(
    store: ProjectStore,
    *,
    layer: str | MemoryLayer | None = None,
    status: MemoryStatus | str | None = None,
    theorem_id: str | None = None,
    goal_id: str | None = None,
    minimum_importance: str | MemoryImportance | None = None,
) -> list[MemoryArtifact]:
    return _matching_artifacts(
        store,
        layer=layer,
        status=status,
        theorem_id=theorem_id,
        goal_id=goal_id,
        minimum_importance=minimum_importance,
    )


def stable_memory(store: ProjectStore, *, theorem_id: str | None = None) -> list[MemoryArtifact]:
    return _matching_artifacts(store, status=MemoryStatus.stable, theorem_id=theorem_id)


def failed_routes(store: ProjectStore, *, theorem_id: str | None = None) -> list[MemoryArtifact]:
    return _matching_artifacts(store, layer=MemoryLayer.episodic, status=MemoryStatus.failed, theorem_id=theorem_id)


def procedural_tactics(store: ProjectStore, *, theorem_id: str | None = None) -> list[MemoryArtifact]:
    return _matching_artifacts(store, layer=MemoryLayer.procedural, status=MemoryStatus.tactic, theorem_id=theorem_id)


def working_memory(store: ProjectStore, *, theorem_id: str | None = None) -> list[MemoryArtifact]:
    return _matching_artifacts(store, layer=MemoryLayer.working, theorem_id=theorem_id)


def record_handoff_snapshot(
    store: ProjectStore,
    handoff_snapshot: HandoffSnapshot,
) -> HandoffSnapshot:
    memory = load_memory(store)
    memory.handoff_snapshots.append(handoff_snapshot)
    save_memory(store, memory)
    return handoff_snapshot


def latest_handoff_snapshot(store: ProjectStore) -> HandoffSnapshot | None:
    memory = load_memory(store)
    if not memory.handoff_snapshots:
        return None
    return memory.handoff_snapshots[-1]


def build_handoff_snapshot(
    store: ProjectStore,
    project_snapshot: ProjectSnapshot,
    *,
    handoff_note: str = "",
) -> HandoffSnapshot:
    memory = load_memory(store)
    working_context = [artifact.content for artifact in memory.working[-3:]]
    stable_facts = [artifact.content for artifact in stable_memory(store)][-5:]
    failed_route_text = [artifact.content for artifact in failed_routes(store)][-5:]
    tactic_text = [artifact.content for artifact in procedural_tactics(store)][-5:]
    recent_attempts = [artifact.content for artifact in (memory.episodic[-2:] + memory.procedural[-2:])]
    unresolved_debts = list(project_snapshot.unresolved_trust_sensitive_calls)
    blocker_ids = list(project_snapshot.active_blockers)
    if not handoff_note:
        handoff_note = project_snapshot.handoff_note or "resume from the latest proof state"
    return HandoffSnapshot(
        project_id=memory.project_id,
        project_snapshot=project_snapshot,
        working_context=working_context,
        stable_facts=stable_facts,
        failed_routes=failed_route_text,
        procedural_tactics=tactic_text,
        unresolved_debts=unresolved_debts,
        recent_attempts=recent_attempts,
        blocker_ids=blocker_ids,
        handoff_note=handoff_note,
    )


def track_symbol(store: ProjectStore, symbol: str) -> LayeredMemory:
    memory = load_memory(store)
    if symbol not in memory.tracked_symbols:
        memory.tracked_symbols.append(symbol)
    return save_memory(store, memory)


def recent_symbols(store: ProjectStore) -> list[str]:
    return list(load_memory(store).tracked_symbols)
