"""Who wrote it, at the CLI boundary (ADR-0021 points 5–6).

Agent-written text is unfixed and restatable by agents, the researcher's is fixed for agents from the start; so what a
create command records as its author decides who may later restate it. An agent's runtime sets PROOF_AGENT_NAME: a
create command without `--created-by`, and an edit without `--by`, are that agent's, and the researcher's ("human")
only outside an agent's runtime. An explicit flag always wins.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import definitions as D
from proof_cli.cli import app
from proof_cli.fog import list_fog
from proof_cli.proof_map import create_node, get_node
from proof_cli.storage import ensure_project, get_reference, list_events

runner = CliRunner()
AGENT = {"PROOF_AGENT_NAME": "reader-1"}


def _run(tmp_path: Path, *args: str, env: dict | None = None) -> dict:
    result = runner.invoke(app, [*args, "--root", str(tmp_path), "--json"], env=env)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


@pytest.mark.parametrize(("env", "flag", "expected"), [
    (AGENT, (), "reader-1"),
    ({"PROOF_AGENT_NAME": ""}, (), "human"),
    (AGENT, ("--created-by", "human"), "human"),
    (AGENT, ("--created-by", "dec-2"), "dec-2"),
])
def test_a_create_command_s_author_is_the_flag_then_the_agent_s_runtime_then_the_researcher(tmp_path: Path, env, flag, expected):
    store = ensure_project(tmp_path)

    _run(tmp_path, "definition", "add", "unit", "u", "--term", "Unit", *flag, env=env)
    _run(tmp_path, "node", "create", "L", "lemma", "s", *flag, env=env)
    _run(tmp_path, "node", "split", "L", "--child", "c1=A", *flag, env=env)
    _run(tmp_path, "fog", "add", "unclear", "--near", "L", *flag, env=env)
    _run(tmp_path, "reference", "import", "ref1", "A Paper", "2020", *flag, env=env)

    assert D.require_definition(store, "unit").created_by == expected
    assert get_node(store, "L").created_by == expected
    assert get_node(store, "c1").created_by == expected
    assert [item.created_by for item in list_fog(store)] == [expected]
    assert get_reference(store, "ref1").created_by == expected


def test_an_edit_without_by_is_the_agent_s_in_its_runtime(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "unit", term="Unit", text="u", created_by="reader-1")
    create_node(store, node_id="L", kind="lemma", statement="s", definitions=["unit"], created_by="reader-1")
    create_node(store, node_id="M", kind="lemma", statement="m", created_by="reader-1")

    _run(tmp_path, "node", "restate", "L", "--statement", "s'", "--reason", "clearer", env=AGENT)
    _run(tmp_path, "definition", "edit", "unit", "--text", "u'", "--reason", "clearer", env=AGENT)
    _run(tmp_path, "node", "depend", "L", "--add", "M", env=AGENT)

    by = {event.kind: (event.payload or {}).get("by") or (event.payload or {}).get("edited_by") for event in list_events(store)}
    assert by["proof_map_node_restated"] == "reader-1"
    assert by["definition_edited"] == "reader-1"
    assert by["proof_map_dependency_added"] == "reader-1"


def test_the_researcher_s_edit_outside_an_agent_s_runtime(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="s")

    _run(tmp_path, "node", "restate", "L", "--statement", "s'", "--reason", "clearer", env={"PROOF_AGENT_NAME": ""})

    [event] = [e for e in list_events(store) if e.kind == "proof_map_node_restated"]
    assert event.payload["by"] == "human"
