"""Memory as the channel between nodes (ADR-0019 part C, phase 2): a run's role records what it learned on its own
node, tagged with the agent and role that learned it (`--source <agent>/<role>`, point 8), and another node's
briefing retrieves memory elsewhere in the map by its statement (`retrieve_memory`, point 14), after what its
dependencies, dependents and siblings hold. Nothing retrieved is a fact: the briefing marks it unverified."""

import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.memory import list_memory_artifacts, record_memory
from proof_cli.proof_map import create_node
from proof_cli.retrieval import retrieve_candidates, retrieve_memory
from proof_cli.storage import ensure_project

runner = CliRunner()


def _project(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="lemma", statement="the partial sums are bounded")
    create_node(store, node_id="B", kind="claim", statement="the tail is summable", dependencies=["A"])
    create_node(store, node_id="C", kind="claim", statement="the constant is at most two")
    return store


def test_a_runs_role_records_what_it_learned_under_its_agent_and_role(tmp_path: Path):
    store = _project(tmp_path)
    done = runner.invoke(app, ["memory", "add", "induction on n dead-ends at the base case", "--node-id", "A", "--layer", "episodic",
                              "--status", "failed", "--source", "claude-code/prover", "--json", "--root", str(tmp_path)])
    assert done.exit_code == 0, done.output
    (entry,) = list_memory_artifacts(store, node_id="A")
    assert (entry.source, entry.status.value, entry.layer.value) == ("claude-code/prover", "failed", "episodic")
    assert json.loads(done.output)["data"]["source"] == "claude-code/prover"


def test_memory_is_retrieved_by_the_statements_words_best_first_newest_among_equals(tmp_path: Path):
    store = _project(tmp_path)
    record_memory(store, "episodic", "bounding the partial sums by the integral test fails: the terms are not monotone", node_id="A", status="failed", source="codex/prover")
    record_memory(store, "procedural", "the partial sums are bounded once the tail is summable", node_id="B", status="tactic", source="codex/prover")
    record_memory(store, "semantic", "a note about something else entirely", node_id="C", status="tentative")
    record_memory(store, "semantic", "settled: the sums are bounded", node_id="C", status="stable")
    hits = retrieve_memory(store, "the partial sums are bounded")
    assert [(h.node_id, h.status) for h in hits] == [("B", "tactic"), ("C", "stable"), ("A", "failed")]  # by how many words match
    assert all("something else" not in h.content for h in hits)  # no overlap, no hit
    assert hits[0].matched == ["are", "bounded", "partial", "sums", "the"] and hits[0].source == "codex/prover"
    assert retrieve_memory(store, "") == [] and retrieve_memory(store, "   ") == []


def test_retrieval_can_keep_to_the_learned_statuses_and_leave_out_the_nodes_a_briefing_already_covers(tmp_path: Path):
    store = _project(tmp_path)
    record_memory(store, "episodic", "the sums diverge for n = 1", node_id="A", status="failed")
    record_memory(store, "procedural", "the sums telescope", node_id="B", status="tactic")
    record_memory(store, "semantic", "the sums are settled", node_id="C", status="stable")
    learned = retrieve_memory(store, "the sums", statuses=("failed", "tactic", "tentative"))
    assert sorted(h.node_id for h in learned) == ["A", "B"]  # a settled fact is not a note to pass on as unverified
    elsewhere = retrieve_memory(store, "the sums", exclude_node_ids=["A", "B"])
    assert [h.node_id for h in elsewhere] == ["C"]
    assert len(retrieve_memory(store, "the sums", limit=1)) == 1


def test_proof_retrieve_carries_the_matching_memory_beside_its_candidates(tmp_path: Path):
    store = _project(tmp_path)
    record_memory(store, "episodic", "the partial sums blow up without the tail bound", node_id="A", status="failed", source="codex/verifier")
    report = retrieve_candidates(store, query="partial sums")
    assert [(h.node_id, h.source) for h in report.memory] == [("A", "codex/verifier")]
    done = runner.invoke(app, ["retrieve", "partial sums", "--json", "--root", str(tmp_path)])
    assert done.exit_code == 0, done.output
    payload = json.loads(done.output)
    data = payload.get("data", payload)
    assert data["memory"][0]["content"] == "the partial sums blow up without the tail bound"


def test_memory_add_names_the_node_once_so_a_permission_on_one_node_admits_no_other(tmp_path: Path):
    """Audit P1: `proof memory add --node-id N … --node-id Other` matched a rule that admits N's memory and wrote Other's
    (Typer keeps the last value). A second --node-id, or an empty one, is refused and writes nothing."""
    store = _project(tmp_path)
    twice = runner.invoke(app, ["memory", "add", "--node-id", "A", "--layer", "episodic", "--status", "failed", "--node-id", "C", "a note", "--json", "--root", str(tmp_path)])
    assert twice.exit_code == 1 and json.loads(twice.output)["error"]["code"] == "INVALID_INPUT", twice.output
    empty = runner.invoke(app, ["memory", "add", "--node-id", "A", "--node-id", "", "a note", "--root", str(tmp_path)])
    assert empty.exit_code == 1 and "INVALID_INPUT" in empty.output
    blank = runner.invoke(app, ["memory", "add", "--node-id", " ", "a note", "--root", str(tmp_path)])
    assert blank.exit_code == 1
    assert list_memory_artifacts(store) == []
    once = runner.invoke(app, ["memory", "add", "--node-id", "A", "--layer", "episodic", "--status", "failed", "--source", "codex/prover", "a note", "--root", str(tmp_path)])
    assert once.exit_code == 0, once.output
    (entry,) = list_memory_artifacts(store)
    assert entry.scope.node_id == "A"
    unscoped = runner.invoke(app, ["memory", "add", "the researcher's own project-wide note", "--root", str(tmp_path)])  # no --node-id at all: as before
    assert unscoped.exit_code == 0, unscoped.output
