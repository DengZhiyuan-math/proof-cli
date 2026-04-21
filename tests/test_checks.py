from pathlib import Path

from proof_cli.checks import run_standard_checks
from proof_cli.domain import TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
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


def test_imported_theorem_checks_surface_weak_grounding_and_export_stretch(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_imported",
        kind="theorem",
        name="Imported Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
        dependencies=[],
    )
    set_current_context(store, ["A"])
    track_symbol(store, "A")
    checks = run_standard_checks(store, "thm_imported")
    assert any(check.name == "assumption_presence" and check.severity == "warn" and "weak grounding" in check.message for check in checks)
    assert any(check.name == "export_strength" and check.severity == "warn" and "without grounded support" in check.message for check in checks)


def test_checks_detect_indirect_dependency_cycle(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_a",
        kind="theorem",
        name="A",
        statement="A",
        assumptions=[],
        exports=[],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_b"],
    )
    add_theorem(
        store,
        theorem_id="thm_b",
        kind="theorem",
        name="B",
        statement="B",
        assumptions=[],
        exports=[],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_a"],
    )
    checks = run_standard_checks(store, "thm_a")
    assert any(check.name == "circular_dependency" and check.severity == "fail" and "thm_a -> thm_b -> thm_a" in check.message for check in checks)
