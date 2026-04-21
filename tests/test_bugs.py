from pathlib import Path

from proof_cli.blockers import add_blocker
from proof_cli.bugs import (
    ProofBugReport,
    ProofBugReviewState,
    ProofBugScan,
    ProofBugSeverity,
    ProofBugStatus,
    ProofBugType,
    detect_assumption_mismatch,
    detect_circular_dependency,
    detect_export_overstretch,
    detect_notation_drift,
    detect_omitted_side_conditions,
    scan_proof_bugs,
)
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.memory import track_symbol
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import set_current_context
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem


def test_bug_report_round_trips_with_separate_review_state() -> None:
    report = ProofBugReport(
        bug_type=ProofBugType.assumption_mismatch,
        description="missing assumption A",
        severity=ProofBugSeverity.high,
        confidence=0.93,
        status=ProofBugStatus.suspected,
        review_state=ProofBugReviewState.unreviewed,
        linked_contract_ids=["thm_main"],
        linked_obligation_ids=["obl_main"],
        linked_blocker_ids=["blk_main"],
        reasoning_path=["thm_main", "assumption_check"],
        missing_conditions=["A"],
        evidence=["callability check: missing assumptions: A"],
        detector="detect_assumption_mismatch",
    )

    reloaded = ProofBugReport.model_validate_json(report.model_dump_json())

    assert reloaded == report
    assert reloaded.status == ProofBugStatus.suspected
    assert reloaded.review_state == ProofBugReviewState.unreviewed
    assert reloaded.status != ProofBugStatus.confirmed


def test_detector_entry_points_produce_serializable_reviewable_bugs(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="If X then Y and Z",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_cycle"],
    )
    add_theorem(
        store,
        theorem_id="thm_cycle",
        kind="lemma",
        name="Cycle Lemma",
        statement="cycle bridge",
        assumptions=[],
        exports=[],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_main"],
    )
    add_theorem(
        store,
        theorem_id="thm_imported",
        kind="result",
        name="Imported Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
        dependencies=[],
    )
    add_obligation(
        store,
        ProofObligation(
            id="obl_gap",
            goal_statement="compressed reasoning gap in the final step",
            required_for="thm_main",
            blocking_reason="omitted side condition",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_gap",
            scope="thm_main",
            description="missing side condition",
            failure_type="omitted_side_condition",
        ),
    )
    set_current_context(store, [])
    track_symbol(store, "A")

    assumption_bugs = detect_assumption_mismatch(store, "thm_main")
    export_bugs = detect_export_overstretch(store, "thm_imported")
    omission_bugs = detect_omitted_side_conditions(store, "thm_main")
    cycle_bugs = detect_circular_dependency(store, "thm_main")
    notation_bugs = detect_notation_drift(store, "thm_main")
    scan = scan_proof_bugs(store, "thm_main")

    assert len(assumption_bugs) == 1
    assert assumption_bugs[0].bug_type == ProofBugType.assumption_mismatch
    assert assumption_bugs[0].status == ProofBugStatus.suspected
    assert assumption_bugs[0].review_state == ProofBugReviewState.unreviewed
    assert assumption_bugs[0].linked_contract_ids == ["thm_main"]
    assert assumption_bugs[0].linked_obligation_ids == ["obl_gap"]

    assert len(export_bugs) == 1
    assert export_bugs[0].bug_type == ProofBugType.export_overstretch
    assert export_bugs[0].severity == ProofBugSeverity.high
    assert export_bugs[0].linked_contract_ids == ["thm_imported"]

    assert len(omission_bugs) == 1
    assert omission_bugs[0].bug_type == ProofBugType.omitted_side_condition
    assert omission_bugs[0].linked_obligation_ids == ["obl_gap"]
    assert omission_bugs[0].linked_blocker_ids == ["blk_gap"]

    assert len(cycle_bugs) == 1
    assert cycle_bugs[0].bug_type == ProofBugType.circular_dependency
    assert cycle_bugs[0].severity == ProofBugSeverity.critical
    assert "thm_cycle" in cycle_bugs[0].linked_contract_ids

    assert len(notation_bugs) == 1
    assert notation_bugs[0].bug_type == ProofBugType.notation_drift
    assert notation_bugs[0].linked_contract_ids == ["thm_main"]

    assert isinstance(scan, ProofBugScan)
    assert scan.theorem_id == "thm_main"
    assert scan.report_ids() == [report.id for report in scan.reports]
    assert scan.bug_types() == [report.bug_type.value for report in scan.reports]
    assert ProofBugScan.model_validate_json(scan.model_dump_json()) == scan
    assert {report.bug_type for report in scan.reports} >= {
        ProofBugType.assumption_mismatch,
        ProofBugType.omitted_side_condition,
        ProofBugType.circular_dependency,
        ProofBugType.notation_drift,
    }
