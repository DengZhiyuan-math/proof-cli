"""Independent ADR-0021 spec probes against the archived audit heads."""

import sys
from pathlib import Path

AUDIT = Path(__file__).parent
for relative in ("core/src", "agents/src", "web/src", "core/packages/latex-agent/src", "core/tests", "agents/tests", "web/tests"):
    sys.path.insert(0, str(AUDIT / relative))

from proof_agents.agent_run import AgentRun
from test_prove_verify_loop import _ScriptedAgent, _hooks, _until
from test_coordinator import World, FakeRun
from proof_cli.proof_map import create_node, record_evidence_check, record_progress
from proof_cli.storage import ensure_project
from _proofs import submit_proof
from _review_client import DirectClient


def test_pursued_split_preserves_a_real_human_only_blocker():
    log, questions = [], []
    agent = _ScriptedAgent(log, [{"entries": [
        {"kind": "split", "nodes": ["T1"]},
        {"kind": "step", "step": 1, "status": "needs-human", "note": "Contradiction in T: x > 0 and x <= 0; the researcher must correct the statement"},
    ]}])
    run = AgentRun(agent, _hooks(
        work_log=lambda: log,
        record_question=lambda *args: questions.append(args),
        node_brief=lambda: {"kind": "theorem", "statement": "T", "dependencies": [], "split_children": []},
    ))
    run.start("claude", roles=["decomposer"], pursue=True)
    _until(lambda: not run.active(), "run finished")
    assert run.view()["status"] == "needs-human", {"view": run.view(), "questions": questions}


def test_reference_review_surfaces_the_dependents_unchecked_source_warning(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="R", kind="imported_result", statement="Bound", source_locator="arXiv:example, Thm 1", source_version="v1", created_by="reader")
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader")
    warning = "R: unchecked against the source; the cited work cannot be reached"
    record_progress(store, "L", role="verifier", by="a", verdict="passed", note=warning)
    proof = submit_proof(store, "L", claimant_id="a", scoping_rationale="scoped", content="Proof invoking R")
    record_evidence_check(store, proof.id, "passed", run_by="a/verifier", notes=warning)
    client = DirectClient(store)
    try:
        source = client.get("/api/node/R")[1]["data"]
        card = next(p for p in client.get("/api/state")[1]["data"]["pending"] if p["node_id"] == "R")
        assert warning in str(source) or warning in str(card), {"source_evidence": source["evidence_checks"], "source_dependents": source["dependents"], "card": card}
    finally:
        client.app.close()


def test_global_budget_boundary_still_records_exhausted_nodes_as_parked():
    world = World(edges={"T": []}, budget=(1, 60.0), parallel=1)
    coordinator = world.coordinator()
    coordinator.start("claude")
    try:
        _until(lambda: world.runs["T"].starts == 1, "Decomposer started")
        world.edges = {"T": ["A"], "A": []}
        world.runs["A"] = FakeRun()
        world.runs["T"].end("done", turns=1, reason="split into 1 Claim(s): A; the Coordinator works them")
        world.runs["T"].claim = None
        _until(lambda: world.runs["A"].starts == 1, "Claim started")
        world.runs["A"].end("budget", turns=1, reason="out of turns")
        _until(lambda: not coordinator.active(), "Coordinator finished")
        assert any(entry["node"] == "A" for entry in coordinator.view()["parked"]), coordinator.view()
        assert any(node == "A" for node, reason in world.parked)
    finally:
        coordinator.release()
