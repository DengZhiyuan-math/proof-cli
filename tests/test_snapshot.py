from pathlib import Path

from proof_cli.blockers import add_blocker
from proof_cli.domain import BlockerRecord
from proof_cli.memory import (
    failed_routes,
    load_memory,
    procedural_tactics,
    record_memory,
    stable_memory,
)
from proof_cli.goals import add_goal, set_current_theorem
from proof_cli.proof_state import note_unresolved_trust_call
from proof_cli.snapshot import create_snapshot, restore_snapshot
from proof_cli.storage import ensure_project


def test_memory_artifacts_are_typed_and_retrievable(tmp_path: Path):
    store = ensure_project(tmp_path)
    set_current_theorem(store, "thm_1")

    record_memory(
        store,
        "working",
        "open theorem 1",
        theorem_id="thm_1",
        goal_id="goal_1",
        importance="high",
        tags=["active"],
    )
    record_memory(
        store,
        "semantic",
        "compactness lemma is reusable",
        theorem_id="thm_1",
        importance="critical",
        tags=["stable"],
    )
    record_memory(
        store,
        "episodic",
        "failed direct proof by contradiction",
        theorem_id="thm_1",
        route_id="route_1",
        importance="low",
    )
    record_memory(
        store,
        "procedural",
        "check assumptions before applying a theorem",
        theorem_id="thm_1",
        importance="medium",
    )

    memory = load_memory(store)

    assert memory.project_id == "proj_alpha"
    assert memory.working[0].content == "open theorem 1"
    assert memory.working[0].scope.theorem_id == "thm_1"
    assert memory.semantic[0].importance.value == "critical"
    assert [artifact.content for artifact in stable_memory(store)] == ["compactness lemma is reusable"]
    assert [artifact.content for artifact in failed_routes(store)] == ["failed direct proof by contradiction"]
    assert [artifact.content for artifact in procedural_tactics(store)] == [
        "check assumptions before applying a theorem"
    ]


def test_snapshot_restore_preserves_memory_context_blockers_and_debts(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_goal(store, "prove theorem 1")
    set_current_theorem(store, "thm_1")
    note_unresolved_trust_call(store, "thm_1")
    add_blocker(
        store,
        BlockerRecord(
            id="blk_1",
            scope="thm_1",
            description="missing lemma",
            failure_type="missing_lemma",
        ),
    )

    record_memory(store, "working", "open theorem 1", theorem_id="thm_1")
    record_memory(store, "semantic", "lemma 1 is reusable", theorem_id="thm_1", importance="high")
    record_memory(store, "episodic", "failed direct proof once", theorem_id="thm_1", route_id="route_1")
    record_memory(store, "procedural", "check assumptions before apply", theorem_id="thm_1")

    snapshot = create_snapshot(store, note="handoff for later")
    restored = restore_snapshot(store)
    memory = load_memory(store)

    assert snapshot.handoff_note == "handoff for later"
    assert restored is not None
    assert restored.project_snapshot.active_theorem == "thm_1"
    assert "prove theorem 1" in restored.project_snapshot.current_goals
    assert restored.working_context == ["open theorem 1"]
    assert restored.failed_routes == ["failed direct proof once"]
    assert restored.procedural_tactics == ["check assumptions before apply"]
    assert restored.blocker_ids == ["blk_1"]
    assert restored.unresolved_debts == ["thm_1"]
    assert memory.handoff_snapshots[-1].handoff_note == "handoff for later"
    assert memory.handoff_snapshots[-1].working_context == ["open theorem 1"]
