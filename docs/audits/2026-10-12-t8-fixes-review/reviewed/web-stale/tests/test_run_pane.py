"""The studio's centre is the Proof agent's run (spec #145, decided in #144, #142): the run card with
the researcher's actions, the plan, and the work log. Driven through tests/js/run_pane_harness.js
against the real latex-agent's static folder/run.js, so what is asserted is what the page shows and posts.
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


def test_a_restatement_and_a_definition_edit_say_who_why_and_what_changed():
    """T8 (proof-cli#197): the studio showed only "definition-edited"; it reads as `proof node progress` does."""
    log = [{"at": "2026-10-11T19:47:00+00:00", "kind": "definition-edited", "by": "human", "definition_id": "D",
            "reason": "n = 1 is degenerate", "from": {"text": "$n \\ge 1$"}, "to": {"text": "$n \\ge 2$"}},
           {"at": "2026-10-11T19:48:00+00:00", "kind": "restated", "by": "reader-1", "reason": "too strong",
            "from": {"statement": "c"}, "to": {"statement": "c'", "assumptions": ["a"]}}]
    (shown,) = _pane(run=IDLE, log=log)
    texts = {e["kind"]: e["text"] for e in shown["log"]}
    assert "definition D edited — n = 1 is degenerate (text: $n \\ge 1$ → $n \\ge 2$)" in texts["definition-edited"]
    assert "restated — too strong (statement: c → c'; assumptions: … → a)" in texts["restated"]


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
    turns = [_turn("t1", "prover", 1, changed=[{"path": "scratch/proof-draft.md", "line": 12, "url": "vscode://file//proj/proofs/N/scratch/proof-draft.md:12"}]), _turn("t2", "typesetter", 4)]
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



# -- the run's own work-log writes that failed (proof-web#11, proof-agents#16) -------------------------

FAILED = {"_close_note": "record_close: OSError: disk full", "_suggest": "record_close: OSError: disk full",
          "_note_turn": "record_turn: OSError: <b>no space</b> & more"}


def test_each_failed_own_write_shows_its_site_and_error_and_the_run_is_shown_as_before():
    (before,) = _pane(run={**RUNNING, "suggestion": "read L1 again"}, log=LOG)
    (shown,) = _pane(run={**RUNNING, "suggestion": "read L1 again", "record_failed": FAILED}, log=LOG)
    assert shown["recordFailed"] == ["its closing note (_close_note): record_close: OSError: disk full",
                                     "its suggested redirect (_suggest): record_close: OSError: disk full",
                                     "its turn record (_note_turn): record_turn: OSError: <b>no space</b> & more"]  # text, as written
    assert "Not in the work log — the run could not write:" in shown["text"] and "saved" not in shown["text"]
    assert (shown["status"], shown["where"], shown["buttons"], shown["suggestion"]) == (before["status"], before["where"], before["buttons"], before["suggestion"])


def test_a_needs_human_run_whose_note_failed_still_shows_its_decision_and_controls():
    needs = {**RUNNING, "status": "needs-human", "active": False, "role": "decomposer", "decision": "structure proposed (2 Claim(s): N1, N2); the researcher decides"}
    (before,) = _pane(run=needs, log=LOG)
    (shown,) = _pane(run={**needs, "record_failed": {"_close_note": "record_close: OSError: disk full"}}, log=LOG)
    assert "Needs you: structure proposed (2 Claim(s): N1, N2); the researcher decides" in shown["text"]
    assert shown["recordFailed"] == ["its closing note (_close_note): record_close: OSError: disk full"]
    assert shown["buttons"] == before["buttons"] and shown["status"] == "needs-human"


@pytest.mark.parametrize("field", [{}, {"record_failed": {}}, {"record_failed": None}])
def test_an_older_run_without_the_field_or_with_none_failed_shows_no_warning(field):
    (before,) = _pane(run=RUNNING, log=LOG)
    (shown,) = _pane(run={**RUNNING, **field}, log=LOG)
    assert shown["recordFailed"] == [] and shown["text"] == before["text"]


def test_the_errors_stay_through_polls_and_a_new_start_shows_its_own():
    first = {**RUNNING, "record_failed": {"_note_turn": "record_turn: OSError: disk full"}}
    both = {**first, "turns": 4, "record_failed": {**first["record_failed"], "_close_note": "record_close: OSError: disk full"}}
    started = {**RUNNING, "turns": 1, "record_failed": {}}
    shown = _pane(run=first, log=LOG, sequence=[{"run": {**first, "turns": 4}}, {"run": both}, {"run": started}])
    assert [len(r["recordFailed"]) for r in shown] == [1, 1, 2, 0]
    assert shown[2]["recordFailed"] == ["its turn record (_note_turn): record_turn: OSError: disk full",  # the earlier one is kept
                                        "its closing note (_close_note): record_close: OSError: disk full"]
    assert "Not in the work log" not in shown[3]["text"]

# -- seventh review ---------------------------------------------------------------------------------

CHANGED = [_turn("t5", "numerics", 2, changed=[{"path": "check.py", "line": 40, "url": "vscode://file//proj/proofs/N/check.py:40"}])]


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


def test_start_runs_on_the_provider_the_page_has_chosen(tmp_path=None):
    """#170: the agent panel's provider select (Claude Code or Codex) is the Start's provider; without one, the server's default."""
    _, started = _pane(run=IDLE, log=[], press="Start agent", provider="codex")
    assert started["posted"] == [{"url": "api/agent/start", "body": {"provider": "codex"}}]
    _, plain = _pane(run=IDLE, log=[], press="Start agent")
    assert plain["posted"] == [{"url": "api/agent/start", "body": {}}]


# -- ADR-0019: the Verifier's verdict and a role's attempt in the work log, the newest verdict on the run line --------

LOG_0019 = [
    *LOG,
    {"at": "2026-10-01T09:38:00+00:00", "kind": "attempt", "role": "prover", "by": "claude-code", "goal": "the base case", "method": "direct computation", "failed_on": "the sum diverges for n = 1"},
    {"at": "2026-10-01T09:40:00+00:00", "kind": "verdict", "role": "verifier", "by": "claude-code", "outcome": "failed", "note": "1. step 2 cites L for a bound L does not give",
     "inputs_sha256": "ab12cd34" + "0" * 56},
]


def test_the_work_log_shows_verdicts_and_attempts_and_the_run_line_the_newest_verdict():
    (shown,) = _pane(run={**RUNNING, "verdict": "failed"}, log=LOG_0019)
    kinds = [e["kind"] for e in shown["log"]]
    assert kinds[-2:] == ["attempt", "verdict"]
    texts = {e["kind"]: e["text"] for e in shown["log"]}
    assert "attempt: the base case (direct computation) — failed on the sum diverges for n = 1" in texts["attempt"]
    assert "verdict failed — 1. step 2 cites L for a bound L does not give" in texts["verdict"] and "inputs ab12cd34" in texts["verdict"]
    assert "Verifier" in texts["verdict"]
    assert shown["verdict"] == "verdict failed"
    (plain,) = _pane(run=RUNNING, log=LOG)
    assert plain["verdict"] is None  # a run with no verdict yet shows none


def test_a_suggested_redirect_is_shown_to_the_researcher_and_a_click_puts_it_in_the_redirect_box_unsent():
    """ADR-0019 point 17: what the record repeats is a suggestion; only the researcher sends it, edited or not."""
    suggested = {**RUNNING, "suggestion": "the Verifier's objection came back 3 times — “step 2: the bound is not justified” — the researcher decides: a redirect, a split, or another line"}
    (shown, pressed) = _pane(run=suggested, log=LOG, press="Use as redirect")
    assert shown["suggestion"].startswith("The record suggests: the Verifier's objection came back 3 times")
    assert "Use as redirect" in shown["buttons"]
    assert pressed["redirect"]["text"] == suggested["suggestion"] and pressed["focusedRedirect"] and pressed["posted"] == []  # in hand, not sent
    (ended,) = _pane(run={**suggested, "status": "stuck", "active": False, "reason": "no change in 5 turn(s)"}, log=LOG)
    assert ended["suggestion"] and "Use as redirect" not in ended["buttons"]  # a run that has ended takes no redirect; the suggestion still reads
    (plain,) = _pane(run=RUNNING, log=LOG)
    assert plain["suggestion"] is None


COORDINATOR_IDLE = {"status": "idle", "active": False, "reason": "", "root": "N", "running": [], "accepted": [], "turns": 0, "turns_max": 0, "nodes": {},
                    "subtree": {"nodes": 4, "accepted": 1, "open": 3}, "parallel": 2}
COORDINATOR_RUNNING = {**COORDINATOR_IDLE, "status": "running", "active": True, "running": ["L1", "L2"], "accepted": ["L3"], "turns": 7, "turns_max": 120}


def test_a_node_with_children_shows_its_subtrees_coordinator_and_start_subtree_posts_to_the_maps_api():
    """ADR-0019 point 18: the Coordinator's card sits above the node's own run, only on a node that rests on others."""
    (shown, pressed) = _pane(run=IDLE, log=[], coordinator=COORDINATOR_IDLE, press="Pursue", provider="codex")
    assert shown["coordinator"].startswith("Subtree") and "3 open of 4 node(s) under this one" in shown["coordinator"] and "Pursue" in shown["buttons"]
    assert pressed["posted"] == [{"url": "../../api/node/N/coordinator/start", "body": {"provider": "codex"}}]
    (leaf,) = _pane(run=IDLE, log=[])
    assert leaf["coordinator"] is None and "Pursue" not in leaf["buttons"]


def test_a_working_coordinator_says_where_it_stands_and_pause_and_stop_post_their_actions():
    (shown, paused) = _pane(run=IDLE, log=[], coordinator=COORDINATOR_RUNNING, press="Pause subtree")
    assert "running: L1, L2 · 1 accepted of 4 · turns 7/120" in shown["coordinator"]
    assert [b for b in shown["buttons"] if "subtree" in b] == ["Pause subtree", "Stop subtree"]
    assert paused["posted"] == [{"url": "../../api/node/N/coordinator/pause", "body": {}}]
    (held, resumed) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_RUNNING, "status": "paused", "running": []}, press="Resume subtree")
    assert "no run on now" in held["coordinator"] and resumed["posted"][0]["url"] == "../../api/node/N/coordinator/resume"
    (ended,) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_IDLE, "status": "stuck", "reason": "every open node in the subtree is stuck or waiting for you: L2"})
    assert "stuck — every open node in the subtree is stuck or waiting for you: L2" in ended["coordinator"] and "Pursue" in ended["buttons"]
    # ADR-0021 point 9: the nodes it parked are named on the card, with why; the rest went on without them
    (parked,) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_IDLE, "status": "parked", "reason": "every open node is parked",
                                                     "parked": [{"node": "L2", "reason": "out of budget after 3 start(s)"}]})
    assert "L2 parked — out of budget after 3 start(s)" in parked["coordinator"] and "Pursue" in parked["buttons"]
    # the nodes it left for the researcher (a run that ended needing them) are named beside them; a resplit breaks nothing
    (held,) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_RUNNING, "resplit": ["T"],
                                                   "held": [{"node": "L3", "reason": "the run ended needs-human: two readings"}]})
    assert "L3 waits for you — the run ended needs-human: two readings" in held["coordinator"]


def test_the_work_log_shows_a_coordinators_note():
    (shown,) = _pane(run=IDLE, log=[{"at": "2026-10-05T09:00:00+00:00", "kind": "coordinator", "by": "claude-code/coordinator", "note": "started a run on L1 (start 1)"}])
    (entry,) = shown["log"]
    assert entry["kind"] == "coordinator" and "coordinator: started a run on L1 (start 1)" in entry["text"]


def test_a_coordinator_whose_stop_failed_offers_stop_again_not_a_new_start():
    """Re-audit P5: the recovery from release-failed is Stop again; a Start is refused by the Coordinator anyway."""
    (shown, pressed) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_IDLE, "status": "release-failed", "reason": "the node(s) are still assigned: L1: giving it back failed"}, press="Stop subtree")
    assert "release failed — the node(s) are still assigned: L1" in shown["coordinator"]
    assert "Stop subtree" in shown["buttons"] and "Pursue" not in shown["buttons"]
    assert pressed["posted"] == [{"url": "../../api/node/N/coordinator/release", "body": {}}]


@pytest.mark.parametrize("status", ["stuck", "budget", "done"])
def test_an_ended_coordinator_with_unreleased_runs_offers_stop_before_a_new_start(status):
    shown, pressed = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_IDLE, "status": status, "can_release": True}, press="Stop subtree")
    assert "Stop subtree" in shown["buttons"] and "Pursue" not in shown["buttons"]
    assert pressed["posted"] == [{"url": "../../api/node/N/coordinator/release", "body": {}}]


def test_a_stopped_coordinator_waits_for_its_previous_start_to_settle():
    (shown,) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_IDLE, "status": "released", "settling": True})
    assert "wait for its runs to settle" in shown["coordinator"]
    assert "Pursue" not in shown["buttons"]


# -- the Decomposer's offer (ADR-0019 point 20, phase 4) ---------------------------------------------------------------

THEOREM = {"node": {"id": "N", "kind": "theorem", "dependencies": []}, "acceptance_state": "unreviewed"}


def test_a_theorem_not_yet_split_offers_the_decomposer_and_the_offer_starts_its_one_role():
    shown, pressed = _pane(run=IDLE, log=[], node=THEOREM, press="Propose a split")
    assert shown["buttons"] == ["Start agent", "Propose a split", "Start"] and "have the Decomposer propose a split" in shown["text"]
    assert pressed["posted"] == [{"url": "api/agent/start", "body": {"roles": ["decomposer"]}}]
    (lemma,) = _pane(run=IDLE, log=[], node={**THEOREM, "node": {**THEOREM["node"], "kind": "lemma"}})
    assert "Propose a split" in lemma["buttons"]


@pytest.mark.parametrize("node", [
    {**THEOREM, "node": {**THEOREM["node"], "kind": "claim"}},                       # a Claim is proved, not decomposed
    {**THEOREM, "node": {**THEOREM["node"], "dependencies": ["N1", "N2"]}},         # split already: the Coordinator's
    {**THEOREM, "acceptance_state": "accepted"},                                     # reviewed: nothing to propose
])
def test_a_claim_a_split_node_and_a_reviewed_one_are_not_offered_the_decomposer(node):
    (shown,) = _pane(run=IDLE, log=[], node=node)
    assert "Propose a split" not in shown["buttons"] and "have the Decomposer propose" not in shown["text"]


def test_the_decomposer_is_not_offered_while_a_run_is_on_and_its_stop_reads_as_needing_the_researcher():
    (running,) = _pane(run=RUNNING, log=LOG, node=THEOREM)
    assert "Propose a split" not in running["buttons"]
    stopped = {**IDLE, "status": "needs-human", "role": "decomposer", "name": "claude-code", "decision": "structure proposed (2 Claim(s): N1, N2); the researcher decides"}
    (shown,) = _pane(run=stopped, log=[], node={**THEOREM, "node": {**THEOREM["node"], "dependencies": ["N1", "N2"]}})
    assert "Needs you: structure proposed (2 Claim(s): N1, N2); the researcher decides" in shown["text"] and "Propose a split" not in shown["buttons"]


# -- proof-web#18: the Pursue's total and time limit (proof-agents#19) -------------------------------------------------------

LIMITS = {"turns": 38, "minutes": 190.0, "node_turns": 12, "node_minutes": 60.0, "open_nodes": 3, "structure_allowance": 2}


def test_before_pursue_the_subtree_shows_its_default_total_and_pursue_sends_what_the_researcher_typed():
    (shown, pressed) = _pane(run=IDLE, log=[], coordinator={**COORDINATOR_IDLE, "limits": LIMITS}, press="Pursue", provider="codex",
                             limitsTyped={"turns": 20})
    assert shown["coordinatorLimits"] == ["38", "190"]
    assert "12 turns per node × 3 open node(s) + 2 structure turn(s) for splits" in shown["coordinator"] and "ceiling" in shown["coordinator"]
    assert pressed["posted"] == [{"url": "../../api/node/N/coordinator/start", "body": {"provider": "codex", "limits": {"turns": 20, "minutes": 190}}}]
    (plain, sent) = _pane(run=IDLE, log=[], coordinator=COORDINATOR_IDLE, press="Pursue", provider="codex")
    assert plain["coordinatorLimits"] == [None, None] and sent["posted"][0]["body"] == {"provider": "codex"}   # an older proof-agents: no limits


def test_a_working_subtree_shows_the_pursues_turns_structure_and_failed_launches_apart():
    working = {**COORDINATOR_RUNNING, "turns": 9, "pursue_turns": 11, "turns_max": 38, "structure_turns": 2, "failed_launches": 1}
    (shown,) = _pane(run=IDLE, log=[], coordinator=working)
    assert "turns 11/38 (2 structure) · failed launches 1" in shown["coordinator"]


def test_an_ended_subtree_says_which_nodes_the_total_interrupted_and_which_failed_to_launch():
    ended = {**COORDINATOR_IDLE, "status": "budget", "reason": "the Pursue's total is spent (38 of 38 turns)", "turns": 38, "pursue_turns": 38, "turns_max": 38,
             "interrupted": [{"node": "T", "reason": "the Pursue's total is spent (38 of 38 turns), which prevented its re-split: L1 is parked"}],
             "launch_failed": [{"node": "L2", "reason": "its launch failed 3 time(s) in this Start: no such provider"}]}
    (shown,) = _pane(run=IDLE, log=[], coordinator=ended)
    text = shown["coordinator"]
    assert "T interrupted — the Pursue's total is spent (38 of 38 turns), which prevented its re-split" in text
    assert "L2 launch failed — its launch failed 3 time(s) in this Start" in text and "turns 38/38" in text
