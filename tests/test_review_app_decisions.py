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
    get_acceptance_state,
    get_dependency_pin,
    get_integrity_state,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    list_integrity_warnings,
    open_challenge,
    record_evidence_check,
)
from proof_cli.collaboration import list_review_records
from proof_cli.storage import ensure_project, get_active_claim, get_current_candidate_proof
from _review_client import DirectClient, decide
from _proofs import submit_proof


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
    submit_proof(store, node_id, claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content=f"proof {node_id}")
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


# -- a corrected source: dependents move onto it by the researcher's decision (#20) ------


def _withdrawn_with_a_correction(store):
    """`ref` found wanting, `ref_v2` citing the corrected source, and nodes resting on `ref`."""
    _reviewed_reference(store)
    _accepted(store, "uses_ref", ["ref"])
    create_node(store, node_id="new_dep", kind="claim", statement="later", dependencies=["ref"])
    create_node(store, node_id="rej", kind="claim", statement="abandoned", dependencies=["ref"])
    submit_proof(store, "rej", claimant_id="agent_a", scoping_rationale="scoped", content="proof rej")
    researcher(store).decide_acceptance("rej", "reject")
    researcher(store).decide_reference_review("ref", "no-longer-callable", rationale="the published proof has a gap")
    _reviewed_reference(store, "ref_v2")


def test_migrating_dependents_moves_them_onto_the_correction_and_makes_the_accepted_ones_re_confirm(tmp_path: Path):
    store = ensure_project(tmp_path)
    _withdrawn_with_a_correction(store)

    record = researcher(store).migrate_dependents("ref", "ref_v2", rationale="erratum published as v2")

    assert get_node(store, "uses_ref").dependencies == ["ref_v2"]
    assert get_node(store, "new_dep").dependencies == ["ref_v2"]
    assert get_node(store, "rej").dependencies == ["ref"]  # Rejected: the record of an abandoned route, left as it was
    # an acceptance made against the withdrawn citation no longer counts: the researcher looks again
    assert get_acceptance_state(store, "uses_ref") == "unverifiable"
    assert get_workflow_state(store, "uses_ref") == "review-needed"
    assert any(w.code == "DECISION_NO_LONGER_APPLIES" and w.details["node_id"] == "uses_ref" for w in list_integrity_warnings(store))
    assert get_workflow_state(store, "new_dep") == "open"
    assert get_dependency_pin(store, "uses_ref", "ref") is None
    assert get_dependency_pin(store, "uses_ref", "ref_v2") is not None

    # the decision is a line in the withdrawn node's reviews.jsonl, naming the correction and who moved
    from proof_cli.authority import verify_decision_row

    assert (record.kind.value, record.decision.value) == ("dependent_migration", "superseded")
    verdict = verify_decision_row(store, record.decision_row_id)
    assert verdict.status == "verified"
    assert [pin.target_node_id for pin in verdict.payload.dependency_pins] == ["ref_v2"]
    assert verdict.payload.migrated_dependents == ["new_dep", "uses_ref"]
    assert (tmp_path / "proofs" / "ref" / "reviews.jsonl").is_file()

    # re-Accepting the same snapshot against the correction counts again
    researcher(store).decide_acceptance("uses_ref", "accept")
    assert get_acceptance_state(store, "uses_ref") == "accepted"
    assert get_integrity_state(store, "uses_ref") == "current"


@pytest.mark.parametrize(
    "old, replacement, code",
    [
        ("ref_v2", "ref", "REFERENCE_STILL_CALLABLE"),  # only a withdrawn citation's dependents move
        ("ref", "ref", "SAME_NODE"),
        ("ref", "uses_ref", "REPLACEMENT_NOT_IMPORTED_RESULT"),
        ("uses_ref", "ref_v2", "NOT_IMPORTED_RESULT"),
        ("ref", "nope", "NODE_NOT_FOUND"),
    ],
)
def test_migrating_dependents_is_refused_when_it_does_not_apply(tmp_path: Path, old, replacement, code):
    store = ensure_project(tmp_path)
    _withdrawn_with_a_correction(store)

    with pytest.raises(ProofMapError) as refused:
        researcher(store).migrate_dependents(old, replacement)

    assert refused.value.code == code
    assert get_node(store, "uses_ref").dependencies == ["ref"]


def test_migrating_onto_a_withdrawn_replacement_or_with_nothing_to_move_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _withdrawn_with_a_correction(store)
    create_node(store, node_id="ref_bad", kind="imported_result", statement="K", source_locator="doi:k", source_version="v3")
    researcher(store).decide_reference_review("ref_bad", "no-longer-callable")

    with pytest.raises(ProofMapError) as refused:
        researcher(store).migrate_dependents("ref", "ref_bad")
    assert refused.value.code == "REPLACEMENT_NOT_CALLABLE"

    researcher(store).migrate_dependents("ref", "ref_v2")
    with pytest.raises(ProofMapError) as refused:
        researcher(store).migrate_dependents("ref", "ref_v2")
    assert refused.value.code == "NO_DEPENDENTS"


def test_the_page_offers_moving_dependents_onto_each_usable_correction(app):
    store, client = app
    _withdrawn_with_a_correction(store)

    offered = [d for d in client.get("/api/node/ref")[1]["data"]["decisions"] if d["kind"] == "dependent_migration"]
    assert [{k: v for k, v in d.items() if k != "binding"} for d in offered] == [
        {"kind": "dependent_migration", "target_id": "ref", "decision": "superseded", "dependency_id": "ref_v2"}
    ]

    status, body = decide(client, [{**offered[0], "rationale": "erratum"}])
    assert status == 200, body
    assert get_node(store, "uses_ref").dependencies == ["ref_v2"]
    assert not [d for d in client.get("/api/node/ref")[1]["data"]["decisions"] if d["kind"] == "dependent_migration"]


def _another_writer_first(store, monkeypatch, write):
    """Run `write` from a second store just before `store`'s next write transaction takes the lock:
    the window between reading the project and writing it (PR #63 audit)."""
    from contextlib import contextmanager

    from proof_cli.storage import ProjectStore

    original = store.transaction
    pending = [write]

    @contextmanager
    def interleaved():
        if pending:
            pending.pop()(ProjectStore(store.root))
        with original() as conn:
            yield conn

    monkeypatch.setattr(store, "transaction", interleaved)


def test_a_split_just_before_migration_keeps_its_new_edge(tmp_path: Path, monkeypatch):
    from proof_cli.proof_map import split_node

    store = ensure_project(tmp_path)
    _withdrawn_with_a_correction(store)
    _another_writer_first(store, monkeypatch, lambda other: split_node(other, "new_dep", [{"id": "child", "statement": "c"}]))

    researcher(store).migrate_dependents("ref", "ref_v2")

    assert get_node(store, "new_dep").dependencies == ["ref_v2", "child"]


def test_a_dependent_added_just_before_migration_is_moved_and_recorded(tmp_path: Path, monkeypatch):
    from proof_cli.authority import verify_decision_row

    store = ensure_project(tmp_path)
    _withdrawn_with_a_correction(store)
    _another_writer_first(store, monkeypatch, lambda other: create_node(other, node_id="late", kind="claim", statement="l", dependencies=["ref"]))

    record = researcher(store).migrate_dependents("ref", "ref_v2")

    assert get_node(store, "late").dependencies == ["ref_v2"]
    assert verify_decision_row(store, record.decision_row_id).payload.migrated_dependents == ["late", "new_dep", "uses_ref"]


def test_a_replacement_withdrawn_just_before_migration_is_refused(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    _withdrawn_with_a_correction(store)
    _another_writer_first(store, monkeypatch, lambda other: researcher(other).decide_reference_review("ref_v2", "no-longer-callable"))

    with pytest.raises(ProofMapError) as refused:
        researcher(store).migrate_dependents("ref", "ref_v2")

    assert refused.value.code == "REPLACEMENT_NOT_CALLABLE"
    assert get_node(store, "uses_ref").dependencies == ["ref"]


def test_a_page_that_showed_the_old_dependencies_cannot_accept_the_new_ones(app):
    """PR #63 audit: an Accept from a page opened before a migration would bind a citation it never showed."""
    store, client = app
    _reviewed_reference(store)
    _accepted(store, "uses_ref", ["ref"])
    submit_proof(store, "uses_ref", claimant_id="agent_a", scoping_rationale="revision", content="revised proof")
    view = client.get("/api/node/uses_ref")[1]["data"]
    accept = next(d for d in view["decisions"] if d["kind"] == "acceptance" and d["decision"] == "accept")
    stale = {**accept, "viewed_candidate_proof_sha256": view["candidate_proof"]["sha256"], "rationale": "read against ref"}

    researcher(store).decide_reference_review("ref", "no-longer-callable")
    _reviewed_reference(store, "ref_v2")
    researcher(store).migrate_dependents("ref", "ref_v2")

    status, body = decide(client, [stale])
    assert body["data"]["results"][0]["error"]["code"] == "STALE_VIEW", body
    assert get_acceptance_state(store, "uses_ref") == "unverifiable"

    reloaded = client.get("/api/node/uses_ref")[1]["data"]
    fresh = next(d for d in reloaded["decisions"] if d["kind"] == "acceptance" and d["decision"] == "accept")
    status, body = decide(client, [{**fresh, "viewed_candidate_proof_sha256": reloaded["candidate_proof"]["sha256"]}])
    assert body["data"]["results"][0]["ok"], body
    assert get_acceptance_state(store, "uses_ref") == "accepted"


def test_the_pending_list_binds_each_decision_to_what_it_showed(app):
    store, client = app
    _reviewed_reference(store)
    create_node(store, node_id="uses_ref", kind="claim", statement="s", dependencies=["ref"])
    submit_proof(store, "uses_ref", claimant_id="agent_a", scoping_rationale="scoped", content="proof")
    (item,) = [p for p in client.get("/api/state")[1]["data"]["pending"] if p["node_id"] == "uses_ref"]
    assert set(item["bindings"]) == {"accept", "revision-requested", "reject"}

    submit_proof(store, "uses_ref", claimant_id="agent_a", scoping_rationale="scoped", content="a newer proof")  # not what the row showed
    status, body = decide(client, [{"kind": "acceptance", "target_id": "uses_ref", "decision": "accept", "binding": item["bindings"]["accept"]}])
    assert body["data"]["results"][0]["error"]["code"] == "STALE_VIEW", body


def test_the_app_offers_both_reference_decisions_and_stops_listing_a_withdrawn_one(app):
    store, client = app
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")

    view = client.get("/api/node/ref")[1]["data"]
    assert all(d.pop("binding") for d in view["decisions"])  # each bound to what the page shows
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
    submit_proof(store, node_id, claimant_id="agent_a", session_id="s2", scoping_rationale="scoped", content="revised proof")
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
    submit_proof(store, "lem", claimant_id="agent_a", session_id="s2", scoping_rationale="scoped", content="v2")
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
