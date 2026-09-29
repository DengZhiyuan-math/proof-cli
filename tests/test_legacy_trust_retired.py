"""Legacy trust is retired (ADR-0012, #90): only proof-map nodes answer what can be called.

The legacy commands stay, frozen, but every place one reports a callable, trust or review
state says it is legacy and not a trust source. The commands that only refused are gone.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _legacy_seed import seed_reference_review
from proof_cli.cli import app
from proof_cli.domain import ProofObligation, TheoremStatus, TrustLevel
from proof_cli.obligations import add_obligation, list_obligations
from proof_cli.proof_state import set_current_context, set_current_theorem
from proof_cli.references import ReferenceRecord, ReferenceReviewStatus, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference
from proof_cli.theorems import LEGACY_TRUST_NOTICE, add_theorem

runner = CliRunner()


def _seed(tmp_path: Path) -> None:
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
    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A"])
    import_reference(
        store,
        ReferenceRecord(id="ref_std", title="Standard Estimate", year=2023, source_type=ReferenceSourceType.standard_reference),
    )
    seed_reference_review(store, "ref_std", ReferenceReviewStatus.approved)
    import_reference(store, ReferenceRecord(id="ref_new", title="Unreviewed Paper", year=2024))


def _invoke(tmp_path: Path, *args: str):
    return runner.invoke(app, [*args, "--root", str(tmp_path)])


@pytest.mark.parametrize("command", [["obligation", "resolve", "obl_1"], ["reference", "review", "ref_std", "approve"]])
@pytest.mark.parametrize("json_output", [False, True])
def test_the_refusing_commands_are_gone(tmp_path: Path, command, json_output):
    _seed(tmp_path)
    result = _invoke(tmp_path, *command, *(["--json"] if json_output else []))
    assert result.exit_code == 2
    if json_output:
        error = json.loads(result.stdout)["error"]
        assert error["code"] == "USAGE_ERROR" and "No such command" in error["message"]
    else:
        assert "No such command" in result.output


LABELLED_COMMANDS = [
    ["theorem", "extract", "thm_main"],
    ["theorem", "apply", "thm_main"],
    ["explain", "apply", "thm_main"],
    ["bug", "scan", "thm_main"],
    ["provenance", "show", "thm_main"],
    ["provenance", "show", "ref_std"],
    ["reference", "list"],
    ["export"],
]


@pytest.mark.parametrize("command", LABELLED_COMMANDS, ids=" ".join)
def test_a_legacy_callable_or_trust_output_says_it_is_not_a_trust_source(tmp_path: Path, command):
    _seed(tmp_path)
    result = _invoke(tmp_path, *command)
    assert result.exit_code == 0, result.output
    assert LEGACY_TRUST_NOTICE in result.stdout


@pytest.mark.parametrize("command", LABELLED_COMMANDS, ids=" ".join)
def test_its_json_envelope_carries_the_legacy_notice(tmp_path: Path, command):
    _seed(tmp_path)
    result = _invoke(tmp_path, *command, "--json")
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True and envelope["command"] == ".".join(command[:2] if len(command) > 1 else command)
    assert envelope["data"]["legacy_notice"] == LEGACY_TRUST_NOTICE


def test_the_notice_says_the_proof_map_answers_what_can_be_called():
    assert LEGACY_TRUST_NOTICE == "legacy — not a trust source; what can be called is answered by the proof map"


def test_a_failed_ground_no_longer_adds_an_obligation(tmp_path: Path):
    _seed(tmp_path)
    store = ensure_project(tmp_path)
    before = [obligation.id for obligation in list_obligations(store)]

    result = _invoke(tmp_path, "theorem", "ground", "thm_main", "--reference-id", "ref_new")

    assert result.exit_code == 0
    assert result.stdout.startswith("ground:blocked:")
    assert [obligation.id for obligation in list_obligations(store)] == before
    assert _invoke(tmp_path, "obligation", "list").stdout.strip() == "No obligations"


def test_project_analyze_no_longer_suggests_resolving_an_obligation(tmp_path: Path):
    _seed(tmp_path)
    add_obligation(ensure_project(tmp_path), ProofObligation(id="obl_open", goal_statement="bridge A to C", required_for="thm_main"))

    result = _invoke(tmp_path, "project", "analyze")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["bottleneck_kind"] == "obligation"
    assert payload["promising_next_steps"]
    assert "resolve obligation" not in result.stdout
