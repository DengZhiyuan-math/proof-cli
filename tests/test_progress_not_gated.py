"""ADR-0021 part A: trust holds back decisions, not work.

Blocked refuses a Review decision, never a claim; a Provisional node — an
unaccepted one whose current snapshot the Verifier passed, or an imported
result not yet Reference-reviewed — puts what rests on it on the frontier; and
what rests on a Provisional node is Conditional until the researcher Accepts
bottom-up.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher

from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    conditional_on,
    create_node,
    get_frontier,
    get_integrity_state,
    get_workflow_state,
    is_provisional,
    record_evidence_check,
)
from proof_cli.storage import ensure_project


def _passed_by_verifier(store, node_id: str, run_by: str = "prover-1/verifier"):
    """The run's record of a passing verdict on the snapshot it gated (ADR-0019 point 4)."""
    proof = submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"proof of {node_id}")
    return record_evidence_check(store, proof.id, "passed", run_by=run_by, notes="no objections")


def _parent_on_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C")
    create_node(store, node_id="lem", kind="lemma", statement="L", dependencies=["clm"])
    return store


def _frontier(store) -> set[str]:
    return {node.id for node in get_frontier(store)}


def test_a_blocked_node_can_be_claimed_worked_and_requested_for_review(tmp_path: Path):
    store = _parent_on_claim(tmp_path)

    claim_node(store, "lem", claimant_id="agent_a")
    submit_proof(store, "lem", claimant_id="agent_a", scoping_rationale="scoped", content="proof")

    # its snapshot waits; the workflow axis still reads Blocked
    assert get_workflow_state(store, "lem") == "blocked"


def test_a_blocked_node_s_acceptance_decision_is_refused(tmp_path: Path):
    store = _parent_on_claim(tmp_path)
    submit_proof(store, "lem", claimant_id="agent_a", scoping_rationale="scoped", content="proof")

    for decision in ("accept", "revision-requested", "reject"):
        with pytest.raises(ProofMapError) as exc_info:
            researcher(store).decide_acceptance("lem", decision)
        assert exc_info.value.code == "NODE_BLOCKED"
        assert exc_info.value.details["unsettled"] == ["clm"]


def test_a_claim_the_verifier_passed_is_provisional_and_puts_its_parent_on_the_frontier(tmp_path: Path):
    store = _parent_on_claim(tmp_path)
    assert _frontier(store) == {"clm"}

    _passed_by_verifier(store, "clm")

    assert is_provisional(store, "clm")
    assert _frontier(store) == {"lem"}
    assert conditional_on(store, "lem") == frozenset({"clm"})
    assert conditional_on(store, "clm") == frozenset()


def test_a_snapshot_without_the_verifier_s_pass_is_not_provisional(tmp_path: Path):
    store = _parent_on_claim(tmp_path)
    proof = submit_proof(store, "clm", claimant_id="agent", scoping_rationale="scoped", content="proof")
    record_evidence_check(store, proof.id, "passed", run_by="numerics-1")  # a computation, not a reading
    record_evidence_check(store, proof.id, "failed", run_by="prover-1/verifier", notes="1. step 2")

    assert not is_provisional(store, "clm")
    assert "lem" not in _frontier(store)


def test_a_verifier_check_the_researcher_found_unusable_does_not_make_provisional(tmp_path: Path):
    store = _parent_on_claim(tmp_path)
    check = _passed_by_verifier(store, "clm")

    researcher(store).decide_evidence_review(check.id, "unusable")

    assert not is_provisional(store, "clm")


def test_accepting_bottom_up_clears_conditional_and_makes_the_parent_s_decision_possible(tmp_path: Path):
    store = _parent_on_claim(tmp_path)
    _passed_by_verifier(store, "clm")
    claim_node(store, "lem", claimant_id="agent_b")
    submit_proof(store, "lem", claimant_id="agent_b", scoping_rationale="scoped", content="proof of lem")

    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).decide_acceptance("lem", "accept")
    assert exc_info.value.code == "NODE_BLOCKED"

    researcher(store).decide_acceptance("clm", "accept")

    assert not is_provisional(store, "clm")
    assert conditional_on(store, "lem") == frozenset()
    assert get_workflow_state(store, "lem") == "review-needed"
    researcher(store).decide_acceptance("lem", "accept")


def test_conditional_runs_through_the_unaccepted_nodes_between(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="leaf", kind="claim", statement="A")
    create_node(store, node_id="mid", kind="claim", statement="B", dependencies=["leaf"])
    create_node(store, node_id="top", kind="theorem", statement="T", dependencies=["mid"])
    _passed_by_verifier(store, "leaf")
    _passed_by_verifier(store, "mid")

    assert conditional_on(store, "top") == frozenset({"leaf", "mid"})
    assert conditional_on(store, "mid") == frozenset({"leaf"})


def test_an_unreviewed_imported_result_is_provisional(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="ref", kind="imported_result", statement="Known", source_locator="doi:x", source_version="v1")
    create_node(store, node_id="lem", kind="lemma", statement="L", dependencies=["ref"])

    assert is_provisional(store, "ref")
    assert _frontier(store) == {"lem"}
    assert conditional_on(store, "lem") == frozenset({"ref"})

    researcher(store).decide_reference_review("ref")

    assert not is_provisional(store, "ref")
    assert conditional_on(store, "lem") == frozenset()


@pytest.mark.parametrize("decision", ["revision-requested", "reject"])
def test_sending_back_a_provisional_node_makes_the_snapshots_resting_on_it_potentially_stale(tmp_path: Path, decision):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C")
    create_node(store, node_id="mid", kind="claim", statement="M", dependencies=["clm"])
    create_node(store, node_id="lem", kind="lemma", statement="L", dependencies=["mid"])
    _passed_by_verifier(store, "clm")
    _passed_by_verifier(store, "mid")
    submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof of lem")
    assert get_integrity_state(store, "lem") == "current"

    researcher(store).decide_acceptance("clm", decision)

    assert not is_provisional(store, "clm")
    assert get_integrity_state(store, "mid") == "potentially-stale"
    assert get_integrity_state(store, "lem") == "potentially-stale"
    # what rests on a withdrawn support is no support for anything else
    assert not is_provisional(store, "mid")


def test_node_show_and_the_frontier_name_what_is_provisional_and_what_rests_on_it(tmp_path: Path):
    import json

    from typer.testing import CliRunner

    from proof_cli.cli import app

    store = _parent_on_claim(tmp_path)
    _passed_by_verifier(store, "clm")
    runner = CliRunner()

    shown = json.loads(runner.invoke(app, ["node", "show", "lem", "--root", str(tmp_path), "--json"]).stdout)["data"]
    assert (shown["provisional"], shown["conditional_on"], shown["workflow_state"]) == (False, ["clm"], "blocked")
    frontier = json.loads(runner.invoke(app, ["frontier", "--root", str(tmp_path), "--json"]).stdout)["data"]
    assert [(node["id"], node["conditional_on"]) for node in frontier] == [("lem", ["clm"])]
    listed = {node["id"]: node["provisional"] for node in json.loads(runner.invoke(app, ["node", "list", "--root", str(tmp_path), "--json"]).stdout)["data"]}
    assert listed == {"clm": True, "lem": False}
    text = runner.invoke(app, ["node", "show", "lem", "--root", str(tmp_path)]).stdout
    assert "Conditional on" in text and "clm" in text
