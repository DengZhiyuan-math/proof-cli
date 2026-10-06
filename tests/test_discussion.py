"""The map-level discussion's record (issue #177): project state, kept as a node's agent turns are."""

import pytest

from proof_cli.proof_map import DISCUSSION_DIR, ProofMapError, discussion_transcript, discussion_turns, record_discussion_turn
from proof_cli.storage import ensure_project, list_events


@pytest.fixture
def store(tmp_path):
    return ensure_project(tmp_path / "project")


def test_a_turn_is_recorded_started_then_ended_and_listed_as_one_entry_with_its_reply_and_session(store):
    record_discussion_turn(store, phase="started", turn="t1", by="claude-code", provider="claude", prompt="How should we split T?", fresh=True)
    assert discussion_turns(store) == [{"turn": "t1", "at": discussion_turns(store)[0]["at"], "by": "claude-code", "provider": "claude", "prompt": "How should we split T?",
                                        "fresh": True, "ended": False, "ended_at": None, "reply": "", "session_id": None, "is_error": False, "transcript": None}]
    events = [{"t": "init", "session_id": "s-1"}, {"t": "text", "text": "Three Claims: …"}, {"t": "done", "session_id": "s-1"}]
    record_discussion_turn(store, phase="ended", turn="t1", by="claude-code", provider="claude", job=7, session_id="s-1", events=events, reply="Three Claims: …")
    (entry,) = discussion_turns(store)
    assert entry["ended"] and entry["reply"] == "Three Claims: …" and entry["session_id"] == "s-1" and entry["is_error"] is False
    assert entry["transcript"] == (DISCUSSION_DIR / "t1.json").as_posix() and (store.root / DISCUSSION_DIR / "t1.json").is_file()
    assert discussion_transcript(store, "t1")["events"] == events and discussion_transcript(store, "t1")["prompt"] is None  # the ended record carries the events; the started one the prompt
    assert [e.kind for e in list_events(store) if e.kind == "map_discussion"] == ["map_discussion", "map_discussion"]
    assert all(e.entity_id is None for e in list_events(store) if e.kind == "map_discussion")  # the map's, not a node's


def test_the_list_is_oldest_first_and_bounded_and_a_failed_turn_says_so(store):
    for i in range(5):
        record_discussion_turn(store, phase="started", turn=f"t{i}", by="codex", provider="codex", prompt=f"message {i}")
    record_discussion_turn(store, phase="ended", turn="t4", by="codex", provider="codex", reply="", is_error=True, session_id=None)
    turns = discussion_turns(store, limit=3)
    assert [t["turn"] for t in turns] == ["t2", "t3", "t4"] and turns[-1]["is_error"] is True and turns[-1]["ended"]
    assert [t["turn"] for t in discussion_turns(store)] == [f"t{i}" for i in range(5)]


def test_the_reply_kept_in_the_event_is_capped_and_the_transcript_holds_the_whole(store):
    record_discussion_turn(store, phase="started", turn="long", by="claude-code", provider="claude", prompt="go on")
    text = "x" * 10000
    record_discussion_turn(store, phase="ended", turn="long", by="claude-code", provider="claude", reply=text, events=[{"t": "text", "text": text}])
    (entry,) = discussion_turns(store)
    assert len(entry["reply"]) == 4000 and len(discussion_transcript(store, "long")["events"][0]["text"]) == 10000


def test_a_bad_turn_id_or_phase_is_refused_and_an_unknown_transcript_is_none(store):
    with pytest.raises(ProofMapError) as refused:
        record_discussion_turn(store, phase="started", turn="../x", by="a", prompt="p")
    assert refused.value.code == "INVALID_REQUEST"
    with pytest.raises(ProofMapError):
        record_discussion_turn(store, phase="running", turn="ok", by="a")
    assert discussion_transcript(store, "nope") is None and discussion_transcript(store, "../../etc") is None
