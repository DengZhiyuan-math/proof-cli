"""`proof node progress` (spec #145, decided in #144): how a Proof agent reports its plan and each
step of its work on a node, as project state written through `proof` like everything else.

The report is an event (`agent_progress`), never a decision and never a file in the node folder
(a snapshot would freeze it). It names the role that reported (Prover, Typesetter, Numerics, Verifier
or Decomposer), read from the runtime's PROOF_AGENT_ROLE unless given; a plan is a list of steps, a
step report is its number, its status (started, done, stuck) and a note. The work log the studio
shows is these events merged with the automatic ones (a split, a review request, an Evidence check,
a fog item).

ADR-0019 adds two kinds. A verdict is the Verifier's reading of the working proof as it stands —
passed or failed, the objections as its note — bound to the inputs digest of the node folder at that
moment, the hash a Review snapshot's manifest would have, so an edit makes it stale by construction;
only the Verifier records one. An attempt is a line a role abandoned: what it tried to establish,
how, and what it failed on; any role records one. Both are what the run briefs its next turn from.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import proof_map, vault
from proof_cli.cli import app
from proof_cli.domain import AGENT_ROLES, Medium
from proof_cli.proof_map import (
    ProofMapError,
    attempts,
    create_node,
    dependents,
    latest_verdict,
    record_progress,
    siblings,
    verdicts,
    work_log,
    request_review,
)
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
    ({"role": "prover", "step": 1, "status": "needs-human"}, "DECISION_REQUIRED"),
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


# -- seventh review (PR #148): a decision only a human can make, and what each entry and turn carries ----------


def test_a_step_that_needs_a_human_decision_names_it(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "N", "claim", "a claim", "--json"))
    env = {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NAME": "claude-code"}
    asked = _data(_run(tmp_path, "node", "progress", "N", "--step", "1", "--status", "needs-human", "--note", "choose the norm", "--json", env=env))
    assert asked["status"] == "needs-human" and asked["note"] == "choose the norm"
    refused = _run(tmp_path, "node", "progress", "N", "--step", "1", "--status", "needs-human", "--json", env=env)
    assert refused.exit_code == 1 and json.loads(refused.output)["error"]["code"] == "DECISION_REQUIRED"
    shown = _run(tmp_path, "node", "progress", "N")
    assert "needs a human decision — choose the norm" in shown.output


def test_automatic_entries_take_the_role_of_the_turn_that_made_them_and_a_turn_keeps_its_conversation(tmp_path: Path):
    from proof_cli.fog import add_fog
    from proof_cli.proof_map import agent_turn_transcript, record_agent_turn

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    add_fog(store, "the researcher's own hunch", near=["N"], created_by="ada")  # outside any turn: no role
    record_agent_turn(store, "N", phase="started", turn="t1", role="numerics", by="claude-code", provider="claude")
    add_fog(store, "the ratio may stay below 2", near=["N"], created_by="claude-code")
    add_fog(store, "ada's note during the turn", near=["N"], created_by="ada")  # the researcher's, though a turn is running
    record_agent_turn(store, "N", phase="ended", turn="t1", role="numerics", by="claude-code", provider="claude",
                      job=3, session_id="s-1", step=2, events=[{"t": "init", "session_id": "s-1"}, {"t": "text", "text": "checked n ≤ 100"}])
    log = work_log(store, "N")
    fog = [entry for entry in log if entry["kind"] == "fog"]
    assert [(entry["role"], entry["text"]) for entry in fog] == [
        (None, "the researcher's own hunch"), ("numerics", "the ratio may stay below 2"), (None, "ada's note during the turn")]
    (turn,) = [entry for entry in log if entry["kind"] == "turn"]
    assert (turn["role"], turn["job"], turn["session_id"], turn["step"], turn["turn"]) == ("numerics", 3, "s-1", 2, "t1")
    kept = agent_turn_transcript(store, "N", "t1")
    assert kept["events"][1]["text"] == "checked n ≤ 100" and kept["session_id"] == "s-1"
    assert agent_turn_transcript(store, "N", "no-such-turn") is None
    assert agent_turn_transcript(store, "N", "../../escape") is None


# -- ADR-0019: the Verifier's verdict, the record of attempts, and the map around a node ---------------------------


def test_the_roles_are_the_five_adr_0019_names():
    assert AGENT_ROLES == ("prover", "typesetter", "numerics", "verifier", "decomposer")


def test_a_verdict_is_bound_to_the_working_inputs_as_they_stand(tmp_path: Path):
    """The hash is the one a Review snapshot's manifest would have now, and a later edit to proof.tex makes it stale."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    before = vault.read_working_snapshot(store.root, "N", Medium.latex).digest()
    first = record_progress(store, "N", role="verifier", by="claude-code", verdict="failed", note="1. step 2 appeals to Lemma L for a bound L does not give")
    assert first["kind"] == "verdict" and first["outcome"] == "failed" and first["inputs_sha256"] == before
    assert first["role"] == "verifier" and first["by"] == "claude-code" and first["note"].startswith("1. step 2")
    assert set(first) == {"kind", "role", "by", "outcome", "note", "inputs_sha256", "node_id", "at"}
    with vault.working_proof_path(store.root, "N").open("a", encoding="utf-8") as handle:
        handle.write("% the bound is now justified\n")
    after = vault.read_working_snapshot(store.root, "N", Medium.latex).digest()
    assert after != before
    second = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    assert second["inputs_sha256"] == after and second["note"] == ""
    assert [entry["outcome"] for entry in verdicts(store, "N")] == ["failed", "passed"]  # newest last
    newest = latest_verdict(store, "N")
    assert newest is not None and newest["outcome"] == "passed" and newest["inputs_sha256"] == after and "at" in newest
    assert [entry["kind"] for entry in work_log(store, "N")] == ["verdict", "verdict"]


def test_a_node_without_verdicts_has_none(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    assert verdicts(store, "N") == [] and latest_verdict(store, "N") is None and attempts(store, "N") == []


def test_only_the_verifier_records_a_verdict(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    for role in (r for r in AGENT_ROLES if r != "verifier"):
        with pytest.raises(ProofMapError) as caught:
            record_progress(store, "N", role=role, by="claude-code", verdict="passed")
        assert caught.value.code == "VERDICT_ROLE_REQUIRED"
    assert verdicts(store, "N") == []


@pytest.mark.parametrize("bad, code", [
    ({"role": "verifier", "verdict": "inconclusive"}, "INVALID_VERDICT"),
    ({"role": "verifier", "verdict": "failed"}, "OBJECTIONS_REQUIRED"),
    ({"role": "verifier", "verdict": "failed", "note": "   "}, "OBJECTIONS_REQUIRED"),
    ({"role": "prover", "attempt": "the base case"}, "ATTEMPT_INCOMPLETE"),
    ({"role": "prover", "attempt": "the base case", "method": "induction"}, "ATTEMPT_INCOMPLETE"),
    ({"role": "prover", "failed_on": "n = 0"}, "ATTEMPT_INCOMPLETE"),
    ({"role": "editor", "verdict": "passed"}, "INVALID_ROLE"),
])
def test_a_malformed_verdict_or_attempt_is_refused(tmp_path: Path, bad, code):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    with pytest.raises(ProofMapError) as caught:
        record_progress(store, "N", by="claude-code", **bad)
    assert caught.value.code == code
    assert work_log(store, "N") == []


def test_an_unreadable_node_folder_leaves_the_verdicts_hash_null_rather_than_refusing(tmp_path: Path, monkeypatch):
    """A verdict is the Verifier's reading, not a snapshot: when the folder can't be hashed it is still recorded, and a
    verdict without a hash matches no snapshot, so it opens no gate."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")

    def unreadable(root, node_id, medium=None):
        raise OSError(13, "Permission denied", str(root / "proofs" / node_id))

    monkeypatch.setattr(proof_map, "read_working_snapshot", unreadable)
    entry = record_progress(store, "N", role="verifier", by="claude-code", verdict="failed", note="1. nothing could be read")
    assert entry["outcome"] == "failed" and entry["inputs_sha256"] is None
    assert latest_verdict(store, "N")["inputs_sha256"] is None


def test_a_verdict_on_a_computation_node_hashes_its_whole_folder(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="C", kind="claim", statement="a check", medium="computation")
    entry = record_progress(store, "C", role="verifier", by="claude-code", verdict="passed")
    assert entry["inputs_sha256"] == vault.read_working_snapshot(store.root, "C", Medium.computation).digest()


def test_an_attempt_is_what_was_tried_how_and_what_it_failed_on(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    first = record_progress(store, "N", role="prover", by="claude-code", attempt="the base case", method="direct computation", failed_on="n = 0 is not covered")
    assert first["kind"] == "attempt" and first["goal"] == "the base case" and first["method"] == "direct computation" and first["failed_on"] == "n = 0 is not covered"
    assert set(first) == {"kind", "role", "by", "goal", "method", "failed_on", "node_id", "at"}
    second = record_progress(store, "N", role="numerics", by="claude-code", attempt="a counterexample below 100", failed_on="none found")  # any role, no method
    assert second["method"] == "" and second["role"] == "numerics"
    assert [(entry["goal"], entry["role"]) for entry in attempts(store, "N")] == [("the base case", "prover"), ("a counterexample below 100", "numerics")]
    assert [entry["kind"] for entry in work_log(store, "N")] == ["attempt", "attempt"]


def test_dependents_and_siblings_are_read_off_the_map(tmp_path: Path):
    """Siblings are the other dependencies of each node this one is a dependency of: each once, never the node itself."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="claim", statement="a")
    create_node(store, node_id="B", kind="claim", statement="b")
    create_node(store, node_id="C", kind="claim", statement="c")
    create_node(store, node_id="D", kind="claim", statement="d")
    create_node(store, node_id="L1", kind="lemma", statement="l1", dependencies=["A", "B", "C"])
    create_node(store, node_id="L2", kind="lemma", statement="l2", dependencies=["A", "C"])
    create_node(store, node_id="T", kind="theorem", statement="t", dependencies=["L1", "L2", "D"])
    assert [node.id for node in dependents(store, "A")] == ["L1", "L2"]
    assert [node.id for node in dependents(store, "L1")] == ["T"]
    assert dependents(store, "T") == []
    assert [node.id for node in siblings(store, "A")] == ["B", "C"]  # C once, though it sits beside A under both lemmas
    assert [node.id for node in siblings(store, "B")] == ["A", "C"]
    assert [node.id for node in siblings(store, "L1")] == ["D", "L2"]  # the map's order, not the parent's
    assert siblings(store, "T") == [] and [node.id for node in siblings(store, "D")] == ["L1", "L2"]
    with pytest.raises(ProofMapError) as caught:
        siblings(store, "nope")
    assert caught.value.code == "NODE_NOT_FOUND"


# -- the CLI (ADR-0019) ----------------------------------------------------------------------------------------------


def test_the_cli_records_a_verdict_and_an_attempt_and_shows_them_in_the_work_log(tmp_path: Path):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "N", "claim", "a claim", "--json"))
    verifier = {"PROOF_AGENT_ROLE": "verifier", "PROOF_AGENT_NAME": "claude-code"}
    prover = {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NAME": "claude-code"}
    verdict = _data(_run(tmp_path, "node", "progress", "N", "--verdict", "failed", "--note", "1. step 3 cites nothing", "--json", env=verifier))
    assert verdict["kind"] == "verdict" and verdict["outcome"] == "failed" and verdict["note"] == "1. step 3 cites nothing"
    assert verdict["inputs_sha256"] == vault.working_inputs_digest(tmp_path, "N", Medium.latex) and verdict["role"] == "verifier"
    attempt = _data(_run(tmp_path, "node", "progress", "N", "--attempt", "step 3 directly", "--method", "a compactness argument", "--failed-on", "the space is not compact", "--json", env=prover))
    assert attempt == {**attempt, "kind": "attempt", "role": "prover", "by": "claude-code", "goal": "step 3 directly", "method": "a compactness argument", "failed_on": "the space is not compact"}
    passed = _run(tmp_path, "node", "progress", "N", "--verdict", "passed", env=verifier)
    assert passed.exit_code == 0 and passed.output.strip() == "verifier on N: verdict passed"
    log = _data(_run(tmp_path, "node", "progress", "N", "--json"))
    assert [entry["kind"] for entry in log] == ["verdict", "attempt", "verdict"]
    shown = " ".join(_run(tmp_path, "node", "progress", "N").output.split())  # Rich wraps a long line; the words are what count
    assert "verifier: failed — 1. step 3 cites nothing" in shown
    assert "attempt: step 3 directly (a compactness argument) failed on the space is not compact" in shown
    assert "verifier: passed" in shown


@pytest.mark.parametrize("args, env_role, code", [
    (["--verdict", "passed"], "prover", "VERDICT_ROLE_REQUIRED"),
    (["--verdict", "maybe"], "verifier", "INVALID_VERDICT"),
    (["--verdict", "failed"], "verifier", "OBJECTIONS_REQUIRED"),
    (["--attempt", "the base case"], "prover", "ATTEMPT_INCOMPLETE"),
    (["--failed-on", "n = 0"], "prover", "ATTEMPT_INCOMPLETE"),
])
def test_the_cli_refuses_a_malformed_verdict_or_attempt_in_one_envelope(tmp_path: Path, args, env_role, code):
    ensure_project(tmp_path)
    _data(_run(tmp_path, "node", "create", "N", "claim", "a claim", "--json"))
    refused = _run(tmp_path, "node", "progress", "N", *args, "--json", env={"PROOF_AGENT_ROLE": env_role, "PROOF_AGENT_NAME": "claude-code"})
    assert refused.exit_code == 1
    envelope = json.loads(refused.output)  # exactly one envelope
    assert envelope["ok"] is False and envelope["command"] == "node.progress" and envelope["error"]["code"] == code
    assert _data(_run(tmp_path, "node", "progress", "N", "--json")) == []


def test_the_cli_help_lists_the_five_roles():
    shown = runner.invoke(app, ["node", "progress", "--help"]).output
    squeezed = " ".join(shown.replace("│", " ").split())  # Rich boxes and wraps the help; the words are what count
    assert "prover, typesetter, numerics, verifier or decomposer" in squeezed
    assert "--verdict" in squeezed and "--attempt" in squeezed and "--method" in squeezed and "--failed-on" in squeezed


# -- the verdict's digest is a snapshot's, and the gate holds at the request itself (ADR-0019 points 2–4; audit P1 1–2) --


def test_a_verdict_hashes_the_whole_folder_as_a_snapshot_would_outputs_included(tmp_path: Path):
    """A computation's `out/` is what the Verifier checks: a passing verdict on output A must not gate a snapshot holding B."""
    from proof_cli.authority import candidate_proof_sha256
    from proof_cli.vault import working_inputs_digest

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a computation", medium="computation")
    folder = tmp_path / "proofs" / "N"
    (folder / "out").mkdir(exist_ok=True)
    (folder / "out" / "result.txt").write_text("A\n")
    passed = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    (folder / "out" / "result.txt").write_text("B\n")
    assert passed["inputs_sha256"] != record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")["inputs_sha256"]
    assert working_inputs_digest(store.root, "N") == working_inputs_digest(store.root, "N")  # the inputs alone never saw the change
    # the digest is the one the snapshot of these very files is known by
    from _proofs import write_key_ideas
    write_key_ideas(store, "N")
    current = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    record = request_review(store, "N", requested_by="claude-code", rationale="checked", gated_by=current["inputs_sha256"])
    assert candidate_proof_sha256(store, record.id) == current["inputs_sha256"]


def test_a_gated_request_is_refused_once_the_files_changed_and_the_researchers_own_never_is(tmp_path: Path):
    from _proofs import write_key_ideas

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="s")
    write_key_ideas(store, "N")
    verdict = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    (tmp_path / "proofs" / "N" / "proof.tex").write_text("\\documentclass{amsart}\\begin{document}edited after the verdict\\end{document}\n")
    with pytest.raises(ProofMapError) as refused:
        request_review(store, "N", requested_by="claude-code", rationale="r", gated_by=verdict["inputs_sha256"])
    assert refused.value.code == "VERDICT_STALE" and refused.value.details["gated_by"] == verdict["inputs_sha256"]
    assert not (tmp_path / "proofs" / "N" / "snapshots").exists() or not any((tmp_path / "proofs" / "N" / "snapshots").iterdir())
    request_review(store, "N", requested_by="human", rationale="my own edit")  # the researcher names no verdict
    result = _run(tmp_path, "node", "request-review", "N", "--rationale", "r", "--gated-by", verdict["inputs_sha256"], "--json")
    assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "VERDICT_STALE"


def test_the_gate_is_one_digest_given_once_and_the_newest_verdict_must_be_the_passing_one(tmp_path: Path):
    """Re-audit P1: a second `--gated-by ""` is not a way out of the gate, and a failed verdict after the passing one on the
    same files closes it."""
    from _proofs import write_key_ideas

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="s")
    write_key_ideas(store, "N")
    passed = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    for bad in (["--gated-by", passed["inputs_sha256"], "--gated-by", ""], ["--gated-by", ""], ["--gated-by", "abc"],
                ["--gated-by", passed["inputs_sha256"], "--gated-by", "0" * 64],
                ["--gated-by", passed["inputs_sha256"], "--gated-by", passed["inputs_sha256"]]):  # given once: an equal repeat is a repeat
        result = _run(tmp_path, "node", "request-review", "N", "--rationale", "r", *bad, "--json")
        assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "GATE_MALFORMED", bad
    record_progress(store, "N", role="verifier", by="claude-code", verdict="failed", note="1. step 2 is unjustified")  # same files, newer verdict
    with pytest.raises(ProofMapError) as refused:
        request_review(store, "N", requested_by="claude-code", rationale="r", gated_by=passed["inputs_sha256"])
    assert refused.value.code == "VERDICT_STALE" and refused.value.details["newest_verdict"]["outcome"] == "failed"
    assert not (tmp_path / "proofs" / "N" / "snapshots").exists() or not any((tmp_path / "proofs" / "N" / "snapshots").iterdir())
    again = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    result = _run(tmp_path, "node", "request-review", "N", "--rationale", "r", "--gated-by", again["inputs_sha256"], "--json")
    assert result.exit_code == 0, result.output


def test_a_failed_verdict_committed_while_the_request_is_made_is_seen_on_the_write_lock(tmp_path: Path, monkeypatch):
    """Re-audit P1: the newest-verdict check is on the write lock. A `failed` another process commits after the files were
    read but before the request's transaction is what the request sees, and nothing is frozen."""
    from _proofs import write_key_ideas
    from proof_cli import proof_map

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="s")
    write_key_ideas(store, "N")
    passed = record_progress(store, "N", role="verifier", by="claude-code", verdict="passed")
    real = proof_map.read_working_snapshot

    injected = []

    def read_then_someone_fails(root, node_id, medium=None):
        snapshot = real(root, node_id, medium)
        if not injected:  # once: the verdict's own digest read, inside record_progress, comes through here too
            injected.append(True)
            record_progress(store, "N", role="verifier", by="another-verifier", verdict="failed", note="1. the lemma is misapplied")  # between the read and the lock
        return snapshot

    monkeypatch.setattr(proof_map, "read_working_snapshot", read_then_someone_fails)
    with pytest.raises(ProofMapError) as refused:
        request_review(store, "N", requested_by="claude-code", rationale="r", gated_by=passed["inputs_sha256"])
    assert refused.value.code == "VERDICT_STALE" and refused.value.details["newest_verdict"]["outcome"] == "failed"
    assert not (tmp_path / "proofs" / "N" / "snapshots").exists() or not any((tmp_path / "proofs" / "N" / "snapshots").iterdir())
