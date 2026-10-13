import json

import pytest
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import create_node, list_nodes
from proof_cli.storage import ensure_project


@pytest.mark.parametrize("kind,parent,reassign", [("lemma", "T", False), ("imported_result", "L", False), ("imported_result", "T", True)])
def test_agent_import_cannot_create_local_work_or_attach_to_another_node(tmp_path, kind, parent, reassign):
    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="theorem", statement="Main")
    create_node(store, node_id="L", kind="lemma", statement="Other work")
    args = ["node", "create", "new", kind, "a statement", "--parent", parent,
            "--source-locator", "Theorem 1", "--source-version", "v1", "--root", str(tmp_path), "--json"]
    if reassign:
        args += ["--reassign"]
    result = CliRunner().invoke(app, args, env={"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NODE": "T"})
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"]["code"] == "AGENT_IMPORT_REFUSED"
    assert {n.id for n in list_nodes(store)} == {"T", "L"}


def test_scoped_decomposer_reuses_only_an_import_for_its_current_node(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="theorem", statement="Main")
    create_node(store, node_id="L", kind="lemma", statement="Local")
    create_node(store, node_id="R", kind="imported_result", statement="Known", source_locator="Theorem 1", source_version="v1")
    env = {"PROOF_AGENT_ROLE": "decomposer", "PROOF_AGENT_NODE": "T", "PROOF_AGENT_NAME": "worker"}
    refused = CliRunner().invoke(app, ["node", "depend", "T", "--add", "L", "--root", str(tmp_path), "--json"], env=env)
    assert refused.exit_code == 1 and json.loads(refused.output)["error"]["code"] == "AGENT_IMPORT_REFUSED"
    allowed = CliRunner().invoke(app, ["node", "depend", "T", "--add", "R", "--root", str(tmp_path), "--json"], env=env)
    assert allowed.exit_code == 0, allowed.output


@pytest.mark.parametrize("env", [{"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NODE": "T", "PROOF_AGENT_NAME": "prover-1"},
                                 {"PROOF_AGENT_NAME": "ask"},
                                 {"PROOF_AGENT_ROLE": "reader"}])
def test_an_agent_never_writes_as_the_researcher(tmp_path, env):
    """An agent's import written as "human" would meet the researcher's Trust rules and skip Reference review."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="theorem", statement="Main")
    root = ["--root", str(tmp_path), "--json"]
    runs = [
        ["reference", "import", "ref", "A paper", "2020", "--author", "A. Author", "--source-type", "research_paper", "--created-by", "human"],
        ["node", "create", "I", "imported_result", "Known", "--source-locator", "Theorem 1", "--source-version", "v1",
         *([] if env.get("PROOF_AGENT_ROLE") == "reader" else ["--parent", "T"]), "--created-by", "human"],  # the Reader takes no --parent
        ["node", "depend", "T", "--add", "T", "--by", "human"],
        ["fog", "add", "a direction", "--created-by", "human"],
    ]
    for args in runs:
        result = CliRunner().invoke(app, args + root, env=env)
        assert result.exit_code == 1, (args, result.output)
        assert json.loads(result.output)["error"]["code"] == "AGENT_AUTHOR_REFUSED", (args, result.output)
    assert {n.id for n in list_nodes(store)} == {"T"}


def test_an_agent_import_under_its_own_name_is_recorded_as_the_agents(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="theorem", statement="Main")
    env = {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NODE": "T", "PROOF_AGENT_NAME": "prover-1"}
    for created_by in (["--created-by", "prover-1"], []):
        node_id = f"I{len(created_by)}"
        result = CliRunner().invoke(app, ["node", "create", node_id, "imported_result", "Known", "--source-locator", "Theorem 1",
                                          "--source-version", "v1", "--parent", "T", *created_by, "--root", str(tmp_path), "--json"], env=env)
        assert result.exit_code == 0, result.output
    assert {n.id: n.created_by for n in list_nodes(store) if n.id != "T"} == {"I0": "prover-1", "I2": "prover-1"}
