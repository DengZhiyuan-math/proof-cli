"""The run's state machine on its own (spec #145): a fake agent whose turns never start, and hooks that
assign and release the node. What the run promises whatever the studio does: one Start at a time, a Stop
during `starting` is final, an assignment coming back late gives nothing back that a later Start holds,
and a Start waits while the previous run is still giving the node back. The runs that work a node through
the studio's agent live in proof-web's tests (test_agent_run.py)."""

import os
import time
from pathlib import Path

from proof_cli.proof_map import create_node, get_active_claim
from proof_cli.storage import ensure_project


def test_a_second_start_while_the_first_is_still_being_assigned_is_refused():
    import threading

    from proof_agents.agent_run import AgentRun, RunHooks

    gate = threading.Event()
    assigned = []

    class Agent:  # never reached: the assignment blocks
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The studio is closed."}

        def stop(self, jid):
            pass

    from dataclasses import fields

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: (gate.wait(5), assigned.append(name)),
                    release=lambda name: None, work_log=lambda: [], record_stuck=lambda *a: None, review_now=lambda: {})
    hooks = RunHooks(**{f.name: hooks_kw[f.name] for f in fields(RunHooks)})  # only the hooks this version of the run takes
    run = AgentRun(Agent(), hooks)
    first = {}
    worker = threading.Thread(target=lambda: first.update(run.start("claude")))
    worker.start()
    time.sleep(0.2)
    second = run.start("claude")  # while the first is still assigning
    gate.set()
    worker.join(5)
    assert second.get("error") == "RUN_ACTIVE" and assigned == ["claude-code"]  # one slot, one assignment
    run.release()


def test_stop_and_release_while_the_node_is_still_being_assigned_holds():
    """Reaudit R-P2: Stop during `starting` is final — when the assignment comes back, no coordinator starts, and the
    assignment it made is given back."""
    import threading

    from proof_agents.agent_run import AgentRun, RunHooks

    gate = threading.Event()
    assigned, released, started = [], [], []

    class Agent:
        jobs = {}

        def start(self, *args, **kwargs):
            started.append(args)
            return {"error": "The studio is closed."}

        def stop(self, jid):
            pass

    from dataclasses import fields

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: (gate.wait(5), assigned.append(name)),
                    release=released.append, work_log=lambda: [], record_stuck=lambda *a: None, review_now=lambda: {})
    run = AgentRun(Agent(), RunHooks(**{f.name: hooks_kw[f.name] for f in fields(RunHooks)}))
    first = {}
    worker = threading.Thread(target=lambda: first.update(run.start("claude")))
    worker.start()
    time.sleep(0.2)
    stopped = run.release()
    assert stopped["status"] == "released"
    gate.set()
    worker.join(5)
    time.sleep(0.2)
    assert first["status"] == "released" and run.view()["status"] == "released"
    assert assigned == ["claude-code"] and released == ["claude-code"]  # the assignment it had made is given back
    assert started == [] and not run.active()  # and no turn ever started


def test_an_old_starts_assignment_coming_back_late_does_not_release_the_new_runs_claim():
    """Third review T-P2: the first Start is stopped while its assignment is still pending; a second Start under the
    same name claims the node; when the first assignment comes back, it must not give back what the second holds."""
    import threading
    from dataclasses import fields

    from proof_cli.proof_map import release_node
    from proof_agents.agent_run import AgentRun, RunHooks

    store = ensure_project(Path(os.environ.get("TMPDIR", "/tmp")) / f"proof-late-assignment-{os.getpid()}-{time.time_ns()}")
    create_node(store, node_id="N", kind="claim", statement="a claim")
    entered, gate = threading.Event(), threading.Event()
    calls: list[str] = []

    def assign(name):
        calls.append(name)
        if len(calls) == 1:
            entered.set()
            assert gate.wait(5)
        from proof_cli.proof_map import claim_node
        claim_node(store, "N", claimant_id=name)

    def release(name):
        claim = get_active_claim(store, "N")
        if claim is not None and claim.claimant_id == name:
            release_node(store, "N", claimant_id=name)

    class Agent:  # a turn that cannot start: the second run ends stuck at once, keeping its claim
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The studio is closed."}

        def stop(self, jid):
            pass

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=assign, release=release,
                    work_log=lambda: [], record_stuck=lambda *a: None, review_now=lambda: {})
    run = AgentRun(Agent(), RunHooks(**{f.name: hooks_kw[f.name] for f in fields(RunHooks)}))
    first = threading.Thread(target=lambda: run.start("claude"))
    first.start()
    assert entered.wait(5)
    assert run.release()["status"] == "released"
    second = run.start("claude", roles=["numerics"])
    assert second["status"] in ("running", "stuck") and get_active_claim(store, "N").claimant_id == "claude-code"  # the second holds the node
    gate.set()
    first.join(5)
    time.sleep(0.3)
    assert get_active_claim(store, "N").claimant_id == "claude-code"  # the late assignment gave nothing back
    assert run.view()["status"] in ("running", "stuck")  # the second run, untouched by the first's end
    run.release()
    assert get_active_claim(store, "N") is None


def test_a_late_assignment_after_the_next_run_was_also_stopped_leaves_no_claim():
    """Fourth review F2: the first Start's assignment is pending; Stop; a second Start claims and is stopped too (claim
    gone); then the first assignment comes back and claims again — nothing holds the node, so it is given back."""
    import threading
    from dataclasses import fields

    from proof_cli.proof_map import claim_node, release_node
    from proof_agents.agent_run import AgentRun, RunHooks

    store = ensure_project(Path(os.environ.get("TMPDIR", "/tmp")) / f"proof-double-stop-{os.getpid()}-{time.time_ns()}")
    create_node(store, node_id="N", kind="claim", statement="a claim")
    entered, gate = threading.Event(), threading.Event()
    calls: list[str] = []

    def assign(name):
        calls.append(name)
        if len(calls) == 1:
            entered.set()
            assert gate.wait(5)
        claim_node(store, "N", claimant_id=name)

    def release(name):
        claim = get_active_claim(store, "N")
        if claim is not None and claim.claimant_id == name:
            release_node(store, "N", claimant_id=name)

    class Agent:
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The studio is closed."}

        def stop(self, jid):
            pass

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=assign, release=release,
                    work_log=lambda: [], record_stuck=lambda *a: None, review_now=lambda: {})
    run = AgentRun(Agent(), RunHooks(**{f.name: hooks_kw[f.name] for f in fields(RunHooks)}))
    first = threading.Thread(target=lambda: run.start("claude"))
    first.start()
    assert entered.wait(5)
    run.release()
    run.start("claude", roles=["numerics"])
    assert get_active_claim(store, "N").claimant_id == "claude-code"
    run.release()  # the second run too
    assert get_active_claim(store, "N") is None
    gate.set()
    first.join(5)
    assert get_active_claim(store, "N") is None  # the late assignment's claim was given back
    assert run.view()["status"] == "released"


def test_a_start_waits_while_the_previous_run_is_still_giving_the_node_back():
    """Sixth review: the decision to give the node back was made under the lock and the release done outside it; a
    Start arriving in between claimed the node (the same name) and then lost that claim to the release. A Start now
    waits for a release in progress, and keeps the claim it makes."""
    import threading
    from dataclasses import fields

    from proof_cli.proof_map import claim_node, release_node
    from proof_agents.agent_run import AgentRun, RunHooks

    store = ensure_project(Path(os.environ.get("TMPDIR", "/tmp")) / f"proof-settle-{os.getpid()}-{time.time_ns()}")
    create_node(store, node_id="N", kind="claim", statement="a claim")
    releasing, gate = threading.Event(), threading.Event()

    def release(name):
        releasing.set()
        assert gate.wait(5)  # the release takes its time: the window the next Start used to slip through
        claim = get_active_claim(store, "N")
        if claim is not None and claim.claimant_id == name:
            release_node(store, "N", claimant_id=name)

    class Agent:
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The studio is closed."}  # every run ends stuck at once, keeping its claim

        def stop(self, jid):
            pass

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: claim_node(store, "N", claimant_id=name),
                    release=release, work_log=lambda: [], record_stuck=lambda *a: None, review_now=lambda: {})
    run = AgentRun(Agent(), RunHooks(**{f.name: hooks_kw[f.name] for f in fields(RunHooks)}))
    run.start("claude")
    deadline = time.monotonic() + 5
    while run.view()["status"] != "stuck" and time.monotonic() < deadline:
        time.sleep(0.01)
    stopper = threading.Thread(target=run.release)
    stopper.start()
    assert releasing.wait(5)
    started: dict = {}
    second = threading.Thread(target=lambda: started.update(run.start("claude")))
    second.start()
    time.sleep(0.3)
    assert not started, "the Start waits while the node is being given back"
    gate.set()
    stopper.join(5)
    second.join(5)
    assert started and started["status"] in ("starting", "running", "stuck")  # it began after the release
    assert get_active_claim(store, "N").claimant_id == "claude-code"  # and its claim is intact
    run.release()
    assert get_active_claim(store, "N") is None


def test_a_late_assignment_after_the_next_run_requested_review_leaves_no_claim():
    """Fifth review: the first Start's assignment is pending; Stop; a second Start claims and Review what it has hands
    the node over (claim released); then the first assignment comes back and claims again — given back."""
    import threading
    from dataclasses import fields

    from proof_cli.proof_map import claim_node, release_node
    from proof_agents.agent_run import AgentRun, RunHooks

    store = ensure_project(Path(os.environ.get("TMPDIR", "/tmp")) / f"proof-late-review-{os.getpid()}-{time.time_ns()}")
    create_node(store, node_id="N", kind="claim", statement="a claim")
    entered, gate = threading.Event(), threading.Event()
    calls: list[str] = []

    def assign(name):
        calls.append(name)
        if len(calls) == 1:
            entered.set()
            assert gate.wait(5)
        claim_node(store, "N", claimant_id=name)

    def release(name):
        claim = get_active_claim(store, "N")
        if claim is not None and claim.claimant_id == name:
            release_node(store, "N", claimant_id=name)

    def review_now():  # as the project's request-review does: the snapshot is frozen and the node handed over
        release("claude-code")
        return {"version": 1}

    class Agent:
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The agent is still working on the previous message."}  # never a turn: the run waits

        def stop(self, jid):
            pass

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=assign, release=release,
                    work_log=lambda: [], record_stuck=lambda *a: None, review_now=review_now)
    run = AgentRun(Agent(), RunHooks(**{f.name: hooks_kw[f.name] for f in fields(RunHooks)}))
    first = threading.Thread(target=lambda: run.start("claude"))
    first.start()
    assert entered.wait(5)
    run.release()
    run.start("claude")
    assert get_active_claim(store, "N").claimant_id == "claude-code"
    run.review_now()
    state = run.view()
    assert (state["status"], state["reason"]) == ("done", "review-requested") and get_active_claim(store, "N") is None
    gate.set()
    first.join(5)
    assert get_active_claim(store, "N") is None  # the late assignment's claim was given back: the node was handed over
    assert (run.view()["status"], run.view()["reason"]) == ("done", "review-requested")
    run.release()
