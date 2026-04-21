from __future__ import annotations

import json
from pathlib import Path

from proof_cli.commands import cmd_proof_provenance_show
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


def test_parse_program_classifies_retrieval_grounding_and_proof_commands() -> None:
    program = parse_program(
        """
        search compactness lemma
        import thm_imported
        ground thm_imported using ref_standard_1, ref_paper_1
        review thm_imported approve grounded after check
        goal theorem_1
        assert obvious intermediate step
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


def test_vague_statement_creates_obligation(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    results = elaborate_program(store, parse_program("goal theorem_2\ndefer obvious conclusion"))
    assert results[1] == "defer:obvious conclusion"
    state = load_state(store)
    assert state.open_obligations
