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
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", budget={"turns": 0})
    P.record_pursuit(store, "theorem", pursuit_id=pid, theorem="T1", outcome="budget", reason="turn budget spent", budget={"turns": 12})
    P.record_pursuit(store, "stop", pursuit_id=pid, theorem="T1", reason="stopped by the researcher")
    P.record_pursuit(store, "release_failed", pursuit_id=pid, theorem="T1", reason="T1 still assigned: database is locked")
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="released", reason="stopped by the researcher")

    for pursuits in (P.project_progress(store), _progress_json(tmp_path)):
        assert len(pursuits) == 1
        view = pursuits[0]
        assert view["pursuit_id"] == pid and view["provider"] == "claude"
        assert (view["status"], view["reason"]) == ("released", "stopped by the researcher")
        assert view["theorem"] == "T1" and view["budget"] == {"turns": 12} and view["ended_at"]
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
    assert _code(lambda: P.record_pursuit(store, "start", pursuit_id="mine")) == "INVALID_PURSUIT_PHASE"
    assert _code(lambda: P.record_pursuit(store, "stop", pursuit_id="nobody")) == "PURSUIT_NOT_FOUND"
    assert _code(lambda: P.record_pursuit(store, "stop")) == "PURSUIT_NOT_FOUND"
    pid = _start(store)
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
