"""Issue #201: a project Pursue's history as `pursuit` events, read by `proof project progress`.

The host that runs a project Pursue records each step through one service function; the events are the project's
own, append-only, with no node behind them. A pursuit with no end reads `interrupted`, and a start that can't be
recorded is refused with a code, so the host starts no provider.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import pursuit as P
from proof_cli.cli import app
from proof_cli.proof_map import ProofMapError, list_nodes
from proof_cli.storage import ensure_project, list_events

runner = CliRunner()

# a Pursue's whole budget, as a host records it (proof-agents#19)
WHOLE = {"turns_max": 12, "minutes_max": 90.0, "spent": 0, "structure_spent": 0, "failed_launches": 0}


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def _progress_json(root: Path) -> list[dict]:
    result = runner.invoke(app, ["project", "progress", "--root", str(root), "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True and envelope["command"] == "project.progress"
    return envelope["data"]


def _start(store, provider="claude") -> str:
    return P.record_pursuit(store, "start", provider=provider).payload["pursuit_id"]


def test_each_phase_round_trips_through_the_service_and_the_cli(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _start(store)
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="ok")
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", budget=WHOLE)
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", outcome="budget", reason="turn budget spent", budget={**WHOLE, "spent": 12})
    P.record_pursuit(store, "stop", pursuit_id=pid, theorem="T1", reason="stopped by the researcher")
    P.record_pursuit(store, "release_failed", pursuit_id=pid, theorem="T1", reason="T1 still assigned: database is locked")
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="released", reason="stopped by the researcher")

    for pursuits in (P.project_progress(store), _progress_json(tmp_path)):
        assert len(pursuits) == 1
        view = pursuits[0]
        assert view["pursuit_id"] == pid and view["provider"] == "claude"
        assert (view["status"], view["reason"]) == ("released", "stopped by the researcher")
        assert view["theorem"] == "T1" and view["budget"] == {**WHOLE, "spent": 12} and view["ended_at"]
        assert [e["phase"] for e in view["events"]] == ["start", "reader_end", "theorem", "theorem", "stop", "release_failed", "end"]
        failed = view["events"][5]
        assert (failed["theorem"], failed["reason"]) == ("T1", "T1 still assigned: database is locked")
        assert view["events"][3]["outcome"] == "budget"

    events = [e for e in list_events(store) if e.kind == P.PURSUIT_EVENT]
    assert len(events) == 7 and all(e.entity_id is None for e in events)


def test_a_pursuit_with_no_end_reads_interrupted_and_the_live_one_running(tmp_path: Path):
    store = ensure_project(tmp_path)
    old = _start(store)
    P.record_pursuit(store, "theorem", pursuit_id=old, theorem="T1")
    now = _start(store, provider="codex")

    [first, second] = _progress_json(tmp_path)
    assert (first["pursuit_id"], first["status"], first["last_phase"], first["ended_at"]) == (old, "interrupted", "theorem", None)
    assert "no end was recorded" in first["reason"]
    assert second["status"] == "interrupted"

    views = {v["pursuit_id"]: v["status"] for v in P.project_progress(store, live=now)}
    assert views == {old: "interrupted", now: "running"}


def test_a_reader_failure_is_a_pursuit_event_not_a_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _start(store)
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="failed", reason="the Reader stated no Theorem")
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="stuck", reason="the Reader stated no Theorem")

    assert list_nodes(store) == []
    [view] = P.project_progress(store)
    assert (view["status"], view["reason"]) == ("stuck", "the Reader stated no Theorem")
    assert view["events"][1]["outcome"] == "failed"


def test_a_failing_write_at_start_is_refused_with_a_code_and_records_nothing(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(P, "append_event", locked)
    with pytest.raises(ProofMapError) as caught:
        P.record_pursuit(store, "start", provider="claude")
    assert caught.value.code == "PURSUIT_RECORD_FAILED" and caught.value.details == {"phase": "start"}
    monkeypatch.undo()
    assert P.project_progress(store) == []


def test_the_service_refuses_what_is_not_a_pursuits_history(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert _code(lambda: P.record_pursuit(store, "resume")) == "INVALID_PURSUIT_PHASE"
    assert _code(lambda: P.record_pursuit(store, "stop", pursuit_id="nobody")) == "PURSUIT_NOT_FOUND"
    assert _code(lambda: P.record_pursuit(store, "stop")) == "PURSUIT_NOT_FOUND"
    pid = _start(store)
    assert _code(lambda: P.record_pursuit(store, "start", pursuit_id=pid)) == "INVALID_PURSUIT_PHASE"   # another pursuit's id
    assert _code(lambda: P.record_pursuit(store, "end", pursuit_id=pid)) == "PURSUIT_OUTCOME_REQUIRED"
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="done")
    assert _code(lambda: P.record_pursuit(store, "stop", pursuit_id=pid)) == "PURSUIT_ENDED"
    assert len(P.project_progress(store)[0]["events"]) == 2  # nothing refused was written


def test_progress_without_json_lists_each_pursuit_and_its_events(tmp_path: Path):
    store = ensure_project(tmp_path)
    empty = runner.invoke(app, ["project", "progress", "--root", str(tmp_path)])
    assert empty.exit_code == 0 and "No project Pursue" in empty.output

    pid = _start(store)
    P.record_pursuit(store, "release_failed", pursuit_id=pid, theorem="T1", reason="still assigned")
    result = runner.invoke(app, ["project", "progress", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert pid in result.output and "interrupted" in result.output
    assert "release_failed T1: still assigned" in result.output


def test_the_pursuits_total_and_each_theorems_result_are_kept_and_read_back(tmp_path: Path):
    """#223: the Pursue's whole budget and its results per Theorem live in the project, not only in the host's memory."""
    store = ensure_project(tmp_path)
    pid = _start(store)
    total = {"turns_max": 12, "minutes_max": 90.0, "spent": 1, "structure_spent": 1, "failed_launches": 0}
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="ok", budget=total)
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", budget={**total, "spent": 3})
    done = {"T1": {"status": "done", "reason": "T1 is requested for review"}}
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="done", reason="every Theorem's Coordinator ended done",
                     budget={**total, "spent": 9, "structure_spent": 2}, results=done)

    for pursuits in (P.project_progress(store), _progress_json(tmp_path)):
        [view] = pursuits
        assert view["budget"] == {"turns_max": 12, "minutes_max": 90.0, "spent": 9, "structure_spent": 2, "failed_launches": 0}
        assert view["results"] == {"T1": {"status": "done", "reason": "T1 is requested for review"}}
        assert view["events"][-1]["results"] == done and view["events"][1]["results"] is None


def test_a_pursuit_recorded_without_results_reads_them_as_unknown_not_empty(tmp_path: Path):
    """#223: history written before results were kept says nothing about them; it is not read as 'no results'."""
    store = ensure_project(tmp_path)
    pid = _start(store)
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="done", reason="every Theorem's Coordinator ended done")

    [view] = _progress_json(tmp_path)
    assert view["results"] is None and view["budget"] is None


def test_plain_progress_says_when_a_recorded_spend_is_incomplete(tmp_path: Path):
    """A host that could not count every turn says so in the budget it records; the plain view says it, JSON keeps it."""
    store = ensure_project(tmp_path)
    counted = _start(store)
    P.record_pursuit(store, "end", pursuit_id=counted, outcome="done", reason="ended", budget={**WHOLE, "spent": 4})
    partial = _start(store)
    P.record_pursuit(store, "end", pursuit_id=partial, outcome="stuck", reason="the Reader could not start",
                     budget={**WHOLE, "spend_incomplete": True})

    first, second = _progress_json(tmp_path)
    assert first["budget"] == {**WHOLE, "spent": 4}
    assert second["budget"] == {**WHOLE, "spend_incomplete": True}
    text = runner.invoke(app, ["project", "progress", "--root", str(tmp_path)]).output
    assert text.count("spend: incomplete — not every turn was counted") == 1
    assert text.index("spend: incomplete") > text.index(partial)


def test_plain_progress_says_when_a_pursuits_budget_was_not_recorded(tmp_path: Path):
    """#223: history from before the Pursue's total was kept read `null` as JSON, and plain progress said nothing of it: an
    unrecorded budget is said as that, never left out or read as nothing spent."""
    store = ensure_project(tmp_path)
    older = _start(store)
    P.record_pursuit(store, "end", pursuit_id=older, outcome="stuck", reason="the Reader stated no Theorem")
    counted = _start(store)
    P.record_pursuit(store, "end", pursuit_id=counted, outcome="done", reason="ended", budget={**WHOLE, "spent": 4})

    text = runner.invoke(app, ["project", "progress", "--root", str(tmp_path)]).output
    assert text.count("budget: not recorded") == 1
    assert text.index(older) < text.index("budget: not recorded") < text.index(counted)


def test_a_spend_checkpoint_keeps_what_an_interrupted_pursuit_had_spent(tmp_path: Path):
    """The budget was recorded only at start, at each Theorem and at the end: a pursuit interrupted mid-Theorem read back
    as nothing spent. A `spend` checkpoint, recorded as turns end, is the last budget an interrupted pursuit reads."""
    store = ensure_project(tmp_path)
    pid = _start(store)
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", budget=WHOLE)
    P.record_pursuit(store, "spend", pursuit_id=pid, budget={**WHOLE, "spent": 7})
    P.record_pursuit(store, "spend", pursuit_id=pid, budget={**WHOLE, "spent": 9})
    (view,) = P.project_progress(store)
    # what an interrupted pursuit spent is what it last recorded: a floor, so it reads as incomplete (the page and the CLI)
    assert view["status"] == P.INTERRUPTED and view["budget"] == {**WHOLE, "spent": 9, "spend_incomplete": True}
    assert view["theorem"] == "T1" and view["last_phase"] == "spend"
    plain = runner.invoke(app, ["project", "progress", "--root", str(tmp_path)]).output
    assert "spend: incomplete" in plain and plain.count(" spend ") == 1   # its last spend, not one line per turn


def test_an_audit_start_is_kept_with_the_pursuit(tmp_path: Path):
    """ADR-0024: whether a Pursue audited first is part of its history, read back after a restart."""
    store = ensure_project(tmp_path)
    audited = P.record_pursuit(store, "start", provider="claude", audit=True).payload["pursuit_id"]
    plain = _start(store)
    views = {view["pursuit_id"]: view for view in P.project_progress(store)}
    assert views[audited]["audit"] is True and views[plain]["audit"] is False
    with pytest.raises(ProofMapError):
        P.record_pursuit(store, "end", pursuit_id=audited, outcome="done", audit=True)   # only a start says it


def test_a_start_on_one_nodes_subtree_is_kept_with_its_root(tmp_path: Path):
    """A Pursue on one Theorem's or Lemma's subtree (its Coordinator's Start) is kept as a pursuit too, naming its root: a
    trial's subtree Start lived in memory only, so a restarted page read the project's older Pursue, done, as the last."""
    store = ensure_project(tmp_path)
    project = _start(store)
    P.record_pursuit(store, "end", pursuit_id=project, outcome="done")
    subtree = P.record_pursuit(store, "start", provider="claude", root="T", audit=True).payload["pursuit_id"]
    P.record_pursuit(store, "end", pursuit_id=subtree, outcome="stuck", reason="T rests on parked L")
    views = {view["pursuit_id"]: view for view in P.project_progress(store)}
    assert views[project]["root"] is None
    assert views[subtree]["root"] == "T" and views[subtree]["status"] == "stuck" and views[subtree]["audit"] is True
    with pytest.raises(ProofMapError):
        P.record_pursuit(store, "end", pursuit_id=project, outcome="done", root="T")   # only a start names it
    with pytest.raises(ProofMapError):
        P.record_pursuit(store, "start", provider="claude", root=" ")
    plain = runner.invoke(app, ["project", "progress", "--root", str(tmp_path)]).output
    assert "on T's subtree" in plain and plain.count("on T's subtree") == 1
