import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from proof_cli.proof_map import create_node, list_nodes, remove_dependency, split_node
from proof_cli.storage import ensure_project
from proof_agents.coordinator import ProjectPursuit, PursuitHooks

root = Path(tempfile.mkdtemp(prefix="nested-abandoned-", dir="/private/tmp"))
store = ensure_project(root)
create_node(store, node_id="T", kind="theorem", statement="Main", created_by="reader")
split_node(store, "T", [{"id": "C1", "statement": "Old route"}, {"id": "C2", "statement": "Replacement"}], created_by="reader")
split_node(store, "C1", [{"id": "D1", "statement": "Old first step"}, {"id": "D2", "statement": "Old second step"}], created_by="reader")
remove_dependency(store, "T", "C1", edited_by="reader")
starts = []
done = SimpleNamespace(start=lambda provider, **kw: starts.append("T") or {}, active=lambda: False,
                       view=lambda: {"status": "done", "turns": 0})
nodes = lambda: [{"id": n.id, "kind": n.kind.value, "dependencies": n.dependencies,
                  "derived_from": n.derived_from, "by_agent": True} for n in list_nodes(store)]
pursuit = ProjectPursuit(PursuitHooks(read=lambda provider: {}, theorems=lambda: ["T"],
                                    coordinator=lambda node: done, nodes=nodes))
results = []
for _ in range(2):
    pursuit.start("offline", limits={"turns": 4, "minutes": 1})
    deadline = time.monotonic() + 5
    while pursuit.active():
        assert time.monotonic() < deadline
        time.sleep(.01)
    results.append(pursuit.view())
print(json.dumps({"map": nodes(), "runs": results, "coordinator_starts": starts}, indent=2))
