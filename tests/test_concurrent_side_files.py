"""Collaboration state and layered memory under concurrent processes (issue #39).

Both used to live in JSON side files under `.proof/` that every write
rewrote whole, with no lock: two processes' load-modify-save cycles
overwrote each other, and `memory.json` was not even written atomically.
They now live in SQLite and every read-modify-write runs inside one
`store.transaction()`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from proof_cli.collaboration import (
    Contributor,
    add_comment,
    list_comment_threads,
    list_comments,
    list_contributors,
    load_collaboration,
    save_collaboration,
    upsert_contributor,
)
from proof_cli.memory import load_memory, record_memory, save_memory
from proof_cli.storage import ensure_project, list_events

SRC = Path(__file__).resolve().parents[1] / "src"

WRITERS = 3
WRITES_PER_WRITER = 12  # 36 writes in all: contributors, comments, memory entries

# Each writer interleaves the three kinds of write. Its comments go on an
# object every writer comments on (whichever gets there first creates the
# thread) and on one object of its own (always a first thread creation).
_WRITER = """
import sys
from proof_cli.collaboration import Contributor, add_comment, upsert_contributor
from proof_cli.memory import record_memory
from proof_cli.storage import load_project

store = load_project(sys.argv[1])
name = sys.argv[2]
for index in range(int(sys.argv[3])):
    kind = index % 3
    if kind == 0:
        upsert_contributor(store, Contributor(display_name=f"{name}-contributor-{index}"))
    elif kind == 1:
        target = "shared" if index % 2 else f"own-{name}-{index}"
        add_comment(store, "theorem", target, author_id=name, content=f"{name}-comment-{index}")
    else:
        record_memory(store, "working", f"{name}-memory-{index}")
"""

# Reads the whole time the writers run: a reader must never see a
# half-written state.
_READER = """
import sys, time
from proof_cli.collaboration import load_collaboration
from proof_cli.memory import load_memory
from proof_cli.storage import load_project

store = load_project(sys.argv[1])
deadline = time.monotonic() + float(sys.argv[2])
while time.monotonic() < deadline:
    load_collaboration(store)
    load_memory(store)
"""


def _spawn(code: str, *args: str) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.Popen(
        [sys.executable, "-c", code, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def test_concurrent_collaboration_and_memory_writes_are_all_kept(tmp_path: Path):
    store = ensure_project(tmp_path)
    names = [f"w{index}" for index in range(WRITERS)]
    reader = _spawn(_READER, str(tmp_path), "4")
    writers = [_spawn(_WRITER, str(tmp_path), name, str(WRITES_PER_WRITER)) for name in names]
    for process in [*writers, reader]:
        _, stderr = process.communicate(timeout=180)
        assert process.returncode == 0, stderr

    expected = {kind: set() for kind in range(3)}
    for name in names:
        for index in range(WRITES_PER_WRITER):
            expected[index % 3].add(f"{name}-{('contributor', 'comment', 'memory')[index % 3]}-{index}")

    assert {c.display_name for c in list_contributors(store)} == expected[0]
    assert {c.content for c in list_comments(store)} == expected[1]
    assert {a.content for a in load_memory(store).working} == expected[2]

    # the shared object's first thread was created exactly once, and every
    # comment on it landed in that thread
    shared = list_comment_threads(store, object_type="theorem", object_id="shared")
    assert len(shared) == 1
    assert set(shared[0].participants) == set(names)
    threads = list_comment_threads(store)
    assert len(threads) == len({(thread.object_type, thread.object_id) for thread in threads})
    thread_ids = {thread.id for thread in threads}
    assert all(comment.thread_id in thread_ids for comment in list_comments(store))


# -- migration from the JSON side files --------------------------------------


def _legacy_project(tmp_path: Path, *, collaboration: dict | None = None, memory: dict | None = None):
    """A project as the pre-#39 code left it: side files under `.proof/`
    and no record that they were ever moved into SQLite."""
    store = ensure_project(tmp_path)
    conn = store.connect()
    conn.execute("DELETE FROM project_meta WHERE key IN ('collaboration_json_migrated', 'memory_json_migrated')")
    conn.commit()
    conn.close()
    if collaboration is not None:
        (tmp_path / ".proof" / "collaboration.json").write_text(json.dumps(collaboration))
    if memory is not None:
        (tmp_path / ".proof" / "memory.json").write_text(json.dumps(memory))
    return store


_LEGACY_COLLABORATION = {
    "project_id": "proj_alpha",
    "version": 1,
    "contributors": [
        {"id": "contrib_alice", "display_name": "Alice", "role": "maintainer", "team_ids": ["t1"], "notes": "lead"},
        {"id": "contrib_bob", "display_name": "Bob"},
    ],
    "policies": [{"project_id": "proj_alpha", "name": "strict", "who_can_publish": ["maintainer", "reviewer"]}],
    "comment_threads": [{"id": "thread_1", "object_type": "theorem", "object_id": "thm_main", "participants": ["alice"]}],
    "comments": [{"id": "comment_1", "thread_id": "thread_1", "author_id": "alice", "content": "check lemma 2"}],
    "branches": [{"id": "branch_1", "scope": "thm_main", "name": "route-a", "downstream_asset_ids": ["a1"]}],
    "publications": [{"id": "publication_1", "asset_id": "a1", "published_to": "team"}],
}

_LEGACY_MEMORY = {
    "project_id": "proj_alpha",
    "version": 4,
    "working": [{"id": "mem_w1", "layer": "working", "content": "try induction", "scope": {"project_id": "proj_alpha"}}],
    "semantic": [{"id": "mem_s1", "layer": "semantic", "content": "lemma 2 holds", "scope": {"project_id": "proj_alpha"}}],
    "tracked_symbols": ["f", "g"],
}


def test_existing_side_files_migrate_into_sqlite_without_loss(tmp_path: Path):
    store = _legacy_project(tmp_path, collaboration=_LEGACY_COLLABORATION, memory=_LEGACY_MEMORY)
    before_collaboration = json.loads(json.dumps(_LEGACY_COLLABORATION))

    state = load_collaboration(store)
    assert [(c.id, c.display_name, c.role.value, c.team_ids, c.notes) for c in state.contributors] == [
        ("contrib_alice", "Alice", "maintainer", ["t1"], "lead"),
        ("contrib_bob", "Bob", "contributor", [], ""),
    ]
    assert [p.name for p in state.policies] == ["strict"]
    assert state.policies[0].who_can_publish == ["maintainer", "reviewer"]
    assert [(t.id, t.participants) for t in state.comment_threads] == [("thread_1", ["alice"])]
    assert [(c.id, c.content) for c in state.comments] == [("comment_1", "check lemma 2")]
    assert [(b.id, b.downstream_asset_ids) for b in state.branches] == [("branch_1", ["a1"])]
    assert [p.id for p in state.publications] == ["publication_1"]

    memory = load_memory(store)
    assert [a.content for a in memory.working] == ["try induction"]
    assert [a.content for a in memory.semantic] == ["lemma 2 holds"]
    assert memory.tracked_symbols == ["f", "g"]

    # the side files are no longer read: writes go to SQLite, the files stay
    # as they were, and a later edit of them changes nothing
    upsert_contributor(store, Contributor(display_name="Carol"))
    record_memory(store, "working", "new idea")
    assert json.loads((tmp_path / ".proof" / "collaboration.json").read_text()) == before_collaboration
    assert json.loads((tmp_path / ".proof" / "memory.json").read_text()) == _LEGACY_MEMORY
    (tmp_path / ".proof" / "collaboration.json").write_text(json.dumps({"contributors": []}))
    (tmp_path / ".proof" / "memory.json").write_text(json.dumps({"working": []}))
    assert [c.display_name for c in list_contributors(store)] == ["Alice", "Bob", "Carol"]
    assert [a.content for a in load_memory(store).working] == ["try induction", "new idea"]

    kinds = [event.kind for event in list_events(store)]
    assert kinds.count("collaboration_json_migrated") == 1
    assert kinds.count("memory_json_migrated") == 1


def test_a_project_without_side_files_migrates_to_empty_state(tmp_path: Path):
    store = _legacy_project(tmp_path)
    assert load_collaboration(store).contributors == []
    assert load_memory(store).working == []
    upsert_contributor(store, Contributor(display_name="Alice"))
    assert [c.display_name for c in list_contributors(store)] == ["Alice"]


def test_an_unreadable_legacy_memory_file_is_refused_not_dropped(tmp_path: Path):
    """A half-written `memory.json` (the old non-atomic write) can't be
    migrated losslessly; it must not be silently replaced by empty memory."""
    store = _legacy_project(tmp_path, memory=None)
    (tmp_path / ".proof" / "memory.json").write_text('{"working": [')
    with pytest.raises(ValueError, match="memory.json"):
        load_memory(store)
    (tmp_path / ".proof" / "memory.json").write_text(json.dumps(_LEGACY_MEMORY))
    assert [a.content for a in load_memory(store).working] == ["try induction"]


def test_save_collaboration_and_save_memory_round_trip_through_sqlite(tmp_path: Path):
    store = ensure_project(tmp_path)
    state = load_collaboration(store)
    state.contributors.append(Contributor(display_name="Alice"))
    save_collaboration(store, state)
    assert [c.display_name for c in load_collaboration(store).contributors] == ["Alice"]
    assert not (tmp_path / ".proof" / "collaboration.json").exists()

    memory = load_memory(store)
    memory.tracked_symbols.append("h")
    save_memory(store, memory)
    assert load_memory(store).tracked_symbols == ["h"]
    assert not (tmp_path / ".proof" / "memory.json").exists()


def test_a_comment_on_a_new_object_creates_its_thread_in_the_same_write(tmp_path: Path):
    store = ensure_project(tmp_path)
    comment = add_comment(store, "theorem", "thm_new", author_id="alice", content="first")
    threads = list_comment_threads(store, object_type="theorem", object_id="thm_new")
    assert len(threads) == 1 and comment.thread_id == threads[0].id
    assert threads[0].participants == ["alice"]
