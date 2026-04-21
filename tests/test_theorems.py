from pathlib import Path

from proof_cli.cli import app
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem, apply_theorem, theorem_callability
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
    )
    set_current_theorem(store, "thm_2")
    ok, reason = apply_theorem(store, "thm_2")
    assert ok is False
    assert "missing assumptions" in reason
