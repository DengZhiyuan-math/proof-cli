"""Serve two isolated audit fixtures on the six-commit candidate."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid

out = Path(__file__).resolve().parent
candidate = json.loads((out / "local-candidate.json").read_text())
repos = {k: Path(v["checkout"]) for k, v in candidate["repositories"].items()}
sources = [repos["core"] / "src", repos["core"] / "packages/latex-agent/src", repos["agents"] / "src", repos["web"] / "src"]
os.environ["PYTHONPATH"] = os.pathsep.join(map(str, sources))
for path in [*sources, repos["web"] / "tests"]:
    sys.path.insert(0, str(path))
empty = out / "empty-claude-profile"
empty.mkdir(exist_ok=True)
os.environ["CLAUDE_CONFIG_DIR"] = str(empty)
os.environ["PRISM_AGENTS"] = str(out / "agents.json")
(out / "agents.json").write_text('{"default":"claude","providers":{"claude":{"default_model":"opus"}}}\n')

from latex_agent.backends import Job
from proof_cli.definitions import add_definition, edit_definition
from proof_cli.proof_map import create_node, record_agent_turn, work_log, list_nodes
from proof_cli.storage import ensure_project
from proof_web.server import ReviewServer
from _proofs import submit_proof

auth = subprocess.run(["/opt/homebrew/bin/claude", "auth", "status"], env=os.environ, text=True, capture_output=True)
(out / "empty-profile-auth.json").write_text(json.dumps({"exit": auth.returncode, "stdout": auth.stdout, "stderr": auth.stderr}, indent=2))
assert json.loads(auth.stdout)["loggedIn"] is False, "empty profile must be logged out"
emit = Job.emit


def observed(job, event):
    with (out / "logged-out-reader-events.jsonl").open("a") as log:
        log.write(json.dumps({"role": getattr(job.context, "role", "reader"), "event": event}, ensure_ascii=False) + "\n")
    return emit(job, event)


Job.emit = observed
servers = []
for name in ("definition", "reader"):
    root = out / "projects" / name
    store = ensure_project(root, project_id="t8-audit-" + name)
    (root / "library").mkdir(exist_ok=True)
    (root / "library/main.tex").write_text('\\begin{theorem}Audit fixture T holds.\\end{theorem}\n')
    (root / "proof.toml").write_text('[studio]\nlibrary=["library"]\nparallel=1\nbudget_turns=1\nbudget_minutes=5\nclaude_config_dir="ignored"\nbudget_turn=4\n[studio.budget]\nminute=5\n')
    if name == "definition" and not list_nodes(store):
        add_definition(store, "D", term="Positive parameter", text="$n \\ge 1$", created_by="reader-1")
        create_node(store, node_id="C", kind="claim", statement="C holds for n.", definitions=["D"], created_by="reader-1")
        create_node(store, node_id="L", kind="lemma", statement="L follows from C.", dependencies=["C"], created_by="reader-1")
        for node in ("C", "L"):
            submit_proof(store, node, claimant_id="prover-fixture", scoping_rationale="isolated audit fixture", content="Fixture proof; no mathematical acceptance.")
        turn = uuid.uuid4().hex
        record_agent_turn(store, "C", phase="started", turn=turn, role="decomposer", by="reader-1")
        edit_definition(store, "D", text="$n \\ge 2$", edited_by="reader-1", reason="n = 1 is degenerate")
        record_agent_turn(store, "C", phase="ended", turn=turn, role="decomposer", by="reader-1")
        (out / "definition-work-log.json").write_text(json.dumps(work_log(store, "C"), indent=2))
    server = ReviewServer(store)
    servers.append(server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
info = {"pid": os.getpid(), "sources": list(map(str, sources)), "urls": {"definition": servers[0].url, "reader": servers[1].url}, "emptyProfile": str(empty)}
(out / "browser-servers.json").write_text(json.dumps(info, indent=2) + "\n")
print(json.dumps(info), flush=True)
stop = threading.Event()
signal.signal(signal.SIGINT, lambda *args: stop.set())
signal.signal(signal.SIGTERM, lambda *args: stop.set())
stop.wait()
for server in servers:
    server.shutdown()
    server.server_close()
