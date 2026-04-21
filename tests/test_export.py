from pathlib import Path

from proof_cli.blockers import add_blocker
from proof_cli.commands import cmd_export, cmd_theorem_ground
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremStatus, TrustLevel
from proof_cli.memory import load_memory, record_memory
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import record_theorem_usage, set_current_context, set_current_theorem
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.snapshot import create_snapshot
from proof_cli.storage import approve_reference, defer_reference, ensure_project, import_reference, list_references, read_latest_snapshot
from proof_cli.theorems import add_theorem, list_theorems


def _seed_real_project(tmp_path: Path) -> tuple[str, str]:
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="A implies C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_aux",
        kind="lemma",
        name="Auxiliary Lemma",
        statement="A and B imply C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )

    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A", "B"])
    record_theorem_usage(store, "thm_aux")

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

    paper_reference = import_reference(
        store,
        ReferenceRecord(
            id="ref_paper",
            title="Paper Lemma",
            authors=["R. Researcher"],
            year=2021,
            source_type=ReferenceSourceType.research_paper,
            origin="arxiv",
            bibliographic_source="arxiv",
            identifier="arXiv:2101.00001",
            url="https://example.test/paper",
            notes="Needs manual review before reuse.",
        ),
    )
    defer_reference(store, paper_reference.id, confirmed=True, rationale="assumptions still need checking")

    add_obligation(
        store,
        ProofObligation(
            id="obl_main",
            goal_statement="bridge A to C",
            required_for="thm_main",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_main",
            scope="thm_main",
            description="paper route needs grounding",
            failure_type="assumption_mismatch",
        ),
    )

    record_memory(store, "working", "searching for the bridge lemma", theorem_id="thm_main")
    record_memory(store, "semantic", "standard estimate is callable in context", theorem_id="thm_main", importance="high")
    record_memory(store, "episodic", "paper route failed assumption match", theorem_id="thm_main", route_id="route_paper")
    record_memory(store, "procedural", "review imported results before reuse", theorem_id="thm_main")

    create_snapshot(store, note="handoff after grounding")
    cmd_theorem_ground("thm_main", ["ref_std"], root=tmp_path, notes="grounded by standard estimate")

    return standard_reference.id, paper_reference.id


def test_export_includes_grounded_imported_and_session_persistent_state(tmp_path: Path):
    standard_reference_id, paper_reference_id = _seed_real_project(tmp_path)

    export_one = cmd_export(root=tmp_path)
    reopened_store = ensure_project(tmp_path)
    export_two = cmd_export(root=tmp_path)

    assert export_one == export_two
    assert "Proof Export" in export_one
    assert "Goals: thm_main" in export_one
    assert "Assumed: A, B" in export_one
    assert "Open obligations: obl_main" in export_one
    assert "Proved: thm_aux" in export_one
    assert "Standard Estimate" in export_one
    assert "Paper Lemma" in export_one
    assert "Grounded theorems:" in export_one
    assert "thm_main: Main Result <- ref_std" in export_one
    assert "Memory layers: working=1, semantic=1, episodic=1, procedural=1, handoffs=1" in export_one
    assert standard_reference_id in export_one
    assert paper_reference_id in export_one

    stateful_references = {reference.id for reference in list_references(reopened_store)}
    assert standard_reference_id in stateful_references
    assert paper_reference_id in stateful_references

    assert [theorem.id for theorem in list_theorems(reopened_store)] == ["thm_aux", "thm_main"]

    memory = load_memory(reopened_store)
    assert memory.handoff_snapshots[-1].handoff_note == "handoff after grounding"
    assert memory.working[0].content == "searching for the bridge lemma"

    assert read_latest_snapshot(reopened_store) is not None
