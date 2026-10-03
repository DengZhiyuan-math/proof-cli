"""The review card offers only decisions the server would take, and shows the snapshot's Evidence checks.

#156: a node whose dependencies changed since its snapshot is listed as awaiting review, but no
decision is offered on it (each would be refused DEPENDENCIES_CHANGED); the card says why and
what to do next. #158: the card shows the Evidence checks on the current snapshot, each read
against it by its bound SHA-256, never an older snapshot's as if it were current.
"""

import shutil
from pathlib import Path

import pytest

from _proofs import submit_proof, write_key_ideas
from _researcher import researcher
from _review_client import DirectClient, decide
from proof_cli.authority import candidate_proof_sha256
from proof_cli.proof_map import add_dependency, create_node, get_workflow_state
from test_map_home import PENDING, _home, _state
from test_node_page import REVIEW_VIEW, _panel


@pytest.fixture
def app(tmp_path: Path):
    from proof_cli.storage import ensure_project

    store = ensure_project(tmp_path)
    client = DirectClient(store)
    yield store, client
    client.app.close()


def _ok(response):
    status, body = response
    assert status == 200 and body["ok"], body
    return body["data"]


def _pending(client, node_id):
    (item,) = [p for p in _ok(client.get("/api/state"))["pending"] if p["node_id"] == node_id]
    return item


def _awaiting_with_a_dependency_added_since(store):
    create_node(store, node_id="lem", kind="lemma", statement="L")
    submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof lem")
    researcher(store).decide_acceptance("lem", "accept")
    create_node(store, node_id="a", kind="claim", statement="A")
    submit_proof(store, "a", claimant_id="agent", scoping_rationale="scoped", content="proof a")
    add_dependency(store, "a", "lem")
    assert get_workflow_state(store, "a") == "review-needed"


# -- #156: no decision the server would refuse -----------------------------------------------


def test_a_node_whose_dependencies_changed_is_listed_with_no_decision_and_the_reason(app):
    store, client = app
    _awaiting_with_a_dependency_added_since(store)

    item = _pending(client, "a")

    assert item["decisions"] == []
    blocked = item["review_blocked"]
    assert blocked["reason"] == "DEPENDENCIES_CHANGED"
    assert "snapshot v1" in blocked["message"] and "request review again" in blocked["message"]
    assert blocked["next"].startswith("proof node request-review a")
    # what it would have offered is indeed refused
    _, body = decide(client, [{"kind": "acceptance", "target_id": "a", "decision": "accept"}])
    assert body["data"]["results"][0]["error"]["code"] == "DEPENDENCIES_CHANGED"


def test_the_node_page_offers_no_acceptance_decision_once_its_dependencies_changed(app):
    store, client = app
    _awaiting_with_a_dependency_added_since(store)

    view = _ok(client.get("/api/node/a"))

    assert not [d for d in view["decisions"] if d["kind"] == "acceptance"]
    assert view["review_blocked"]["reason"] == "DEPENDENCIES_CHANGED"


def test_requesting_review_again_brings_the_decisions_back(app):
    from proof_cli.proof_map import request_review

    store, client = app
    _awaiting_with_a_dependency_added_since(store)
    request_review(store, "a", requested_by="agent", rationale="re-pinned")

    item = _pending(client, "a")
    assert item["decisions"] == ["accept", "revision-requested", "reject"] and item["review_blocked"] is None
    view = _ok(client.get("/api/node/a"))
    assert {d["decision"] for d in view["decisions"] if d["kind"] == "acceptance"} == {"accept", "revision-requested", "reject"}
    assert view["review_blocked"] is None


def test_a_node_whose_dependencies_stand_is_unaffected(app):
    store, client = app
    create_node(store, node_id="b", kind="claim", statement="B")
    submit_proof(store, "b", claimant_id="agent", scoping_rationale="scoped", content="proof b")

    item = _pending(client, "b")
    assert item["decisions"] == ["accept", "revision-requested", "reject"]
    assert item["review_blocked"] is None


# -- #158: the current snapshot's Evidence checks ---------------------------------------------


def _two_snapshots(store, client):
    _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C"}))
    write_key_ideas(store, "c1")
    v1 = _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    (store.root / "proofs" / "c1" / "proof.tex").write_text("a second version\n")
    v2 = _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    return v1, v2


def test_the_card_shows_the_current_snapshots_evidence_and_not_an_older_ones(app):
    store, client = app
    v1, v2 = _two_snapshots(store, client)
    _ok(client.post("/api/node/c1/evidence", {"candidate_proof_id": v1["id"], "outcome": "failed", "run_by": "sage"}))
    new = _ok(client.post("/api/node/c1/evidence", {"candidate_proof_id": v2["id"], "outcome": "passed", "run_by": "sympy-checker"}))

    (check,) = _pending(client, "c1")["evidence_checks"]

    sha = candidate_proof_sha256(store, v2["id"])
    assert check["id"] == new["id"]
    assert (check["outcome"], check["run_by"], check["created_at"]) == ("passed", "sympy-checker", new["created_at"])
    assert check["sha256"] == sha and check["state"] == "matches"


def test_a_card_with_no_evidence_lists_none(app):
    store, client = app
    _two_snapshots(store, client)
    assert _pending(client, "c1")["evidence_checks"] == []


def test_the_cards_evidence_on_an_unreadable_snapshot_reads_unverifiable(app):
    store, client = app
    _, v2 = _two_snapshots(store, client)
    _ok(client.post("/api/node/c1/evidence", {"candidate_proof_id": v2["id"], "outcome": "passed", "run_by": "lean"}))
    shutil.rmtree(store.root / "proofs" / "c1" / "snapshots" / "v2")

    item = _pending(client, "c1")

    (check,) = item["evidence_checks"]
    assert check["state"] == "unverifiable" and check["sha256"] == v2["sha256"]
    assert item["decisions"] == []  # nothing is decided on a snapshot that can't be read (#92)


# -- the card on the map's home, run for real under node (tests/js/map_home_harness.js) -------

BLOCKED = {**PENDING[0], "decisions": [], "review_blocked": {
    "reason": "DEPENDENCIES_CHANGED", "message": "dependencies changed since snapshot v1 — request review again",
    "next": "proof node request-review lem_bound --rationale \"…\""}}


def test_a_card_whose_dependencies_changed_offers_no_decision_and_says_what_to_do():
    (shown,) = _home(state=_state([BLOCKED, PENDING[1]]))
    assert shown["pendingChoices"][0] is None and shown["pendingTickable"][0] is False
    assert "dependencies changed since snapshot v1 — request review again" in shown["pendingBlocked"][0]
    assert "proof node request-review lem_bound" in shown["pendingBlocked"][0]
    # the other card is unaffected
    assert shown["pendingChoices"][1] == ["reference-review"] and shown["pendingTickable"][1] is True
    assert shown["pendingBlocked"][1] == ""


def test_recording_sends_nothing_for_a_card_with_no_decision():
    *_, recorded = _home(state=_state([BLOCKED, PENDING[1]]), steps=[{"tick": "ref_bw"}, {"record": True}])
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    assert [d["target_id"] for d in sent["body"]["decisions"]] == ["ref_bw"]


def test_a_card_whose_dependencies_stand_offers_its_decisions():
    (shown,) = _home()
    assert shown["pendingChoices"][0] == ["accept", "reject"] and shown["pendingTickable"][0] is True
    assert shown["pendingBlocked"][0] == ""


def _check(**fields):
    return {"id": "ev1", "outcome": "passed", "run_by": "sympy-checker", "notes": "", "created_at": "2026-10-03T09:15:00+00:00",
            "sha256": "a" * 64, "state": "matches", **fields}


def test_a_card_shows_the_evidence_checks_on_its_snapshot():
    item = {**PENDING[0], "evidence_checks": [_check()]}
    (shown,) = _home(state=_state([item]))
    (check,) = shown["pendingEvidence"][0]
    assert "passed" in check["text"] and "sympy-checker" in check["text"] and "2026-10-03 09:15" in check["text"]
    assert "a" * 12 in check["text"] and "a" * 13 not in check["text"]  # the hash, shortened
    assert check["warnings"] == []


@pytest.mark.parametrize("state, mark", [
    ("unverifiable", "unverifiable"),
    ("changed", "snapshot changed since this check"),
    ("unbound", "not bound"),
])
def test_a_cards_evidence_not_matching_its_snapshot_is_marked(state, mark):
    item = {**PENDING[0], "evidence_checks": [_check(state=state, sha256=None if state == "unbound" else "e" * 64)]}
    (shown,) = _home(state=_state([item]))
    (check,) = shown["pendingEvidence"][0]
    assert any(mark in w for w in check["warnings"]), check


def test_a_card_with_no_evidence_shows_no_evidence_list():
    (shown,) = _home()
    assert shown["pendingEvidence"] == [[], []]


# -- the studio's review sheet (tests/js/node_panel_harness.js) ---------------------------------


def test_the_studio_review_sheet_offers_no_decision_and_says_why_once_dependencies_changed():
    blocked = {**REVIEW_VIEW, "decisions": [], "review_blocked": BLOCKED["review_blocked"]}
    shown = _panel(view=blocked)
    assert "dependencies changed since snapshot v1 — request review again" in shown["review"]
    assert "proof node request-review lem_bound" in shown["review"]
    assert [label for label in shown["reviewButtons"] if label != "Done"] == []
