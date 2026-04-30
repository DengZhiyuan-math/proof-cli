from pathlib import Path

from proof_cli.blockers import add_blocker
from proof_cli.bugs import ProofBugReport, ProofBugReviewState, ProofBugSeverity, ProofBugStatus, ProofBugType
from proof_cli.debug_tasks import debug_task_batch_from_reports
from proof_cli.domain import BlockerRecord
from proof_cli.evidence import EvidenceChain
from proof_cli.memory import (
    ProofRepairDecision,
    VerificationLifecycleKind,
    accepted_verification_results,
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
    record_verification_lifecycle,
    record_verification_revalidation,
    record_verification_staleness,
    revalidation_history,
    stale_verification_fragments,
    procedural_tactics,
    record_memory,
    stable_memory,
    queued_verification_fragments,
    verification_dependency_versions,
    verification_records,
)
from proof_cli.goals import add_goal, set_current_theorem
from proof_cli.proof_state import note_unresolved_trust_call
from proof_cli.snapshot import create_snapshot, restore_snapshot
from proof_cli.storage import ensure_project
from proof_cli.verification_ir import (
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
    VerificationSourceKind,
)
from proof_cli.verification_results import VerificationResultRecord


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
    assert snapshot.latest_diagnostic_report is not None
    assert snapshot.latest_diagnostic_report["current_theorem"] == "thm_1"
    assert restored is not None
    assert restored.project_snapshot.active_theorem == "thm_1"
    assert restored.project_snapshot.latest_diagnostic_report is not None
    assert restored.latest_diagnostic_report is not None
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


def test_verification_lifecycle_snapshots_preserve_stale_and_revalidation_state(tmp_path: Path):
    store = ensure_project(tmp_path)
    scope = VerificationScope(
        project_id="proj_alpha",
        theorem_id="thm_1",
        obligation_id="obl_1",
        proof_step_id="step_1",
        route_id="route_1",
        tags=["phase4", "memory"],
    )
    dependency_v1 = VerificationDependencyVersion(
        dependency_id="thm_bridge",
        version=1,
        kind="theorem_contract",
        digest="sha256:aaa111",
    )
    dependency_v2 = VerificationDependencyVersion(
        dependency_id="thm_bridge",
        version=2,
        kind="theorem_contract",
        digest="sha256:bbb222",
    )
    fragment = VerificationFragment(
        source_type=VerificationSourceKind.theorem_application,
        source_id="step_1",
        scope=scope,
        ir_version=1,
        status=VerificationFragmentStatus.queued_for_verification,
        backend_target="lean4",
        dependency_versions=[dependency_v1],
        provenance=VerificationProvenance(
            source_kind=VerificationSourceKind.theorem_application,
            source_id="step_1",
            source_label="initial machine-check candidate",
            source_scope=scope,
            derived_from_ids=["goal_1", "lemma_bridge"],
            machine_path=["inspect state", "queue for backend"],
        ),
        notes="queued for verification",
    )
    queued_fragment = fragment.queue_for_verification(backend_target="lean4")
    queued_record = record_verification_lifecycle(
        store,
        queued_fragment,
        kind=VerificationLifecycleKind.queued_for_verification,
        notes="queued for backend execution",
    )

    checked_fragment = queued_fragment.record_machine_check(result_id="vchk_1", backend_target="lean4")
    machine_result = VerificationResult(
        fragment_id=checked_fragment.id,
        backend="lean4",
        summary="machine check succeeded for the bridge fragment",
        review_status=VerificationReviewStatus.accepted_after_review,
        notes="reviewed and accepted",
    )
    machine_result_record = VerificationResultRecord(
        result=machine_result,
        result_status=checked_fragment.status,
        review_status=machine_result.review_status,
        source_kind=checked_fragment.source_type,
        source_id=checked_fragment.source_id,
        scope=checked_fragment.scope,
        theorem_id=checked_fragment.scope.theorem_id,
        obligation_id=checked_fragment.scope.obligation_id,
        proof_step_id=checked_fragment.scope.proof_step_id,
        route_id=checked_fragment.scope.route_id,
        effect="strengthening",
        notes="accepted after machine check",
    )
    machine_checked_record = record_verification_lifecycle(
        store,
        checked_fragment,
        result=machine_result,
        result_record=machine_result_record,
        kind=VerificationLifecycleKind.machine_checked,
        notes="machine check accepted",
    )

    stale_fragment = checked_fragment.mark_stale_after_change(
        changed_dependency_versions=[dependency_v2],
        reason="dependency version changed after a proof update",
    )
    stale_record = record_verification_staleness(
        store,
        stale_fragment,
        notes="dependency version changed after a proof update",
    )

    revalidated_fragment = stale_fragment.queue_for_verification(backend_target="lean4").model_copy(
        update={
            "id": "vfrag_revalidated_1",
            "dependency_versions": [dependency_v2],
            "provenance": stale_fragment.provenance.model_copy(
                update={
                    "derived_from_ids": [*stale_fragment.provenance.derived_from_ids, stale_fragment.id],
                    "machine_path": [*stale_fragment.provenance.machine_path, "revalidate fragment"],
                }
            ),
        }
    )
    revalidated_result = VerificationResult(
        fragment_id=revalidated_fragment.id,
        backend="lean4",
        summary="revalidated machine check succeeded",
        review_status=VerificationReviewStatus.accepted_after_review,
        notes="revalidated and accepted",
    )
    revalidated_record = VerificationResultRecord(
        result=revalidated_result,
        result_status=revalidated_fragment.status,
        review_status=revalidated_result.review_status,
        source_kind=revalidated_fragment.source_type,
        source_id=revalidated_fragment.source_id,
        scope=revalidated_fragment.scope,
        theorem_id=revalidated_fragment.scope.theorem_id,
        obligation_id=revalidated_fragment.scope.obligation_id,
        proof_step_id=revalidated_fragment.scope.proof_step_id,
        route_id=revalidated_fragment.scope.route_id,
        effect="strengthening",
        notes="accepted after revalidation",
    )
    revalidation_record = record_verification_revalidation(
        store,
        revalidated_fragment,
        result=revalidated_result,
        result_record=revalidated_record,
        notes="revalidated after dependency change",
    )

    memory = load_memory(store)
    snapshot = create_snapshot(store, note="handoff after verification lifecycle update")
    restored = restore_snapshot(store)

    assert memory.verification_history[0].kind == VerificationLifecycleKind.queued_for_verification
    assert {record.fragment.status for record in verification_records(store, theorem_id="thm_1")} >= {
        VerificationFragmentStatus.queued_for_verification,
        VerificationFragmentStatus.machine_checked,
        VerificationFragmentStatus.stale_after_change,
    }
    assert [dep.version for dep in verification_dependency_versions(store, theorem_id="thm_1")] == [1, 2]
    assert [fragment.id for fragment in queued_verification_fragments(store, theorem_id="thm_1")] == [
        queued_record.fragment.id,
        revalidation_record.fragment.id,
    ]
    assert [fragment.id for fragment in stale_verification_fragments(store, theorem_id="thm_1")] == [stale_record.fragment.id]
    assert [record.result.id for record in accepted_verification_results(store, theorem_id="thm_1")] == [
        machine_result.id,
        revalidated_result.id,
    ]
    assert [record.fragment.id for record in revalidation_history(store, theorem_id="thm_1")] == [
        stale_record.fragment.id,
        revalidation_record.fragment.id,
    ]
    assert snapshot.handoff_note == "handoff after verification lifecycle update"
    assert restored is not None
    assert [fragment.id for fragment in restored.queued_verification_fragments] == [
        queued_record.fragment.id,
        revalidation_record.fragment.id,
    ]
    assert [fragment.id for fragment in restored.stale_verification_fragments] == [stale_record.fragment.id]
    assert [record.result.id for record in restored.accepted_verification_results] == [
        machine_result_record.result.id,
        revalidated_record.result.id,
    ]
    assert [record.fragment.id for record in restored.revalidation_requirements] == [
        stale_record.fragment.id,
        revalidation_record.fragment.id,
    ]
