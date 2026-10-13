"""Serve exact production sources with a deterministic backend for browser acceptance.

No model calls. Reader uses the normal AgentManager path. Coordinator is reused
from the submitted test fixture. State is persisted through core's normal APIs.
"""
import argparse
import json
import os
from pathlib import Path

from latex_agent import agent
from latex_agent.backends import Backend
from proof_cli.proof_map import ProofMapError, create_node, list_nodes
from proof_cli.storage import ensure_project
from proof_web import studios
from proof_web.server import ReviewServer
from test_pursuit_history import _Coordinator

parser = argparse.ArgumentParser()
parser.add_argument("scenario", choices=("ending", "reader-error", "release-retry", "release-interrupted", "shutdown-released", "record-error", "start-record-error"))
parser.add_argument("root", type=Path)
args = parser.parse_args()
store = ensure_project(args.root, project_id=f"browser10-{args.scenario}")
(args.root / "library").mkdir(exist_ok=True)
draft = args.root / "library" / "main.tex"
if not draft.exists():
    draft.write_text("\\begin{theorem}T1 holds.\\end{theorem}\n")
config = args.root / "proof.toml"
if not config.exists():
    config.write_text('[studio]\nlibrary = ["library"]\n')


class BrowserBackend(Backend):
    def run(self, job):
        job.emit({"t": "text", "text": "Deterministic browser acceptance fixture; no model call."})
        if args.scenario == "reader-error":
            return {"exit": 1, "is_error": True, "stderr": "browser fixture: Reader failed to read the draft"}
        if args.scenario.startswith("release-") or args.scenario == "shutdown-released":
            if not list_nodes(store):
                create_node(store, node_id="T1", kind="theorem", statement="T1 holds", created_by="reader-fixture")
        return {"exit": 0}


backend = BrowserBackend("browser10-fixture")
agent.load_backends = lambda: ({backend.id: backend}, backend.id, None)
if args.scenario in ("record-error", "start-record-error"):
    original_record = studios.record_pursuit

    def fixture_record(store, phase, **kwargs):
        if args.scenario == "start-record-error" or phase != "start":
            raise ProofMapError("PURSUIT_RECORD_FAILED", "browser fixture: disk full")
        return original_record(store, phase, **kwargs)

    studios.record_pursuit = fixture_record

server = ReviewServer(store)
if args.scenario.startswith("release-") or args.scenario == "shutdown-released":
    class BrowserCoordinator(_Coordinator):
        def view(self):
            # The map reads running; the DirectClient fixture does not need it.
            return {**super().view(), "running": []}

    fails = 1 if args.scenario == "release-retry" else 100 if args.scenario == "release-interrupted" else 0
    coordinator = BrowserCoordinator("running", fails=fails)
    server.app.studios._coordinators["T1"] = coordinator
    server.app.studios.coordinator = lambda theorem: coordinator

print(json.dumps({"pid": os.getpid(), "url": server.url, "scenario": args.scenario, "root": str(args.root)}), flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
