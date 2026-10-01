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

IDLE = {"status": "idle", "active": False, "reason": "", "role": None, "turns": 0, "turns_max": 0, "name": "", "steps": None, "step": None, "redirect": None}
RUNNING = {"status": "running", "active": True, "reason": "", "role": "typesetter", "turns": 3, "turns_max": 40, "name": "claude-code", "steps": 5, "step": 4, "step_status": "started", "redirect": None}
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
    assert "Evidence check passed" in texts["evidence"] and "fog-3" in texts["fog"] and "the constant may be optimal" in texts["fog"]


def test_pause_redirect_and_release_post_their_actions_with_what_was_typed():
    _, paused = _pane(run=RUNNING, log=LOG, press="Pause", after={**RUNNING, "status": "paused"})  # still active
    assert paused["posted"] == [{"url": "api/agent/pause", "body": {}}] and paused["buttons"][0] == "Resume"
    _, redirected = _pane(run=RUNNING, log=LOG, press="Redirect", redirect="try the dual problem", role="prover")
    assert redirected["posted"] == [{"url": "api/agent/redirect", "body": {"text": "try the dual problem", "role": "prover"}}]
    _, released = _pane(run=RUNNING, log=LOG, press="Stop and release", after=IDLE)
    assert released["posted"] == [{"url": "api/agent/release", "body": {}}] and released["buttons"] == ["Start agent", "Start"]


def test_review_what_it_has_freezes_a_snapshot_and_has_the_node_panel_open_the_review_sheet():
    _, frozen = _pane(run=RUNNING, log=LOG, press="Review what it has", answer={"version": 3, "id": "cp-3"})
    assert frozen["posted"] == [{"url": "api/agent/review-now", "body": {}}]
    assert "Snapshot v3 frozen" in frozen["note"] and "handed the node over" in frozen["note"]
    assert frozen["dispatched"] == [{"type": "proof:node-changed", "detail": {"review": True}}]


def test_the_log_links_to_what_each_entry_produced_and_folds_each_turns_conversation():
    turns = [{"job": 7, "role": "prover", "prompt": "Take your turn as the Prover…", "at": 1.0, "done": True, "changed": ["scratch/proof-draft.md"]},
             {"job": 8, "role": "typesetter", "prompt": "Take your turn as the Typesetter…", "at": 2.0, "done": False, "changed": []}]
    (shown,) = _pane(run=RUNNING, log=LOG, turns=turns)
    assert "/#/fog/fog-3" in shown["links"] and "/#/node/N" in shown["links"]  # the fog item in the map's drawer, the Evidence check on the node's page
    assert [t["summary"] for t in shown["turns"]] == ["turn 1 · Prover", "turn 2 · Typesetter · running"]
    assert shown["turns"][0]["files"] == ["vscode://file//proj/proofs/N/scratch/proof-draft.md"]


def test_the_pane_keeps_reading_so_a_start_from_the_map_shows_up():
    (idle,) = _pane(run=IDLE, log=[])
    (active,) = _pane(run=RUNNING, log=LOG)
    assert idle["polls"] == [10000] and active["polls"] == [2000]


def test_a_refused_action_is_said_and_nothing_else_changes():
    _, refused = _pane(run=IDLE, log=[], press="Start agent", refuse=True)
    assert "RUN_ACTIVE" in refused["note"] and refused["buttons"] == ["Start agent", "Start"]


def test_a_stopped_run_says_why():
    stuck = {**RUNNING, "status": "stuck", "active": False, "reason": "no change in 5 turn(s)"}
    (shown,) = _pane(run=stuck, log=LOG)
    assert shown["status"] == "stuck" and "no change in 5 turn(s)" in shown["text"] and shown["buttons"][0] == "Start agent"


def test_a_poll_keeps_the_redirect_being_typed_the_open_conversation_and_the_focus():
    turns = [{"job": 7, "role": "prover", "prompt": "Take your turn as the Prover…", "at": 1.0, "done": True, "changed": []}]
    _, typed, polled = _pane(run=RUNNING, log=LOG, turns=turns, typed="try the dual problem", role="prover", open=[1])
    assert typed["redirect"] == {"text": "try the dual problem", "role": "prover"} and typed["open"] == ["1"] and typed["focusedRedirect"]
    assert polled["redirect"] == {"text": "try the dual problem", "role": "prover"} and polled["open"] == ["1"] and polled["focusedRedirect"]  # nothing new: nothing rebuilt


def test_a_poll_that_brings_news_rebuilds_but_still_keeps_what_was_in_hand():
    turns = [{"job": 7, "role": "prover", "prompt": "Take your turn as the Prover…", "at": 1.0, "done": True, "changed": []}]
    news = {"at": "2026-10-01T09:40:00+00:00", "kind": "step", "role": "typesetter", "by": "claude-code", "step": 4, "status": "done", "note": "typeset"}
    _, _, polled = _pane(run=RUNNING, log=LOG, turns=turns, typed="try the dual problem", role="prover", open=[1], changed=news)
    assert any("step 4 done" in e["text"] for e in polled["log"])  # the new entry is shown
    assert polled["redirect"]["text"] == "try the dual problem" and polled["open"] == ["1"] and polled["focusedRedirect"]


def test_a_running_turns_conversation_is_read_on_until_the_turn_is_done_then_kept():
    """Reaudit R-P3: the conversation opened while the turn runs is not frozen at its first fragment — each poll and each
    opening reads on; once the turn is done, what was last read is final and shown again without asking."""
    turns = [{"job": 7, "role": "prover", "prompt": "Take your turn as the Prover…", "at": 1.0, "done": False, "changed": []}]
    conversation = {"turn": 1, "more": "first fragment\nthen a lemma", "final": "first fragment\nthen a lemma\ncompleted proof"}
    _, opened, polled, finished, reopened = _pane(run=RUNNING, log=LOG, turns=turns, said="first fragment", conversation=conversation)
    assert opened["transcripts"]["1"] == "first fragment" and "running" in opened["turns"][0]["summary"]
    assert polled["transcripts"]["1"] == "first fragment\nthen a lemma"  # a poll with no other news still reads on
    assert finished["transcripts"]["1"] == conversation["final"] and "running" not in finished["turns"][0]["summary"]
    assert reopened["transcripts"]["1"] == conversation["final"]  # final: kept, not asked for again
