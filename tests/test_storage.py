from pathlib import Path

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
