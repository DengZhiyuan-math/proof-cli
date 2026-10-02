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
# each invocation pops one script (a list of commands; ["write", path, text] writes a file, ["tool", command]
# reports a shell command the agent ran, as Claude Code's stream does) from FAKE_QUEUE and logs how it was
# started to FAKE_LOG (one JSON line per turn)
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
tools = []
for command in script:
    if command[0] == "tool":
        tools.append(command[1]); continue
    if command[0] == "write":
        path = os.path.join(os.getcwd(), command[1]); os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").write(command[2]); continue
    if command[0] == "sleep":
        import time; time.sleep(float(command[1])); continue
    done = subprocess.run(command, capture_output=True, text=True)
    log["ran"].append({{"argv": command, "code": done.returncode, "out": done.stdout[-2000:], "err": done.stderr[-2000:]}})
open(os.environ["FAKE_LOG"], "a").write(json.dumps(log) + "\n")
print(json.dumps({{"type": "system", "subtype": "init", "session_id": "stub-session", "model": "stub"}}))
for i, tool in enumerate(tools):
    print(json.dumps({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": f"t{{i}}", "name": "Bash", "input": {{"command": tool}}}}]}}}}))
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


def _hooks(**given):
    """A run's hooks for the tests that drive AgentRun alone: what is not given does nothing."""
    from dataclasses import fields

    from proof_cli.studio.agent_run import RunHooks

    base = dict(agent_name=lambda provider: "claude-code", budget=lambda: (40, 60.0), assign=lambda name: None,
                release=lambda name, reason: None, work_log=lambda: [], record_close=lambda *a: None)
    names = {f.name for f in fields(RunHooks)}
    return RunHooks(**{key: value for key, value in {**base, **given}.items() if key in names})


def _wait(hub, node="N", until=("done", "stuck", "budget", "needs-human", "paused", "released"), timeout=60):
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
    assert "Bash(./run.sh)" in numerics["argv"] and "Bash(bash *)" not in numerics["argv"]  # its own program, never a general shell
    assert "Bash(proof fog add *)" in numerics["argv"]  # the duty of every role: an unclear direction goes in the fog


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
    assert node["assignee"] == "claude-code" and node["run"] == {"status": "running", "role": "prover", "step": 2, "steps": 3, "decision": None}
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

    from proof_cli.studio.agent_run import AgentRun

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

    from proof_cli.studio.agent_run import AgentRun

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
    from proof_cli.proof_map import release_node
    from proof_cli.studio.agent_run import AgentRun

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
    from proof_cli.studio.agent_run import AgentRun

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
    from proof_cli.studio.agent_run import AgentRun

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



# -- seventh review (PR #148) -----------------------------------------------------------------------


def _fake_turns(on_turn):
    """An agent manager whose every turn ends at once after `on_turn(turn)` ran — the project side effects of a turn."""
    import itertools

    from proof_cli.studio.backends import Job

    class Agent:
        def __init__(self):
            self.jobs, self.ids = {}, itertools.count(1)

        def start(self, *args, turn=None, **kwargs):
            job = Job(next(self.ids))
            self.jobs[job.id] = job
            on_turn(turn)
            job.emit({"t": "done", "changed": [], "session_id": f"session-{job.id}"})
            with job.cond:
                job.done = True
                job.cond.notify_all()
            return {"job": job.id}

        def stop(self, jid):
            pass

    return Agent()


@pytest.mark.parametrize("role", ["prover", "typesetter", "numerics"])
def test_no_role_may_run_a_general_shell(tmp_path, role):
    """ADR-0011/0004: a role's write scope means nothing if it can run a shell that runs anything — `proof review`, a
    write outside the node. A role's programs are named; an interpreter's inline code (`python3 -c`, `-m`) is denied."""
    from proof_cli.studio.proof_agent import ProofAgentContext

    args = ProofAgentContext("N", tmp_path, [], role=role).claude_args(True)
    allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
    denied = args[args.index("--disallowedTools") + 1:]
    shells = {"bash", "sh", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "env", "xargs", "eval", "exec", "nohup", "sudo", "osascript", "perl", "ruby", "node"}
    for rule in allowed:
        assert rule != "Bash" and not rule.startswith("Bash(*"), rule
        if rule.startswith("Bash("):
            command = rule[len("Bash("):-1].split()[0]
            assert command not in shells, rule
            assert rule != "Bash(proof *)" and "review " not in rule.replace("request-review", ""), rule  # named `proof` commands only
    for interpreter in ("python", "python3", "sage"):
        if f"Bash({interpreter} *)" in allowed:
            assert f"Bash({interpreter} -c *)" in denied and f"Bash({interpreter} -m *)" in denied, interpreter


@pytest.mark.parametrize("role", ["prover", "typesetter", "numerics"])
def test_every_role_puts_an_unclear_direction_in_the_fog_when_it_stops(tmp_path, role):
    """Spec #145: 停下时写 progress … 说不清的方向 fog add --near — the duty of every role, in its brief and its permissions."""
    from proof_cli.studio.proof_agent import ProofAgentContext

    context = ProofAgentContext("N", tmp_path, [], role=role, name="claude-code")
    assert "proof fog add" in context.brief() and "--near N" in context.brief()
    assert "Bash(proof fog add *)" in context.claude_args(True)


def test_several_roles_run_as_a_flow_restricted_to_them_in_the_specs_order(studio):
    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue,
           [["proof", "node", "progress", "N", "--handoff", "typesetter", "--note", "write it up"]],  # not part of this Start
           [["proof", "node", "progress", "N", "--handoff", "numerics", "--note", "check n ≤ 100"]],
           [["write", "out/check.csv", "n\n"]],
           [REVIEW])
    status, started = _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["numerics", "prover"]})
    assert status == 200 and started["roles"] == ["prover", "numerics"]  # the spec's order, whatever order they were asked in
    state = _wait(hub)
    turns = _turns(log)
    assert [turn["role"] for turn in turns] == ["prover", "prover", "numerics", "prover"] and state["reason"] == "review-requested"
    assert "only the Prover and the Numerics" in turns[0]["prompt"]
    assert "The Typesetter is not part of this Start" in turns[1]["prompt"]
    assert "check n ≤ 100" in turns[2]["prompt"]


def test_several_roles_without_the_prover_end_when_the_first_hands_nothing_over(studio):
    store, hub, log, queue = studio
    _queue(queue,
           [["proof", "node", "progress", "N", "--handoff", "numerics", "--note", "the table for §3"]],
           [["write", "out/table.csv", "n\n"]],
           [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}ok\\end{document}\n"]],
           [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter", "numerics"]})
    state = _wait(hub)
    assert [turn["role"] for turn in _turns(log)] == ["typesetter", "numerics", "typesetter"]
    assert (state["status"], state["reason"]) == ("done", "turn-finished")


def test_progress_narration_alone_does_not_count_as_a_change(studio, monkeypatch):
    """Spec #145: stuck = turns with no `proof` write, file change or run. A plan, a step or a handoff alone is narration."""
    from proof_cli.studio import agent_run

    store, hub, log, queue = studio
    monkeypatch.setattr(agent_run, "STUCK_TURNS", 3)
    _queue(queue,
           [["proof", "node", "progress", "N", "--plan", "a", "--plan", "b"]],
           [["proof", "node", "progress", "N", "--step", "1", "--status", "started"]],
           [["proof", "node", "progress", "N", "--step", "1", "--status", "done", "--note", "nothing yet"]],
           [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "stuck" and "no change in 3 turn(s)" in state["reason"] and len(_turns(log)) == 3


def test_a_run_a_proof_write_or_a_file_change_each_count_as_a_change(studio, monkeypatch):
    from proof_cli.studio import agent_run

    store, hub, log, queue = studio
    monkeypatch.setattr(agent_run, "STUCK_TURNS", 2)
    _queue(queue,
           [["sleep", "0"]],
           [["tool", "python3 scratch/check.py --n 100"]],  # a run
           [["sleep", "0"]],
           [["proof", "fog", "add", "maybe the dual norm", "--near", "N", "--created-by", "claude-code"]],  # a `proof` write
           [["sleep", "0"]],
           [["write", "scratch/draft.md", "x"]],  # a file change
           [["sleep", "0"]], [["sleep", "0"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "stuck" and len(_turns(log)) == 8, state


def test_pause_stops_the_budget_clock_and_resume_continues_with_what_is_left(studio):
    store, hub, log, queue = studio
    (store.root / "proof.toml").write_text("[studio]\nbudget = { turns = 3, minutes = 0.04 }\n")  # 2.4 seconds
    _queue(queue, [["sleep", "0.4"]], [["write", "scratch/a.md", "a"]], [["write", "scratch/b.md", "b"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    time.sleep(0.1)
    _post(hub, "/studio/N/api/agent/pause")
    paused = _wait(hub, until=("paused",))
    left = paused["minutes_left"]
    assert 0 < left <= 0.04
    time.sleep(3.0)  # longer than the whole budget: none of it is spent while paused
    assert _get(hub, "/studio/N/api/agent/run")[1]["minutes_left"] == pytest.approx(left, abs=1e-6)
    _post(hub, "/studio/N/api/agent/resume")
    state = _wait(hub, until=("done", "stuck", "budget"))
    assert len(_turns(log)) >= 2, state  # the next turn ran: the pause did not use up the budget


def test_redirect_with_no_run_is_refused_with_no_run(studio):
    store, hub, log, queue = studio
    status, refused = _post(hub, "/studio/N/api/agent/redirect", {"text": "try the dual problem"})
    assert status == 409 and refused["error"] == "NO_RUN"


def test_a_decision_only_a_human_can_make_stops_the_run_as_needs_human_and_names_it(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--step", "1", "--status", "needs-human", "--note", "choose the L2 or the sup norm"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    state = _wait(hub)
    assert state["status"] == "needs-human" and state["decision"] == "choose the L2 or the sup norm" and len(_turns(log)) == 1
    asked = [e for e in work_log(store, "N") if e.get("kind") == "step" and e.get("status") == "needs-human"]
    assert asked and asked[0]["note"] == "choose the L2 or the sup norm" and asked[0]["role"] == "prover"
    assert get_active_claim(store, "N") is not None  # it holds its place for the researcher's answer
    client = DirectClient(store)
    client.app.studios = hub
    node = next(n for n in client.get("/api/map")[1]["data"]["nodes"] if n["id"] == "N")
    assert node["run"]["status"] == "needs-human" and node["run"]["decision"] == "choose the L2 or the sup norm"


def test_the_run_leaves_a_closing_note_on_every_stop(studio):
    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue, [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}ok\\end{document}\n"], REVIEW])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    last = [e for e in work_log(store, "N") if e.get("kind") == "step"][-1]
    assert (last["status"], last["role"], last["by"]) == ("done", "prover", "claude-code") and "review-requested" in last["note"]
    _queue(queue, [["sleep", "5"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"]})
    time.sleep(0.4)
    _post(hub, "/studio/N/api/agent/release")
    last = [e for e in work_log(store, "N") if e.get("kind") == "step"][-1]
    assert (last["status"], last["role"]) == ("done", "typesetter") and "released" in last["note"]


def test_work_log_entries_carry_the_role_of_the_turn_and_each_turn_its_job_session_step_and_transcript(studio):
    from proof_cli.proof_map import agent_turn_transcript

    store, hub, log, queue = studio
    _queue(queue,
           [["proof", "node", "progress", "N", "--plan", "look", "--plan", "compute"], ["proof", "node", "progress", "N", "--step", "1", "--status", "started"],
            ["proof", "fog", "add", "a direction I can't state yet", "--near", "N", "--created-by", "claude-code"],
            ["proof", "node", "progress", "N", "--handoff", "numerics", "--note", "compute"]],
           [["proof", "node", "progress", "N", "--step", "2", "--status", "stuck", "--note", "no interpreter"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    _wait(hub)
    entries = work_log(store, "N")
    fog = next(e for e in entries if e["kind"] == "fog")
    assert fog["role"] == "prover" and fog["text"] == "a direction I can't state yet"  # an automatic entry, the role of its turn
    turns = [e for e in entries if e["kind"] == "turn"]
    assert [(t["role"], t["step"]) for t in turns] == [("prover", 1), ("numerics", 2)]
    assert all(t["job"] and t["session_id"] == "stub-session" and t["turn"] for t in turns)
    # the raw conversation is kept with the project: a new Start, or a restart, still finds it
    hub.close()
    again = StudioHub(store)
    try:
        answer = again.request("GET", "/studio/N/api/agent/turn", f"turn={turns[0]['turn']}", None, cross_site=False)
        status, transcript = answer.status, json.loads(answer.body)
        assert status == 200 and any(e.get("t") == "init" and e.get("session_id") == "stub-session" for e in transcript["events"])
        assert agent_turn_transcript(store, "N", turns[1]["turn"])["role"] == "numerics"
    finally:
        again.close()


def test_an_ask_turn_while_the_run_is_paused_gets_no_role_scope_or_pending_redirect(studio):
    """Seventh review §11: the researcher's Ask turn is not a role's turn — no role brief, no PROOF_AGENT_ROLE, no role
    permissions, and the redirect waiting for the role's next turn stays waiting."""
    store, hub, log, queue = studio
    _queue(queue,
           [["proof", "node", "progress", "N", "--handoff", "typesetter", "--note", "write it up"], ["sleep", "0.5"]],  # the Prover
           [["sleep", "0"]],  # the researcher's Ask turn
           [["sleep", "0"]],  # the Typesetter, after Resume
           [["proof", "node", "progress", "N", "--step", "1", "--status", "stuck", "--note", "enough"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover", "typesetter"]})
    time.sleep(0.1)
    _post(hub, "/studio/N/api/agent/pause")
    _wait(hub, until=("paused",))
    _post(hub, "/studio/N/api/agent/redirect", {"text": "use the sup norm", "role": "typesetter"})
    status, asked = _post(hub, "/studio/N/api/agent", {"prompt": "what is your plan?", "mode": "ask", "provider": "claude"})
    assert status == 200, asked
    agent = hub.studio("N").agent
    job = agent.jobs[asked["job"]]
    with job.cond:
        job.cond.wait_for(lambda: job.done, timeout=20)
    ask = _turns(log)[-1]
    assert ask["role"] is None and "This turn you are" not in ask["brief"] and "use the sup norm" not in ask["prompt"]
    assert "Edit(./key-ideas.md)" not in ask["argv"]  # not the Typesetter's scope
    _post(hub, "/studio/N/api/agent/resume")
    _wait(hub, until=("done", "stuck", "budget"))
    resumed = _turns(log)[2]
    assert resumed["role"] == "typesetter" and "use the sup norm" in resumed["prompt"]  # the redirect reached the role's turn


def test_a_start_is_refused_when_the_previous_run_is_still_giving_the_node_back(monkeypatch):
    import threading

    from proof_cli.studio import agent_run
    from proof_cli.studio.agent_run import AgentRun

    monkeypatch.setattr(agent_run, "SETTLE_WAIT", 0.3)
    gate = threading.Event()
    run = AgentRun(_fake_turns(lambda turn: None), _hooks(release=lambda name, reason: gate.wait(5)))
    run.start("claude", roles=["numerics"])
    deadline = time.monotonic() + 5
    while run.view()["status"] not in ("done", "stuck") and time.monotonic() < deadline:
        time.sleep(0.01)
    stopper = threading.Thread(target=run.release)
    stopper.start()
    time.sleep(0.1)
    refused = run.start("claude")
    gate.set()
    stopper.join(5)
    assert refused.get("error") == "RUN_SETTLING" and "still" in refused["message"]


def test_a_failed_release_is_not_reported_as_released(studio, monkeypatch):
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "5"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    time.sleep(0.3)
    run = hub.studio("N").run

    def fails(name, reason):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(run.hooks, "release", fails)
    status, answer = _post(hub, "/studio/N/api/agent/release")
    assert status == 500 and answer["error"] == "RELEASE_FAILED" and "database is locked" in answer["message"]
    state = _get(hub, "/studio/N/api/agent/run")[1]
    assert state["status"] == "release-failed" and "database is locked" in state["reason"]
    assert get_active_claim(store, "N") is not None  # and the claim it failed to give back is still there, as it says


def test_the_release_reason_says_why_the_node_was_given_back(studio):
    from proof_cli.storage import list_events

    store, hub, log, queue = studio
    _queue(queue, [["sleep", "5"]], [["sleep", "5"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    time.sleep(0.3)
    _post(hub, "/studio/N/api/agent/release")
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    time.sleep(0.3)
    hub.studio("N").close()
    reasons = [e.payload["reason"] for e in list_events(store) if e.kind == "proof_map_claim_released"]
    assert reasons == ["stopped and released by the researcher", "studio closed"]


def test_a_late_assignment_after_the_later_run_requested_review_leaves_no_claim():
    """Fifth review: a review request hands the node over and releases its claim, so a later Start that ended
    `done / review-requested` left nothing behind: what the stopped Start's late assignment made is its own to give back."""
    import threading

    from proof_cli.proof_map import claim_node, release_node
    from proof_cli.studio.agent_run import AgentRun

    store = ensure_project(Path(os.environ.get("TMPDIR", "/tmp")) / f"proof-late-review-{os.getpid()}-{time.time_ns()}")
    create_node(store, node_id="N", kind="claim", statement="a claim")
    entered, gate = threading.Event(), threading.Event()
    calls: list[str] = []
    log: list[dict] = []

    def assign(name):
        calls.append(name)
        if len(calls) == 1:
            entered.set()
            assert gate.wait(5)
        claim_node(store, "N", claimant_id=name)

    def release(name, reason=None):
        claim = get_active_claim(store, "N")
        if claim is not None and claim.claimant_id == name:
            release_node(store, "N", claimant_id=name, reason=reason)

    def requests_review(turn):  # the turn requests review: the node is handed over, and its claim with it
        release_node(store, "N", claimant_id="claude-code", reason="review requested")
        log.append({"kind": "review-requested"})

    run = AgentRun(_fake_turns(requests_review), _hooks(assign=assign, release=release, work_log=lambda: list(log)))
    first = threading.Thread(target=lambda: run.start("claude"))
    first.start()
    assert entered.wait(5)
    run.release()
    run.start("claude", roles=["prover"])
    deadline = time.monotonic() + 5
    while run.view()["status"] != "done" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (run.view()["status"], run.view()["reason"]) == ("done", "review-requested") and get_active_claim(store, "N") is None
    gate.set()
    first.join(5)
    assert get_active_claim(store, "N") is None  # the late assignment's claim was given back


# -- what the studio's centre reads and does (spec #145, part 4) ---------------------------------------


def test_the_studio_serves_the_work_log(studio):
    store, hub, log, queue = studio
    _queue(queue, [["proof", "node", "progress", "N", "--plan", "read", "--plan", "prove"], ["proof", "node", "progress", "N", "--step", "1", "--status", "started"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    _wait(hub)
    status, served = _get(hub, "/studio/N/api/agent/log")
    assert status == 200 and [e["kind"] for e in served["entries"]][:3] == ["claimed", "plan", "step"]


def test_review_what_it_has_is_recorded_under_the_researcher_and_ends_the_run(studio):
    """Seventh review: the researcher asked for the review, so it is recorded as the researcher — the page's git
    identity, as every page-initiated human action is — not as the agent that holds the node. The run's claim ends
    with it (the researcher unassigns the node in the same request), so the run ends as any review request ends it."""
    from proof_cli.proof_map import list_candidate_proofs
    from proof_cli.reviews import git_identity

    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    _queue(queue, [["write", "proof.tex", "\\documentclass{amsart}\\begin{document}half\\end{document}\n"], ["sleep", "2"]], [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude"})
    time.sleep(1.2)
    assert get_active_claim(store, "N").claimant_id == "claude-code"
    status, frozen = _post(hub, "/studio/N/api/agent/review-now")
    assert status == 200 and frozen["version"] == 1
    assert get_workflow_state(store, "N") == "review-needed"
    (proof,) = list_candidate_proofs(store, "N")
    assert proof.submitted_by == git_identity(store.root) != "claude-code"
    (requested,) = [e for e in work_log(store, "N") if e["kind"] == "review-requested"]
    assert requested["by"] == git_identity(store.root)
    state = _wait(hub)
    assert state["status"] == "done" and state["reason"] == "review-requested" and get_active_claim(store, "N") is None


def test_review_what_it_has_on_a_node_another_person_holds_is_recorded_under_the_researcher(studio):
    from proof_cli.proof_map import claim_node, list_candidate_proofs
    from proof_cli.reviews import git_identity

    store, hub, log, queue = studio
    write_key_ideas(store, "N")
    claim_node(store, "N", claimant_id="alice")
    status, frozen = _post(hub, "/studio/N/api/agent/review-now")
    assert status == 200 and frozen["version"] == 1
    (proof,) = list_candidate_proofs(store, "N")
    assert proof.submitted_by == git_identity(store.root) != "alice"
    assert get_active_claim(store, "N") is None  # handed over: the researcher unassigned it in the same request


def test_a_refused_review_what_it_has_leaves_the_holders_claim(studio):
    from proof_cli.proof_map import claim_node

    store, hub, log, queue = studio
    claim_node(store, "N", claimant_id="alice")
    status, refused = _post(hub, "/studio/N/api/agent/review-now")  # no key ideas: refused before anything changes
    assert status == 409 and refused["error"] == "KEY_IDEAS_REQUIRED"
    assert get_active_claim(store, "N").claimant_id == "alice"


def test_review_what_it_has_is_refused_when_nothing_can_be_frozen(studio):
    store, hub, log, queue = studio
    status, refused = _post(hub, "/studio/N/api/agent/review-now")  # no key ideas yet: the service refuses, and says so
    assert status == 409 and refused["error"] == "KEY_IDEAS_REQUIRED"


def test_every_starts_turns_stay_in_the_log_under_their_steps_after_a_new_start_and_a_restart(studio):
    """Seventh review (spec #145, story 40): each turn is in the work log with the step it belongs to, and its raw
    conversation is read from what the project kept — the turns of an earlier Start survive a new Start and a restart."""
    store, hub, log, queue = studio
    _queue(queue,
           [["proof", "node", "progress", "N", "--plan", "read", "--plan", "prove"], ["proof", "node", "progress", "N", "--step", "1", "--status", "done"]],
           [["proof", "node", "progress", "N", "--step", "2", "--status", "started"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})  # a second Start
    _wait(hub)
    hub.close()
    again = StudioHub(store)  # and a restart
    try:
        answer = again.request("GET", "/studio/N/api/agent/log", "", None, cross_site=False)
        turns = [e for e in json.loads(answer.body)["entries"] if e["kind"] == "turn"]
        assert [(t["role"], t["step"]) for t in turns] == [("prover", 1), ("prover", 2)]
        for turn in turns:
            kept = json.loads(again.request("GET", "/studio/N/api/agent/turn", f"turn={turn['turn']}", None, cross_site=False).body)
            assert "Take your turn as the Prover" in kept["prompt"] and any(e.get("t") == "done" for e in kept["events"])
    finally:
        again.close()


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


def _cli_commands() -> set[str]:
    """Every `proof` command the CLI really has, as `group … command`, walked from its command tree."""
    import typer

    from proof_cli.cli import app

    def leaves(command, path=()):
        if hasattr(command, "commands"):
            for name, sub in command.commands.items():
                yield from leaves(sub, (*path, name))
        else:
            yield " ".join(path)

    return set(leaves(typer.main.get_command(app)))


def _proof_rule_command(rule: str) -> str:
    """`Bash(proof node split *)` → `node split`."""
    assert rule.startswith("Bash(proof ") and rule.endswith(" *)"), rule
    return rule[len("Bash(proof "):-len(" *)")]


def test_the_prover_may_open_a_challenge(studio):
    """Seventh review: the rule names the CLI's real command (ADR-0006: `proof challenge open`), not one that
    does not exist — a permission for a command the CLI lacks lets the agent do nothing."""
    store, hub, log, queue = studio
    _queue(queue, [["sleep", "0"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    argv = _turns(log)[0]["argv"]
    challenge = [rule for rule in argv if rule.startswith("Bash(proof") and "challenge" in rule]
    assert challenge == ["Bash(proof challenge open *)"]
    assert _proof_rule_command(challenge[0]) in _cli_commands()


def test_only_opening_a_challenge_is_agent_reachable_and_the_prover_is_told_so():
    """The researcher confirmed (PR #149): the Prover may open a Challenge (ADR-0005, ADR-0011); dismissing or
    resolving one stays human-only, so no role may reach any other challenge command, nor `proof` at large."""
    from proof_cli.studio.proof_agent import ROLES, ProofAgentContext

    challenge_commands = {c for c in _cli_commands() if c.startswith("challenge ")}
    assert "challenge dismiss" in challenge_commands  # the human-only path the roles must not reach
    for role in ROLES.values():
        rules = [*role.proof, *role.commands]
        assert "Bash(proof *)" not in rules and "Bash(proof challenge *)" not in rules, role.name
        reached = {_proof_rule_command(r) for r in role.proof if r.startswith("Bash(proof challenge")}
        assert reached == ({"challenge open"} if role.name == "prover" else set()), role.name
    brief = ProofAgentContext("N", Path("/p"), role="prover", name="claude-code").brief()
    assert "proof challenge open" in brief and "Dismissing or resolving a\nChallenge is the researcher's alone" in brief


def test_every_roles_proof_rules_name_real_commands():
    from proof_cli.studio.proof_agent import ROLES

    known = _cli_commands()
    for role in ROLES.values():
        for rule in role.proof:
            assert _proof_rule_command(rule) in known, (role.name, rule)


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


def test_the_log_gives_each_changed_file_its_line_and_how_the_page_opens_it(studio):
    """Seventh review (spec #145, stories 18–19): a file a turn changed is listed with the first line it changed, and
    the log says how the page opens it — the vscode:// scheme, or the project's `[studio] open_command` when set."""
    store, hub, log, queue = studio
    folder = store.root / "proofs" / "N"
    (folder / "scratch").mkdir(exist_ok=True)
    (folder / "scratch" / "draft.md").write_text("one\ntwo\nthree\nfour\nfive\nsix\n")
    _queue(queue, [["write", "scratch/draft.md", "one\ntwo\nthree\nFOUR\nfive\nsix\n"], ["write", "scratch/new.md", "fresh\n"]])
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    served = _get(hub, "/studio/N/api/agent/log")[1]
    (turn,) = [e for e in served["entries"] if e["kind"] == "turn"]
    assert {c["path"]: c["line"] for c in turn["changed"]} == {"scratch/draft.md": 4, "scratch/new.md": 1}
    assert served["open"] == {"kind": "scheme", "url": f"vscode://file/{folder}"}
    (store.root / "proof.toml").write_text('[studio]\nopen_command = "subl {file}"\n')
    assert _get(hub, "/studio/N/api/agent/log")[1]["open"] == {"kind": "command", "command": "subl {file}"}


# -- ADR-0013: a key-ideas summary an agent turn wrote is recorded as the agent's draft ------------------


def _typeset_key_ideas(hub, queue, text):
    """The "+" menu's Typesetter · draft key ideas: one Typesetter turn of the run, which writes key-ideas.md."""
    _queue(queue, [["write", "key-ideas.md", text]])
    status, _ = _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["typesetter"],
                                                         "redirect": "Write key-ideas.md from the draft and proof.tex: 核心思路, 主要步骤, 难点, 未覆盖."})
    assert status == 200
    _wait(hub)
    _post(hub, "/studio/N/api/agent/release")  # the one turn is over: the node is the author's to submit


def _draft_events(store):
    from proof_cli.storage import list_events

    return [e for e in list_events(store) if e.kind == "proof_map_key_ideas_drafted"]


def test_a_summary_the_typesetter_drafted_and_the_author_left_as_it_is_reads_as_the_agents_confirmed(studio):
    from _proofs import KEY_IDEAS

    from proof_cli import key_ideas
    from proof_cli.proof_map import request_review

    store, hub, log, queue = studio
    _typeset_key_ideas(hub, queue, KEY_IDEAS)
    (drafted,) = _draft_events(store)  # the agent's name and the digest of what it left
    assert drafted.payload == {"drafted_by": "claude-code", "sha256": key_ideas.digest(KEY_IDEAS.encode())}
    record = request_review(store, "N", requested_by="author", rationale="scoped")
    assert record.key_ideas_drafted_by == key_ideas.AGENT_CONFIRMED == "agent (confirmed by author at request-review)"


def test_a_summary_the_typesetter_drafted_and_the_author_edited_reads_as_edited(studio):
    from _proofs import KEY_IDEAS

    from proof_cli import key_ideas
    from proof_cli.proof_map import request_review

    store, hub, log, queue = studio
    _typeset_key_ideas(hub, queue, KEY_IDEAS)
    write_key_ideas(store, "N", KEY_IDEAS.replace("compactness", "compactness and continuity"))  # the author's edit
    record = request_review(store, "N", requested_by="author", rationale="scoped")
    assert record.key_ideas_drafted_by == key_ideas.AGENT_EDITED == "agent draft, edited by author"


def test_a_summary_no_agent_turn_touched_reads_as_the_authors(studio):
    from proof_cli import key_ideas
    from proof_cli.proof_map import request_review

    store, hub, log, queue = studio
    write_key_ideas(store, "N")  # the author's own
    _queue(queue, [["write", "scratch/draft.md", "a draft\n"]])  # an agent turn that leaves key-ideas.md alone
    _post(hub, "/studio/N/api/agent/start", {"provider": "claude", "roles": ["prover"]})
    _wait(hub)
    _post(hub, "/studio/N/api/agent/release")
    assert _draft_events(store) == []
    record = request_review(store, "N", requested_by="author", rationale="scoped")
    assert record.key_ideas_drafted_by == key_ideas.AUTHOR == "author"
