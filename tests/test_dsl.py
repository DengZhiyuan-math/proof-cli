from __future__ import annotations

import json
from pathlib import Path

from proof_cli.commands import (
    cmd_proof_bug_list,
    cmd_proof_bug_show,
    cmd_proof_debug_generate,
    cmd_proof_debug_list,
    cmd_proof_evidence_show,
    cmd_proof_explain_apply,
    cmd_proof_formalize_recommend,
    cmd_proof_provenance_show,
    cmd_proof_repair_mark,
    cmd_proof_review_suspicion,
    cmd_proof_trace_machine_check,
)
from proof_cli.domain import (
    TheoremProvenanceKind,
    TheoremReviewState,
    TheoremStatus,
    TrustLevel,
)
from proof_cli.dsl import parse_program
from proof_cli.elaboration import elaborate_program
from proof_cli.obligations import list_obligations
from proof_cli.proof_state import load_state, set_current_context
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import approve_reference, ensure_project, import_reference
from proof_cli.theorems import add_theorem


def test_parse_program_classifies_retrieval_grounding_reasoning_and_debug_commands() -> None:
    program = parse_program(
        """
        search compactness lemma
        import thm_imported
        ground thm_imported using ref_standard_1, ref_paper_1
        review thm_imported approve grounded after check
        goal theorem_1
        assert obvious intermediate step
        reason theorem_1 because downstream use
        obligation derive theorem_1
        bug scan theorem_1
        bug list theorem_1
        bug show bug_123
        evidence show bug_123
        debug generate theorem_1
        debug list theorem_1
        repair mark bug_123 repaired after review
        review suspicion bug_123 under_review
        trace dependency theorem_1
        explain apply theorem_1
        """
    )

    assert program[0].name == "search"
    assert program[0].category == "retrieval"
    assert program[0].target == "compactness lemma"
    assert program[1].name == "import"
    assert program[1].category == "retrieval"
    assert program[1].target == "thm_imported"
    assert program[2].name == "ground"
    assert program[2].category == "grounding"
    assert program[2].target == "thm_imported"
    assert program[2].references == ("ref_standard_1", "ref_paper_1")
    assert program[3].name == "review"
    assert program[3].category == "review"
    assert program[3].target == "thm_imported"
    assert program[4].category == "proof"
    assert program[5].category == "proof"
    assert program[6].name == "reason"
    assert program[6].category == "reasoning"
    assert program[6].target == "theorem_1"
    assert program[6].argument == "because downstream use"
    assert program[7].name == "obligation_derive"
    assert program[7].category == "reasoning"
    assert program[7].target == "theorem_1"
    assert program[8].name == "bug_scan"
    assert program[8].category == "bug"
    assert program[8].target == "theorem_1"
    assert program[9].name == "bug_list"
    assert program[9].category == "bug"
    assert program[10].name == "bug_show"
    assert program[10].category == "bug"
    assert program[11].name == "evidence_show"
    assert program[11].category == "evidence"
    assert program[12].name == "debug_generate"
    assert program[12].category == "debug"
    assert program[13].name == "debug_list"
    assert program[13].category == "debug"
    assert program[14].name == "repair_mark"
    assert program[14].category == "repair"
    assert program[15].name == "review_suspicion"
    assert program[15].category == "review"
    assert program[16].name == "trace_dependency"
    assert program[16].category == "trace"
    assert program[17].name == "explain_apply"
    assert program[17].category == "explain"


def test_elaboration_records_retrieval_grounding_and_review_transitions(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)

    import_reference(
        store,
        ReferenceRecord(
            id="ref_standard_1",
            title="Standard Lemma",
            authors=["A. Expert"],
            year=2020,
            source_type=ReferenceSourceType.standard_reference,
            origin="book",
            bibliographic_source="book",
            identifier="isbn:123",
            url="https://example.test/standard",
            notes="Project-approved standard result.",
        ),
    )
    approve_reference(store, "ref_standard_1", confirmed=True, rationale="standard result grounded in the project")

    import_reference(
        store,
        ReferenceRecord(
            id="ref_paper_1",
            title="Research Paper Lemma",
            authors=["B. Scholar"],
            year=2022,
            source_type=ReferenceSourceType.research_paper,
            origin="arxiv",
            bibliographic_source="arxiv",
            identifier="arXiv:2201.00001",
            url="https://example.test/paper",
            notes="Callable after explicit review.",
        ),
    )
    approve_reference(store, "ref_paper_1", confirmed=True, rationale="reviewed research-paper source")

    add_theorem(
        store,
        theorem_id="thm_imported",
        kind="lemma",
        name="Imported Grounding Target",
        statement="A -> C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.candidate,
        source_ref="arxiv:2201.00001",
    )
    add_theorem(
        store,
        theorem_id="thm_local",
        kind="theorem",
        name="Local Proof Target",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )

    set_current_context(store, ["A"])

    results = elaborate_program(
        store,
        parse_program(
            """
            search imported result
            import thm_imported
            review thm_imported approve grounded after check
            ground thm_imported using ref_standard_1, ref_paper_1
            review thm_imported approve grounded after check
            apply thm_imported
            assert obvious intermediate step
            """
        ),
    )

    assert results[0].startswith("query: imported result")
    assert results[1].startswith("import:blocked:")
    assert results[2] == "review:blocked:grounding required before approval"
    assert results[3] == "ground:thm_imported:ref_standard_1,ref_paper_1"
    assert results[4] == "review:thm_imported:approved"
    assert results[5] == "apply:thm_imported"
    assert results[6] == "assert:obvious intermediate step"

    state = load_state(store)
    assert "search:imported result" in state.session_history
    assert any(entry.startswith("ground:thm_imported") for entry in state.session_history)
    assert "A" in state.current_context
    assert state.recent_theorem_usage == ["thm_imported"]
    assert state.open_obligations

    obligations = list_obligations(store)
    assert any(obligation.blocking_reason == "compressed reasoning" for obligation in obligations)

    provenance = json.loads(cmd_proof_provenance_show("thm_imported", root=tmp_path))
    assert provenance["kind"] == "theorem"
    assert provenance["grounded_reference_ids"] == ["ref_standard_1", "ref_paper_1"]
    assert provenance["review_state"] == "approved"
    assert provenance["callable"] is True
    assert provenance["callability_reason"] == "callable"


def test_reasoning_bug_and_debug_workflow_exposes_explicit_state(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_reason",
        kind="theorem",
        name="Reasoning Target",
        statement="A -> C",
        assumptions=["A"],
        exports=["C"],
        dependencies=["thm_dep"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )
    add_theorem(
        store,
        theorem_id="thm_dep",
        kind="lemma",
        name="Dependency Lemma",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )

    results = elaborate_program(
        store,
        parse_program(
            """
            goal thm_reason
            reason thm_reason because downstream use
            obligation derive thm_reason
            bug scan thm_reason
            trace dependency thm_reason
            explain apply thm_reason
            """
        ),
    )

    assert results[0] == "goal:thm_reason"
    reasoning_payload = json.loads(results[1])
    assert reasoning_payload["theorem_id"] == "thm_reason"
    assert reasoning_payload["adequacy_check"]["adequate"] is False
    assert reasoning_payload["derived_obligations"]
    assert json.loads(results[2])["obligations"]

    scan_payload = json.loads(results[3])
    assert scan_payload["theorem_id"] == "thm_reason"
    assert len(scan_payload["reports"]) >= 1
    bug_id = scan_payload["reports"][0]["id"]

    trace_payload = json.loads(results[4])
    assert trace_payload["target_id"] == "thm_reason"
    assert "thm_dep" in trace_payload["dependency_ids"]

    explain_payload = json.loads(results[5])
    assert explain_payload["theorem_id"] == "thm_reason"
    assert explain_payload["callable"] is False
    assert "A" in explain_payload["missing_assumptions"]
    assert explain_payload["open_obligations"]

    bug_list_output = cmd_proof_bug_list(root=tmp_path, theorem_id="thm_reason")
    assert bug_id in bug_list_output

    bug_show_payload = json.loads(cmd_proof_bug_show(bug_id, root=tmp_path))
    assert bug_show_payload["id"] == bug_id
    assert bug_show_payload["status"] == "suspected"
    assert bug_show_payload["review_state"] == "unreviewed"

    evidence_payload = json.loads(cmd_proof_evidence_show(bug_id, root=tmp_path))
    assert evidence_payload["bug_report_id"] == bug_id
    assert evidence_payload["review_recommendation"] in {"block", "revise"}

    review_payload = json.loads(cmd_proof_review_suspicion(bug_id, "under_review", root=tmp_path, rationale="needs review"))
    assert review_payload["bug_id"] == bug_id
    assert review_payload["bug_status"] == "under_review"

    debug_batch = json.loads(cmd_proof_debug_generate("thm_reason", root=tmp_path))
    assert debug_batch["theorem_id"] == "thm_reason"
    assert debug_batch["tasks"]
    assert debug_batch["tasks"][0]["bug_report_id"] == bug_id

    debug_list_output = cmd_proof_debug_list(root=tmp_path, theorem_id="thm_reason")
    assert bug_id in debug_list_output
    assert "bug=" in debug_list_output

    repair_payload = json.loads(cmd_proof_repair_mark(bug_id, "repaired", root=tmp_path, note="fixed by new lemma"))
    assert repair_payload["bug_id"] == bug_id
    assert repair_payload["bug_status"] == "repaired"

    updated_bug_show = json.loads(cmd_proof_bug_show(bug_id, root=tmp_path))
    assert updated_bug_show["status"] == "repaired"

    explanation = json.loads(cmd_proof_explain_apply("thm_reason", root=tmp_path))
    assert explanation["callability_reason"].startswith("missing assumptions:")


def test_parse_program_understands_formalization_verification_and_trace_commands() -> None:
    program = parse_program(
        """
        formalize recommend thm_verify backend=smt notes=fragile
        formalize show thm_verify
        formalize edit thm_verify backend=proof_assistant notes=tuned
        verify queue thm_verify backend=smt route=route_1 notes=queued
        verify run thm_verify backend=smt notes=run
        verify status thm_verify
        verify result thm_verify
        verify accept thm_verify notes=accepted
        verify reject thm_verify notes=rejected
        verify stale thm_verify dependency=thm_dep reason=changed
        trace machine-check thm_verify
        revalidate thm_verify backend=smt notes=recheck
        """
    )

    assert program[0].name == "formalize_recommend"
    assert program[0].category == "formalization"
    assert program[0].target == "thm_verify"
    assert dict(program[0].options) == {"backend": "smt", "notes": "fragile"}
    assert program[3].name == "verify_queue"
    assert program[3].category == "verification"
    assert program[3].target == "thm_verify"
    assert dict(program[3].options) == {"backend": "smt", "route": "route_1", "notes": "queued"}
    assert program[10].name == "trace_machine_check"
    assert program[10].category == "trace"
    assert program[11].name == "revalidate"
    assert program[11].category == "verification"


def test_formalize_and_verify_commands_preserve_provenance_and_audit_reviews(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_verify",
        kind="theorem",
        name="Verification Target",
        statement="A -> C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )
    add_theorem(
        store,
        theorem_id="thm_reject",
        kind="theorem",
        name="Rejected Verification Target",
        statement="B -> D",
        assumptions=["B"],
        exports=["D"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )
    set_current_context(store, ["A", "B"])

    formalize_payload = json.loads(
        cmd_proof_formalize_recommend("thm_verify", root=tmp_path, backend_target="smt", notes="fragile")
    )
    assert formalize_payload["recommendation"]["source_id"] == "thm_verify"
    assert formalize_payload["fragment"]["provenance"]["source_id"] == "thm_verify"

    accepted_outputs = elaborate_program(
        store,
        parse_program(
            """
            verify queue thm_verify backend=smt
            verify run thm_verify backend=smt
            verify accept thm_verify accepted after review
            verify status thm_verify
            verify result thm_verify
            trace machine-check thm_verify
            verify stale thm_verify dependency=thm_dep reason=dependency changed
            revalidate thm_verify backend=smt
            """
        ),
    )

    queue_payload = json.loads(accepted_outputs[0])
    assert queue_payload["machine_check_status"] == "queued_for_verification"
    assert queue_payload["fragment"]["provenance"]["source_id"] == "thm_verify"

    run_payload = json.loads(accepted_outputs[1])
    assert run_payload["machine_check_status"] == "machine_checked"
    assert run_payload["result"]["fragment_id"] == run_payload["fragment"]["id"]

    accept_payload = json.loads(accepted_outputs[2])
    assert accept_payload["result"]["review_status"] == "accepted_after_review"
    assert accept_payload["machine_check_status"] == "accepted_after_review"

    status_payload = json.loads(accepted_outputs[3])
    assert status_payload["machine_check_status"] == "accepted_after_review"
    assert status_payload["provenance"]["source_id"] == "thm_verify"

    result_payload = json.loads(accepted_outputs[4])
    assert result_payload["review_status"] == "accepted_after_review"
    assert result_payload["result"]["fragment_id"] == run_payload["fragment"]["id"]

    trace_payload = json.loads(accepted_outputs[5])
    assert trace_payload["machine_check_status"] == "accepted_after_review"
    assert trace_payload["provenance"]["source_id"] == "thm_verify"
    assert trace_payload["trace"]["kind"] == "machine-check-trace"

    direct_trace_payload = json.loads(cmd_proof_trace_machine_check("thm_verify", root=tmp_path))
    assert direct_trace_payload["provenance"]["source_id"] == "thm_verify"
    assert direct_trace_payload["trace"]["kind"] == "machine-check-trace"

    stale_payload = json.loads(accepted_outputs[6])
    assert stale_payload["machine_check_status"] == "stale_after_change"

    revalidate_payload = json.loads(accepted_outputs[7])
    assert revalidate_payload["machine_check_status"] == "queued_for_verification"
    assert revalidate_payload["stale_fragment"]["status"] == "stale_after_change"

    rejected_outputs = elaborate_program(
        store,
        parse_program(
            """
            verify run thm_reject backend=smt
            verify reject thm_reject needs more work
            verify result thm_reject
            """
        ),
    )

    reject_run_payload = json.loads(rejected_outputs[0])
    assert reject_run_payload["machine_check_status"] == "machine_checked"

    reject_payload = json.loads(rejected_outputs[1])
    assert reject_payload["result"]["review_status"] == "rejected_by_human"
    assert reject_payload["machine_check_status"] == "rejected_by_human"

    reject_result_payload = json.loads(rejected_outputs[2])
    assert reject_result_payload["review_status"] == "rejected_by_human"


def test_vague_statement_creates_obligation(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    results = elaborate_program(store, parse_program("goal theorem_2\ndefer obvious conclusion"))
    assert results[1] == "defer:obvious conclusion"
    state = load_state(store)
    assert state.open_obligations
