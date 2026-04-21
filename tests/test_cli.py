from pathlib import Path

from typer.testing import CliRunner

from proof_cli.blockers import add_blocker
from proof_cli.cli import app
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremStatus, TrustLevel
from proof_cli.memory import list_memory_artifacts, record_memory
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import set_current_context, set_current_theorem
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import approve_reference, defer_reference, ensure_project, import_reference
from proof_cli.theorems import add_theorem


runner = CliRunner()


def _seed_phase_two_project(tmp_path: Path) -> tuple[str, str, str]:
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
    record_memory(
        store,
        "semantic",
        "standard estimate is callable in context",
        theorem_id="thm_main",
        importance="high",
    )
    record_memory(store, "episodic", "paper route failed assumption match", theorem_id="thm_main", route_id="route_paper")
    record_memory(store, "procedural", "review imported results before reuse", theorem_id="thm_main")

    semantic_memory = next(
        artifact for artifact in list_memory_artifacts(store) if artifact.content == "standard estimate is callable in context"
    )
    return standard_reference.id, paper_reference.id, semantic_memory.id


def test_help_lists_phase_two_commands(tmp_path: Path):
    _seed_phase_two_project(tmp_path)

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "reference" in result.stdout
    assert "memory" in result.stdout
    assert "provenance" in result.stdout
    assert "search" in result.stdout
    assert "theorem" in result.stdout


def test_phase_two_cli_paths_are_reachable_and_readable(tmp_path: Path):
    reference_id, paper_reference_id, memory_id = _seed_phase_two_project(tmp_path)

    result = runner.invoke(app, ["search", "Auxiliary Lemma", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "query: Auxiliary Lemma" in result.stdout
    assert "sources:" in result.stdout
    assert "thm_aux" in result.stdout

    result = runner.invoke(app, ["reference", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "References:" in result.stdout
    assert "Standard Estimate" in result.stdout
    assert "Paper Lemma" in result.stdout

    result = runner.invoke(app, ["reference", "show", reference_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"title": "Standard Estimate"' in result.stdout
    assert '"review_status": "approved"' in result.stdout

    result = runner.invoke(
        app,
        [
            "reference",
            "review",
            paper_reference_id,
            "defer",
            "--root",
            str(tmp_path),
            "--rationale",
            "still needs checking",
        ],
    )
    assert result.exit_code == 0
    assert f"review:{paper_reference_id}:deferred" in result.stdout

    result = runner.invoke(app, ["theorem", "extract", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"callable": true' in result.stdout

    result = runner.invoke(
        app,
        ["theorem", "ground", "thm_main", "--reference-id", reference_id, "--root", str(tmp_path), "--notes", "grounded by standard estimate"],
    )
    assert result.exit_code == 0
    assert f"ground:thm_main:{reference_id}" in result.stdout

    result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Memory:" in result.stdout
    assert "standard estimate is callable in context" in result.stdout

    result = runner.invoke(app, ["memory", "show", memory_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"layer": "semantic"' in result.stdout

    result = runner.invoke(app, ["provenance", "show", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"kind": "theorem"' in result.stdout
    assert '"callable": true' in result.stdout
