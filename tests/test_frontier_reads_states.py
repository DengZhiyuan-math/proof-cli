"""The frontier is CONTEXT.md's Frontier, read off the five states (#322, part 2 of #283).

Ready to be worked right now: Proof layer incomplete with no snapshot waiting for a check, or resting directly on a
false node; no Assignee; unsealed, and reached without going through a sealed node; not stopped by a statement
Challenge; every dependency true, verified true or false. Never the old acceptance axis: a dependency the researcher verified on the page counts as one Accepted did,
and one sealed false is something to work around, not a wait. Synthetic projects only.
"""

from pathlib import Path

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.proof_map import claim_node, create_node, get_frontier, open_challenge, record_evidence_check
from proof_cli.storage import ensure_project


def _frontier(store) -> set[str]:
    return {node.id for node in get_frontier(store)}


def _snapshot(store, node_id: str):
    return submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"a proof of {node_id}")


def test_a_node_resting_directly_on_a_false_node_is_ready_for_a_proof_without_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="F", kind="claim", statement="F")
    create_node(store, node_id="W", kind="claim", statement="W", dependencies=["F"])
    assert _frontier(store) == {"F"}   # W waits for F, which is uncertain

    researcher(store).seal("F", False, rationale="F fails for n = 1")

    assert _frontier(store) == {"W"}   # ADR-0025 point 3: W needs a proof that does not use F


def test_a_dependency_verified_on_the_page_lets_its_user_on_as_an_acceptance_did(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="D", kind="claim", statement="D")
    create_node(store, node_id="U", kind="claim", statement="U", dependencies=["D"])
    _snapshot(store, "D")
    researcher(store).verify("D", rationale="read it")

    assert _frontier(store) == {"U"}


def test_sealed_verified_and_assigned_nodes_are_not_ready_and_a_seal_covers_what_it_rests_on(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id in ("C", "V", "A"):
        create_node(store, node_id=node_id, kind="claim", statement=node_id)
    create_node(store, node_id="T", kind="claim", statement="T", dependencies=["C"])
    researcher(store).seal("T", True, rationale="classical")   # covers C
    _snapshot(store, "V")
    researcher(store).verify("V", rationale="read it")
    claim_node(store, "A", claimant_id="agent")

    assert _frontier(store) == set()


def test_a_snapshot_waiting_for_a_check_is_not_ready_until_a_challenge_sends_it_back(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="H", kind="claim", statement="H")
    _snapshot(store, "H")   # frozen, and no check has passed it: it needs a check, not a Prover
    assert _frontier(store) == set()

    open_challenge(store, "H", kind="proof", opened_by="human", rationale="step 2 skips the case n = 1")

    assert _frontier(store) == {"H"}   # the researcher's reading sends the work back to the agents


def test_a_snapshot_a_run_s_check_passed_waits_for_no_check(tmp_path: Path):
    """A snapshot waits for a check only while no check of a run (the Verifier's or an audit's, by its mark) has passed
    it; once one has, an incomplete Proof layer is the agents' work again."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="P", kind="claim", statement="P")
    proof = _snapshot(store, "P")
    record_evidence_check(store, proof.id, "passed", run_by="numerics-1", checker="mechanical")
    assert _frontier(store) == set()   # a mechanical check is no run's reading of the proof

    record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", checker="verifier")

    assert _frontier(store) == {"P"}


def test_a_node_a_statement_challenge_stops_waits_with_its_branch_and_the_rest_goes_on(tmp_path: Path):
    """ADR-0025 point 6's example: A uses U1 and U2, and U1 uses N and S. N challenged as false stops all work under U1,
    S included; U2 goes on."""
    store = ensure_project(tmp_path)
    for node_id in ("N", "S", "U2"):
        create_node(store, node_id=node_id, kind="claim", statement=node_id)
    create_node(store, node_id="U1", kind="claim", statement="U1", dependencies=["N", "S"])
    create_node(store, node_id="A", kind="theorem", statement="A", dependencies=["U1", "U2"])
    assert _frontier(store) == {"N", "S", "U2"}

    open_challenge(store, "N", kind="statement", opened_by="human", rationale="N fails for n = 1")

    assert _frontier(store) == {"U2"}


def test_an_old_revision_request_on_the_snapshot_sends_it_back_to_the_agents(tmp_path: Path):
    """ADR-0025 point 24: Revision requested is a Challenge against the proof now, so its snapshot waits for no check."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="R", kind="claim", statement="R")
    _snapshot(store, "R")
    researcher(store).decide_acceptance("R", "revision-requested", rationale="step 2 is unclear")   # an older version's line

    assert _frontier(store) == {"R"}


def test_what_only_a_sealed_node_rests_on_is_not_worked(tmp_path: Path):
    """CONTEXT.md, Frontier: reached without going through a sealed node. Sealing false seals only the node, and a node
    that comes to rest under a true seal later is not covered by it; neither is worked through the seal."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="G", kind="claim", statement="G")
    create_node(store, node_id="F", kind="claim", statement="F", dependencies=["G"])
    create_node(store, node_id="T", kind="theorem", statement="T", dependencies=["F"])
    researcher(store).seal("F", False, rationale="F fails for n = 1")
    create_node(store, node_id="L", kind="claim", statement="L")
    create_node(store, node_id="S", kind="claim", statement="S")
    researcher(store).seal("S", True, rationale="classical")
    from proof_cli.proof_map import add_dependency
    add_dependency(store, "S", "L", edited_by="human")   # under the seal after it was made: not covered

    assert _frontier(store) == {"T"}   # T rests directly on F, which is false: it needs a proof without F

