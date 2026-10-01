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

The lock guards the run's own state only; the project is read and written outside it, as the
agent manager does with its backends.
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
    status: str = "idle"          # idle | running | pausing | paused | released | done | stuck | budget
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


class AgentRun:
    def __init__(self, agent, hooks: RunHooks) -> None:
        self.agent = agent          # the studio's AgentManager
        self.hooks = hooks
        self.state = RunState()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stop = False          # released: end as soon as the turn ends (or is cancelled)
        self._pause = False
        self._job = None
        self._handoff: dict | None = None       # the last turn's handoff, for the next turn's prompt
        self._last_report: dict | None = None   # the last turn's last step report, for a role that follows it
        self._turn_role: str | None = None
        self._turn_redirect: str | None = None
        self.model = self.effort = None

    # ------------------------------------------------------------ what the next turn is
    def role_for_turn(self) -> str | None:
        return self._turn_role

    def redirect_for_turn(self) -> str | None:
        return self._turn_redirect

    def active(self) -> bool:
        return self.state.status in ("running", "pausing", "paused")

    def view(self) -> dict:
        """The run as the page and the map read it: status, reason, role, turns, and where the plan stands."""
        with self._lock:
            state = RunState(**vars(self.state))
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
            self.state.status = "starting"  # holds the slot while the node is assigned, outside the lock
        try:
            turns_max, minutes = self.hooks.budget()
            name = self.hooks.agent_name(provider)
            self.hooks.assign(name)  # another assignee, a blocked or rejected node: refused here, and no run begins
        except Exception as exc:  # noqa: BLE001 — the refusal is the answer; the slot is given back
            with self._lock:
                self.state.status = "idle"
            code = getattr(exc, "code", None) or type(exc).__name__
            return {"error": code, "message": getattr(exc, "message", None) or str(exc)}
        with self._lock:
            self.state = RunState(status="running", role=roles[0] if roles else "prover", turns_max=turns_max, started_at=time.time(),
                                  deadline=time.time() + minutes * 60, name=name, provider=provider, roles=roles,
                                  redirect={"text": redirect, "role": None} if redirect else None)
            self._stop = self._pause = False
            self._handoff = self._last_report = None
            self.model, self.effort = model, effort
        self._thread = threading.Thread(target=self._loop, name=f"agent-run-{name}", daemon=True)
        self._thread.start()
        return self.view()

    def pause(self) -> dict:
        with self._lock:
            if self.state.status == "running":
                self._pause = True
                self.state.status = "pausing"
        return self.view()

    def resume(self) -> dict:
        with self._lock:
            if self.state.status in ("paused", "pausing"):
                self._pause = False
                self.state.status = "running"
                self._wake.notify_all()
        return self.view()

    def redirect(self, text: str, role: str | None = None) -> dict:
        with self._lock:
            if self.active():
                self.state.redirect = {"text": text.strip(), "role": role if role in AGENT_ROLES else None}
        return self.view()

    def release(self, reason: str = "stopped and released by the researcher") -> dict:
        with self._lock:
            was, name, job = self.state.status, self.state.name, self._job
            self._stop = True
            self._pause = False
            self.state.status = "released"
            self.state.reason = reason
            self._wake.notify_all()
        if job is not None and not job.done:
            self.agent.stop(job.id)
        if was not in ("idle", "released"):
            self.hooks.release(name)
        return self.view()

    # ------------------------------------------------------------ the loop
    def _loop(self) -> None:
        idle_turns = 0
        try:
            while True:
                with self._lock:
                    if self._stop:
                        return
                    if self._pause:
                        self.state.status = "paused"
                        while self._pause and not self._stop:
                            self._wake.wait(1.0)
                        if self._stop:
                            return
                    state = self.state
                    if state.turns >= state.turns_max or (state.deadline and time.time() >= state.deadline):
                        ending = ("budget", f"the budget of this Start is spent ({state.turns} turn(s))")
                    else:
                        ending = None
                        role = self._next_role()
                        self.state.role = role
                        redirect = None
                        if state.redirect and state.redirect.get("role") in (None, role):
                            redirect, state.redirect = state.redirect["text"], None
                        self._turn_role, self._turn_redirect = role, redirect
                        prompt = self._prompt(role, redirect)
                        provider = state.provider
                if ending:
                    self._end(*ending)
                    return
                before = len(self.hooks.work_log())
                started = self._start_turn(prompt, provider)
                if started is None:
                    return
                if "error" in started:
                    self._end("stuck", f"the turn could not start: {started['error']}")
                    return
                job = self.agent.jobs[started["job"]]
                with self._lock:
                    self._job = job
                with job.cond:
                    while not job.done:
                        job.cond.wait(0.5)
                with self._lock:
                    self._job = None
                    if self._stop:
                        return
                    self.state.turns += 1
                    single = bool(self.state.roles)
                done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
                new = self.hooks.work_log()[before:]
                self._handoff = next((e for e in reversed(new) if e.get("kind") == "handoff"), None)
                self._last_report = next((e for e in reversed(new) if e.get("kind") == "step"), None)
                if any(e.get("kind") == "review-requested" for e in new):
                    self._end("done", "review-requested")
                    return
                stuck = next((e for e in reversed(new) if e.get("kind") == "step" and e.get("status") == "stuck"), None)
                if stuck is not None:
                    self._end("stuck", stuck.get("note") or "the agent reported it is stuck")
                    return
                if single:  # a single role was asked for: one turn
                    self._end("done", "turn-finished")
                    return
                changed = bool(done.get("changed")) or any(e.get("kind") in _CHANGES for e in new)
                idle_turns = 0 if changed else idle_turns + 1
                if idle_turns >= STUCK_TURNS:
                    self._end("stuck", f"no change in {idle_turns} turn(s)")
                    return
        except Exception as exc:  # noqa: BLE001 — the run ends, and says why
            self._end("stuck", f"{type(exc).__name__}: {exc}")

    def _start_turn(self, prompt: str, provider: str) -> dict | None:
        """Start the role's turn; the researcher's own Ask turn, if one is running, is waited for. None: released meanwhile."""
        deadline = time.monotonic() + BUSY_WAIT
        while True:
            started = self.agent.start(prompt, None, "edit", self.model, self.effort, None, provider)
            busy = "error" in started and "still working" in started["error"]
            if not busy or time.monotonic() >= deadline:
                return started
            with self._lock:
                if self._stop:
                    return None
            time.sleep(0.2)

    def _next_role(self) -> str:
        """Who takes the next turn: the role asked for, the role handed off to, else the Prover."""
        if self.state.roles:
            return self.state.roles[0]
        if self._handoff and self._handoff.get("to") in AGENT_ROLES:
            return self._handoff["to"]
        return "prover"

    def _prompt(self, role: str, redirect: str | None) -> str:
        parts = [f"Take your turn as the {role.capitalize()} on this node. Report your plan or your step with `proof node progress`, and end the turn when the step is done or handed over."]
        if self._handoff and self._handoff.get("to") == role and self._handoff.get("note"):
            parts.append(f"The {self._handoff.get('role', 'previous role')} handed this to you: {self._handoff['note']}")
        elif self._last_report and self._last_report.get("role") not in (None, role) and self._last_report.get("note"):
            parts.append(f"The {self._last_report['role']} reports: {self._last_report['note']}")
        if redirect:
            parts.append(f"The researcher says: {redirect}")
        return "\n\n".join(parts)

    def _end(self, status: str, reason: str) -> None:
        """Close the run, and leave its last word in the work log unless the roles already did."""
        with self._lock:
            if self._stop:
                return
            self.state.status, self.state.reason = status, reason
            role, name = self.state.role or "prover", self.state.name
        if status in ("budget", "stuck") and not reason.startswith("the turn could not start"):
            try:
                self.hooks.record_stuck(role, name, reason)
            except Exception:  # noqa: BLE001 — the note is a courtesy; the state is the record
                pass
