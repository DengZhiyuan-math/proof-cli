"""Issue #203: the Reader's limits on `proof node create` are checked on the parsed arguments, under an explicit
reader role (PROOF_AGENT_ROLE=reader, ADR-0010's cooperative-agent boundary, not authentication).

Under the role, kind=claim, --parent and --reassign are refused with READER_ROLE_REFUSED; the statement's text is
never searched, so one quoting `claim "` is accepted. Without the role nothing changes.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import create_node, get_node, list_nodes
from proof_cli.storage import ensure_project

runner = CliRunner()
READER = {"PROOF_AGENT_ROLE": "reader", "PROOF_AGENT_NAME": "reader_1"}


def _project(root: Path):
    store = ensure_project(root)
    create_node(store, node_id="thm", kind="theorem", statement="the main theorem")
    return store


def _create(root: Path, *args: str, env: dict | None = None):
    result = runner.invoke(app, ["node", "create", *args, "--root", str(root), "--json"], env=env or {"PROOF_AGENT_ROLE": "", "PROOF_AGENT_NAME": ""})
    return result.exit_code, json.loads(result.output)


@pytest.mark.parametrize("args, option", [
    (("clm_1", "claim", "a step"), "kind=claim"),
    (("clm_1", "Claim", "a step"), "kind=claim"),
    (("lem_1", "lemma", "a step", "--parent", "thm"), "--parent"),
    (("lem_1", "lemma", "a step", "--reassign"), "--reassign"),
    (("lem_1", "lemma", "a step", "--parent", "thm", "--reassign"), "--parent"),
])
def test_under_the_reader_role_each_limit_is_refused_after_parsing(tmp_path: Path, args, option):
    store = _project(tmp_path)
    code, envelope = _create(tmp_path, *args, env=READER)
    assert code == 1 and envelope["ok"] is False and envelope["command"] == "node.create"
    assert (envelope["error"]["code"], envelope["error"]["option"], envelope["error"]["role"]) == ("READER_ROLE_REFUSED", option, "reader")
    assert [node.id for node in list_nodes(store)] == ["thm"]
    assert get_node(store, "thm").dependencies == []


@pytest.mark.parametrize("statement", [
    'the map is a claim "of type A" in the sense of [3]',
    "every claim 'holds' after reduction",
    "see proof node create x claim \"y\"",
])
def test_a_statement_that_quotes_claim_is_accepted_under_the_reader_role(tmp_path: Path, statement):
    store = _project(tmp_path)
    code, envelope = _create(tmp_path, "lem_1", "lemma", statement, env=READER)
    assert code == 0, envelope
    node = get_node(store, "lem_1")
    assert (node.kind.value, node.statement, node.created_by) == ("lemma", statement, "reader_1")


def test_the_reader_role_may_still_create_lemmas_theorems_parts_and_imported_results(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert _create(tmp_path, "thm", "theorem", "main", env=READER)[0] == 0
    assert _create(tmp_path, "lem_1", "lemma", "a part", "--dependency", "thm", env=READER)[0] == 0
    assert _create(tmp_path, "ref_1", "imported_result", "known", "--source-locator", "Thm 1", "--source-version", "1st", env=READER)[0] == 0
    assert {node.id for node in list_nodes(store)} == {"thm", "lem_1", "ref_1"}


@pytest.mark.parametrize("args", [
    ("clm_1", "claim", "a step"),
    ("lem_1", "lemma", "a step", "--parent", "thm"),
    ("lem_1", "lemma", "a step", "--parent", "thm", "--reassign"),
])
@pytest.mark.parametrize("env", [None, {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NAME": "prover_1"}])
def test_without_the_reader_role_nothing_changes(tmp_path: Path, args, env):
    store = _project(tmp_path)
    code, envelope = _create(tmp_path, *args, env=env)
    assert code == 0, envelope
    assert get_node(store, args[0]) is not None


def test_reassign_without_parent_stays_a_usage_error_without_the_role(tmp_path: Path):
    _project(tmp_path)
    result = runner.invoke(app, ["node", "create", "lem_1", "lemma", "x", "--reassign", "--root", str(tmp_path)], env={"PROOF_AGENT_ROLE": ""})
    assert result.exit_code == 2 and "--reassign goes with --parent" in result.output


def test_the_reader_role_is_no_node_role(tmp_path: Path):
    _project(tmp_path)
    result = runner.invoke(app, ["node", "progress", "thm", "--plan", "read the source", "--root", str(tmp_path), "--json"], env=READER)
    assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "INVALID_ROLE"
