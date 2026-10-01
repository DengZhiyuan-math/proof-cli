"""`proof node progress` (spec #145, decided in #144): how a Proof agent reports its plan and each
step of its work on a node, as project state written through `proof` like everything else.

The report is an event (`agent_progress`), never a decision and never a file in the node folder
(a snapshot would freeze it). It names the role that reported (Prover, Typesetter or Numerics),
read from the runtime's PROOF_AGENT_ROLE unless given; a plan is a list of steps, a step report is
its number, its status (started, done, stuck) and a note. The work log the studio shows is these
events merged with the automatic ones (a split, a review request, an Evidence check, a fog item).
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import ProofMapError, create_node, record_progress, work_log
from proof_cli.storage import ensure_project

runner = CliRunner()


def _run(root: Path, *args: str, env=None):
    return runner.invoke(app, [*args, "--root", str(root)], env=env or {})


def _data(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


# -- the service ------------------------------------------------------------------------------------


def test_a_plan_and_its_steps_are_events_on_the_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    record_progress(store, "N", role="prover", by="claude-code", plan=["read what the project holds", "draft the proof", "request review"])
    record_progress(store, "N", role="prover", by="claude-code", step=1, status="started")
    record_progress(store, "N", role="prover", by="claude-code", step=1, status="done", note="nothing in the project settles it")
    log = work_log(store, "N")
    kinds = [(entry["kind"], entry["role"], entry.get("step"), entry.get("status")) for entry in log]
    assert kinds == [("plan", "prover", None, None), ("step", "prover", 1, "started"), ("step", "prover", 1, "done")]
    assert log[0]["plan"] == ["read what the project holds", "draft the proof", "request review"]
    assert log[2]["note"] == "nothing in the project settles it" and all(entry["by"] == "claude-code" for entry in log)


def test_the_work_log_merges_what_the_agent_did_through_proof(tmp_path: Path):
    from proof_cli.fog import add_fog
    from proof_cli.proof_map import split_node

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="lemma", statement="a lemma")
    record_progress(store, "N", role="prover", by="claude-code", plan=["split it"])
    record_progress(store, "N", role="prover", by="claude-code", step=1, status="started")
    split_node(store, "N", [{"id": "N1", "statement": "first half"}], created_by="claude-code")
    add_fog(store, "the second half may need compactness", near=["N"], created_by="claude-code")
    record_progress(store, "N", role="prover", by="claude-code", step=1, status="done")
    from proof_cli.fog import list_fog, record_experiment

    (item,) = list_fog(store)
    record_experiment(store, item.id, "refutes", summary="n = 7 is a counterexample", run_by="claude-code")
    kinds = [entry["kind"] for entry in work_log(store, "N")]
    assert kinds == ["plan", "step", "split", "fog", "step", "experiment"]  # in time order, the automatic events between the reports
    assert work_log(store, "N")[-1]["outcome"] == "refutes"
    split = next(entry for entry in work_log(store, "N") if entry["kind"] == "split")
    assert split["nodes"] == ["N1"] and split["by"] == "claude-code"


@pytest.mark.parametrize("bad, code", [
    ({"role": "editor", "plan": ["x"]}, "INVALID_ROLE"),
    ({"role": "prover", "step": 1, "status": "finished"}, "INVALID_PROGRESS_STATUS"),
    ({"role": "prover", "step": 1}, "PROGRESS_STATUS_REQUIRED"),
    ({"role": "prover"}, "PROGRESS_EMPTY"),
])
def test_a_malformed_report_is_refused(tmp_path: Path, bad, code):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    with pytest.raises(ProofMapError) as caught:
        record_progress(store, "N", by="claude-code", **bad)
    assert caught.value.code == code


# -- the CLI -----------------------------------------------------------------------------------------


def test_the_cli_reports_a_plan_and_a_step_and_reads_the_role_from_the_runtime(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "N", "claim", "a claim", "--json"))
    env = {"PROOF_AGENT_ROLE": "numerics", "PROOF_AGENT_NAME": "claude-code"}
    plan = _data(_run(tmp_path, "node", "progress", "N", "--plan", "write check.py", "--plan", "run it", "--json", env=env))
    assert plan["kind"] == "plan" and plan["role"] == "numerics" and plan["by"] == "claude-code" and plan["plan"] == ["write check.py", "run it"]
    step = _data(_run(tmp_path, "node", "progress", "N", "--step", "2", "--status", "stuck", "--note", "no numpy here", "--json", env=env))
    assert step["kind"] == "step" and step["step"] == 2 and step["status"] == "stuck" and step["note"] == "no numpy here"
    log = _data(_run(tmp_path, "node", "progress", "N", "--json"))
    assert [entry["kind"] for entry in log] == ["plan", "step"]
    human = _data(_run(tmp_path, "node", "progress", "N", "--step", "2", "--status", "done", "--role", "prover", "--by", "human", "--json"))
    assert human["role"] == "prover" and human["by"] == "human"


def test_without_a_role_the_cli_refuses_a_report(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "N", "claim", "a claim", "--json"))
    refused = _run(tmp_path, "node", "progress", "N", "--plan", "x", "--json", env={"PROOF_AGENT_ROLE": ""})
    assert refused.exit_code == 1 and json.loads(refused.output)["error"]["code"] == "ROLE_REQUIRED"
