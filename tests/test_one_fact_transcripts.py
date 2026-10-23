"""One fact in one place (#284, ADR-0025 check 2), part 2: a turn's transcript keeps its conversation only.

A turn's record — its role, phase, author, provider, job, session — is its event; the transcript file under .proof/
repeated all of it beside the prompt and the events. It now keeps the conversation, and the turn reads back whole as
it did, its record joined from the event; an old transcript, which holds everything, reads the same. Synthetic
projects only."""

from __future__ import annotations

import json
from pathlib import Path

from proof_cli import pursuit as P
from proof_cli.proof_map import (DISCUSSION_DIR, TURNS_DIR, agent_turn_transcript, create_node, discussion_transcript, record_agent_turn,
                                 record_discussion_turn)
from proof_cli.storage import ensure_project

EVENTS = [{"t": "text", "text": "reading L1"}, {"t": "done"}]


def _on_disk(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_each_turns_transcript_keeps_only_its_conversation_and_the_turn_still_reads_back_whole(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N")
    record_agent_turn(store, "N", phase="started", turn="t1", role="prover", by="claude-code", provider="claude")
    record_agent_turn(store, "N", phase="ended", turn="t1", role="prover", by="claude-code", provider="claude", job=3, session_id="s-1",
                      step=2, events=EVENTS, prompt="prove N")
    assert _on_disk(tmp_path / TURNS_DIR / "N" / "t1.json") == {"prompt": "prove N", "events": EVENTS}
    turn = agent_turn_transcript(store, "N", "t1")
    assert (turn["role"], turn["phase"], turn["by"], turn["job"], turn["step"], turn["prompt"], turn["events"]) == (
        "prover", "ended", "claude-code", 3, 2, "prove N", EVENTS)

    record_discussion_turn(store, phase="started", turn="d1", by="claude-code", provider="claude", prompt="split T?", fresh=True)
    record_discussion_turn(store, phase="ended", turn="d1", by="claude-code", provider="claude", job=4, session_id="s-2", events=EVENTS, reply="three")
    assert set(_on_disk(tmp_path / DISCUSSION_DIR / "d1.json")) == {"prompt", "events"}
    said = discussion_transcript(store, "d1")
    assert (said["by"], said["provider"], said["job"], said["events"]) == ("claude-code", "claude", 4, EVENTS)

    pid = P.record_pursuit(store, "start", provider="claude").payload["pursuit_id"]
    P.record_reader_turn(store, phase="started", turn="r1", by="claude-code", provider="claude", pursuit_id=pid, prompt="Read the draft")
    P.record_reader_turn(store, phase="ended", turn="r1", by="claude-code", provider="claude", pursuit_id=pid, job=5, session_id="s-3",
                         outcome="ok", exit=0, events=EVENTS)
    assert _on_disk(tmp_path / P.READER_TURNS_DIR / "r1.json") == {"prompt": "Read the draft", "events": EVENTS}
    read = P.reader_turn_transcript(store, "r1")
    assert (read["outcome"], read["exit"], read["prompt"], read["events"]) == ("ok", 0, "Read the draft", EVENTS)


def test_a_transcript_from_before_reads_as_it_did(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N")
    record_agent_turn(store, "N", phase="ended", turn="t0", role="typesetter", by="codex", provider="codex", job=1, events=EVENTS, prompt="write it")
    old = {"phase": "ended", "turn": "t0", "role": "typesetter", "by": "codex", "provider": "codex", "job": 1, "prompt": "write it", "events": EVENTS}
    (tmp_path / TURNS_DIR / "N" / "t0.json").write_text(json.dumps(old), encoding="utf-8")   # as an older version kept it
    turn = agent_turn_transcript(store, "N", "t0")
    assert {key: turn[key] for key in old} == old

    record_discussion_turn(store, phase="ended", turn="d0", by="codex", provider="codex", job=2, events=EVENTS, reply="two")
    said = {"phase": "ended", "turn": "d0", "by": "codex", "provider": "codex", "job": 2, "reply": "two", "prompt": "split T?", "events": EVENTS}
    (tmp_path / DISCUSSION_DIR / "d0.json").write_text(json.dumps(said), encoding="utf-8")
    turn = discussion_transcript(store, "d0")
    assert {key: turn[key] for key in said} == said

    pid = P.record_pursuit(store, "start", provider="codex").payload["pursuit_id"]
    P.record_reader_turn(store, phase="ended", turn="r0", by="codex", provider="codex", pursuit_id=pid, job=3, outcome="ok", exit=0,
                         events=EVENTS, prompt="Read the draft")
    read = {"phase": "ended", "turn": "r0", "by": "codex", "provider": "codex", "job": 3, "outcome": "ok", "exit": 0,
            "prompt": "Read the draft", "events": EVENTS}
    (tmp_path / P.READER_TURNS_DIR / "r0.json").write_text(json.dumps(read), encoding="utf-8")
    turn = P.reader_turn_transcript(store, "r0")
    assert {key: turn[key] for key in read} == read
