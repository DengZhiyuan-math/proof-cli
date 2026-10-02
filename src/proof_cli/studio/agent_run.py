"""A Proof agent's run on a node (spec #145, decided in #144): Start once, then autonomous.

One run is the node's assignee under the project's agent name and works the node as three roles
in turn — Prover, Typesetter, Numerics — each a turn of the same CLI (agent.py) with its own brief,
environment and write scope (proof_agent.py). The Prover goes first and hands work over through
`proof node progress --handoff <role>`; a role hands back when it is done; the run brings the Prover
back after every delegation, telling it what the other role reported. A Start may name the roles it
runs: one role is one turn; several are the same flow restricted to them, in the spec's order. It
stops on its own when review is requested, when a step reports stuck or names a decision only a
human can make, when its budget is spent, or when turns stop changing anything; it leaves a closing
progress note on every stop. The researcher pauses it (the turn finishes, the assignment stays, the
budget's clock stops), redirects it (one line for the next turn, optionally for one role), resumes
it, or stops and releases it. Everything it learns is project state the roles wrote through `proof`;
the run itself keeps only what the page asks about: its status, its reason, which role and turn it
is on — and records each turn (its job, session, step and conversation) through its hooks.

Each Start is its own record (`_Start`): the coordinator thread of a Start holds that record and
nothing else, so a coordinator still winding down after Stop and release can never end, count or
resume the Start that follows it. The lock guards the run's own state only; the project is read
and written outside it, as the agent manager does with its backends.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..domain import AGENT_ROLES
from ..errors import ERROR_CODES
from .proof_agent import is_a_run

STUCK_TURNS = 5      # turns in a row that change nothing — no `proof` write, no file, no run — before the run stops as stuck
BUSY_WAIT = 30.0     # seconds a turn waits for the researcher's own Ask turn to end before giving up
SETTLE_WAIT = 5.0    # seconds a Start waits for a run that is over to finish giving the node back, before it is refused
# the work log entries the stuck rule counts as a change: a `proof` write that is not narration. A plan, a step or a
# handoff only says what the run means to do or did; a turn that says only that changed nothing.
_CHANGES = ("split", "fog", "experiment", "evidence", "dependencies", "review-requested")
ACTIONS = ("start", "pause", "resume", "redirect", "release")   # the researcher's oversight, on the studio's and the map's routes
ACTIVE = ("starting", "running", "pausing", "paused")
# how a run's end reads as its closing progress note's step status
_CLOSING = {"done": "done", "released": "done", "stuck": "stuck", "budget": "stuck", "needs-human": "needs-human"}


@dataclass
class RunHooks:
    """What a run needs from the project, as callables: the studio knows nothing of the proof map itself."""

    agent_name: Callable[[str], str]                 # provider -> the name the run works under
    budget: Callable[[], tuple[int, float]]           # (turns, minutes)
    assign: Callable[[str], None]                     # make the node's assignee this name (raises when another holds it)
    release: Callable[[str, str], None]               # (name, reason): release the node when this name is its assignee
    work_log: Callable[[], list[dict]]                # the node's work log, oldest first
    record_close: Callable[[str, str, str, str], None]  # (role, name, step status, note): the run's closing progress note
    # a turn's record: {"phase": "started"|"ended", "turn", "role", "by", "provider"} and, ended, its job, session,
    # step and conversation (`events`)
    record_turn: Callable[[dict], None] = lambda turn: None
    transcript: Callable[[str], dict | None] = lambda turn: None   # a recorded turn's conversation, by its id


@dataclass
class RunState:
    # idle | starting | running | pausing | paused | released | release-failed | done | stuck | budget | needs-human
    status: str = "idle"
    reason: str = ""
    role: str | None = None
    turns: int = 0
    turns_max: int = 0
    started_at: float | None = None
    deadline: float | None = None
    paused_at: float | None = None   # while paused: the budget's clock is stopped here (resume moves the deadline on)
    name: str = ""
    provider: str = ""
    roles: list[str] = field(default_factory=list)   # the roles asked for, in the spec's order; empty is every role
    redirect: dict | None = None                     # {"text", "role"} waiting for the next matching turn
    decision: str | None = None                      # needs-human: the decision only the researcher can make
    job: int | None = None                           # the turn running now: the agent manager's job id
    turn: str | None = None                          # and its id in the work log


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
    model: object = None
    effort: object = None


class AgentRun:
    def __init__(self, agent, hooks: RunHooks) -> None:
        self.agent = agent          # the studio's AgentManager
        self.hooks = hooks
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._run = _Start(RunState())
        self._settling = 0   # releases of the node in progress: a Start arriving meanwhile waits for them (see _give_back)

    # ------------------------------------------------------------ what the current Start is
    @property
    def state(self) -> RunState:
        return self._run.state

    def active(self) -> bool:
        """The run holds the node's one slot: while it is being started too, so two Starts can't both begin."""
        return self._run.state.status in ACTIVE

    def view(self) -> dict:
        """The run as the page and the map read it: status, reason, role, turns, the budget left, and where the plan stands."""
        with self._lock:
            state = RunState(**vars(self._run.state))
        log = self.hooks.work_log() if state.status != "idle" else []
        plans = [e for e in log if e.get("kind") == "plan"]
        steps = [e for e in log if e.get("kind") == "step"]
        left = None
        if state.deadline is not None:
            left = max(0.0, (state.deadline - (state.paused_at or time.time())) / 60)
        return {
            "status": state.status, "reason": state.reason, "role": state.role, "name": state.name, "provider": state.provider,
            "turns": state.turns, "turns_max": state.turns_max, "started_at": state.started_at, "deadline": state.deadline,
            "minutes_left": left, "roles": list(state.roles), "redirect": state.redirect, "decision": state.decision,
            "job": state.job, "turn": state.turn,
            "steps": len(plans[-1]["plan"]) if plans else None, "step": steps[-1]["step"] if steps else None,
            "step_status": steps[-1]["status"] if steps else None,
        }

    def transcript(self, turn: str) -> dict | None:
        return self.hooks.transcript(turn)

    # ------------------------------------------------------------ the researcher's actions
    def start(self, provider: str, *, roles: list[str] | None = None, redirect: str | None = None, model=None, effort=None) -> dict:
        roles = [role for role in AGENT_ROLES if role in (roles or [])]  # the spec's order, whatever order they came in
        with self._lock:
            # a run that is over may still be giving the node back: begin after it, so this Start's own assignment
            # cannot slip in between the decision and the release and be taken away with it
            deadline = time.monotonic() + SETTLE_WAIT
            while self._settling and not self.active():
                left = deadline - time.monotonic()
                if left <= 0:
                    return {"error": "the previous run is still giving the node back; Start again in a moment", "code": "RUN_SETTLING"}
                self._wake.wait(min(0.05, left))
            if self.active():
                return {"error": "an agent is already working on this node; pause, redirect or release it", "code": "RUN_ACTIVE"}
            run = self._run = _Start(RunState(status="starting"))  # holds the slot while the node is assigned, outside the lock
        try:
            turns_max, minutes = self.hooks.budget()
            name = self.hooks.agent_name(provider)
            self.hooks.assign(name)  # another assignee, a blocked or rejected node: refused here, and no run begins
        except Exception as exc:  # noqa: BLE001 — the refusal is the answer; the slot is given back
            with self._lock:
                if not run.stop:
                    run.state.status = "idle"
            code = getattr(exc, "code", None)
            return {"error": getattr(exc, "message", None) or str(exc), "code": code if code in ERROR_CODES else "RUN_REFUSED"}
        with self._lock:
            if run.stop:  # stopped and released while the node was being assigned: this Start is over before it began
                run.state.name = name
                # ours to give back — unless a later Start under the same name holds the node now. A later Start that
                # never began, was released, or requested review (a review request hands the node over) left no claim
                # behind, so what this late assignment made is ours too; one that ended done, stuck or over budget
                # keeps its claim on purpose, and the late assignment made none.
                later = self._run.state
                give_back = self._run is run or later.status in ("idle", "released") or later.reason == "review-requested"
                if give_back:
                    self._settling += 1  # decided and announced in one breath: a Start arriving now waits for the release
            else:
                give_back = False
                run.state = RunState(status="running", role=roles[0] if roles else "prover", turns_max=turns_max, started_at=time.time(),
                                     deadline=time.time() + minutes * 60, name=name, provider=provider, roles=roles,
                                     redirect={"text": redirect, "role": None} if redirect else None)
                run.model, run.effort = model, effort
                run.thread = threading.Thread(target=self._loop, args=(run,), name=f"agent-run-{name}", daemon=True)
        if give_back:
            failed = self._give_back(run, name, "late assignment given back")  # the assignment it just made
            return {**self.view(), **(failed or {})}
        if run.stop:
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
            if not self.active():
                return {"error": "no agent is working on this node; Start one, with this line as its first redirect", "code": "NO_RUN"}
            self._run.state.redirect = {"text": text.strip(), "role": role if role in AGENT_ROLES else None}
        return self.view()

    def release(self, reason: str = "stopped and released by the researcher") -> dict:
        with self._lock:
            run = self._run
            was, name, job, role = run.state.status, run.state.name, run.job, run.state.role or "prover"
            run.stop = True
            run.pause = False
            run.state.status = "released"
            run.state.reason = reason
            run.state.paused_at = None
            gives_back = was not in ("idle", "released", "starting")  # a Start still assigning gives its assignment back itself
            if gives_back:
                self._settling += 1
            self._wake.notify_all()
        if job is not None and not job.done:
            self.agent.stop(job.id)
        if was in ("running", "pausing", "paused"):  # the run's last word: an ended run already left its own
            self._close_note(role, name, "released", reason)
        failed = self._give_back(run, name, reason) if gives_back else None
        return {**self.view(), **(failed or {})}

    def _give_back(self, run: _Start, name: str, reason: str) -> dict | None:
        """Release the node for a run that is over. `_settling` was raised under the lock together with the decision,
        so a Start arriving meanwhile waits in `start()` instead of claiming the node and losing that claim to this.
        A release that fails is not a release: the run says so (`release-failed`), and the error is the answer."""
        try:
            self.hooks.release(name, reason)
            return None
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed: the node is still assigned
            message = f"the node is still assigned to {name}: giving it back failed ({type(exc).__name__}: {exc})"
            with self._lock:
                run.state.status, run.state.reason = "release-failed", message
            return {"error": message, "code": "RELEASE_FAILED"}
        finally:
            with self._lock:
                self._settling -= 1
                self._wake.notify_all()

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
                        run.state.paused_at = time.time()  # the budget's clock stops while the run waits
                        while run.pause and not run.stop:
                            self._wake.wait(1.0)
                        if run.stop:
                            return
                        if run.state.deadline is not None:  # resumed: what was left of the budget is left still
                            run.state.deadline += time.time() - run.state.paused_at
                        run.state.paused_at = None
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
                        prompt = self._prompt(run, role, redirect)
                        provider, name = state.provider, state.name
                if ending:
                    self._end(run, *ending)
                    return
                before = len(self.hooks.work_log())
                turn = {"turn": uuid.uuid4().hex[:16], "role": role, "by": name, "provider": provider}
                began: list = []

                def begin(job, turn=turn, began=began):  # the turn exists and its backend is about to start
                    began.append(job)
                    self._note_turn({**turn, "phase": "started", "job": job.id})

                started = self._start_turn(run, prompt, provider, {"role": role, "name": name, "redirect": redirect}, begin)
                if started is None or "error" in started:
                    if began:  # it began and was stopped at once: close its marker
                        self._note_turn({**turn, "phase": "ended", "job": None})
                    if started is not None:
                        self._end(run, "stuck", f"the turn could not start: {started['error']}")
                    return
                job = self.agent.jobs[started["job"]]
                with self._lock:
                    deadline = run.state.deadline
                    run.state.job, run.state.turn = job.id, turn["turn"]
                over_budget = False
                with job.cond:
                    while not job.done:
                        job.cond.wait(0.5)
                        if not job.done and not over_budget and deadline and time.time() >= deadline:
                            over_budget = True  # the time budget ends a turn that is still running (spec #145, story 25)
                            self.agent.stop(job.id)
                log = self.hooks.work_log()
                new = log[before:]
                steps = [e["step"] for e in log if e.get("kind") == "step"]
                self._note_turn({**turn, "phase": "ended", "job": job.id, "step": steps[-1] if steps else None,
                                 "session_id": next((e["session_id"] for e in reversed(job.events) if e.get("session_id")), None),
                                 "events": [e for e in job.events if e.get("t") != "delta"]})  # the text events hold the whole text
                with self._lock:
                    run.job = None
                    run.state.job = run.state.turn = None
                    if run.stop:
                        return
                    run.state.turns += 1
                    roles = list(run.state.roles)
                if over_budget:
                    self._end(run, "budget", f"the time budget of this Start is spent ({run.state.turns} turn(s), the last one stopped)")
                    return
                done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
                run.handoff = next((e for e in reversed(new) if e.get("kind") == "handoff"), None)
                run.last_report = next((e for e in reversed(new) if e.get("kind") == "step"), None)
                # a decision only the researcher can make comes first: a review request in the same turn stands as it is,
                # but the run stops for the decision, which would otherwise be lost under "done"
                asked = next((e for e in reversed(new) if e.get("kind") == "step" and e.get("status") == "needs-human"), None)
                if asked is not None:
                    self._end(run, "needs-human", asked.get("note") or "a decision only the researcher can make")
                    return
                if any(e.get("kind") == "review-requested" for e in new):
                    self._end(run, "done", "review-requested")
                    return
                stuck = next((e for e in reversed(new) if e.get("kind") == "step" and e.get("status") == "stuck"), None)
                if stuck is not None:
                    self._end(run, "stuck", stuck.get("note") or "the agent reported it is stuck")
                    return
                if len(roles) == 1:  # a single role was asked for: one turn
                    self._end(run, "done", "turn-finished")
                    return
                if roles and roles[0] != "prover" and role == roles[0] and self._handed_to(run) is None:
                    # several roles without the Prover: nobody decides to go on once the first hands nothing over
                    self._end(run, "done", "turn-finished")
                    return
                ran = any(e.get("t") == "tool" and e.get("name") == "Bash" and is_a_run(str(e.get("summary") or "")) for e in job.events)
                changed = bool(done.get("changed")) or ran or any(e.get("kind") in _CHANGES for e in new)
                idle_turns = 0 if changed else idle_turns + 1
                if idle_turns >= STUCK_TURNS:
                    self._end(run, "stuck", f"no change in {idle_turns} turn(s)")
                    return
        except Exception as exc:  # noqa: BLE001 — the run ends, and says why
            self._end(run, "stuck", f"{type(exc).__name__}: {exc}")

    def _note_turn(self, turn: dict) -> None:
        try:
            self.hooks.record_turn(turn)
        except Exception:  # noqa: BLE001 — the record is the log's; the run goes on without it
            pass

    def _start_turn(self, run: _Start, prompt: str, provider: str, turn: dict, begin=None) -> dict | None:
        """Start the role's turn; the researcher's own Ask turn, if one is running, is waited for. None: released meanwhile —
        before the turn, while it was being prepared (the manager asks `unless` once more before the turn exists), or in
        the moment it began, in which case it is stopped at once. `turn` (role, name, redirect) goes to the manager as it
        is, so the role reaches this turn's context and no other."""
        deadline = time.monotonic() + BUSY_WAIT
        while True:
            with self._lock:
                if run.stop:
                    return None
            started = self.agent.start(prompt, None, "edit", run.model, run.effort, None, provider, unless=lambda: run.stop, turn=turn, begin=begin)
            if "job" in started:
                with self._lock:
                    run.job = self.agent.jobs[started["job"]]
                    stopped = run.stop
                if stopped:
                    self.agent.stop(started["job"])
                    return None
                return started
            if started.get("code") == "TURN_CALLED_OFF":
                return None
            if started.get("code") != "AGENT_BUSY" or time.monotonic() >= deadline:
                return started
            time.sleep(0.2)

    def _allowed(self, run: _Start) -> tuple[str, ...]:
        return tuple(run.state.roles) or AGENT_ROLES

    def _handed_to(self, run: _Start) -> str | None:
        """The role the last turn handed the work to, when that role is part of this Start."""
        to = run.handoff.get("to") if run.handoff else None
        return to if to in self._allowed(run) else None

    def _next_role(self, run: _Start) -> str:
        """Who takes the next turn: the role handed off to, when this Start runs it; else the first role it runs — the Prover
        for the whole flow."""
        return self._handed_to(run) or self._allowed(run)[0]

    def _prompt(self, run: _Start, role: str, redirect: str | None) -> str:
        label = lambda name: name.capitalize()  # noqa: E731
        parts = [f"Take your turn as the {label(role)} on this node. Report your plan or your step with `proof node progress`, and end the turn when the step is done or handed over."]
        allowed = self._allowed(run)
        if len(allowed) == 1:
            parts.append(f"This Start runs only the {label(role)}, for this one turn.")
        elif len(allowed) < len(AGENT_ROLES):
            parts.append(f"This Start runs only the {' and the '.join(label(r) for r in allowed)}: hand work only to them.")
        if run.handoff and run.handoff.get("to") == role and run.handoff.get("note"):
            parts.append(f"The {run.handoff.get('role', 'previous role')} handed this to you: {run.handoff['note']}")
        elif run.handoff and run.handoff.get("to") not in allowed:
            parts.append(f"The {label(str(run.handoff.get('to')))} is not part of this Start; carry on without it.")
        elif run.last_report and run.last_report.get("role") not in (None, role) and run.last_report.get("note"):
            parts.append(f"The {run.last_report['role']} reports: {run.last_report['note']}")
        if redirect:
            parts.append(f"The researcher says: {redirect}")
        return "\n\n".join(parts)

    def _end(self, run: _Start, status: str, reason: str) -> None:
        """Close this Start, and leave its last word in the work log: a progress note on every stop — except a decision,
        whose own needs-human step, the role's, is already that last word."""
        with self._lock:
            if run.stop:
                return
            run.state.status, run.state.reason = status, reason
            if status == "needs-human":
                run.state.decision = reason
            role, name = run.state.role or "prover", run.state.name
        if status != "needs-human":
            self._close_note(role, name, status, reason)

    def _close_note(self, role: str, name: str, status: str, reason: str) -> None:
        try:
            self.hooks.record_close(role, name, _CLOSING.get(status, "done"), f"run {status}: {reason}")
        except Exception:  # noqa: BLE001 — the note is a courtesy; the state is the record
            pass
