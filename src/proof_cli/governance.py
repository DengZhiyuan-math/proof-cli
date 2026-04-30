from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel, Field

from .automation import (
    AutomationAction,
    AutomationActionType,
    AutomationExecutionMode,
    AutomationPolicyDecision,
    AutomationPolicyProfile,
    AutomationRun,
    AutomationTaskType,
    build_action as automation_build_action,
    build_automation_run as automation_build_automation_run,
    default_policy_profile,
)
from .automation_eval import (
    AutomationBenchmarkReplay,
    AutomationEvaluationRecord,
    replay_automation_benchmark,
)
from .domain import utc_now
from .domain_packs import DomainPack, DomainPackInstallation
from .proof_state import load_state, save_state
from .recommendations import CrossProjectRecommendationReport, recommend_cross_project_assets
from .reusable_assets import ReusableAsset, ReusableAssetReuseStatus
from .storage import ProjectStore, append_event


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


ASSET_HISTORY_PREFIX = "proof_asset:"
PACK_HISTORY_PREFIX = "proof_pack:"
POLICY_HISTORY_PREFIX = "proof_policy:"
RECOMMENDATION_HISTORY_PREFIX = "proof_recommendation:"
REUSE_HISTORY_PREFIX = "proof_reuse:"
AUTOMATION_HISTORY_PREFIX = "proof_automation:"
BENCHMARK_HISTORY_PREFIX = "proof_benchmark:"


class GovernanceAssetRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("asset_record"))
    project_id: str
    asset: ReusableAsset
    review_action: str = "publish"
    reviewer: str = "human"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class GovernancePackRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("pack_record"))
    project_id: str
    pack: DomainPack
    installation: DomainPackInstallation | None = None
    review_action: str = "install"
    reviewer: str = "human"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class GovernancePolicyRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("policy_record"))
    project_id: str
    profile: AutomationPolicyProfile
    decision: AutomationPolicyDecision | None = None
    reviewer: str = "human"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class GovernanceRecommendationRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("recommendation_record"))
    project_id: str
    report: CrossProjectRecommendationReport
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ReuseOutcome(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("reuse"))
    asset_id: str
    used_in_project: str
    outcome: str
    notes: str = ""
    reviewed_by_human: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class GovernanceReuseRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("reuse_record"))
    project_id: str
    outcome: ReuseOutcome
    created_at: datetime = Field(default_factory=utc_now)


class GovernanceAutomationRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("automation_record"))
    project_id: str
    run: AutomationRun
    review_status: str = "pending_review"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class GovernanceBenchmarkRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("benchmark_record"))
    project_id: str
    replay: AutomationBenchmarkReplay
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


T = TypeVar("T", bound=BaseModel)


def _append_record(
    store: ProjectStore,
    *,
    prefix: str,
    payload: BaseModel | Mapping[str, Any],
    event_kind: str,
    message: str,
    entity_id: str | None = None,
) -> None:
    state = load_state(store)
    if isinstance(payload, BaseModel):
        payload_json = payload.model_dump(mode="json")
    else:
        payload_json = dict(payload)
    state.session_history.append(f"{prefix}{json.dumps(payload_json, sort_keys=True)}")
    save_state(store, state, message=message)
    append_event(store, event_kind, message, entity_id=entity_id, payload=payload_json)


def _records_from_history(store: ProjectStore, prefix: str, model: type[T]) -> list[T]:
    state = load_state(store)
    records: list[T] = []
    for entry in state.session_history:
        if not entry.startswith(prefix):
            continue
        payload = entry.removeprefix(prefix)
        records.append(model.model_validate_json(payload))
    return records


def _latest_by(records: Iterable[T], key_fn) -> list[T]:
    seen: set[str] = set()
    ordered: list[T] = []
    for record in reversed(list(records)):
        key = str(key_fn(record))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(record)
    ordered.reverse()
    return ordered


def _parse_json_model(value: str, model: type[T]) -> T:
    return model.model_validate_json(value)


def _transition_asset(asset: ReusableAsset, review_action: str, *, reviewer: str, notes: str) -> ReusableAsset:
    normalized = review_action.strip().lower()
    if normalized in {"publish", "domain_shared", "publish_to_domain_shared"}:
        return asset.publish_to_domain_shared(reviewer=reviewer, notes=notes)
    if normalized in {"approve", "approve_for_reuse", "approved_reusable"}:
        return asset.approve_for_reuse(reviewer=reviewer, notes=notes)
    if normalized in {"private", "private_experimental"}:
        return asset.move_to_private_experimental(reviewer=reviewer, notes=notes)
    if normalized in {"reject", "rejected"}:
        return asset.reject_reuse(reviewer=reviewer, notes=notes)
    if normalized in {"deprecate", "deprecated"}:
        return asset.deprecate(reviewer=reviewer, notes=notes)
    return asset.model_copy(update={"review_notes": notes, "reviewed_by": reviewer})


def publish_reusable_asset(
    store: ProjectStore,
    asset: ReusableAsset,
    *,
    review_action: str = "publish",
    reviewer: str = "human",
    notes: str = "",
) -> GovernanceAssetRecord:
    state = load_state(store)
    updated_asset = _transition_asset(asset, review_action, reviewer=reviewer, notes=notes)
    record = GovernanceAssetRecord(
        project_id=state.project_id,
        asset=updated_asset,
        review_action=review_action,
        reviewer=reviewer,
        notes=notes,
    )
    _append_record(
        store,
        prefix=ASSET_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_asset_recorded",
        message=f"recorded reusable asset {updated_asset.id}",
        entity_id=updated_asset.id,
    )
    return record


def list_reusable_asset_records(store: ProjectStore, *, project_id: str = "", kind: str = "", status: str = "") -> list[GovernanceAssetRecord]:
    records = _records_from_history(store, ASSET_HISTORY_PREFIX, GovernanceAssetRecord)
    records = _latest_by(records, lambda record: record.asset.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    if kind:
        records = [record for record in records if record.asset.kind.value == kind]
    if status:
        records = [record for record in records if record.asset.reuse_status.value == status]
    return records


def get_reusable_asset_record(store: ProjectStore, asset_id: str) -> GovernanceAssetRecord | None:
    for record in reversed(_records_from_history(store, ASSET_HISTORY_PREFIX, GovernanceAssetRecord)):
        if record.asset.id == asset_id:
            return record
    return None


def install_domain_pack(
    store: ProjectStore,
    pack: DomainPack,
    *,
    installed_by: str = "human",
    project_tags: Sequence[str] = (),
    available_asset_ids: Sequence[str] = (),
    available_asset_kinds: Sequence[str] = (),
    notation_profile: str = "",
    notes: str = "",
) -> GovernancePackRecord:
    state = load_state(store)
    installation = pack.install(
        project_id=state.project_id,
        installed_by=installed_by,
        project_tags=project_tags,
        available_asset_ids=available_asset_ids,
        available_asset_kinds=available_asset_kinds,
        notation_profile=notation_profile,
        notes=notes,
    )
    record = GovernancePackRecord(
        project_id=state.project_id,
        pack=pack,
        installation=installation,
        review_action="install",
        reviewer=installed_by,
        notes=notes,
    )
    _append_record(
        store,
        prefix=PACK_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_pack_recorded",
        message=f"recorded domain pack {pack.id}",
        entity_id=pack.id,
    )
    return record


def update_domain_pack(
    store: ProjectStore,
    pack: DomainPack,
    *,
    reviewer: str = "human",
    notes: str = "",
) -> GovernancePackRecord:
    state = load_state(store)
    record = GovernancePackRecord(
        project_id=state.project_id,
        pack=pack,
        installation=None,
        review_action="update",
        reviewer=reviewer,
        notes=notes,
    )
    _append_record(
        store,
        prefix=PACK_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_pack_updated",
        message=f"updated domain pack {pack.id}",
        entity_id=pack.id,
    )
    return record


def list_domain_pack_records(store: ProjectStore, *, project_id: str = "") -> list[GovernancePackRecord]:
    records = _records_from_history(store, PACK_HISTORY_PREFIX, GovernancePackRecord)
    records = _latest_by(records, lambda record: record.pack.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    return records


def get_domain_pack_record(store: ProjectStore, pack_id: str) -> GovernancePackRecord | None:
    for record in reversed(_records_from_history(store, PACK_HISTORY_PREFIX, GovernancePackRecord)):
        if record.pack.id == pack_id:
            return record
    return None


def set_policy_profile(
    store: ProjectStore,
    profile: AutomationPolicyProfile,
    *,
    decision: AutomationPolicyDecision | None = None,
    reviewer: str = "human",
    notes: str = "",
) -> GovernancePolicyRecord:
    state = load_state(store)
    record = GovernancePolicyRecord(
        project_id=state.project_id,
        profile=profile,
        decision=decision,
        reviewer=reviewer,
        notes=notes,
    )
    _append_record(
        store,
        prefix=POLICY_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_policy_recorded",
        message=f"recorded policy profile {profile.name}",
        entity_id=profile.id,
    )
    return record


def list_policy_records(store: ProjectStore, *, project_id: str = "") -> list[GovernancePolicyRecord]:
    records = _records_from_history(store, POLICY_HISTORY_PREFIX, GovernancePolicyRecord)
    records = _latest_by(records, lambda record: record.profile.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    return records


def get_latest_policy_profile(store: ProjectStore, *, project_id: str = "") -> AutomationPolicyProfile | None:
    records = list_policy_records(store, project_id=project_id)
    return records[-1].profile if records else None


def record_cross_project_recommendation(
    store: ProjectStore,
    report: CrossProjectRecommendationReport,
    *,
    notes: str = "",
) -> GovernanceRecommendationRecord:
    state = load_state(store)
    record = GovernanceRecommendationRecord(project_id=state.project_id, report=report, notes=notes)
    _append_record(
        store,
        prefix=RECOMMENDATION_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_recommendation_recorded",
        message=f"recorded recommendation for {report.query}",
        entity_id=record.id,
    )
    return record


def list_recommendation_records(store: ProjectStore, *, project_id: str = "") -> list[GovernanceRecommendationRecord]:
    records = _records_from_history(store, RECOMMENDATION_HISTORY_PREFIX, GovernanceRecommendationRecord)
    records = _latest_by(records, lambda record: record.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    return records


def record_reuse_outcome(
    store: ProjectStore,
    *,
    asset_id: str,
    used_in_project: str,
    outcome: str,
    notes: str = "",
    reviewed_by_human: bool = True,
) -> GovernanceReuseRecord:
    state = load_state(store)
    record = GovernanceReuseRecord(
        project_id=state.project_id,
        outcome=ReuseOutcome(
            asset_id=asset_id,
            used_in_project=used_in_project,
            outcome=outcome,
            notes=notes,
            reviewed_by_human=reviewed_by_human,
        ),
    )
    _append_record(
        store,
        prefix=REUSE_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_reuse_recorded",
        message=f"recorded reuse outcome for {asset_id}",
        entity_id=asset_id,
    )
    return record


def list_reuse_records(store: ProjectStore, *, project_id: str = "", asset_id: str = "") -> list[GovernanceReuseRecord]:
    records = _records_from_history(store, REUSE_HISTORY_PREFIX, GovernanceReuseRecord)
    records = _latest_by(records, lambda record: record.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    if asset_id:
        records = [record for record in records if record.outcome.asset_id == asset_id]
    return records


def build_automation_run(
    *,
    project_id: str,
    scope: str,
    task_type: AutomationTaskType,
    action_specs: Sequence[Mapping[str, Any] | AutomationAction],
    policy_profile: AutomationPolicyProfile | None = None,
    execution_mode: AutomationExecutionMode = AutomationExecutionMode.supervised,
    notes: str = "",
    dry_run: bool | None = None,
    approval_required: bool | None = None,
) -> AutomationRun:
    actions: list[AutomationAction] = []
    for spec in action_specs:
        if isinstance(spec, AutomationAction):
            actions.append(spec)
            continue
        action_type = AutomationActionType(str(spec.get("action_type", AutomationActionType.execute_task.value)))
        action = automation_build_action(
            action_type,
            str(spec.get("description", action_type.value.replace("_", " "))),
            risk_level=spec.get("risk_level", "low"),
            reversible=bool(spec.get("reversible", True)),
            requires_review=bool(spec.get("requires_review", False)),
            payload=spec.get("payload"),
        )
        actions.append(action)
    run = automation_build_automation_run(
        project_id=project_id,
        scope=scope,
        task_type=task_type,
        actions=actions,
        policy_profile=policy_profile,
        execution_mode=execution_mode,
        notes=notes,
        dry_run=dry_run,
        approval_required=approval_required,
    )
    return run


def record_automation_run(
    store: ProjectStore,
    run: AutomationRun,
    *,
    review_status: str = "pending_review",
    notes: str = "",
) -> GovernanceAutomationRecord:
    state = load_state(store)
    record = GovernanceAutomationRecord(
        project_id=state.project_id,
        run=run,
        review_status=review_status,
        notes=notes,
    )
    _append_record(
        store,
        prefix=AUTOMATION_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_automation_recorded",
        message=f"recorded automation run {run.id}",
        entity_id=run.id,
    )
    return record


def list_automation_records(store: ProjectStore, *, project_id: str = "") -> list[GovernanceAutomationRecord]:
    records = _records_from_history(store, AUTOMATION_HISTORY_PREFIX, GovernanceAutomationRecord)
    records = _latest_by(records, lambda record: record.run.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    return records


def get_automation_record(store: ProjectStore, run_id: str) -> GovernanceAutomationRecord | None:
    for record in reversed(_records_from_history(store, AUTOMATION_HISTORY_PREFIX, GovernanceAutomationRecord)):
        if record.run.id == run_id:
            return record
    return None


def record_benchmark_replay(
    store: ProjectStore,
    replay: AutomationBenchmarkReplay,
    *,
    notes: str = "",
) -> GovernanceBenchmarkRecord:
    state = load_state(store)
    record = GovernanceBenchmarkRecord(project_id=state.project_id, replay=replay, notes=notes)
    _append_record(
        store,
        prefix=BENCHMARK_HISTORY_PREFIX,
        payload=record,
        event_kind="governance_benchmark_recorded",
        message=f"recorded automation benchmark {replay.benchmark_name}",
        entity_id=record.id,
    )
    return record


def list_benchmark_records(store: ProjectStore, *, project_id: str = "") -> list[GovernanceBenchmarkRecord]:
    records = _records_from_history(store, BENCHMARK_HISTORY_PREFIX, GovernanceBenchmarkRecord)
    records = _latest_by(records, lambda record: record.id)
    if project_id:
        records = [record for record in records if record.project_id == project_id]
    return records


def summarize_reusable_asset(record: GovernanceAssetRecord) -> str:
    asset = record.asset
    scope_text = f" scope={asset.team_scope}" if getattr(asset, "team_scope", "") else ""
    return (
        f"{asset.id}: {asset.name} [{asset.kind.value}/{asset.reuse_status.value}/{asset.trust_level.value}] "
        f"project={record.project_id} review={record.review_action}{scope_text}"
    )


def summarize_domain_pack(record: GovernancePackRecord) -> str:
    installation = record.installation
    install_text = f" install={installation.status.value}" if installation is not None else ""
    scope_text = f" scope={record.pack.team_scope}" if getattr(record.pack, "team_scope", "") else ""
    return (
        f"{record.pack.id}: {record.pack.name} v{record.pack.version} "
        f"[{record.pack.review_status.value}/{record.pack.trust_level.value}]{install_text} project={record.project_id}{scope_text}"
    )


def summarize_policy_record(record: GovernancePolicyRecord) -> str:
    decision_text = f" decision={record.decision.value}" if record.decision is not None else ""
    return f"{record.profile.name}: project={record.project_id}{decision_text} allow={','.join(action.value for action in record.profile.allowed_actions) or 'none'}"


def summarize_recommendation_record(record: GovernanceRecommendationRecord) -> str:
    top = record.report.recommendations[0] if record.report.recommendations else None
    if top is None:
        return f"{record.report.current_project_id}: {record.report.query} [no recommendations]"
    return (
        f"{record.report.current_project_id}: {record.report.query} -> "
        f"{top.candidate_id} [{top.source_kind.value}] score={top.total_score:.2f}"
    )


def summarize_reuse_record(record: GovernanceReuseRecord) -> str:
    outcome = record.outcome
    return (
        f"{outcome.asset_id}: used in {outcome.used_in_project} [{outcome.outcome}] "
        f"reviewed={'yes' if outcome.reviewed_by_human else 'no'}"
    )


def summarize_automation_record(record: GovernanceAutomationRecord) -> str:
    run = record.run
    return f"{run.id}: {run.task_type.value} [{run.status.value}/{record.review_status}] scope={run.scope}"


def summarize_benchmark_record(record: GovernanceBenchmarkRecord) -> str:
    replay = record.replay
    interpretation = replay.comparison.overall_interpretation if replay.comparison is not None else "n/a"
    return f"{replay.benchmark_name}: scenario={replay.scenario_id} [{interpretation}] project={record.project_id}"


def render_json(model: BaseModel | Mapping[str, Any]) -> str:
    if isinstance(model, BaseModel):
        return model.model_dump_json(indent=2)
    return json.dumps(dict(model), indent=2, sort_keys=True)


__all__ = [
    "ASSET_HISTORY_PREFIX",
    "AUTOMATION_HISTORY_PREFIX",
    "BENCHMARK_HISTORY_PREFIX",
    "GovernanceAssetRecord",
    "GovernanceAutomationRecord",
    "GovernanceBenchmarkRecord",
    "GovernancePackRecord",
    "GovernancePolicyRecord",
    "GovernanceRecommendationRecord",
    "GovernanceReuseRecord",
    "PACK_HISTORY_PREFIX",
    "POLICY_HISTORY_PREFIX",
    "RECOMMENDATION_HISTORY_PREFIX",
    "REUSE_HISTORY_PREFIX",
    "ReuseOutcome",
    "build_automation_run",
    "get_automation_record",
    "get_domain_pack_record",
    "get_latest_policy_profile",
    "get_reusable_asset_record",
    "install_domain_pack",
    "list_automation_records",
    "list_benchmark_records",
    "list_domain_pack_records",
    "list_policy_records",
    "list_recommendation_records",
    "list_reusable_asset_records",
    "list_reuse_records",
    "publish_reusable_asset",
    "record_automation_run",
    "record_benchmark_replay",
    "record_cross_project_recommendation",
    "record_reuse_outcome",
    "render_json",
    "set_policy_profile",
    "summarize_automation_record",
    "summarize_benchmark_record",
    "summarize_domain_pack",
    "summarize_policy_record",
    "summarize_recommendation_record",
    "summarize_reusable_asset",
    "summarize_reuse_record",
    "update_domain_pack",
]
