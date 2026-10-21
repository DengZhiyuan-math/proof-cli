"""A pin taken while its dependency was not yet Accepted (ADR-0021: work runs ahead of review).

A Pursue works a chain bottom-up before the researcher reviews any of it, so every snapshot pins dependencies that
are only Provisional: what the dependent was checked against is the dependency's statement, never a version of its
proof. Such a pin is current while that interface stands, and lags nothing; it changes only when the dependency is
restated. The researcher then Accepts bottom-up (CONTEXT, Conditional: "cleared as the researcher Accepts
bottom-up"), and each Acceptance pins the accepted versions it was made against; a later proof-only revision of a
dependency leaves the pin current, as a pin follows an unchanged interface by itself (ADR-0025). Before this, every such edge read "interface
changed", what rested on it read dependency-stale, and a chain could not be Accepted past its middle.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher

from proof_cli.proof_map import (
    create_node,
    dependency_pin_is_current,
    get_accepted_version,
    get_acceptance_state,
    get_blocked_reason,
    get_dependency_pin,
    get_integrity_state,
    record_evidence_check,
    restate_node,
)
from proof_cli.storage import ensure_project, upsert_dependency_pin


def _passed_by_verifier(store, node_id: str, content: str | None = None):
    proof = submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=content or f"proof of {node_id}")
    record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", notes="no objections")


def _chain(tmp_path: Path):
    """leaf → mid → top, each passed by the Verifier while nothing is Accepted: what a Pursue leaves."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="leaf", kind="claim", statement="A holds", created_by="dec-1")
    create_node(store, node_id="mid", kind="claim", statement="B holds, given A", dependencies=["leaf"], created_by="dec-1")
    create_node(store, node_id="top", kind="theorem", statement="T holds, given B", dependencies=["mid"], created_by="reader")
    for node_id in ("leaf", "mid", "top"):
        _passed_by_verifier(store, node_id)
    return store


def _accept(store, node_id: str) -> None:
    researcher(store).decide_acceptance(node_id, "accept")


def _current(store, node_id: str, dependency_id: str) -> bool:
    return dependency_pin_is_current(store, get_dependency_pin(store, node_id, dependency_id))


def test_a_chain_worked_ahead_of_review_reads_no_changed_interface(tmp_path: Path):
    store = _chain(tmp_path)

    assert _current(store, "mid", "leaf") and _current(store, "top", "mid")
    assert get_blocked_reason(store, "top") == "not-accepted"  # waiting for decisions, not stale


def test_the_researcher_accepts_it_bottom_up(tmp_path: Path):
    store = _chain(tmp_path)

    for node_id in ("leaf", "mid", "top"):
        _accept(store, node_id)
        assert get_acceptance_state(store, node_id) == "accepted"
        assert get_integrity_state(store, node_id) == "current", node_id

    assert _current(store, "mid", "leaf") and _current(store, "top", "mid")


def test_an_acceptance_pins_the_accepted_versions_it_was_made_against_and_a_proof_only_revision_leaves_it_current(tmp_path: Path):
    store = _chain(tmp_path)
    _accept(store, "leaf")
    _accept(store, "mid")

    pin = get_dependency_pin(store, "mid", "leaf")
    assert pin.pinned_version == get_accepted_version(store, "leaf") == 1

    # a proof-only revision of leaf: the interface mid was checked against stands, so its pin follows (ADR-0025)
    submit_proof(store, "leaf", claimant_id="agent", scoping_rationale="scoped", content="proof of leaf, v2, shorter")
    _accept(store, "leaf")
    assert _current(store, "mid", "leaf") and get_integrity_state(store, "mid") == "current"


def test_a_pin_taken_before_acceptance_still_sees_its_dependency_restated(tmp_path: Path):
    store = _chain(tmp_path)

    restate_node(store, "leaf", statement="A holds for every n", reason="the quantifier was missing")

    assert not _current(store, "mid", "leaf")
    assert get_blocked_reason(store, "top") == "dependency-stale"


def test_a_restated_dependency_is_not_pinned_away_by_the_dependents_acceptance(tmp_path: Path):
    store = _chain(tmp_path)
    restate_node(store, "leaf", statement="A holds for every n", reason="the quantifier was missing")
    _passed_by_verifier(store, "leaf", content="proof of leaf for every n")
    _accept(store, "leaf")

    _accept(store, "mid")  # its snapshot was checked against the old statement

    assert get_dependency_pin(store, "mid", "leaf").pinned_version is None
    assert get_integrity_state(store, "mid") == "potentially-stale"


@pytest.fixture
def legacy(tmp_path: Path):
    """The chain with the pins core wrote before this fix: neither a version nor a fingerprint."""
    store = _chain(tmp_path)
    for node_id, target in (("mid", "leaf"), ("top", "mid")):
        pin = get_dependency_pin(store, node_id, target)
        upsert_dependency_pin(store, pin.model_copy(update={"pinned_version": None, "pinned_fingerprint": None}))
    return store


def test_an_old_pin_reads_current_and_the_chain_is_accepted_bottom_up(legacy):
    assert dependency_pin_is_current(legacy, get_dependency_pin(legacy, "mid", "leaf"))

    for node_id in ("leaf", "mid", "top"):
        _accept(legacy, node_id)
        assert get_integrity_state(legacy, node_id) == "current", node_id
    assert get_dependency_pin(legacy, "top", "mid").pinned_version == 1


def test_an_old_pin_still_sees_its_dependency_restated_after_it_was_taken(legacy):
    restate_node(legacy, "leaf", statement="A holds for every n", reason="the quantifier was missing")

    assert not dependency_pin_is_current(legacy, get_dependency_pin(legacy, "mid", "leaf"))


def test_a_definition_edited_under_a_pinned_dependency_is_not_pinned_away(tmp_path: Path):
    """top's snapshot was checked against leaf while leaf's Definition said one thing; it says another when leaf is
    Accepted. Accepting the old top must leave its pin reading changed, as a restatement would (independent audit)."""
    from proof_cli.definitions import add_definition, edit_definition

    store = ensure_project(tmp_path)
    add_definition(store, "d", term="D", text="d is 1", created_by="reader")
    create_node(store, node_id="leaf", kind="claim", statement="D holds", definitions=["d"], created_by="reader")
    create_node(store, node_id="top", kind="theorem", statement="T holds, given D", dependencies=["leaf"], created_by="reader")
    for node_id in ("leaf", "top"):
        _passed_by_verifier(store, node_id)

    edit_definition(store, "d", text="d is 2", edited_by="reader", reason="the value was wrong")
    assert not _current(store, "top", "leaf")

    _passed_by_verifier(store, "leaf", content="proof of leaf under the corrected d")
    _accept(store, "leaf")
    _accept(store, "top")

    assert get_dependency_pin(store, "top", "leaf").pinned_version is None
    assert get_integrity_state(store, "top") == "potentially-stale"


def test_an_old_pin_keeps_its_time_once_an_acceptance_signs_it(legacy):
    """The pin an Acceptance signs is read back from the decision; an old pin's time must still be its snapshot's,
    or a restatement after the snapshot reads as one before it (independent audit)."""
    restate_node(legacy, "leaf", statement="A holds for every n", reason="the quantifier was missing")
    _passed_by_verifier(legacy, "leaf", content="proof of leaf for every n")
    _accept(legacy, "leaf")

    _accept(legacy, "mid")  # its snapshot was checked against the old statement

    assert not dependency_pin_is_current(legacy, get_dependency_pin(legacy, "mid", "leaf"))
    assert get_integrity_state(legacy, "mid") == "potentially-stale"
