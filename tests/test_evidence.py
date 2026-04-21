from pathlib import Path

from proof_cli.bugs import ProofBugReport, ProofBugSeverity, ProofBugStatus, ProofBugType, scan_proof_bugs
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.evidence import EvidenceChain, EvidenceReviewRecommendation, build_evidence_chains
from proof_cli.proof_state import set_current_context
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem


def test_evidence_chain_links_to_bug_report_and_round_trips() -> None:
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
        detector="detect_assumption_mismatch",
    )

    chain = EvidenceChain.from_bug_report(report)
    reloaded = EvidenceChain.model_validate_json(chain.model_dump_json())

    assert chain.bug_report_id == report.id
    assert chain.reasoning_path == ["thm_main", "assumption_check", "review_gate"]
    assert chain.missing_conditions == ["A"]
    assert chain.review_recommendation == EvidenceReviewRecommendation.block
    assert chain.linked_contract_ids == ["thm_main"]
    assert chain.linked_obligation_ids == ["obl_main"]
    assert chain.linked_blocker_ids == ["blk_main"]
    assert chain.evidence == ["callability check: missing assumptions: A"]
    assert reloaded == chain


def test_build_evidence_chains_keeps_only_suspected_reports() -> None:
    suspected_report = ProofBugReport(
        bug_type=ProofBugType.omitted_side_condition,
        description="open obligations indicate an omitted side condition",
        severity=ProofBugSeverity.medium,
        confidence=0.82,
        status=ProofBugStatus.suspected,
        linked_contract_ids=["thm_main"],
        linked_obligation_ids=["obl_gap"],
        reasoning_path=["thm_main", "obligation_scan"],
        missing_conditions=["hidden side condition"],
        evidence=["checker output: unresolved omission gaps: obl_gap"],
        detector="detect_omitted_side_conditions",
    )
    confirmed_report = ProofBugReport(
        bug_type=ProofBugType.notation_drift,
        description="notation drift detected in theorem thm_main",
        severity=ProofBugSeverity.low,
        confidence=0.7,
        status=ProofBugStatus.confirmed,
        linked_contract_ids=["thm_main"],
        reasoning_path=["thm_main", "notation_drift_check"],
        missing_conditions=["untracked symbol"],
        evidence=["checker output: untracked symbols: X"],
        detector="detect_notation_drift",
    )

    chains = build_evidence_chains([suspected_report, confirmed_report])

    assert [chain.bug_report_id for chain in chains] == [suspected_report.id]
    assert chains[0].reasoning_path == suspected_report.reasoning_path
    assert chains[0].missing_conditions == suspected_report.missing_conditions
    assert chains[0].review_recommendation == EvidenceReviewRecommendation.revise


def test_detector_reports_can_be_translated_into_evidence_chains(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="derive result from premises",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    set_current_context(store, [])

    scan = scan_proof_bugs(store, "thm_main")
    chains = build_evidence_chains(scan.reports)

    assert len(scan.reports) == 1
    assert scan.reports[0].status == ProofBugStatus.suspected
    assert len(chains) == 1
    assert chains[0].bug_report_id == scan.reports[0].id
    assert chains[0].reasoning_path == ["thm_main", "assumption_check"]
    assert chains[0].missing_conditions == ["A"]
    assert chains[0].review_recommendation == EvidenceReviewRecommendation.block
