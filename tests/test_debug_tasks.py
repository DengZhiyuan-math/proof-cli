from pathlib import Path

from proof_cli.bugs import ProofBugReport, ProofBugSeverity, ProofBugStatus, ProofBugType
from proof_cli.debug_tasks import (
    ProofDebugTask,
    ProofDebugTaskBatch,
    ProofDebugTaskPriority,
    ProofDebugTaskStatus,
    ProofDebugTaskType,
    debug_task_batch_from_reports,
    generate_debug_tasks,
)
from proof_cli.evidence import EvidenceChain, EvidenceReviewRecommendation


def test_debug_tasks_link_to_suspected_bug_reports_and_round_trip() -> None:
    report = ProofBugReport(
        bug_type=ProofBugType.assumption_mismatch,
        description="theorem thm_main is missing assumptions: A",
        severity=ProofBugSeverity.high,
        confidence=0.94,
        status=ProofBugStatus.suspected,
        linked_contract_ids=["thm_main"],
        linked_obligation_ids=["obl_main"],
        linked_blocker_ids=["blk_main"],
        reasoning_path=["thm_main", "assumption_check", "review_gate"],
        missing_conditions=["A"],
        evidence=["callability check: missing assumptions: A"],
    )
    chain = EvidenceChain(
        bug_report_id=report.id,
        bug_type=report.bug_type.value,
        bug_status=report.status,
        description=report.description,
        reasoning_path=report.reasoning_path,
        missing_conditions=report.missing_conditions,
        review_recommendation=EvidenceReviewRecommendation.block,
        linked_contract_ids=report.linked_contract_ids,
        linked_obligation_ids=report.linked_obligation_ids,
        linked_blocker_ids=report.linked_blocker_ids,
        evidence=report.evidence,
    )

    tasks = generate_debug_tasks([report], [chain])
    batch = debug_task_batch_from_reports([report], [chain], theorem_id="thm_main")
    reloaded = [ProofDebugTask.model_validate_json(task.model_dump_json()) for task in tasks]

    assert len(tasks) == 2
    assert batch.theorem_id == "thm_main"
    assert batch.task_ids() == [task.id for task in batch.tasks]
    assert batch.priorities() == [task.priority.value for task in batch.tasks]
    assert batch.model_validate_json(batch.model_dump_json()) == batch
    assert reloaded == tasks

    first_task = tasks[0]
    assert first_task.bug_report_id == report.id
    assert first_task.bug_type == ProofBugType.assumption_mismatch.value
    assert first_task.bug_status == ProofBugStatus.suspected
    assert first_task.status == ProofDebugTaskStatus.pending
    assert first_task.priority == ProofDebugTaskPriority.high
    assert first_task.evidence_chain_id == chain.id
    assert first_task.review_recommendation == EvidenceReviewRecommendation.block
    assert first_task.linked_contract_ids == ["thm_main"]
    assert first_task.linked_obligation_ids == ["obl_main"]
    assert first_task.linked_blocker_ids == ["blk_main"]
    assert first_task.reasoning_path == ["thm_main", "assumption_check", "review_gate"]
    assert first_task.missing_conditions == ["A"]
    assert "assumption" in first_task.task_type.value
    assert first_task.candidate_repairs


def test_debug_task_generation_prioritizes_repair_work_by_bug_type() -> None:
    omission_report = ProofBugReport(
        bug_type=ProofBugType.omitted_side_condition,
        description="compressed proof hides a required side condition",
        severity=ProofBugSeverity.critical,
        confidence=0.91,
        status=ProofBugStatus.suspected,
        linked_contract_ids=["thm_gap"],
        linked_obligation_ids=["obl_gap"],
        missing_conditions=["hidden side condition"],
        evidence=["checker output: unresolved omission gaps: obl_gap"],
    )
    cycle_report = ProofBugReport(
        bug_type=ProofBugType.circular_dependency,
        description="theorem thm_cycle depends on itself through lemmas",
        severity=ProofBugSeverity.high,
        confidence=0.88,
        status=ProofBugStatus.under_review,
        linked_contract_ids=["thm_cycle"],
        reasoning_path=["thm_cycle", "cycle_detection"],
        evidence=["checker output: dependency cycle detected"],
    )
    dismissed_report = ProofBugReport(
        bug_type=ProofBugType.notation_drift,
        description="notation drift was explained away",
        severity=ProofBugSeverity.low,
        confidence=0.3,
        status=ProofBugStatus.dismissed,
    )

    tasks = generate_debug_tasks([omission_report, cycle_report, dismissed_report])

    assert [task.bug_report_id for task in tasks] == [omission_report.id, omission_report.id, omission_report.id, cycle_report.id, cycle_report.id]
    assert tasks[0].priority == ProofDebugTaskPriority.critical
    assert tasks[0].task_type == ProofDebugTaskType.omission_gap_investigation
    assert tasks[1].task_type == ProofDebugTaskType.missing_lemma_isolation
    assert tasks[2].task_type == ProofDebugTaskType.counterexample_search
    assert tasks[3].priority == ProofDebugTaskPriority.critical
    assert tasks[3].task_type == ProofDebugTaskType.dependency_cycle_break
    assert tasks[3].status == ProofDebugTaskStatus.triaged
    assert tasks[4].task_type == ProofDebugTaskType.missing_lemma_isolation
    assert all(task.bug_report_id != dismissed_report.id for task in tasks)
    assert all(task.status in {ProofDebugTaskStatus.pending, ProofDebugTaskStatus.triaged} for task in tasks)
    assert {task.priority for task in tasks} >= {ProofDebugTaskPriority.critical, ProofDebugTaskPriority.high}


def test_debug_task_batch_serialization_preserves_audit_fields() -> None:
    report = ProofBugReport(
        bug_type=ProofBugType.export_overstretch,
        description="export is stronger than its grounding supports",
        severity=ProofBugSeverity.high,
        confidence=0.9,
        status=ProofBugStatus.suspected,
        linked_contract_ids=["thm_imported"],
        linked_obligation_ids=["obl_export"],
        linked_blocker_ids=["blk_export"],
        reasoning_path=["thm_imported", "export_strength_check"],
        missing_conditions=["grounded support"],
        evidence=["checker output: exported theorem has weak grounding"],
    )

    batch = debug_task_batch_from_reports([report], theorem_id="thm_imported")
    reloaded = ProofDebugTaskBatch.model_validate_json(batch.model_dump_json())

    assert len(batch.tasks) == 2
    assert batch.theorem_id == "thm_imported"
    assert batch.tasks[0].status == ProofDebugTaskStatus.pending
    assert batch.tasks[0].priority == ProofDebugTaskPriority.high
    assert batch.tasks[0].linked_contract_ids == ["thm_imported"]
    assert batch.tasks[0].candidate_repairs
    assert reloaded == batch
