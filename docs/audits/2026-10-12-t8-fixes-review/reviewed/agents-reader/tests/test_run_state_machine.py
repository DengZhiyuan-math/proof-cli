"""The run's state machine on its own (spec #145): a fake agent whose turns never start, and hooks that
assign and release the node. What the run promises whatever the studio does: one Start at a time, a Stop
during `starting` is final, an assignment coming back late gives nothing back that a later Start holds,
and a Start waits while the previous run is still giving the node back. The runs that work a node through
the studio's agent live in proof-web's tests (test_agent_run.py)."""

import os
import threading
import time
from pathlib import Path

import pytest

from proof_cli.proof_map import create_node, get_active_claim
from proof_cli.storage import ensure_project
from proof_agents.agent_run import AgentRun


WAIT = 30.0  # seconds: how long a test waits for a subprocess (the stub CLI, a `proof` call) to do what it should  # seconds a wait may take: a `proof` start-up is slow in a sandbox


def _hooks(**given):
    """A run's hooks for the tests that drive AgentRun alone: what is not given does nothing."""
    from dataclasses import fields

    from proof_agents.agent_run import RunHooks

    base = dict(agent_name=lambda provider: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: None,
                release=lambda name, reason: None, work_log=lambda: [], record_close=lambda *a: None)
    names = {f.name for f in fields(RunHooks)}
    return RunHooks(**{key: value for key, value in {**base, **given}.items() if key in names})


def _until(ready, what, timeout=WAIT, every=0.05):
    """Poll `ready()` until it is true; after `timeout` seconds fail, naming `what` (a string, or a callable that says
    what is missing at that moment). Never a fixed sleep: a `proof` start-up takes seconds in a slow sandbox."""
    deadline = time.monotonic() + timeout
    while True:
        value = ready()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"waited {timeout:g}s for {what() if callable(what) else what}")
        time.sleep(every)


def test_a_second_start_while_the_first_is_still_being_assigned_is_refused():
    import threading

    from proof_agents.agent_run import AgentRun

    gate = threading.Event()
    assigned = []

    class Agent:  # never reached: the assignment blocks
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The studio is closed."}

        def stop(self, jid):
            pass

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: (gate.wait(5), assigned.append(name)),
                    release=lambda name, reason: None, work_log=lambda: [], record_close=lambda *a: None)
    hooks = _hooks(**hooks_kw)
    run = AgentRun(Agent(), hooks)
    first = {}
    worker = threading.Thread(target=lambda: first.update(run.start("claude")))
    worker.start()
    _until(lambda: run.view()["status"] == "starting", "the first Start to be assigning the node")
    second = run.start("claude")  # while the first is still assigning
    gate.set()
    worker.join(5)
    assert second.get("code") == "RUN_ACTIVE" and assigned == ["claude-code"]  # one slot, one assignment
    run.release()


def test_stop_and_release_while_the_node_is_still_being_assigned_holds():
    """Reaudit R-P2: Stop during `starting` is final — when the assignment comes back, no coordinator starts, and the
    assignment it made is given back."""
    import threading

    from proof_agents.agent_run import AgentRun

    gate = threading.Event()
    assigned, released, started = [], [], []

    class Agent:
        jobs = {}

        def start(self, *args, **kwargs):
            started.append(args)
            return {"error": "The studio is closed."}

        def stop(self, jid):
            pass

    hooks_kw = dict(agent_name=lambda p: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: (gate.wait(5), assigned.append(name)),
                    release=lambda name, reason: released.append(name), work_log=lambda: [], record_close=lambda *a: None)
    run = AgentRun(Agent(), _hooks(**hooks_kw))
    first = {}
    worker = threading.Thread(target=lambda: first.update(run.start("claude")))
    worker.start()
    _until(lambda: run.view()["status"] == "starting", "the first Start to be assigning the node")
    stopped = run.release()
    assert stopped["status"] == "released"
    gate.set()
    worker.join(WAIT)
    assert not worker.is_alive(), "the first Start never came back from its assignment"
    _until(lambda: released == ["claude-code"] and run.view()["status"] == "released",
           lambda: f"the late assignment to be given back (released={released}, status={run.view()['status']})")
    assert first["status"] == "released" and run.view()["status"] == "released"
    assert assigned == ["claude-code"] and released == ["claude-code"]  # the assignment it had made is given back
    assert started == [] and not run.active()  # and no turn ever started


def test_an_old_starts_assignment_coming_back_late_does_not_release_the_new_runs_claim():
    """Third review T-P2: the first Start is stopped while its assignment is still pending; a second Start under the
    same name claims the node; when the first assignment comes back, it must not give back what the second holds."""
    import threading
    from proof_cli.proof_map import release_node
    from proof_agents.agent_run import AgentRun

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

    def release(name, reason=None):
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
                    work_log=lambda: [], record_close=lambda *a: None)
    run = AgentRun(Agent(), _hooks(**hooks_kw))
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
    from proof_cli.proof_map import claim_node, release_node
    from proof_agents.agent_run import AgentRun

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

    def release(name, reason=None):
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
                    work_log=lambda: [], record_close=lambda *a: None)
    run = AgentRun(Agent(), _hooks(**hooks_kw))
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
    from proof_cli.proof_map import claim_node, release_node
    from proof_agents.agent_run import AgentRun

    store = ensure_project(Path(os.environ.get("TMPDIR", "/tmp")) / f"proof-settle-{os.getpid()}-{time.time_ns()}")
    create_node(store, node_id="N", kind="claim", statement="a claim")
    releasing, gate = threading.Event(), threading.Event()

    def release(name, reason=None):
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
                    release=release, work_log=lambda: [], record_close=lambda *a: None)
    run = AgentRun(Agent(), _hooks(**hooks_kw))
    run.start("claude")
    _until(lambda: run.view()["status"] == "stuck", "the run to end stuck")
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

    from proof_cli.proof_map import claim_node, release_node

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

    def release(name, reason="released"):
        claim = get_active_claim(store, "N")
        if claim is not None and claim.claimant_id == name:
            release_node(store, "N", claimant_id=name, reason=reason)

    def review_now():  # as the project's request-review does: the snapshot is frozen and the node handed over
        release("claude-code")
        return {"version": 1}

    class Agent:
        jobs = {}

        def start(self, *args, **kwargs):
            return {"error": "The agent is still working on the previous message.", "code": "AGENT_BUSY"}  # never a turn: the run waits

        def stop(self, jid):
            pass

    run = AgentRun(Agent(), _hooks(assign=assign, release=release, review_now=review_now))
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


# -- a turn that fails (#171): the CLI exits non-zero or reports an error ---------------------------------------------


class _Job:
    """A finished turn, as the agent manager leaves it: its events hold the `done` event the backend's result became."""

    def __init__(self, jid, result, events=()):
        self.id, self.done, self.cond = jid, True, threading.Condition()
        self.events = [*events, {"t": "done", "turn": jid, "changed": [], **result}]
        self.before = self.after = {}


class _AgentWhoseTurnsEnd:
    """An agent whose every turn is over at once with the given result (no CLI runs)."""

    def __init__(self, result, events=()):
        self.result, self.events, self.jobs, self.started = result, events, {}, []

    def start(self, prompt, session, mode, model, effort, scope, provider, unless=None, turn=None, begin=None):
        self.started.append({"provider": provider, "role": (turn or {}).get("role")})
        job = _Job(len(self.jobs) + 1, self.result, self.events)
        self.jobs[job.id] = job
        if begin is not None:
            begin(job)
        return {"job": job.id}

    def stop(self, jid):
        pass


@pytest.mark.parametrize("result", [{"exit": 1, "is_error": True, "stderr": "The model gpt-6-sol is not available to your account.\n"},
                                    {"exit": 2}, {"exit": 0, "is_error": True, "subtype": "error_during_execution"}])
def test_a_turn_the_cli_could_not_finish_ends_a_single_role_run_as_stuck_with_the_reason(result):
    agent = _AgentWhoseTurnsEnd(result)
    run = AgentRun(agent, _hooks())
    assert run.start("codex", roles=["typesetter"])["status"] in ("starting", "running", "stuck")
    _until(lambda: not run.active(), lambda: f"the run is still {run.view()['status']}")
    view = run.view()
    assert view["status"] == "stuck", view
    assert view["reason"].startswith("the typesetter turn failed: ") and (
        "not available to your account" in view["reason"] or "exit 2" in view["reason"] or "error_during_execution" in view["reason"]), view["reason"]
    assert agent.started == [{"provider": "codex", "role": "typesetter"}]


@pytest.mark.parametrize("events, expected", [
    ([{"t": "init", "session_id": "s"}, {"t": "text", "text": "Not logged in · Please run /login"}], "Not logged in · Please run /login"),
    ([{"t": "text", "text": "Working on it."}, {"t": "error", "message": "Codex error: the stream was closed"}], "Codex error: the stream was closed"),
    ([{"t": "text", "text": "   "}], "success"),  # nothing said: the subtype, as before
])
def test_a_failed_turn_with_no_stderr_says_what_the_cli_last_said_not_its_subtype(events, expected):
    """#179: Claude's result for a lapsed login is is_error, subtype "success", exit 1, no stderr; the reason is in the text."""
    run = AgentRun(_AgentWhoseTurnsEnd({"exit": 1, "is_error": True, "subtype": "success", "stderr": ""}, events), _hooks())
    run.start("claude", roles=["prover"])
    _until(lambda: not run.active(), lambda: f"the run is still {run.view()['status']}")
    assert (run.view()["status"], run.view()["reason"]) == ("stuck", f"the prover turn failed: {expected}")


def test_a_host_reads_the_same_reason_for_its_own_turn():
    """A host's own turn, such as proof-web's Reader, names the lapsed login too, not the subtype "success"."""
    from proof_agents.agent_run import failure_reason
    done = {"t": "done", "exit": 1, "is_error": True, "subtype": "success", "stderr": ""}
    events = [{"t": "init", "model": "claude-opus-5-5"}, {"t": "text", "text": "Not logged in · Please run /login"}, done]
    assert failure_reason(done, events) == "Not logged in · Please run /login"


def test_stderr_still_comes_before_what_the_cli_said():
    agent = _AgentWhoseTurnsEnd({"exit": 1, "is_error": True, "subtype": "success", "stderr": "boom\nfatal: the real cause\n"},
                                [{"t": "text", "text": "Not logged in"}])
    run = AgentRun(agent, _hooks())
    run.start("claude", roles=["prover"])
    _until(lambda: not run.active(), lambda: f"the run is still {run.view()['status']}")
    assert run.view()["reason"] == "the prover turn failed: fatal: the real cause"


def test_a_turn_that_ends_cleanly_lets_a_single_role_run_read_done():
    run = AgentRun(_AgentWhoseTurnsEnd({"exit": 0}), _hooks())
    run.start("claude", roles=["typesetter"])
    _until(lambda: not run.active(), lambda: f"the run is still {run.view()['status']}")
    assert (run.view()["status"], run.view()["reason"]) == ("done", "turn-finished")
