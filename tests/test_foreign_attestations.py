"""Exchange carries signatures, never authority (ADR-0009 point 6, issue #38).

A bundle's signed decisions arrive as *foreign attestations*: shown next to
their node, never counted. The receiving researcher can accept one as a
local decision with a tap, or deliberately enroll the other reviewer's key
— which lets that key sign decisions here from now on, and never makes its
old, foreign signatures count.
"""

import json
import shutil
from pathlib import Path

import pytest

from _authenticator import researcher
from proof_cli.authority import list_reviewer_keys
from proof_cli.exchange import bundle_from_json, bundle_to_json, export_exchange_bundle, import_exchange_bundle
from proof_cli.proof_map import claim_node, create_node, get_acceptance_state, get_workflow_state, list_nodes, submit_candidate_proof
from proof_cli.signing import b64url_decode, public_key_fingerprint
from proof_cli.storage import ensure_project, list_foreign_attestations
from _review_client import serving
from test_review_app import _sign


def _source_with_an_accepted_lemma(root: Path):
    store = ensure_project(root)
    create_node(store, node_id="lem", kind="lemma", statement="A holds")
    token = claim_node(store, "lem", claimant_id="agent_a", session_id="s").claim_token
    submit_candidate_proof(store, "lem", claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content="# Proof\n\nBy induction.", claim_token=token)
    researcher(store).decide_acceptance("lem", "accept", rationale="checked every step")
    return store


def _received(tmp_path: Path, *, tamper=None):
    source = _source_with_an_accepted_lemma(tmp_path / "source")
    target = ensure_project(tmp_path / "target")
    bundle = json.loads(bundle_to_json(export_exchange_bundle(source)))
    if tamper:
        tamper(bundle)
    report = import_exchange_bundle(target, bundle_from_json(json.dumps(bundle)))
    # the proof vault travels by git, not in the bundle (#31)
    shutil.copytree(source.root / "proofs", target.root / "proofs")
    return source, target, report


def test_an_imported_acceptance_is_a_foreign_attestation_and_counts_for_nothing(tmp_path: Path):
    source, target, report = _received(tmp_path)

    assert get_acceptance_state(target, "lem") == "unreviewed"
    assert get_workflow_state(target, "lem") == "review-needed"
    (attestation,) = list_foreign_attestations(target)
    signer = researcher(source).authenticator
    assert (attestation.object_id, attestation.kind, attestation.decision) == ("lem", "acceptance", "accept")
    assert attestation.rationale == "checked every step"
    assert attestation.signer_fingerprint == public_key_fingerprint(signer.public_key_spki)
    assert attestation.signature == "valid"
    assert any("foreign attestation" in warning for warning in report.warnings)


def test_a_tampered_foreign_signature_reads_invalid_and_still_counts_for_nothing(tmp_path: Path):
    def tamper(bundle):
        for signed in bundle["signed_decisions"].values():
            signed["payload"]["rationale"] = "rubber-stamped"

    _, target, _ = _received(tmp_path, tamper=tamper)

    (attestation,) = list_foreign_attestations(target)
    assert attestation.signature == "invalid"
    assert get_acceptance_state(target, "lem") == "unreviewed"


def test_importing_twice_keeps_one_attestation(tmp_path: Path):
    source, target, _ = _received(tmp_path)
    import_exchange_bundle(target, export_exchange_bundle(source))
    assert len(list_foreign_attestations(target)) == 1


# -- in the review app ----------------------------------------------------------------


@pytest.fixture
def received_app(tmp_path: Path):
    source, target, _ = _received(tmp_path)
    with serving(target) as client:
        yield source, target, client


def test_the_node_page_shows_the_attestation_and_it_can_be_accepted_as_a_local_decision(received_app):
    source, target, client = received_app
    local = researcher(target)

    view = client.get("/api/node/lem")[1]["data"]
    (shown,) = view["foreign_attestations"]
    assert (shown["decision"], shown["signature"], shown["signer_name"]) == ("accept", "valid", researcher(source).authenticator.display_name)
    assert shown["accept_as_local"] == {"kind": "acceptance", "target_id": "lem", "decision": "accept"}

    status, outcome = _sign(client, local.authenticator, [{**shown["accept_as_local"], "rationale": "read it myself too"}])

    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome
    assert get_acceptance_state(target, "lem") == "accepted"


def test_a_foreign_key_is_enrolled_only_with_a_tap_from_a_local_key_and_its_old_signatures_still_dont_count(received_app):
    source, target, client = received_app
    local = researcher(target)
    foreign_fingerprint = public_key_fingerprint(researcher(source).authenticator.public_key_spki)

    status, prepared = client.post("/api/keys/enroll-foreign/prepare", {"fingerprint": foreign_fingerprint})
    assert status == 200, prepared
    to_sign = prepared["data"]
    assert to_sign["allow_credentials"] == [local.authenticator.credential_id]
    assertion = local.authenticator.assert_challenge(b64url_decode(to_sign["challenge"]), origin=client.origin)
    status, enrolled = client.post("/api/keys/enroll-foreign", {"token": to_sign["token"], "assertion": assertion.model_dump()})

    assert status == 200, enrolled
    assert foreign_fingerprint in {key.fingerprint for key in list_reviewer_keys(target)}
    assert get_acceptance_state(target, "lem") == "unreviewed"


def test_a_foreign_key_is_never_a_projects_first_key(tmp_path: Path):
    source = _source_with_an_accepted_lemma(tmp_path / "source")
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, export_exchange_bundle(source))
    with serving(target) as client:
        fingerprint = public_key_fingerprint(researcher(source).authenticator.public_key_spki)
        status, refused = client.post("/api/keys/enroll-foreign/prepare", {"fingerprint": fingerprint})

    assert (status, refused["error"]["code"]) == (409, "NO_LOCAL_KEY")
    assert list_reviewer_keys(target) == []


def test_a_crafted_bundle_cant_hide_a_genuine_attestation_imported_after_it(tmp_path: Path):
    def tamper(bundle):
        for signed in bundle["signed_decisions"].values():
            signed["payload"]["rationale"] = "rubber-stamped"

    source, target, _ = _received(tmp_path, tamper=tamper)
    import_exchange_bundle(target, export_exchange_bundle(source))

    assert sorted(a.signature for a in list_foreign_attestations(target)) == ["invalid", "valid"]


def test_a_malformed_key_in_a_bundle_refuses_the_import_before_it_writes_anything(tmp_path: Path):
    source = _source_with_an_accepted_lemma(tmp_path / "source")
    target = ensure_project(tmp_path / "target")
    bundle = json.loads(bundle_to_json(export_exchange_bundle(source)))
    bundle["reviewer_keys"][0]["alg"] = None

    with pytest.raises(ValueError):
        import_exchange_bundle(target, bundle)

    assert list_foreign_attestations(target) == []
    assert list_nodes(target) == []


def test_a_key_that_only_signed_an_invalid_attestation_is_never_offered_for_enrollment(tmp_path: Path):
    def tamper(bundle):
        for signed in bundle["signed_decisions"].values():
            signed["payload"]["rationale"] = "rubber-stamped"

    source, target, _ = _received(tmp_path, tamper=tamper)
    researcher(target)
    with serving(target) as client:
        fingerprint = public_key_fingerprint(researcher(source).authenticator.public_key_spki)
        status, refused = client.post("/api/keys/enroll-foreign/prepare", {"fingerprint": fingerprint})

    assert (status, refused["error"]["code"]) == (404, "UNKNOWN_FOREIGN_KEY")
