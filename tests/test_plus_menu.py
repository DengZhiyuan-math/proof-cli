"""The agent panel's "+" menu (spec #145, story 48): the researcher's oversight of the run first, then the one-off
tasks under "Ask the agent to…", reworded by role, then the researcher's own decision. Driven through
tests/js/plus_menu_harness.js against the real src/proof_cli/studio/static/menu.js.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "js" / "plus_menu_harness.js"

IDLE = {"status": "idle", "active": False}
RUNNING = {"status": "running", "active": True}
PAUSED = {"status": "paused", "active": True}
TASKS = ["Prover · propose a split", "Prover · edit dependencies", "Prover · open a Challenge",
         "Typesetter · draft key ideas", "Typesetter · compile and fix", "Numerics · run a check"]


def _menu(**scenario):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    scenario.setdefault("run", IDLE)
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _heads(shown):
    return [row["head"] for row in shown["rows"] if "head" in row]


def _items(shown):
    return [row["item"] for row in shown["rows"] if "item" in row]


def test_without_a_run_the_menu_offers_start_then_ask_the_agent_to_by_role():
    shown = _menu(run=IDLE)
    assert shown["open"] and _heads(shown) == ["The agent", "Ask the agent to…"]
    assert _items(shown) == ["Start agent", *TASKS]
    assert not any(row.get("disabled") for row in shown["rows"])
    assert "Prove it" not in _items(shown)  # proving is what Start does


def test_start_and_a_one_off_task_start_the_run_or_one_roles_turn():
    pressed = _menu(run=IDLE, press="Start agent")
    assert pressed["calls"] == [["start", None, None]] and pressed["closed"]
    task = _menu(run=IDLE, press="Typesetter · draft key ideas")
    assert task["calls"] == [["start", ["typesetter"], "Write key-ideas.md from the draft and proof.tex: 核心思路, 主要步骤, 难点, 未覆盖."]]


def test_while_the_run_is_under_way_the_menu_is_its_oversight_and_the_tasks_wait():
    shown = _menu(run=RUNNING)
    assert _items(shown)[:4] == ["Pause", "Redirect…", "Review what it has", "Stop and release"]
    tasks = [row for row in shown["rows"] if row.get("item") in TASKS]
    assert len(tasks) == len(TASKS) and all(row["disabled"] for row in tasks)
    assert all("Finish or stop the run first" in row["title"] for row in tasks)
    assert _items(_menu(run=PAUSED))[0] == "Resume"


def test_the_menu_reads_whether_the_run_is_under_way_from_the_runs_view():
    """Not from a list of statuses of its own: a status the menu has never heard of is whatever the view says."""
    assert _items(_menu(run={"status": "settling", "active": True}))[0] == "Pause"
    assert _items(_menu(run={"status": "running", "active": False}))[0] == "Start agent"


@pytest.mark.parametrize("label, call", [
    ("Pause", [["pause"]]), ("Review what it has", [["reviewNow"]]), ("Stop and release", [["release"]]),
    ("Redirect…", [["showCentre", "run"], ["focusRedirect"]]),
])
def test_each_oversight_item_does_what_it_says(label, call):
    assert _menu(run=RUNNING, press=label)["calls"] == call


def test_a_snapshot_awaiting_review_adds_a_read_only_check_and_the_researchers_decision():
    shown = _menu(run=IDLE, review={"version": 2})
    assert _heads(shown) == ["The agent", "Ask the agent to…", "Your decision"]
    assert _items(shown)[-2:] == ["Check snapshot v2", "Review snapshot v2…"]
    assert _menu(run=IDLE, review={"version": 2}, press="Check snapshot v2")["calls"] == [["askAgent", "Check it."]]
    assert _menu(run=IDLE, review={"version": 2}, press="Review snapshot v2…")["calls"] == [["openReview"]]


def test_a_page_with_no_run_says_so():
    shown = _menu(run=None)
    assert _heads(shown) == ["The agent", "no run on this page"] and _items(shown) == []
