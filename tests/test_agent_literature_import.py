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
