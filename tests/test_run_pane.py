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
    assert {str(p["step"]): p["status"] for p in shown["plan"]} == {"1": "done", "2": "", "3": "", "4": "started", "5": "next"}
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


def _turn(turn, role, step, **more):
    """A turn's entry in the work log, as the project records it (PR #148): its job, session, step and transcript."""
    return {"at": "2026-10-01T09:38:00+00:00", "kind": "turn", "turn": turn, "role": role, "by": "claude-code", "provider": "claude",
            "job": 7, "session_id": "s", "step": step, "transcript": f".proof/agent-turns/N/{turn}.json", "changed": [], **more}


def test_the_log_links_to_what_each_entry_produced_and_folds_each_turns_conversation_under_its_step():
    turns = [_turn("t1", "prover", 1, changed=[{"path": "scratch/proof-draft.md", "line": 12}]), _turn("t2", "typesetter", 4)]
    (shown,) = _pane(run=RUNNING, log=LOG, turns=turns)
    assert "/#/fog/fog-3" in shown["links"] and "/#/node/N" in shown["links"]  # the fog item in the map's drawer, the Evidence check on the node's page
    assert [t["summary"] for t in shown["turns"]] == ["step 1 · Prover's turn — its conversation", "step 4 · Typesetter's turn — its conversation"]
    assert shown["turns"][0]["files"] == ["vscode://file//proj/proofs/N/scratch/proof-draft.md:12"]
    assert [e["kind"] for e in shown["log"]][-2:] == ["turn", "turn"]  # in the log, after the step they belong to


def test_an_earlier_starts_turn_reads_its_conversation_from_what_the_project_kept():
    """Story 40: a finished turn's conversation is read from api/agent/turn — the project's record, which outlives the
    studio's memory (a new Start, a restart) — and, being final, is not asked for again."""
    turns = [_turn("t1", "prover", 1)]
    _, typed, _ = _pane(run=RUNNING, log=LOG, turns=turns, said="I read L1 first.", typed="", open=["t1"])
    assert typed["transcripts"]["t1"] == "I read L1 first." and typed["turns"][0]["prompt"] == "Take your turn (t1)…"
    assert typed["askedTurns"] == ["t1"]


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
    turns = [_turn("t1", "prover", 1)]
    _, typed, polled = _pane(run=RUNNING, log=LOG, turns=turns, typed="try the dual problem", role="prover", open=["t1"])
    assert typed["redirect"] == {"text": "try the dual problem", "role": "prover"} and typed["open"] == ["t1"] and typed["focusedRedirect"]
    assert polled["redirect"] == {"text": "try the dual problem", "role": "prover"} and polled["open"] == ["t1"] and polled["focusedRedirect"]  # nothing new: nothing rebuilt


def test_a_poll_that_brings_news_rebuilds_but_still_keeps_what_was_in_hand():
    turns = [_turn("t1", "prover", 1)]
    news = {"at": "2026-10-01T09:40:00+00:00", "kind": "step", "role": "typesetter", "by": "claude-code", "step": 4, "status": "done", "note": "typeset"}
    _, _, polled = _pane(run=RUNNING, log=LOG, turns=turns, typed="try the dual problem", role="prover", open=["t1"], changed=news)
    assert any("step 4 done" in e["text"] for e in polled["log"])  # the new entry is shown
    assert polled["redirect"]["text"] == "try the dual problem" and polled["open"] == ["t1"] and polled["focusedRedirect"]


def test_a_running_turns_conversation_is_read_on_until_the_turn_is_done_then_kept():
    """Reaudit R-P3: the conversation opened while the turn runs is not frozen at its first fragment — each poll and each
    opening reads on from its job; once the turn is recorded, its kept conversation is final and shown again without asking."""
    running = {**RUNNING, "job": 7, "turn": "t9"}
    conversation = {"turn": "t9", "more": "first fragment\nthen a lemma", "final": "first fragment\nthen a lemma\ncompleted proof",
                    "recorded": _turn("t9", "typesetter", 4)}
    _, opened, polled, finished, reopened = _pane(run=running, log=LOG, said="first fragment", conversation=conversation)
    assert opened["transcripts"]["t9"] == "first fragment" and "running" in opened["turns"][0]["summary"]
    assert "step 4 · Typesetter" in opened["turns"][0]["summary"]  # under the step it is on
    assert polled["transcripts"]["t9"] == "first fragment\nthen a lemma"  # a poll with no other news still reads on
    assert finished["transcripts"]["t9"] == conversation["final"] and "running" not in finished["turns"][0]["summary"]
    assert finished["open"] == ["t9"]  # the same fold, still open, now the recorded turn
    assert reopened["transcripts"]["t9"] == conversation["final"] and reopened["askedTurns"] == ["t9"]  # final: not asked for again


def test_a_run_that_needs_the_researcher_says_what_it_needs_and_a_failed_release_can_be_retried():
    needs = {**RUNNING, "status": "needs-human", "active": False, "decision": "is the constant allowed to depend on n?"}
    (shown,) = _pane(run=needs, log=LOG)
    assert shown["status"] == "needs-human" and "Needs you: is the constant allowed to depend on n?" in shown["text"]
    assert shown["buttons"][0] == "Start agent"
    failed = {**RUNNING, "status": "release-failed", "active": False, "reason": "the node is still assigned to claude-code"}
    (shown,) = _pane(run=failed, log=LOG)
    assert "still assigned" in shown["text"] and "Stop and release" in shown["buttons"]


# -- seventh review ---------------------------------------------------------------------------------

CHANGED = [_turn("t5", "numerics", 2, changed=[{"path": "check.py", "line": 40}])]


def test_a_changed_file_opens_in_vs_code_at_its_line():
    """Story 18: "the agent changed check.py line 40" is one click away."""
    (shown,) = _pane(run=RUNNING, log=LOG, turns=CHANGED)
    assert shown["turns"][0]["files"] == ["vscode://file//proj/proofs/N/check.py:40"]
    assert "line 40" in shown["turns"][0]["titles"][0] and "VS Code" in shown["turns"][0]["titles"][0]


def test_with_an_open_command_a_changed_file_is_opened_by_the_server_instead():
    """Story 19: with `[studio] open_command` set, the link asks the studio's server to run it — no vscode:// URL."""
    command = {"kind": "command", "command": "subl {file}"}
    shown, clicked = _pane(run=RUNNING, log=LOG, turns=CHANGED, open=command, clickFile="check.py", answer={"ok": True, "kind": "command", "exit": 0})
    assert not any(href.startswith("vscode:") for href in shown["turns"][0]["files"])
    assert "subl {file}" in shown["turns"][0]["titles"][0]
    assert clicked["posted"] == [{"url": "api/open", "body": {"file": "check.py", "line": 40}}] and clicked["prevented"]


def test_an_idle_studio_opens_on_start_whatever_files_tab_was_remembered():
    """Story 42: no agent at work, the centre shows "Start agent on this node" — the remembered Files tab waits for a run."""
    (idle,) = _pane(run=IDLE, log=[])
    assert idle["centred"] == [["run", False]]  # shown, and not remembered as the researcher's choice
    stopped = {**RUNNING, "status": "stuck", "active": False}
    assert _pane(run=stopped, log=LOG)[0]["centred"] == [["run", False]]
    assert _pane(run=RUNNING, log=LOG)[0]["centred"] == []  # an agent at work: the remembered view stands
    assert _pane(run=IDLE, log=[], hash="#files")[0]["centred"] == []  # a link to #files asks for Files


def test_the_plan_says_in_words_which_steps_are_done_the_current_step_and_its_role_and_the_next():
    """Story 36: the plan's state is in the page's text, not only in its classes."""
    (shown,) = _pane(run=RUNNING, log=LOG)
    marks = {str(p["step"]): p["mark"] for p in shown["plan"]}
    assert marks == {"1": "done", "2": "", "3": "", "4": "current step · Typesetter", "5": "next"}
    between = [*LOG[:-3], {**LOG[5], "status": "done"}]  # step 4 done, nothing started yet
    marks = {str(p["step"]): p["mark"] for p in _pane(run=RUNNING, log=between)[0]["plan"]}
    assert marks == {"1": "done", "2": "", "3": "", "4": "done", "5": "next"}


def test_a_turns_transcript_reads_its_steps_and_the_running_turn_is_handed_to_the_files_view():
    """From upstream 2938c05, watched the proof-cli way: the transcript shows each step the agent took, and the
    running turn's events are read as they come and handed to the Files view (app.js studioLive)."""
    running = {**RUNNING, "job": 7, "turn": "t9", "started_at": 100.0}
    events = [{"t": "tool_start", "id": "r1", "name": "Read"}, {"t": "tool", "id": "r1", "name": "Read", "summary": "sec/a.tex", "path": "sec/a.tex", "lines": [20, 30]},
              {"t": "tool_result", "id": "r1", "error": False}, {"t": "thinking_start"}, {"t": "text", "text": "I rewrote §2."},
              {"t": "build", "result": {"exit": 0, "diagnostics": []}}, {"t": "done"}]
    _, opened, polled = _pane(run=running, log=LOG, events=events, typed="x", open=["t9"])
    assert opened["transcripts"]["t9"] == "▸ Read sec/a.tex\n… thinking\nI rewrote §2.\n▸ Compile: OK"
    assert opened["live"] == [e["t"] for e in events] and opened["resets"] == 1  # every event once, after a reset for the new Start
    assert polled["live"] == opened["live"] and polled["resets"] == 1  # the next poll does not follow the same turn again


def test_the_files_views_marks_are_reset_by_a_new_start_not_by_each_turn():
    """Seventh review: the Files view keeps what the Prover changed when the Typesetter's turn comes (a role's
    hand-off is the same Start); only a new Start clears last run's marks."""
    prover = {**RUNNING, "role": "prover", "job": 7, "turn": "t1", "started_at": 100.0}
    typesetter = {**prover, "role": "typesetter", "job": 8, "turn": "t2"}
    again = {**prover, "job": 9, "turn": "t3", "started_at": 200.0}
    events = [{"t": "tool", "id": "w1", "name": "Edit", "summary": "proof.tex", "path": "proof.tex"}, {"t": "tool_result", "id": "w1", "error": False}, {"t": "done"}]
    first, handed_off, restarted = _pane(run=prover, log=LOG, events=events, sequence=[
        {"run": typesetter, "log": [*LOG, _turn("t1", "prover", 1, job=7)]},
        {"run": again},
    ])
    assert first["resets"] == 1 and first["live"] == ["tool", "tool_result", "done"]
    assert handed_off["resets"] == 1 and len(handed_off["live"]) == 6  # the Typesetter's turn followed, the marks kept
    assert restarted["resets"] == 2 and len(restarted["live"]) == 9  # a new Start: last run's marks go
