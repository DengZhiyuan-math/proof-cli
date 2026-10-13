"""A Proof agent's run on a node (spec #145, decided in #144): Start once, then autonomous.

One run is the node's assignee under the project's agent name and works the node as its roles
in turn — Prover, Typesetter, Numerics, and the Verifier (ADR-0019) — each a turn of the same CLI (latex-agent's agent
manager) with its own brief, environment and write scope (proof_agent.py). The Prover goes first and hands work over
through `proof node progress --handoff <role>`; a role hands back when it is done; the run brings the Prover back
after every delegation, telling it what the other role reported. It is a prove–verify loop: the Verifier reads the
proof after the Prover hands it over, and after every Typesetter turn that changed a .tex file; a failed verdict
returns the work to the Prover with its objections; a passing one on the files as they stand is the Prover's gate to
request review, and the run records it as an Evidence check on the snapshot the request froze (ADR-0019 points 3–6).
Every turn is briefed by the run from the record — the node, the redirect, the last word, the verdict, the attempts,
the shared notes (briefing.py, ADR-0019 point 9) — never left to reconstruct the history from the work log; an edit
of the working inputs between two turns is the researcher's, and its diff heads the next briefing (point 21). A Start may name the roles it
runs: one role is one turn; several are the same flow restricted to them, in the spec's order. The Decomposer is
started alone, on a Theorem not yet split: it proposes the split and the run stops for the researcher (point 20) —
unless a Coordinator's Pursue started it, when the split is the structure worked next (ADR-0021 point 7). It
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

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from proof_cli.domain import AGENT_ROLES
from .briefing import BriefingParts, build_briefing, inputs_diff, questions_from
from .patterns import suggested_redirects
from .proof_agent import CYCLE_ROLES, ROLES, is_a_run

DECOMPOSABLE_KINDS = ("theorem", "lemma")   # what a Decomposer may be started on (ADR-0019 point 20), when the host names the node's kind

STUCK_TURNS = 5      # turns in a row that change nothing — no `proof` write, no file, no run — before the run stops as stuck
CHECK_TURNS = 3      # turns in a row sent back on the mechanical checks (issue #180) before the run stops as stuck
BRIEFED_FILES = ("proof.tex", "key-ideas.md")   # the working files the Verifier and the Typesetter read in the briefing
BUSY_WAIT = 30.0     # seconds a turn waits for the researcher's own Ask turn to end before giving up
SETTLE_WAIT = 5.0    # seconds a Start waits for a run that is over to finish giving the node back, before it is refused
# the work log entries the stuck rule counts as a change: a `proof` write that is not narration. A plan, a step or a
# handoff only says what the run means to do or did; a turn that says only that changed nothing.
_CHANGES = ("split", "fog", "experiment", "evidence", "dependencies", "review-requested")
ACTIONS = ("start", "pause", "resume", "redirect", "release", "review-now")   # the researcher's oversight, on the studio's and the map's routes
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
    review_now: Callable[[], dict] = lambda: {}   # Review what it has: freeze a snapshot of the folder as it stands (as the researcher)
    # ADR-0019 (optional: a host without them runs as before, with no gate and a briefing of the record alone)
    inputs_digest: Callable[[], str | None] | None = None   # the working inputs' digest now, as a verdict's `inputs_sha256` and a snapshot's manifest hash it
    # {"node_id", "kind"?, "statement", "definitions"?: [{"id", "term", "text"}] (ADR-0020),
    #  "dependencies": [{"id", "statement", "accepted": bool, "key_ideas": str | None, "provisional": bool?, "kind": str?}]}:
    #  `provisional` as proof-cli's is_provisional says (ADR-0021 point 2)
    node_brief: Callable[[], dict] | None = None
    # one read of the working inputs: {"digest": the same digest inputs_digest gives, "files": {path: text, or bytes for a
    # file that is not text}} — the digest and the text of one and the same read, so what the run keeps at a turn's end is
    # consistent (audit P2-3); the run diffs it against the next turn's start to show the researcher's edit (point 21)
    working_inputs: Callable[[], dict] | None = None
    shared_notes: Callable[[], list[dict]] | None = None    # [{"node_id", "status", "text", "by"}]: part C's memory entries, newest first
    # (candidate_proof_id, "passed", run_by=, notes=, inputs_sha256=) -> recorded?: the host compares the hash with the snapshot's own
    record_evidence: Callable[..., bool] | None = None
    # the mechanical checks of the node's working folder (issue #180), as `proof node check` gives them: [{"code", "level", "message", "path"?}];
    # an error-level finding sends the work back to the Typesetter (or the Prover) instead of the Verifier
    check_inputs: Callable[[], list[dict]] | None = None
    # ADR-0021 point 8 (optional): (role, name, text) records a Standing question on the node — `proof node progress <node>
    # --question <text>` as the role would. The run itself no longer calls it (proof-agents#15): each role records its
    # own questions with that command, and a needs-human step stays a stop
    record_question: Callable[[str, str, str], None] | None = None


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
    suggestion: str | None = None                    # the newest suggested redirect the record showed (ADR-0019 point 17), for the researcher
    pursue: bool = False                             # started by a Coordinator's Pursue (ADR-0021 point 7): a Decomposer's split does not stop for the researcher
    # the work-log writes of this Start that failed (proof-agents#16): site (_close_note, _suggest, _note_turn) -> its latest
    # error, "<hook>: <exception>: <message>". The writes stay a courtesy, so the run goes on; the failure is not hidden
    record_failed: dict = field(default_factory=dict)


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
    # ADR-0019: what the last turn did (its role, whether it changed a .tex file, whether it recorded a verdict) decides
    # the next role; the digest at its end tells a researcher's edit from a role's; the passing verdict it gated with
    last_role: str | None = None
    last_changed_tex: bool = False
    last_verdict: bool = False
    inputs_after_turn: str | None = None
    inputs_text_after_turn: dict | None = None   # and their text then (with the working_inputs hook): what the researcher's diff is taken against
    gate_hash: str | None = None    # the passing verdict's inputs_sha256 the Prover's turn was given request-review on
    gate_note: str = ""
    suggested: set = field(default_factory=set)   # the patterns already surfaced in this Start (ADR-0019 point 17), by key
    given_back: bool = False        # the run gives the node back as it ends (a Decomposer's split, #186): a release has nothing left to give, unless that failed
    checks: list[dict] | None = None   # the mechanical checks of the folder as it stands (issue #180), read before each turn; None without the hook
    checks_error: str | None = None    # the checks could not run: no Verifier turn until they can (an exception never opens the gate)
    verify_wanted: bool = False        # the cycle meant to hand the next turn to the Verifier: it does once the checks pass, and sends the work back until then
    sent_back: int = 0                 # turns in a row the same failures sent back (CHECK_TURNS of them end the run)
    sent_back_on: tuple = ()           # the failure codes those turns were sent back on: a different set starts the count again
    node_id: str | None = None      # the node, as the host's node_brief names it: what tells this node's memory from another's


def first_changed_line(diff: str) -> int:
    """The first line a unified diff changes, in the new file: where "the agent changed check.py line 40" opens (spec #145)."""
    line = None
    for text in diff.splitlines():
        hunk = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", text)
        if hunk:
            if line is not None:
                break  # the first hunk had no change of its own: never so in a unified diff
            line = int(hunk.group(1))
        elif line is not None:
            if text.startswith(("+", "-")):
                return max(line, 1)
            line += 1
    return 1


def _changed_files(job) -> list[dict]:
    """The files a finished turn changed, each with the first line it changed: where the work log opens it."""
    done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
    return [{"path": c.get("path"), "line": first_changed_line(c.get("diff") or "")} for c in done.get("changed") or []]


def _check_errors(checks: list[dict] | None) -> list[dict]:
    """The error-level findings of the mechanical checks (issue #180); none without checks."""
    return [f for f in checks or [] if f.get("level") == "error"]


def _attempts_from(log: list[dict]) -> list[dict]:
    """The node's attempts, oldest first (ADR-0019 point 7): the ones a role closed with `--attempt`, and the ones the run reads
    off the record it already has — a failed verdict's objections, and a stuck step's note (a role's own, or the run's closing
    one) — each saying where it comes from (`derived`), so a later Prover is briefed on every dead end, not only the declared."""
    out: list[dict] = []
    for e in log:
        kind = e.get("kind")
        if kind == "attempt":
            out.append(e)
        elif kind == "verdict" and e.get("outcome") == "failed" and e.get("note"):
            out.append({"at": e.get("at"), "kind": "attempt", "role": e.get("role") or "verifier", "by": e.get("by"), "goal": "the proof as it stood",
                        "method": "", "failed_on": f"the Verifier's objections: {e['note']}", "derived": "verdict"})
        elif kind == "step" and e.get("status") == "stuck" and e.get("note"):
            out.append({"at": e.get("at"), "kind": "attempt", "role": e.get("role"), "by": e.get("by"), "goal": f"step {e.get('step')}",
                        "method": "", "failed_on": e["note"], "derived": "stuck"})
    return out



def failure_reason(done: dict, events: list[dict]) -> str:
    """Why a turn the CLI could not finish failed, by what says most (#179): the last line of stderr; else the last thing the
    turn said, a text or an error event ("Not logged in · Please run /login" comes as text, with subtype "success"); else
    the subtype or the exit code. Public for a host's own turns, such as proof-web's Reader turn."""
    said = (e.get("text") if e.get("t") == "text" else e.get("message") for e in reversed(events) if e.get("t") in ("text", "error"))
    for why in (done.get("stderr"), *said, done.get("subtype"), f"exit {done.get('exit')}" if done.get("exit") not in (None, 0) else None):
        lines = [line.strip() for line in str(why or "").splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return "the CLI reported an error"


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
            state = RunState(**{**vars(self._run.state), "record_failed": dict(self._run.state.record_failed)})
        log = self.hooks.work_log() if state.status != "idle" else []
        plans = [e for e in log if e.get("kind") == "plan"]
        steps = [e for e in log if e.get("kind") == "step"]
        left = None
        if state.deadline is not None:
            left = max(0.0, (state.deadline - (state.paused_at or time.time())) / 60)
        return {
            "status": state.status, "active": state.status in ACTIVE,
            "reason": state.reason, "role": state.role, "name": state.name, "provider": state.provider,
            "turns": state.turns, "turns_max": state.turns_max, "started_at": state.started_at, "deadline": state.deadline,
            "minutes_left": left, "roles": list(state.roles), "redirect": state.redirect, "decision": state.decision,
            "job": state.job, "turn": state.turn,
            "steps": len(plans[-1]["plan"]) if plans else None, "step": steps[-1]["step"] if steps else None,
            "step_status": steps[-1]["status"] if steps else None,
            "verdict": self._newest_verdict(log)["outcome"] if self._newest_verdict(log) else None,  # ADR-0019
            "suggestion": state.suggestion, "pursue": state.pursue, "record_failed": state.record_failed,
        }

    @staticmethod
    def _newest_verdict(log: list[dict]) -> dict | None:
        """The newest verdict in the work log (ADR-0019 point 2), or None."""
        found = [e for e in log if e.get("kind") == "verdict"]
        return found[-1] if found else None

    def _digest(self) -> str | None:
        """The working inputs' digest now, through the host; None without the hook or when the folder can't be read."""
        if self.hooks.inputs_digest is None:
            return None
        try:
            return self.hooks.inputs_digest()
        except Exception:  # noqa: BLE001 — an unreadable folder opens no gate and says nothing of the researcher's edits
            return None

    def _gate(self, log: list[dict], digest: str | None) -> dict | None:
        """The passing verdict that opens the Prover's gate (ADR-0019 point 3): the newest verdict, passed, with the
        working inputs' digest now. None otherwise — no verdict, a failed one, or one of an earlier version."""
        verdict = self._newest_verdict(log)
        if verdict and verdict.get("outcome") == "passed" and verdict.get("inputs_sha256") and digest and verdict["inputs_sha256"] == digest:
            return verdict
        return None

    def transcript(self, turn: str) -> dict | None:
        return self.hooks.transcript(turn)

    # ------------------------------------------------------------ the researcher's actions
    def start(self, provider: str, *, roles: list[str] | None = None, redirect: str | None = None, model=None, effort=None,
              turns: int | None = None, minutes: float | None = None, pursue: bool = False) -> dict:
        """Start a run. `turns` caps this Start's turn budget below `[studio] budget` — a Coordinator's retry gets the node
        budget's remainder, not a fresh budget (ADR-0019 point 18) — and `minutes` its time the same way: what is left of a
        Pursue's one time limit (proof-agents#19). `pursue` is a Coordinator's Start (ADR-0021 point 7):
        a Decomposer's split is the structure the Coordinator works next, not a stop for the researcher, and a Theorem
        split already may be given one more Decomposer turn when a Claim of it is parked (point 9)."""
        unknown = [role for role in (roles or []) if role not in ROLES]  # a role with no brief takes no turn
        if unknown:
            return {"error": f"no brief for the {', '.join(unknown)} role: it cannot take a turn", "code": "INVALID_ROLE"}
        roles = [role for role in AGENT_ROLES if role in (roles or [])]  # the spec's order, whatever order they came in
        alone = [role for role in roles if ROLES[role].alone]  # the Decomposer (ADR-0019 point 20): one turn on its own, on a Theorem not yet split
        if alone and len(roles) > 1:
            return {"error": f"the {alone[0].capitalize()} is started on its own, for one turn: it proposes the split and stops for the researcher",
                    "code": "ROLE_ALONE"}
        if alone:
            refused = self._not_decomposable(resplit=pursue)
            if refused:
                return {"error": refused, "code": "NOT_DECOMPOSABLE"}
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
            turns_max, minutes_max = self.hooks.budget()
            if turns is not None and 0 < int(turns) < turns_max:
                turns_max = int(turns)
            if minutes is not None and 0 < float(minutes) < minutes_max:
                minutes_max = float(minutes)
            name = self.hooks.agent_name(provider)
            self.hooks.assign(name)  # another assignee, a blocked or rejected node: refused here, and no run begins
        except Exception:  # the node could not be assigned (the server answers with the refusal): the slot is given back
            with self._lock:
                if not run.stop:
                    run.state.status = "idle"
            raise
        with self._lock:
            if run.stop:  # stopped and released while the node was being assigned: this Start is over before it began
                run.state.name = name
                # ours to give back — unless a later Start under the same name holds the node now. A later Start that
                # never began, was released, requested review (a review request hands the node over) or gave the node
                # back as it ended (#186) left no claim behind, so what this late assignment made is ours too; one that
                # ended done, stuck or over budget keeps its claim on purpose, and the late assignment made none.
                later = self._run.state
                give_back = (self._run is run or later.status in ("idle", "released") or later.reason == "review-requested"
                             or self._run.given_back)
                if give_back:
                    self._settling += 1  # decided and announced in one breath: a Start arriving now waits for the release
            else:
                give_back = False
                run.state = RunState(status="running", role=roles[0] if roles else "prover", turns_max=turns_max, started_at=time.time(),
                                     deadline=time.time() + minutes_max * 60, name=name, provider=provider, roles=roles,
                                     redirect={"text": redirect, "role": None} if redirect else None, pursue=pursue)
                run.model, run.effort = model, effort
                run.thread = threading.Thread(target=self._loop, args=(run,), name=f"agent-run-{name}", daemon=True)
        if give_back:
            failed = self._give_back(run, name, "late assignment given back")  # the assignment it just made
            return {**self.view(), **(failed or {})}
        if run.stop:
            return self.view()
        run.thread.start()
        return self.view()

    def work_log(self) -> list[dict]:
        return self.hooks.work_log()

    def review_now(self) -> dict:
        """Review what it has: a snapshot of the folder as it stands, frozen through the project's own request-review.
        A review request hands the node over, so a successful freeze ends the run — paused or running — and nothing
        resumes it: the researcher's review is what happens next (audit P4)."""
        record = self.hooks.review_now()
        with self._lock:
            run = self._run
            ended = self.active()
            job = run.job if ended else None
            role, name = run.state.role or "prover", run.state.name
            if ended:
                run.stop = True
                run.pause = False
                run.state.status, run.state.reason = "done", "review-requested"
                run.state.paused_at = None
                self._wake.notify_all()
        if job is not None and not job.done:
            self.agent.stop(job.id)
        if ended:  # the run's last word, as on every stop
            self._close_note(run, role, name, "done", "review-requested")
        return record

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

    def release(self, reason: str = "stopped and released by the researcher", *, expected_started_at: float | None = None) -> dict:
        """Release the current Start, or only the named Start for a Coordinator. Checking its identity and stopping it
        happen under the same lock, so a later researcher Start cannot be released in its place."""
        with self._lock:
            # the run's own give-back, under way (#186), decides whether this one retries: wait for its outcome first, and
            # only then read which Start is current — the wait lets go of the lock, and a new Start may begin meanwhile
            deadline = time.monotonic() + SETTLE_WAIT
            while self._run.given_back and self._settling:
                left = deadline - time.monotonic()
                if left <= 0:  # still under way: no release happened here, and none is reported
                    return {"status": self._run.state.status, "error": "the run is still giving the node back; Stop again in a moment",
                            "code": "RUN_SETTLING"}
                self._wake.wait(min(0.05, left))
            run = self._run
            if expected_started_at is not None and run.state.started_at != expected_started_at:
                return {"skipped": True, "reason": "a later Start owns this node"}
            was, name, job, role = run.state.status, run.state.name, run.job, run.state.role or "prover"
            run.stop = True
            run.pause = False
            run.state.status = "released"
            run.state.reason = reason
            run.state.paused_at = None
            gives_back = was not in ("idle", "released", "starting") and not run.given_back  # a Start still assigning gives its assignment back itself
            if gives_back:
                self._settling += 1
            self._wake.notify_all()
        if job is not None and not job.done:
            self.agent.stop(job.id)
        if was in ("running", "pausing", "paused"):  # the run's last word: an ended run already left its own
            self._close_note(run, role, name, "released", reason)
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
                run.given_back = False  # nothing was given back: the next Stop tries again
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
                # the mechanical checks of the folder as it stands now (issue #180), read after any pause and before the role is chosen:
                # the researcher may have edited since the last turn ended, or while the run waited, so no earlier result is reused;
                # an exception keeps the Verifier's gate shut, never opens it
                checks, checks_error = self._checks()
                with self._lock:
                    run.checks, run.checks_error = checks, checks_error
                    if run.stop:
                        return
                    if run.pause:  # paused while the checks ran: wait, then read them again
                        continue
                    state = run.state
                    if state.turns >= state.turns_max or (state.deadline and time.time() >= state.deadline):
                        ending = ("budget", f"the budget of this Start is spent ({state.turns} turn(s))")
                    else:
                        ending = None
                        role = self._next_role(run)
                        if role == "verifier" and run.checks_error:
                            ending = ("stuck", f"the mechanical checks could not run, so the Verifier was not called: {run.checks_error}")
                        state.role = role
                        if role == "verifier":
                            run.verify_wanted = False  # the Verifier takes the turn the cycle meant for it
                        redirect = None
                        if state.redirect and state.redirect.get("role") in (None, role):
                            redirect, state.redirect = state.redirect["text"], None
                        provider, name = state.provider, state.name
                if ending:
                    self._end(run, *ending)
                    return
                # the briefing (ADR-0019 point 9) and the Prover's gate (point 3), read off the record before the turn
                log_before = self.hooks.work_log()
                digest, text_now = self._inputs_now()
                gate = self._gate(log_before, digest) if role == "prover" else None
                with self._lock:
                    run.gate_hash, run.gate_note = (gate.get("inputs_sha256"), gate.get("note") or "") if gate else (None, "")
                prompt = self._prompt(run, role, redirect, log=log_before, digest=digest, gate=gate, text_now=text_now)
                before = len(log_before)
                turn = {"turn": uuid.uuid4().hex[:16], "role": role, "by": name, "provider": provider}  # the record (the core's record_agent_turn fields)
                began: list = []

                def begin(job, turn=turn, began=began):  # the turn exists and its backend is about to start
                    began.append(job)
                    self._note_turn(run, {**turn, "phase": "started", "job": job.id})

                started = self._start_turn(run, prompt, provider, {"role": role, "name": name, "redirect": redirect, "review_gate": gate.get("inputs_sha256") if gate else None,
                                                                    "pursue": run.state.pursue}, begin)
                if started is None or "error" in started:
                    if began:  # it began and was stopped at once: close its marker
                        self._note_turn(run, {**turn, "phase": "ended", "job": None})
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
                changed_files = _changed_files(job)
                digest_after, text_after = self._inputs_now()  # one read: what the researcher's edit, if one comes, is diffed against
                checks, checks_error = self._checks()  # the mechanical checks of the folder as the turn left it (issue #180)
                with self._lock:  # what this turn did, for the next role's choice and the researcher's-edit mark (ADR-0019)
                    run.last_role = role
                    run.last_changed_tex = any(str(c.get("path") or "").endswith(".tex") for c in changed_files)
                    run.last_verdict = any(e.get("kind") == "verdict" for e in new)
                    run.inputs_after_turn, run.inputs_text_after_turn = digest_after, text_after
                    run.checks, run.checks_error = checks, checks_error
                self._note_turn(run, {**turn, "phase": "ended", "job": job.id, "step": steps[-1] if steps else None,
                                 "session_id": next((e["session_id"] for e in reversed(job.events) if e.get("session_id")), None),
                                 "events": [e for e in job.events if e.get("t") != "delta"],  # the text events hold the whole text
                                 "prompt": prompt, "changed": changed_files})
                self._suggest(run, role, name, log)  # what the record now repeats, for the researcher (ADR-0019 point 17)
                with self._lock:
                    run.job = None
                    run.state.job = run.state.turn = None
                    if run.stop:
                        return
                    run.state.turns += 1
                    roles = list(run.state.roles)
                done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
                run.handoff = next((e for e in reversed(new) if e.get("kind") == "handoff"), None)
                run.last_report = next((e for e in reversed(new) if e.get("kind") == "step"), None)
                with self._lock:  # the cycle's intent (issue #180): once it means to verify, it verifies as soon as the checks pass
                    if self._proposed_role(run) == "verifier" and "verifier" in self._allowed(run):
                        run.verify_wanted = True
                # a decision only the researcher can make comes first — before the budget, too (audit P2-2): a review request
                # in the same turn stands as it is, but the run stops for the decision, which would otherwise be lost
                budget_note = f" (the time budget of this Start ended the turn, after {run.state.turns} turn(s))" if over_budget else ""
                # a Decomposer's split proposed hands the Theorem back (#186): it is proven once its children are Accepted,
                # by whichever Start comes then — a Coordinator's too, which would not take over a claim it did not make
                split = [e for e in new if e.get("kind") == "split"] if role == "decomposer" else []
                # under Pursue too (ADR-0021 point 8): the pursued Decomposer's brief keeps needs-human for a contradiction in
                # the node's own statement or a fact only the researcher knows, so a split in the same turn does not answer it
                asked = next((e for e in reversed(new) if e.get("kind") == "step" and e.get("status") == "needs-human"), None)
                if asked is not None:
                    self._end(run, "needs-human", (asked.get("note") or "a decision only the researcher can make") + budget_note, give_back=bool(split))
                    return
                if split and run.state.pursue:  # ADR-0021 point 7: under Pursue the split is the structure worked next
                    children = [child for e in split for child in (e.get("nodes") or [])]
                    reason = f"split into {len(children)} Claim(s): {', '.join(children)}; the Coordinator works them" + budget_note
                    self._end(run, "done", reason, give_back=True)
                    return
                if split:  # ADR-0019 point 20: a split proposed is a decision for the researcher, whether or not the turn said so
                    children = [child for e in split for child in (e.get("nodes") or [])]
                    reason = f"structure proposed ({len(children)} Claim(s): {', '.join(children)}); the researcher decides" + budget_note
                    self._close_note(run, role, name, "needs-human", reason)  # the turn left no needs-human step of its own: the run's is the last word
                    self._end(run, "needs-human", reason, give_back=True)
                    return
                if over_budget:
                    self._end(run, "budget", f"the time budget of this Start is spent ({run.state.turns} turn(s), the last one stopped)")
                    return
                requested = next((e for e in new if e.get("kind") == "review-requested"), None)
                if requested is not None:
                    self._record_gating_verdict(run, requested)  # ADR-0019 point 4: the verdict that gated it, as an Evidence check
                    self._end(run, "done", "review-requested")
                    return
                stuck = next((e for e in reversed(new) if e.get("kind") == "step" and e.get("status") == "stuck"), None)
                if stuck is not None:
                    self._end(run, "stuck", stuck.get("note") or "the agent reported it is stuck")
                    return
                # a turn the CLI itself could not finish — it exited non-zero, or reported an error (a model the account
                # can't use, a login that lapsed) — is no work done: the run is stuck and says why, never "done" (#171)
                if done.get("is_error") or done.get("exit") not in (None, 0):
                    self._end(run, "stuck", f"the {role} turn failed: {failure_reason(done, job.events)[:200]}")
                    return
                if len(roles) == 1:  # a single role was asked for: one turn
                    self._end(run, "done", "turn-finished")
                    return
                failed = _check_errors(checks)
                if failed and role in ("typesetter", "prover") and run.verify_wanted:  # sent back on the checks (issue #180), not to the Verifier
                    codes = tuple(sorted({str(f.get("code")) for f in failed}))
                    with self._lock:  # the count is of the same failures in a row: a new set of failures is a new count
                        run.sent_back = run.sent_back + 1 if codes == run.sent_back_on else 1
                        run.sent_back_on = codes
                        sent_back = run.sent_back
                    self._close_note(run, role, name, "done", f"mechanical checks failed ({len(failed)}): " + "; ".join(f"{f.get('code')}: {f.get('message')}" for f in failed)[:600])
                    if sent_back >= CHECK_TURNS:
                        self._end(run, "stuck", f"the same mechanical checks still fail after {sent_back} turn(s): " + ", ".join(codes))
                        return
                elif not failed:
                    with self._lock:
                        run.sent_back, run.sent_back_on = 0, ()
                if roles and roles[0] != "prover" and role == roles[0] and self._handed_to(run) is None:
                    # several roles without the Prover: nobody decides to go on once the first hands nothing over
                    self._end(run, "done", "turn-finished")
                    return
                # a run: a computation or a compile in a shell, or a compile through the compile tool (the Typesetter's)
                ran = any(e.get("t") == "tool" and (e.get("name") == "Compile" or (e.get("name") == "Bash" and is_a_run(str(e.get("summary") or ""))))
                          for e in job.events)
                changed = bool(done.get("changed")) or ran or any(e.get("kind") in _CHANGES for e in new)
                idle_turns = 0 if changed else idle_turns + 1
                if idle_turns >= STUCK_TURNS:
                    self._end(run, "stuck", f"no change in {idle_turns} turn(s)")
                    return
        except Exception as exc:  # noqa: BLE001 — the run ends, and says why
            self._end(run, "stuck", f"{type(exc).__name__}: {exc}")

    def _note_turn(self, run: _Start, turn: dict) -> None:
        try:
            self.hooks.record_turn(turn)
        except Exception as exc:  # noqa: BLE001 — the record is the log's; the run goes on without it, and says so
            self._record_failed(run, "_note_turn", "record_turn", exc)

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

    def _record_gating_verdict(self, run: _Start, requested: dict) -> None:
        """A review request that the Prover's gate let through (ADR-0019 point 4): the run asks the host to record the gating
        verdict as an Evidence check on the snapshot just frozen, by the verdict's hash; the host compares it with the
        snapshot's manifest hash and records nothing on a mismatch. The run itself writes nothing, and asks once."""
        with self._lock:
            gate_hash, gate_note, name = run.gate_hash, run.gate_note, run.state.name
            run.gate_hash, run.gate_note = None, ""
        proof_id = requested.get("candidate_proof_id")
        if self.hooks.record_evidence is None or gate_hash is None or not proof_id:
            return
        try:
            recorded = self.hooks.record_evidence(proof_id, "passed", run_by=f"{name}/verifier", notes=gate_note, inputs_sha256=gate_hash)
        except Exception as exc:  # noqa: BLE001 — the check is advisory (ADR-0004); the review request stands
            recorded = f"{type(exc).__name__}: {exc}"
        if recorded is not True:  # the work log says why (ADR-0019 point 4): a str is the host's reason, False its silence
            why = recorded if isinstance(recorded, str) and recorded else "the snapshot's digest is not the verdict's"
            self._close_note(run, "prover", name, "done", f"the Verifier's verdict was not recorded as an Evidence check on the snapshot: {why}")

    def _allowed(self, run: _Start) -> tuple[str, ...]:
        """The roles this Start runs: those asked for, else the cycle — every role with a brief but the Decomposer, which is
        started alone (ADR-0019 point 20); a `--handoff decomposer` in a whole run hands to nobody."""
        return tuple(run.state.roles) or CYCLE_ROLES

    def _not_decomposable(self, *, resplit: bool = False) -> str | None:
        """Why a Decomposer may not be started on this node (ADR-0019 point 20): it is not a Theorem or Lemma, or it is split
        already (it rests on something) — unless `resplit`, a Coordinator's one more turn on a parent whose Claim is parked
        (ADR-0021 point 9). None when it may; also without a node brief, when the host says nothing of the node."""
        brief = self._node_brief()
        kind = brief.get("kind")
        if kind is not None and kind not in DECOMPOSABLE_KINDS:
            return f"the Decomposer proposes a Theorem's split; {brief.get('node_id') or 'this node'} is a {kind}"
        # split already: it has children (point 20's "no children": the Claims a split made, `split_child`); a host that does
        # not say which dependencies are children is read as if every one were. An ordinary premise is no child.
        dependencies = list(brief.get("dependencies") or [])
        children = [dep for dep in dependencies if dep.get("split_child")] if any("split_child" in dep for dep in dependencies) else dependencies
        if children and not resplit:
            resting = ", ".join(str(dep.get("id")) for dep in children)
            return f"the Decomposer works a Theorem not yet split; {brief.get('node_id') or 'this node'} is split already (it rests on {resting}) — start a Coordinator instead"
        return None

    def _handed_to(self, run: _Start) -> str | None:
        """The role the last turn handed the work to, when that role is part of this Start."""
        to = run.handoff.get("to") if run.handoff else None
        return to if to in self._allowed(run) else None

    def _next_role(self, run: _Start) -> str:
        """Who takes the next turn (ADR-0019 point 6): the role handed off to, when this Start runs it; else, after a
        Typesetter turn that changed a .tex file, the Verifier — what will be frozen is the LaTeX; after a verdict, the
        Prover; else the first role this Start runs — the Prover for the whole flow. The Verifier is gated on the mechanical
        checks (issue #180): while they fail, the Typesetter (or the Prover) takes the turn instead, briefed with them."""
        allowed = self._allowed(run)
        if run.verify_wanted and "verifier" in allowed:
            if _check_errors(run.checks):
                for owner in ("typesetter", "prover"):
                    if owner in allowed:
                        return owner
            return "verifier"  # with checks_error set, the loop ends the run instead of starting this turn
        return self._proposed_role(run)

    def _proposed_role(self, run: _Start) -> str:
        handed = self._handed_to(run)
        if handed:
            return handed
        allowed = self._allowed(run)
        if run.last_role == "typesetter" and run.last_changed_tex and "verifier" in allowed:
            return "verifier"
        if run.last_verdict and "prover" in allowed:
            return "prover"
        return allowed[0]

    def _checks(self) -> tuple[list[dict] | None, str | None]:
        """The mechanical checks through the host (issue #180): (findings, None); (None, None) without the hook — the cycle runs
        as before; (None, why) when the configured hook failed — the Verifier's gate stays shut and the run says why."""
        if self.hooks.check_inputs is None:
            return None, None
        try:
            return list(self.hooks.check_inputs() or []), None
        except Exception as exc:  # noqa: BLE001 — a check that cannot run must not read as a check that passed
            return None, f"{type(exc).__name__}: {exc}"

    def _prompt(self, run: _Start, role: str, redirect: str | None, *, log: list[dict] | None = None, digest: str | None = None,
                gate: dict | None = None, text_now: dict | None = None) -> str:
        """The turn's prompt: its charge, what this Start runs, and the briefing built from the record (ADR-0019 point 9)."""
        label = lambda name: name.capitalize()  # noqa: E731
        parts = [f"Take your turn as the {label(role)} on this node. Report your plan or your step with `proof node progress`, and end the turn when the step is done or handed over."]
        allowed = self._allowed(run)
        if len(allowed) == 1:
            parts.append(f"This Start runs only the {label(role)}, for this one turn.")
        elif len(allowed) < len(AGENT_ROLES):
            parts.append(f"This Start runs only the {' and the '.join(label(r) for r in allowed)}: hand work only to them.")
        if run.handoff and run.handoff.get("to") not in allowed and run.handoff.get("to") != role:
            parts.append(f"The {label(str(run.handoff.get('to')))} is not part of this Start; carry on without it.")
        if role == "prover":
            parts.append("The Verifier passed the files as they stand: you may request review this turn." if gate else
                         "You may not request review this turn: no verdict passed the files as they stand. Hand to the Verifier when the draft is complete.")
        parts.append(self._briefing(run, role, redirect, log if log is not None else [], digest, text_now))
        return "\n\n".join(part for part in parts if part)

    def _briefing(self, run: _Start, role: str, redirect: str | None, log: list[dict], digest: str | None, text_now: dict | None = None) -> str:
        """What the run knows for this turn, gathered through the hooks and written by briefing.py (ADR-0019 point 9)."""
        brief = self._node_brief()
        with self._lock:
            run.node_id = brief.get("node_id") or run.node_id
            inputs_before = run.inputs_text_after_turn
            checks = list(run.checks) if run.checks is not None else None
        shared = self._shared()
        verdict = self._newest_verdict(log)
        handoff = run.handoff if run.handoff and run.handoff.get("to") == role else None
        report = run.last_report if not handoff and run.last_report and run.last_report.get("role") not in (None, role) else None
        # the researcher's edits (point 21): the inputs differ from the digest at the previous turn's end, and no role's turn
        # did it; with the files' text from then and now, their diff, else the fact alone
        changed = bool(digest and run.inputs_after_turn and digest != run.inputs_after_turn)
        diff = inputs_diff(inputs_before, text_now) if changed and inputs_before is not None and text_now is not None else None
        return build_briefing(BriefingParts(
            role=role, node_id=brief.get("node_id") or "", statement=brief.get("statement"), dependencies=list(brief.get("dependencies") or []),
            definitions=list(brief.get("definitions") or []),
            redirect=redirect, handoff=handoff, report=report,
            questions=questions_from(log),  # the choices made instead of stopping, and the researcher's redirects of them (ADR-0021 point 8)
            verdict={**verdict, "stale": bool(digest) and verdict.get("inputs_sha256") != digest} if verdict else None,
            attempts=_attempts_from(log),  # the record, and what the run derives from it (ADR-0019 point 7)
            inputs_changed=changed, inputs_diff=diff,
            shared=shared,
            checks=checks,  # issue #180: the errors first for a role sent back, "passed" for the Verifier
            files={name: text for name, text in (text_now or {}).items() if name in BRIEFED_FILES and isinstance(text, str)} if role in ("verifier", "typesetter") else {},
        ))

    def _node_brief(self) -> dict:
        """The node as the host describes it (statement, kind, dependencies); {} without the hook or when it fails."""
        if self.hooks.node_brief is None:
            return {}
        try:
            return dict(self.hooks.node_brief() or {})
        except Exception:  # noqa: BLE001 — the briefing is the richer for it, not conditional on it
            return {}

    def _inputs_now(self) -> tuple[str | None, dict | None]:
        """The working inputs now, in one read: their digest and their text (working_inputs), the two of the same read, so
        the text kept at a turn's end is the text its digest is of (audit P2-3). Without the hook, or when it fails or
        gives no digest, the digest alone (inputs_digest) and no text: the briefing then says the inputs changed and no more."""
        if self.hooks.working_inputs is not None:
            try:
                got = self.hooks.working_inputs() or {}
                if got.get("digest"):
                    return str(got["digest"]), dict(got.get("files") or {})
            except Exception:  # noqa: BLE001 — an unreadable folder: no text, no diff
                pass
        return self._digest(), None

    @staticmethod
    def _attempts_from_log(log: list[dict]) -> list[dict]:
        return _attempts_from(log)

    def _shared(self) -> list[dict]:
        """Part C's shared entries through the host, newest first within each source; none without the hook or when it fails."""
        if self.hooks.shared_notes is None:
            return []
        try:
            return list(self.hooks.shared_notes() or [])
        except Exception:  # noqa: BLE001 — the briefing is the richer for it, not conditional on it
            return []

    def _suggest(self, run: _Start, role: str, name: str, log: list[dict]) -> None:
        """A pattern the record shows — the same objection three times, the same dead end here and on another node — is
        surfaced once in the work log as a suggested redirect for the researcher, who decides (ADR-0019 point 17). No
        role is told; nothing is rebriefed or reallocated by it. A suggestion already in the log (an earlier Start's,
        by its unchanging mark: the count in the text grows) is not said again, but the page is shown it."""
        with self._lock:
            node_id = run.node_id
        found = suggested_redirects(log, self._shared(), node_id=node_id)
        if not found:
            return
        said = " ".join(str(e.get("note") or "") for e in log if e.get("kind") == "step" and "suggested redirect:" in str(e.get("note") or ""))
        for suggestion in found:
            with self._lock:
                if suggestion["key"] in run.suggested:
                    continue
                run.suggested.add(suggestion["key"])
                run.state.suggestion = suggestion["text"]
            note = f"suggested redirect: {suggestion['text']}"
            if suggestion["mark"] not in said:
                try:
                    self.hooks.record_close(role, name, "done", note)
                except Exception as exc:  # noqa: BLE001 — the page still shows it; the record is a courtesy here
                    self._record_failed(run, "_suggest", "record_close", exc)

    def _end(self, run: _Start, status: str, reason: str, *, give_back: bool = False) -> None:
        """Close this Start, and leave its last word in the work log: a progress note on every stop — except a decision,
        whose own needs-human step, the role's, is already that last word. With `give_back`, the node is released too,
        decided under the same lock as the end, so a release arriving after it has nothing left to give."""
        with self._lock:
            if run.stop:
                return
            run.state.status, run.state.reason = status, reason
            if status == "needs-human":
                run.state.decision = reason
            role, name = run.state.role or "prover", run.state.name
            if give_back:
                run.given_back = True
                self._settling += 1
        if status != "needs-human":
            self._close_note(run, role, name, status, reason)
        if give_back:
            self._give_back(run, name, reason)

    def _close_note(self, run: _Start, role: str, name: str, status: str, reason: str) -> None:
        try:
            self.hooks.record_close(role, name, _CLOSING.get(status, "done"), f"run {status}: {reason}")
        except Exception as exc:  # noqa: BLE001 — the note is a courtesy; the state is the record, and says it failed
            self._record_failed(run, "_close_note", "record_close", exc)

    def _record_failed(self, run: _Start, site: str, hook: str, exc: Exception) -> None:
        """A work-log write of `run` failed: kept on that Start's state, never written through the hook that failed. A
        late failure of an earlier Start lands on its own state, not on the Start that follows it (proof-agents#16)."""
        with self._lock:
            run.state.record_failed[site] = f"{hook}: {type(exc).__name__}: {exc}"
