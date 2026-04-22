from __future__ import annotations

import pytest

from proof_cli.automation import (
    AutomationActionStatus,
    AutomationActionType,
    AutomationExecutionMode,
    AutomationPolicyDecision,
    AutomationRunStatus,
    AutomationTaskType,
    AutomationTraceKind,
    AutomationRiskLevel,
    build_action,
    build_automation_run,
    default_policy_profile,
)


def test_automation_run_round_trip_preserves_explicit_trace_and_modes() -> None:
    policy = default_policy_profile()
    run = build_automation_run(
        project_id="proj_alpha",
        scope="thm_main",
        task_type=AutomationTaskType.obligation_splitting,
        policy_profile=policy,
        execution_mode=AutomationExecutionMode.supervised,
        actions=[
            build_action(AutomationActionType.inspect_state, "inspect current theorem state"),
            build_action(AutomationActionType.retrieve_assets, "retrieve local and shared assets"),
            build_action(AutomationActionType.generate_plan, "assemble a bounded action plan"),
        ],
        notes="bounded supervised run",
    )

    reloaded = run.model_validate_json(run.model_dump_json())

    assert reloaded == run
    assert reloaded.execution_mode == AutomationExecutionMode.supervised
    assert reloaded.dry_run is False
    assert reloaded.approval_required is False
    assert reloaded.status == AutomationRunStatus.planned
    assert reloaded.trace[0].kind == AutomationTraceKind.action_planned
    assert reloaded.trace[-1].kind == AutomationTraceKind.run_created
    assert [action.sequence_index for action in reloaded.planned_actions] == [0, 1, 2]
    assert [action.status for action in reloaded.planned_actions] == [AutomationActionStatus.planned] * 3
    assert run.policy_profile.decide(AutomationActionType.inspect_state) == AutomationPolicyDecision.allow

    executed = reloaded.execute()

    assert executed.status == AutomationRunStatus.completed
    assert executed.completed_at is not None
    assert executed.next_action_index == 3
    assert len(executed.executed_actions) == 3
    assert [action.status for action in executed.planned_actions] == [AutomationActionStatus.completed] * 3
    assert executed.trace[-1].kind == AutomationTraceKind.run_completed


def test_automation_run_dry_run_simulates_actions_without_side_effects() -> None:
    policy = default_policy_profile(execution_mode=AutomationExecutionMode.dry_run)
    run = build_automation_run(
        project_id="proj_beta",
        scope="obl_17",
        task_type=AutomationTaskType.low_risk_translation,
        policy_profile=policy,
        execution_mode=AutomationExecutionMode.dry_run,
        dry_run=True,
        actions=[
            build_action(
                AutomationActionType.execute_task,
                "translate the obligation into an intermediate fragment",
                risk_level=AutomationRiskLevel.medium,
                requires_review=True,
            ),
            build_action(AutomationActionType.record_trace, "record the planned trace"),
        ],
        notes="dry run should remain auditable",
    )

    assert run.dry_run is True
    assert run.execution_mode == AutomationExecutionMode.dry_run
    assert run.policy_profile.decide(
        AutomationActionType.execute_task,
        risk_level=AutomationRiskLevel.medium,
        reversible=True,
        execution_mode=AutomationExecutionMode.dry_run,
    ) == AutomationPolicyDecision.simulate

    executed = run.execute()

    assert executed.status == AutomationRunStatus.completed
    assert all(action.status == AutomationActionStatus.simulated for action in executed.planned_actions)
    assert executed.executed_actions[0].status == AutomationActionStatus.simulated
    assert executed.trace[-2].kind == AutomationTraceKind.action_simulated
    assert executed.trace[-1].kind == AutomationTraceKind.run_completed
    assert executed.result_summary == "bounded automation completed"


def test_automation_run_supports_review_gating_interrupt_and_rollback() -> None:
    policy = default_policy_profile(execution_mode=AutomationExecutionMode.approval_required)
    run = build_automation_run(
        project_id="proj_gamma",
        scope="thm_review",
        task_type=AutomationTaskType.repetitive_repair_attempts,
        policy_profile=policy,
        execution_mode=AutomationExecutionMode.approval_required,
        approval_required=True,
        actions=[
            build_action(
                AutomationActionType.publish_reusable_outcome,
                "publish the repaired pattern as reusable",
                risk_level=AutomationRiskLevel.high,
                reversible=False,
                requires_review=True,
            ),
        ],
        notes="approval should gate the first action",
    )

    waiting = run.execute()

    assert waiting.status == AutomationRunStatus.waiting_for_review
    assert waiting.next_action_index == 0
    assert waiting.planned_actions[0].status == AutomationActionStatus.awaiting_approval
    assert waiting.trace[-1].kind == AutomationTraceKind.action_waiting_for_review

    approved = waiting.approve_action(waiting.planned_actions[0].id, reviewer="researcher", rationale="reviewed by hand")
    resumed = approved.resume()

    assert len(resumed.approvals) == 1
    assert resumed.approvals[0].reviewer == "researcher"
    assert resumed.status == AutomationRunStatus.completed
    assert resumed.planned_actions[0].approval_id is not None
    assert resumed.planned_actions[0].status == AutomationActionStatus.completed
    assert resumed.trace[-1].kind == AutomationTraceKind.run_completed


def test_automation_run_can_be_interrupted_and_rolled_back() -> None:
    policy = default_policy_profile(execution_mode=AutomationExecutionMode.supervised)
    run = build_automation_run(
        project_id="proj_delta",
        scope="thm_interrupt",
        task_type=AutomationTaskType.blocker_triage,
        policy_profile=policy,
        execution_mode=AutomationExecutionMode.supervised,
        actions=[
            build_action(AutomationActionType.inspect_state, "inspect the live proof state"),
            build_action(AutomationActionType.retrieve_assets, "retrieve reusable proof assets"),
        ],
        notes="interruption and rollback should remain auditable",
    )

    interrupted = run.execute(interrupt_after=1)

    assert interrupted.status == AutomationRunStatus.interrupted
    assert interrupted.interruptions[-1].resume_from_action_index == 1
    assert interrupted.planned_actions[0].status == AutomationActionStatus.completed
    assert interrupted.planned_actions[1].status == AutomationActionStatus.planned
    assert interrupted.trace[-1].kind == AutomationTraceKind.run_interrupted

    rolled_back = interrupted.rollback(
        reason="revert bounded automation after interruption",
        action_ids=[interrupted.planned_actions[0].id],
    )

    assert rolled_back.status == AutomationRunStatus.rolled_back
    assert rolled_back.planned_actions[0].status == AutomationActionStatus.rolled_back
    assert rolled_back.rollbacks[-1].action_ids == [interrupted.planned_actions[0].id]
    assert rolled_back.trace[-1].kind == AutomationTraceKind.run_rolled_back


def test_automation_policy_blocks_forbidden_actions() -> None:
    policy = default_policy_profile()
    policy = policy.model_copy(
        update={
            "forbidden_actions": [AutomationActionType.interrupt],
        }
    )
    decision = policy.decide(AutomationActionType.interrupt)

    assert decision == AutomationPolicyDecision.deny


def test_automation_run_rejects_action_over_capacity() -> None:
    policy = default_policy_profile()
    run = build_automation_run(
        project_id="proj_delta",
        scope="thm_capacity",
        task_type=AutomationTaskType.blocker_triage,
        policy_profile=policy,
        actions=[],
        notes="capacity guard",
    )

    for index in range(run.max_actions):
        run = run.add_action(build_action(AutomationActionType.inspect_state, f"action {index}"))

    with pytest.raises(ValueError, match="maximum"):
        run.add_action(build_action(AutomationActionType.inspect_state, "overflow"))
