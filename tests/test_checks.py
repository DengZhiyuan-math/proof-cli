from pathlib import Path

from proof_cli.checks import run_standard_checks
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.memory import track_symbol
from proof_cli.obligations import add_obligation
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem
from proof_cli.domain import ProofObligation
from proof_cli.proof_state import set_current_context


def test_standard_checks_return_expected_signals(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="Main Lemma",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.temporary_admit,
        dependencies=[],
    )
    set_current_context(store, ["A"])
    track_symbol(store, "A")
    add_obligation(
        store,
        ProofObligation(
            id="obl_1",
            goal_statement="compressed reasoning",
            required_for="thm_1",
            blocking_reason="compressed reasoning",
        ),
    )
    checks = run_standard_checks(store, "thm_1")
    assert [check.severity for check in checks[:4]] == ["warn", "fail", "pass", "pass"]
    assert any(check.name == "omission_marker" and check.severity == "warn" for check in checks)


def test_checks_flag_missing_dependency(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_2",
        kind="theorem",
        name="Dependent Result",
        statement="C -> D",
        assumptions=["C"],
        exports=["D"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["missing_dep"],
    )
    checks = run_standard_checks(store, "thm_2")
    assert any(check.name == "dependency_existence" and check.severity == "fail" for check in checks)
