"""Probes for proof-agents 7e742b5 (#18). Synthetic maps and runs (test_coordinator's World/FakeRun).

Run with AGENTS=<a proof-agents checkout at 7e742b5> on sys.path: src and tests.
"""
import os
import sys
import time
from pathlib import Path

AGENTS = Path(os.environ["AGENTS"])
sys.path[:0] = [str(AGENTS / "src"), str(AGENTS / "tests")]
from test_coordinator import World, FakeRun, _until  # noqa: E402
from proof_agents.coordinator import ProjectPursuit, PursuitHooks  # noqa: E402


def _split_then_claim(world):
    _until(lambda: world.runs["T"].starts == 1, "Decomposer started")
    world.edges = {"T": ["A"], "A": []}
    world.runs["A"] = FakeRun()
    world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A; the Coordinator works them")
    world.runs["T"].claim = None
    _until(lambda: world.runs["A"].starts == 1, "Claim started")


def test_1_audit_probe_split_then_one_claim_turn_total_2_parks_and_logs_the_claim():
    world = World(edges={"T": []}, budget=(1, 60.0), parallel=1)
    c = world.coordinator()
    c.start("claude")
    try:
        _split_then_claim(world)
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not c.active(), "Coordinator finished")
        view = c.view()
        print("VIEW1", view["status"], view["reason"], view["parked"], view["interrupted"], view["decomposed"], view["resplit"])
        assert [e["node"] for e in view["parked"]] == ["A"] and any(n.startswith("parked A:") for n in world.notes)
        assert world.runs["T"].starts == 1   # no re-split started past the budget
    finally:
        c.release()


def test_2_project_pursuit_releases_the_parked_claim():
    world = World(edges={"T": []}, budget=(1, 60.0), parallel=1)
    c = world.coordinator()
    p = ProjectPursuit(PursuitHooks(theorems=lambda: ["T"], coordinator=lambda _: c, read=lambda _: {}, record=lambda _: None), tick=0.01)
    p.start("claude")
    try:
        _split_then_claim(world)
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not p.active(), "Project Pursue ended")
        assert p.view()["results"]["T"]["status"] == "budget" and c.view()["status"] == "released"
        assert world.runs["A"].claim is None
    finally:
        c.release()


def test_3_a_node_running_at_the_boundary_is_not_parked_and_its_late_result_is_collected():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(1, 60.0))
    c = world.coordinator()
    c.start("claude")
    try:
        _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
        world.runs["B"].turns = 2
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: c.view()["parked"], "A parked")
        time.sleep(0.1)
        view = c.view()
        assert c.active() and [e["node"] for e in view["parked"]] == ["A"] and world.runs["B"].status == "running"
        world.runs["B"].end("budget", turns=2, reason="late ending")
        _until(lambda: not c.active(), "Coordinator ended")
        view = c.view()
        print("VIEW3", view["status"], view["parked"], view["interrupted"])
        assert sorted(e["node"] for e in view["parked"]) == ["A", "B"] and view["nodes"]["B"]["last"] == "budget"
        assert c.release()["status"] == "released" and world.runs["B"].claim is None
    finally:
        c.release()


def test_4_a_late_run_ending_with_node_budget_left_is_interrupted_not_parked():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(2, 60.0))
    c = world.coordinator()
    c.start("claude")
    try:
        _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
        world.runs["B"].turns = 1
        world.runs["A"].end("budget", turns=5, reason="out of turns")
        _until(lambda: c.view()["parked"], "A parked")
        world.runs["B"].end("stuck", turns=1, reason="the deadline came")
        _until(lambda: not c.active(), "Coordinator ended")
        view = c.view()
        print("VIEW4", view["parked"], view["interrupted"])
        assert [e["node"] for e in view["interrupted"]] == ["B"] and "B" not in [e["node"] for e in view["parked"]]
    finally:
        c.release()


def test_5_stop_while_waiting_for_the_running_runs_releases_them():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(1, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["B"].turns = 2
    world.runs["A"].end("budget", turns=1, reason="out of turns")
    _until(lambda: "end on their own" in c.view()["reason"], "waiting")
    out = c.stop() if hasattr(c, "stop") else c.release()
    view = c.view()
    print("VIEW5", view["status"], view["reason"])
    assert view["status"] == "released" and world.runs["B"].claim is None


def test_6_what_the_split_parent_reads_at_the_budgets_end():
    """Not an acceptance item: where T (its split run ended, a re-split due after A parked) stands."""
    world = World(edges={"T": []}, budget=(1, 60.0), parallel=1)
    c = world.coordinator()
    c.start("claude")
    try:
        _split_then_claim(world)
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not c.active(), "Coordinator finished")
        view = c.view()
        print("VIEW6 T entry:", view["nodes"].get("T"), "| interrupted:", view["interrupted"], "| parked:", view["parked"])
    finally:
        c.release()
