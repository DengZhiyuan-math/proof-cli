"""Serve the unchanged web commit with a deterministic backend. No model calls."""

import argparse
import json
import os
from pathlib import Path
import time

from latex_agent import agent
from latex_agent.backends import Backend
from proof_cli.proof_map import create_node, record_progress, split_node
from proof_cli.storage import ensure_project
from proof_web.server import ReviewServer


parser = argparse.ArgumentParser()
parser.add_argument("scenario", choices=("project", "subtree", "launch-failed"))
parser.add_argument("root", type=Path)
args = parser.parse_args()
store = ensure_project(args.root, project_id=f"browser18-{args.scenario}")
(args.root / "library").mkdir(exist_ok=True)
(args.root / "library/main.tex").write_text("\\begin{theorem}T holds.\\end{theorem}\n")
(args.root / "proof.toml").write_text(
    '[studio]\nlibrary = ["library"]\nparallel = 1\nagent_name = "browser18-fixture"\n'
    '[studio.budget]\nturns = 2\nminutes = 4\n'
)
if args.scenario != "project":
    create_node(store, node_id="T", kind="theorem", statement="T holds", created_by="fixture")
if args.scenario == "launch-failed":
    split_node(store, "T", [{"id": "A", "statement": "A holds"}], created_by="fixture")


class BrowserBackend(Backend):
    def preflight(self, root):
        if args.scenario == "launch-failed":
            with (args.root / "preflights.jsonl").open("a") as output:
                output.write(json.dumps({"root": str(root), "time": time.time()}) + "\n")
            return "browser fixture: launch refused before any turn"
        return None

    def run(self, job):
        with (args.root / "backend-turns.jsonl").open("a") as output:
            output.write(json.dumps({"role": getattr(job.context, "role", "reader"), "node": getattr(job.context, "node_id", None)}) + "\n")
        job.emit({"t": "text", "text": "Deterministic browser fixture; no model call."})
        job.cancel.wait(1.5)
        if job.cancel.is_set():
            return {"exit": 0}
        if args.scenario == "subtree":
            context = job.context
            if context.role == "decomposer":
                split_node(store, context.node_id, [{"id": "A", "statement": "A holds"}], created_by=context.name)
            else:
                record_progress(store, context.node_id, role=context.role, by=context.name, step=1,
                                status="stuck", note="browser fixture: no proof found")
        return {"exit": 0}


backend = BrowserBackend("browser18-fixture")
agent.load_backends = lambda: ({backend.id: backend}, backend.id, None)
server = ReviewServer(store)
print(json.dumps({"pid": os.getpid(), "url": server.url, "scenario": args.scenario, "root": str(args.root)}), flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
