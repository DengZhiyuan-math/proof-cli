"""Zero-provider probe: progress events still accept researcher attribution in an agent runtime."""
import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

import proof_cli.cli
from proof_cli.cli import app
from proof_cli.proof_map import create_node, work_log
from proof_cli.storage import ensure_project


project = Path(tempfile.mkdtemp(prefix="progress-attribution-project-", dir=Path(__file__).parent))
store = ensure_project(project)
create_node(store, node_id="T", kind="theorem", statement="Main", created_by="human")
records = []
cases = [
    ("explicit-human-with-role-and-name", {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NAME": "worker", "PROOF_AGENT_NODE": "T"}, ["--by", "human"]),
    ("role-only-defaults-to-human", {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NAME": "", "PROOF_AGENT_NODE": "T"}, []),
]
for label, environment, by in cases:
    argv = ["node", "progress", "T", "--plan", label, *by, "--root", str(project), "--json"]
    result = CliRunner().invoke(app, argv, env=environment)
    records.append({"case": label, "environment": environment, "argv": argv, "exit": result.exit_code,
                    "output": result.output, "parsed_output": json.loads(result.output)})

print(json.dumps({"module": proof_cli.cli.__file__, "project": str(project), "provider_calls": 0,
                  "cases": records, "recorded_work_log": work_log(store, "T")}, indent=2))
