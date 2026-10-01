"""The Proof agent's run on a node (spec #145, decided in #144): Start once, then autonomous.

A run holds the node's claim under the project's agent name and works the node as three roles in
turn — Prover, Typesetter, Numerics — each the same CLI with its own brief, environment and write
scope; it stops when review is requested, when its budget is spent, when it is stuck, or when the
researcher pauses or releases it; a Redirect is handed to the next turn. A stub Claude Code on PATH
plays the CLI: each turn pops the next script from a queue file and runs its `proof` commands, so
the tests see the real launch (role, brief, permissions) and the real project state it produces.
"""

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from _proofs import write_key_ideas
from _review_client import DirectClient
from proof_cli.proof_map import create_node, get_active_claim, get_workflow_state, work_log
from proof_cli.storage import ensure_project
from proof_cli.webapp.studios import StudioHub

SRC = Path(__file__).resolve().parents[1] / "src"
# each invocation pops one script (a list of commands; ["write", path, text] writes a file) from FAKE_QUEUE
# and logs how it was started to FAKE_LOG (one JSON line per turn)
FAKE_CLAUDE = r'''#!{python}
import json, os, subprocess, sys
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": True, "email": "stub@example.org"}})); sys.exit(0)
prompt = sys.stdin.read()
queue_path = os.environ["FAKE_QUEUE"]
queue = json.load(open(queue_path)) if os.path.exists(queue_path) else []
script = queue.pop(0) if queue else []
json.dump(queue, open(queue_path, "w"))
log = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "role": os.environ.get("PROOF_AGENT_ROLE"), "name": os.environ.get("PROOF_AGENT_NAME"),
       "prompt": prompt, "brief": sys.argv[sys.argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in sys.argv else "", "ran": []}}
for command in script:
    if command[0] == "write":
        path = os.path.join(os.getcwd(), command[1]); os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").write(command[2]); continue
    if command[0] == "sleep":
        import time; time.sleep(float(command[1])); continue
    done = subprocess.run(command, capture_output=True, text=True)
    log["ran"].append({{"argv": command, "code": done.returncode, "out": done.stdout[-2000:], "err": done.stderr[-2000:]}})
open(os.environ["FAKE_LOG"], "a").write(json.dumps(log) + "\n")
print(json.dumps({{"type": "system", "subtype": "init", "session_id": "stub-session", "model": "stub"}}))
print(json.dumps({{"type": "result", "session_id": "stub-session", "is_error": False, "subtype": "success"}}))
'''


def _executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def studio(tmp_path: Path, monkeypatch):
    """A project with claim N, a stub Claude Code on PATH, `proof` running this checkout, and the hub."""
    project = tmp_path / "project"
    store = ensure_project(project)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "claude", FAKE_CLAUDE.format(python=sys.executable))
    _executable(bin_dir / "proof", f'#!/bin/sh\nexec "{sys.executable}" -m proof_cli.cli "$@"\n')
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTHONPATH", f"{SRC}{os.pathsep}{os.environ.get('PYTHONPATH', '')}")
    monkeypatch.setenv("CLAUDE_BIN", str(bin_dir / "claude"))
    for name in ("PROOF_ROOT", "PROOF_CLAUDE_ACCOUNT", "PROOF_AGENT_ROLE", "PROOF_AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    log = tmp_path / "claude-log.jsonl"
    queue = tmp_path / "queue.json"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_QUEUE", str(queue))
    hub = StudioHub(store)
    yield store, hub, log, queue
    hub.close()


def _queue(queue: Path, *scripts):
    queue.write_text(json.dumps(list(scripts)))


def _turns(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _post(hub, path, body=None):
    answer = hub.request("POST", path, "", body or {}, cross_site=False)
    return answer.status, json.loads(answer.body)


def _get(hub, path):
    answer = hub.request("GET", path, "", None, cross_site=False)
    return answer.status, json.loads(answer.body)


def _wait(hub, node="N", until=("done", "stuck", "budget", "paused", "released"), timeout=60):
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = _get(hub, f"/studio/{node}/api/agent/run")[1]
        if state["status"] in until:
            return state
        time.sleep(0.05)
    raise AssertionError(f"the run never reached {until}: {state}")


REVIEW = ["proof", "node", "request-review", "N", "--rationale", "scoped", "--requested-by", "claude-code"]


# -- Start once, then autonomous ------------------------------------------------------------------


def test_start_claims_the_node_under_the_agents_name_and_the_prover_goes_first(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--plan", "read", "--plan", "prove"]], [["sleep", "0"]])
    status, started = _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    assert status == 200 and started["status"] == "running", started
    claim = get_active_claim(store, "N")
    assert claim is not None and claim.claimant_id == "claude-code"  # the provider's name, unless proof.toml says otherwise
    _wait(hub, until=("done", "stuck", "budget"))
    first = _turns(log)[0]
    assert first["role"] == "prover" and first["name"] == "claude-code"
    assert "Prover" in first["brief"] and "scratch/" in first["brief"] and "never write proof.tex" in first["brief"]
    log = work_log(store, "N")
    assert log[0]["kind"] == "claimed" and log[0]["by"] == "claude-code"  # the run's claim opens the log
    assert log[1]["kind"] == "plan" and log[1]["role"] == "prover"


def test_a_run_stops_when_review_is_requested(studio):
    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue, [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}ok\\end{document}\n"], REVIEW], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    state = _wait(hub)
    assert state["status"] == "done" and state["reason"] == "review-requested"
    assert get_workflow_state(store, "N") == "review-needed" and get_active_claim(store, "N") is None
    assert len(_turns(log)) == 1  # nothing ran after the request


def test_the_whole_run_hands_the_work_from_the_prover_to_the_typesetter_and_back(studio):
    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue,
           [["proof", "node", "progress", "N", "--handoff", "typesetter", "--note", "write §2 as LaTeX"]],  # prover delegates
           [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}typeset\\end{document}\n"]],  # typesetter writes
           [REVIEW])  # prover closes
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    roles = [turn["role"] for turn in _turns(log)]
    assert roles == ["prover", "typesetter", "prover"] and state["reason"] == "review-requested"
    typesetter = _turns(log)[1]
    assert "write §2 as LaTeX" in typesetter["prompt"] and "Typesetter" in typesetter["brief"] and "never supply a missing step" in typesetter["brief"]
    assert "Bash(proof node split *)" not in typesetter["argv"] and "Edit(./key-ideas.md)" in typesetter["argv"]


def test_a_computation_node_hands_the_work_to_numerics(studio):
    store, hub, log, queue = studio
    create_node(store, node_id="C", kind="claim", statement="n ≤ 10^4 holds", medium="computation")
    write_key_ideas(store, "C")
    _queue(queue,
           [["proof", "node", "progress", "C", "--handoff", "numerics", "--note", "check n ≤ 10^4"]],
           [["write", "out/table.csv", "n,ratio\n"]],
           [["proof", "node", "request-review", "C", "--rationale", "a finite check", "--requested-by", "claude-code"]])
    _post(hub, "/studio/C/api/agent/start", {"provider": "claude"})
    _wait(hub, node="C")
    numerics = _turns(log)[1]
    assert numerics["role"] == "numerics" and "Numerics" in numerics["brief"] and "run.sh" in numerics["brief"]
    assert "Bash(proof node evidence record *)" in numerics["argv"] and "Edit(./out/**)" in numerics["argv"] and "Edit(./**/*.tex)" not in numerics["argv"]
    assert "Bash(./run.sh)" in numerics["argv"] and "Bash(bash *)" in numerics["argv"]  # it can run its own program
    assert "Bash(proof fog add *)" not in numerics["argv"]


# -- the run stops on its own ----------------------------------------------------------------------


def test_the_budget_stops_the_run_and_keeps_the_claim(studio):
    store, hub, log, queue = studio
    (store.root / "proof.toml").write_text("[studio]\nbudget_turns = 2\n")
    _queue(queue, *[[["write", f"scratch/t{i}.md", "x"]] for i in range(6)])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "budget" and len(_turns(log)) == 2 and state["turns"] == 2
    assert get_active_claim(store, "N") is not None  # it waits for the researcher, holding its place
    assert work_log(store, "N")[-1]["kind"] == "step" and work_log(store, "N")[-1]["status"] == "stuck"  # the run's own closing note


def test_turns_that_change_nothing_read_as_stuck(studio, monkeypatch):
    from proof_cli.studio import agent_run

    store, hub, log, queue = studio
    monkeypatch.setattr(agent_run, "STUCK_TURNS", 2)
    _queue(queue, *[[["sleep", "0"]] for _ in range(6)])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "stuck" and len(_turns(log)) == 2
    assert "no change" in state["reason"]


def test_a_turn_that_reports_stuck_or_a_decision_stops_the_run(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--step", "1", "--status", "stuck", "--note", "needs the researcher to choose the norm"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "stuck" and "choose the norm" in state["reason"] and len(_turns(log)) == 1


# -- oversight -----------------------------------------------------------------------------------


def test_pause_lets_the_turn_finish_then_holds_and_a_redirect_reaches_the_next_turn(studio):
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "0.6"]], [["sleep", "0"]], [["sleep", "0"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    time.sleep(0.2)
    assert _post(hub, "/studio/N/api/agent/pause")[1]["status"] in ("pausing", "paused")
    _wait(hub, until=("paused",))
    assert len(_turns(log)) == 1 and get_active_claim(store, "N") is not None
    _post(hub, "/studio/N/api/agent/redirect", {"text": "try the dual problem instead", "role": "prover"})
    _post(hub, "/studio/N/api/agent/resume")
    _wait(hub, until=("done", "stuck", "budget", "paused"))
    second = _turns(log)[1]
    assert "try the dual problem instead" in second["prompt"] and second["role"] == "prover"


def test_stop_and_release_ends_the_run_and_unassigns_the_node(studio):
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "5"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    time.sleep(0.3)
    status, released = _post(hub, "/studio/N/api/agent/release")
    assert status == 200 and released["status"] == "released"
    assert get_active_claim(store, "N") is None
    time.sleep(0.5)
    assert len(_turns(log)) <= 1 and _get(hub, "/studio/N/api/agent/run")[1]["status"] == "released"


def test_only_one_run_per_node_and_a_single_role_can_be_asked_for(studio):
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "1"]], [["sleep", "0"]])
    assert _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"]})[0] == 200
    status, again = _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    assert status == 409 and again["error"] == "RUN_ACTIVE"
    _wait(hub)
    assert [turn["role"] for turn in _turns(log)] == ["typesetter"]


# -- what the map and the node page see --------------------------------------------------------


def test_the_map_and_the_node_payload_show_the_runs_role_and_step(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--plan", "a", "--plan", "b", "--plan", "c"], ["proof", "node", "progress", "N", "--step", "2", "--status", "started"], ["sleep", "1.5"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    time.sleep(0.9)
    client = DirectClient(store)
    client.app.studios = hub  # the page's own hub is this one
    node = next(n for n in client.get("/api/map")[1]["data"]["nodes"] if n["id"] == "N")
    assert node["assignee"] == "claude-code" and node["run"] == {"status": "running", "role": "prover", "step": 2, "steps": 3}
    assert client.get("/api/node/N")[1]["data"]["run"]["role"] == "prover"
    _wait(hub)


def test_start_is_refused_while_someone_else_holds_the_node_and_leaves_no_run_behind(studio):
    from proof_cli.proof_map import claim_node

    store, hub, log, queue = studio
    claim_node(store, "N", claimant_id="ada")
    status, refused = _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    assert status == 400 and refused["error"] == "CLAIM_CONFLICT"  # the service's own refusal, as it stands
    assert _get(hub, "/studio/N/api/agent/run")[1]["status"] == "idle"
    assert get_active_claim(store, "N").claimant_id == "ada" and not _turns(log)


def test_the_typesetters_report_reaches_the_prover_when_it_hands_back_without_a_handoff(studio):
    store, hub, log, queue = studio
    _queue(queue,
           [["proof", "node", "progress", "N", "--handoff", "typesetter", "--note", "write it up"]],
           [["proof", "node", "progress", "N", "--step", "1", "--status", "done", "--note", "missing: the case n = 0"]],
           [["proof", "node", "progress", "N", "--step", "2", "--status", "stuck", "--note", "n = 0 needs a different argument"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    _wait(hub)
    prover_again = _turns(log)[2]
    assert prover_again["role"] == "prover" and "The typesetter reports: missing: the case n = 0" in prover_again["prompt"]


def test_the_budget_table_in_proof_toml_is_read(studio):
    store, hub, log, queue = studio
    (store.root / "proof.toml").write_text("[studio]\nbudget = { turns = 1, minutes = 60 }\n")
    _queue(queue, [["write", "scratch/a.md", "x"]], [["write", "scratch/b.md", "x"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "budget" and state["turns_max"] == 1 and len(_turns(log)) == 1


# -- the audit's findings on the run (P1, P2, P4) ---------------------------------------------------------


def test_the_time_budget_stops_a_turn_that_is_still_running(studio):
    store, hub, log, queue = studio
    (store.root / "proof.toml").write_text("[studio]\nbudget = { turns = 40, minutes = 0.02 }\n")  # 1.2 seconds
    _queue(queue, [["sleep", "20"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub, timeout=30)
    assert state["status"] == "budget" and "spent" in state["reason"]
    assert len(_turns(log)) <= 1  # the long turn was stopped; no second one ran
    assert get_active_claim(store, "N") is not None  # it waits for the researcher, holding its place


def test_a_second_start_while_the_first_is_still_being_assigned_is_refused():
    import threading

    from proof_cli.studio.agent_run import AgentRun, RunHooks

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

    from proof_cli.studio.agent_run import AgentRun, RunHooks

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


def test_stop_while_the_turn_is_being_prepared_starts_no_turn(studio, monkeypatch):
    """Third review T-P1: Stop lands while the manager is still checking the backend (its preflight). No turn may begin
    after it: the manager asks the run once more before the turn exists, and nothing is written."""
    import threading

    store, hub, log, queue = studio
    _queue(queue, [["write", "scratch/after-release.txt", "written after Stop"]])
    agent = hub.studio("N").agent
    backend = agent.backend("claude")
    entered, gate = threading.Event(), threading.Event()
    original = backend.preflight

    def slow_preflight(root):
        entered.set()
        assert gate.wait(5)
        return original(root)

    monkeypatch.setattr(backend, "preflight", slow_preflight)
    status, started = _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"]})
    assert status == 200 and entered.wait(5) and agent.active is None
    assert _post(hub, "/studio/N/api/agent/release")[1]["status"] == "released"
    gate.set()
    time.sleep(1.0)
    assert _get(hub, "/studio/N/api/agent/run")[1]["status"] == "released"
    assert agent.active is None and _turns(log) == []  # no turn ever existed
    assert not (store.root / "proofs" / "N" / "scratch" / "after-release.txt").exists()
    assert get_active_claim(store, "N") is None


def test_an_old_starts_assignment_coming_back_late_does_not_release_the_new_runs_claim():
    """Third review T-P2: the first Start is stopped while its assignment is still pending; a second Start under the
    same name claims the node; when the first assignment comes back, it must not give back what the second holds."""
    import threading
    from dataclasses import fields

    from proof_cli.proof_map import release_node
    from proof_cli.studio.agent_run import AgentRun, RunHooks

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
    from proof_cli.studio.agent_run import AgentRun, RunHooks

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
    from proof_cli.studio.agent_run import AgentRun, RunHooks

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
    from proof_cli.studio.agent_run import AgentRun, RunHooks

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


def test_a_start_right_after_stop_and_release_is_not_ended_by_the_old_coordinator(studio):
    """Reaudit R-P1: the first run's turn is still being stopped when the second Start begins; when it finally ends,
    only the first Start ends — the second keeps running its own turn and counts it."""
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "20"]], [["sleep", "1.5"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"]})
    agent = hub.studio("N").agent
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (agent.active and agent.active.proc):
        time.sleep(0.01)
    old = agent.active
    assert old is not None and _post(hub, "/studio/N/api/agent/release")[1]["status"] == "released"
    status, second = _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["numerics"]})
    assert status == 200 and second["status"] == "running"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (agent.active and agent.active is not old and agent.active.proc):
        time.sleep(0.01)
    assert old.done, "the old turn was stopped before the new one began"
    state = _get(hub, "/studio/N/api/agent/run")[1]
    assert (state["status"], state["turns"], state["roles"]) == ("running", 0, ["numerics"])  # the old coordinator's exit changed nothing
    final = _wait(hub, timeout=30)
    assert (final["status"], final["reason"], final["turns"]) == ("done", "turn-finished", 1)
    assert _turns(log)[-1]["role"] == "numerics" and get_active_claim(store, "N").claimant_id == "claude-code"


# -- what the studio's centre reads and does (spec #145, part 4) ---------------------------------------


def test_the_studio_serves_the_work_log(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--plan", "read", "--plan", "prove"], ["proof", "node", "progress", "N", "--step", "1", "--status", "started"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    _wait(hub)
    status, served = _get(hub, "/studio/N/api/agent/log")
    assert status == 200 and [e["kind"] for e in served["entries"]][:3] == ["claimed", "plan", "step"]


def test_review_what_it_has_freezes_a_snapshot_in_the_runs_name_and_ends_the_run(studio):
    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue, [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}half\\end{document}\n"], ["sleep", "2"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    time.sleep(1.2)
    status, frozen = _post(hub, "/studio/N/api/agent/review-now")
    assert status == 200 and frozen["version"] == 1
    assert get_workflow_state(store, "N") == "review-needed"
    from proof_cli.proof_map import list_candidate_proofs
    (proof,) = list_candidate_proofs(store, "N")
    assert proof.submitted_by == "claude-code"  # the node is the run's: the request is made in its name, and ends it
    state = _wait(hub)
    assert state["status"] == "done" and state["reason"] == "review-requested" and get_active_claim(store, "N") is None


def test_review_what_it_has_is_refused_when_nothing_can_be_frozen(studio):
    store, hub, log, queue = studio
    status, refused = _post(hub, "/studio/N/api/agent/review-now")  # no key ideas yet: the service refuses, and says so
    assert status == 409 and refused["error"] == "KEY_IDEAS_REQUIRED"


def test_the_log_lists_this_starts_turns_with_their_roles(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--handoff", "typesetter", "--note", "write it"]], [["sleep", "0"]], [["proof", "node", "progress", "N", "--step", "1", "--status", "stuck", "--note", "enough"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    _wait(hub)
    turns = _get(hub, "/studio/N/api/agent/log")[1]["turns"]
    assert [t["role"] for t in turns] == ["prover", "typesetter", "prover"] and all(t["done"] for t in turns) and "Take your turn as the Prover" in turns[0]["prompt"]


def test_the_chat_route_is_ask_only_whatever_the_body_says(studio):
    store, hub, log, queue = studio
    _queue(queue, [["write", "proof.tex", "edited by a chat turn\n"]])
    status, started = _post(hub, "/studio/N/api/agent", {"prompt": "rewrite the proof", "mode": "edit", "provider": "claude"})
    assert status == 200 and "job" in started
    job = hub.studio("N").agent.jobs[started["job"]]
    deadline = time.monotonic() + 30
    while not job.done and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.mode == "ask"  # the backend gets no Edit permission in this mode; what the stub wrote directly says nothing about that


def test_the_prover_may_open_a_challenge(studio):
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    assert "Bash(proof node challenge *)" in _turns(log)[0]["argv"]


def test_review_what_it_has_while_paused_ends_the_run_and_resume_does_nothing(studio):
    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue, [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}half\\end{document}\n"]], [["write", "scratch/after-review.md", "x"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    _post(hub, "/studio/N/api/agent/pause")
    _wait(hub, until=("paused",))
    status, frozen = _post(hub, "/studio/N/api/agent/review-now")
    assert status == 200 and frozen["version"] == 1
    state = _get(hub, "/studio/N/api/agent/run")[1]
    assert state["status"] == "done" and state["reason"] == "review-requested" and state["active"] is False
    assert _post(hub, "/studio/N/api/agent/resume")[1]["status"] == "done"  # nothing to resume
    time.sleep(0.8)
    assert not (store.root / "proofs" / "N" / "scratch" / "after-review.md").exists() and len(_turns(log)) == 1


# -- taken from upstream (prism-local 2938c05): the agent compiles through the studio's own build -------------


def test_the_typesetter_compiles_through_the_nodes_studio_not_a_shell(studio):
    from proof_cli.webapp.server import project_origin

    store, hub, log, queue = studio
    _queue(queue, [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"]})
    _wait(hub)
    argv = _turns(log)[0]["argv"]
    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert servers["studio"]["args"][-2:] == ["--url", f"{project_origin(store)}/studio/N/"] and "--strict-mcp-config" in argv
    assert "mcp__studio__compile" in argv and "Bash(latexmk *)" not in argv and "Bash(pdflatex *)" not in argv


def test_the_typesetter_on_codex_is_configured_with_the_compile_tool_too(studio, monkeypatch):
    """Fourth review F3: the same brief, the same tool — through Codex's configuration overrides."""
    from proof_cli.studio.backend_codex import Codex
    from proof_cli.webapp.server import project_origin

    store, hub, log, queue = studio
    agent = hub.studio("N").agent
    seen = []
    codex = Codex("codex", {"bin": "codex"})
    agent.backends["codex"] = codex
    monkeypatch.setattr(codex, "unavailable", lambda: None)
    monkeypatch.setattr(codex, "preflight", lambda root: None)
    monkeypatch.setattr(agent, "_run", lambda job, backend: seen.append(backend.command(job)))  # never start Codex
    _post(hub, "/studio/N/api/agent/start", {"provider": "codex", "roles": ["typesetter"]})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not seen:
        time.sleep(0.02)
    _post(hub, "/studio/N/api/agent/release")
    ((cmd, prompt),) = seen
    assert f'mcp_servers.studio.args=["{__import__("proof_cli.studio.mcp_compile", fromlist=["__file__"]).__file__}", "--url", "{project_origin(store)}/studio/N/"]' in cmd
    assert "compile it with the `compile` tool" in prompt


def test_only_a_typesetting_turn_on_a_latex_node_gets_the_compile_tool(studio):
    store, hub, log, queue = studio
    create_node(store, node_id="C", kind="claim", statement="n ≤ 10^4 holds", medium="computation")
    _queue(queue, [["sleep", "0"]], [["sleep", "0"]])
    _post(hub, "/studio/C/api/agent/start", {"provider": "claude", "roles": ["numerics"]})
    _wait(hub, node="C")
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    numerics, prover = _turns(log)
    assert "--mcp-config" not in numerics["argv"]  # a computation node has no build
    assert "--mcp-config" not in prover["argv"] and "mcp__studio__compile" not in prover["argv"]  # the Prover does not typeset


def test_a_build_the_agent_ran_shows_in_its_turn(studio):
    """The compile tool posts the build as the agent's: the turn's events carry it, so the page shows it as yours."""
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "3"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"]})
    deadline = time.monotonic() + 10
    agent = hub.studio("N").agent
    while time.monotonic() < deadline and not (agent.active and not agent.active.done):
        time.sleep(0.02)
    status, built = _post(hub, "/studio/N/api/build", {"mode": "draft", "by": "agent"})
    assert status == 200
    answer = hub.request("GET", "/studio/N/api/agent/events", f"job={agent.active.id}&after=0", None, cross_site=False)
    events = json.loads(answer.body)["events"]
    assert any(e["t"] == "build" and e["result"] == built for e in events)
    _post(hub, "/studio/N/api/agent/release")
