"""ADR-0021 on the map page's own script: the review queue, Conditional and Parked on the map, and Pursue from the draft."""

import json
import shutil
import subprocess

import pytest

from test_map_home import HARNESS, _as_served, _node, _state


def _page(*, map_nodes, queue=None, pursue=None, steps=(), pursue_replies=None):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    scenario = {"state": _state(), "map": {"nodes": map_nodes}, "steps": list(steps), "nodes": {}}
    scenario = _as_served(scenario)
    if queue is not None:
        scenario["queue"] = queue
    if pursue is not None:
        scenario["pursue"] = pursue
    if pursue_replies is not None:
        scenario["pursueReplies"] = pursue_replies
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


MAP = [
    _node("C", "claim", "C holds", provisional=True, conditional_on=[], parked=None, workflow_state="review-needed"),
    _node("L", "lemma", "L holds", ["C"], provisional=False, conditional_on=["C"], parked="out of budget after 3 start(s)", workflow_state="blocked"),
    _node("T", "theorem", "T holds", ["L"], provisional=False, conditional_on=["C"], parked=None, workflow_state="blocked"),
]
QUEUE = {"departures": "- the height's sup 1/Im is infinite; took the inf\n", "items": [
    {"kind": "provisional", "node_id": "C", "node_kind": "claim", "statement": "C holds", "depth": 0, "conditional_on": [], "snapshot": 1, "workflow_state": "review-needed"},
    {"kind": "question", "node_id": "C", "node_kind": "claim", "statement": "C holds", "depth": 0, "question_id": "q_1", "question": "took n ≥ 2; the alternative: n ≥ 1", "by": "prover-1", "role": "prover"},
    {"kind": "parked", "node_id": "L", "node_kind": "lemma", "statement": "L holds", "depth": 1, "reason": "out of budget after 3 start(s)",
     "attempts": [{"goal": "the height bound", "method": "Siegel sets", "failed_on": "the cusp at p"}]},
    {"kind": "unfixed", "definition_id": "D", "term": "height", "text": "h(x) = inf 1/Im", "by": "reader-1", "named_by": ["L"], "depth": 1},
]}


def test_the_map_marks_conditional_and_parked_nodes():
    (shown,) = _page(map_nodes=MAP)
    assert "conditional" in shown["dag"]["T"]["classes"] and "parked" not in shown["dag"]["T"]["classes"]
    assert {"conditional", "parked"} <= set(shown["dag"]["L"]["classes"])
    assert "Conditional on C: it stands only if they do." in shown["dag"]["T"]["title"]
    assert "Parked: out of budget after 3 start(s)" in shown["dag"]["L"]["title"]
    assert shown["dag"]["L"]["status"]["text"] == "Parked"
    assert any("provisional" in text for text in shown["dag"]["C"]["texts"])


def test_the_review_queue_lists_what_waits_bottom_up_and_answers_a_question_in_place():
    shown, kept, redirected = _page(map_nodes=MAP, queue=QUEUE, steps=[{"queueAnswer": {"node": "C", "keep": True}},
                                                                        {"queueAnswer": {"node": "C", "answer": "take n ≥ 1"}}])
    assert [item["kind"] for item in shown["queue"]] == ["provisional", "question", "parked", "unfixed"]
    assert shown["queueCount"] == "4"
    assert "the height bound — Siegel sets: failed on the cusp at p" in shown["queue"][2]["text"]
    assert "D · height" in shown["queue"][3]["text"] and "named by L" in shown["queue"][3]["text"]
    assert shown["departures"].startswith("- the height's sup 1/Im")
    assert kept["posted"][-1] == {"url": "/api/node/C/answer", "body": {"question": "q_1", "keep": True}}
    assert redirected["posted"][-1] == {"url": "/api/node/C/answer", "body": {"question": "q_1", "answer": "take n ≥ 1"}}


def test_an_empty_queue_says_nothing_waits():
    (shown,) = _page(map_nodes=MAP, queue={"items": [], "departures": None})
    assert [item["text"] for item in shown["queue"]] == ["Nothing is waiting on you."] and shown["departures"] is None


def test_a_project_with_a_draft_and_no_map_offers_pursue_and_the_homes_link_hands_it_over():
    idle = {"status": "idle", "reason": "", "theorems": [], "current": None, "results": {}, "can_pursue": True}
    shown, landed, pressed = _page(map_nodes=[], pursue=idle, steps=[{"hash": "#/pursue"}, {"pursue": "start"}])
    assert shown["pursue"]["shown"] and shown["pursue"]["start"] and not shown["pursue"]["stop"]
    assert landed["pursue"]["focused"] and landed["posted"] == []  # the Home's link never starts the agents itself
    assert pressed["posted"][-1] == {"url": "/api/pursue/start", "body": {}}
    assert pressed["pursue"]["stop"] and pressed["pursue"]["status"] == "The Reader is stating the draft…"
    (mapped,) = _page(map_nodes=MAP)
    assert not mapped["pursue"]["shown"]  # a map already: Pursue is on a Theorem's page


def test_a_stopped_pursuit_whose_reader_has_not_ended_offers_neither_pursue_nor_stop():
    stopping = {"status": "released", "reason": "stopped by the researcher", "theorems": [], "current": None, "results": {},
                "can_pursue": False, "stopping": True}
    (shown,) = _page(map_nodes=[], pursue=stopping)
    assert shown["pursue"]["shown"] and not shown["pursue"]["start"] and not shown["pursue"]["stop"]
    assert shown["pursue"]["status"] == "Stopping: the Reader's turn is ending…"


# -- a release that failed holds its runs until Stop gives them back (proof-web#12, proof-agents#17) -----------------

HELD_REASON = "the runs of T1 are still assigned: L1 is still claimed by claude-code; Stop again to give them back"
HELD = {"status": "release-failed", "reason": HELD_REASON, "theorems": ["T1", "T2"], "current": "T1", "results": {}, "stopping": False}
FAILED = {"code": "RELEASE_FAILED", "message": "L1 is still claimed by claude-code"}


@pytest.mark.parametrize("can_pursue", [True, False])
def test_a_release_failed_pursuit_offers_stop_and_not_pursue_and_says_which_theorem_holds_its_runs(can_pursue):
    (shown,) = _page(map_nodes=[], pursue={**HELD, "can_pursue": can_pursue})
    assert shown["pursue"]["shown"] and shown["pursue"]["stop"] and not shown["pursue"]["start"]
    assert shown["pursue"]["status"] == f"Release failed on T1 — {HELD_REASON}"


def test_stop_retries_the_release_until_it_succeeds_and_then_the_ended_pursuit_reads_as_before():
    released = {**HELD, "status": "released", "reason": "stopped by the researcher", "can_pursue": True}
    shown, again, done = _page(map_nodes=[], pursue={**HELD, "can_pursue": False}, steps=[{"pursue": "stop"}, {"pursue": "stop"}],
                               pursue_replies=[{"error": FAILED, "view": {**HELD, "can_pursue": False}}, {"view": released}])
    assert again["posted"][-1] == {"url": "/api/pursue/stop", "body": {}}
    assert again["message"] == "RELEASE_FAILED: L1 is still claimed by claude-code"   # the failure, said
    assert again["pursue"]["stop"] and not again["pursue"]["start"] and again["pursue"]["status"].startswith("Release failed on T1")
    assert [p["url"] for p in done["posted"]] == ["/api/pursue/stop", "/api/pursue/stop"]
    assert not done["pursue"]["stop"] and done["pursue"]["start"] and done["pursue"]["status"] == "released — stopped by the researcher"


def test_while_the_runs_are_being_given_back_neither_pursue_nor_stop_is_offered():
    giving = {**HELD, "status": "stopping", "reason": "stopped by the researcher; giving the runs back", "can_pursue": False, "stopping": True}
    (shown,) = _page(map_nodes=[], pursue=giving)
    assert shown["pursue"]["shown"] and not shown["pursue"]["stop"] and not shown["pursue"]["start"]
    assert shown["pursue"]["status"] == "Stopping: giving the runs of T1 back…"


@pytest.mark.parametrize("status, stop, start", [("reading", True, False), ("pursuing", True, False), ("done", False, True),
                                                 ("stuck", False, True), ("released", False, True), ("idle", False, True)])
def test_the_other_statuses_keep_their_controls(status, stop, start):
    view = {"status": status, "reason": "", "theorems": ["T1"], "current": "T1" if status == "pursuing" else None, "results": {},
            "can_pursue": status not in ("reading", "pursuing"), "stopping": False}
    (shown,) = _page(map_nodes=[], pursue=view)
    assert (shown["pursue"]["stop"], shown["pursue"]["start"]) == (stop, start)
