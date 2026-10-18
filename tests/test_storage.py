import gc
import sqlite3
from pathlib import Path

import pytest

from proof_cli import proof_map
from proof_cli.domain import TheoremContract, TheoremStatus, TrustLevel
from proof_cli.storage import (
    append_event,
    ensure_project,
    get_contract,
    list_contracts,
    read_latest_snapshot,
    read_state,
    store_contract,
    store_snapshot,
    store_state,
)
from proof_cli.domain import ProjectSnapshot, ProjectState


def test_project_create_and_reopen(tmp_path: Path):
    store = ensure_project(tmp_path)
    state = read_state(store)
    assert state.project_id == "proj_alpha"

    store_state(
        store,
        ProjectState(
            project_id="proj_alpha",
            current_theorem="thm_1",
            open_goals=["prove lemma"],
        ),
    )

    reopened = ensure_project(tmp_path)
    reopened_state = read_state(reopened)
    assert reopened_state.current_theorem == "thm_1"
    assert reopened_state.open_goals == ["prove lemma"]


def test_contract_versioning_and_lookup(tmp_path: Path):
    store = ensure_project(tmp_path)
    contract = TheoremContract(
        id="thm_1",
        name="Main Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    stored = store_contract(store, contract)
    assert stored.version == 1

    fetched = get_contract(store, "thm_1")
    assert fetched is not None
    assert fetched.name == "Main Result"
    assert list_contracts(store)[0].id == "thm_1"


def test_snapshot_and_event_log(tmp_path: Path):
    store = ensure_project(tmp_path)
    snapshot = ProjectSnapshot(
        project_id="proj_alpha",
        active_theorem="thm_1",
        current_goals=["g1"],
        open_obligations=["obl_1"],
        active_blockers=["blk_1"],
        unresolved_trust_sensitive_calls=["thm_2"],
        next_promising_routes=["try lemma"],
        handoff_note="resume here",
    )
    store_snapshot(store, snapshot)
    assert read_latest_snapshot(store).handoff_note == "resume here"

    event = append_event(store, "state_changed", "updated proof state", entity_id="proj_alpha")
    assert event.kind == "state_changed"


def _open_connections() -> int:
    open_ = 0
    for obj in gc.get_objects():
        if isinstance(obj, sqlite3.Connection):
            try:
                obj.in_transaction
            except sqlite3.ProgrammingError:  # closed
                continue
            open_ += 1
    return open_


def test_a_connection_is_closed_when_its_with_block_ends(tmp_path: Path):
    """sqlite3's own `with` only commits or rolls back. From Python 3.11 a connection and its statement cache refer to
    each other, so one left open waits for the cyclic garbage collector, holding its file descriptors until then."""
    store = ensure_project(tmp_path)
    with store.connect() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_reads_and_writes_leave_no_connection_for_the_garbage_collector_to_close(tmp_path: Path):
    """A long-running server reads the project many times a minute: connections left to the garbage collector pile up
    until it runs, enough of them to reach the default limit of 256 open files on macOS."""
    store = ensure_project(tmp_path)
    gc.collect()
    before = _open_connections()
    gc.disable()
    try:
        proof_map.create_node(store, node_id="A", kind="claim", statement="A holds")
        proof_map.create_node(store, node_id="T", kind="theorem", statement="T holds", dependencies=["A"])
        proof_map.list_nodes(store)
        proof_map.get_node(store, "T")
        proof_map.get_workflow_state(store, "T")
        read_state(store)
        assert _open_connections() == before
    finally:
        gc.enable()
