"""Every Human Review decision, made on the proof map page (issue #38, ADR-0010).

Each is driven through the page's own API — read the node, record the
decision — without a socket (see `_review_client.DirectClient`).
"""

from pathlib import Path

import pytest

from _researcher import researcher
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    get_blocked_reason,
    get_challenge,
    get_node,
    get_integrity_state,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    open_challenge,
    record_evidence_check,
    submit_candidate_proof,
)
from proof_cli.collaboration import list_review_records
from proof_cli.storage import ensure_project, get_active_claim, get_current_candidate_proof
from _review_client import DirectClient, decide


@pytest.fixture
def app(tmp_path: Path):
    store = ensure_project(tmp_path)
    yield store, DirectClient(store)


# -- a claim is shown as its assignee; there is no force-release (ADR-0010) ----------


def test_the_node_page_shows_who_holds_the_claim_but_not_how_to_impersonate_them(app):
    store, client = app
    create_node(store, node_id="clm_1", kind="claim", statement="C")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="secret_session")

    view = client.get("/api/node/clm_1")[1]["data"]

    assert view["claim"]["claimant_id"] == "agent_a"
    assert view["claim"]["id"] == get_active_claim(store, "clm_1").id
    assert "secret_session" not in str(view)


def test_a_claim_is_never_a_decision_on_the_page(app):
    """A stale claim is reassigned or cleared on the CLI, by anyone: nothing to sign."""
    store, client = app
    create_node(store, node_id="clm_1", kind="claim", statement="C")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="s")

    decisions = client.get("/api/node/clm_1")[1]["data"]["decisions"]

    assert all(decision["kind"] != "force_release" for decision in decisions)


def _reviewed_reference(store, node_id="ref"):
    create_node(store, node_id=node_id, kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    researcher(store).decide_reference_review(node_id)


def _accepted(store, node_id, dependencies=()):
    create_node(store, node_id=node_id, kind="claim", statement=f"stmt {node_id}", dependencies=list(dependencies))
    submit_candidate_proof(store, node_id, claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content=f"proof {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def test_an_imported_result_found_wanting_is_no_longer_callable_and_its_dependents_notice(tmp_path: Path):
    store = ensure_project(tmp_path)
    _reviewed_reference(store)
    _accepted(store, "uses_ref", ["ref"])
    create_node(store, node_id="new_dep", kind="claim", statement="later", dependencies=["ref"])

    researcher(store).decide_reference_review("ref", "no-longer-callable", rationale="the published proof has a gap")

    assert get_reference_review_state(store, "ref") == "no-longer-callable"
    assert get_integrity_state(store, "uses_ref") == "potentially-stale"
    assert (get_workflow_state(store, "new_dep"), get_blocked_reason(store, "new_dep")) == ("blocked", "dependency-not-callable")


def test_no_longer_callable_is_terminal(tmp_path: Path):
    """A corrected source is a new imported_result node, never a revived old one (#20)."""
    store = ensure_project(tmp_path)
    _reviewed_reference(store)
    researcher(store).decide_reference_review("ref", "no-longer-callable", rationale="gap")

    with pytest.raises(ProofMapError) as refused:
        researcher(store).decide_reference_review("ref", "reference-review")
    assert refused.value.code == "REFERENCE_NOT_CALLABLE"
    assert get_reference_review_state(store, "ref") == "no-longer-callable"


def test_the_app_offers_both_reference_decisions_and_stops_listing_a_withdrawn_one(app):
    store, client = app
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")

    view = client.get("/api/node/ref")[1]["data"]
    assert view["decisions"] == [
        {"kind": "reference_review", "target_id": "ref", "decision": "reference-review"},
        {"kind": "reference_review", "target_id": "ref", "decision": "no-longer-callable"},
    ]
    _, outcome = decide(client, [{"kind": "reference_review", "target_id": "ref", "decision": "no-longer-callable", "rationale": "gap"}])

    assert outcome["data"]["results"][0]["ok"], outcome
    assert get_reference_review_state(store, "ref") == "no-longer-callable"
    assert not client.get("/api/state")[1]["data"]["pending"]
    assert client.get("/api/node/ref")[1]["data"]["decisions"] == []


# -- Challenge outcomes: dismissed / upheld / resolved-by-revision, with rationale (#25) --


def _challenged_and_resubmitted(store, node_id="lem"):
    _accepted(store, node_id)
    challenge = open_challenge(store, node_id, opened_by="agent_b", rationale="step 2?")
    claim_node(store, node_id, claimant_id="agent_a", session_id="s2")
    submit_candidate_proof(store, node_id, claimant_id="agent_a", session_id="s2", scoping_rationale="scoped", content="revised proof")
    return challenge


def test_a_dismissed_challenge_carries_the_researchers_reason(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store, "lem")
    challenge = open_challenge(store, "lem", opened_by="agent_b", rationale="step 2?")

    researcher(store).dismiss_challenge(challenge.id, rationale="step 2 is Lemma 4")

    resolved = get_challenge(store, challenge.id)
    assert (resolved.status.value, resolved.resolution_rationale) == ("dismissed", "step 2 is Lemma 4")


@pytest.mark.parametrize(
    "decision, outcome",
    [("accept", "resolved-by-revision"), ("reject", "upheld"), ("revision-requested", "upheld")],
)
def test_the_decision_on_a_revision_records_how_the_challenge_ended(tmp_path: Path, decision, outcome):
    store = ensure_project(tmp_path)
    challenge = _challenged_and_resubmitted(store)

    researcher(store).decide_acceptance("lem", decision, rationale="read the revision")

    resolved = get_challenge(store, challenge.id)
    assert (resolved.status.value, resolved.resolution_rationale) == (outcome, "read the revision")
    assert [c.id for c in list_challenges(store, status=outcome)] == [challenge.id]


@pytest.mark.parametrize("decision, outcome", [("reference-review", "dismissed"), ("no-longer-callable", "upheld")])
def test_a_reference_decision_records_how_a_challenge_on_it_ended(tmp_path: Path, decision, outcome):
    store = ensure_project(tmp_path)
    _reviewed_reference(store)
    challenge = open_challenge(store, "ref", opened_by="agent_b", rationale="wrong edition?")

    researcher(store).decide_reference_review("ref", decision, rationale="checked the source")

    assert get_challenge(store, challenge.id).status.value == outcome


# -- the node page offers each decision, and each can be signed from it ----------------


def _offered(client, node_id, kind):
    return [d for d in client.get(f"/api/node/{node_id}")[1]["data"]["decisions"] if d["kind"] == kind]


def _record_offered(client, offered, **extra):
    status, outcome = decide(client, [{**offered, **extra}])
    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome


def test_a_lagging_pin_is_shown_and_re_reviewed_from_the_page(app):
    store, client = app
    _accepted(store, "lem")
    _accepted(store, "uses", ["lem"])
    challenge = open_challenge(store, "lem", opened_by="agent_b", rationale="?")
    claim_node(store, "lem", claimant_id="agent_a", session_id="s2")
    submit_candidate_proof(store, "lem", claimant_id="agent_a", session_id="s2", scoping_rationale="scoped", content="v2")
    researcher(store).decide_acceptance("lem", "accept")  # v2, same interface
    assert get_challenge(store, challenge.id).status.value == "resolved-by-revision"

    (dependency,) = client.get("/api/node/uses")[1]["data"]["dependencies"]
    assert (dependency["pin"]["pinned_version"], dependency["accepted_version"], dependency["remedy"]) == (1, 2, "lightweight-re-review")
    (offered,) = _offered(client, "uses", "dependency_revalidation")
    _record_offered(client, offered, rationale="v2 only tidies the proof")

    (dependency,) = client.get("/api/node/uses")[1]["data"]["dependencies"]
    assert dependency["pin"]["pinned_version"] == 2
    assert _offered(client, "uses", "dependency_revalidation") == []


def test_an_evidence_check_is_judged_from_the_page(app):
    store, client = app
    _accepted(store, "lem")
    check = record_evidence_check(store, get_current_candidate_proof(store, "lem").id, "passed", notes="all agree")

    offered = _offered(client, "lem", "evidence_review")
    assert {(d["target_id"], d["decision"]) for d in offered} == {(check.id, "trusted"), (check.id, "unusable")}
    _record_offered(client, next(d for d in offered if d["decision"] == "trusted"))

    (record,) = [r for r in list_review_records(store, object_type="evidence_check", object_id=check.id) if r.kind]
    assert record.decision.value == "trusted"


def test_an_accepted_claim_is_promoted_from_the_page_and_not_offered_again(app):
    store, client = app
    _accepted(store, "clm")

    (offered,) = _offered(client, "clm", "promote")
    _record_offered(client, offered, rationale="reused in three places")

    assert get_node(store, "clm").kind.value == "lemma"
    assert _offered(client, "clm", "promote") == []


def test_a_challenge_is_dismissed_from_the_page(app):
    store, client = app
    _accepted(store, "lem")
    challenge = open_challenge(store, "lem", opened_by="agent_b", rationale="?")

    (offered,) = _offered(client, "lem", "challenge_resolution")
    assert offered["target_id"] == challenge.id
    _record_offered(client, offered, rationale="false alarm")

    assert get_challenge(store, challenge.id).status.value == "dismissed"
