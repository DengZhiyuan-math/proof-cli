from pathlib import Path

from proof_cli.memory import record_memory, load_memory
from proof_cli.snapshot import create_snapshot, restore_snapshot
from proof_cli.goals import add_goal
from proof_cli.storage import ensure_project


def test_snapshot_restore_and_memory_layers(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_goal(store, "prove theorem 1")
    record_memory(store, "working", "open theorem 1")
    record_memory(store, "semantic", "theorem 1 depends on lemma 1")
    record_memory(store, "episodic", "failed direct proof once")
    record_memory(store, "procedural", "check assumptions before apply")

    snapshot = create_snapshot(store, note="handoff for later")
    restored = restore_snapshot(store)
    memory = load_memory(store)

    assert snapshot.handoff_note == "handoff for later"
    assert restored is not None
    assert restored.active_theorem == snapshot.active_theorem
    assert "prove theorem 1" in snapshot.current_goals
    assert memory.working == ["open theorem 1"]
    assert memory.semantic == ["theorem 1 depends on lemma 1"]
    assert memory.episodic == ["failed direct proof once"]
    assert memory.procedural == ["check assumptions before apply"]
