"""ADR-0024 point 13: an audit reads the proof afresh, and nothing of the earlier record anchors it.

A trial's audit briefings carried no earlier verdict, yet every audit turn ran `proof node show <node> --json`, as its
brief asks, and read there every earlier Evidence check with its notes — including the passing audits of the very
snapshot it was auditing — and `proof node progress <node>` prints the work log's verdicts and attempts. In an audit's
runtime (PROOF_AGENT_AUDIT, set by the run for that turn) both reads leave the earlier record out: the Evidence checks
of every node shown, and every work-log entry but the Standing questions and their answers, which the audit reads.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from _proofs import submit_proof

from proof_cli.cli import app
from proof_cli.proof_map import answer_question, claim_node, create_node, record_progress
from proof_cli.storage import ensure_project

runner = CliRunner()
AUDIT = {"PROOF_AGENT_NAME": "claude-code", "PROOF_AGENT_ROLE": "verifier", "PROOF_AGENT_NODE": "thm", "PROOF_AGENT_AUDIT": "1"}


def _audited(tmp_path: Path) -> str:
    """A Theorem awaiting review on a Lemma, each with a passing Evidence check, the Theorem's log holding a verdict, an
    attempt and an answered Standing question."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    create_node(store, node_id="thm", kind="theorem", statement="T", dependencies=["lem"])
    for node_id in ("lem", "thm"):
        claim_node(store, node_id, claimant_id="prover-1")
        proof = submit_proof(store, node_id, claimant_id="prover-1", scoping_rationale="scoped", content=f"proof of {node_id}")
        runner.invoke(app, ["node", "evidence", "record", proof.id, "passed", "--notes", "every step checked", "--run-by",
                            "claude-code/verifier", "--root", str(tmp_path)])
    record_progress(store, "thm", role="prover", by="prover-1", attempt="the direct bound", method="by parts", failed_on="a boundary term")
    asked = record_progress(store, "thm", role="prover", by="prover-1", question="read c as any constant; the alternative: the best one")
    answer_question(store, "thm", asked["id"], keep=True)
    record_progress(store, "thm", role="verifier", by="claude-code", verdict="passed", note="every step holds")
    return str(tmp_path)


def _show(root: str, node_id: str, env: dict | None = None) -> dict:
    result = runner.invoke(app, ["node", "show", node_id, "--root", root, "--json"], env=env)
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)["data"]


def _log(root: str, env: dict | None = None, *, json_output: bool = True):
    result = runner.invoke(app, ["node", "progress", "thm", "--root", root, *(["--json"] if json_output else [])], env=env)
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)["data"] if json_output else result.stdout


def test_outside_an_audit_node_show_and_the_work_log_give_the_whole_record(tmp_path: Path):
    root = _audited(tmp_path)
    assert [check["notes"] for check in _show(root, "thm")["evidence_checks"]] == ["every step checked"]
    assert {entry["kind"] for entry in _log(root)} >= {"verdict", "attempt", "question", "answer"}


def test_an_audit_reads_no_evidence_check_of_any_node(tmp_path: Path):
    root = _audited(tmp_path)
    for node_id in ("thm", "lem"):  # the audited node's, and a dependency's
        shown = _show(root, node_id, AUDIT)
        assert shown["evidence_checks"] == [], node_id
        assert "audit" in shown["evidence_checks_withheld"], node_id
        assert shown["statement"] and shown["snapshots"], node_id  # the rest of the node is there to read
    assert "evidence_checks_withheld" not in _show(root, "thm")


def test_an_audit_reads_only_the_standing_questions_of_the_work_log(tmp_path: Path):
    root = _audited(tmp_path)
    assert [entry["kind"] for entry in _log(root, AUDIT)] == ["question", "answer"]
    text = _log(root, AUDIT, json_output=False)
    assert "every step holds" not in text and "the direct bound" not in text
    assert "read c as any constant" in text and "withheld" in text
