"""The Coordinator: a Theorem's or Lemma's subtree worked by node runs (ADR-0019 points 18 and 19, ADR-0021 Pursue).

Started on a Theorem or Lemma from the map, it holds no node and takes no turn — Pursue, the researcher's one action
(ADR-0021 point 7). A Theorem with no Claims yet is given a Decomposer turn first, whose split is the structure worked
next. It starts node runs on the frontier within the subtree — the nodes whose dependencies are each Accepted or
Provisional — up to `[studio] parallel` at a time; a node's run briefs its own turns (point 9). A run that ends
without a snapshot for review (stuck, out of its turns, sent back for revision) is started again, whatever its last
verdict, until the node's budget (one Start's turns) is spent; then the node is **parked**, and the rest of the
subtree goes on. A parked Claim gives its parent one more Decomposer turn, once per parent (ADR-0021 point 9). A
parent starts once every child is Accepted or Provisional; the Coordinator never waits for a Review decision. It
never requests review, never Accepts, and stops when the subtree's root is requested for review (or Accepted), when
its budget — the sum of the node budgets it may spend — is spent, or when nothing open is left to work: every open
node parked, or resting on what no run will settle.

`ProjectPursuit` is Pursue on a project with no map yet: a Reader turn states the draft as a map, then each Theorem
the Reader stated is pursued by a Coordinator, one after another.

When a node in its subtree is Accepted it redirects the runs of that node's dependents with one line naming the
node and its key ideas (point 19): the sole cross-node push, on the existing Redirect channel, read at the next turn.

The researcher's actions: Start, Pause (no new node run begins; the running ones pause after their turn), Resume,
and Stop and release (every node run it started is released). It is the only thing besides the researcher that
starts a run. What it does is recorded on the root's work log as `coordinator` notes, through the host.

Like AgentRun, it knows nothing of the proof map itself: the host (proof-web's hub) gives it the subtree as it
stands, each node's run, the budgets and the record, through `CoordinatorHooks`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

ACTIONS = ("start", "pause", "resume", "release")
ACTIVE = ("starting", "running", "paused")
RUN_ACTIVE = ("starting", "running", "pausing", "paused")   # a node run's statuses while it holds the node's slot
ENDED_RESTARTABLE = ("stuck", "budget")   # a node run that ended so is started again while the node budget lasts, whatever its verdict (ADR-0021 point 9)
ENDED_FOR_GOOD = ("needs-human", "refused")   # a node run that ended so is not: the node is parked at once (needs-human stops the node, not the subtree)
SPLIT_REASON = "split into"                # how a pursued Decomposer's run that split the node ends (agent_run.py)
DECOMPOSABLE = ("theorem", "lemma")        # what a Decomposer turn is given to (ADR-0019 point 20)
TICK = 0.5                                 # seconds between the Coordinator's looks at the subtree


@dataclass
class CoordinatorHooks:
    """What a Coordinator needs from the project, as callables."""

    # the subtree as it stands: the root and every node it rests on, transitively, each
    # {"id", "kind", "statement", "dependencies": [...], "accepted": bool, "workflow": open|claimed|review-needed|revision-requested|blocked,
    #  "claimed_by": str | None, "key_ideas": str | None, "has_run": bool (a local node a run can work),
    #  ADR-0021 (optional; a host without them reads as before):
    #  "provisional": bool (proof_map.is_provisional: rested on for work), "awaiting_review": bool (a snapshot awaits the
    #  researcher, Blocked or not: the workflow axis hides it under `blocked`), "split_children": [ids] (the Claims a Split made)}
    subtree: Callable[[], list[dict]]
    run: Callable[[str], object]                       # the node's AgentRun (made on demand, no page needed); raises when it has none
    budget: Callable[[], tuple[int, float]]            # one node run's (turns, minutes): the node budget
    parallel: Callable[[], int]                        # how many node runs at once
    agent_name: Callable[[str], str] = lambda provider: provider   # provider -> the name the runs work under
    record: Callable[[str], None] = lambda note: None  # a `coordinator` note on the root's work log
    # (node id, reason): the node is parked (ADR-0021 point 9) — the host records it on the node's work log, where the review
    # queue reads it with the node's attempts
    park: Callable[[str, str], None] = lambda node_id, reason: None


@dataclass
class CoordinatorState:
    status: str = "idle"       # idle | starting | running | paused | done | stuck | budget | released | release-failed
    reason: str = ""
    root: str | None = None
    provider: str = ""
    name: str = ""
    turns: int = 0             # turns spent by the runs it started, all Starts counted
    turns_max: int = 0         # the sum of the node budgets it may spend
    started_at: float | None = None
    # node id -> {"starts", "turns" (over every Start), "idle_starts" (Starts that ended before any turn counted), "last" (the last
    # run's ending), "verdict", "started_at" (the run's, as its view says it: what tells this Coordinator's Start of the run from a
    # later owner's)}
    nodes: dict = field(default_factory=dict)
    running: list = field(default_factory=list)  # node ids whose run is active now
    accepted: list = field(default_factory=list)  # accepted nodes of the subtree, as last seen
    redirected: list = field(default_factory=list)  # accepted nodes whose dependents' runs were redirected (point 19)
    parked: dict = field(default_factory=dict)      # node id -> why it is parked (ADR-0021 point 9), as this Start parked it
    decomposed: list = field(default_factory=list)  # nodes given a Decomposer turn by this Start: the root unsplit, a parent of a parked Claim
    resplit: list = field(default_factory=list)     # parents given their one further Decomposer turn for a parked Claim (point 9)
    # node id -> why it is the researcher's now: they stopped and released its run, or its run ended done without a review
    # request. This Start never starts it again (it is not parked: the agents did not fail there; the researcher took it)
    held: dict = field(default_factory=dict)


class Coordinator:
    def __init__(self, hooks: CoordinatorHooks, root: str, *, tick: float = TICK) -> None:
        self.hooks = hooks
        self.root = root
        self.tick = tick
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self.state = CoordinatorState(root=root)
        self._thread: threading.Thread | None = None
        self._stop = False
        self._pause = False
        self._releasing = False  # a Stop doing its releases outside the lock: a new Start must wait for it
        self._spent: dict[str, int] = {}     # node id -> turns of its earlier Starts (the current run's turns are read live)
        self._seen: dict[str, int] = {}      # node id -> the current run's turns as last read
        self._counted: set[str] = set()      # the open nodes the Coordinator's budget is the sum over
        self._resplits: dict[str, str] = {}  # parent id -> the redirect of its further Decomposer turn, due and not started yet
        # non-root nodes to work again though a snapshot of theirs awaits review: a dependency they were worked on was sent
        # back and is being worked again, so their proof is Potentially stale (ADR-0021 point 4)
        self._redo: set[str] = set()

    # ------------------------------------------------------------ what it is
    def active(self) -> bool:
        return self.state.status in ACTIVE

    def view(self) -> dict:
        with self._lock:
            state = CoordinatorState(**{**vars(self.state), "nodes": {node_id: dict(entry) for node_id, entry in self.state.nodes.items()}, "running": list(self.state.running),
                                        "accepted": list(self.state.accepted), "redirected": list(self.state.redirected),
                                        "parked": dict(self.state.parked), "decomposed": list(self.state.decomposed),
                                        "resplit": list(self.state.resplit), "held": dict(self.state.held)})
            settling = self._releasing or (state.status not in ACTIVE and self._thread is not None and self._thread.is_alive())
        can_release = state.status in (*ACTIVE, "release-failed") or (
            state.status not in ("idle", "released") and any(self._owned_run(node_id, entry.get("started_at")) for node_id, entry in state.nodes.items()))
        return {"status": state.status, "active": state.status in ACTIVE, "reason": state.reason, "root": state.root, "provider": state.provider,
                "name": state.name, "turns": state.turns, "turns_max": state.turns_max, "started_at": state.started_at,
                "running": state.running, "accepted": state.accepted, "nodes": state.nodes, "settling": settling, "can_release": can_release,
                "parked": [{"node": node_id, "reason": reason} for node_id, reason in state.parked.items()],
                "decomposed": state.decomposed, "resplit": state.resplit, "needs_you": self._needs_you(state),
                "held": [{"node": node_id, "reason": reason} for node_id, reason in state.held.items()]}

    def _needs_you(self, state: CoordinatorState) -> list[dict]:
        """The nodes this Coordinator parked (ADR-0021 point 9): stuck or out of budget once the node budget was spent, or
        stopped on a decision only the researcher can make, or refused a run. The rest of the subtree went on without
        them; each is where the agents could not go, for the researcher's review queue, with why."""
        return [{"node": node_id, "last": (state.nodes.get(node_id) or {}).get("last"), "reason": reason} for node_id, reason in state.parked.items()]

    # ------------------------------------------------------------ the researcher's actions
    def start(self, provider: str) -> dict:
        with self._lock:
            if self.state.status in ACTIVE:
                return {"error": "a Coordinator is already working this subtree; pause or stop it", "code": "COORDINATOR_ACTIVE"}
            if self.state.status == "release-failed":  # what the last Stop could not give back is still this Coordinator's to release
                return {"error": f"the last Stop left node(s) assigned ({self.state.reason}); Stop again before a new Start", "code": "RELEASE_FAILED"}
            if self._releasing or (self._thread is not None and self._thread.is_alive()):
                return {"error": "the previous Coordinator Start is still finishing; Start again after it settles", "code": "COORDINATOR_ACTIVE"}
            if any(self._owned_run(node_id, entry.get("started_at")) for node_id, entry in self.state.nodes.items()):
                return {"error": "the previous Coordinator Start still holds nodes; Stop and release them before a new Start", "code": "COORDINATOR_ACTIVE"}
            try:
                subtree = self.hooks.subtree()
            except Exception as exc:  # noqa: BLE001 — no subtree, no Start
                return {"error": f"{type(exc).__name__}: {exc}", "code": "NO_SUBTREE"}
            open_nodes = [node for node in subtree if node.get("has_run") and not node.get("accepted")]
            if not open_nodes:
                return {"error": "nothing in this subtree is open: every node is Accepted, or none has a proof to write", "code": "NOTHING_OPEN"}
            turns, _ = self.hooks.budget()
            self.state = CoordinatorState(status="starting", root=self.root, provider=provider, name=self.hooks.agent_name(provider),
                                          turns_max=turns * len(open_nodes), started_at=time.time(),
                                          accepted=[node["id"] for node in subtree if node.get("accepted")])
            self._stop = self._pause = False
            self._spent, self._seen, self._resplits, self._redo = {}, {}, {}, set()
            self._counted = {node["id"] for node in open_nodes}   # the open nodes the budget counts; a split adds its Claims
            self._thread = threading.Thread(target=self._loop, name=f"coordinator-{self.root}", daemon=True)
            self._thread.start()
        self._record(f"started on {self.root}: {len(open_nodes)} open node(s), up to {self.hooks.parallel()} run(s) at a time, {turns * len(open_nodes)} turns in all")
        return self.view()

    def pause(self) -> dict:
        with self._lock:
            if self.state.status not in ACTIVE:
                return {"error": "no Coordinator is working this subtree", "code": "NO_COORDINATOR"}
            self._pause = True
            self.state.status = "paused"
            running = list(self.state.running)
        for node_id in running:  # the running ones finish their turn, then hold (point 18)
            self._on_run(node_id, lambda run: run.pause())
        self._record("paused: no new node run begins; the running ones hold after their turn")
        return self.view()

    def resume(self) -> dict:
        with self._lock:
            if self.state.status != "paused":
                return {"error": "the Coordinator is not paused", "code": "NOT_PAUSED"}
            self._pause = False
            self.state.status = "running"
            running = list(self.state.running)
            self._wake.notify_all()
        for node_id in running:  # the runs Pause held; one that ended meanwhile is not started again by this
            view = self._view_of(node_id) or {}
            if view.get("status") in ("paused", "pausing"):
                self._on_run(node_id, lambda run: run.resume())
        self._record("resumed")
        return self.view()

    def release(self) -> dict:
        """Stop and release: every node run this Start made is released (point 18) — the running ones, and the ended ones
        whose claim a run keeps on purpose (stuck, over budget, a turn finished) — never a later owner's run on the same
        node. A release that fails is not a release: the Coordinator says so (`release-failed`, RELEASE_FAILED) and keeps
        what it owns, so Stop can be tried again."""
        with self._lock:
            if self._releasing:
                return {"error": "the Coordinator is still releasing its runs; wait for this Stop to finish", "code": "COORDINATOR_ACTIVE"}
            if self.state.status in ("idle", "released"):
                return {"error": "no Coordinator is working this subtree", "code": "NO_COORDINATOR"}
            self._releasing = True
            self._stop = True
            self._pause = False
            self.state.status, self.state.reason = "released", "stopped and released by the researcher"
            running = list(self.state.running)
            owned = {node_id: entry.get("started_at") for node_id, entry in self.state.nodes.items() if entry.get("started_at") is not None}
            self.state.running = []
            self._wake.notify_all()
        released, failed = [], []
        try:
            for node_id in sorted(set(running) | set(owned)):
                if node_id in running and node_id not in owned:
                    continue  # reserved, its Start under way: the Start's own late-stop path releases it (and says if that fails)
                if not self._owned_run(node_id, owned.get(node_id)):
                    continue
                answer = self._answer_of(node_id, lambda run: run.release("the Coordinator was stopped and released", expected_started_at=owned[node_id]))
                if "error" in answer:
                    failed.append(f"{node_id}: {answer.get('error')}")
                elif not answer.get("skipped"):
                    released.append(node_id)
            if failed:
                with self._lock:
                    self.state.status = "release-failed"
                    self.state.reason = "the node(s) are still assigned: " + "; ".join(failed)
        finally:
            with self._lock:
                self._releasing = False
        if failed:
            self._record(f"stop and release failed on {len(failed)} run(s): " + "; ".join(failed) + " — try Stop again")
            return {"error": self.state.reason, "code": "RELEASE_FAILED", **self.view()}
        self._record(f"stopped and released; released the run(s) on {', '.join(released) or 'no node'}")
        return self.view()

    # ------------------------------------------------------------ the loop
    def _loop(self) -> None:
        with self._lock:
            if self._stop:
                return
            if not self._pause:  # a Pause that came before the thread ran stands
                self.state.status = "running"
        try:
            while True:
                with self._lock:
                    if self._stop:
                        return
                    while self._pause and not self._stop:
                        self._wake.wait(self.tick)
                    if self._stop:
                        return
                ending = self._step()
                if ending is not None:
                    self._end(*ending)
                    return
                with self._lock:
                    if self._stop:
                        return  # Stop during _step already woke us; do not wait for another tick
                    self._wake.wait(self.tick)
        except Exception as exc:  # noqa: BLE001 — the Coordinator ends, and says why; the node runs go on by themselves
            self._end("stuck", f"{type(exc).__name__}: {exc}")

    def _step(self) -> tuple[str, str] | None:
        """One look at the subtree: the redirects an Acceptance calls for, the turns spent, the nodes to park, the runs to
        start; or why to end."""
        # the runs that ended since are noted first, their turns counted — and before the map is read (#15): a Decomposer
        # seen ended has written its split, so the map read next has its new Claims for `_park` to hold; one not seen
        # ended yet is still running here, and `_split_by_running` keeps them
        running = self._running()
        subtree = self.hooks.subtree()
        by_id = {node["id"]: node for node in subtree}
        root = by_id.get(self.root)
        if root is None:
            return ("stuck", f"{self.root} is no longer on the map")
        self._redirect_dependents(subtree, by_id)
        turns = self._turns(running)
        node_turns, _ = self.hooks.budget()
        with self._lock:
            self.state.running, self.state.turns = running, turns
            self.state.accepted = [node["id"] for node in subtree if node.get("accepted")]
            # a split adds Claims: the budget grows with the open nodes there are to work (ADR-0021 point 7)
            self._counted |= {node["id"] for node in subtree if node.get("has_run") and not node.get("accepted")}
            self.state.turns_max = max(self.state.turns_max, node_turns * len(self._counted))
            turns_max, provider = self.state.turns_max, self.state.provider
        # the root's own run ends first (#187): a review request lands mid-turn, and the run records the verdict that
        # gated it as the turn ends; done before that, and the host may close the run before it does
        settled = "Accepted" if root.get("accepted") else "requested for review" if _awaiting(root) else None
        if settled:
            return None if self.root in running else ("done", f"{self.root} is {settled}")
        if turns >= turns_max:
            # the nodes that ended for good or spent their node budget are parked all the same (proof-agents#18, ADR-0021
            # point 9), for the researcher's review queue; a running one is not, and no further Decomposer turn starts
            self._park(subtree, by_id, running, node_turns)
            return ("budget", f"the budget of this Start is spent ({turns} turns over {len(self.state.nodes)} node(s)); the running run(s) finish on their own")
        starts = [(node, "decomposer", redirect) for node, redirect in self._park(subtree, by_id, running, node_turns)]
        if self._unsplit(root) and self.root not in running:
            starts.append((root, "decomposer", None))   # Pursue on a Theorem with no Claims: a Decomposer turn first (point 7)
        starts += [(node, None, None) for node in subtree if self._startable(node, by_id, running, node_turns)]
        room = max(0, self.hooks.parallel() - len(running))
        started: list[str] = []
        for node, role, redirect in starts:
            if room <= 0 or node["id"] in started:
                continue
            with self._lock:  # Stop or Pause meanwhile: no new node run begins (point 18)
                if self._stop or self._pause:
                    break
                self.state.running = [*self.state.running, node["id"]]   # reserved before the run starts: Pause and Stop see it
                self._worked_again(node, subtree)
                if role == "decomposer":
                    self.state.decomposed = [*self.state.decomposed, node["id"]]
                    if self._resplits.pop(node["id"], None) is not None:
                        self.state.resplit = [*self.state.resplit, node["id"]]
            self._start_run(node, provider, node_turns, role=role, redirect=redirect)
            started.append(node["id"])
            running = running + [node["id"]]
            room -= 1
        if not running and not starts:
            open_nodes = [node["id"] for node in subtree if _open(node)]
            if not open_nodes:
                return ("done", "nothing in the subtree is open")
            with self._lock:
                parked = [node_id for node_id in open_nodes if node_id in self.state.parked]
                held = [node_id for node_id in open_nodes if node_id in self.state.held]
            if len(parked) == len(open_nodes):
                return ("parked", f"every open node in the subtree is parked: {', '.join(parked)}")
            waiting = [node_id for node_id in open_nodes if node_id not in parked and node_id not in held]
            aside = [f"parked: {', '.join(parked)}"] * bool(parked) + [f"the researcher's: {', '.join(held)}"] * bool(held)
            what = f"{', '.join(waiting)} rest(s) on what no run will settle" if waiting else "every open node is parked or the researcher's"
            return ("stuck", f"nothing left to work without the researcher: {what}" + (f" ({'; '.join(aside)})" if aside else ""))
        return None

    def _worked_again(self, node: dict, subtree: list[dict]) -> None:
        """Under the lock, as `node`'s run is about to start: when it requested review in this Start and was sent back, or is
        being worked again for that reason itself, the dependents this Start worked on it are to be worked again too, once
        it is Accepted or Provisional again (ADR-0021 point 4) — the root aside, whose review request ends the Coordinator."""
        entry = self.state.nodes.get(node["id"]) or {}
        again = node["id"] in self._redo or (entry.get("last") == "done" and entry.get("reason") == "review-requested")
        self._redo.discard(node["id"])
        if again:
            self._redo |= {other["id"] for other in subtree if node["id"] in (other.get("dependencies") or [])
                           and other["id"] != self.root and other["id"] in self.state.nodes}

    def _unsplit(self, node: dict) -> bool:
        """The root is a Theorem or Lemma with no Claims a Split made, given no Decomposer turn by this Start yet."""
        if node.get("kind") not in DECOMPOSABLE or not node.get("has_run") or node.get("accepted") or _awaiting(node):
            return False
        with self._lock:
            if node["id"] in self.state.decomposed or node["id"] in self.state.nodes:
                return False
        children = node.get("split_children")
        return not children if children is not None else not node.get("dependencies")

    def _park(self, subtree: list[dict], by_id: dict, running: list[str], node_turns: int) -> list[tuple[dict, str]]:
        """Park the nodes whose run will not be started again (ADR-0021 point 9): those that ended for good, and those whose
        node budget is spent. Each parked Claim gives its parent one more Decomposer turn, once per parent — the first
        decomposition of an unsplit root is not it. A turn due is kept until it starts (no free slot, a Pause, the parent's
        own run still going): the parents whose turn may start now, each with the redirect that says why."""
        newly: list[tuple[str, str]] = []
        with self._lock:
            for node in subtree:
                entry = self.state.nodes.get(node["id"])
                if entry is None or node["id"] in running or node["id"] in self.state.parked or not _open(node):
                    continue
                last = entry.get("last")
                if last in ENDED_FOR_GOOD:
                    reason = f"{last}: {entry.get('reason') or ''}".rstrip(": ")
                elif last in ENDED_RESTARTABLE and _used(entry) >= node_turns:
                    idle = int(entry.get("idle_starts") or 0)
                    spent = f"{entry.get('turns')} turn(s)" + (f", {idle} Start(s) that took no turn" if idle else "")
                    reason = f"its budget is spent ({spent}); the last run ended {last}: {entry.get('reason') or ''}".rstrip(": ")
                else:
                    continue
                self.state.parked[node["id"]] = reason
                newly.append((node["id"], reason))
                if last == "needs-human" and entry.get("role") == "decomposer":
                    # the Claims its own turn split it into wait on the same decision (proof-agents#15): a contradiction in
                    # its statement, or a fact only the researcher knows, is not settled by working them
                    before = set(entry.get("split_before") or [])
                    for child_id in node.get("split_children") or []:
                        child = by_id.get(child_id)
                        if child_id not in before and child is not None and _open(child) and child_id not in self.state.held:
                            self.state.held[child_id] = f"its split waits on the researcher's decision on {node['id']}: {entry.get('reason') or ''}".rstrip(": ")
        for node_id, reason in newly:
            self._record(f"parked {node_id}: {reason}")
            try:
                self.hooks.park(node_id, reason)
            except Exception:  # noqa: BLE001 — the record is the host's; the Coordinator goes on either way
                pass
            if by_id[node_id].get("kind") != "claim":
                continue
            for parent in by_id.values():
                if node_id in (parent.get("dependencies") or []) and _resplittable(parent):
                    with self._lock:
                        if parent["id"] not in self.state.resplit and parent["id"] not in self._resplits:
                            self._resplits[parent["id"]] = (f"{node_id} is parked ({reason}); propose another structure for {parent['id']} "
                                                            f"that does not need {node_id} as it stands")
        with self._lock:
            due = list(self._resplits.items())
        out: list[tuple[dict, str]] = []
        for parent_id, redirect in due:
            parent = by_id.get(parent_id)
            if parent is None or not _resplittable(parent):  # gone from the subtree, or Accepted meanwhile: nothing to restructure
                with self._lock:
                    self._resplits.pop(parent_id, None)
            elif parent_id not in running:
                out.append((parent, redirect))
        return out

    def _startable(self, node: dict, by_id: dict, running: list[str], node_turns: int) -> bool:
        """A node whose run may start now (ADR-0021 point 4): a local node, open, nobody else's, every dependency Accepted or
        Provisional — the frontier, which makes a parent startable once every child has passed the Verifier — with budget
        left: none spent yet, or its last run ended short of a snapshot for review and the node budget is not spent."""
        with self._lock:
            again = node["id"] in self._redo and not node.get("accepted")
        if not node.get("has_run") or not (_open(node) or again) or node["id"] in running:
            return False
        with self._lock:
            done = self.state.nodes.get(node["id"])
            name = self.state.name
            if node["id"] in self.state.parked or node["id"] in self.state.held:
                return False
            if any(self._split_by_running(parent, node["id"], running) for parent in by_id.values()):
                return False  # its split is not settled until the Decomposer turn that made it ends (#15)
        if node.get("claimed_by") not in (None, name) or (node.get("claimed_by") == name and done is None):
            return False  # another's claim; or ours from before this Start, which a run of ours is not here to resume
        if node.get("workflow") == "claimed" and node.get("claimed_by") is None:
            return False
        if self._unsplit(node) and node["id"] == self.root:
            return False  # its Decomposer turn comes first
        for dependency_id in node.get("dependencies") or []:
            dependency = by_id.get(dependency_id)
            if dependency is not None and not dependency.get("accepted") and not dependency.get("provisional"):
                return False
        if done is None:
            return True
        return done.get("last") not in ENDED_FOR_GOOD and _used(done) < node_turns

    def _split_by_running(self, parent: dict, node_id: str, running: list[str]) -> bool:
        """Under the lock: `node_id` is a Claim `parent`'s Decomposer turn, still running, split it into. It waits for the
        turn's end: a needs-human there leaves it held for the researcher (`_park`), any other ending lets it be worked."""
        if parent["id"] not in running or node_id not in (parent.get("split_children") or []):
            return False
        entry = self.state.nodes.get(parent["id"]) or {}
        return entry.get("role") == "decomposer" and node_id not in (entry.get("split_before") or [])

    def _start_run(self, node: dict, provider: str, node_turns: int, *, role: str | None = None, redirect: str | None = None) -> None:
        """Start the node's run with what is left of the node budget (audit P4) — every role, or a Decomposer's one turn — as
        a Pursue (ADR-0021 point 7). The node was reserved in `running` before; a Stop or Pause that came while the run was
        starting reaches it here (audit P1)."""
        with self._lock:
            entry = self.state.nodes.setdefault(node["id"], {"starts": 0, "turns": 0, "last": None, "verdict": None, "started_at": None})
            entry["role"] = role
            if role == "decomposer":  # the Claims there were before its turn: those its turn adds are told from them (#15)
                entry["split_before"] = list(node.get("split_children") or [])
            left = max(1, node_turns - _used(entry))
        try:
            run = self.hooks.run(node["id"])
            answer = run.start(provider, turns=left, pursue=True, **({"roles": [role]} if role else {}), **({"redirect": redirect} if redirect else {}))
        except Exception as exc:  # noqa: BLE001
            answer = {"error": f"{type(exc).__name__}: {exc}", "code": "RUN_REFUSED"}
        with self._lock:
            if "error" in answer:
                entry["last"] = "refused"
                entry["reason"] = answer.get("error")
                self.state.running = [n for n in self.state.running if n != node["id"]]
            else:
                entry["starts"] += 1
                entry["last"] = None
                entry["started_at"] = answer.get("started_at")
                self._spent[node["id"]] = entry["turns"]
                self._seen[node["id"]] = 0
            late_stop, late_pause = self._stop, self._pause
        if "error" in answer:
            self._record(f"could not start a run on {node['id']}: {answer.get('error')}")
            return
        what = "a Decomposer turn" if role == "decomposer" else "a run"
        self._record(f"started {what} on {node['id']} (start {entry['starts']}, {left} turn(s) left of the node budget)")
        if late_stop:  # Stop came while this run was starting: it is released as the others were
            answer = self._answer_of(node["id"], lambda run: run.release("the Coordinator was stopped and released", expected_started_at=entry["started_at"]))
            with self._lock:
                self.state.running = [n for n in self.state.running if n != node["id"]]
                if "error" in answer:  # not released: the Coordinator says so and keeps the node to release on the next Stop
                    failed_already = self.state.status == "release-failed"
                    self.state.status = "release-failed"
                    self.state.reason = (f"{self.state.reason}; " if failed_already else "the node(s) are still assigned: ") + f"{node['id']}: {answer.get('error')}"
            if "error" in answer:
                self._record(f"the run on {node['id']}, started as the Coordinator was stopped, could not be released: {answer.get('error')} — try Stop again")
            else:
                self._record(f"released the run on {node['id']}, started as the Coordinator was stopped")
        elif late_pause:
            self._on_run(node["id"], lambda run: run.pause())

    def _running(self) -> list[str]:
        """The node runs it started that are active now; the ones that ended are noted (their ending, their newest verdict, their turns)."""
        running: list[str] = []
        ended: list[tuple[str, dict]] = []
        with self._lock:
            watched = list(self.state.running)
        for node_id in watched:
            view = self._view_of(node_id)
            if view is None:
                continue
            if view.get("status") in RUN_ACTIVE:
                running.append(node_id)
            else:
                ended.append((node_id, view))
        with self._lock:
            for node_id, view in ended:
                entry = self.state.nodes.setdefault(node_id, {"starts": 0, "turns": 0, "last": None, "verdict": None})
                took = int(view.get("turns") or 0)
                entry["turns"] = self._spent.get(node_id, 0) + took
                if not took:  # it ended before any turn counted (its turn could not start, its loop raised): it spends the
                    # node budget all the same, one turn's worth, or a node whose turns never start is started forever
                    entry["idle_starts"] = int(entry.get("idle_starts") or 0) + 1
                status, reason = view.get("status"), str(view.get("reason") or "")
                entry["last"], entry["verdict"], entry["reason"] = status, view.get("verdict"), view.get("reason")
                if entry.get("role") == "decomposer" and status == "done":
                    # its turn is over and the node is worked next, like any open node: split, or one argument after all
                    entry["last"] = "split" if reason.startswith(SPLIT_REASON) else "no-split"
                    entry["role"] = None
                elif status == "released" or (status == "done" and reason != "review-requested"):
                    # the researcher's Stop and release, or a run that ended done short of review: theirs, not restarted
                    self.state.held[node_id] = f"the run ended {status}: {reason}".rstrip(": ")
                self._seen.pop(node_id, None)
        for node_id, view in ended:
            self._record(f"the run on {node_id} ended: {view.get('status')} — {view.get('reason') or ''}".rstrip(" —"))
        return running

    def _turns(self, running: list[str]) -> int:
        """Turns spent over every Start of every node: the ended runs' as noted, the running ones' as read now."""
        with self._lock:
            total = sum(int(entry.get("turns") or 0) for node_id, entry in self.state.nodes.items() if node_id not in running)
        for node_id in running:
            view = self._view_of(node_id) or {}
            total += self._spent.get(node_id, 0) + int(view.get("turns") or 0)
        return total

    def _redirect_dependents(self, subtree: list[dict], by_id: dict) -> None:
        """A node of the subtree newly Accepted: its dependents' active runs are redirected with one line naming it and its
        key ideas (point 19) — the only cross-node push, on the Redirect channel, read at the next turn."""
        with self._lock:
            done = set(self.state.redirected)
        for node in subtree:
            if not node.get("accepted") or node["id"] in done or node["id"] == self.root:
                continue
            line = f"{node['id']} is Accepted: {node.get('statement') or ''}".strip()
            ideas = (node.get("key_ideas") or "").strip()
            if ideas:
                line += f" — key ideas: {' '.join(ideas.split())[:400]}"
            told = []
            for dependent in subtree:
                if node["id"] in (dependent.get("dependencies") or []):
                    view = self._view_of(dependent["id"])
                    if view and view.get("status") in RUN_ACTIVE:
                        self._on_run(dependent["id"], lambda run, line=line: run.redirect(line))
                        told.append(dependent["id"])
            with self._lock:
                self.state.redirected = [*self.state.redirected, node["id"]]
            if told:
                self._record(f"{node['id']} is Accepted: redirected the run(s) on {', '.join(told)} with its statement and key ideas")

    def _view_of(self, node_id: str) -> dict | None:
        try:
            return self.hooks.run(node_id).view()
        except Exception:  # noqa: BLE001 — a node with no run (gone from the map) has no view
            return None

    def _owned_run(self, node_id: str, started_at: float | None) -> dict | None:
        """An unreleased Start this Coordinator owns. The release itself rechecks the identity under AgentRun's lock."""
        if started_at is None:
            return None
        view = self._view_of(node_id)
        if view is None or view.get("started_at") != started_at or view.get("status") in ("idle", "released"):
            return None
        if view.get("status") == "done" and view.get("reason") == "review-requested":
            return None  # review handed the node over; it left no claim to release
        return view

    def _on_run(self, node_id: str, action) -> None:
        try:
            action(self.hooks.run(node_id))
        except Exception:  # noqa: BLE001 — a run that is gone takes no action
            pass

    def _answer_of(self, node_id: str, action) -> dict:
        """A run action's answer, an error when the run is gone or the action raised."""
        try:
            answer = action(self.hooks.run(node_id))
            return answer if isinstance(answer, dict) else {}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}", "code": "RUN_GONE"}

    def _end(self, status: str, reason: str) -> None:
        with self._lock:
            if self._stop:
                return
            self.state.status, self.state.reason = status, reason
            self.state.running = [] if status != "budget" else self.state.running
        self._record(f"{status}: {reason}")

    def _record(self, note: str) -> None:
        try:
            self.hooks.record(note)
        except Exception:  # noqa: BLE001 — the record is a courtesy; the state is the Coordinator's
            pass


def _awaiting(node: dict) -> bool:
    """A snapshot of the node awaits the researcher's decision (ADR-0021: Blocked hides it on the workflow axis)."""
    return bool(node.get("awaiting_review")) or node.get("workflow") == "review-needed"


def _resplittable(node: dict) -> bool:
    """A parent a further Decomposer turn may be given to: a local Theorem or Lemma, not Accepted."""
    return node.get("kind") in DECOMPOSABLE and bool(node.get("has_run")) and not node.get("accepted")


def _used(entry: dict) -> int:
    """What a node has spent of its node budget: its turns, and one for each Start that ended before any turn counted."""
    return int(entry.get("turns") or 0) + int(entry.get("idle_starts") or 0)


def _open(node: dict) -> bool:
    """Still to be worked: a local node, not Accepted, not Provisional, no snapshot awaiting a decision."""
    return bool(node.get("has_run")) and not node.get("accepted") and not node.get("provisional") and not _awaiting(node)


@dataclass
class PursuitHooks:
    """Pursue on a project with no map (ADR-0021 point 7), as callables: the host runs the turns and makes the Coordinators."""

    read: Callable[[str], dict]                  # provider -> the Reader's turn, run to its end: {} or {"error", "code"}
    theorems: Callable[[], list[str]]            # the map's Theorems now, in the map's order
    coordinator: Callable[[str], Coordinator]    # a Theorem's Coordinator, made on demand
    record: Callable[[str], None] = lambda note: None
    # Stop while the Reader's turn runs: the host stops that turn, so `read` returns (with an error, or with what was
    # written so far); a no-op when no Reader turn is running
    stop_read: Callable[[], None] = lambda: None


class ProjectPursuit:
    """Pursue started on a project: a Reader turn states the draft in the library as a map, then each Theorem it stated is
    pursued by its own Coordinator, one after another, each to its own end. Stop stops the one working and starts no other."""

    def __init__(self, hooks: PursuitHooks, *, tick: float = TICK) -> None:
        self.hooks = hooks
        self.tick = tick
        self._lock = threading.Lock()
        self._stop = False
        self._thread: threading.Thread | None = None
        self.state = {"status": "idle", "reason": "", "theorems": [], "current": None, "results": {}}

    def view(self) -> dict:
        with self._lock:
            return self._view_locked()

    def start(self, provider: str) -> dict:
        with self._lock:
            if self.state["status"] in ("reading", "pursuing"):
                return {"error": "this project is being pursued already; stop it first", "code": "PURSUIT_ACTIVE"}
            if self._thread is not None and self._thread.is_alive():
                return {"error": "the stopped pursuit is still ending; Start again after it settles", "code": "PURSUIT_ACTIVE"}
            self._stop = False
            self.state = {"status": "reading", "reason": "", "theorems": [], "current": None, "results": {}}
            self._thread = threading.Thread(target=self._loop, args=(provider,), name="pursuit", daemon=True)
            self._thread.start()
        return self.view()

    def stop(self) -> dict:
        """Stop: the Reader's turn is stopped (`stop_read`) or the working Theorem's Coordinator released, and no other
        Theorem is started. A pursuit that already ended keeps its ending: there is nothing to stop."""
        with self._lock:
            status, current = self.state["status"], self.state["current"]
            if status not in ("reading", "pursuing"):
                return {"error": "no pursuit is running on this project", "code": "NO_PURSUIT", **self._view_locked()}
            self._stop = True
            self.state["status"], self.state["reason"] = "released", "stopped by the researcher"
        if status == "reading":
            self.hooks.stop_read()
        if current is not None:
            self.hooks.coordinator(current).release()
        return self.view()

    def _view_locked(self) -> dict:
        return {**self.state, "theorems": list(self.state["theorems"]), "results": dict(self.state["results"])}

    def active(self) -> bool:
        """The pursuit's thread is alive: it is reading or pursuing, or it was stopped and its Reader's turn or its
        Coordinator has not ended yet. A Start is refused (PURSUIT_ACTIVE) until it is False."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _stopped(self) -> bool:
        with self._lock:
            return self._stop

    def _loop(self, provider: str) -> None:
        try:
            if not self.hooks.theorems():  # a map already there is pursued as it stands; the Reader only states one
                answer = self.hooks.read(provider) or {}
                if self._stopped():
                    return
                if "error" in answer:
                    return self._end("stuck", f"the Reader's turn failed: {answer.get('error')}")
            theorems = list(self.hooks.theorems())
            with self._lock:
                self.state["theorems"] = theorems
            if not theorems:
                return self._end("stuck", "the Reader stated no Theorem")
            self._note(f"pursuing {len(theorems)} Theorem(s): {', '.join(theorems)}")
            for theorem in theorems:
                with self._lock:
                    if self._stop:
                        return
                    self.state["status"], self.state["current"] = "pursuing", theorem
                coordinator = self.hooks.coordinator(theorem)
                if self._stopped():
                    return
                answer = coordinator.start(provider)
                if "error" in answer:
                    with self._lock:
                        self.state["results"][theorem] = {"status": "refused", "reason": answer.get("error")}
                    continue
                if self._stopped():  # Stop came while it was starting, and may have found nothing started to release
                    coordinator.release()
                    return
                while coordinator.active() or coordinator.view().get("settling"):
                    time.sleep(self.tick)   # a Stop releases it; the pursuit is active until it has settled
                if self._stopped():
                    return
                view = coordinator.view()
                with self._lock:
                    self.state["results"][theorem] = {"status": view.get("status"), "reason": view.get("reason")}
                if view.get("status") == "budget":  # its runs go on by themselves: stopped before the next Theorem starts
                    coordinator.release()
            self._end("done", "every Theorem was pursued to its end")
        except Exception as exc:  # noqa: BLE001 — the pursuit ends, and says why
            self._end("stuck", f"{type(exc).__name__}: {exc}")

    def _end(self, status: str, reason: str) -> None:
        with self._lock:
            if self._stop:
                return
            self.state["status"], self.state["reason"], self.state["current"] = status, reason, None
        self._note(f"{status}: {reason}")

    def _note(self, note: str) -> None:
        try:
            self.hooks.record(note)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["ACTIONS", "ACTIVE", "Coordinator", "CoordinatorHooks", "CoordinatorState", "ProjectPursuit", "PursuitHooks"]
