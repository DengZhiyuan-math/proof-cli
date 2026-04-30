from pathlib import Path

from proof_cli.blockers import add_blocker, list_blockers, record_failed_route, resolve_blocker
from proof_cli.domain import BlockerRecord, ProofObligation, ProjectSnapshot
from proof_cli.goals import add_goal, list_goals, set_current_theorem
from proof_cli.obligations import add_obligation, block_obligation, close_obligation, list_obligations
from proof_cli.proof_state import (
    build_snapshot,
    load_state,
    list_literature_routes,
    record_candidate_reference,
    record_supporting_reference,
    summarize_state,
)
from proof_cli.storage import ensure_project, read_latest_snapshot


def test_goals_blockers_obligations_and_snapshot(tmp_path: Path):
    store = ensure_project(tmp_path)

    add_goal(store, "prove lemma 1")
    set_current_theorem(store, "thm_1")
    record_candidate_reference(
        store,
        target_kind="goal",
        target_id="prove lemma 1",
        reference_id="ref_goal_candidate",
        reference_title="Compactness Lemma",
        notes="candidate literature route for the current goal",
    )
    record_supporting_reference(
        store,
        target_kind="goal",
        target_id="prove lemma 1",
        reference_id="ref_goal_support",
        reference_title="Supportive Estimate",
        notes="supports the same goal in the local project state",
    )
    add_obligation(
        store,
        ProofObligation(
            id="obl_1",
            goal_statement="show lemma 1",
            source_step_id="step_1",
            required_for="thm_1",
        ),
        candidate_reference_ids=["ref_goal_candidate"],
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_1",
            scope="thm_1",
            description="missing compactness argument",
            failure_type="missing_lemma",
        ),
        candidate_reference_ids=["ref_goal_candidate"],
    )
    record_failed_route(
        store,
        "try direct expansion",
        target_kind="blocker",
        target_id="blk_1",
        reference_id="ref_goal_candidate",
        reference_title="Compactness Lemma",
        notes="assumption mismatch during grounding",
    )

    state = load_state(store)
    assert state.current_theorem == "thm_1"
    assert "prove lemma 1" in list_goals(store)
    assert list_obligations(store)[0].dependencies == ["candidate_ref:ref_goal_candidate"]
    assert list_blockers(store)[0].related_contracts == ["candidate_ref:ref_goal_candidate"]
    assert "try direct expansion" in state.failed_routes[0]
    routes = list_literature_routes(store, target_id="prove lemma 1")
    assert {route.outcome for route in routes} == {"candidate", "supporting"}
    assert any(route.reference_id == "ref_goal_candidate" for route in routes)

    snapshot = build_snapshot(store, handoff_note="continue from lemma 1")
    assert snapshot.active_theorem == "thm_1"
    assert "obl_1" in snapshot.open_obligations
    assert any("Compactness Lemma" in route for route in snapshot.next_promising_routes)
    assert snapshot.latest_diagnostic_report is not None
    assert snapshot.latest_diagnostic_report["current_theorem"] == "thm_1"
    assert snapshot.latest_diagnostic_report["promising_next_steps"]
    assert read_latest_snapshot(store).handoff_note == "continue from lemma 1"

    summary = summarize_state(store)
    assert summary["current_theorem"] == "thm_1"
    assert "literature_routes" in summary
    assert any(route["reference_id"] == "ref_goal_support" for route in summary["literature_routes"])
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


def test_blocking_and_resolving_carry_literature_routes(tmp_path: Path):
    store = ensure_project(tmp_path)

    add_obligation(
        store,
        ProofObligation(
            id="obl_3",
            goal_statement="prove auxiliary estimate",
            required_for="thm_3",
        ),
        failed_reference_ids=["ref_gap"],
        route_notes="grounding gap from literature search",
    )
    blocked = block_obligation(
        store,
        "obl_3",
        "assumption mismatch",
        failed_reference_ids=["ref_gap"],
        route_notes="candidate paper route does not satisfy the theorem assumptions",
    )
    assert blocked.status.value == "blocked"
    assert "failed_ref:ref_gap" in blocked.dependencies
    assert "route_note:candidate paper route does not satisfy the theorem assumptions" in blocked.dependencies
    assert "assumption mismatch" in blocked.blocking_reason

    add_blocker(
        store,
        BlockerRecord(
            id="blk_2",
            scope="thm_3",
            description="needs imported result",
            failure_type="missing_route",
        ),
        failed_reference_ids=["ref_gap"],
        route_notes="no supporting paper result yet",
    )
    record_failed_route(
        store,
        "paper route failed",
        target_kind="blocker",
        target_id="blk_2",
        reference_id="ref_gap",
        reference_title="Auxiliary Estimate",
        notes="failed assumption match",
    )

    resolved = resolve_blocker(
        store,
        "blk_2",
        rationale="support found",
        supporting_reference_ids=["ref_support"],
        route_notes="standard result now covers the blocker",
    )
    assert resolved.status.value == "resolved"
    assert "supporting_ref:ref_support" in resolved.related_contracts
    assert any(step.startswith("route_note:") for step in resolved.related_steps)
    assert "literature: standard result now covers the blocker" in resolved.description

    routes = list_literature_routes(store, target_id="blk_2")
    assert any(route.outcome == "failed" for route in routes)
    assert any(route.outcome == "supporting" for route in list_literature_routes(store, target_id="blk_2", outcome="supporting"))
