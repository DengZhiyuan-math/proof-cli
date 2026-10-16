"""A turn's transcript is kept only with its recorded end — for node turns, discussion turns and the Reader's alike.

One writer puts each in place inside the transaction that records the turn's end. If that event or the commit fails,
what this attempt wrote is removed and anything it moved aside is put back; a file left by a crash before an end was
recorded (an orphan) may be replaced by the retry; a turn whose end is recorded is refused a second one, touching
nothing (TURN_ENDED, READER_TURN_ENDED for the Reader).
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from proof_cli import proof_map, pursuit
from proof_cli.proof_map import DISCUSSION_DIR, TURNS_DIR, ProofMapError, create_node, record_agent_turn, record_discussion_turn
from proof_cli.storage import ProjectStore, ensure_project, list_events

AGENT = "agent-x"
EVENTS = [{"t": "text", "text": "a reply"}, {"t": "done", "exit": 0}]


@dataclass
class Kind:
    name: str
    module: object
    folder: Path
    ended_code: str
    setup: Callable
    start: Callable
    end: Callable


def _node_setup(store):
    create_node(store, node_id="N", kind="lemma", statement="a lemma")


def _reader_setup(store):
    pursuit.record_pursuit(store, "start", provider="claude")


def _pursuit_id(store) -> str:
    return pursuit.project_progress(store)[-1]["pursuit_id"]


KINDS = [
    Kind("node", proof_map, TURNS_DIR / "N", "TURN_ENDED", _node_setup,
         lambda store, turn: record_agent_turn(store, "N", phase="started", turn=turn, role="prover", by=AGENT),
         lambda store, turn, events: record_agent_turn(store, "N", phase="ended", turn=turn, role="prover", by=AGENT, job=1, events=events)),
    Kind("discussion", proof_map, DISCUSSION_DIR, "TURN_ENDED", lambda store: None,
         lambda store, turn: record_discussion_turn(store, phase="started", turn=turn, by=AGENT, prompt="a question"),
         lambda store, turn, events: record_discussion_turn(store, phase="ended", turn=turn, by=AGENT, events=events, reply="a reply")),
    Kind("reader", pursuit, pursuit.READER_TURNS_DIR, "READER_TURN_ENDED", _reader_setup,
         lambda store, turn: pursuit.record_reader_turn(store, phase="started", turn=turn, by=AGENT, pursuit_id=_pursuit_id(store)),
         lambda store, turn, events: pursuit.record_reader_turn(store, phase="ended", turn=turn, by=AGENT, pursuit_id=_pursuit_id(store),
                                                                outcome="ok", exit=0, events=events)),
]


@pytest.fixture(params=KINDS, ids=lambda kind: kind.name)
def turns(request, tmp_path: Path):
    kind = request.param
    store = ensure_project(tmp_path)
    kind.setup(store)
    kind.start(store, "t1")
    kind.end(store, "t1", EVENTS)
    kind.start(store, "t2")
    folder = tmp_path / kind.folder
    return kind, store, folder, (folder / "t1.json").read_bytes()


def _files(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def _ended(store, turn: str) -> int:
    return sum(1 for e in list_events(store) if (e.payload or {}).get("turn") == turn and (e.payload or {}).get("phase") == "ended")


def _locked(*args, **kwargs):
    raise sqlite3.OperationalError("database is locked")


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


def test_an_end_whose_event_cannot_be_written_keeps_no_transcript(turns, monkeypatch):
    kind, store, folder, t1 = turns
    monkeypatch.setattr(kind.module, "append_event", _locked)
    with pytest.raises(Exception):
        kind.end(store, "t2", EVENTS)
    monkeypatch.undo()
    assert _files(folder) == ["t1.json"] and (folder / "t1.json").read_bytes() == t1 and _ended(store, "t2") == 0


def test_an_end_whose_commit_fails_keeps_no_transcript(turns, monkeypatch):
    kind, store, folder, t1 = turns
    real = ProjectStore.connect
    monkeypatch.setattr(ProjectStore, "connect", lambda self: CommitFails(real(self)))
    with pytest.raises(Exception):
        kind.end(store, "t2", EVENTS)
    monkeypatch.undo()
    assert _files(folder) == ["t1.json"] and (folder / "t1.json").read_bytes() == t1 and _ended(store, "t2") == 0


def test_an_orphan_a_crash_left_before_the_end_was_recorded_is_replaced_by_the_retry(turns):
    kind, store, folder, _ = turns
    (folder / "t2.json").write_text("half of an earlier attempt", encoding="utf-8")
    kind.end(store, "t2", EVENTS)

    assert _files(folder) == ["t1.json", "t2.json"] and _ended(store, "t2") == 1
    assert "half of an earlier attempt" not in (folder / "t2.json").read_text(encoding="utf-8")


def test_an_orphan_is_put_back_when_the_retry_fails(turns, monkeypatch):
    kind, store, folder, _ = turns
    (folder / "t2.json").write_text("half of an earlier attempt", encoding="utf-8")
    monkeypatch.setattr(kind.module, "append_event", _locked)
    with pytest.raises(Exception):
        kind.end(store, "t2", EVENTS)
    monkeypatch.undo()
    assert _files(folder) == ["t1.json", "t2.json"] and (folder / "t2.json").read_text(encoding="utf-8") == "half of an earlier attempt"


def test_a_turn_whose_end_is_recorded_is_refused_a_second_and_nothing_changes(turns):
    kind, store, folder, t1 = turns
    before = len(list_events(store))
    with pytest.raises(ProofMapError) as refused:
        kind.end(store, "t1", [{"t": "text", "text": "another conversation"}])
    assert refused.value.code == kind.ended_code
    assert len(list_events(store)) == before and _files(folder) == ["t1.json"] and (folder / "t1.json").read_bytes() == t1


def test_an_orphan_is_put_back_when_the_retrys_commit_fails(turns, monkeypatch):
    kind, store, folder, _ = turns
    (folder / "t2.json").write_text("half of an earlier attempt", encoding="utf-8")
    real = ProjectStore.connect
    monkeypatch.setattr(ProjectStore, "connect", lambda self: CommitFails(real(self)))
    with pytest.raises(Exception):
        kind.end(store, "t2", EVENTS)
    monkeypatch.undo()
    assert _files(folder) == ["t1.json", "t2.json"] and (folder / "t2.json").read_text(encoding="utf-8") == "half of an earlier attempt"
    assert _ended(store, "t2") == 0
