"""The Coordinator over a subtree (ADR-0019 points 18 and 19, ADR-0021 Pursue), driven with fake node runs and a subtree
the test moves along: it starts runs on the frontier up to `parallel` at a time, starts the parent once every child is
Accepted or Provisional, restarts a node whatever its last verdict until the node budget is spent and then parks it,
redirects dependents when a node is Accepted, stops when the root is requested for review, its budget is spent, or
nothing open is left to work; and Pause, Resume and Stop and release reach the runs it started."""

import time

import pytest

from proof_agents.coordinator import Coordinator, CoordinatorHooks

WAIT = 10.0


def _until(ready, what, timeout=WAIT, every=0.01):
    deadline = time.monotonic() + timeout
    while True:
        value = ready()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(what() if callable(what) else what)
        time.sleep(every)


class FakeRun:
    """A node's run as the Coordinator sees it: started, viewed, paused, resumed, redirected, released; the test ends it.
    As AgentRun: a run that ends stuck or over budget keeps the node's claim; one that requested review or was released
    does not; `started_at` tells one Start from another; a Start may be held (`gate`) and a release may fail."""

    def __init__(self):
        self.status, self.turns, self.verdict, self.reason = "idle", 0, None, ""
        self.calls, self.redirects, self.starts, self.caps, self.kw = [], [], 0, [], []
        self.claim, self.started_at, self.gate, self.fail_release = None, None, None, False

    def start(self, provider, turns=None, **kw):
        if self.gate is not None:
            self.gate.wait(5)
        self.calls.append("start")
        self.starts += 1
        self.caps.append(turns)
        self.kw.append(kw)
        self.status, self.turns, self.verdict, self.reason = "running", 0, None, ""
        self.claim, self.started_at = "claude-code", self.starts * 1000.0
        return self.view()

    def view(self):
        return {"status": self.status, "turns": self.turns, "verdict": self.verdict, "reason": self.reason, "role": "prover", "started_at": self.started_at}

    def active(self):
        return self.status in ("starting", "running", "paused")

    def pause(self):
        self.calls.append("pause"); self.status = "paused"; return {}

    def resume(self):
        self.calls.append("resume")
        if self.status == "paused":  # as AgentRun: a run that ended is not revived by Resume
            self.status = "running"
        return {}

    def release(self, reason="", *, expected_started_at=None):
        if expected_started_at is not None and self.started_at != expected_started_at:
            return {"skipped": True}
        self.calls.append("release")
        if self.fail_release:
            self.status = "release-failed"
            return {"error": "the node is still assigned: giving it back failed", "code": "RELEASE_FAILED", **self.view()}
        self.status, self.claim = "released", None
        return self.view()

    def redirect(self, text, role=None):
        self.redirects.append(text); return {}

    def end(self, status, *, verdict=None, turns=1, reason="", requested=False):
        self.turns, self.verdict, self.reason, self.status = turns, verdict, reason, status
        if reason == "review-requested" or status == "released":
            self.claim = None   # a review request hands the node over; stuck, budget and turn-finished keep the claim


class World:
    """A subtree: T rests on A and B; C rests on A. The test accepts nodes and requests review; the hooks read it."""

    def __init__(self, edges=None, parallel=2, budget=(5, 60.0), kinds=None):
        self.edges = edges or {"T": ["A", "B"], "A": [], "B": [], "C": ["A"]}
        self.kinds = kinds or {}
        self.accepted, self.requested, self.ideas = set(), set(), {}
        self.runs = {node: FakeRun() for node in self.edges}
        self.notes, self.parked = [], []
        self._parallel, self._budget = parallel, budget

    def subtree(self):
        out = []
        for node, deps in self.edges.items():
            run = self.runs[node]
            if node in self.requested:
                workflow = "review-needed"
            elif any(dep not in self.accepted for dep in deps):
                workflow = "blocked"
            elif run.claim:
                workflow = "claimed"
            else:
                workflow = "open"
            kind = self.kinds.get(node, "theorem" if node == "T" else "claim")
            out.append({"id": node, "kind": kind, "statement": f"{node} holds", "dependencies": list(deps),
                        "accepted": node in self.accepted, "workflow": workflow, "claimed_by": run.claim,
                        "key_ideas": self.ideas.get(node), "has_run": True,
                        # ADR-0021: a snapshot the Verifier passed is Provisional; every dependency of a Theorem here is a split's Claim
                        "awaiting_review": node in self.requested, "provisional": node in self.requested and run.verdict == "passed",
                        "split_children": [d for d in deps if self.kinds.get(d, "claim") == "claim"] if kind in ("theorem", "lemma") else []})
        return out

    def hooks(self):
        return CoordinatorHooks(subtree=self.subtree, run=lambda node: self.runs[node], budget=lambda: self._budget, parallel=lambda: self._parallel,
                                agent_name=lambda provider: "claude-code", record=self.notes.append,
                                park=lambda node, reason: self.parked.append((node, reason)))

    def coordinator(self, root="T"):
        return Coordinator(self.hooks(), root, tick=0.01)


def test_start_runs_the_frontier_up_to_parallel_then_the_parent_once_every_child_is_provisional_and_stops_at_the_roots_review():
    world = World(edges={"T": ["A", "B", "C"], "A": [], "B": [], "C": []})
    c = world.coordinator()
    assert c.start("claude")["status"] in ("starting", "running")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    time.sleep(0.05)
    assert world.runs["C"].starts == 0 and sorted(c.view()["running"]) == ["A", "B"]  # parallel 2
    world.runs["A"].end("done", verdict="passed", turns=3, reason="review-requested"); world.requested.add("A")
    _until(lambda: world.runs["C"].starts == 1, "C started once A's run ended")
    world.runs["B"].end("done", verdict="passed", turns=2, reason="review-requested"); world.requested.add("B")
    time.sleep(0.05)
    assert world.runs["T"].starts == 0  # C is still being worked: T waits for every child to be Accepted or Provisional
    world.runs["C"].end("done", verdict="passed", turns=2, reason="review-requested"); world.requested.add("C")
    # nobody Accepted anything: every child passed the Verifier, and that is enough to work the parent (ADR-0021 point 4)
    _until(lambda: world.runs["T"].starts == 1, "T started once every child is Provisional")
    assert world.accepted == set()
    world.runs["T"].end("done", verdict="passed", turns=4, reason="review-requested"); world.requested.add("T")
    _until(lambda: not c.active(), "the Coordinator ended")
    view = c.view()
    assert (view["status"], view["reason"]) == ("done", "T is requested for review") and view["turns"] == 11
    assert view["nodes"]["A"]["starts"] == 1 and view["nodes"]["T"]["turns"] == 4
    assert all(kw == {"pursue": True} for kw in world.runs["T"].kw + world.runs["A"].kw)
    assert any(n.startswith("started on T: 4 open node(s)") for n in world.notes) and "done: T is requested for review" in world.notes


def test_a_child_awaiting_review_without_the_verifiers_pass_holds_its_parent_and_the_coordinator_does_not_wait_for_it():
    world = World(edges={"T": ["A"], "A": []}, parallel=1)
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1, "A started")
    world.runs["A"].end("done", verdict=None, turns=1, reason="review-requested"); world.requested.add("A")  # no passing verdict
    _until(lambda: not c.active(), "the Coordinator ended")
    assert world.runs["T"].starts == 0
    assert c.view()["status"] == "stuck" and "nothing left to work without the researcher: T" in c.view()["reason"]


def test_the_coordinator_is_done_only_once_the_roots_run_has_ended_too():
    """#187: the root is requested for review in the middle of its run's turn; the run still records the verdict that gated
    the request (an Evidence check) as the turn ends. Done before that, and the host may close the run first."""
    world = World(edges={"T": []}, parallel=1, kinds={"T": "claim"})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["T"].starts == 1, "T started")
    world.requested.add("T")  # the request is on the map; the run is still finishing its turn
    time.sleep(0.1)
    assert c.active() and c.view()["status"] == "running"
    world.runs["T"].end("done", verdict="passed", turns=1, reason="review-requested")
    _until(lambda: not c.active(), "the Coordinator ended")
    assert (c.view()["status"], c.view()["reason"]) == ("done", "T is requested for review")


def test_a_run_that_ended_short_of_review_is_started_again_whatever_its_verdict_until_the_node_budget_is_spent_then_parked():
    # A is a Lemma here: a parked Claim would give T another Decomposer turn (see below)
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2, budget=(4, 60.0), kinds={"A": "lemma"})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world.runs["A"].end("stuck", verdict="failed", turns=2, reason="no change in 5 turn(s)")
    assert world.runs["A"].claim == "claude-code"  # the ended run keeps the claim (as AgentRun does): this Coordinator's own, no bar to the retry
    _until(lambda: world.runs["A"].starts == 2, "A started again after a failed verdict")
    assert world.runs["A"].caps == [4, 2]  # the retry gets what is left of the node budget, not a fresh one (audit P4)
    world.runs["A"].end("stuck", verdict=None, turns=1, reason="the agent reported it is stuck")  # no verdict: started again all the same
    _until(lambda: world.runs["A"].starts == 3, "A started again after a stuck run with no verdict")
    world.runs["A"].end("budget", verdict=None, turns=1, reason="out of turns")  # 4 turns spent of 4: the node budget is spent
    _until(lambda: c.view()["parked"], "A parked")
    # A is parked, and the rest of the subtree goes on: B is still worked, and passes
    assert c.active() and world.runs["A"].starts == 3 and world.parked[0][0] == "A" and "its budget is spent" in world.parked[0][1]
    world.runs["B"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("B")
    _until(lambda: not c.active(), "the Coordinator ended")
    view = c.view()
    assert view["status"] == "stuck" and "T rest(s) on what no run will settle (parked: A)" in view["reason"]
    assert view["needs_you"] == [{"node": "A", "last": "budget", "reason": view["parked"][0]["reason"]}]


def test_a_node_whose_run_stops_for_a_decision_is_parked_at_once_and_when_every_open_node_is_parked_the_coordinator_ends():
    world = World(edges={"T": [], "A": []}, parallel=2, kinds={"T": "claim"})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["T"].starts == 1, "A and T started")
    world.runs["A"].end("needs-human", turns=1, reason="the statement contradicts itself")
    world.runs["T"].end("needs-human", turns=1, reason="a constant only you know")
    _until(lambda: not c.active(), "the Coordinator ended")
    assert world.runs["A"].starts == 1 and c.view()["status"] == "parked"
    assert c.view()["reason"].startswith("every open node in the subtree is parked")


def test_the_budget_is_the_sum_of_the_node_budgets_and_ends_the_coordinator_not_the_runs():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(2, 60.0))  # 3 open nodes × 2 turns
    c = world.coordinator()
    c.start("claude")
    assert c.view()["turns_max"] == 6
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["A"].turns = 3; world.runs["B"].turns = 3   # still running, 6 turns spent between them
    _until(lambda: not c.active(), "the Coordinator ended")
    assert c.view()["status"] == "budget" and world.runs["A"].status == "running" and "release" not in world.runs["A"].calls


def test_at_the_budgets_end_a_node_that_spent_its_node_budget_is_still_parked_and_a_running_one_is_not():
    """proof-agents#18 (ADR-0021 point 9): the Coordinator ended at its budget before parking, so a Claim out of turns
    never reached the review queue's Parked nodes."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(1, 60.0))  # 3 open nodes × 1 turn
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["B"].turns = 2   # still running
    world.runs["A"].end("budget", turns=1, reason="out of turns")
    _until(lambda: not c.active(), "the Coordinator ended")
    view = c.view()
    assert view["status"] == "budget" and [entry["node"] for entry in view["parked"]] == ["A"]
    assert [node for node, _ in world.parked] == ["A"] and world.runs["B"].status == "running"
    assert world.runs["T"].starts == 0   # A's parent gets no further Decomposer turn once the budget is spent
    c.release()


def test_an_acceptance_redirects_the_running_dependents_once_with_the_statement_and_the_key_ideas():
    world = World(edges={"T": ["A", "B"], "A": [], "B": ["A"]})
    world.accepted.add("A"); world.ideas["A"] = "## 核心思路\nby compactness\n"
    c = world.coordinator()
    c.start("claude")  # A is Accepted already at Start: nothing to redirect for it (its dependents' runs begin briefed with it)
    _until(lambda: world.runs["B"].starts == 1, "B started")
    time.sleep(0.05)
    assert world.runs["B"].redirects == []
    world2 = World(edges={"T": ["A", "B"], "A": [], "B": ["A"], "D": ["A"]})
    world2.edges["B"] = []  # B runs without A; D rests on A and is blocked
    c2 = world2.coordinator()
    c2.start("claude")
    _until(lambda: world2.runs["A"].starts and world2.runs["B"].starts, "A and B started")
    # the researcher's own request, with no passing verdict: A is not Provisional, so D waits for its Acceptance
    world2.runs["A"].end("done", verdict=None, turns=1, reason="review-requested"); world2.requested.add("A")
    time.sleep(0.05)
    world2.requested.discard("A"); world2.accepted.add("A"); world2.ideas["A"] = "## 核心思路\nby compactness\n## 主要步骤\n1. x\n"
    _until(lambda: world2.runs["D"].starts == 1, "D started once A is Accepted")
    time.sleep(0.05)
    assert world2.runs["B"].redirects == [] and world2.runs["D"].redirects == []  # D's run began after: it is briefed, not redirected
    world3 = World(edges={"T": ["A", "B"], "A": [], "B": ["A"]}, parallel=2)
    world3.accepted.add("A")  # B may run; T waits
    c3 = world3.coordinator()
    world3.accepted.discard("A")  # start with A open and B blocked; then let B run while A is reviewed
    c3.start("claude")
    _until(lambda: world3.runs["A"].starts == 1, "A started")
    world3.runs["A"].end("done", verdict=None, turns=1, reason="review-requested"); world3.requested.add("A")
    world3.requested.discard("A"); world3.accepted.add("A"); world3.ideas["A"] = "## 核心思路\nby compactness\n"
    _until(lambda: world3.runs["B"].starts == 1, "B started")
    world3.runs["B"].turns = 1  # B is running now; T is blocked on B
    time.sleep(0.05)
    assert world3.runs["B"].redirects == []  # A was Accepted before B's run began
    world3.runs["B"].end("done", verdict=None, turns=1, reason="review-requested"); world3.requested.add("B")
    world3.requested.discard("B"); world3.accepted.add("B"); world3.ideas["B"] = "## 核心思路\ntelescoping\n"
    _until(lambda: world3.runs["T"].starts == 1, "T started")
    assert world3.runs["T"].redirects == []
    assert any("redirected" not in n for n in world3.notes)


def test_a_node_accepted_while_its_dependents_run_redirects_them():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["A"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("A")
    time.sleep(0.03)
    world.edges["B"] = ["A"]  # B comes to rest on A (its Prover added the edge) while it runs
    world.requested.discard("A"); world.accepted.add("A"); world.ideas["A"] = "## 核心思路\nby compactness\n## 主要步骤\n1. bound\n"
    _until(lambda: world.runs["B"].redirects, "B redirected")
    (line,) = world.runs["B"].redirects
    assert line.startswith("A is Accepted: A holds — key ideas: ## 核心思路 by compactness")
    time.sleep(0.05)
    assert world.runs["B"].redirects == [line]  # once
    assert any(n.startswith("A is Accepted: redirected the run(s) on B") for n in world.notes)


def test_pause_holds_the_runs_after_their_turn_resume_lets_them_on_and_release_releases_every_run_it_started():
    world = World(edges={"T": ["A", "B", "C"], "A": [], "B": [], "C": []})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    assert c.pause()["status"] == "paused" and world.runs["A"].calls[-1] == "pause" and world.runs["B"].calls[-1] == "pause"
    world.runs["A"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("A")
    time.sleep(0.05)
    assert world.runs["C"].starts == 0  # paused: no new node run begins
    assert c.resume()["status"] == "running" and world.runs["B"].calls[-1] == "resume"
    _until(lambda: world.runs["C"].starts == 1, "C started after Resume")
    released = c.release()
    assert released["status"] == "released" and world.runs["B"].calls[-1] == "release" and world.runs["C"].calls[-1] == "release"
    assert "release" not in world.runs["A"].calls  # A's run had ended
    time.sleep(0.03)
    assert not c.active() and c.pause()["code"] == "NO_COORDINATOR"


def test_a_start_is_refused_while_one_is_working_and_when_nothing_in_the_subtree_is_open():
    world = World(edges={"T": ["A"], "A": []})
    c = world.coordinator()
    assert c.start("claude")["status"] in ("starting", "running")
    assert c.start("claude")["code"] == "COORDINATOR_ACTIVE"
    c.release()
    _until(lambda: not c.view()["settling"], "the old Coordinator worker to finish")
    world.accepted.update({"A", "T"})
    assert c.start("claude")["code"] == "NOTHING_OPEN"


def test_a_start_that_returns_after_stop_or_pause_is_released_or_paused_and_no_further_run_begins():
    """Audit P1: Stop and Pause reach a run whose Start was under way, and the next candidate does not start."""
    import threading

    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2)
    gate = threading.Event()
    world.runs["A"].gate = gate   # A's Start blocks until the test lets it return
    c = world.coordinator()
    c.start("claude")
    _until(lambda: "A" in c.view()["running"], "A reserved while its Start is under way")
    assert world.runs["A"].starts == 0 and world.runs["B"].starts == 0
    released = c.release()
    assert released["status"] == "released"
    gate.set()
    _until(lambda: "release" in world.runs["A"].calls, "A's late Start released")
    time.sleep(0.05)
    assert world.runs["B"].starts == 0 and c.view()["running"] == []
    world2 = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2)
    gate2 = threading.Event()
    world2.runs["A"].gate = gate2
    c2 = world2.coordinator()
    c2.start("claude")
    _until(lambda: "A" in c2.view()["running"], "A reserved")
    assert c2.pause()["status"] == "paused"
    gate2.set()
    _until(lambda: "pause" in world2.runs["A"].calls, "A's late Start paused")
    time.sleep(0.05)
    assert world2.runs["B"].starts == 0
    c2.resume()
    _until(lambda: world2.runs["B"].starts == 1, "B started after Resume")
    c2.release()


def test_stop_releases_the_ended_runs_that_kept_their_claim_but_not_a_later_owners_run():
    """Audit P3: a run that ended stuck keeps the node; Stop gives it back too — unless the researcher started the node again since."""
    world = World(edges={"T": ["A", "B", "C"], "A": [], "B": [], "C": []}, parallel=3, kinds={"A": "lemma", "C": "lemma"})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: all(world.runs[n].starts == 1 for n in "ABC"), "A, B and C started")
    world.runs["A"].end("needs-human", verdict=None, turns=1, reason="a decision only you can make")   # keeps the claim; parked
    world.runs["B"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("B")
    world.runs["C"].end("needs-human", verdict=None, turns=1, reason="another")
    _until(lambda: c.view()["running"] == [], "the ended runs noted")
    world.runs["C"].start("claude")   # the researcher starts C again: a later owner
    assert c.release()["status"] == "released"
    assert world.runs["A"].calls[-1] == "release" and world.runs["A"].claim is None
    assert world.runs["C"].calls[-1] == "start" and world.runs["C"].status == "running"  # not this Coordinator's Start: left alone
    assert "release" not in world.runs["B"].calls  # a review request had handed B over already


def test_a_release_that_fails_is_said_and_stop_can_be_tried_again():
    """Audit P6: a run that cannot give its node back leaves the Coordinator release-failed, with the node named; a later Stop retries."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2)
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["A"].fail_release = True
    answer = c.release()
    assert answer["code"] == "RELEASE_FAILED" and answer["status"] == "release-failed" and "A: the node is still assigned" in answer["error"]
    assert world.runs["B"].status == "released"  # the others were released all the same
    assert any(n.startswith("stop and release failed on 1 run(s)") for n in world.notes)
    world.runs["A"].fail_release = False
    again = c.release()
    assert again["status"] == "released" and world.runs["A"].status == "released"


def test_stop_leaves_alone_a_run_the_researcher_started_again_since_the_coordinator_last_looked():
    """Re-audit P1: the ownership check holds for every node, the ones still in the running list included."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2)
    c = Coordinator(world.hooks(), "T", tick=10)   # one look, then a long wait: what happens meanwhile is unseen until Stop
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["A"].end("stuck", verdict=None, turns=1, reason="stuck")
    world.runs["A"].start("claude")   # the researcher starts A again before the Coordinator looks: a later owner, still listed as running
    assert c.release()["status"] == "released"
    assert world.runs["A"].calls[-1] == "start" and world.runs["A"].status == "running"
    assert world.runs["B"].status == "released"


def test_after_a_failed_stop_a_start_is_refused_until_the_nodes_are_given_back():
    """Re-audit P2: a new Start would lose the record of what is still to release."""
    world = World(edges={"T": ["A"], "A": []}, parallel=1)
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1, "A started")
    world.runs["A"].fail_release = True
    assert c.release()["code"] == "RELEASE_FAILED"
    refused = c.start("claude")
    assert refused["code"] == "RELEASE_FAILED" and "Stop again" in refused["error"]
    world.runs["A"].fail_release = False
    assert c.release()["status"] == "released"
    _until(lambda: not c.view()["settling"], "the old Coordinator worker to finish")
    assert c.start("claude")["status"] in ("starting", "running")
    c.release()


def test_a_late_starts_release_that_fails_leaves_the_coordinator_release_failed_and_stop_retries_it():
    """Re-audit P3: a Start that returned after Stop and could not be released is not hidden under 'released'."""
    import threading

    world = World(edges={"T": ["A"], "A": []}, parallel=1)
    gate = threading.Event()
    world.runs["A"].gate = gate
    c = world.coordinator()
    c.start("claude")
    _until(lambda: "A" in c.view()["running"], "A reserved")
    assert c.release()["status"] == "released"
    world.runs["A"].fail_release = True
    gate.set()
    _until(lambda: c.view()["status"] == "release-failed", lambda: f"the late release's failure said: {c.view()}")
    assert "A: the node is still assigned" in c.view()["reason"]
    world.runs["A"].fail_release = False
    assert c.release()["status"] == "released" and world.runs["A"].status == "released"


def test_a_stop_or_pause_right_after_start_is_not_undone_by_the_loops_first_breath():
    """Re-audit P4: the thread's entry does not set 'running' over a Stop or Pause that came first."""
    world = World(edges={"T": ["A"], "A": []}, parallel=1)
    c = world.coordinator()
    c.start("claude")
    c.release()
    time.sleep(0.05)
    assert c.view()["status"] == "released" and not c.active()
    world2 = World(edges={"T": ["A"], "A": []}, parallel=1)
    c2 = world2.coordinator()
    c2.start("claude")
    assert c2.pause()["status"] == "paused"
    time.sleep(0.05)
    assert c2.view()["status"] == "paused"
    assert c2.resume()["status"] == "running"
    c2.release()


def test_the_nodes_it_parked_are_named_as_needing_you_and_a_restartable_one_is_not():
    """#132 tier 3: MEAN's run ended stuck with no verdict while PAIR and SITES waited for review, and nothing said MEAN would
    not be started again. Under ADR-0021 it is started again while its budget lasts; what is parked is named, with why."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, budget=(5, 60.0), kinds={"A": "lemma"})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts and world.runs["B"].starts, "A and B started")
    world.runs["B"].end("done", verdict="passed", turns=3, reason="review-requested"); world.requested.add("B")
    world.runs["A"].end("stuck", verdict=None, turns=1, reason="writing scratch/ was denied")
    _until(lambda: world.runs["A"].starts == 2, "A started again")
    assert c.view()["needs_you"] == []
    world.runs["A"].end("needs-human", verdict=None, turns=1, reason="which Γ is meant")
    _until(lambda: c.view()["needs_you"], "A named")
    assert c.view()["needs_you"] == [{"node": "A", "last": "needs-human", "reason": "needs-human: which Γ is meant"}]
    c.release()
    _until(lambda: not c.active(), "the Coordinator released")


# -- Pursue (ADR-0021 point 7): the Decomposer first, its split worked, a parked Claim's parent split again ----------------


def test_pursue_on_a_theorem_with_no_claims_starts_with_a_decomposer_turn_and_works_its_split():
    world = World(edges={"T": []}, parallel=2, budget=(3, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["T"].starts == 1, "the Decomposer started on T")
    assert world.runs["T"].kw[0] == {"pursue": True, "roles": ["decomposer"]} and c.view()["decomposed"] == ["T"]
    assert c.view()["turns_max"] == 3
    # its split: T rests on two Claims, and the run ends done (it gave T back)
    world.edges.update({"T": ["A", "B"], "A": [], "B": []})
    world.runs.update({"A": FakeRun(), "B": FakeRun()})
    world.runs["T"].end("done", turns=1, reason="split into 2 Claim(s): A, B; the Coordinator works them")
    world.runs["T"].claim = None
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "the Claims are worked")
    assert c.view()["turns_max"] == 9  # the budget grew with the Claims
    for claim in "AB":
        world.runs[claim].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add(claim)
    _until(lambda: world.runs["T"].starts == 2, "T's own proof once its Claims are Provisional")
    assert world.runs["T"].kw[1] == {"pursue": True} and world.runs["T"].caps[1] == 2
    world.runs["T"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("T")
    _until(lambda: not c.active(), "the Coordinator ended")
    assert c.view()["status"] == "done"


def test_a_parked_claim_gives_its_parent_one_more_decomposer_turn_once():
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2, budget=(2, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world.runs["A"].end("needs-human", turns=1, reason="cannot be stated as is")
    _until(lambda: world.runs["T"].starts == 1, "T given a Decomposer turn")
    kw = world.runs["T"].kw[0]
    assert kw["roles"] == ["decomposer"] and kw["pursue"] and kw["redirect"].startswith("A is parked (needs-human: cannot be stated as is)")
    world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A2; the Coordinator works them"); world.runs["T"].claim = None
    world.runs["B"].end("needs-human", turns=1, reason="also stuck")
    _until(lambda: not c.active(), "the Coordinator ended")
    assert world.runs["T"].starts == 1  # once per parent
    assert sorted(node for node, _ in world.parked) == ["A", "B"]


def test_a_project_with_no_map_is_read_first_and_each_theorem_pursued_in_turn():
    from proof_agents.coordinator import ProjectPursuit, PursuitHooks

    stated: list[str] = []
    worlds = {"T1": World(edges={"T1": []}, kinds={"T1": "claim"}), "T2": World(edges={"T2": []}, kinds={"T2": "claim"})}
    coordinators = {name: Coordinator(CoordinatorHooks(subtree=w.subtree, run=lambda node, w=w: w.runs[node], budget=lambda: (2, 60.0),
                                                       parallel=lambda: 1), name, tick=0.01) for name, w in worlds.items()}
    reads = []

    def read(provider):
        reads.append(provider)
        stated.extend(["T1", "T2"])
        return {}

    pursuit = ProjectPursuit(PursuitHooks(read=read, theorems=lambda: list(stated), coordinator=coordinators.__getitem__), tick=0.01)
    pursuit.start("claude")
    _until(lambda: worlds["T1"].runs["T1"].starts == 1, "T1 pursued")
    assert reads == ["claude"] and worlds["T2"].runs["T2"].starts == 0  # one Theorem after another
    worlds["T1"].runs["T1"].end("done", verdict="passed", turns=1, reason="review-requested"); worlds["T1"].requested.add("T1")
    _until(lambda: worlds["T2"].runs["T2"].starts == 1, "T2 pursued next")
    worlds["T2"].runs["T2"].end("needs-human", turns=1, reason="?")
    _until(lambda: pursuit.view()["status"] == "done", "the pursuit ended")
    assert pursuit.view()["results"] == {"T1": {"status": "done", "reason": "T1 is requested for review"},
                                         "T2": {"status": "parked", "reason": "every open node in the subtree is parked: T2"}}


def test_a_dependent_started_on_a_provisional_node_is_redirected_when_the_researcher_accepts_it():
    world = World(edges={"T": ["A", "D"], "A": [], "D": ["A"]})
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1, "A started")
    world.runs["A"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("A")
    _until(lambda: world.runs["D"].starts == 1, "D started on A's Provisional statement")
    world.requested.discard("A"); world.accepted.add("A")
    _until(lambda: world.runs["D"].redirects, "D told that A is Accepted")
    assert world.runs["D"].redirects[0].startswith("A is Accepted: A holds")
    c.release()


# -- the audit of ADR-0021's Pursue ----------------------------------------------------------------------------------------


def test_a_start_that_took_no_turn_counts_toward_the_node_budget_and_the_node_is_parked_in_the_end():
    """P1-1: a run that ends before any turn counts — its turn could not start, or its loop raised — was started again
    forever. Each such Start spends one of the node budget's turns, so the node is parked once they are spent."""
    world = World(edges={"T": ["A"], "A": []}, parallel=1, budget=(3, 60.0), kinds={"T": "claim"})
    c = world.coordinator()
    c.start("claude")
    for start in (1, 2, 3):
        _until(lambda start=start: world.runs["A"].starts == start, f"A's start {start}")
        world.runs["A"].end("stuck", verdict=None, turns=0, reason="the turn could not start: no such provider")
    _until(lambda: c.view()["parked"], "A parked")
    time.sleep(0.05)
    assert world.runs["A"].starts == 3 and world.runs["A"].caps == [3, 2, 1]
    assert "its budget is spent" in c.view()["parked"][0]["reason"]
    _until(lambda: not c.active(), "the Coordinator ended")
    assert c.view()["status"] == "stuck" and "(parked: A)" in c.view()["reason"]


def test_a_node_whose_run_the_researcher_released_or_that_ended_done_short_of_review_is_left_to_the_researcher():
    """P1-5: the researcher's Stop and release of a node's run, or a run that ended done without a review request, is not
    undone by the Coordinator's restart: the node is the researcher's now, named as such, and the rest goes on."""
    for ending in ("released", "turn-finished"):
        world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2, budget=(5, 60.0))
        c = world.coordinator()
        c.start("claude")
        _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
        world.runs["A"].turns = 1
        if ending == "released":
            world.runs["A"].release("stopped and released by the researcher")
        else:
            world.runs["A"].end("done", verdict=None, turns=1, reason="turn-finished")
        _until(lambda: c.view()["held"], "A left to the researcher")
        world.runs["B"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("B")
        _until(lambda: not c.active(), "the Coordinator ended")
        assert world.runs["A"].starts == 1 and world.runs["T"].starts == 0, ending
        assert [h["node"] for h in c.view()["held"]] == ["A"] and c.view()["parked"] == []
        assert c.view()["status"] == "stuck" and "the researcher's: A" in c.view()["reason"], c.view()["reason"]


def test_a_decomposer_turn_that_split_nothing_is_not_noted_as_a_split_and_the_theorem_is_worked_as_one_argument():
    for budget, split in ((1, False), (3, False), (3, True)):
        world = World(edges={"T": []}, parallel=1, budget=(budget, 60.0))
        c = world.coordinator()
        c.start("claude")
        _until(lambda: world.runs["T"].starts == 1, "the Decomposer started on T")
        if split:
            world.edges.update({"T": ["A"], "A": []}); world.runs["A"] = FakeRun()
        world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A; the Coordinator works them" if split else "turn-finished")
        world.runs["T"].claim = None
        if budget == 1:   # no turn left to work it: what the Decomposer's turn ended as stays on the record
            _until(lambda: not c.active(), "the Coordinator ended")
            assert c.view()["nodes"]["T"]["last"] == "no-split" and c.view()["held"] == []
            continue
        if split:
            _until(lambda: world.runs["A"].starts == 1, "the Claim worked")
            assert c.view()["nodes"]["T"]["last"] == "split"
        else:
            _until(lambda: world.runs["T"].starts == 2, "T worked as one argument")
            assert world.runs["T"].kw[1] == {"pursue": True} and c.view()["held"] == []
        c.release()


def test_a_root_decomposed_by_this_start_still_gets_its_one_further_decomposer_turn_when_a_claim_parks():
    """P1-2: the first decomposition is not the further structure ADR-0021 point 9 gives a parent once per parent."""
    world = World(edges={"T": []}, parallel=2, budget=(5, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["T"].starts == 1, "the Decomposer started on T")
    world.edges.update({"T": ["A", "B"], "A": [], "B": []}); world.runs.update({"A": FakeRun(), "B": FakeRun()})
    world.runs["T"].end("done", turns=1, reason="split into 2 Claim(s): A, B; the Coordinator works them"); world.runs["T"].claim = None
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "the Claims are worked")
    world.runs["A"].end("needs-human", turns=1, reason="cannot be stated as is")
    _until(lambda: world.runs["T"].starts == 2, "T given its further Decomposer turn")
    kw = world.runs["T"].kw[1]
    assert kw["roles"] == ["decomposer"] and kw["redirect"].startswith("A is parked") and c.view()["resplit"] == ["T"]
    world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A2; the Coordinator works them"); world.runs["T"].claim = None
    world.runs["B"].end("needs-human", turns=1, reason="also stuck")
    _until(lambda: not c.active(), "the Coordinator ended")
    assert world.runs["T"].starts == 2 and c.view()["decomposed"] == ["T", "T"]  # exactly one further turn


def test_a_further_decomposer_turn_that_cannot_start_yet_is_kept_until_it_can():
    """P2-4: a parent's further structure computed when no run slot is free is not lost."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2, budget=(5, 60.0))
    hooks = world.hooks()
    hooks.parallel = lambda: world._parallel
    c = Coordinator(hooks, "T", tick=0.01)
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world._parallel = 1   # the researcher lowers `parallel`: B's run holds the one slot
    world.runs["A"].end("needs-human", turns=1, reason="cannot be stated as is")
    _until(lambda: c.view()["parked"], "A parked")
    time.sleep(0.05)
    assert world.runs["T"].starts == 0
    world._parallel = 2
    _until(lambda: world.runs["T"].starts == 1, "T's further Decomposer turn, once a slot is free")
    assert world.runs["T"].kw[0]["roles"] == ["decomposer"] and world.runs["T"].kw[0]["redirect"].startswith("A is parked")
    c.release()


def test_after_the_further_split_drops_the_parked_claim_the_parent_is_worked_once_its_new_claims_pass():
    """P1-3: the further Decomposer turn replaces the parked Claim — a new split, and the parent's edge to the parked Claim
    dropped (`proof node depend T --remove A`) — and the parent is started once its Claims are Accepted or Provisional."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2, budget=(5, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world.runs["B"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("B")
    world.runs["A"].end("needs-human", turns=1, reason="false as stated")
    _until(lambda: world.runs["T"].starts == 1, "T's further Decomposer turn")
    time.sleep(0.05)
    assert world.runs["T"].kw[0]["roles"] == ["decomposer"]
    world.runs["A2"] = FakeRun()
    world.edges.update({"T": ["B", "A2"], "A2": []})   # split again, and T's edge to A removed; A stays on the map, parked
    world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A2; the Coordinator works them"); world.runs["T"].claim = None
    _until(lambda: world.runs["A2"].starts == 1, "the new Claim worked")
    world.runs["A2"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("A2")
    _until(lambda: world.runs["T"].starts == 2, "T's own proof once its new Claims are Provisional")
    assert world.runs["T"].kw[1] == {"pursue": True} and "A" in c.view()["parked"][0]["node"]
    c.release()


def test_a_decomposer_turn_that_split_and_stopped_for_a_decision_holds_its_new_claims_and_the_siblings_go_on():
    """proof-agents#15 (PR #21 review): a contradiction the Decomposer reports in the same turn as its split leaves the
    Claims that split made for the researcher; the Claims there were before its turn are worked as ever."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=2, budget=(5, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world.runs["A"].end("needs-human", turns=1, reason="cannot be stated as is")
    _until(lambda: world.runs["T"].starts == 1, "T's further Decomposer turn")
    world.runs["A2"] = FakeRun()
    world.edges.update({"T": ["A", "B", "A2"], "A2": []})
    world.runs["T"].end("needs-human", turns=1, reason="the statement asks x > 0 and x <= 0"); world.runs["T"].claim = None
    _until(lambda: any(entry["node"] == "T" for entry in c.view()["parked"]), "T parked")
    time.sleep(0.05)
    assert world.runs["A2"].starts == 0
    assert c.view()["held"] == [{"node": "A2", "reason": "its split waits on the researcher's decision on T: the statement asks x > 0 and x <= 0"}]
    world.runs["B"].end("stuck", turns=1, reason="not yet")
    _until(lambda: world.runs["B"].starts == 2, "B, the sibling there was before, worked again")
    world.runs["B"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("B")
    _until(lambda: not c.active(), "the Coordinator ended")
    assert world.runs["A2"].starts == 0 and "the researcher's: A2" in c.view()["reason"]


@pytest.mark.parametrize("ending", ["needs-human", "done"])
def test_the_claims_a_running_decomposer_turn_split_off_wait_for_its_end(ending):
    """PR #21 review: a split is on the map before the Decomposer's turn ends; a free slot does not start its new Claims
    then. A needs-human ending leaves them held; any other ending lets them be worked."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=3, budget=(5, 60.0))
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world.runs["A"].end("needs-human", turns=1, reason="cannot be stated as is")
    _until(lambda: world.runs["T"].starts == 1, "T's further Decomposer turn")
    world.runs["A2"] = FakeRun()
    world.edges.update({"T": ["A", "B", "A2"], "A2": []})   # the split is written; the turn goes on
    time.sleep(0.1)   # several ticks, with a slot free
    assert world.runs["A2"].starts == 0
    world.runs["T"].end(ending, turns=1, reason="the statement asks x > 0 and x <= 0" if ending == "needs-human" else "split into 1 Claim(s): A2")
    world.runs["T"].claim = None
    if ending == "needs-human":
        _until(lambda: any(entry["node"] == "T" for entry in c.view()["parked"]), "T parked")
        time.sleep(0.05)
        assert world.runs["A2"].starts == 0 and [entry["node"] for entry in c.view()["held"]] == ["A2"]
    else:
        _until(lambda: world.runs["A2"].starts == 1, "A2 worked once the turn ended")
        assert c.view()["held"] == []
    c.release()


def test_a_decomposer_turn_that_splits_and_stops_for_a_decision_just_after_the_map_is_read_still_has_its_claims_held():
    """PR #21 review (cb62326): the map read, then the turn wrote its split and ended needs-human before the runs were
    read. The ending is seen before the map is read, so the parent is parked on a map with its new Claims."""
    world = World(edges={"T": ["A", "B"], "A": [], "B": []}, parallel=3, budget=(5, 60.0))
    armed = []

    def subtree():
        snapshot = world.subtree()
        if armed and armed.pop():   # once: the split and the ending land right after this read
            world.runs["A2"] = FakeRun()
            world.edges.update({"T": ["A", "B", "A2"], "A2": []})
            world.runs["T"].end("needs-human", turns=1, reason="the statement asks x > 0 and x <= 0"); world.runs["T"].claim = None
        return snapshot

    hooks = world.hooks()
    hooks.subtree = subtree
    c = Coordinator(hooks, "T", tick=0.01)
    c.start("claude")
    _until(lambda: world.runs["A"].starts == 1 and world.runs["B"].starts == 1, "A and B started")
    world.runs["A"].end("needs-human", turns=1, reason="cannot be stated as is")
    _until(lambda: world.runs["T"].starts == 1, "T's further Decomposer turn")
    armed.append(True)
    _until(lambda: any(entry["node"] == "T" for entry in c.view()["parked"]), "T parked")
    time.sleep(0.05)
    assert world.runs["A2"].starts == 0 and [entry["node"] for entry in c.view()["held"]] == ["A2"]
    c.release()


def test_a_child_sent_back_and_worked_again_has_its_parents_awaiting_snapshot_worked_again_too():
    """P2-5, ADR-0021 point 4: a child the researcher sends back makes its parent's proof Potentially stale; the Coordinator
    restarts the child, then — once the child is Provisional again — the parent, though its old snapshot still awaits review."""
    world = World(edges={"T": ["P"], "P": ["C"], "C": []}, parallel=2, budget=(5, 60.0))
    stale: set = set()   # the snapshots made Potentially stale: not Provisional, though they still await review
    world.subtree = (lambda subtree: lambda: [{**n, "provisional": n["provisional"] and n["id"] not in stale} for n in subtree()])(world.subtree)
    c = world.coordinator()
    c.start("claude")
    _until(lambda: world.runs["C"].starts == 1, "C started")
    world.runs["C"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("C")
    _until(lambda: world.runs["P"].starts == 1, "P started on C's Provisional statement")
    stale.add("P"); world.requested.discard("C")   # the researcher sends C back while P's run is still going
    _until(lambda: world.runs["C"].starts == 2, "C worked again")
    world.runs["P"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("P")   # on the old C
    time.sleep(0.05)
    assert world.runs["P"].starts == 1 and world.runs["T"].starts == 0   # C is not Provisional yet; P's snapshot is stale
    world.runs["C"].end("done", verdict="passed", turns=1, reason="review-requested"); world.requested.add("C")
    _until(lambda: world.runs["P"].starts == 2, "P worked again once C is Provisional again")
    c.release()


# -- ProjectPursuit's Stop (audit P2-6) -------------------------------------------------------------------------------------


def _pursuit(worlds, *, read=None, stated=None, coordinator=None, stop_read=None):
    from proof_agents.coordinator import ProjectPursuit, PursuitHooks

    stated = stated if stated is not None else list(worlds)
    made = {name: Coordinator(CoordinatorHooks(subtree=w.subtree, run=lambda node, w=w: w.runs[node], budget=lambda w=w: w._budget,
                                               parallel=lambda: 1), name, tick=0.01) for name, w in worlds.items()}
    hooks = PursuitHooks(read=read or (lambda provider: {}), theorems=lambda: list(stated), coordinator=coordinator or made.__getitem__,
                         **({"stop_read": stop_read} if stop_read else {}))
    return ProjectPursuit(hooks, tick=0.01), made


def test_stop_while_the_reader_reads_stops_its_turn_and_pursues_nothing():
    import threading

    reading, stopped = threading.Event(), threading.Event()
    stated: list[str] = []

    def read(provider):
        reading.set()
        stopped.wait(5)
        stated.append("T1")   # what it wrote before its turn was stopped stays on the map
        return {"error": "the turn was stopped", "code": "READER_FAILED"}

    worlds = {"T1": World(edges={"T1": []}, kinds={"T1": "claim"})}
    pursuit, _ = _pursuit(worlds, read=read, stated=stated, stop_read=stopped.set)
    pursuit.start("claude")
    _until(reading.is_set, "the Reader reading")
    assert pursuit.view()["status"] == "reading"
    assert pursuit.stop()["status"] == "released" and stopped.is_set()   # C4: stop_read is called
    time.sleep(0.1)
    assert worlds["T1"].runs["T1"].starts == 0 and pursuit.view()["status"] == "released"


def test_a_stop_before_the_theorems_coordinator_started_leaves_no_coordinator_running():
    import threading

    worlds = {"T1": World(edges={"T1": []}, kinds={"T1": "claim"})}
    gate, asked = threading.Event(), threading.Event()
    made: dict = {}

    def coordinator(theorem):   # the loop's call is held until the test lets it go; Stop's own call is not
        if not asked.is_set():
            asked.set()
            gate.wait(5)
        return made[theorem]

    pursuit, made_ = _pursuit(worlds, coordinator=coordinator)
    made.update(made_)
    pursuit.start("claude")
    _until(asked.is_set, "the loop about to start T1's Coordinator")
    assert pursuit.stop()["status"] == "released"
    gate.set()
    time.sleep(0.15)
    assert not made["T1"].active() and worlds["T1"].runs["T1"].status != "running"
    assert pursuit.view()["status"] == "released"


def test_a_coordinator_that_spent_its_budget_has_its_runs_stopped_before_the_next_theorem():
    worlds = {"T1": World(edges={"T1": []}, kinds={"T1": "claim"}, budget=(1, 60.0)), "T2": World(edges={"T2": []}, kinds={"T2": "claim"})}
    pursuit, made = _pursuit(worlds)
    pursuit.start("claude")
    _until(lambda: worlds["T1"].runs["T1"].starts == 1, "T1 pursued")
    worlds["T1"].runs["T1"].turns = 1   # still running, the Coordinator's budget spent
    _until(lambda: worlds["T2"].runs["T2"].starts == 1, "T2 pursued next")
    assert worlds["T1"].runs["T1"].status == "released" and pursuit.view()["results"]["T1"]["status"] == "budget"
    pursuit.stop()


def test_stop_on_a_finished_pursuit_leaves_its_ending_as_it_was():
    worlds = {"T1": World(edges={"T1": []}, kinds={"T1": "claim"})}
    pursuit, _ = _pursuit(worlds)
    pursuit.start("claude")
    _until(lambda: worlds["T1"].runs["T1"].starts == 1, "T1 pursued")
    worlds["T1"].runs["T1"].end("done", verdict="passed", turns=1, reason="review-requested"); worlds["T1"].requested.add("T1")
    _until(lambda: pursuit.view()["status"] == "done", "the pursuit ended")
    answer = pursuit.stop()
    assert answer["code"] == "NO_PURSUIT" and answer["status"] == "done" and pursuit.view()["reason"] == "every Theorem was pursued to its end"


def test_a_pursuit_is_active_while_its_thread_lives_a_stopped_one_until_its_reader_has_ended():
    import threading

    reading, stopped, let_go = threading.Event(), threading.Event(), threading.Event()

    def read(provider):
        reading.set()
        stopped.wait(5)
        let_go.wait(5)   # the Reader's turn takes a moment to end after Stop
        return {"error": "the turn was stopped", "code": "READER_FAILED"}

    worlds = {"T1": World(edges={"T1": []}, kinds={"T1": "claim"})}
    pursuit, _ = _pursuit(worlds, read=read, stated=[], stop_read=stopped.set)
    assert not pursuit.active()
    pursuit.start("claude")
    _until(reading.is_set, "the Reader reading")
    assert pursuit.active()
    pursuit.stop()
    time.sleep(0.05)
    assert pursuit.view()["status"] == "released" and pursuit.active()   # stopped, its Reader not ended yet
    assert pursuit.start("claude")["code"] == "PURSUIT_ACTIVE"
    let_go.set()
    _until(lambda: not pursuit.active(), "the pursuit's thread ended")
    assert pursuit.view()["status"] == "released"
