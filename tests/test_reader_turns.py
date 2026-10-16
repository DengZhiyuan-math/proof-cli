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


def test_a_reader_refused_before_its_job_existed_has_no_turn_to_keep(tmp_path: Path):
    """A refusal before launch is no turn: its pursuit lists no Reader turn, not an unknown one (#224)."""
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="failed", reason="claude: command not found", launched=False)
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="stuck", reason="the Reader could not start")

    [view] = _progress_json(tmp_path)
    assert view["reader_turns"] == [] and view["events"][1]["launched"] is False


def test_a_reader_turn_that_began_but_whose_record_was_lost_reads_unknown(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="ok", launched=True)

    [view] = _progress_json(tmp_path)
    assert view["reader_turns"] is None and view["events"][1]["launched"] is True


# -- a transcript is kept only with its recorded end (#224) -----------------------------------------------------------


def _ended(store, pid: str, turn: str, events=CONVERSATION):
    P.record_reader_turn(store, phase="ended", turn=turn, by="claude-code", provider="claude", pursuit_id=pid,
                         job=3, session_id="s-1", outcome="ok", exit=0, is_error=False, events=events)


def _kept_files(root: Path) -> list[str]:
    folder = root / P.READER_TURNS_DIR
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def _one_kept_and_another_started(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    P.record_reader_turn(store, phase="started", turn="r1", by="claude-code", provider="claude", pursuit_id=pid)
    _ended(store, pid, "r1")
    P.record_reader_turn(store, phase="started", turn="r2", by="claude-code", provider="claude", pursuit_id=pid)
    return store, pid, (tmp_path / P.READER_TURNS_DIR / "r1.json").read_bytes()


def _nothing_more_kept(store, tmp_path: Path, r1: bytes):
    assert _kept_files(tmp_path) == ["r1.json"] and (tmp_path / P.READER_TURNS_DIR / "r1.json").read_bytes() == r1
    by_turn = {t["turn"]: t for t in P.reader_turns(store)}
    assert by_turn["r1"]["ended"] and by_turn["r1"]["transcript"] == ".proof/reader-turns/r1.json"
    assert (by_turn["r2"]["ended"], by_turn["r2"]["transcript"]) == (False, None)
    assert P.reader_turn_transcript(store, "r2") is None


def test_an_end_whose_event_cannot_be_written_leaves_no_transcript_and_the_earlier_one_untouched(tmp_path: Path, monkeypatch):
    store, pid, r1 = _one_kept_and_another_started(tmp_path)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(P, "append_event", locked)
    with pytest.raises(ProofMapError) as caught:
        _ended(store, pid, "r2")
    monkeypatch.undo()
    assert caught.value.code == "READER_TURN_RECORD_FAILED"
    _nothing_more_kept(store, tmp_path, r1)


def test_an_end_whose_transaction_cannot_commit_leaves_no_transcript(tmp_path: Path, monkeypatch):
    from proof_cli.storage import ProjectStore

    store, pid, r1 = _one_kept_and_another_started(tmp_path)

    class CommitFails:
        def __init__(self, conn):
            self._conn = conn

        def commit(self):
            raise sqlite3.OperationalError("disk I/O error")

        def __enter__(self):  # `with store.connect() as conn`, as the reads use it: the real connection's own handling
            self._conn.__enter__()
            return self

        def __exit__(self, *exc):
            return self._conn.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    real = ProjectStore.connect
    monkeypatch.setattr(ProjectStore, "connect", lambda self: CommitFails(real(self)))
    with pytest.raises(ProofMapError) as caught:
        _ended(store, pid, "r2")
    monkeypatch.undo()
    assert caught.value.code == "READER_TURN_RECORD_FAILED"
    _nothing_more_kept(store, tmp_path, r1)


def test_an_end_whose_transcript_cannot_be_put_in_place_leaves_no_half_file(tmp_path: Path, monkeypatch):
    store, pid, r1 = _one_kept_and_another_started(tmp_path)

    def no_rename(*args, **kwargs):
        raise OSError("read-only file system")

    import proof_cli.storage as storage

    monkeypatch.setattr(storage.os, "replace", no_rename)
    with pytest.raises(ProofMapError) as caught:
        _ended(store, pid, "r2")
    monkeypatch.undo()
    assert caught.value.code == "READER_TURN_RECORD_FAILED"
    _nothing_more_kept(store, tmp_path, r1)


def test_a_second_end_for_a_turn_already_ended_is_refused_and_touches_nothing(tmp_path: Path):
    store, pid, r1 = _one_kept_and_another_started(tmp_path)
    events_before = len(list_events(store))

    with pytest.raises(ProofMapError) as caught:
        _ended(store, pid, "r1", events=[{"t": "text", "text": "a different conversation"}])
    assert caught.value.code == "READER_TURN_ENDED"
    assert len(list_events(store)) == events_before
    _nothing_more_kept(store, tmp_path, r1)


def test_a_transcript_is_reported_only_while_its_file_is_there(tmp_path: Path):
    store, _, _ = _one_kept_and_another_started(tmp_path)
    (tmp_path / P.READER_TURNS_DIR / "r1.json").unlink()

    [r1] = [t for t in P.reader_turns(store) if t["turn"] == "r1"]
    assert (r1["ended"], r1["transcript"]) == (True, None)


# -- reading a Reader turn back (#224) ------------------------------------------------------------------------------


def _kept_reader_turn(root: Path):
    store = ensure_project(root)
    pid = _pursuit(store)
    P.record_reader_turn(store, phase="started", turn="r1", by="claude-code", provider="claude", pursuit_id=pid, prompt="Read the draft")
    _ended(store, pid, "r1")
    P.record_pursuit(store, "reader_end", pursuit_id=pid, outcome="ok", launched=True)
    P.record_pursuit(store, "end", pursuit_id=pid, outcome="done", reason="every Theorem's Coordinator ended done",
                     results={"T1": {"status": "done", "reason": "T1 is requested for review"}})
    return store, pid


def test_an_ended_turn_counts_its_failed_tool_calls_apart_from_its_own_outcome(tmp_path: Path):
    store, _ = _kept_reader_turn(tmp_path)

    [turn] = P.reader_turns(store)
    assert (turn["tool_failures"], turn["outcome"], turn["exit"]) == (1, "ok", 0)


def test_the_cli_reads_a_reader_turn_and_its_conversation_back(tmp_path: Path):
    _kept_reader_turn(tmp_path)

    result = runner.invoke(app, ["project", "reader-turn", "r1", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True and envelope["command"] == "project.reader_turn"
    data = envelope["data"]
    assert (data["turn"], data["outcome"], data["exit"], data["tool_failures"], data["prompt"]) == ("r1", "ok", 0, 1, "Read the draft")
    assert data["events"] == CONVERSATION

    shown = runner.invoke(app, ["project", "reader-turn", "r1", "--root", str(tmp_path)])
    assert shown.exit_code == 0, shown.output
    text = shown.output
    assert "turn outcome: ok, exit 0" in text
    assert "1 tool-call failure(s) in the turn" in text
    assert "tool result u1: FAILED — Exit code 127: command not found: pdftotext" in text
    assert "Reading the PDF pages instead." in text and "nothing shortened" not in text and "whole" not in text


def test_a_long_text_is_shown_whole_in_plain_output(tmp_path: Path):
    store = ensure_project(tmp_path)
    pid = _pursuit(store)
    long_text = "the height bound " * 400
    P.record_reader_turn(store, phase="started", turn="r9", by="claude-code", provider="claude", pursuit_id=pid)
    _ended(store, pid, "r9", events=[{"t": "text", "text": long_text}, {"t": "done", "exit": 0}])

    shown = runner.invoke(app, ["project", "reader-turn", "r9", "--root", str(tmp_path)])
    assert shown.exit_code == 0 and " ".join(shown.output.split()).count("the height bound") == 400


def test_an_unknown_reader_turn_is_refused_with_a_code(tmp_path: Path):
    ensure_project(tmp_path)
    result = runner.invoke(app, ["project", "reader-turn", "nope", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "READER_TURN_NOT_FOUND"


def test_a_project_copied_elsewhere_reads_its_reader_turn_back_without_the_providers_profile(tmp_path: Path):
    import shutil

    _kept_reader_turn(tmp_path / "here")
    shutil.copytree(tmp_path / "here", tmp_path / "there")
    shutil.rmtree(tmp_path / "here")

    result = runner.invoke(app, ["project", "reader-turn", "r1", "--root", str(tmp_path / "there"), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["events"] == CONVERSATION


def test_plain_progress_shows_each_pursuits_results_and_reader_turns(tmp_path: Path):
    store, _ = _kept_reader_turn(tmp_path)
    old = _pursuit(store)
    P.record_pursuit(store, "reader_end", pursuit_id=old, outcome="ok")  # history from before: nothing kept, launched unsaid

    text = " ".join(runner.invoke(app, ["project", "progress", "--root", str(tmp_path)]).output.split())
    assert "results: T1 done — T1 is requested for review" in text
    assert "Reader turn r1: ok, exit 0, 1 tool-call failure(s), conversation kept" in text
    assert "Reader turns: not kept with the project (unknown)" in text and "results: not recorded" in text


# -- the form a kept conversation has: the backend's previews (#224) ---------------------------------------------------

LIMITS = {"tool.summary[Bash]": 50, "tool.summary[Read]": None, "tool.summary": 30, "tool_result.preview": 40}


def _with_limits(root: Path, events, **ended):
    store = ensure_project(root)
    pid = _pursuit(store)
    P.record_reader_turn(store, phase="started", turn="r7", by="agent-x", provider="claude", pursuit_id=pid)
    P.record_reader_turn(store, phase="ended", turn="r7", by="agent-x", provider="claude", pursuit_id=pid,
                         job=1, outcome="ok", exit=0, is_error=False, events=events, **ended)
    return store


def test_a_field_that_reached_its_backends_limit_is_marked_possibly_shortened_and_no_other(tmp_path: Path):
    events = [
        {"t": "tool", "id": "a", "name": "Bash", "summary": "c" * 50},      # at the command's limit
        {"t": "tool", "id": "b", "name": "Read", "summary": "p" * 30},      # a path: kept whole
        {"t": "tool", "id": "c", "name": "Fetch", "summary": "u" * 29},     # under the input's limit
        {"t": "tool_result", "id": "a", "error": False, "preview": "o" * 40},
        {"t": "text", "text": "t" * 500},                                   # text is never cut
    ]
    store = _with_limits(tmp_path, events, backend="claude", preview_limits=LIMITS)

    view = P.reader_turn(store, "r7")
    assert (view["backend"], view["preview_limits"]) == ("claude", LIMITS)
    assert view["possibly_shortened"] == [{"event": 1, "field": "summary", "limit": 50}, {"event": 4, "field": "preview", "limit": 40}]

    text = " ".join(runner.invoke(app, ["project", "reader-turn", "r7", "--root", str(tmp_path)]).output.split())
    assert "the events as the claude backend reported them" in text
    assert "tool.summary[Bash] 50, tool.summary 30, tool_result.preview 40 characters" in text
    assert text.count("possibly shortened by the backend") == 2
    assert "(its 50-character limit)" in text and "(its 40-character limit)" in text
    assert text.count("shortened") == text.count("possibly shortened")  # never a cut it did not record


def test_a_record_without_the_backends_limits_says_so_and_that_previews_may_be_shortened(tmp_path: Path):
    store = _with_limits(tmp_path, [{"t": "tool_result", "id": "a", "error": False, "preview": "o" * 300}])

    view = P.reader_turn(store, "r7")
    assert (view["backend"], view["preview_limits"], view["possibly_shortened"]) == (None, None, None)
    text = " ".join(runner.invoke(app, ["project", "reader-turn", "r7", "--root", str(tmp_path)]).output.split())
    assert "the backend's preview limits were not recorded; tool previews may be shortened" in text


def test_reader_turn_reads_none_for_an_unknown_turn(tmp_path: Path):
    assert P.reader_turn(ensure_project(tmp_path), "nope") is None
