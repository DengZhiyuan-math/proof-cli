from pathlib import Path

from proof_cli.cli import app
from proof_cli.domain import TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem, add_usage_note, apply_theorem, theorem_callability, update_theorem
from proof_cli.proof_state import set_current_context, set_current_theorem
from typer.testing import CliRunner


runner = CliRunner()


def test_theorem_add_show_list_and_apply(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="Spectral Decomposition",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )
    set_current_context(store, ["A"])
    ok, reason = theorem_callability(store, "thm_1")
    assert ok is True
    assert reason == "callable"

    ok, reason = apply_theorem(store, "thm_1")
    assert ok is True
    assert reason == "applied"

    show = runner.invoke(app, ["theorem", "show", "thm_1", "--root", str(tmp_path)])
    assert show.exit_code == 0
    assert "Spectral Decomposition" in show.stdout

    listing = runner.invoke(app, ["theorem", "list", "--root", str(tmp_path)])
    assert listing.exit_code == 0
    assert "thm_1" in listing.stdout


def test_theorem_apply_rejects_missing_assumptions(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_2",
        kind="theorem",
        name="Auxiliary Lemma",
        statement="C -> D",
        assumptions=["C"],
        exports=["D"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
    )
    set_current_theorem(store, "thm_2")
    ok, reason = apply_theorem(store, "thm_2")
    assert ok is False
    assert "missing assumptions" in reason


def test_theorem_record_round_trips_provenance_review_and_usage_notes(tmp_path: Path):
    store = ensure_project(tmp_path)
    contract = add_theorem(
        store,
        theorem_id="thm_3",
        kind="lemma",
        name="Imported Grounding Lemma",
        statement="A -> C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
        source_ref="arxiv:2201.00001",
        grounded_reference_ids=["ref_1"],
        grounded_theorem_ids=["thm_base"],
        local_usage_notes=["project-local search note"],
        imported_usage_notes=["imported from an approved standard result"],
        notes="Grounded against imported literature.",
    )

    payload = contract.model_dump(mode="json")
    reloaded = type(contract).model_validate_json(contract.model_dump_json())

    assert payload["provenance_kind"] == "imported"
    assert payload["review_state"] == "approved"
    assert payload["source_ref"] == "arxiv:2201.00001"
    assert payload["grounded_reference_ids"] == ["ref_1"]
    assert payload["grounded_theorem_ids"] == ["thm_base"]
    assert payload["local_usage_notes"] == ["project-local search note"]
    assert payload["imported_usage_notes"] == ["imported from an approved standard result"]
    assert reloaded == contract


def test_theorem_update_preserves_prior_versions_and_explicit_supersession(tmp_path: Path):
    store = ensure_project(tmp_path)
    original = add_theorem(
        store,
        theorem_id="thm_4",
        kind="theorem",
        name="Replacement Target",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        provenance_kind=TheoremProvenanceKind.local,
        review_state=TheoremReviewState.approved,
        local_usage_notes=["project-local proof route"],
    )

    add_usage_note(store, "thm_4", "imported example anchored the update", provenance_kind=TheoremProvenanceKind.imported)
    updated = update_theorem(
        store,
        "thm_4",
        statement="A -> C",
        exports=["C"],
        imported_usage_notes=["replacement grounded in imported result"],
    )

    assert updated.version == original.version + 2
    assert updated.supersedes_version == original.version + 1
    assert updated.source_ref == original.source_ref
    assert updated.local_usage_notes == ["project-local proof route"]
    assert updated.imported_usage_notes == ["imported example anchored the update", "replacement grounded in imported result"]

    with store.connect() as conn:
        rows = conn.execute(
            "SELECT version, is_current, data FROM theorem_contracts WHERE id = ? ORDER BY version",
            ("thm_4",),
        ).fetchall()

    assert len(rows) == 3
    first = type(original).model_validate_json(rows[0]["data"])
    second = type(original).model_validate_json(rows[1]["data"])
    third = type(original).model_validate_json(rows[2]["data"])
    assert rows[0]["version"] == 1
    assert rows[0]["is_current"] == 0
    assert rows[1]["version"] == 2
    assert rows[1]["is_current"] == 0
    assert rows[2]["version"] == 3
    assert rows[2]["is_current"] == 1
    assert first.statement == "A -> B"
    assert first.source_ref == "internal/project"
    assert second.statement == "A -> B"
    assert second.imported_usage_notes == ["imported example anchored the update"]
    assert third.statement == "A -> C"
    assert third.supersedes_version == 2


def test_imported_theorem_requires_review_approval_before_callability(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_5",
        kind="result",
        name="Imported Candidate Result",
        statement="D -> E",
        assumptions=["D"],
        exports=["E"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.candidate,
        source_ref="doi:10.1000/example",
        imported_usage_notes=["candidate literature result"],
    )

    set_current_context(store, ["D"])
    ok, reason = theorem_callability(store, "thm_5")
    assert ok is False
    assert "not approved" in reason
