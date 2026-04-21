from pathlib import Path

from proof_cli.blockers import add_blocker
from proof_cli.bugs import ProofBugReport, ProofBugReviewState, ProofBugSeverity, ProofBugStatus, ProofBugType
from proof_cli.debug_tasks import debug_task_batch_from_reports
from proof_cli.domain import BlockerRecord
from proof_cli.evidence import EvidenceChain
from proof_cli.memory import (
    ProofRepairDecision,
    failed_routes,
    load_memory,
    proof_debug_history,
    proof_debug_patterns,
    proof_debug_records,
    record_bug_report_memory,
    record_debug_task_memory,
    record_evidence_chain_memory,
    record_failure_motif_memory,
    record_repair_decision_memory,
    record_repair_pattern_memory,
    procedural_tactics,
    record_memory,
    stable_memory,
)
from proof_cli.goals import add_goal, set_current_theorem
from proof_cli.proof_state import note_unresolved_trust_call
from proof_cli.snapshot import create_snapshot, restore_snapshot
from proof_cli.storage import ensure_project


def test_proof_debug_memory_is_typed_and_retrievable_by_scope(tmp_path: Path):
    store = ensure_project(tmp_path)

    suspect_report = ProofBugReport(
        bug_type=ProofBugType.omitted_side_condition,
        description="boundary condition is only implicit",
        severity=ProofBugSeverity.high,
        confidence=0.93,
        status=ProofBugStatus.suspected,
        linked_contract_ids=["thm_1"],
        linked_obligation_ids=["obl_1"],
        reasoning_path=["thm_1", "boundary_check"],
        missing_conditions=["side condition"],
        evidence=["checker output: omitted side condition"],
        detector="detect_omitted_side_conditions",
    )
    dismissed_report = ProofBugReport(
        bug_type=ProofBugType.notation_drift,
        description="notation drift was reviewed and dismissed",
        severity=ProofBugSeverity.low,
        confidence=0.4,
        status=ProofBugStatus.dismissed,
        linked_contract_ids=["thm_1"],
        linked_obligation_ids=["obl_1"],
        reasoning_path=["thm_1", "notation_review"],
        evidence=["review note: symbol set is consistent"],
        detector="detect_notation_drift",
    )
    suspect_chain = EvidenceChain.from_bug_report(suspect_report)
    debug_batch = debug_task_batch_from_reports([suspect_report], [suspect_chain], theorem_id="thm_1")
    debug_task = debug_batch.tasks[0]

    record_bug_report_memory(
        store,
        suspect_report,
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )
    record_bug_report_memory(
        store,
        dismissed_report,
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="notation_review",
    )
    record_evidence_chain_memory(
        store,
        suspect_chain,
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )
    record_debug_task_memory(
        store,
        debug_task,
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )
    record_repair_decision_memory(
        store,
        ProofRepairDecision(
            bug_id=suspect_report.id,
            bug_status=ProofBugStatus.repaired,
            review_state=ProofBugReviewState.reviewed,
            note="added the missing boundary lemma",
        ),
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )
    record_repair_pattern_memory(
        store,
        "add a boundary lemma before reuse",
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )
    record_failure_motif_memory(
        store,
        "omitted side condition",
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )

    memory = load_memory(store)

    assert memory.project_id == "proj_alpha"
    assert {record.kind.value for record in memory.proof_debug_history} >= {
        "suspicion",
        "bug_history",
        "evidence_chain",
        "debug_task",
        "repair_decision",
        "repair_pattern",
        "failure_motif",
    }
    assert [record.bug_report.id for record in proof_debug_records(store, theorem_id="thm_1") if record.bug_report is not None] == [
        suspect_report.id,
        dismissed_report.id,
    ]
    assert [record.bug_report.id for record in proof_debug_records(store, obligation_id="obl_1") if record.bug_report is not None] == [
        suspect_report.id,
        dismissed_report.id,
    ]
    assert [record.debug_task.id for record in proof_debug_records(store, method_id="boundary_check") if record.debug_task is not None] == [
        debug_task.id,
    ]
    assert [record.summary for record in proof_debug_patterns(store, theorem_id="thm_1")]
    assert [record.bug_report.id for record in proof_debug_history(store, theorem_id="thm_1") if record.bug_report is not None][0] == suspect_report.id


def test_memory_artifacts_are_typed_and_retrievable(tmp_path: Path):
    store = ensure_project(tmp_path)
    set_current_theorem(store, "thm_1")

    record_memory(
        store,
        "working",
        "open theorem 1",
        theorem_id="thm_1",
        goal_id="goal_1",
        importance="high",
        tags=["active"],
    )
    record_memory(
        store,
        "semantic",
        "compactness lemma is reusable",
        theorem_id="thm_1",
        importance="critical",
        tags=["stable"],
    )
    record_memory(
        store,
        "episodic",
        "failed direct proof by contradiction",
        theorem_id="thm_1",
        route_id="route_1",
        importance="low",
    )
    record_memory(
        store,
        "procedural",
        "check assumptions before applying a theorem",
        theorem_id="thm_1",
        importance="medium",
    )

    memory = load_memory(store)

    assert memory.project_id == "proj_alpha"
    assert memory.working[0].content == "open theorem 1"
    assert memory.working[0].scope.theorem_id == "thm_1"
    assert memory.semantic[0].importance.value == "critical"
    assert [artifact.content for artifact in stable_memory(store)] == ["compactness lemma is reusable"]
    assert [artifact.content for artifact in failed_routes(store)] == ["failed direct proof by contradiction"]
    assert [artifact.content for artifact in procedural_tactics(store)] == [
        "check assumptions before applying a theorem"
    ]


def test_snapshot_restore_preserves_memory_context_blockers_and_debts(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_goal(store, "prove theorem 1")
    set_current_theorem(store, "thm_1")
    note_unresolved_trust_call(store, "thm_1")
    add_blocker(
        store,
        BlockerRecord(
            id="blk_1",
            scope="thm_1",
            description="missing lemma",
            failure_type="missing_lemma",
        ),
    )

    record_memory(store, "working", "open theorem 1", theorem_id="thm_1")
    record_memory(store, "semantic", "lemma 1 is reusable", theorem_id="thm_1", importance="high")
    record_memory(store, "episodic", "failed direct proof once", theorem_id="thm_1", route_id="route_1")
    record_memory(store, "procedural", "check assumptions before apply", theorem_id="thm_1")

    suspect_report = ProofBugReport(
        bug_type=ProofBugType.omitted_side_condition,
        description="a hidden side condition is now explicit",
        severity=ProofBugSeverity.high,
        confidence=0.91,
        status=ProofBugStatus.suspected,
        linked_contract_ids=["thm_1"],
        linked_obligation_ids=["obl_1"],
        reasoning_path=["thm_1", "boundary_check"],
        missing_conditions=["side condition"],
        evidence=["checker output: omitted side condition"],
        detector="detect_omitted_side_conditions",
    )
    dismissed_report = ProofBugReport(
        bug_type=ProofBugType.notation_drift,
        description="notation drift was reviewed and dismissed",
        severity=ProofBugSeverity.low,
        confidence=0.4,
        status=ProofBugStatus.dismissed,
        linked_contract_ids=["thm_1"],
        linked_obligation_ids=["obl_1"],
        reasoning_path=["thm_1", "notation_review"],
        evidence=["review note: symbol set is consistent"],
        detector="detect_notation_drift",
    )
    suspect_chain = EvidenceChain.from_bug_report(suspect_report)
    debug_batch = debug_task_batch_from_reports([suspect_report], [suspect_chain], theorem_id="thm_1")
    debug_task = debug_batch.tasks[0]

    record_bug_report_memory(store, suspect_report, theorem_id="thm_1", obligation_id="obl_1", method_id="boundary_check")
    record_bug_report_memory(store, dismissed_report, theorem_id="thm_1", obligation_id="obl_1", method_id="notation_review")
    record_evidence_chain_memory(store, suspect_chain, theorem_id="thm_1", obligation_id="obl_1", method_id="boundary_check")
    record_debug_task_memory(store, debug_task, theorem_id="thm_1", obligation_id="obl_1", method_id="boundary_check")
    record_repair_decision_memory(
        store,
        ProofRepairDecision(
            bug_id=suspect_report.id,
            bug_status=ProofBugStatus.repaired,
            review_state=ProofBugReviewState.reviewed,
            note="proof was repaired by naming the boundary lemma",
        ),
        theorem_id="thm_1",
        obligation_id="obl_1",
        method_id="boundary_check",
    )

    snapshot = create_snapshot(store, note="handoff for later")
    restored = restore_snapshot(store)
    memory = load_memory(store)

    assert snapshot.handoff_note == "handoff for later"
    assert restored is not None
    assert restored.project_snapshot.active_theorem == "thm_1"
    assert "prove theorem 1" in restored.project_snapshot.current_goals
    assert [report.id for report in restored.suspicion_reports] == [suspect_report.id]
    assert [report.id for report in restored.resolved_bug_history] == [dismissed_report.id]
    assert [chain.bug_report_id for chain in restored.evidence_chains] == [suspect_report.id]
    assert [task.id for task in restored.debug_tasks] == [debug_task.id]
    assert [decision.bug_id for decision in restored.repair_decisions] == [suspect_report.id]
    assert restored.proof_debug_history[0].bug_report is not None
    assert {record.kind.value for record in restored.proof_debug_history} >= {"suspicion", "bug_history", "debug_task"}
    assert restored.working_context == ["open theorem 1"]
    assert restored.failed_routes == ["failed direct proof once"]
    assert restored.procedural_tactics == ["check assumptions before apply"]
    assert restored.blocker_ids == ["blk_1"]
    assert restored.unresolved_debts == ["thm_1"]
    assert memory.handoff_snapshots[-1].handoff_note == "handoff for later"
    assert memory.handoff_snapshots[-1].working_context == ["open theorem 1"]
