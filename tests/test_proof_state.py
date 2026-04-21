from pathlib import Path

from proof_cli.blockers import add_blocker, list_blockers, record_failed_route
from proof_cli.domain import BlockerRecord, ProofObligation, ProjectSnapshot
from proof_cli.goals import add_goal, list_goals, set_current_theorem
from proof_cli.obligations import add_obligation, close_obligation, list_obligations
from proof_cli.proof_state import build_snapshot, load_state, summarize_state
from proof_cli.storage import ensure_project, read_latest_snapshot


def test_goals_blockers_obligations_and_snapshot(tmp_path: Path):
    store = ensure_project(tmp_path)

    add_goal(store, "prove lemma 1")
    set_current_theorem(store, "thm_1")
    add_obligation(
        store,
        ProofObligation(
            id="obl_1",
            goal_statement="show lemma 1",
            source_step_id="step_1",
            required_for="thm_1",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_1",
            scope="thm_1",
            description="missing compactness argument",
            failure_type="missing_lemma",
        ),
    )
    record_failed_route(store, "try direct expansion")

    state = load_state(store)
    assert state.current_theorem == "thm_1"
    assert "prove lemma 1" in list_goals(store)
    assert list_obligations(store)[0].id == "obl_1"
    assert list_blockers(store)[0].id == "blk_1"
    assert state.failed_routes == ["try direct expansion"]

    snapshot = build_snapshot(store, handoff_note="continue from lemma 1")
    assert snapshot.active_theorem == "thm_1"
    assert "obl_1" in snapshot.open_obligations
    assert read_latest_snapshot(store).handoff_note == "continue from lemma 1"

    summary = summarize_state(store)
    assert summary["current_theorem"] == "thm_1"
    assert summary["latest_snapshot"] is not None


def test_closing_obligation_updates_open_queue(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_obligation(
        store,
        ProofObligation(
            id="obl_2",
            goal_statement="close step",
            required_for="thm_2",
        ),
    )
    closed = close_obligation(store, "obl_2", rationale="proved explicitly")
    assert closed.status.value == "closed"
    assert "obl_2" not in load_state(store).open_obligations
