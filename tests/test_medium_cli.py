"""The Medium of a node from the CLI (spec #145): `node create --medium`, `node medium set`, the views."""

import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.storage import ensure_project

runner = CliRunner()


def _run(root: Path, *args: str):
    return runner.invoke(app, [*args, "--root", str(root)])


def _data(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


def test_node_create_takes_a_medium_and_every_view_carries_it(tmp_path: Path):
    ensure_project(tmp_path)
    created = _data(_run(tmp_path, "node", "create", "c1", "claim", "n ≤ 10^4 holds", "--medium", "computation", "--json"))
    assert created["medium"] == "computation"
    assert _data(_run(tmp_path, "node", "show", "c1", "--json"))["medium"] == "computation"
    (listed,) = _data(_run(tmp_path, "node", "list", "--json"))
    assert listed["medium"] == "computation"
    shown = _run(tmp_path, "node", "show", "c1")
    assert shown.exit_code == 0 and "computation" in shown.output and "run.sh" in shown.output


def test_node_show_json_names_a_computations_entry_as_run_script_never_as_working_proof(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "c1", "claim", "a computation", "--medium", "computation", "--json"))
    _data(_run(tmp_path, "node", "create", "c2", "claim", "a written proof", "--json"))
    computation = _data(_run(tmp_path, "node", "show", "c1", "--json"))
    assert computation["run_script"] == "proofs/c1/run.sh" and computation["working_proof"] is None
    written = _data(_run(tmp_path, "node", "show", "c2", "--json"))
    assert written["working_proof"] == "proofs/c2/proof.tex" and "run_script" not in written


def test_node_medium_set_switches_and_refuses_what_the_service_refuses(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "c1", "claim", "a claim", "--json"))
    switched = _data(_run(tmp_path, "node", "medium", "set", "c1", "computation", "--json"))
    assert switched["medium"] == "computation"
    refused = _run(tmp_path, "node", "medium", "set", "c1", "notebook", "--json")
    assert refused.exit_code == 1 and json.loads(refused.output)["error"]["code"] == "INVALID_MEDIUM"


def test_fog_crystallize_takes_a_medium(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "fog", "add", "machine-checkable for n ≤ 10^4", "--json"))
    made = _data(_run(tmp_path, "fog", "crystallize", "fog-1", "c-check", "For every n ≤ 10^4 it holds", "--medium", "computation", "--json"))
    assert made["medium"] == "computation"
