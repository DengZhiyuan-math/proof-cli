"""Legacy decisions: batch re-sign in the web app (issue #42).

The fixture under tests/fixtures/pre_adr_0009_project was built by `master`
before #35 (see build_pre_adr_0009_project.py): an accepted lemma with a
trusted Evidence check (acc), an accepted-then-promoted claim (pro), a
rejected claim (rej), a revision-requested claim (rev), a reference-reviewed
imported result (ref), an accepted lemma whose Challenge was dismissed
(dis), and a dependent (dep). All of those decisions are unsigned.
`master_axes.json` is how that code itself read every node.
"""

import json
import shutil
import threading
from pathlib import Path

import pytest

from _authenticator import SoftwareAuthenticator
from proof_cli.domain import ChallengeStatus, ProofMapNodeKind
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    get_acceptance_state,
    get_integrity_state,
    get_node,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    list_integrity_warnings,
    list_legacy_decisions,
)
from proof_cli.signing import b64url_decode
from proof_cli.storage import list_raw_chain_rows, load_project
from proof_cli.webapp.server import ReviewServer
from test_review_app import Client, _enroll_over_http

FIXTURE = Path(__file__).parent / "fixtures" / "pre_adr_0009_project"


@pytest.fixture
def legacy_app(tmp_path: Path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    store = load_project(root)
    server = ReviewServer(store)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = Client(server.url)
    passkey = SoftwareAuthenticator(display_name="researcher", counter=True)
    status, enrolled = _enroll_over_http(client, passkey)  # a pre-#35 project has never had keys: trust on first use
    assert status == 200, enrolled
    yield store, client, passkey
    server.shutdown()
    server.server_close()


def _master_axes() -> dict:
    return json.loads((FIXTURE / "master_axes.json").read_text())


def _current_axes(store) -> dict:
    axes = {}
    for node_id in ("acc", "pro", "rej", "rev", "ref", "dis", "dep"):
        node = get_node(store, node_id)
        axes[node_id] = {
            "kind": node.kind.value,
            "acceptance": get_reference_review_state(store, node_id) if node.kind == ProofMapNodeKind.imported_result else get_acceptance_state(store, node_id),
            "workflow": get_workflow_state(store, node_id),
            "integrity": get_integrity_state(store, node_id),
        }
    axes["challenges"] = {c.id: c.status.value for c in list_challenges(store)}
    return axes


def _axes(store):
    return {
        "acc": get_acceptance_state(store, "acc"),
        "pro": (get_acceptance_state(store, "pro"), get_node(store, "pro").kind),
        "rej": get_acceptance_state(store, "rej"),
        "ref": get_reference_review_state(store, "ref"),
        "dis": get_acceptance_state(store, "dis"),
        "dis_challenge": [challenge.status for challenge in list_challenges(store, target_node_id="dis")],
    }


def _sign_batch(client, passkey, decisions):
    prepared = client.post("/api/prepare", {"decisions": decisions})
    assert prepared[0] == 200, prepared
    to_sign = prepared[1]["data"]
    assertion = passkey.assert_challenge(b64url_decode(to_sign["challenge"]), origin=client.origin)
    return client.post("/api/decide", {"payloads": to_sign["payloads"], "batch": to_sign["batch"], "assertion": assertion.model_dump()})


def test_one_batch_re_sign_restores_a_pre_adr_0009_project(legacy_app):
    store, client, passkey = legacy_app

    # before: nothing counts, yet nothing is reopened
    assert _axes(store) == {
        "acc": "unverifiable",
        "pro": ("unverifiable", ProofMapNodeKind.lemma),
        "rej": "rejected",
        "ref": "unverifiable",
        "dis": "unverifiable",
        "dis_challenge": [ChallengeStatus.dismissed],
    }
    rows_before = list_raw_chain_rows(store, "review_history")

    status, listed = client.get("/api/legacy")
    items = listed["data"]
    assert status == 200
    assert {(item["kind"], item["target_id"]) for item in items if item["resignable"] and item["kind"] != "evidence_review"} == {
        ("acceptance", "acc"),
        ("acceptance", "pro"),  # master's promote left no review row: its kind carries over through ledger adoption
        ("acceptance", "rej"),
        ("acceptance", "rev"),
        ("reference_review", "ref"),
        ("acceptance", "dis"),
        ("challenge_resolution", [c.id for c in list_challenges(store, target_node_id="dis")][0]),
    }
    evidence = next(item for item in items if item["kind"] == "evidence_review")
    assert evidence["resignable"] and evidence["context"]["evidence_check"]["outcome"] == "passed"
    assert all(item["candidate_proof"] or item["kind"] in ("reference_review", "challenge_resolution") for item in items)

    # one tap
    taps = passkey.sign_count
    status, outcome = _sign_batch(
        client,
        passkey,
        [
            {"kind": item["kind"], "target_id": item["target_id"], "decision": item["decision"], "resigns": item["item_id"]}
            for item in items
            if item["resignable"]
        ],
    )
    assert status == 200 and all(result["ok"] for result in outcome["data"]["results"]), outcome
    assert passkey.sign_count - taps == 1  # one tap for the whole batch

    # after: every axis exactly as master itself read it, now backed by signatures
    assert _current_axes(store) == _master_axes()
    assert list_integrity_warnings(store) == []
    assert list_legacy_decisions(store) == []
    assert client.get("/api/legacy")[1]["data"] == []

    # every row that was there before — the legacy ones included — is exactly as it was
    assert list_raw_chain_rows(store, "review_history")[: len(rows_before)] == rows_before


def test_before_re_signing_no_legacy_reject_or_dismissal_can_be_reopened(legacy_app):
    store, client, passkey = legacy_app
    challenge = list_challenges(store, target_node_id="dis")[0]

    for node_id, code in (("rej", "NODE_REJECTED"), ("acc", "NODE_UNVERIFIABLE")):
        with pytest.raises(ProofMapError) as exc_info:
            claim_node(store, node_id, claimant_id="agent", session_id="s")
        assert exc_info.value.code == code

    # a fresh decision on the rejected node, even properly signed, is refused
    outcome = _sign_batch(client, passkey, [{"kind": "acceptance", "target_id": "rej", "decision": "accept"}])[1]
    assert outcome["data"]["results"][0]["error"]["code"] == "NODE_REJECTED"
    # and the legacy dismissal can't be "dismissed again" into something else
    outcome = _sign_batch(client, passkey, [{"kind": "challenge_resolution", "target_id": challenge.id, "decision": "dismissed"}])[1]
    assert not outcome["data"]["results"][0]["ok"]

    assert get_acceptance_state(store, "rej") == "rejected"
    assert [c.status for c in list_challenges(store, target_node_id="dis")] == [ChallengeStatus.dismissed]


def test_declining_a_legacy_decision_takes_a_tap_and_removes_it_from_the_page(legacy_app):
    store, client, passkey = legacy_app
    item = next(item for item in list_legacy_decisions(store) if item.target_id == "acc")

    # without a signature nothing happens
    status, response = client.post("/api/decide", {"payloads": [], "batch": []})
    assert status >= 400
    assert item.item_id in {i.item_id for i in list_legacy_decisions(store)}

    status, outcome = _sign_batch(client, passkey, [{"kind": "legacy_decline", "target_id": item.item_id, "decision": "decline"}])
    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome

    assert item.item_id not in {i.item_id for i in list_legacy_decisions(store)}
    assert get_acceptance_state(store, "acc") in {"unreviewed", "unverifiable"}  # uncounted, never a signed fallback


def test_an_acceptance_whose_proof_moved_on_can_only_be_declined(legacy_app):
    """Re-signing must never accept a submission nobody reviewed."""
    store, client, passkey = legacy_app
    import sqlite3

    conn = sqlite3.connect(store.db_path)
    conn.execute("UPDATE candidate_proofs SET review_record_id = NULL WHERE node_id = 'acc'")
    conn.commit()
    conn.close()

    item = next(item for item in list_legacy_decisions(store) if item.target_id == "acc" and item.kind.value == "acceptance")
    assert not item.resignable
    outcome = _sign_batch(client, passkey, [{"kind": "acceptance", "target_id": "acc", "decision": "accept", "resigns": item.item_id}])[1]
    assert outcome["data"]["results"][0]["error"]["code"] == "LEGACY_NOT_RESIGNABLE"
    assert get_acceptance_state(store, "acc") == "unverifiable"


@pytest.mark.parametrize("which", ["reject", "dismissal"])
def test_a_legacy_reject_or_dismissal_can_only_be_re_signed_never_declined(legacy_app, which):
    """Declining one would reopen what it closed — the one thing #35 promises can't happen."""
    store, client, passkey = legacy_app
    items = list_legacy_decisions(store)
    item = next(
        item
        for item in items
        if (which == "reject" and item.target_id == "rej" and item.decision == "reject")
        or (which == "dismissal" and item.kind.value == "challenge_resolution")
    )

    outcome = _sign_batch(client, passkey, [{"kind": "legacy_decline", "target_id": item.item_id, "decision": "decline"}])[1]

    assert outcome["data"]["results"][0]["error"]["code"] == "LEGACY_DECLINE_REFUSED"
    assert get_acceptance_state(store, "rej") == "rejected"
    assert [c.status for c in list_challenges(store, target_node_id="dis")] == [ChallengeStatus.dismissed]
    with pytest.raises(ProofMapError):
        claim_node(store, "rej", claimant_id="agent", session_id="s")


def test_legacy_nodes_stay_off_the_ordinary_review_list(legacy_app):
    """They're re-signed on the legacy list, with their original context — not re-decided blind."""
    store, client, passkey = legacy_app
    pending = client.get("/api/state")[1]["data"]["pending"]
    assert not {item["node_id"] for item in pending} & {"acc", "pro", "rej", "rev", "ref", "dis"}
