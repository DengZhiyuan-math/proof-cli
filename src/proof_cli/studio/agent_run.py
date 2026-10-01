"""A Proof agent's run on a node (spec #145, decided in #144): Start once, then autonomous.

One run is the node's assignee under the project's agent name and works the node as three roles
in turn — Prover, Typesetter, Numerics — each a turn of the same CLI (agent.py) with its own brief,
environment and write scope (proof_agent.py). The Prover goes first and hands work over through
`proof node progress --handoff <role>`; a role hands back when it is done; the run brings the Prover
back after every delegation, telling it what the other role reported. It stops on its own when
review is requested, when a step reports stuck (or a decision only a human can make), when its
budget is spent, or when turns stop changing anything. The researcher pauses it (the turn finishes,
the assignment stays), redirects it (one line for the next turn, optionally for one role), resumes
it, or stops and releases it. Everything it learns is project state the roles wrote through
`proof`; the run itself keeps only what the page asks about: its status, its reason, which role
and turn it is on.

Each Start is its own record (`_Start`): the coordinator thread of a Start holds that record and
nothing else, so a coordinator still winding down after Stop and release can never end, count or
resume the Start that follows it. The lock guards the run's own state only; the project is read
and written outside it, as the agent manager does with its backends.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..domain import AGENT_ROLES

STUCK_TURNS = 5      # turns in a row that change nothing — no report, no file, no run, no fog — before the run stops as stuck
BUSY_WAIT = 30.0     # seconds a turn waits for the researcher's own Ask turn to end before giving up
# the turn's changes the stuck rule counts: a report, a split, a fog item, an Evidence check, a dependency edit
_CHANGES = ("plan", "step", "handoff", "split", "fog", "experiment", "evidence", "dependencies", "review-requested")


@dataclass
class RunHooks:
    """What a run needs from the project, as callables: the studio knows nothing of the proof map itself."""

    agent_name: Callable[[str], str]                 # provider -> the name the run works under
    budget: Callable[[], tuple[int, float]]           # (turns, minutes)
    assign: Callable[[str], None]                     # make the node's assignee this name (raises when another holds it)
    release: Callable[[str], None]                    # release the node when this name is its assignee
    work_log: Callable[[], list[dict]]                # the node's work log, oldest first
    record_stuck: Callable[[str, str, str], None]     # (role, name, note): the run's own last word, as a stuck step


@dataclass
class RunState:
    status: str = "idle"          # idle | starting | running | pausing | paused | released | done | stuck | budget
    reason: str = ""
    role: str | None = None
    turns: int = 0
    turns_max: int = 0
    started_at: float | None = None
    deadline: float | None = None
    name: str = ""
    provider: str = ""
    roles: list[str] = field(default_factory=list)   # a single role asked for, or every role
    redirect: dict | None = None                     # {"text", "role"} waiting for the next matching turn


@dataclass
class _Start:
    """One Start, from its assignment to its end: its state, its flags, its running turn and what the turns told
    each other. The researcher's actions reach the current one; a coordinator thread reaches only its own."""

    state: RunState
    stop: bool = False              # released or handed over: end as soon as the turn ends (or is cancelled)
    pause: bool = False
    job: object = None              # the turn running now, as the agent manager's job
    thread: threading.Thread | None = None
    handoff: dict | None = None     # the last turn's handoff, for the next turn's prompt
    last_report: dict | None = None # the last turn's last step report, for a role that follows it
    turn_role: str | None = None
    turn_redirect: str | None = None
    model: object = None
    effort: object = None


ACTIVE = ("starting", "running", "pausing", "paused")


class AgentRun:
    def __init__(self, agent, hooks: RunHooks) -> None:
        self.agent = agent          # the studio's AgentManager
        self.hooks = hooks
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._run = _Start(RunState())

    # ------------------------------------------------------------ what the current Start is
    @property
    def state(self) -> RunState:
        return self._run.state

    def role_for_turn(self) -> str | None:
        return self._run.turn_role

    def redirect_for_turn(self) -> str | None:
        return self._run.turn_redirect

    def active(self) -> bool:
        """The run holds the node's one slot: while it is being started too, so two Starts can't both begin."""
        return self._run.state.status in ACTIVE

    def view(self) -> dict:
        """The run as the page and the map read it: status, reason, role, turns, and where the plan stands."""
        with self._lock:
            state = RunState(**vars(self._run.state))
        log = self.hooks.work_log() if state.status != "idle" else []
        plans = [e for e in log if e.get("kind") == "plan"]
        steps = [e for e in log if e.get("kind") == "step"]
        return {
            "status": state.status, "reason": state.reason, "role": state.role, "name": state.name, "provider": state.provider,
            "turns": state.turns, "turns_max": state.turns_max, "started_at": state.started_at, "deadline": state.deadline,
            "roles": list(state.roles), "redirect": state.redirect,
            "steps": len(plans[-1]["plan"]) if plans else None, "step": steps[-1]["step"] if steps else None,
            "step_status": steps[-1]["status"] if steps else None,
        }

    # ------------------------------------------------------------ the researcher's actions
    def start(self, provider: str, *, roles: list[str] | None = None, redirect: str | None = None, model=None, effort=None) -> dict:
        roles = [role for role in (roles or []) if role in AGENT_ROLES]
        with self._lock:
            if self.active():
                return {"error": "RUN_ACTIVE", "message": "an agent is already working on this node; pause, redirect or release it"}
            run = self._run = _Start(RunState(status="starting"))  # holds the slot while the node is assigned, outside the lock
        try:
            turns_max, minutes = self.hooks.budget()
            name = self.hooks.agent_name(provider)
            self.hooks.assign(name)  # another assignee, a blocked or rejected node: refused here, and no run begins
        except Exception as exc:  # noqa: BLE001 — the refusal is the answer; the slot is given back
            with self._lock:
                if not run.stop:
                    run.state.status = "idle"
            code = getattr(exc, "code", None) or type(exc).__name__
            return {"error": code, "message": getattr(exc, "message", None) or str(exc)}
        with self._lock:
            if run.stop:  # stopped and released while the node was being assigned: this Start is over before it began
                run.state.name = name
                stopped = self._run is run  # a later Start under the same name now holds the assignment: it is not ours to give back
            else:
                stopped = False
                run.state = RunState(status="running", role=roles[0] if roles else "prover", turns_max=turns_max, started_at=time.time(),
                                     deadline=time.time() + minutes * 60, name=name, provider=provider, roles=roles,
                                     redirect={"text": redirect, "role": None} if redirect else None)
                run.model, run.effort = model, effort
                run.thread = threading.Thread(target=self._loop, args=(run,), name=f"agent-run-{name}", daemon=True)
        if stopped:
            self.hooks.release(name)  # the assignment it just made is given back
        if stopped or run.stop:
            return self.view()
        run.thread.start()
        return self.view()

    def pause(self) -> dict:
        with self._lock:
            run = self._run
            if run.state.status == "running":
                run.pause = True
                run.state.status = "pausing"
        return self.view()

    def resume(self) -> dict:
        with self._lock:
            run = self._run
            if run.state.status in ("paused", "pausing"):
                run.pause = False
                run.state.status = "running"
                self._wake.notify_all()
        return self.view()

    def redirect(self, text: str, role: str | None = None) -> dict:
        with self._lock:
            if self.active():
                self._run.state.redirect = {"text": text.strip(), "role": role if role in AGENT_ROLES else None}
        return self.view()

    def release(self, reason: str = "stopped and released by the researcher") -> dict:
        with self._lock:
            run = self._run
            was, name, job = run.state.status, run.state.name, run.job
            run.stop = True
            run.pause = False
            run.state.status = "released"
            run.state.reason = reason
            self._wake.notify_all()
        if job is not None and not job.done:
            self.agent.stop(job.id)
        if was not in ("idle", "released", "starting"):  # a Start still assigning gives its assignment back itself
            self.hooks.release(name)
        return self.view()

    # ------------------------------------------------------------ the loop
    def _loop(self, run: _Start) -> None:
        idle_turns = 0
        try:
            while True:
                with self._lock:
                    if run.stop:
                        return
                    if run.pause:
                        run.state.status = "paused"
                        while run.pause and not run.stop:
                            self._wake.wait(1.0)
                        if run.stop:
                            return
                    state = run.state
                    if state.turns >= state.turns_max or (state.deadline and time.time() >= state.deadline):
                        ending = ("budget", f"the budget of this Start is spent ({state.turns} turn(s))")
                    else:
                        ending = None
                        role = self._next_role(run)
                        state.role = role
                        redirect = None
                        if state.redirect and state.redirect.get("role") in (None, role):
                            redirect, state.redirect = state.redirect["text"], None
                        run.turn_role, run.turn_redirect = role, redirect
                        prompt = self._prompt(run, role, redirect)
                        provider = state.provider
                if ending:
                    self._end(run, *ending)
                    return
                before = len(self.hooks.work_log())
                started = self._start_turn(run, prompt, provider)
                if started is None:
                    return
                if "error" in started:
                    self._end(run, "stuck", f"the turn could not start: {started['error']}")
                    return
                job = self.agent.jobs[started["job"]]
                with self._lock:
                    deadline = run.state.deadline
                over_budget = False
                with job.cond:
                    while not job.done:
                        job.cond.wait(0.5)
                        if not job.done and not over_budget and deadline and time.time() >= deadline:
                            over_budget = True  # the time budget ends a turn that is still running (spec #145, story 25)
                            self.agent.stop(job.id)
                with self._lock:
                    run.job = None
                    if run.stop:
                        return
                    run.state.turns += 1
                    single = bool(run.state.roles)
                if over_budget:
                    self._end(run, "budget", f"the time budget of this Start is spent ({run.state.turns} turn(s), the last one stopped)")
                    return
                done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
                new = self.hooks.work_log()[before:]
                run.handoff = next((e for e in reversed(new) if e.get("kind") == "handoff"), None)
                run.last_report = next((e for e in reversed(new) if e.get("kind") == "step"), None)
                if any(e.get("kind") == "review-requested" for e in new):
                    self._end(run, "done", "review-requested")
                    return
                stuck = next((e for e in reversed(new) if e.get("kind") == "step" and e.get("status") == "stuck"), None)
                if stuck is not None:
                    self._end(run, "stuck", stuck.get("note") or "the agent reported it is stuck")
                    return
                if single:  # a single role was asked for: one turn
                    self._end(run, "done", "turn-finished")
                    return
                changed = bool(done.get("changed")) or any(e.get("kind") in _CHANGES for e in new)
                idle_turns = 0 if changed else idle_turns + 1
                if idle_turns >= STUCK_TURNS:
                    self._end(run, "stuck", f"no change in {idle_turns} turn(s)")
                    return
        except Exception as exc:  # noqa: BLE001 — the run ends, and says why
            self._end(run, "stuck", f"{type(exc).__name__}: {exc}")

    def _start_turn(self, run: _Start, prompt: str, provider: str) -> dict | None:
        """Start the role's turn; the researcher's own Ask turn, if one is running, is waited for. None: released meanwhile —
        before the turn, while it was being prepared (the manager asks `unless` once more before the turn exists), or in
        the moment it began, in which case it is stopped at once."""
        deadline = time.monotonic() + BUSY_WAIT
        while True:
            with self._lock:
                if run.stop:
                    return None
            started = self.agent.start(prompt, None, "edit", run.model, run.effort, None, provider, unless=lambda: run.stop)
            if "job" in started:
                with self._lock:
                    run.job = self.agent.jobs[started["job"]]
                    stopped = run.stop
                if stopped:
                    self.agent.stop(started["job"])
                    return None
                return started
            if "called off" in started.get("error", ""):
                return None
            busy = "still working" in started["error"]
            if not busy or time.monotonic() >= deadline:
                return started
            time.sleep(0.2)

    def _next_role(self, run: _Start) -> str:
        """Who takes the next turn: the role asked for, the role handed off to, else the Prover."""
        if run.state.roles:
            return run.state.roles[0]
        if run.handoff and run.handoff.get("to") in AGENT_ROLES:
            return run.handoff["to"]
        return "prover"

    def _prompt(self, run: _Start, role: str, redirect: str | None) -> str:
        parts = [f"Take your turn as the {role.capitalize()} on this node. Report your plan or your step with `proof node progress`, and end the turn when the step is done or handed over."]
        if run.handoff and run.handoff.get("to") == role and run.handoff.get("note"):
            parts.append(f"The {run.handoff.get('role', 'previous role')} handed this to you: {run.handoff['note']}")
        elif run.last_report and run.last_report.get("role") not in (None, role) and run.last_report.get("note"):
            parts.append(f"The {run.last_report['role']} reports: {run.last_report['note']}")
        if redirect:
            parts.append(f"The researcher says: {redirect}")
        return "\n\n".join(parts)

    def _end(self, run: _Start, status: str, reason: str) -> None:
        """Close this Start, and leave its last word in the work log unless the roles already did."""
        with self._lock:
            if run.stop:
                return
            run.state.status, run.state.reason = status, reason
            role, name = run.state.role or "prover", run.state.name
        if status in ("budget", "stuck") and not reason.startswith("the turn could not start"):
            try:
                self.hooks.record_stuck(role, name, reason)
            except Exception:  # noqa: BLE001 — the note is a courtesy; the state is the record
                pass
