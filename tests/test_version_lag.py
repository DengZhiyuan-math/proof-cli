"""A pin that lags its dependency's accepted version reads stale (#23).

L is accepted at v1 and M pins it; L is revised to v2 with the same interface and accepted.
M's pin says v1 while L's accepted version is 2: M reads `potentially-stale` (and the page
offers M a Lightweight re-review for exactly that), and a new node resting on M is blocked
with `dependency-stale`, distinct from `dependency-challenged`.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.proof_map import (
    claim_node,
    create_node,
    dependency_pin_is_current,
    dependency_pin_lags,
    get_accepted_version,
    get_blocked_reason,
    get_dependency_pin,
    get_integrity_state,
    get_workflow_state,
    open_challenge,
)
from proof_cli.storage import ensure_project


def _accept(store, node_id: str, content: str) -> None:
    submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="scoped", content=content)
    researcher(store).decide_acceptance(node_id, "accept")


def _lagging(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L holds")
    _accept(store, "L", "proof of L, v1")
    create_node(store, node_id="M", kind="claim", statement="M holds, given L", dependencies=["L"])
    _accept(store, "M", "proof of M")
    assert get_integrity_state(store, "M") == "current"
    # a proof-only revision of L: same statement, a new accepted version
    _accept(store, "L", "proof of L, v2, shorter")
    return store


def test_a_pin_behind_the_dependencys_accepted_version_lags_though_the_interface_is_the_same(tmp_path: Path):
    store = _lagging(tmp_path)
    pin = get_dependency_pin(store, "M", "L")
    assert (pin.pinned_version, get_accepted_version(store, "L")) == (1, 2)
    assert dependency_pin_is_current(store, pin)  # the interface didn't change …
    assert dependency_pin_lags(store, pin)  # … but M was checked against v1


def test_an_accepted_dependent_with_a_lagging_pin_reads_potentially_stale(tmp_path: Path):
    store = _lagging(tmp_path)
    assert get_integrity_state(store, "M") == "potentially-stale"


def test_a_new_node_resting_on_it_is_blocked_as_dependency_stale_not_challenged(tmp_path: Path):
    store = _lagging(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N holds, given M", dependencies=["M"])
    assert (get_workflow_state(store, "N"), get_blocked_reason(store, "N")) == ("blocked", "dependency-stale")


def test_a_challenge_upstream_still_reads_as_dependency_challenged(tmp_path: Path):
    store = _lagging(tmp_path)
    open_challenge(store, "L", opened_by="agent_x", rationale="a gap")
    create_node(store, node_id="N", kind="claim", statement="N holds, given M", dependencies=["M"])
    assert get_blocked_reason(store, "N") == "dependency-challenged"  # a Challenge outranks a lag


def test_a_pin_that_matches_the_accepted_version_does_not_lag(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L holds")
    _accept(store, "L", "proof of L")
    create_node(store, node_id="M", kind="claim", statement="M holds, given L", dependencies=["L"])
    _accept(store, "M", "proof of M")
    assert not dependency_pin_lags(store, get_dependency_pin(store, "M", "L"))
    assert get_integrity_state(store, "M") == "current"


def test_the_core_and_the_page_agree_on_the_lag(tmp_path: Path):
    ReviewApp = pytest.importorskip("proof_web.server").ReviewApp  # the page (proof-web), when it is installed

    store = _lagging(tmp_path)
    view = ReviewApp(store).node("M")
    (dependency,) = view["dependencies"]
    assert dependency["remedy"] == "lightweight-re-review"
    assert view["integrity_state"] == "potentially-stale"


# -- #24: a Lightweight re-review is for a lag, and clears it -----------------------------


def test_the_whole_loop_a_lag_is_reviewed_lightly_and_the_dependent_reads_current_again(tmp_path: Path):
    """accept L v1 → M pins v1 → L v2 with the same interface → M stale → revalidate → M current."""
    store = _lagging(tmp_path)
    assert get_integrity_state(store, "M") == "potentially-stale"

    record = researcher(store).revalidate_dependency("M", "L", rationale="the v2 proof changes nothing M uses")

    assert record.decision.value == "reaffirmed"
    assert get_dependency_pin(store, "M", "L").pinned_version == 2
    assert get_integrity_state(store, "M") == "current"
    create_node(store, node_id="N", kind="claim", statement="N holds, given M", dependencies=["M"])
    assert get_workflow_state(store, "N") == "open"  # no longer blocked as dependency-stale


def test_a_lightweight_re_review_with_nothing_lagging_is_refused(tmp_path: Path):
    """PR #24: it used to succeed with no lag at all, twice in a row, recording two decisions."""
    import pytest

    from proof_cli.proof_map import ProofMapError
    from proof_cli.reviews import load_entries

    store = _lagging(tmp_path)
    researcher(store).revalidate_dependency("M", "L")
    before = len(load_entries(store.root)[0])

    with pytest.raises(ProofMapError) as refused:
        researcher(store).revalidate_dependency("M", "L")

    assert refused.value.code == "PIN_NOT_LAGGING"
    assert len(load_entries(store.root)[0]) == before  # no second reaffirmed decision
