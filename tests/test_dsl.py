from pathlib import Path

from proof_cli.dsl import parse_program
from proof_cli.elaboration import elaborate_program
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.proof_state import load_state
from proof_cli.obligations import list_obligations


def test_parse_and_elaborate_program(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="Reusable Lemma",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )

    program = parse_program(
        """
        goal theorem_1
        assume A
        apply thm_1
        assert obvious intermediate step
        defer finish later
        split
        close
        """
    )
    results = elaborate_program(store, program)

    assert results[0] == "goal:theorem_1"
    assert "apply:thm_1" in results[2]
    state = load_state(store)
    assert "A" in state.current_context
    assert state.recent_theorem_usage == ["thm_1"]
    assert state.open_obligations
    assert any("subgoal 1" in obligation.goal_statement for obligation in list_obligations(store))


def test_vague_statement_creates_obligation(tmp_path: Path):
    store = ensure_project(tmp_path)
    results = elaborate_program(store, parse_program("goal theorem_2\ndefer obvious conclusion"))
    assert results[1] == "defer:obvious conclusion"
    state = load_state(store)
    assert state.open_obligations
