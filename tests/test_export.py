from pathlib import Path

from proof_cli.commands import cmd_export
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.goals import add_goal
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import set_current_context, record_theorem_usage
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem, apply_theorem
from proof_cli.domain import ProofObligation


def test_export_includes_proved_assumed_and_open_sections(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="Exported Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    set_current_context(store, ["A"])
    add_goal(store, "theorem_1")
    record_theorem_usage(store, "thm_1")
    add_obligation(
        store,
        ProofObligation(
            id="obl_1",
            goal_statement="finish proof",
            required_for="thm_1",
        ),
    )
    output = cmd_export(root=tmp_path)
    assert "Proof Export" in output
    assert "Proved:" in output
    assert "Assumed:" in output
    assert "Open:" in output
    assert "thm_1" in output
    assert "theorem_1" in output
