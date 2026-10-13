"""Scope checks for proof-agents ef7db62. Synthetic maps and runs only."""
import sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path[:0] = [str(HERE / "src"), str(HERE / "tests")]
from test_coordinator import World, FakeRun, _until
from proof_agents.coordinator import ProjectPursuit, PursuitHooks

def test_global_budget_boundary_still_records_exhausted_nodes_as_parked():
    world = World(edges={"T": []}, budget=(1, 60.0), parallel=1)
    coordinator = world.coordinator()
    coordinator.start("claude")
    try:
        _until(lambda: world.runs["T"].starts == 1, "Decomposer started")
        world.edges = {"T": ["A"], "A": []}
        world.runs["A"] = FakeRun()
        world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A; the Coordinator works them")
        world.runs["T"].claim = None
        _until(lambda: world.runs["A"].starts == 1, "Claim started")
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not coordinator.active(), "Coordinator finished")
        assert any(entry["node"] == "A" for entry in coordinator.view()["parked"]), coordinator.view()
        assert any(node == "A" for node, reason in world.parked)
    finally:
        coordinator.release()


def test_project_pursuit_releases_the_parked_claim_after_the_total_budget():
    world = World(edges={"T": []}, budget=(1, 60.0), parallel=1)
    coordinator = world.coordinator()
    pursuit = ProjectPursuit(PursuitHooks(
        theorems=lambda: ["T"], coordinator=lambda _: coordinator,
        read=lambda _: {}, record=lambda _: None), tick=0.01)
    pursuit.start("claude")
    try:
        _until(lambda: world.runs["T"].starts == 1, "Decomposer started")
        world.edges = {"T": ["A"], "A": []}
        world.runs["A"] = FakeRun()
        world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A; the Coordinator works them")
        world.runs["T"].claim = None
        _until(lambda: world.runs["A"].starts == 1, "Claim started")
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not pursuit.active(), "Project Pursue ended")
        assert pursuit.view()["results"]["T"]["status"] == "budget"
        assert coordinator.view()["status"] == "released"
        assert any(entry["node"] == "A" for entry in coordinator.view()["parked"])
        assert any(node == "A" for node, _ in world.parked)
        assert world.runs["A"].claim is None
    finally:
        coordinator.release()


def test_known_limit_a_late_ending_is_not_collected_by_the_finished_coordinator():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(1, 60.0))
    coordinator = world.coordinator()
    coordinator.start("claude")
    try:
        _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
        world.runs["B"].turns = 2
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not coordinator.active(), "Coordinator ended")
        world.runs["B"].end("budget", turns=2, reason="late ending")
        view = coordinator.view()
        assert [entry["node"] for entry in view["parked"]] == ["A"]
        assert view["nodes"]["B"]["last"] is None
        assert [node for node, _ in world.parked] == ["A"]
        assert world.runs["B"].claim is not None
        assert not any(note.startswith("the run on B ended:") for note in world.notes)
        assert coordinator.release()["status"] == "released"
        assert world.runs["B"].claim is None
        assert [entry["node"] for entry in coordinator.view()["parked"]] == ["A"]
    finally:
        coordinator.release()
