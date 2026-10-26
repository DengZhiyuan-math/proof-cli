"""zeqome/proof-agents#50 item 3 (ADR-0025 check 2): what a Pursue spent is its turns' records, read in core.

A Pursue's history kept a copy of its spend on each step, and a `spend` step as each turn ended, so a pursuit the server
stopped read the last copy as a floor. Now each turn's record names the Pursue it is spent under, a launch that failed
says so on the turn's end, and `project_progress` counts them: what an interrupted Pursue spent is known, not a floor.
The steps keep the Pursue's total alone, and say beside it when a turn's record could not be written: then, as when a
Reader's turn was not kept, the spend reads incomplete. History that kept the spend on its steps reads its last copy.
"""

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import pursuit as P
from proof_cli.cli import app
from proof_cli.proof_map import ProofMapError, create_node, record_agent_turn
from proof_cli.storage import ensure_project

TOTAL = {"turns_max": 60, "minutes_max": 90.0}
AGENT = "claude-code"


def _turn(store, node: str, turn: str, phase: str, pid: str, **ended) -> None:
    role = ended.pop("role", "prover")
    record_agent_turn(store, node, phase=phase, turn=turn, role=role, by=AGENT, provider="claude", pursuit_id=pid, **ended)


def test_an_interrupted_pursue_reads_what_its_turns_spent_not_a_floor(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node in ("A", "B"):
        create_node(store, node_id=node, kind="claim", statement=f"{node} holds")
    pid = P.record_pursuit(store, "start", provider="claude", budget=TOTAL).payload["pursuit_id"]
    P.record_reader_turn(store, phase="started", turn="r1", by=AGENT, provider="claude", pursuit_id=pid)
    P.record_reader_turn(store, phase="ended", turn="r1", by=AGENT, provider="claude", pursuit_id=pid, job=1, outcome="ok", events=[])
    P.record_pursuit(store, "reader_end", pursuit_id=pid, budget=TOTAL)
    _turn(store, "A", "a1", "started", pid)
    _turn(store, "A", "a1", "ended", pid, job=2)
    _turn(store, "B", "b1", "started", pid)
    _turn(store, "B", "b1", "ended", pid, job=None, launch_failed=True)   # its backend never started
    _turn(store, "B", "b2", "started", pid)   # under way as the server stopped

    [view] = P.project_progress(store)
    assert view["status"] == P.INTERRUPTED
    budget = dict(view["budget"])
    # the deadline counts from the Start, as the Pursue's own does (PursueBudget.set_total)
    assert budget.pop("deadline") == datetime.fromisoformat(view["started_at"]).timestamp() + 90 * 60
    assert budget == {**TOTAL, "spent": 3, "structure_spent": 1, "failed_launches": 1, "under_way": 1, "spend_incomplete": False}


def test_what_counts_against_a_pursue_and_what_does_not(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node in ("A", "B", "T"):
        create_node(store, node_id=node, kind="claim", statement=f"{node} holds")
    pid = P.record_pursuit(store, "start", provider="claude", budget=TOTAL).payload["pursuit_id"]
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="failed", reason="no CLI", launched=False)   # refused: one failed launch
    _turn(store, "A", "a1", "ended", pid, job=None, launch_failed=True)        # refused before any job existed: one failed launch
    _turn(store, "A", "a2", "started", pid)
    _turn(store, "A", "a2", "ended", pid, job=None, launch_failed=False)       # called off before it began: nothing
    _turn(store, "T", "t1", "started", pid, role="decomposer")
    _turn(store, "T", "t1", "ended", pid, job=3, role="decomposer")            # a structure turn
    record_agent_turn(store, "B", phase="started", turn="b1", role="prover", by=AGENT)   # a run the researcher started: no Pursue's
    record_agent_turn(store, "B", phase="ended", turn="b1", role="prover", by=AGENT, job=4)
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="stuck", reason="A could not launch", budget=TOTAL)
    stopped = P.record_pursuit(store, "start", provider="claude", budget=TOTAL).payload["pursuit_id"]
    P.record_pursuit(store, "reader_end", pursuit_id=stopped, outcome="stopped", reason="stopped by the researcher", launched=False)

    first, second = ({key: value for key, value in view["budget"].items() if key != "deadline"} for view in P.project_progress(store))
    assert first == {**TOTAL, "spent": 1, "structure_spent": 1, "failed_launches": 2, "under_way": 0, "spend_incomplete": False}
    assert second == {**TOTAL, "spent": 0, "structure_spent": 0, "failed_launches": 0, "under_way": 0, "spend_incomplete": False}


def test_plain_progress_says_what_the_pursue_spent(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="claim", statement="A holds")
    pid = P.record_pursuit(store, "start", provider="claude", budget=TOTAL).payload["pursuit_id"]
    _turn(store, "A", "a1", "started", pid)
    _turn(store, "A", "a1", "ended", pid, job=1)
    _turn(store, "A", "a2", "started", pid)

    text = CliRunner().invoke(app, ["project", "progress", "--root", str(tmp_path)]).output
    assert "spent: 2 of 60 turns (0 structure), 0 failed launch(es), 1 under way" in text


def test_a_start_may_take_the_id_its_host_made_for_it_once(tmp_path: Path):
    """A subtree's Coordinator spends its first turns as it starts, before its host records the start: the host makes the
    pursuit's id first, the turns name it, and the start is recorded under it."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="claim", statement="A holds")
    _turn(store, "A", "a1", "started", "made-by-the-host")
    assert P.record_pursuit(store, "start", pursuit_id="made-by-the-host", provider="claude", root="A", budget=TOTAL).payload["pursuit_id"] == "made-by-the-host"
    [view] = P.project_progress(store)
    assert (view["pursuit_id"], view["budget"]["spent"], view["budget"]["under_way"]) == ("made-by-the-host", 1, 1)
    with pytest.raises(ProofMapError) as again:
        P.record_pursuit(store, "start", pursuit_id="made-by-the-host", provider="claude")
    assert again.value.code == "PURSUIT_ID_TAKEN"


def test_a_reader_whose_turn_was_not_kept_leaves_the_spend_incomplete(tmp_path: Path):
    """The host could not write the Reader's turn records (READER_TURN_RECORD_FAILED), so its step says how it ended: the
    turn may have begun, and no record counts it. What the Pursue spent is at least what its records say, not all of it."""
    store = ensure_project(tmp_path)
    pid = P.record_pursuit(store, "start", provider="claude", budget=TOTAL).payload["pursuit_id"]
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="ok")
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="done")

    [view] = P.project_progress(store)
    assert view["reader_turns"] is None
    assert (view["budget"]["spent"], view["budget"]["spend_incomplete"]) == (0, True)


def test_a_turn_record_its_host_could_not_write_leaves_the_spend_incomplete(tmp_path: Path):
    """A turn's start could not be written, so no record counts it: the host says so with the total on a later step."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="claim", statement="A holds")
    pid = P.record_pursuit(store, "start", provider="claude", root="A", budget=TOTAL).payload["pursuit_id"]
    _turn(store, "A", "a1", "started", pid)
    _turn(store, "A", "a1", "ended", pid, job=1)
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="stuck", reason="no change", budget={**TOTAL, "spend_incomplete": True})

    [view] = P.project_progress(store)
    assert (view["budget"]["spent"], view["budget"]["spend_incomplete"]) == (1, True)
