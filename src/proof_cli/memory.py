from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import ProjectSnapshot, utc_now
from .storage import ProjectStore, read_state
from .verification_ir import (
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
)
from .verification_results import VerificationResultRecord


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
    method_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class LinkedProofState(BaseModel):
    theorem_id: str | None = None
    goal_id: str | None = None
    obligation_id: str | None = None
    blocker_id: str | None = None
    route_id: str | None = None
    method_id: str | None = None
    snapshot_id: str | None = None
    notes: str = ""


class VerificationLifecycleKind(str, Enum):
    queued_for_verification = "queued_for_verification"
    machine_checked = "machine_checked"
    backend_failed = "backend_failed"
    translation_failed = "translation_failed"
    stale_after_change = "stale_after_change"
    rejected_by_human = "rejected_by_human"
    accepted_after_review = "accepted_after_review"
    revalidation_requested = "revalidation_requested"
    revalidation_completed = "revalidation_completed"


class VerificationLifecycleRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: VerificationLifecycleKind
    scope: VerificationScope
    fragment: VerificationFragment
    result: VerificationResult | None = None
    result_record: VerificationResultRecord | None = None
    source: Literal["manual", "snapshot", "recovery", "migration", "state_sync"] = "manual"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


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


class ProofDebugMemoryKind(str, Enum):
    suspicion = "suspicion"
    bug_history = "bug_history"
    evidence_chain = "evidence_chain"
    debug_task = "debug_task"
    repair_decision = "repair_decision"
    repair_pattern = "repair_pattern"
    failure_motif = "failure_motif"


class ProofDebugScope(BaseModel):
    project_id: str
    theorem_id: str | None = None
    obligation_id: str | None = None
    method_id: str | None = None
    blocker_id: str | None = None
    route_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ProofRepairDecision(BaseModel):
    bug_id: str
    bug_status: Any
    review_state: Any = "reviewed"
    note: str = ""


class ProofDebugMemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: ProofDebugMemoryKind
    scope: ProofDebugScope
    summary: str
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual"
    source_key: str = ""
    bug_report: Any | None = None
    evidence_chain: Any | None = None
    debug_task: Any | None = None
    repair_decision: ProofRepairDecision | None = None
    pattern: str = ""
    motif: str = ""
    evidence: list[str] = Field(default_factory=list)
    linked_snapshot_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class HandoffSnapshot(BaseModel):
    project_id: str
    project_snapshot: ProjectSnapshot
    verification_history: list[VerificationLifecycleRecord] = Field(default_factory=list)
    queued_verification_fragments: list[VerificationFragment] = Field(default_factory=list)
    accepted_verification_results: list[VerificationResultRecord] = Field(default_factory=list)
    stale_verification_fragments: list[VerificationFragment] = Field(default_factory=list)
    revalidation_requirements: list[VerificationLifecycleRecord] = Field(default_factory=list)
    proof_debug_history: list[ProofDebugMemoryRecord] = Field(default_factory=list)
    suspicion_reports: list[Any] = Field(default_factory=list)
    resolved_bug_history: list[Any] = Field(default_factory=list)
    evidence_chains: list[Any] = Field(default_factory=list)
    debug_tasks: list[Any] = Field(default_factory=list)
    repair_decisions: list[ProofRepairDecision] = Field(default_factory=list)
    repair_patterns: list[str] = Field(default_factory=list)
    failure_motifs: list[str] = Field(default_factory=list)
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
    version: int = 4
    working: list[MemoryArtifact] = Field(default_factory=list)
    semantic: list[MemoryArtifact] = Field(default_factory=list)
    episodic: list[MemoryArtifact] = Field(default_factory=list)
    procedural: list[MemoryArtifact] = Field(default_factory=list)
    verification_history: list[VerificationLifecycleRecord] = Field(default_factory=list)
    proof_debug_history: list[ProofDebugMemoryRecord] = Field(default_factory=list)
    handoff_snapshots: list[HandoffSnapshot] = Field(default_factory=list)
    tracked_symbols: list[str] = Field(default_factory=list)


_LAYER_DEFAULT_STATUS: dict[MemoryLayer, MemoryStatus] = {
    MemoryLayer.working: MemoryStatus.tentative,
    MemoryLayer.semantic: MemoryStatus.stable,
    MemoryLayer.episodic: MemoryStatus.failed,
    MemoryLayer.procedural: MemoryStatus.tactic,
}

_BUG_SCAN_HISTORY_PREFIX = "proof_bug_scan:"
_BUG_REVIEW_HISTORY_PREFIX = "proof_bug_review:"
_BUG_REPAIR_HISTORY_PREFIX = "proof_bug_repair:"
_DEBUG_BATCH_HISTORY_PREFIX = "proof_debug_batch:"
_REASONING_HISTORY_PREFIX = "proof_reasoning:"
_VERIFICATION_FRAGMENT_HISTORY_PREFIX = "verification_fragment:"
_VERIFICATION_RESULT_HISTORY_PREFIX = "verification_result:"


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


def _stable_debug_id(*parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"dbgmem_{digest}"


def _stable_verification_id(*parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"vmem_{digest}"


def _coerce_debug_scope(item: Any, project_id: str) -> ProofDebugScope:
    if isinstance(item, ProofDebugScope):
        if not item.project_id:
            item.project_id = project_id
        return item
    if isinstance(item, dict):
        payload = dict(item)
        payload.setdefault("project_id", project_id)
        return ProofDebugScope.model_validate(payload)
    raise TypeError(f"unsupported debug scope payload: {type(item)!r}")


def _debug_record_payload(item: Any, project_id: str) -> ProofDebugMemoryRecord:
    from .bugs import ProofBugReport, ProofBugReviewState, ProofBugScan, ProofBugStatus
    from .debug_tasks import ProofDebugTask
    from .evidence import EvidenceChain

    if isinstance(item, ProofDebugMemoryRecord):
        if not item.scope.project_id:
            item.scope.project_id = project_id
        return item
    if isinstance(item, dict):
        payload = dict(item)
        payload.setdefault("scope", {"project_id": project_id})
        if isinstance(payload["scope"], dict):
            payload["scope"].setdefault("project_id", project_id)
        record = ProofDebugMemoryRecord.model_validate(payload)
        if isinstance(record.bug_report, dict):
            record.bug_report = ProofBugReport.model_validate(record.bug_report)
        if isinstance(record.evidence_chain, dict):
            record.evidence_chain = EvidenceChain.model_validate(record.evidence_chain)
        if isinstance(record.debug_task, dict):
            record.debug_task = ProofDebugTask.model_validate(record.debug_task)
        if isinstance(record.repair_decision, dict):
            repair_decision = dict(record.repair_decision)
            repair_decision.setdefault("review_state", ProofBugReviewState.reviewed.value)
            record.repair_decision = ProofRepairDecision.model_validate(repair_decision)
        return record
    raise TypeError(f"unsupported debug record payload: {type(item)!r}")


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
            payload["scope"].setdefault("method_id", None)
        payload.setdefault("source", "migration")
        return MemoryArtifact.model_validate(payload)
    raise TypeError(f"unsupported memory artifact payload: {type(item)!r}")


def _verification_result_record_payload(item: Any) -> VerificationResultRecord:
    if isinstance(item, VerificationResultRecord):
        return item
    if isinstance(item, dict):
        return VerificationResultRecord.model_validate(item)
    raise TypeError(f"unsupported verification result record payload: {type(item)!r}")


def _verification_lifecycle_payload(item: Any, project_id: str) -> VerificationLifecycleRecord:
    if isinstance(item, VerificationLifecycleRecord):
        if item.scope.project_id != project_id:
            item.scope.project_id = project_id
        if item.fragment.scope.project_id != project_id:
            item.fragment.scope.project_id = project_id
        return item
    if isinstance(item, dict):
        payload = dict(item)
        payload.setdefault("scope", {"project_id": project_id})
        if isinstance(payload["scope"], dict):
            payload["scope"].setdefault("project_id", project_id)
        fragment = payload.get("fragment")
        if isinstance(fragment, dict):
            fragment.setdefault("scope", {"project_id": project_id})
            if isinstance(fragment["scope"], dict):
                fragment["scope"].setdefault("project_id", project_id)
        record = VerificationLifecycleRecord.model_validate(payload)
        if record.scope.project_id != project_id:
            record.scope.project_id = project_id
        if record.fragment.scope.project_id != project_id:
            record.fragment.scope.project_id = project_id
        return record
    raise TypeError(f"unsupported verification lifecycle payload: {type(item)!r}")


def _coerce_handoff_snapshot(item: Any, project_id: str) -> HandoffSnapshot:
    from .bugs import ProofBugReport, ProofBugReviewState, ProofBugStatus
    from .debug_tasks import ProofDebugTask
    from .evidence import EvidenceChain

    if isinstance(item, HandoffSnapshot):
        return item
    if isinstance(item, dict):
        payload = dict(item)
        payload.setdefault("project_id", project_id)
        payload.setdefault("proof_debug_history", [])
        payload.setdefault("suspicion_reports", [])
        payload.setdefault("resolved_bug_history", [])
        payload.setdefault("evidence_chains", [])
        payload.setdefault("debug_tasks", [])
        payload.setdefault("repair_decisions", [])
        payload.setdefault("repair_patterns", [])
        payload.setdefault("failure_motifs", [])
        snapshot = HandoffSnapshot.model_validate(payload)
        snapshot.proof_debug_history = [_debug_record_payload(record, project_id) for record in snapshot.proof_debug_history]
        snapshot.suspicion_reports = [
            ProofBugReport.model_validate(report) if isinstance(report, dict) else report for report in snapshot.suspicion_reports
        ]
        snapshot.resolved_bug_history = [
            ProofBugReport.model_validate(report) if isinstance(report, dict) else report for report in snapshot.resolved_bug_history
        ]
        snapshot.evidence_chains = [
            EvidenceChain.model_validate(chain) if isinstance(chain, dict) else chain for chain in snapshot.evidence_chains
        ]
        snapshot.debug_tasks = [
            ProofDebugTask.model_validate(task) if isinstance(task, dict) else task for task in snapshot.debug_tasks
        ]
        snapshot.repair_decisions = [
            ProofRepairDecision.model_validate(decision) if isinstance(decision, dict) else decision
            for decision in snapshot.repair_decisions
        ]
        return snapshot
    raise TypeError(f"unsupported handoff snapshot payload: {type(item)!r}")


def load_memory(store: ProjectStore) -> LayeredMemory:
    path = _memory_path(store)
    project_id = _project_id(store)
    if not path.exists():
        return LayeredMemory(project_id=project_id)
    data = json.loads(path.read_text())
    layer_memory = LayeredMemory(project_id=data.get("project_id", project_id), version=int(data.get("version", 4)))
    for layer in (MemoryLayer.working, MemoryLayer.semantic, MemoryLayer.episodic, MemoryLayer.procedural):
        raw_entries = data.get(layer.value, [])
        entries = [_artifact_payload(item, layer, layer_memory.project_id) for item in raw_entries]
        setattr(layer_memory, layer.value, entries)
    layer_memory.verification_history = [
        _verification_lifecycle_payload(item, layer_memory.project_id) for item in data.get("verification_history", [])
    ]
    raw_debug_entries = data.get("proof_debug_history", data.get("debug_history", []))
    layer_memory.proof_debug_history = [
        _debug_record_payload(item, layer_memory.project_id) for item in raw_debug_entries
    ]
    layer_memory.handoff_snapshots = [
        _coerce_handoff_snapshot(item, layer_memory.project_id) for item in data.get("handoff_snapshots", [])
    ]
    layer_memory.tracked_symbols = list(data.get("tracked_symbols", []))
    return layer_memory


def save_memory(store: ProjectStore, memory: LayeredMemory) -> LayeredMemory:
    path = _memory_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    memory.project_id = _project_id(store)
    memory.version = 4
    path.write_text(memory.model_dump_json(indent=2))
    return memory


def _verification_record_kind(fragment: VerificationFragment) -> VerificationLifecycleKind:
    if fragment.status == VerificationFragmentStatus.queued_for_verification and any(
        step == "revalidate fragment" for step in fragment.provenance.machine_path
    ):
        return VerificationLifecycleKind.revalidation_completed
    return VerificationLifecycleKind(fragment.status.value)


def _verification_records_from_state(store: ProjectStore) -> list[VerificationLifecycleRecord]:
    from .proof_state import list_verification_result_records, load_state

    state = load_state(store)
    fragments: list[VerificationFragment] = []
    for entry in state.session_history:
        if not entry.startswith(_VERIFICATION_FRAGMENT_HISTORY_PREFIX):
            continue
        payload = entry.removeprefix(_VERIFICATION_FRAGMENT_HISTORY_PREFIX)
        fragments.append(VerificationFragment.model_validate_json(payload))

    result_records = {
        record.result.id: _verification_result_record_payload(record)
        for record in list_verification_result_records(state)
    }

    records: list[VerificationLifecycleRecord] = []
    for fragment in fragments:
        result_record = None
        if fragment.result_id is not None:
            result_record = result_records.get(fragment.result_id)
        if result_record is None:
            result_record = next((record for record in result_records.values() if record.result.fragment_id == fragment.id), None)
        record = VerificationLifecycleRecord(
            id=_stable_verification_id(
                state.project_id,
                fragment.id,
                fragment.status.value,
                fragment.updated_at.isoformat(),
                fragment.result_id or "",
                result_record.result.review_status.value if result_record is not None else "",
                _verification_record_kind(fragment).value,
            ),
            kind=_verification_record_kind(fragment),
            scope=fragment.scope,
            fragment=fragment,
            result=result_record.result if result_record is not None else None,
            result_record=result_record,
            source="state_sync",
            notes=fragment.notes,
            created_at=fragment.created_at,
            updated_at=fragment.updated_at,
        )
        records.append(record)
    return records


def synchronize_verification_history(store: ProjectStore) -> LayeredMemory:
    memory = load_memory(store)
    records = _verification_records_from_state(store)
    if not records:
        return memory
    changed = False
    existing_ids = {record.id for record in memory.verification_history}
    for record in records:
        if record.id in existing_ids:
            continue
        memory.verification_history.append(record)
        existing_ids.add(record.id)
        changed = True
    if changed:
        save_memory(store, memory)
    return memory


def _debug_scope_from_ids(
    project_id: str,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    tags: list[str] | None = None,
) -> ProofDebugScope:
    return ProofDebugScope(
        project_id=project_id,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        blocker_id=blocker_id,
        route_id=route_id,
        tags=list(tags or []),
    )


def _append_debug_record(memory: LayeredMemory, record: ProofDebugMemoryRecord) -> bool:
    existing_keys = {item.id for item in memory.proof_debug_history}
    key = record.id
    if key in existing_keys:
        return False
    memory.proof_debug_history.append(record)
    return True


def record_proof_debug_record(
    store: ProjectStore,
    kind: ProofDebugMemoryKind | str,
    summary: str,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    tags: list[str] | None = None,
    bug_report: ProofBugReport | None = None,
    evidence_chain: EvidenceChain | None = None,
    debug_task: ProofDebugTask | None = None,
    repair_decision: ProofRepairDecision | None = None,
    pattern: str = "",
    motif: str = "",
    evidence: list[str] | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
    source_key: str = "",
) -> ProofDebugMemoryRecord:
    memory = load_memory(store)
    record_kind = kind if isinstance(kind, ProofDebugMemoryKind) else ProofDebugMemoryKind(kind)
    record = ProofDebugMemoryRecord(
        id=_stable_debug_id(
            memory.project_id,
            record_kind.value,
            theorem_id or "",
            obligation_id or "",
            method_id or "",
            blocker_id or "",
            route_id or "",
            source_key or summary,
        ),
        kind=record_kind,
        scope=_debug_scope_from_ids(
            memory.project_id,
            theorem_id=theorem_id,
            obligation_id=obligation_id,
            method_id=method_id,
            blocker_id=blocker_id,
            route_id=route_id,
            tags=tags,
        ),
        summary=summary,
        source=source,
        source_key=source_key or summary,
        bug_report=bug_report,
        evidence_chain=evidence_chain,
        debug_task=debug_task,
        repair_decision=repair_decision,
        pattern=pattern,
        motif=motif,
        evidence=list(evidence or []),
        linked_snapshot_id=linked_snapshot_id,
    )
    if _append_debug_record(memory, record):
        save_memory(store, memory)
    return record


def record_bug_report_memory(
    store: ProjectStore,
    report: ProofBugReport,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
    source_key: str = "",
) -> ProofDebugMemoryRecord:
    from .bugs import ProofBugStatus

    summary = f"{report.id}: {report.bug_type.value} [{report.status.value}/{report.severity.value}] {report.description}"
    kind = (
        ProofDebugMemoryKind.suspicion
        if report.status in {ProofBugStatus.suspected, ProofBugStatus.under_review}
        else ProofDebugMemoryKind.bug_history
    )
    return record_proof_debug_record(
        store,
        kind,
        summary,
        theorem_id=theorem_id or (report.linked_contract_ids[0] if report.linked_contract_ids else None),
        obligation_id=obligation_id or (report.linked_obligation_ids[0] if report.linked_obligation_ids else None),
        method_id=method_id or (report.detector or report.bug_type.value),
        blocker_id=blocker_id or (report.linked_blocker_ids[0] if report.linked_blocker_ids else None),
        route_id=route_id,
        tags=[report.bug_type.value, report.status.value],
        bug_report=report,
        evidence=list(report.evidence),
        linked_snapshot_id=linked_snapshot_id,
        source=source,
        source_key=source_key or f"bug:{report.id}:{report.status.value}:{report.updated_at.isoformat()}",
    )


def record_evidence_chain_memory(
    store: ProjectStore,
    chain: EvidenceChain,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
) -> ProofDebugMemoryRecord:
    from .evidence import EvidenceChain

    summary = f"{chain.bug_report_id}: evidence chain [{chain.review_recommendation.value}]"
    return record_proof_debug_record(
        store,
        ProofDebugMemoryKind.evidence_chain,
        summary,
        theorem_id=theorem_id or (chain.linked_contract_ids[0] if chain.linked_contract_ids else None),
        obligation_id=obligation_id or (chain.linked_obligation_ids[0] if chain.linked_obligation_ids else None),
        method_id=method_id or chain.bug_type,
        blocker_id=blocker_id or (chain.linked_blocker_ids[0] if chain.linked_blocker_ids else None),
        route_id=route_id,
        tags=[chain.bug_status.value, chain.review_recommendation.value],
        evidence_chain=chain,
        evidence=list(chain.evidence),
        linked_snapshot_id=linked_snapshot_id,
        source=source,
        source_key=f"evidence:{chain.id}",
    )


def record_debug_task_memory(
    store: ProjectStore,
    task: ProofDebugTask,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
) -> ProofDebugMemoryRecord:
    from .debug_tasks import ProofDebugTask

    summary = f"{task.id}: {task.task_type.value} [{task.priority.value}/{task.status.value}] {task.title}"
    return record_proof_debug_record(
        store,
        ProofDebugMemoryKind.debug_task,
        summary,
        theorem_id=theorem_id or (task.linked_contract_ids[0] if task.linked_contract_ids else None),
        obligation_id=obligation_id or (task.linked_obligation_ids[0] if task.linked_obligation_ids else None),
        method_id=method_id or task.task_type.value,
        blocker_id=blocker_id or (task.linked_blocker_ids[0] if task.linked_blocker_ids else None),
        route_id=route_id,
        tags=[task.task_type.value, task.status.value, task.priority.value],
        debug_task=task,
        evidence=list(task.evidence),
        linked_snapshot_id=linked_snapshot_id,
        source=source,
        source_key=f"task:{task.id}",
    )


def record_repair_decision_memory(
    store: ProjectStore,
    decision: ProofRepairDecision,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
) -> ProofDebugMemoryRecord:
    summary = f"{decision.bug_id}: {getattr(decision.bug_status, 'value', decision.bug_status)} [{getattr(decision.review_state, 'value', decision.review_state)}] {decision.note}".strip()
    return record_proof_debug_record(
        store,
        ProofDebugMemoryKind.repair_decision,
        summary,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        blocker_id=blocker_id,
        route_id=route_id,
        tags=[decision.bug_status.value, decision.review_state.value],
        repair_decision=decision,
        linked_snapshot_id=linked_snapshot_id,
        source=source,
        source_key=f"decision:{decision.bug_id}:{decision.bug_status.value}:{decision.review_state.value}:{decision.note}",
    )


def record_repair_pattern_memory(
    store: ProjectStore,
    pattern: str,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
    note: str = "",
) -> ProofDebugMemoryRecord:
    summary = note or f"repair pattern: {pattern}"
    return record_proof_debug_record(
        store,
        ProofDebugMemoryKind.repair_pattern,
        summary,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        blocker_id=blocker_id,
        route_id=route_id,
        pattern=pattern,
        linked_snapshot_id=linked_snapshot_id,
        source=source,
        source_key=f"pattern:{theorem_id}:{obligation_id}:{method_id}:{pattern}",
    )


def record_failure_motif_memory(
    store: ProjectStore,
    motif: str,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    linked_snapshot_id: str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "scan", "review", "repair", "debug_batch"] = "manual",
    note: str = "",
) -> ProofDebugMemoryRecord:
    summary = note or f"failure motif: {motif}"
    return record_proof_debug_record(
        store,
        ProofDebugMemoryKind.failure_motif,
        summary,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        blocker_id=blocker_id,
        route_id=route_id,
        motif=motif,
        linked_snapshot_id=linked_snapshot_id,
        source=source,
        source_key=f"motif:{theorem_id}:{obligation_id}:{method_id}:{motif}",
    )


def _proof_debug_records_from_state(store: ProjectStore) -> list[ProofDebugMemoryRecord]:
    from .bugs import ProofBugReport, ProofBugReviewState, ProofBugScan, ProofBugStatus
    from .debug_tasks import ProofDebugTaskBatch
    from .evidence import EvidenceChain

    state = read_state(store)
    project_id = state.project_id
    reviews: dict[str, dict[str, object]] = {}
    repairs: dict[str, dict[str, object]] = {}
    bug_reports: dict[str, ProofBugReport] = {}
    records: list[ProofDebugMemoryRecord] = []

    for entry in state.session_history:
        if entry.startswith(_BUG_REVIEW_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_REVIEW_HISTORY_PREFIX))
            reviews[str(payload["bug_id"])] = payload
        elif entry.startswith(_BUG_REPAIR_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_REPAIR_HISTORY_PREFIX))
            repairs[str(payload["bug_id"])] = payload

    for entry in state.session_history:
        if entry.startswith(_BUG_SCAN_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_SCAN_HISTORY_PREFIX))
            scan = ProofBugScan.model_validate(payload)
            for report in scan.reports:
                records.append(
                    record_bug_report_memory(
                        store,
                        report,
                        theorem_id=scan.theorem_id,
                        method_id=report.detector or report.bug_type.value,
                        source="scan",
                        source_key=f"scanraw:{scan.theorem_id}:{report.id}:{report.status.value}:{report.updated_at.isoformat()}",
                    )
                )
                bug_reports[report.id] = report

                update: dict[str, object] = {}
                review_payload = reviews.get(report.id)
                if review_payload is not None:
                    update["status"] = ProofBugStatus(str(review_payload["bug_status"]))
                repair_payload = repairs.get(report.id)
                if repair_payload is not None:
                    update["status"] = ProofBugStatus(str(repair_payload["bug_status"]))
                adjusted_report = report.model_copy(update=update) if update else report
                if adjusted_report.status != report.status:
                    records.append(
                        record_bug_report_memory(
                            store,
                            adjusted_report,
                            theorem_id=scan.theorem_id,
                            method_id=adjusted_report.detector or adjusted_report.bug_type.value,
                            source="repair" if repair_payload is not None else "review",
                            source_key=f"scanfinal:{scan.theorem_id}:{report.id}:{adjusted_report.status.value}:{adjusted_report.updated_at.isoformat()}",
                        )
                    )
                    bug_reports[adjusted_report.id] = adjusted_report
                chain = EvidenceChain.from_bug_report(report)
                records.append(
                    record_evidence_chain_memory(
                        store,
                        chain,
                        theorem_id=scan.theorem_id,
                        method_id=report.detector or report.bug_type.value,
                        source="scan",
                    )
                )
                records.append(
                    record_repair_pattern_memory(
                        store,
                        report.bug_type.value,
                        theorem_id=scan.theorem_id,
                        obligation_id=report.linked_obligation_ids[0] if report.linked_obligation_ids else None,
                        method_id=report.detector or report.bug_type.value,
                        source="scan",
                        note=f"repair pattern for {report.id}",
                    )
                )
                records.append(
                    record_failure_motif_memory(
                        store,
                        report.description,
                        theorem_id=scan.theorem_id,
                        obligation_id=report.linked_obligation_ids[0] if report.linked_obligation_ids else None,
                        method_id=report.detector or report.bug_type.value,
                        source="scan",
                        note=f"failure motif for {report.id}",
                    )
                )
        elif entry.startswith(_DEBUG_BATCH_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_DEBUG_BATCH_HISTORY_PREFIX))
            batch = ProofDebugTaskBatch.model_validate(payload)
            for task in batch.tasks:
                records.append(
                    record_debug_task_memory(
                        store,
                        task,
                        theorem_id=batch.theorem_id,
                        method_id=task.task_type.value,
                        source="debug_batch",
                    )
                )
        elif entry.startswith(_BUG_REVIEW_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_REVIEW_HISTORY_PREFIX))
            bug_id = str(payload["bug_id"])
            report = bug_reports.get(bug_id)
            decision = ProofRepairDecision(
                bug_id=bug_id,
                bug_status=ProofBugStatus(str(payload["bug_status"])),
                review_state=ProofBugReviewState(str(payload.get("review_state", "triaged"))),
                note=str(payload.get("rationale", "")),
            )
            records.append(
                record_repair_decision_memory(
                    store,
                    decision,
                    theorem_id=report.linked_contract_ids[0] if report and report.linked_contract_ids else None,
                    obligation_id=report.linked_obligation_ids[0] if report and report.linked_obligation_ids else None,
                    method_id=report.detector if report and report.detector else None,
                    source="review",
                )
            )
        elif entry.startswith(_BUG_REPAIR_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_REPAIR_HISTORY_PREFIX))
            bug_id = str(payload["bug_id"])
            report = bug_reports.get(bug_id)
            decision = ProofRepairDecision(
                bug_id=bug_id,
                bug_status=ProofBugStatus(str(payload["bug_status"])),
                review_state=ProofBugReviewState(str(payload.get("review_state", "reviewed"))),
                note=str(payload.get("note", "")),
            )
            records.append(
                record_repair_decision_memory(
                    store,
                    decision,
                    theorem_id=report.linked_contract_ids[0] if report and report.linked_contract_ids else None,
                    obligation_id=report.linked_obligation_ids[0] if report and report.linked_obligation_ids else None,
                    method_id=report.detector if report and report.detector else None,
                    source="repair",
                )
            )
        elif entry.startswith(_REASONING_HISTORY_PREFIX):
            continue

    return records


def synchronize_proof_debug_history(store: ProjectStore) -> LayeredMemory:
    memory = load_memory(store)
    records = _proof_debug_records_from_state(store)
    if not records:
        return memory
    changed = False
    existing_keys = {record.id for record in memory.proof_debug_history}
    for record in records:
        key = record.id
        if key in existing_keys:
            continue
        memory.proof_debug_history.append(record)
        existing_keys.add(key)
        changed = True
    if changed:
        save_memory(store, memory)
    return memory


def record_verification_lifecycle(
    store: ProjectStore,
    fragment: VerificationFragment,
    *,
    result: VerificationResult | None = None,
    result_record: VerificationResultRecord | None = None,
    kind: VerificationLifecycleKind | str | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "state_sync"] = "manual",
    notes: str = "",
) -> VerificationLifecycleRecord:
    memory = load_memory(store)
    record_kind = kind if isinstance(kind, VerificationLifecycleKind) else VerificationLifecycleKind(kind or fragment.status.value)
    record = VerificationLifecycleRecord(
        id=_stable_verification_id(
            memory.project_id,
            fragment.id,
            fragment.status.value,
            fragment.updated_at.isoformat(),
            fragment.result_id or "",
            result.review_status.value if result is not None else (result_record.review_status.value if result_record is not None else ""),
            record_kind.value,
        ),
        kind=record_kind,
        scope=fragment.scope,
        fragment=fragment,
        result=result,
        result_record=result_record,
        source=source,
        notes=notes or fragment.notes,
        created_at=fragment.created_at,
        updated_at=fragment.updated_at,
    )
    if all(existing.id != record.id for existing in memory.verification_history):
        memory.verification_history.append(record)
        save_memory(store, memory)
    return record


def record_verification_staleness(
    store: ProjectStore,
    fragment: VerificationFragment,
    *,
    result: VerificationResult | None = None,
    result_record: VerificationResultRecord | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "state_sync"] = "manual",
    notes: str = "",
) -> VerificationLifecycleRecord:
    return record_verification_lifecycle(
        store,
        fragment,
        result=result,
        result_record=result_record,
        kind=VerificationLifecycleKind.stale_after_change,
        source=source,
        notes=notes,
    )


def record_verification_revalidation(
    store: ProjectStore,
    fragment: VerificationFragment,
    *,
    result: VerificationResult | None = None,
    result_record: VerificationResultRecord | None = None,
    source: Literal["manual", "snapshot", "recovery", "migration", "state_sync"] = "manual",
    notes: str = "",
) -> VerificationLifecycleRecord:
    kind = VerificationLifecycleKind.revalidation_completed
    return record_verification_lifecycle(
        store,
        fragment,
        result=result,
        result_record=result_record,
        kind=kind,
        source=source,
        notes=notes,
    )


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
    method_id: str | None = None,
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
            method_id=method_id,
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
            method_id=method_id,
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
    method_id: str | None = None,
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
        method_id=method_id,
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


def _matches_verification_scope(
    record: VerificationLifecycleRecord,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
) -> bool:
    if theorem_id is not None and record.scope.theorem_id != theorem_id:
        return False
    if obligation_id is not None and record.scope.obligation_id != obligation_id:
        return False
    if proof_step_id is not None and record.scope.proof_step_id != proof_step_id:
        return False
    if source_id is not None and record.fragment.source_id != source_id and record.fragment.id != source_id:
        return False
    if route_id is not None and record.scope.route_id != route_id:
        return False
    return True


def verification_records(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
    kind: VerificationLifecycleKind | str | None = None,
) -> list[VerificationLifecycleRecord]:
    memory = synchronize_verification_history(store)
    candidates = list(memory.verification_history)
    if kind is not None:
        kind_enum = kind if isinstance(kind, VerificationLifecycleKind) else VerificationLifecycleKind(kind)
        candidates = [record for record in candidates if record.kind == kind_enum]
    candidates = [
        record
        for record in candidates
        if _matches_verification_scope(
            record,
            theorem_id=theorem_id,
            obligation_id=obligation_id,
            proof_step_id=proof_step_id,
            source_id=source_id,
            route_id=route_id,
        )
    ]
    return sorted(candidates, key=lambda record: (record.updated_at, record.created_at, record.id))


def verification_dependency_versions(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
) -> list[VerificationDependencyVersion]:
    versions: list[VerificationDependencyVersion] = []
    seen: set[tuple[str, int, str, str]] = set()
    for record in verification_records(
        store,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        proof_step_id=proof_step_id,
        source_id=source_id,
        route_id=route_id,
    ):
        for dependency in record.fragment.dependency_versions:
            key = (dependency.dependency_id, dependency.version, dependency.kind, dependency.digest)
            if key in seen:
                continue
            seen.add(key)
            versions.append(dependency)
    return versions


def queued_verification_fragments(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
) -> list[VerificationFragment]:
    return [
        record.fragment
        for record in verification_records(
            store,
            theorem_id=theorem_id,
            obligation_id=obligation_id,
            proof_step_id=proof_step_id,
            source_id=source_id,
            route_id=route_id,
        )
        if record.fragment.status == VerificationFragmentStatus.queued_for_verification
    ]


def stale_verification_fragments(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
) -> list[VerificationFragment]:
    return [
        record.fragment
        for record in verification_records(
            store,
            theorem_id=theorem_id,
            obligation_id=obligation_id,
            proof_step_id=proof_step_id,
            source_id=source_id,
            route_id=route_id,
        )
        if record.fragment.status == VerificationFragmentStatus.stale_after_change
    ]


def accepted_verification_results(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
) -> list[VerificationResultRecord]:
    records = []
    for record in verification_records(
        store,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        proof_step_id=proof_step_id,
        source_id=source_id,
        route_id=route_id,
    ):
        if record.result_record is None:
            continue
        if record.result_record.review_status != VerificationReviewStatus.accepted_after_review:
            continue
        records.append(record.result_record)
    return records


def revalidation_history(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    source_id: str | None = None,
    route_id: str | None = None,
) -> list[VerificationLifecycleRecord]:
    return [
        record
        for record in verification_records(
            store,
            theorem_id=theorem_id,
            obligation_id=obligation_id,
            proof_step_id=proof_step_id,
            source_id=source_id,
            route_id=route_id,
        )
        if record.kind in {VerificationLifecycleKind.stale_after_change, VerificationLifecycleKind.revalidation_completed}
        or "revalidate fragment" in record.fragment.provenance.machine_path
    ]


def _matches_debug_scope(
    record: ProofDebugMemoryRecord,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
) -> bool:
    if theorem_id is not None and record.scope.theorem_id != theorem_id:
        return False
    if obligation_id is not None and record.scope.obligation_id != obligation_id:
        return False
    if method_id is not None and record.scope.method_id != method_id:
        return False
    if blocker_id is not None and record.scope.blocker_id != blocker_id:
        return False
    if route_id is not None and record.scope.route_id != route_id:
        return False
    return True


def proof_debug_records(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
    kind: ProofDebugMemoryKind | str | None = None,
) -> list[ProofDebugMemoryRecord]:
    memory = load_memory(store)
    candidates = list(memory.proof_debug_history)
    if kind is not None:
        kind_enum = kind if isinstance(kind, ProofDebugMemoryKind) else ProofDebugMemoryKind(kind)
        candidates = [record for record in candidates if record.kind == kind_enum]
    candidates = [
        record
        for record in candidates
        if _matches_debug_scope(
            record,
            theorem_id=theorem_id,
            obligation_id=obligation_id,
            method_id=method_id,
            blocker_id=blocker_id,
            route_id=route_id,
        )
    ]
    return sorted(candidates, key=lambda record: (record.created_at, record.id))


def proof_debug_history(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
    blocker_id: str | None = None,
    route_id: str | None = None,
) -> list[ProofDebugMemoryRecord]:
    return proof_debug_records(
        store,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        blocker_id=blocker_id,
        route_id=route_id,
    )


def proof_debug_patterns(
    store: ProjectStore,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    method_id: str | None = None,
) -> list[ProofDebugMemoryRecord]:
    return proof_debug_records(
        store,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        kind=ProofDebugMemoryKind.repair_pattern,
    ) + proof_debug_records(
        store,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        method_id=method_id,
        kind=ProofDebugMemoryKind.failure_motif,
    )


def latest_proof_debug_snapshot(store: ProjectStore, *, theorem_id: str | None = None) -> HandoffSnapshot | None:
    memory = load_memory(store)
    snapshots = memory.handoff_snapshots
    if theorem_id is None:
        return snapshots[-1] if snapshots else None
    for snapshot in reversed(snapshots):
        if snapshot.project_snapshot.active_theorem == theorem_id:
            return snapshot
    return None


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
    memory = synchronize_verification_history(store)
    theorem_id = project_snapshot.active_theorem
    debug_records = proof_debug_history(store, theorem_id=theorem_id) if theorem_id is not None else proof_debug_history(store)
    verification_history = verification_records(store, theorem_id=theorem_id) if theorem_id is not None else verification_records(store)
    suspicion_reports = [
        record.bug_report
        for record in debug_records
        if record.bug_report is not None and record.kind == ProofDebugMemoryKind.suspicion
    ]
    resolved_bug_history = [
        record.bug_report
        for record in debug_records
        if record.bug_report is not None and record.kind == ProofDebugMemoryKind.bug_history
    ]
    evidence_chains = [record.evidence_chain for record in debug_records if record.evidence_chain is not None]
    debug_tasks = [record.debug_task for record in debug_records if record.debug_task is not None]
    repair_decisions = [record.repair_decision for record in debug_records if record.repair_decision is not None]
    repair_patterns = [record.pattern or record.summary for record in debug_records if record.kind == ProofDebugMemoryKind.repair_pattern]
    failure_motifs = [record.motif or record.summary for record in debug_records if record.kind == ProofDebugMemoryKind.failure_motif]
    working_context = [artifact.content for artifact in memory.working[-3:]]
    stable_facts = [artifact.content for artifact in stable_memory(store)][-5:]
    failed_route_text = [artifact.content for artifact in failed_routes(store)][-5:]
    tactic_text = [artifact.content for artifact in procedural_tactics(store)][-5:]
    recent_attempts = [artifact.content for artifact in (memory.episodic[-2:] + memory.procedural[-2:])]
    unresolved_debts = list(project_snapshot.unresolved_trust_sensitive_calls)
    blocker_ids = list(project_snapshot.active_blockers)
    queued_fragments = [
        record.fragment
        for record in verification_history
        if record.fragment.status == VerificationFragmentStatus.queued_for_verification
    ]
    stale_fragments = [
        record.fragment
        for record in verification_history
        if record.fragment.status == VerificationFragmentStatus.stale_after_change
    ]
    accepted_results = [
        record.result_record
        for record in verification_history
        if record.result_record is not None and record.result_record.review_status == VerificationReviewStatus.accepted_after_review
    ]
    revalidation_requirements = [
        record
        for record in verification_history
        if record.fragment.status == VerificationFragmentStatus.stale_after_change
        or record.kind == VerificationLifecycleKind.revalidation_requested
        or record.kind == VerificationLifecycleKind.revalidation_completed
        or "revalidate fragment" in record.fragment.provenance.machine_path
    ]
    if not handoff_note:
        handoff_note = project_snapshot.handoff_note or "resume from the latest proof state"
    return HandoffSnapshot(
        project_id=memory.project_id,
        project_snapshot=project_snapshot,
        verification_history=verification_history,
        queued_verification_fragments=queued_fragments,
        accepted_verification_results=[record for record in accepted_results if record is not None],
        stale_verification_fragments=stale_fragments,
        revalidation_requirements=revalidation_requirements,
        proof_debug_history=debug_records,
        suspicion_reports=[report for report in suspicion_reports if report is not None],
        resolved_bug_history=[report for report in resolved_bug_history if report is not None],
        evidence_chains=[chain for chain in evidence_chains if chain is not None],
        debug_tasks=[task for task in debug_tasks if task is not None],
        repair_decisions=[decision for decision in repair_decisions if decision is not None],
        repair_patterns=repair_patterns,
        failure_motifs=failure_motifs,
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
