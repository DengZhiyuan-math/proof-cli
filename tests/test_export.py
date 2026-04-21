import json
from pathlib import Path

from proof_cli.blockers import add_blocker
from proof_cli.commands import (
    cmd_export,
    cmd_proof_bug_scan,
    cmd_proof_debug_generate,
    cmd_proof_evidence_show,
    cmd_proof_reason,
    cmd_proof_repair_mark,
    cmd_proof_review_suspicion,
    cmd_theorem_ground,
)
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.memory import load_memory, record_memory
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import record_theorem_usage, set_current_context, set_current_theorem
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.snapshot import create_snapshot
from proof_cli.storage import approve_reference, ensure_project, import_reference, list_references, read_latest_snapshot
from proof_cli.theorems import add_theorem, list_theorems


def _seed_real_project(tmp_path: Path) -> tuple[str, str]:
    store = ensure_project(tmp_path)

    standard_reference = import_reference(
        store,
        ReferenceRecord(
            id="ref_std",
            title="Standard Estimate",
            authors=["E. Analyst"],
            year=2023,
            source_type=ReferenceSourceType.standard_reference,
            origin="zbmath",
            bibliographic_source="zbmath",
            identifier="zb:2023.001",
            url="https://example.test/std",
            notes="Callable standard result.",
        ),
    )
    approve_reference(store, standard_reference.id, confirmed=True, rationale="standard reference is trusted")

    add_theorem(
        store,
        theorem_id="thm_blackbox",
        kind="theorem",
        name="Black Box Estimate",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
        grounded_reference_ids=[standard_reference.id],
        notes="Imported result used as a black box.",
    )
    cmd_theorem_ground("thm_blackbox", [standard_reference.id], root=tmp_path, notes="grounded black box theorem")

    add_theorem(
        store,
        theorem_id="thm_aux",
        kind="lemma",
        name="Auxiliary Lemma",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_aux2",
        kind="lemma",
        name="Propagation Lemma",
        statement="B implies C",
        assumptions=["B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_aux", "thm_blackbox"],
    )
    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="A implies C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_aux", "thm_aux2", "thm_blackbox"],
    )

    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A"])
    record_theorem_usage(store, "thm_blackbox")
    record_theorem_usage(store, "thm_aux")
    record_theorem_usage(store, "thm_aux2")

    add_obligation(
        store,
        ProofObligation(
            id="obl_main",
            goal_statement="compressed reasoning hides a standard bridge step",
            required_for="thm_main",
            blocking_reason="omitted standard step",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_main",
            scope="thm_main",
            description="fragile blocker around the black-box handoff",
            failure_type="fragile_dependency",
            related_contracts=["thm_blackbox"],
        ),
    )
    record_memory(store, "working", "checking the black-box handoff", theorem_id="thm_main")
    record_memory(store, "semantic", "the black-box theorem is imported and grounded", theorem_id="thm_main", importance="high")
    record_memory(store, "episodic", "compressed reasoning hid a bridge step", theorem_id="thm_main", route_id="route_gap")
    record_memory(store, "procedural", "inspect bugs before reuse", theorem_id="thm_main")

    cmd_proof_reason("thm_main", root=tmp_path, notes="derive local obligations")
    cmd_theorem_ground("thm_main", [standard_reference.id], root=tmp_path, notes="grounded by standard estimate")

    return standard_reference.id, "thm_main"


def test_export_includes_grounded_imported_reasoning_and_repair_state(tmp_path: Path):
    standard_reference_id, theorem_id = _seed_real_project(tmp_path)

    scan_payload = json.loads(cmd_proof_bug_scan(theorem_id, root=tmp_path))
    bug_ids = {report["bug_type"]: report["id"] for report in scan_payload["reports"]}
    assumption_bug_id = bug_ids["assumption_mismatch"]

    debug_payload = cmd_proof_debug_generate(theorem_id, root=tmp_path)
    assert assumption_bug_id in debug_payload

    review_payload = cmd_proof_review_suspicion(assumption_bug_id, "confirmed", root=tmp_path, rationale="confirmed by reviewer")
    assert '"bug_status": "confirmed"' in review_payload

    repair_payload = cmd_proof_repair_mark(assumption_bug_id, "repaired", root=tmp_path, note="fixed by making the assumption explicit")
    assert '"bug_status": "repaired"' in repair_payload

    evidence_payload = cmd_proof_evidence_show(assumption_bug_id, root=tmp_path)
    assert '"review_recommendation": "accept"' in evidence_payload

    create_snapshot(ensure_project(tmp_path), note="handoff after reasoning")

    export_one = cmd_export(root=tmp_path)
    reopened_store = ensure_project(tmp_path)
    export_two = cmd_export(root=tmp_path)

    assert export_one == export_two
    assert "Proof Export" in export_one
    assert "Goals: thm_main" in export_one
    assert "Assumed: A" in export_one
    assert "Open obligations: obl_main" in export_one
    assert "Proved: thm_blackbox, thm_aux, thm_aux2" in export_one
    assert "Standard Estimate" in export_one
    assert "Grounded theorems:" in export_one
    assert "thm_blackbox: Black Box Estimate <- ref_std" in export_one
    assert "thm_main: Main Result <- ref_std" in export_one
    assert "Reasoning:" in export_one
    assert "Bug reports:" in export_one
    assert "assumption_mismatch" in export_one
    assert "omitted_side_condition" in export_one
    assert "Evidence chains:" in export_one
    assert "recommendation=accept" in export_one
    assert "Debug tasks:" in export_one
    assert "Repair state:" in export_one
    assert "status=repaired" in export_one
    assert "Memory layers: working=1, semantic=1, episodic=1, procedural=1, handoffs=1" in export_one
    assert standard_reference_id in export_one

    stateful_references = {reference.id for reference in list_references(reopened_store)}
    assert standard_reference_id in stateful_references

    assert [theorem.id for theorem in list_theorems(reopened_store)] == ["thm_aux", "thm_aux2", "thm_blackbox", "thm_main"]

    memory = load_memory(reopened_store)
    assert memory.handoff_snapshots[-1].handoff_note == "handoff after reasoning"
    assert memory.working[0].content == "checking the black-box handoff"

    assert read_latest_snapshot(reopened_store) is not None
