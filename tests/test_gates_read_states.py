"""Core's gates read the node's states (ADR-0025 checks 1 and 3; #321, part 1 of #283).

Claim, split, dependency edits, fixed text and Promote read the five states, never the old acceptance axis: a sealed
node is not the agents' to work, a verified one with nothing open against it neither, and a node whose statement is
challenged as false waits for the Challenge. An old Acceptance reads as a verification and an old Rejection as such a
Challenge (ADR-0025 point 26), so a node verified on the page and one Accepted before the switch are refused alike.
Synthetic projects only.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.domain import Challenge
from proof_cli.proof_map import (
    ProofMapError,
    add_dependency,
    claim_node,
    create_node,
    fixed_by,
    get_node,
    open_challenge,
    restate_node,
    split_node,
)
from proof_cli.storage import ensure_project, insert_challenge


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def _snapshot(store, node_id: str) -> None:
    submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"a proof of {node_id}")


def _split(store, node_id: str):
    return lambda: split_node(store, node_id, [{"id": f"{node_id}-part", "statement": "a part"}], created_by="agent")


def test_a_claim_the_researcher_verified_or_sealed_true_is_promoted_and_an_unverified_one_is_not(tmp_path: Path):
    store = ensure_project(tmp_path)
    reviewer = researcher(store)
    for node_id in ("VER", "SEAL", "OPEN"):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds")
    _snapshot(store, "VER")
    reviewer.verify("VER", rationale="checked")
    reviewer.seal("SEAL", True, rationale="classical")
    _snapshot(store, "OPEN")
    assert reviewer.promote_to_lemma("VER").id == "VER"
    assert reviewer.promote_to_lemma("SEAL").id == "SEAL"
    assert _code(lambda: reviewer.promote_to_lemma("OPEN")) == "NOT_VERIFIED"  # checks passed is not enough (ADR-0025 point 14)


def test_a_sealed_node_is_not_the_agents_to_claim_split_or_rewire_and_the_researcher_may_still_rewire_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    reviewer = researcher(store)
    create_node(store, node_id="T", kind="lemma", statement="T")
    create_node(store, node_id="F", kind="lemma", statement="F")
    create_node(store, node_id="X", kind="lemma", statement="X")
    reviewer.seal("T", True, rationale="known")
    reviewer.seal("F", False, rationale="known false")
    for node_id in ("T", "F"):
        assert _code(lambda: claim_node(store, node_id, claimant_id="agent")) == "NODE_SEALED"
        assert _code(_split(store, node_id)) == "NODE_SEALED"
        assert _code(lambda: add_dependency(store, node_id, "X", edited_by="agent")) == "NODE_SEALED"
    add_dependency(store, "T", "X", edited_by="human")   # a node may come to rest under a seal later (ADR-0025 point 14)
    assert get_node(store, "T").dependencies == ["X"]


def test_a_verified_node_is_refused_until_an_agent_challenges_it_and_an_old_acceptance_reads_the_same(tmp_path: Path):
    store = ensure_project(tmp_path)
    reviewer = researcher(store)
    create_node(store, node_id="VER", kind="claim", statement="verified on the page")
    create_node(store, node_id="ACC", kind="claim", statement="accepted before the switch")
    create_node(store, node_id="X", kind="lemma", statement="X")
    _snapshot(store, "VER")
    reviewer.verify("VER", rationale="checked")
    _snapshot(store, "ACC")
    reviewer.decide_acceptance("ACC", "accept")   # an old Acceptance reads as a verification (ADR-0025 point 26)
    for node_id in ("VER", "ACC"):
        assert _code(lambda: claim_node(store, node_id, claimant_id="agent")) == "NODE_VERIFIED"
        assert _code(_split(store, node_id)) == "NODE_VERIFIED"
        assert _code(lambda: add_dependency(store, node_id, "X", edited_by="agent")) == "NODE_VERIFIED"
    open_challenge(store, "VER", kind="proof", opened_by="agent", rationale="step 2 skips a case")  # lapses the verification
    assert claim_node(store, "VER", claimant_id="agent").node_id == "VER"


def test_a_node_challenged_as_false_waits_and_a_resplit_one_level_up_stays_open(tmp_path: Path):
    """ADR-0025 point 6's example: A uses U1 and U2, and U1 uses N and S; the researcher challenges N as false. N waits
    for the researcher to conclude. What the Challenge stops below U1 is the agents' and the frontier's to hold back,
    while U1 may be split again, one way the Challenge is settled (point 7)."""
    store = ensure_project(tmp_path)
    for node_id in ("N", "S", "U2"):
        create_node(store, node_id=node_id, kind="claim", statement=node_id)
    create_node(store, node_id="U1", kind="claim", statement="U1", dependencies=["N", "S"])
    create_node(store, node_id="A", kind="theorem", statement="A", dependencies=["U1", "U2"])
    open_challenge(store, "N", kind="statement", opened_by="human", rationale="N fails for n = 1")
    assert _code(lambda: claim_node(store, "N", claimant_id="agent")) == "STATEMENT_CHALLENGED"
    assert _code(_split(store, "N")) == "STATEMENT_CHALLENGED"
    assert [child.id for child in _split(store, "U1")()] == ["U1-part"]


def test_an_agents_statement_challenge_leaves_both_sides_to_be_worked(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="every continuous f on [0,1] is monotone")
    create_node(store, node_id="U", kind="claim", statement="U", dependencies=["N"])
    create_node(store, node_id="CE", kind="claim", statement="f(x)=x(1-x) is continuous on [0,1] and not monotone")
    open_challenge(store, "N", kind="statement", opened_by="agent", rationale="not monotone", counterexample="CE")
    assert claim_node(store, "N", claimant_id="agent").node_id == "N"   # a proof of N is one side (ADR-0025 point 7)


def test_a_challenged_node_nothing_rests_on_waits_for_the_researcher(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="R", kind="claim", statement="R")
    insert_challenge(store, Challenge(id="old-1", target_node_id="R", opened_by="agent", rationale="R may not hold"))  # no kind
    assert _code(lambda: claim_node(store, "R", claimant_id="agent")) == "STATEMENT_CHALLENGED"


def test_only_a_verification_a_seal_or_an_old_approval_fixes_the_text(tmp_path: Path):
    store = ensure_project(tmp_path)
    reviewer = researcher(store)
    create_node(store, node_id="REJ", kind="claim", statement="a rejected route")
    create_node(store, node_id="REV", kind="claim", statement="a claim sent back")
    create_node(store, node_id="ACC", kind="claim", statement="an accepted claim")
    _snapshot(store, "REJ")
    reviewer.decide_acceptance("REJ", "reject", rationale="the route fails")
    _snapshot(store, "REV")
    reviewer.decide_acceptance("REV", "revision-requested", rationale="step 2 is unclear")
    _snapshot(store, "ACC")
    reviewer.decide_acceptance("ACC", "accept")
    assert fixed_by(store, "REJ") is None and fixed_by(store, "REV") is None   # neither relied on the text: it may still be restated
    assert fixed_by(store, "ACC")["kind"] == "acceptance"
    restate_node(store, "REJ", statement="a corrected route", reason="the rejection named the gap", by="human")
    assert get_node(store, "REJ").statement == "a corrected route"
    assert _code(lambda: restate_node(store, "ACC", statement="changed", reason="r", by="human")) == "TEXT_FIXED"
