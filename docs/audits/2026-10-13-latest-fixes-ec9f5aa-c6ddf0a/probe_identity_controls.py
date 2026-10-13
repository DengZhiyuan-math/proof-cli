import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path[:0] = [str(ROOT / "core/tests")]
from _researcher import researcher
from proof_agents.proof_agent import ProofAgentContext, agent_name
from proof_agents.reader import ReaderContext
from proof_cli.cli import app
from proof_cli.proof_map import create_node, get_node, get_reference_review_state
from proof_cli.reviews import git_identity
from proof_cli.storage import ensure_project
from typer.testing import CliRunner

run = Path(tempfile.mkdtemp(prefix="identity-controls-", dir=ROOT))
answers = []
for mode in ("normal", "human", "git-identity"):
    root = run / mode
    store = ensure_project(root)
    alias = {"normal": "reader", "human": "human", "git-identity": git_identity(root)}[mode]
    (root / "proof.toml").write_text("[studio]\nagent_name = " + json.dumps(alias) + "\n")
    create_node(store, node_id="T", kind="theorem", statement="Main")
    result = CliRunner().invoke(app, ["node", "create", "orphan", "lemma", "Agent work", "--root", str(root), "--json"],
                                env=ReaderContext(root, name=agent_name(root, "claude")).env())
    data = json.loads(result.output)
    assert result.exit_code == (0 if mode == "normal" else 1), data
    if mode != "normal":
        assert data["error"]["code"] == "AGENT_AUTHOR_REFUSED"
        assert get_node(store, "orphan") is None
    answers.append({"case": mode, "exit": result.exit_code, "response": data})

root = run / "trust"
store = ensure_project(root)
(root / "proof.toml").write_text('[studio]\nagent_name = "human"\n')
create_node(store, node_id="T", kind="theorem", statement="Main")
researcher(store).declare_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}],
                                   rationale="synthetic offline fixture")
env = ProofAgentContext("T", root, role="prover", name=agent_name(root, "claude")).env()
args = [["reference", "import", "r", "Fixture", "2020", "--source-type", "textbook"],
        ["node", "create", "I", "imported_result", "Source statement", "--parent", "T", "--source-locator", "Theorem 1", "--source-version", "v1"]]
for argv in args:
    result = CliRunner().invoke(app, argv + ["--root", str(root), "--json"], env=env)
    data = json.loads(result.output)
    assert result.exit_code == 1 and data["error"]["code"] == "AGENT_AUTHOR_REFUSED", data
    answers.append({"case": "trust-reserved-name", "command": argv[:2], "exit": result.exit_code, "response": data})
assert get_node(store, "I") is None
print(json.dumps({"new_real_provider_calls": 0, "cases": answers}, ensure_ascii=False, indent=2))
