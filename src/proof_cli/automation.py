from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
import uuid
from typing import Any

from pydantic import BaseModel, Field

from .domain import utc_now


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class AutomationTaskType(str, Enum):
    theorem_application_checks = "theorem_application_checks"
    omission_elaboration = "omission_elaboration"
    obligation_splitting = "obligation_splitting"
    literature_grounded_contract_suggestion = "literature_grounded_contract_suggestion"
    blocker_triage = "blocker_triage"
    debug_task_generation = "debug_task_generation"
    snapshot_handoff_generation = "snapshot_handoff_generation"
    low_risk_translation = "low_risk_translation"
    repetitive_repair_attempts = "repetitive_repair_attempts"


class AutomationExecutionMode(str, Enum):
    dry_run = "dry_run"
    approval_required = "approval_required"
    supervised = "supervised"


class AutomationRiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    trust_sensitive = "trust_sensitive"


class AutomationActionType(str, Enum):
    inspect_state = "inspect_state"
    retrieve_assets = "retrieve_assets"
    check_policy = "check_policy"
    generate_plan = "generate_plan"
    request_review = "request_review"
    execute_task = "execute_task"
    record_trace = "record_trace"
    publish_reusable_outcome = "publish_reusable_outcome"
    rollback = "rollback"
    interrupt = "interrupt"


class AutomationPolicyDecision(str, Enum):
    allow = "allow"
    requires_review = "requires_review"
    deny = "deny"
    simulate = "simulate"


class AutomationActionStatus(str, Enum):
    planned = "planned"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    simulated = "simulated"
    blocked = "blocked"
    rejected = "rejected"
    interrupted = "interrupted"
    rolled_back = "rolled_back"


class AutomationRunStatus(str, Enum):
    planned = "planned"
    running = "running"
    waiting_for_review = "waiting_for_review"
    interrupted = "interrupted"
    rolled_back = "rolled_back"
    completed = "completed"
    rejected = "rejected"


class AutomationTraceKind(str, Enum):
    run_created = "run_created"
    run_started = "run_started"
    policy_checked = "policy_checked"
    action_planned = "action_planned"
    action_started = "action_started"
    action_completed = "action_completed"
    action_simulated = "action_simulated"
    action_waiting_for_review = "action_waiting_for_review"
    action_approved = "action_approved"
    action_rejected = "action_rejected"
    run_interrupted = "run_interrupted"
    run_rolled_back = "run_rolled_back"
    run_completed = "run_completed"


class AutomationApproval(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("approval"))
    run_id: str
    action_id: str
    reviewer: str
    rationale: str = ""
    approved: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class AutomationInterruptRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("interrupt"))
    run_id: str
    reason: str
    interrupted_by: str = "system"
    resume_from_action_index: int = 0
    created_at: datetime = Field(default_factory=utc_now)


class AutomationRollbackRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("rollback"))
    run_id: str
    reason: str
    action_ids: list[str] = Field(default_factory=list)
    rolled_back_by: str = "system"
    created_at: datetime = Field(default_factory=utc_now)


class AutomationTraceEntry(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("trace"))
    kind: AutomationTraceKind
    message: str
    action_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AutomationPolicyProfile(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("policy"))
    name: str
    execution_mode: AutomationExecutionMode = AutomationExecutionMode.supervised
    allowed_actions: list[AutomationActionType] = Field(default_factory=list)
    approval_required_for: list[AutomationActionType] = Field(default_factory=list)
    forbidden_actions: list[AutomationActionType] = Field(default_factory=list)
    max_actions_per_run: int = 8
    allow_reversible_only: bool = False
    notes: str = ""

    def decide(
        self,
        action_type: AutomationActionType,
        *,
        risk_level: AutomationRiskLevel = AutomationRiskLevel.low,
        reversible: bool = True,
        execution_mode: AutomationExecutionMode | None = None,
    ) -> AutomationPolicyDecision:
        mode = execution_mode or self.execution_mode
        if action_type in self.forbidden_actions:
            return AutomationPolicyDecision.deny
        if mode == AutomationExecutionMode.dry_run:
            return AutomationPolicyDecision.simulate
        if self.allowed_actions and action_type not in self.allowed_actions:
            return AutomationPolicyDecision.deny
        if self.allow_reversible_only and not reversible:
            return AutomationPolicyDecision.requires_review
        if mode == AutomationExecutionMode.approval_required:
            return AutomationPolicyDecision.requires_review
        if action_type in self.approval_required_for:
            return AutomationPolicyDecision.requires_review
        if risk_level in {AutomationRiskLevel.high, AutomationRiskLevel.trust_sensitive}:
            return AutomationPolicyDecision.requires_review
        return AutomationPolicyDecision.allow


class AutomationAction(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("act"))
    action_type: AutomationActionType
    description: str
    status: AutomationActionStatus = AutomationActionStatus.planned
    risk_level: AutomationRiskLevel = AutomationRiskLevel.low
    reversible: bool = True
    requires_review: bool = False
    policy_decision: AutomationPolicyDecision = AutomationPolicyDecision.allow
    sequence_index: int = 0
    reviewer: str = ""
    approval_id: str | None = None
    review_notes: str = ""
    result_summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def mark(
        self,
        *,
        status: AutomationActionStatus | None = None,
        policy_decision: AutomationPolicyDecision | None = None,
        requires_review: bool | None = None,
        reviewer: str | None = None,
        approval_id: str | None = None,
        review_notes: str | None = None,
        result_summary: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> "AutomationAction":
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if status is not None:
            updates["status"] = status
        if policy_decision is not None:
            updates["policy_decision"] = policy_decision
        if requires_review is not None:
            updates["requires_review"] = requires_review
        if reviewer is not None:
            updates["reviewer"] = reviewer
        if approval_id is not None:
            updates["approval_id"] = approval_id
        if review_notes is not None:
            updates["review_notes"] = review_notes
        if result_summary is not None:
            updates["result_summary"] = result_summary
        if payload is not None:
            updates["payload"] = dict(payload)
        return self.model_copy(update=updates)


class AutomationRun(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("auto"))
    project_id: str
    scope: str
    task_type: AutomationTaskType
    policy_profile: AutomationPolicyProfile
    execution_mode: AutomationExecutionMode = AutomationExecutionMode.supervised
    status: AutomationRunStatus = AutomationRunStatus.planned
    planned_actions: list[AutomationAction] = Field(default_factory=list)
    executed_actions: list[AutomationAction] = Field(default_factory=list)
    approvals: list[AutomationApproval] = Field(default_factory=list)
    interruptions: list[AutomationInterruptRecord] = Field(default_factory=list)
    rollbacks: list[AutomationRollbackRecord] = Field(default_factory=list)
    trace: list[AutomationTraceEntry] = Field(default_factory=list)
    result_summary: str = ""
    notes: str = ""
    dry_run: bool = False
    approval_required: bool = False
    max_actions: int = 8
    next_action_index: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    interrupted_at: datetime | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def _transition(self, **updates: Any) -> "AutomationRun":
        updates["updated_at"] = utc_now()
        return self.model_copy(update=updates)

    def _append_trace(
        self,
        kind: AutomationTraceKind,
        message: str,
        *,
        action_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> "AutomationRun":
        entry = AutomationTraceEntry(
            kind=kind,
            message=message,
            action_id=action_id,
            payload=dict(payload or {}),
        )
        return self._transition(trace=[*self.trace, entry])

    def _replace_action(self, action: AutomationAction) -> "AutomationRun":
        updated_actions = [action if existing.id == action.id else existing for existing in self.planned_actions]
        return self._transition(planned_actions=updated_actions)

    def add_action(self, action: AutomationAction) -> "AutomationRun":
        if len(self.planned_actions) >= self.max_actions:
            raise ValueError(f"run {self.id} already has the maximum of {self.max_actions} actions")
        action = action.mark(
            status=AutomationActionStatus.planned,
            policy_decision=AutomationPolicyDecision.allow,
            requires_review=action.requires_review,
        )
        action = action.model_copy(update={"sequence_index": len(self.planned_actions)})
        return self._transition(
            planned_actions=[*self.planned_actions, action],
            trace=[
                *self.trace,
                AutomationTraceEntry(
                    kind=AutomationTraceKind.action_planned,
                    message=f"planned {action.action_type.value}: {action.description}",
                    action_id=action.id,
                ),
            ],
        )

    def add_actions(self, actions: Sequence[AutomationAction]) -> "AutomationRun":
        run = self
        for action in actions:
            run = run.add_action(action)
        return run

    def start(self) -> "AutomationRun":
        if self.status != AutomationRunStatus.planned:
            return self
        return self._transition(
            status=AutomationRunStatus.running,
            started_at=self.started_at or utc_now(),
            trace=[
                *self.trace,
                AutomationTraceEntry(
                    kind=AutomationTraceKind.run_started,
                    message=f"run {self.id} started in {self.execution_mode.value} mode",
                ),
            ],
        )

    def approve_action(self, action_id: str, *, reviewer: str, rationale: str = "") -> "AutomationRun":
        action = next((item for item in self.planned_actions if item.id == action_id), None)
        if action is None:
            raise ValueError(f"action {action_id} not found")
        approval = AutomationApproval(
            run_id=self.id,
            action_id=action_id,
            reviewer=reviewer,
            rationale=rationale,
        )
        updated_action = action.mark(
            reviewer=reviewer,
            approval_id=approval.id,
            review_notes=rationale,
            requires_review=False,
        )
        run = self._replace_action(updated_action)
        return run._transition(
            approvals=[*self.approvals, approval],
            trace=[
                *run.trace,
                AutomationTraceEntry(
                    kind=AutomationTraceKind.action_approved,
                    message=f"approved {action_id} by {reviewer}",
                    action_id=action_id,
                    payload={"rationale": rationale},
                ),
            ],
        )

    def interrupt(
        self,
        *,
        reason: str,
        interrupted_by: str = "system",
        resume_from_action_index: int | None = None,
    ) -> "AutomationRun":
        index = self.next_action_index if resume_from_action_index is None else resume_from_action_index
        record = AutomationInterruptRecord(
            run_id=self.id,
            reason=reason,
            interrupted_by=interrupted_by,
            resume_from_action_index=index,
        )
        return self._transition(
            status=AutomationRunStatus.interrupted,
            interruptions=[*self.interruptions, record],
            interrupted_at=self.interrupted_at or utc_now(),
            next_action_index=index,
            trace=[
                *self.trace,
                AutomationTraceEntry(
                    kind=AutomationTraceKind.run_interrupted,
                    message=reason,
                    payload={"interrupted_by": interrupted_by, "resume_from_action_index": index},
                ),
            ],
        )

    def rollback(
        self,
        *,
        reason: str,
        action_ids: Sequence[str] = (),
        rolled_back_by: str = "system",
    ) -> "AutomationRun":
        action_id_set = set(action_ids)
        updated_actions = [
            action.mark(status=AutomationActionStatus.rolled_back)
            if action.id in action_id_set
            else action
            for action in self.planned_actions
        ]
        record = AutomationRollbackRecord(
            run_id=self.id,
            reason=reason,
            action_ids=list(action_ids),
            rolled_back_by=rolled_back_by,
        )
        return self._transition(
            status=AutomationRunStatus.rolled_back,
            planned_actions=updated_actions,
            rollbacks=[*self.rollbacks, record],
            rolled_back_at=self.rolled_back_at or utc_now(),
            trace=[
                *self.trace,
                AutomationTraceEntry(
                    kind=AutomationTraceKind.run_rolled_back,
                    message=reason,
                    payload={"rolled_back_by": rolled_back_by, "action_ids": list(action_ids)},
                ),
            ],
        )

    def _record_executed_action(self, action: AutomationAction) -> "AutomationRun":
        return self._transition(executed_actions=[*self.executed_actions, action], next_action_index=action.sequence_index + 1)

    def execute(
        self,
        *,
        approvals: Mapping[str, Any] | None = None,
        interrupt_after: int | None = None,
    ) -> "AutomationRun":
        approvals = dict(approvals or {})
        run = self.start() if self.status == AutomationRunStatus.planned else self
        if run.status in {AutomationRunStatus.completed, AutomationRunStatus.rejected, AutomationRunStatus.rolled_back}:
            return run

        processed_this_call = 0
        current = run
        start_index = current.next_action_index

        for action in current.planned_actions[start_index:]:
            if interrupt_after is not None and processed_this_call >= interrupt_after:
                return current.interrupt(
                    reason=f"interrupt requested after {interrupt_after} action(s)",
                    resume_from_action_index=action.sequence_index,
                )

            processed_this_call += 1
            reviewer_override = approvals.get(action.id)
            already_approved = action.approval_id is not None
            decision = current.policy_profile.decide(
                action.action_type,
                risk_level=action.risk_level,
                reversible=action.reversible,
                execution_mode=current.execution_mode,
            )
            if current.approval_required:
                decision = AutomationPolicyDecision.requires_review
            if already_approved and decision == AutomationPolicyDecision.requires_review:
                decision = AutomationPolicyDecision.allow
            current = current._append_trace(
                AutomationTraceKind.policy_checked,
                f"policy decision for {action.id}: {decision.value}",
                action_id=action.id,
                payload={
                    "action_type": action.action_type.value,
                    "risk_level": action.risk_level.value,
                    "decision": decision.value,
                },
            )

            if decision == AutomationPolicyDecision.deny:
                updated_action = action.mark(
                    status=AutomationActionStatus.rejected,
                    policy_decision=decision,
                    requires_review=True,
                    review_notes="blocked by policy",
                )
                current = current._replace_action(updated_action)
                current = current._transition(
                    status=AutomationRunStatus.rejected,
                    trace=[
                        *current.trace,
                        AutomationTraceEntry(
                            kind=AutomationTraceKind.action_rejected,
                            message=f"rejected {action.id} by policy",
                            action_id=action.id,
                            payload={"decision": decision.value},
                        ),
                    ],
                )
                return current

            if current.execution_mode == AutomationExecutionMode.dry_run or decision == AutomationPolicyDecision.simulate:
                updated_action = action.mark(
                    status=AutomationActionStatus.simulated,
                    policy_decision=decision,
                    requires_review=decision == AutomationPolicyDecision.requires_review,
                    result_summary="simulated without side effects",
                )
                current = current._replace_action(updated_action)
                current = current._record_executed_action(updated_action)
                current = current._transition(
                    trace=[
                        *current.trace,
                        AutomationTraceEntry(
                            kind=AutomationTraceKind.action_simulated,
                            message=f"simulated {action.id}",
                            action_id=action.id,
                            payload={"decision": decision.value},
                        ),
                    ],
                )
                continue

            if decision == AutomationPolicyDecision.requires_review:
                if reviewer_override is not None:
                    reviewer_name = "human" if isinstance(reviewer_override, bool) else str(reviewer_override)
                    current = current.approve_action(action.id, reviewer=reviewer_name, rationale="pre-approved")
                    action = next(item for item in current.planned_actions if item.id == action.id)
                else:
                    updated_action = action.mark(
                        status=AutomationActionStatus.awaiting_approval,
                        policy_decision=decision,
                        requires_review=True,
                    )
                    current = current._replace_action(updated_action)
                    current = current._transition(
                        status=AutomationRunStatus.waiting_for_review,
                        next_action_index=action.sequence_index,
                        trace=[
                            *current.trace,
                            AutomationTraceEntry(
                                kind=AutomationTraceKind.action_waiting_for_review,
                                message=f"waiting on review for {action.id}",
                                action_id=action.id,
                                payload={"decision": decision.value},
                            ),
                        ],
                    )
                    return current

            updated_action = action.mark(
                status=AutomationActionStatus.completed,
                policy_decision=decision,
                requires_review=decision == AutomationPolicyDecision.requires_review,
                result_summary=action.result_summary or "completed bounded automation step",
            )
            current = current._replace_action(updated_action)
            current = current._record_executed_action(updated_action)
            current = current._transition(
                trace=[
                    *current.trace,
                    AutomationTraceEntry(
                        kind=AutomationTraceKind.action_completed,
                        message=f"completed {action.id}",
                        action_id=action.id,
                        payload={"decision": decision.value},
                    ),
                ],
            )

        return current._transition(
            status=AutomationRunStatus.completed,
            completed_at=current.completed_at or utc_now(),
            next_action_index=len(current.planned_actions),
            result_summary=current.result_summary or "bounded automation completed",
            trace=[
                *current.trace,
                AutomationTraceEntry(
                    kind=AutomationTraceKind.run_completed,
                    message=f"run {current.id} completed",
                    payload={"executed_actions": [action.id for action in current.executed_actions]},
                ),
            ],
        )

    def resume(
        self,
        *,
        approvals: Mapping[str, bool] | None = None,
        interrupt_after: int | None = None,
    ) -> "AutomationRun":
        if self.status not in {AutomationRunStatus.interrupted, AutomationRunStatus.waiting_for_review}:
            return self
        return self.execute(approvals=approvals, interrupt_after=interrupt_after)


def default_policy_profile(
    *,
    name: str = "bounded_local_reasoning",
    execution_mode: AutomationExecutionMode = AutomationExecutionMode.supervised,
) -> AutomationPolicyProfile:
    return AutomationPolicyProfile(
        name=name,
        execution_mode=execution_mode,
        allowed_actions=[
            AutomationActionType.inspect_state,
            AutomationActionType.retrieve_assets,
            AutomationActionType.check_policy,
            AutomationActionType.generate_plan,
            AutomationActionType.request_review,
            AutomationActionType.execute_task,
            AutomationActionType.record_trace,
            AutomationActionType.publish_reusable_outcome,
            AutomationActionType.rollback,
            AutomationActionType.interrupt,
        ],
        approval_required_for=[
            AutomationActionType.publish_reusable_outcome,
            AutomationActionType.execute_task,
            AutomationActionType.rollback,
        ],
        forbidden_actions=[],
        max_actions_per_run=8,
        allow_reversible_only=False,
        notes="default bounded supervised automation policy",
    )


def build_automation_run(
    *,
    project_id: str,
    scope: str,
    task_type: AutomationTaskType,
    actions: Sequence[AutomationAction],
    policy_profile: AutomationPolicyProfile | None = None,
    execution_mode: AutomationExecutionMode = AutomationExecutionMode.supervised,
    notes: str = "",
    dry_run: bool | None = None,
    approval_required: bool | None = None,
) -> AutomationRun:
    profile = policy_profile or default_policy_profile(execution_mode=execution_mode)
    run = AutomationRun(
        project_id=project_id,
        scope=scope,
        task_type=task_type,
        policy_profile=profile,
        execution_mode=execution_mode,
        dry_run=dry_run if dry_run is not None else execution_mode == AutomationExecutionMode.dry_run,
        approval_required=approval_required if approval_required is not None else execution_mode == AutomationExecutionMode.approval_required,
        max_actions=profile.max_actions_per_run,
        notes=notes,
    )
    run = run.add_actions(actions)
    return run._append_trace(
        AutomationTraceKind.run_created,
        f"created automation run for {task_type.value}",
        payload={
            "project_id": project_id,
            "scope": scope,
            "execution_mode": execution_mode.value,
            "planned_actions": len(actions),
        },
    )


def build_action(
    action_type: AutomationActionType,
    description: str,
    *,
    risk_level: AutomationRiskLevel = AutomationRiskLevel.low,
    reversible: bool = True,
    requires_review: bool = False,
    payload: Mapping[str, Any] | None = None,
) -> AutomationAction:
    return AutomationAction(
        action_type=action_type,
        description=description,
        risk_level=risk_level,
        reversible=reversible,
        requires_review=requires_review,
        payload=dict(payload or {}),
    )


__all__ = [
    "AutomationAction",
    "AutomationActionStatus",
    "AutomationActionType",
    "AutomationApproval",
    "AutomationExecutionMode",
    "AutomationInterruptRecord",
    "AutomationPolicyDecision",
    "AutomationPolicyProfile",
    "AutomationRollbackRecord",
    "AutomationRiskLevel",
    "AutomationRun",
    "AutomationRunStatus",
    "AutomationTaskType",
    "AutomationTraceEntry",
    "AutomationTraceKind",
    "build_action",
    "build_automation_run",
    "default_policy_profile",
]
