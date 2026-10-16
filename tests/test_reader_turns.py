"""Issue #224: the Reader's turn is kept with the project, as a node's turns are, though it has no node.

A Reader turn that began is recorded `started`, then `ended` with its job, backend session, outcome and the whole
conversation under .proof/reader-turns/, tied to the project Pursue it belongs to. A launch refused before any job
exists is no turn and leaves none. A record that can't be written is a visible error, never taken as kept.
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

CONVERSATION = [
    {"t": "init", "session_id": "s-1", "model": "claude-opus-5-5"},
    {"t": "tool", "id": "u1", "name": "Bash", "summary": "pdftotext draft.pdf"},
    {"t": "tool_result", "id": "u1", "error": True, "preview": "Exit code 127: command not found: pdftotext"},
    {"t": "text", "text": "Reading the PDF pages instead."},
    {"t": "done", "exit": 0, "is_error": False, "session_id": "s-1"},
]


def _pursuit(store) -> str:
    return P.record_pursuit(store, "start", provider="claude").payload["pursuit_id"]


def _progress_json(root: Path) -> list[dict]:
    result = runner.invoke(app, ["project", "progress", "--root", str(root), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


def test_a_reader_turn_that_ends_is_kept_with_its_conversation_and_read_back_by_the_cli(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    P.record_reader_turn(store, phase="started", turn="r1", by="claude-code", provider="claude", pursuit_id=pid, prompt="Read the draft")
    P.record_reader_turn(store, phase="ended", turn="r1", by="claude-code", provider="claude", pursuit_id=pid,
                         job=3, session_id="s-1", outcome="ok", exit=0, is_error=False, events=CONVERSATION)

    [turn] = P.reader_turns(store)
    assert (turn["turn"], turn["pursuit_id"], turn["by"], turn["provider"]) == ("r1", pid, "claude-code", "claude")
    assert (turn["ended"], turn["outcome"], turn["job"], turn["session_id"], turn["exit"], turn["is_error"]) == (True, "ok", 3, "s-1", 0, False)
    assert turn["transcript"] == ".proof/reader-turns/r1.json" and (tmp_path / turn["transcript"]).is_file()
    kept = P.reader_turn_transcript(store, "r1")
    assert kept["events"] == CONVERSATION and kept["prompt"] == "Read the draft"
    assert kept["events"][2]["error"] is True  # the failed tool call is kept, not only the final success

    [view] = _progress_json(tmp_path)
    assert [t["turn"] for t in view["reader_turns"]] == ["r1"] and view["reader_turns"][0]["outcome"] == "ok"
    assert list_nodes(store) == [] and all(e.entity_id is None for e in list_events(store) if e.kind == P.READER_TURN_EVENT)


def test_a_reader_turn_that_failed_after_it_began_and_one_stopped_say_so(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    failed = [{"t": "init", "session_id": "s-2"}, {"t": "done", "exit": 23, "is_error": True, "stderr": "provider failure"}]
    P.record_reader_turn(store, phase="started", turn="r2", by="claude-code", provider="claude", pursuit_id=pid)
    P.record_reader_turn(store, phase="ended", turn="r2", by="claude-code", provider="claude", pursuit_id=pid,
                         job=4, session_id="s-2", outcome="failed", reason="provider failure", exit=23, is_error=True, events=failed)
    P.record_reader_turn(store, phase="started", turn="r3", by="claude-code", provider="claude", pursuit_id=pid)
    P.record_reader_turn(store, phase="ended", turn="r3", by="claude-code", provider="claude", pursuit_id=pid,
                         job=5, outcome="stopped", reason="stopped by the researcher", events=[])

    by_turn = {t["turn"]: t for t in P.reader_turns(store)}
    assert (by_turn["r2"]["outcome"], by_turn["r2"]["exit"], by_turn["r2"]["is_error"], by_turn["r2"]["reason"]) == ("failed", 23, True, "provider failure")
    assert P.reader_turn_transcript(store, "r2")["events"] == failed
    assert (by_turn["r3"]["outcome"], by_turn["r3"]["reason"]) == ("stopped", "stopped by the researcher")


def test_a_turn_that_began_with_no_recorded_end_reads_unended_not_ok(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    P.record_reader_turn(store, phase="started", turn="r4", by="claude-code", provider="claude", pursuit_id=pid)

    [turn] = P.reader_turns(store)
    assert (turn["ended"], turn["outcome"], turn["exit"], turn["transcript"]) == (False, None, None, None)


def test_history_kept_before_reader_turns_were_reads_them_as_unknown(tmp_path: Path):
    """A pursuit whose Reader ended with nothing kept says its turn is unknown; one that read no map has none."""
    store = ensure_project(tmp_path)
    read = _pursuit(store)
    P.record_pursuit(store, "reader_end", pursuit_id=read, outcome="ok")
    P.record_pursuit(store, "end", pursuit_id=read, outcome="done", reason="every Theorem's Coordinator ended done")
    mapped = _pursuit(store)
    P.record_pursuit(store, "theorem", pursuit_id=mapped, theorem="T1")

    old, new = _progress_json(tmp_path)
    assert old["reader_turns"] is None and new["reader_turns"] == []


def test_a_reader_turn_that_cannot_be_written_is_refused_with_a_code(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(P, "append_event", locked)
    with pytest.raises(ProofMapError) as caught:
        P.record_reader_turn(store, phase="started", turn="r5", by="claude-code", provider="claude", pursuit_id=pid)
    assert caught.value.code == "READER_TURN_RECORD_FAILED" and caught.value.details == {"phase": "started"}
    monkeypatch.undo()
    assert P.reader_turns(store) == []


def test_what_is_no_reader_turn_is_refused_and_an_unknown_transcript_is_none(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    for bad in ({"phase": "running", "turn": "ok"}, {"phase": "started", "turn": "../x"},
                {"phase": "ended", "turn": "ok", "outcome": "maybe"}, {"phase": "ended", "turn": "ok"}):
        with pytest.raises(ProofMapError) as refused:
            P.record_reader_turn(store, by="claude-code", pursuit_id=pid, **bad)
        assert refused.value.code == "INVALID_REQUEST"
    with pytest.raises(ProofMapError) as orphan:
        P.record_reader_turn(store, phase="started", turn="r6", by="claude-code", pursuit_id="nobody")
    assert orphan.value.code == "PURSUIT_NOT_FOUND"
    assert P.reader_turns(store) == []
    assert P.reader_turn_transcript(store, "nope") is None and P.reader_turn_transcript(store, "../../etc") is None
