"""The studio's centre is the Proof agent's run (spec #145, decided in #144, #142): the run card with
the researcher's actions, the plan, and the work log. Driven through tests/js/run_pane_harness.js
against the real src/proof_cli/studio/static/run.js, so what is asserted is what the page shows and posts.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "js" / "run_pane_harness.js"

IDLE = {"status": "idle", "reason": "", "role": None, "turns": 0, "turns_max": 0, "name": "", "steps": None, "step": None, "redirect": None}
RUNNING = {"status": "running", "reason": "", "role": "typesetter", "turns": 3, "turns_max": 40, "name": "claude-code", "steps": 5, "step": 4, "step_status": "started", "redirect": None}
LOG = [
    {"at": "2026-10-01T09:30:00+00:00", "kind": "claimed", "by": "claude-code"},
    {"at": "2026-10-01T09:30:05+00:00", "kind": "plan", "role": "prover", "by": "claude-code", "plan": ["read what the project holds", "draft the proof", "have it typeset", "check n ≤ 10^4", "request review"]},
    {"at": "2026-10-01T09:31:00+00:00", "kind": "step", "role": "prover", "by": "claude-code", "step": 1, "status": "done", "note": "nothing in the project settles it"},
    {"at": "2026-10-01T09:34:00+00:00", "kind": "split", "by": "claude-code", "nodes": ["N1", "N2"]},
    {"at": "2026-10-01T09:35:00+00:00", "kind": "handoff", "role": "prover", "by": "claude-code", "to": "typesetter", "note": "write §2 as LaTeX"},
    {"at": "2026-10-01T09:36:00+00:00", "kind": "step", "role": "typesetter", "by": "claude-code", "step": 4, "status": "started"},
    {"at": "2026-10-01T09:36:30+00:00", "kind": "evidence", "by": "claude-code", "outcome": "passed"},
    {"at": "2026-10-01T09:37:00+00:00", "kind": "fog", "by": "claude-code", "fog_id": "fog-3", "text": "the constant may be optimal"},
]


def _pane(**scenario):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_without_a_run_the_centre_offers_start_and_nothing_else_drives_the_agent():
    (shown,) = _pane(run=IDLE, log=[])
    assert "No agent is working on this node" in shown["text"] and shown["buttons"] == ["Start agent", "Start"]
    assert "the work log fills" in shown["text"]


def test_start_posts_the_whole_run_or_one_role():
    _, started = _pane(run=IDLE, log=[], press="Start agent")
    assert started["posted"] == [{"url": "api/agent/start", "body": {}}] and "Started as claude-code" in started["note"]
    _, one = _pane(run=IDLE, log=[], press="Start", role="typesetter")
    assert one["posted"] == [{"url": "api/agent/start", "body": {"roles": ["typesetter"]}}]


def test_a_running_agent_shows_its_role_step_plan_and_the_four_actions():
    (shown,) = _pane(run=RUNNING, log=LOG)
    assert shown["status"] == "running" and shown["where"] == "Typesetter · step 4/5"
    assert [p["text"] for p in shown["plan"]][:2] == ["read what the project holds", "draft the proof"]
    assert {str(p["step"]): p["status"] for p in shown["plan"]} == {"1": "done", "2": "", "3": "", "4": "started", "5": ""}
    assert shown["buttons"] == ["Pause", "Redirect", "Review what it has", "Stop and release"]


def test_the_work_log_reads_in_time_order_with_roles_and_links():
    (shown,) = _pane(run=RUNNING, log=LOG)
    kinds = [e["kind"] for e in shown["log"]]
    assert kinds == ["claimed", "plan", "step", "split", "handoff", "step", "evidence", "fog"]
    texts = {e["kind"]: e["text"] for e in shown["log"]}
    assert "Prover" in texts["plan"] and "1. read what the project holds" in texts["plan"]
    assert "step 1 done — nothing in the project settles it" in texts["step"] or any("step 1 done" in e["text"] for e in shown["log"])
    assert "handed off to the Typesetter: write §2 as LaTeX" in texts["handoff"]
    assert "/studio/N1/" in shown["links"] and "/studio/N2/" in shown["links"]
    assert "Evidence check passed" in texts["evidence"] and "fog fog-3: the constant may be optimal" in texts["fog"]


def test_pause_redirect_and_release_post_their_actions_with_what_was_typed():
    _, paused = _pane(run=RUNNING, log=LOG, press="Pause", after={**RUNNING, "status": "paused"})
    assert paused["posted"] == [{"url": "api/agent/pause", "body": {}}] and paused["buttons"][0] == "Resume"
    _, redirected = _pane(run=RUNNING, log=LOG, press="Redirect", redirect="try the dual problem", role="prover")
    assert redirected["posted"] == [{"url": "api/agent/redirect", "body": {"text": "try the dual problem", "role": "prover"}}]
    _, released = _pane(run=RUNNING, log=LOG, press="Stop and release", after=IDLE)
    assert released["posted"] == [{"url": "api/agent/release", "body": {}}] and released["buttons"] == ["Start agent", "Start"]


def test_review_what_it_has_freezes_a_snapshot_and_tells_the_node_panel():
    _, frozen = _pane(run=RUNNING, log=LOG, press="Review what it has", answer={"version": 3, "id": "cp-3"})
    assert frozen["posted"] == [{"url": "api/agent/review-now", "body": {}}]
    assert "Snapshot v3 frozen" in frozen["note"] and frozen["dispatched"] == ["proof:node-changed"]


def test_a_refused_action_is_said_and_nothing_else_changes():
    _, refused = _pane(run=IDLE, log=[], press="Start agent", refuse=True)
    assert "RUN_ACTIVE" in refused["note"] and refused["buttons"] == ["Start agent", "Start"]


def test_a_stopped_run_says_why():
    stuck = {**RUNNING, "status": "stuck", "reason": "no change in 5 turn(s)"}
    (shown,) = _pane(run=stuck, log=LOG)
    assert shown["status"] == "stuck" and "no change in 5 turn(s)" in shown["text"] and shown["buttons"][0] == "Start agent"
