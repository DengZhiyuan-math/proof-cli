"""#284 (ADR-0025 check 2), a pursuit's history: what it spent and how its Reader ended, each read in one place.

An interrupted Pursue's spend is the last whole-Pursue budget it recorded, read as a floor, here and nowhere else: the
page reads core's reading. Whether its Reader began, and how the Reader's turn ended, are the Reader's turn records; the
`reader_end` step says only what no turn record holds: a launch refused before any job existed.
"""

from pathlib import Path

from proof_cli import pursuit as P
from proof_cli.storage import ensure_project

WHOLE = {"turns_max": 60, "minutes_max": 90.0, "spent": 0, "structure_spent": 0, "failed_launches": 0}


def _start(store) -> str:
    return P.record_pursuit(store, "start", provider="claude", budget=WHOLE).payload["pursuit_id"]


def test_an_interrupted_pursuit_reads_its_last_whole_budget_as_a_floor_past_an_older_hosts_theorem_count(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _start(store)
    P.record_pursuit(store, "spend", pursuit_id=pid, budget={**WHOLE, "spent": 7, "structure_spent": 1})
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", budget={"turns": 4, "turns_max": 20})   # an older host's

    [view] = P.project_progress(store)
    assert view["status"] == P.INTERRUPTED
    assert view["budget"] == {**WHOLE, "spent": 7, "structure_spent": 1, "spend_incomplete": True}


def test_a_pursuit_that_kept_only_an_older_hosts_theorem_counts_reads_its_budget_unknown(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = P.record_pursuit(store, "start", provider="claude").payload["pursuit_id"]
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="budget", reason="turn budget spent", budget={"turns": 20, "turns_max": 20})

    [view] = P.project_progress(store)
    assert view["budget"] is None and view["events"][-1]["budget"] == {"turns": 20, "turns_max": 20}   # kept as recorded


def _reader_turn(store, pid: str, *, outcome: str, reason: str = "") -> None:
    P.record_reader_turn(store, phase="started", turn="r1", by="claude-code", provider="claude", pursuit_id=pid, prompt="Read")
    P.record_reader_turn(store, phase="ended", turn="r1", by="claude-code", provider="claude", pursuit_id=pid,
                         job=1, outcome=outcome, reason=reason, exit=0, is_error=False, events=[])


def test_how_the_reader_ended_is_read_off_its_turn_record(tmp_path: Path):
    """The Reader's turn, stopped by the researcher, ended `stopped`; its pursuit's `reader_end` step had read `failed`
    beside it, a second reading of the same end. The step now records no outcome of its own, and its view reads the turn's."""
    store = ensure_project(tmp_path)
    pid = _start(store)
    _reader_turn(store, pid, outcome="stopped", reason="stopped by the researcher")
    P.record_pursuit(store, "reader_end", pursuit_id=pid)

    [view] = P.project_progress(store)
    reader_end = view["events"][1]
    assert (reader_end["phase"], reader_end["outcome"], reader_end["reason"]) == ("reader_end", "stopped", "stopped by the researcher")


def test_a_reader_end_no_record_says_reads_unknown_and_an_older_steps_own_outcome_stands(tmp_path: Path):
    store = ensure_project(tmp_path)
    lost = _start(store)
    P.record_reader_turn(store, phase="started", turn="r2", by="claude-code", provider="claude", pursuit_id=lost)   # its end not kept
    P.record_pursuit(store, "reader_end", pursuit_id=lost)
    older = _start(store)
    P.record_pursuit(store, "reader_end", pursuit_id=older, outcome="ok", launched=True)

    first, second = P.project_progress(store)
    assert first["events"][1]["outcome"] == "unknown"
    assert second["events"][1]["outcome"] == "ok" and second["reader_turns"] is None


def test_history_whose_step_said_failed_beside_a_stopped_turn_reads_the_turns_record(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _start(store)
    _reader_turn(store, pid, outcome="stopped", reason="stopped by the researcher")
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="failed", reason="the turn was stopped", launched=True)   # as hosts did

    [view] = P.project_progress(store)
    assert (view["events"][1]["outcome"], view["events"][1]["reason"]) == ("stopped", "stopped by the researcher")
