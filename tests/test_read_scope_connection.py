"""One read, one connection (#43): the reads of a read scope share one SQLite connection.

A page read asks every node for its claim, proofs, pins, Challenges and work log, and each read opened a connection
of its own, running two PRAGMAs to check the schema: about 390 connections per map request on a 2,311-event trial
log, 0.10 s of a 0.21 s map. A read scope now opens one, on its first read, and closes it when it ends; reads
outside a scope open their own as before. Writes never run on it, it holds no read lock between reads (rollback-
journal mode: another process's writer would wait on one), and it belongs to the thread that opened the scope.
"""

from __future__ import annotations

import contextvars
import sqlite3
import threading
from pathlib import Path

import pytest

import proof_cli.storage as storage
from proof_cli.definitions import nodes_naming
from proof_cli.proof_map import create_node, get_node, list_nodes, record_progress, work_log
from proof_cli.storage import (
    ProjectNotFoundError,
    ProjectStore,
    append_event,
    ensure_project,
    get_active_claim,
    get_current_candidate_proof,
    get_definition,
    get_dependency_pin,
    get_proof_map_node,
    list_candidate_proofs_for_node,
    list_challenges,
    list_events,
    list_events_of_kind,
    list_fog_items,
    read_only,
    read_project_instance_id,
    read_scope,
    read_state,
)
from _proofs import submit_proof


@pytest.fixture
def opened(monkeypatch):
    """Every connection opened from here on, each with the statements run on it."""
    seen: list[tuple[sqlite3.Connection, list[str]]] = []
    real_connect = storage.connect

    def traced(path):
        conn = real_connect(path)
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        seen.append((conn, statements))
        return conn

    monkeypatch.setattr(storage, "connect", traced)
    return seen


def _small_map(root: Path):
    """A Theorem on two Claims, one written in a Definition, one with a proof up for review and a plan on its log."""
    from proof_cli.definitions import add_definition
    from proof_cli.fog import add_fog

    store = ensure_project(root)
    add_definition(store, "D", term="weight", text="w", created_by="dec-1")
    create_node(store, node_id="a", kind="claim", statement="a", definitions=["D"], created_by="dec-1")
    create_node(store, node_id="b", kind="claim", statement="b", created_by="dec-1")
    create_node(store, node_id="top", kind="theorem", statement="t", dependencies=["a", "b"])
    submit_proof(store, "a", claimant_id="agent_a", scoping_rationale="r", content="proof of a")
    record_progress(store, "b", role="prover", by="agent_a/prover", plan=["first", "second"])
    add_fog(store, "a gap both may share", near=["a", "b"], created_by="dec-1")
    return store


def _reads(store) -> list:
    """What a page reads of each node: the reads a connection each was opened for."""
    answers: list = [read_state(store).project_id, read_project_instance_id(store), len(list_events(store))]
    for node in list_nodes(store):
        answers += [
            get_node(store, node.id), get_active_claim(store, node.id), get_current_candidate_proof(store, node.id),
            list_candidate_proofs_for_node(store, node.id), list_challenges(store, target_node_id=node.id),
            [get_dependency_pin(store, node.id, dependency_id) for dependency_id in node.dependencies],
            [get_definition(store, definition_id) for definition_id in node.definitions], work_log(store, node.id),
        ]
    answers += [list_fog_items(store), list_events_of_kind(store, "proof_map_node_created"), nodes_naming(store, "D")]
    return answers


def _is_read(statement: str) -> bool:
    return statement.lstrip().upper().startswith(("SELECT", "PRAGMA"))


def test_a_read_scope_reads_on_one_connection(tmp_path: Path, opened):
    store = _small_map(tmp_path)
    opened.clear()
    unscoped = _reads(store)  # outside a scope, each read opens its own, as before
    per_read = len(opened)
    opened.clear()

    with read_scope():
        scoped = _reads(store)

    assert scoped == unscoped
    assert len(opened) == 1 and per_read > 20, (len(opened), per_read)


def test_the_scopes_connection_is_opened_on_its_first_read_and_closed_when_it_ends(tmp_path: Path, opened):
    store = _small_map(tmp_path)
    opened.clear()

    with read_scope():
        assert opened == []  # nothing read yet, nothing opened
        list_nodes(store)
        [(conn, _)] = opened

    with pytest.raises(sqlite3.ProgrammingError):  # closed
        conn.execute("SELECT 1")


def test_between_reads_the_scope_holds_no_lock_and_sees_what_another_process_committed(tmp_path: Path, opened):
    """Rollback-journal mode: a read transaction left open on the scope's connection would keep another process's
    writer from committing (and show its reads a state from before the write)."""
    store = _small_map(tmp_path)
    opened.clear()

    with read_scope():
        node = get_proof_map_node(store, "a")
        [(conn, _)] = opened
        assert not conn.in_transaction
        other = sqlite3.connect(store.db_path, timeout=0)  # fails at once, rather than waiting, on any lock the scope holds
        try:
            edited = node.model_copy(update={"statement": "a, edited by another process"})
            other.execute("UPDATE proof_map_nodes SET data = ? WHERE id = ?", (edited.model_dump_json(), "a"))
            other.commit()
        finally:
            other.close()
        assert get_proof_map_node(store, "a").statement == "a, edited by another process"
        assert len(opened) == 1


def test_writes_inside_a_scope_never_run_on_its_connection_and_the_reads_after_them_see_them(tmp_path: Path, opened):
    store = _small_map(tmp_path)
    opened.clear()

    with read_scope():
        count = len(list_events(store))
        append_event(store, "synthetic_note", "on a connection of its own")
        with store.transaction() as conn:
            append_event(store, "synthetic_note", "in a transaction", conn=conn)
        node = get_proof_map_node(store, "b")
        storage.update_proof_map_node(store, node.model_copy(update={"statement": "b, restated"}))
        assert len(list_events(store)) == count + 2
        assert get_proof_map_node(store, "b").statement == "b, restated"

    scope_reads = [statements for _, statements in opened if any("FROM events ORDER BY created_at" in s for s in statements)]
    assert scope_reads, "the scope read the log"
    assert all(_is_read(statement) for statements in scope_reads for statement in statements)
    assert any(not _is_read(statement) for _, statements in opened for statement in statements), "the writes ran, elsewhere"


def test_a_write_while_a_read_is_using_the_scopes_connection_leaves_that_read_its_connection(tmp_path: Path):
    store = _small_map(tmp_path)

    with read_scope():
        with storage._reading(store, None) as conn:
            first = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            append_event(store, "synthetic_note", "written mid-read")
            assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == first + 1
        with pytest.raises(sqlite3.ProgrammingError):  # closed once that read was done with it
            conn.execute("SELECT 1")
        assert len(list_events(store)) == first + 1


def test_a_write_on_the_scopes_connection_is_undone_as_closing_a_fresh_one_would_undo_it(tmp_path: Path):
    """No read helper writes; one that did would leave the shared connection in a transaction, holding a lock and
    hiding what others commit, for the rest of the scope."""
    store = _small_map(tmp_path)

    with read_scope():
        with storage._reading(store, None) as conn:
            conn.execute("INSERT INTO project_meta(key, value) VALUES ('synthetic', '1')")
        assert not conn.in_transaction
        with storage._reading(store, None) as again:
            assert again is conn
            assert again.execute("SELECT 1 FROM project_meta WHERE key = 'synthetic'").fetchone() is None


def test_a_context_copied_inside_a_scope_reads_as_outside_one_once_the_scope_has_ended(tmp_path: Path, opened):
    """A task created inside a scope may outlive it: its reads then open and close their own, as outside any scope."""
    store = _small_map(tmp_path)
    with read_scope():
        storage.list_proof_map_nodes(store)
        copied = contextvars.copy_context()
    opened.clear()

    copied.run(storage.list_proof_map_nodes, store)

    [(conn, _)] = opened
    with pytest.raises(sqlite3.ProgrammingError):  # closed
        conn.execute("SELECT 1")


def test_another_thread_in_the_scopes_context_reads_and_writes_on_connections_of_its_own(tmp_path: Path, opened):
    """A context copied into another thread (a worker, `asyncio.to_thread`) carries the read scope with it, but a SQLite
    connection belongs to the thread that opened it: that thread never reads on the scope's, nor closes it."""
    store = _small_map(tmp_path)

    with read_scope():
        nodes = storage.list_proof_map_nodes(store)
        errors: list[BaseException] = []
        answers: list = []

        def work() -> None:
            try:
                answers.append(storage.list_proof_map_nodes(store))
                append_event(store, "synthetic_note", "from a worker thread")
                answers.append(get_proof_map_node(store, "a").statement)
            except BaseException as exc:  # noqa: BLE001 — reported below, on the test's thread
                errors.append(exc)

        worker = threading.Thread(target=contextvars.copy_context().run, args=(work,))
        worker.start()
        worker.join()

        assert errors == []
        assert answers == [nodes, "a"]
        assert storage.list_proof_map_nodes(store) == nodes  # the scope's own connection still serves it


def test_a_scope_inside_a_write_transaction_reads_on_one_connection_of_its_own_and_lets_it_commit(tmp_path: Path, opened):
    """proof-web holds the write lock while it reads a page (`_one_state`): the scope inside reads on one connection
    besides the transaction's, closed before the transaction commits."""
    store = _small_map(tmp_path)
    expected = _reads(store)
    opened.clear()

    with store.transaction() as conn, read_scope():
        assert _reads(store) == expected
        append_event(store, "synthetic_note", "in the transaction", conn=conn)

    assert len(opened) == 2, len(opened)
    assert [event.message for event in list_events(store)][-1] == "in the transaction"


def test_a_transaction_inside_a_scope_reads_as_it_did_without_one(tmp_path: Path, opened):
    """A scope belongs to the write transaction it was opened in, as its memos do: a transaction begun inside one
    retires its connection before taking the write lock, and its reads open their own."""
    store = _small_map(tmp_path)
    opened.clear()

    with read_scope():
        storage.list_proof_map_nodes(store)
        [(scope_conn, _)] = opened
        with store.transaction() as conn:
            with pytest.raises(sqlite3.ProgrammingError):  # retired: closed
                scope_conn.execute("SELECT 1")
            opened.clear()
            storage.list_proof_map_nodes(store)
            storage.list_proof_map_nodes(store)
            assert len(opened) == 2
            append_event(store, "synthetic_note", "in the transaction", conn=conn)
        opened.clear()
        assert [event.message for event in list_events(store)][-1] == "in the transaction"
        storage.list_proof_map_nodes(store)
        assert len(opened) == 1  # the scope's next read opened a fresh one, and the one after shared it


def test_a_read_in_a_scope_under_read_only_of_a_missing_project_is_refused(tmp_path: Path):
    missing = tmp_path / "no project here"
    store = ProjectStore(missing)

    with read_only(), read_scope():
        with pytest.raises(ProjectNotFoundError):
            storage.list_proof_map_nodes(store)

    assert not missing.exists()
