"""ADR-0021 on the page: Pursue, the review queue, and Conditional / Parked on the map.

Pursue is a Coordinator started on a Theorem — split first when it has no Claims yet — or on a project with a library
and no map, where a Reader turn states the draft first. What the agents leave the researcher is one queue, ordered
bottom-up so that each Accept makes the next decision possible; none of it holds the agents back.
"""

import dataclasses
from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from _review_client import DirectClient
from proof_cli.definitions import add_definition
from proof_cli.proof_map import create_node, record_evidence_check, record_progress, questions, work_log
from proof_cli.storage import ensure_project
from proof_web.studios import StudioHub


def _passed(store, node_id: str):
    proof = submit_proof(store, node_id, claimant_id="prover-1", scoping_rationale="scoped", content=f"proof of {node_id}")
    record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", notes="no objections")


@pytest.fixture
def project(tmp_path: Path):
    """A Theorem T over a Lemma L over a Claim C the Verifier passed, beside an unreviewed citation R that L also uses;
    C and L are an agent's, T is the researcher's."""
    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="R", kind="imported_result", statement="Known", source_locator="doi:x", source_version="v1", created_by="reader-1")
    create_node(store, node_id="C", kind="claim", statement="C holds", created_by="decomposer-1")
    create_node(store, node_id="L", kind="lemma", statement="L holds", dependencies=["C", "R"], created_by="reader-1")
    create_node(store, node_id="T", kind="theorem", statement="T holds", dependencies=["L"])
    _passed(store, "C")
    client = DirectClient(store)
    yield store, client
    client.app.close()


def _nodes(client) -> dict:
    return {n["id"]: n for n in client.get("/api/map")[1]["data"]["nodes"]}


def test_the_map_marks_provisional_and_conditional_nodes(project):
    store, client = project
    nodes = _nodes(client)
    assert (nodes["C"]["provisional"], nodes["C"]["conditional_on"]) == (True, [])
    assert nodes["R"]["provisional"] is True
    assert nodes["L"]["conditional_on"] == ["C", "R"] and nodes["L"]["frontier"]
    assert nodes["T"]["conditional_on"] == ["C", "R"] and not nodes["T"]["frontier"]
    assert not any(n["parked"] for n in nodes.values())


def test_a_parked_node_is_marked_on_the_map_until_work_on_it_resumes(project):
    store, client = project
    hub = client.app.studios
    hub._park("T", "L", "out of budget after 3 start(s)")
    assert _nodes(client)["L"]["parked"] == "out of budget after 3 start(s)"
    assert any(e.get("kind") == "coordinator" and e.get("note", "").startswith("parked") for e in work_log(store, "L"))
    record_progress(store, "L", role="prover", by="prover-2", step=1, status="started")
    assert _nodes(client)["L"]["parked"] is None


def test_the_review_queue_holds_everything_waiting_on_the_researcher_bottom_up(project):
    store, client = project
    add_definition(store, "D", term="height", text="h(x) = sup 1/Im", created_by="reader-1")
    record_progress(store, "C", role="prover", by="prover-1", question="read Γ as SL2(Z[1/p]); the alternative: a congruence subgroup")
    departures = store.root / "scratch" / "reader"
    departures.mkdir(parents=True)
    (departures / "departures.md").write_text("- the height's sup 1/Im is infinite; took the inf\n")
    client.app.studios._park("T", "L", "out of budget")

    queue = client.get("/api/review-queue")[1]["data"]
    kinds = [(item["kind"], item.get("node_id") or item.get("definition_id")) for item in queue["items"]]
    # the places the agents could not go first, then the rest bottom-up
    assert kinds[0] == ("parked", "L")
    assert kinds.index(("provisional", "C")) < kinds.index(("unfixed", "L"))
    assert ("imported", "R") in kinds
    assert ("question", "C") in kinds
    unfixed = {key for kind, key in kinds if kind == "unfixed"}
    assert unfixed >= {"C", "L", "D"} and "T" not in unfixed  # T is the researcher's own text: fixed for agents from the start
    assert queue["departures"] == "- the height's sup 1/Im is infinite; took the inf\n"
    question = next(item for item in queue["items"] if item["kind"] == "question")
    assert question["question"].startswith("read Γ as SL2(Z[1/p])")


def test_the_queue_reads_parked_first_then_each_node_s_text_before_the_decision_that_fixes_it(tmp_path: Path):
    """Parked nodes first, bottom-up; then the rest bottom-up, a node's questions and unfixed text (its statement, the
    Definitions it names) before its Accept, and a Definition no later than the first node that names it."""
    store = ensure_project(tmp_path / "project")
    add_definition(store, "D", term="height", text="h(x) = inf 1/Im", created_by="reader-1")
    add_definition(store, "E", term="orbit", text="the horocycle orbit", created_by="reader-1")
    create_node(store, node_id="C", kind="claim", statement="C holds", definitions=["D"], created_by="decomposer-1")
    create_node(store, node_id="L", kind="lemma", statement="L holds", dependencies=["C"], definitions=["D", "E"], created_by="reader-1")
    create_node(store, node_id="M", kind="lemma", statement="M holds", dependencies=["L"], created_by="reader-1")
    create_node(store, node_id="P", kind="lemma", statement="P holds", created_by="reader-1")
    create_node(store, node_id="T", kind="theorem", statement="T holds", dependencies=["M", "P"])
    _passed(store, "C")
    _passed(store, "L")
    record_progress(store, "C", role="prover", by="prover-1", question="took n ≥ 2; the alternative: n ≥ 1")
    record_progress(store, "L", role="prover", by="prover-1", question="read Γ as SL2(Z[1/p])")
    client = DirectClient(store)
    try:
        client.app.studios._park("T", "M", "out of budget")
        client.app.studios._park("T", "P", "out of budget")
        items = client.get("/api/review-queue")[1]["data"]["items"]
    finally:
        client.app.close()
    keys = [(item["kind"], item.get("node_id") or item.get("definition_id")) for item in items]
    at = keys.index

    assert keys[:2] == [("parked", "P"), ("parked", "M")]  # parked first overall, bottom-up: P rests on nothing unsettled
    assert at(("unfixed", "D")) < min(i for i, (_, key) in enumerate(keys) if key == "C")  # before the first node naming it
    assert at(("question", "C")) < at(("provisional", "C")) and at(("unfixed", "C")) < at(("provisional", "C"))
    assert at(("provisional", "C")) < at(("question", "L"))  # bottom-up across nodes: C's decision makes L's possible
    assert at(("unfixed", "E")) < at(("provisional", "L"))  # a Definition L names, read before L's Accept
    assert at(("question", "L")) < at(("provisional", "L")) and at(("unfixed", "L")) < at(("provisional", "L"))


def test_a_standing_question_is_answered_in_place(project):
    store, client = project
    record_progress(store, "C", role="prover", by="prover-1", question="took n ≥ 2; the alternative: n ≥ 1")
    question_id = questions(store, "C")[0]["id"]

    status, answered = client.post("/api/node/C/answer", {"question": question_id, "answer": "take n ≥ 1"})
    assert status == 200, answered
    assert questions(store, "C")[0]["answer"]["redirect"] == "take n ≥ 1"
    assert not any(item["kind"] == "question" for item in client.get("/api/review-queue")[1]["data"]["items"])
    again = client.post("/api/node/C/answer", {"question": question_id, "keep": True})
    assert again[1]["error"]["code"] == "QUESTION_ANSWERED"  # each is answered once
    assert client.post("/api/node/C/answer", {"question": "q_nope", "keep": True})[1]["error"]["code"] == "QUESTION_NOT_FOUND"


@pytest.mark.parametrize("keep", ["false", "yes", 1, 0, None, [True], {"keep": True}])
def test_an_answer_s_keep_is_a_json_boolean_and_nothing_else(project, keep):
    store, client = project
    record_progress(store, "C", role="prover", by="prover-1", question="took n ≥ 2; the alternative: n ≥ 1")
    question_id = questions(store, "C")[0]["id"]
    status, refused = client.post("/api/node/C/answer", {"question": question_id, "keep": keep})
    assert (status, refused["error"]["code"]) == (400, "INVALID_REQUEST")
    assert questions(store, "C")[0]["state"] == "open"  # nothing recorded
    assert client.post("/api/node/C/answer", {"question": question_id, "keep": True})[0] == 200


def test_the_coordinator_reads_provisional_awaiting_review_and_split_children(project):
    store, client = project
    hub = client.app.studios
    subtree = {n["id"]: n for n in hub._subtree("T")}
    assert subtree["C"]["provisional"] and subtree["C"]["awaiting_review"]
    submit_proof(store, "L", claimant_id="prover-1", scoping_rationale="scoped", content="proof of L")
    subtree = {n["id"]: n for n in hub._subtree("T")}
    assert subtree["L"]["workflow"] == "blocked" and subtree["L"]["awaiting_review"]  # Blocked on the axis, awaiting all the same
    assert subtree["T"]["split_children"] == []


def test_a_brief_names_each_dependency_s_kind_and_whether_it_is_provisional(project):
    store, client = project
    brief = client.app.studios._node_brief("L")
    deps = {d["id"]: d for d in brief["dependencies"]}
    assert (deps["C"]["kind"], deps["C"]["provisional"], deps["C"]["accepted"]) == ("claim", True, False)
    assert (deps["R"]["kind"], deps["R"]["provisional"]) == ("imported_result", True)
    researcher(store).decide_reference_review("R")
    deps = {d["id"]: d for d in client.app.studios._node_brief("L")["dependencies"]}
    assert (deps["R"]["accepted"], deps["R"]["provisional"]) == (True, False)  # Reference-reviewed counts as accepted here


def test_pursue_on_a_theorem_with_no_claims_has_a_coordinator(tmp_path: Path):
    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="T", kind="theorem", statement="T holds")
    create_node(store, node_id="X", kind="claim", statement="X holds")
    client = DirectClient(store)
    try:
        assert client.get("/api/node/T/coordinator")[1]["data"]["status"] == "idle"  # Pursue splits it first (ADR-0021 point 7)
        assert client.get("/api/node/X/coordinator")[0] == 404  # a Claim that rests on nothing has nothing to pursue
    finally:
        client.app.close()


def test_pursue_on_a_project_with_a_library_and_no_map(tmp_path: Path):
    root = tmp_path / "project"
    store = ensure_project(root)
    (root / "library").mkdir()
    (root / "library" / "main.tex").write_text("\\begin{theorem}T\\end{theorem}\n")
    (root / "proof.toml").write_text('[studio]\nlibrary = ["library"]\n')
    client = DirectClient(store)
    try:
        view = client.get("/api/pursue")[1]["data"]
        assert view["status"] == "idle" and view["can_pursue"] is True
        hub = client.app.studios
        read = []
        # the Reader's turn is the host's: a stand-in states one Theorem, then each Theorem gets its Coordinator
        hub._read_turn = lambda provider: read.append(provider) or create_node(store, node_id="T", kind="theorem", statement="T") and {}
        pursuit = hub.pursuit()
        assert pursuit.hooks.theorems() == []
        assert pursuit.hooks.read("claude") == {} and read == ["claude"]
        assert pursuit.hooks.theorems() == ["T"]
        assert pursuit.hooks.coordinator("T") is hub.coordinator("T")
        assert client.get("/api/pursue")[1]["data"]["can_pursue"] is False  # a map now: Pursue goes on its Theorems
    finally:
        client.app.close()


def test_the_home_offers_pursue_for_a_project_with_a_draft_and_no_map(tmp_path: Path):
    from proof_cli import projects
    from proof_web.home import HomeApp

    root = tmp_path / "horo"
    store = ensure_project(root)
    (root / "library").mkdir()
    (root / "library" / "main.tex").write_text("\\begin{theorem}T\\end{theorem}\n")
    projects.register_project(root)
    home = HomeApp()
    try:
        assert home.projects()["projects"][0]["can_pursue"] is False  # no library listed yet
        (root / "proof.toml").write_text('[studio]\nlibrary = ["library"]\n')
        assert home.projects()["projects"][0]["can_pursue"] is True
        create_node(store, node_id="T", kind="theorem", statement="T")
        assert home.projects()["projects"][0]["can_pursue"] is False  # a map: Pursue goes on a Theorem, from its page
    finally:
        home.close()


def test_the_home_does_not_offer_pursue_when_proof_agents_has_no_project_pursuit(tmp_path: Path, monkeypatch):
    from proof_cli import projects
    from proof_web import studios
    from proof_web.home import HomeApp

    root = tmp_path / "horo"
    ensure_project(root)
    (root / "library").mkdir()
    (root / "library" / "main.tex").write_text("\\begin{theorem}T\\end{theorem}\n")
    (root / "proof.toml").write_text('[studio]\nlibrary = ["library"]\n')
    projects.register_project(root)
    monkeypatch.setattr(studios, "ProjectPursuit", None)  # an older proof-agents: no Reader, no project pursuit
    home = HomeApp()
    try:
        assert home.projects()["projects"][0]["can_pursue"] is False
    finally:
        home.close()


def test_a_parked_node_reads_parked(project):
    store, client = project
    client.app.studios._park("T", "L", "out of budget")
    assert _nodes(client)["L"]["status"] == {"text": "Parked", "kind": "attention"}


def test_a_turn_a_coordinator_s_pursue_started_reaches_the_role_as_pursue(project):
    store, client = project
    hub = client.app.studios
    assert hub.studio("T").agent.context_fn({"role": "decomposer", "name": "claude-code", "pursue": True}).pursue is True
    assert hub.studio("T").agent.context_fn({"role": "decomposer", "name": "claude-code"}).pursue is False  # started alone: it stops


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_a_parked_node_stops_reading_parked_once_the_researcher_decides_it(project, decision):
    store, client = project
    client.app.studios._park("T", "C", "out of budget")
    assert _nodes(client)["C"]["parked"] == "out of budget"
    researcher(store).decide_acceptance("C", decision)

    node = _nodes(client)["C"]
    assert node["parked"] is None
    assert node["status"]["text"] != "Parked"
    queue = client.get("/api/review-queue")[1]["data"]["items"]
    assert not any(item["kind"] == "parked" and item.get("node_id") == "C" for item in queue)


def test_a_decided_node_never_reads_parked_whatever_the_map_field_says():
    from proof_web.node_status import node_status

    for acceptance, text in (("accepted", "Accepted"), ("rejected", "Rejected"), ("no-longer-callable", "No longer callable")):
        node = {"workflow_state": "accepted" if acceptance == "accepted" else "rejected", "acceptance_state": acceptance,
                "integrity_state": "valid", "parked": "out of budget"}
        assert node_status(node)["text"] == text


class _ReaderStandIn:
    """The Reader's agent manager, standing in: a turn that runs until it is stopped, and a stop that ends it only
    when the test lets it (`ends`), as a backend may take a while to wind down."""

    def __init__(self) -> None:
        import threading
        from types import SimpleNamespace

        self.started, self.stopped, self.ends = threading.Event(), [], threading.Event()
        self.job = SimpleNamespace(id=7, cond=threading.Condition(), done=False, events=[])
        self.jobs = {7: self.job}

    def start(self, *args, begin=None, unless=None, **kwargs):
        if unless is not None and unless():
            return {"error": "stopped", "code": "STOPPED"}
        if begin is not None:
            begin(self.job)
        self.started.set()
        return {"job": 7}

    def stop(self, job_id):
        self.stopped.append(job_id)
        import threading

        def end():
            self.ends.wait(10)
            with self.job.cond:
                self.job.events.append({"t": "done", "exit": 1, "is_error": True, "subtype": "stopped"})
                self.job.done = True
                self.job.cond.notify_all()
        threading.Thread(target=end, daemon=True).start()
        return {"ok": True}

    def backend(self, provider):
        return None

    def shutdown(self):
        self.ends.set()


@pytest.fixture
def drafted(tmp_path: Path):
    """A project with a draft in its library and no map, its Reader stood in for."""
    root = tmp_path / "project"
    store = ensure_project(root)
    (root / "library").mkdir()
    (root / "library" / "main.tex").write_text("\\begin{theorem}T\\end{theorem}\n")
    (root / "proof.toml").write_text('[studio]\nlibrary = ["library"]\n')
    from proof_web import studios

    if studios.ProjectPursuit is None:
        pytest.skip("this proof-agents has no project pursuit")
    client = DirectClient(store)
    reader = _ReaderStandIn()
    client.app.studios._reader = reader
    yield store, client, reader
    reader.ends.set()
    client.app.close()


def _until(condition, timeout=10.0):
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def test_stop_while_the_reader_reads_stops_the_reader_s_turn(drafted):
    store, client, reader = drafted
    status, started = client.post("/api/pursue/start", {"provider": "claude"})
    assert status == 200, started
    assert reader.started.wait(10)
    assert client.get("/api/pursue")[1]["data"]["status"] == "reading"

    assert client.post("/api/pursue/stop", {})[0] == 200
    assert reader.stopped == [7]  # the Reader's own turn, not only the pursuit's flag


def test_pursue_is_neither_offered_nor_started_again_until_the_stopped_reader_has_ended(drafted):
    store, client, reader = drafted
    client.post("/api/pursue/start", {"provider": "claude"})
    assert reader.started.wait(10)
    client.post("/api/pursue/stop", {})

    view = client.get("/api/pursue")[1]["data"]
    assert view["can_pursue"] is False and view["stopping"] is True  # the map is still empty, but the Reader's turn has not ended yet
    status, again = client.post("/api/pursue/start", {"provider": "claude"})
    assert status == 409 and again["error"]["code"] == "PURSUIT_ACTIVE"

    reader.ends.set()
    _until(lambda: client.get("/api/pursue")[1]["data"]["can_pursue"] is True)
    assert client.get("/api/pursue")[1]["data"]["stopping"] is False



def test_pursue_start_is_refused_from_another_origin(drafted):
    import io

    from proof_web.server import _Handler

    store, client, reader = drafted
    app = client.app
    handler_class = type("InProcessHandler", (_Handler,), {"app": app})
    netloc = app.origin.split("://", 1)[1]
    for origin in ("http://evil.example", None):
        headers = {"Host": netloc, "Content-Type": "application/json", "Content-Length": "2", **({"Origin": origin} if origin else {})}
        raw = "POST /api/pursue/start HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n{}"
        handler = handler_class.__new__(handler_class)
        handler.rfile, handler.wfile = io.BytesIO(raw.encode()), io.BytesIO()
        handler.client_address, handler.server, handler.request = ("127.0.0.1", 0), None, None
        handler.handle_one_request()
        status_line = handler.wfile.getvalue().split(b"\r\n", 1)[0].decode()
        assert status_line.split()[1] == "403", status_line
        assert b"WRONG_ORIGIN" in handler.wfile.getvalue()
    assert not reader.started.is_set() and client.get("/api/pursue")[1]["data"]["status"] == "idle"


def test_the_pursuit_is_handed_the_hub_s_stop_read(drafted):
    from proof_agents.coordinator import PursuitHooks

    if "stop_read" not in {f.name for f in dataclasses.fields(PursuitHooks)}:
        pytest.skip("this proof-agents has no stop_read (contract C4)")
    store, client, reader = drafted
    hub = client.app.studios
    assert hub.pursuit().hooks.stop_read == hub._stop_read
    hub._stop_read()  # no Reader running: nothing to stop
    assert reader.stopped == []


def test_stop_on_a_pursuit_that_already_ended_is_no_error_and_keeps_its_ending(drafted):
    store, client, reader = drafted
    status, view = client.post("/api/pursue/stop", {})  # never started
    assert status == 200 and view["data"]["status"] == "idle", view
    client.app.studios._read_turn = lambda provider: {"error": "no backend", "code": "NO_BACKEND"}
    client.post("/api/pursue/start", {"provider": "claude"})
    _until(lambda: client.get("/api/pursue")[1]["data"]["status"] == "stuck" and not client.app.studios._pursuit_busy())
    status, view = client.post("/api/pursue/stop", {})
    assert status == 200 and view["data"]["status"] == "stuck", view  # its ending stands; nothing was released


class _HeldCoordinator:
    """A Theorem's Coordinator whose release fails as often as the test says, then gives its runs back."""

    def __init__(self, fails: int) -> None:
        self.fails, self.released, self.asked = fails, False, 0

    def open_nodes(self):   # proof-agents#19: what the default total counts
        return []

    def start(self, provider, **limits):   # proof-agents#19: the Pursue's shared budget, or the researcher's limits
        return {"status": "running"}

    def active(self):
        return not self.released

    def view(self):
        return {"status": "released" if self.released else "running", "reason": "", "settling": False}

    def release(self):
        self.asked += 1
        if self.fails:
            self.fails -= 1
            return {"error": "L1 is still claimed by claude-code", "code": "RELEASE_FAILED"}
        self.released = True
        return {"status": "released"}


def test_a_failed_release_holds_the_pursuit_until_stop_gives_its_runs_back(drafted):
    """proof-web#12: Stop on a pursuit whose release fails (proof-agents#17) answers RELEASE_FAILED; the view reads
    release-failed on its Theorem, neither stopping nor offering Pursue, Pursue is refused, and Stop again retries."""
    from proof_web import studios

    if not hasattr(studios.ProjectPursuit, "_release_failed"):
        pytest.skip("needs proof-agents#17")
    store, client, reader = drafted
    create_node(store, node_id="T1", kind="theorem", statement="T1 holds")  # a map already: no Reader turn
    held = _HeldCoordinator(fails=2)
    client.app.studios.coordinator = lambda theorem: held
    assert client.post("/api/pursue/start", {"provider": "claude"})[0] == 200
    _until(lambda: client.get("/api/pursue")[1]["data"]["status"] == "pursuing")
    for attempt in (1, 2):
        status, answer = client.post("/api/pursue/stop", {})
        assert status == 409 and answer["error"]["code"] == "RELEASE_FAILED" and held.asked == attempt, answer
        view = client.get("/api/pursue")[1]["data"]
        assert (view["status"], view["current"], view["stopping"], view["can_pursue"]) == ("release-failed", "T1", False, False)
        assert "L1 is still claimed by claude-code" in view["reason"]
        status, refused = client.post("/api/pursue/start", {"provider": "claude"})
        assert status == 409 and refused["error"]["code"] == "PURSUIT_ACTIVE"
    status, answer = client.post("/api/pursue/stop", {})
    assert status == 200 and answer["data"]["status"] == "released" and held.released
    _until(lambda: client.get("/api/pursue")[1]["data"]["stopping"] is False)
    assert client.get("/api/pursue")[1]["data"]["status"] == "released"


def test_while_a_stop_gives_the_runs_back_the_pursuit_reads_stopping_and_pursue_waits(drafted):
    import threading

    from proof_web import studios

    if not hasattr(studios.ProjectPursuit, "_release_failed"):
        pytest.skip("needs proof-agents#17")
    store, client, reader = drafted
    create_node(store, node_id="T1", kind="theorem", statement="T1 holds")
    held, going, go = _HeldCoordinator(fails=0), threading.Event(), threading.Event()
    release = held.release
    held.release = lambda: (going.set(), go.wait(10), release())[-1]  # the release takes a while
    client.app.studios.coordinator = lambda theorem: held
    client.post("/api/pursue/start", {"provider": "claude"})
    _until(lambda: client.get("/api/pursue")[1]["data"]["status"] == "pursuing")
    stopped = []
    stop = threading.Thread(target=lambda: stopped.append(client.post("/api/pursue/stop", {})))
    stop.start()
    assert going.wait(10)
    view = client.get("/api/pursue")[1]["data"]
    assert (view["status"], view["current"], view["stopping"], view["can_pursue"]) == ("stopping", "T1", True, False)
    assert client.post("/api/pursue/start", {"provider": "claude"})[1]["error"]["code"] == "PURSUIT_ACTIVE"
    go.set()
    stop.join(10)
    assert stopped[0][0] == 200 and stopped[0][1]["data"]["status"] == "released"

def test_a_run_s_standing_question_is_recorded_on_the_node(project):
    from proof_agents.agent_run import RunHooks

    if "record_question" not in {f.name for f in dataclasses.fields(RunHooks)}:
        pytest.skip("this proof-agents has no record_question")
    store, client = project
    hooks = client.app.studios._run_hooks("C")
    hooks.record_question("prover", "prover-1", "took n ≥ 2; the alternative: n ≥ 1")
    (asked,) = questions(store, "C")
    assert asked["question"] == "took n ≥ 2; the alternative: n ≥ 1" and asked["state"] == "open"
    assert any(item["kind"] == "question" and item["node_id"] == "C" for item in client.get("/api/review-queue")[1]["data"]["items"])


def test_the_map_says_which_definition_edit_left_a_snapshot_stale(project):
    """T8 (proof-cli#197): the Warnings page names the Definition, who edited it and why, from the map's stale_cause."""
    from proof_cli import proof_map
    from proof_cli.definitions import edit_definition

    if not hasattr(proof_map, "get_stale_cause"):
        pytest.skip("this proof-cli has no stale cause")
    store, client = project
    add_definition(store, "D", term="Positive parameter", text="$n \\ge 1$", created_by="reader-1")
    create_node(store, node_id="E", kind="claim", statement="E holds for n", definitions=["D"], created_by="decomposer-1")
    _passed(store, "E")
    edit_definition(store, "D", text="$n \\ge 2$", edited_by="reader-1", reason="n = 1 is degenerate")

    cause = _nodes(client)["E"]["stale_cause"]
    assert (cause["cause"], cause["definition_id"], cause["by"], cause["reason"]) == ("definition-edited", "D", "reader-1", "n = 1 is degenerate")
    assert _nodes(client)["C"]["stale_cause"] is None
