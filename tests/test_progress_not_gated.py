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


def test_restating_a_provisional_node_s_text_ends_its_provisional_standing(tmp_path: Path):
    from proof_cli.proof_map import restate_node

    store = _parent_on_claim(tmp_path)
    _passed_by_verifier(store, "clm")
    assert _frontier(store) == {"lem"}

    restate_node(store, "clm", statement="C, corrected", reason="the draft's reading was wrong")

    # the Verifier passed a proof of other text: nothing rests on it until it is read again
    assert not is_provisional(store, "clm")
    assert "lem" not in _frontier(store)


def test_a_blocked_node_s_waiting_snapshot_is_readable(tmp_path: Path):
    from proof_cli.proof_map import awaiting_decision

    store = _parent_on_claim(tmp_path)
    assert awaiting_decision(store, "lem") is None
    proof = submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof")
    assert get_workflow_state(store, "lem") == "blocked"
    assert awaiting_decision(store, "lem").id == proof.id


def test_a_node_resting_on_nothing_settled_or_provisional_is_not_provisional(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="x", kind="claim", statement="X")
    create_node(store, node_id="c", kind="claim", statement="C", dependencies=["x"])
    create_node(store, node_id="t", kind="lemma", statement="T", dependencies=["c"])

    _passed_by_verifier(store, "c")  # x has no proof at all: c's proof rests on nothing yet

    assert not is_provisional(store, "c")
    assert "t" not in _frontier(store)
    assert conditional_on(store, "t") == frozenset()

    _passed_by_verifier(store, "x")  # once x is Provisional, so is c

    assert is_provisional(store, "c")
    assert "t" in _frontier(store)
    assert conditional_on(store, "t") == frozenset({"x", "c"})


def test_a_challenge_on_an_accepted_node_in_the_support_ends_provisional_standing(tmp_path: Path):
    from proof_cli.proof_map import open_challenge

    store = ensure_project(tmp_path)
    create_node(store, node_id="a", kind="claim", statement="A")
    create_node(store, node_id="x", kind="claim", statement="X", dependencies=["a"])
    create_node(store, node_id="c", kind="claim", statement="C", dependencies=["x"])
    submit_proof(store, "a", claimant_id="agent", scoping_rationale="scoped", content="proof of a")
    researcher(store).decide_acceptance("a", "accept")
    _passed_by_verifier(store, "x")
    _passed_by_verifier(store, "c")
    assert is_provisional(store, "x") and is_provisional(store, "c")

    open_challenge(store, "a", rationale="step 2 is wrong")

    assert not is_provisional(store, "x")
    assert not is_provisional(store, "c")  # two steps above the Challenge


def test_a_later_failed_verifier_check_on_the_same_snapshot_ends_provisional_standing(tmp_path: Path):
    store = _parent_on_claim(tmp_path)
    check = _passed_by_verifier(store, "clm")
    assert is_provisional(store, "clm")

    record_evidence_check(store, check.candidate_proof_id, "failed", run_by="prover-1/verifier", notes="1. step 3 cites nothing")

    assert not is_provisional(store, "clm")
    assert "lem" not in _frontier(store)


def test_a_citation_found_no_longer_callable_makes_the_snapshots_resting_on_it_potentially_stale(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="ref", kind="imported_result", statement="Known", source_locator="doi:x", source_version="v1")
    create_node(store, node_id="mid", kind="claim", statement="M", dependencies=["ref"])
    create_node(store, node_id="lem", kind="lemma", statement="L", dependencies=["mid"])
    _passed_by_verifier(store, "mid")
    submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof of lem")
    assert get_integrity_state(store, "lem") == "current"

    researcher(store).decide_reference_review("ref", "no-longer-callable", rationale="the cited theorem needs compact support")

    assert get_integrity_state(store, "mid") == "potentially-stale"
    assert get_integrity_state(store, "lem") == "potentially-stale"
    assert not is_provisional(store, "mid")


def test_an_imported_result_whose_review_no_longer_counts_is_not_provisional(tmp_path: Path):
    import json

    from proof_cli.proof_map import get_reference_review_state

    store = ensure_project(tmp_path)
    create_node(store, node_id="ref", kind="imported_result", statement="Known", source_locator="doi:x", source_version="v1")
    researcher(store).decide_reference_review("ref", rationale="checked")
    path = store.root / "proofs" / "ref" / "reviews.jsonl"
    line = json.loads(path.read_text())
    line["payload"]["interface_fingerprint"] = "made on something else"  # a decision that no longer binds this node
    path.write_text(json.dumps(line) + "\n")
    assert get_reference_review_state(store, "ref") == "unverifiable"

    # the researcher has decided on it: what stands now is theirs to settle, not an unreviewed citation
    assert not is_provisional(store, "ref")
