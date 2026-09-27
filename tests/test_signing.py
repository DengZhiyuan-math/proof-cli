"""WebAuthn assertion verification for signed decisions (ADR-0009, issue #35)."""

import pytest

from _authenticator import SoftwareAuthenticator
from proof_cli.signing import (
    ALG_EDDSA,
    ALG_ES256,
    DecisionKind,
    DecisionPayload,
    SignatureError,
    SignedDecision,
    batch_challenge,
    canonical_payload,
    payload_hash,
    verify_signed_decision,
)


def _payload(**overrides) -> DecisionPayload:
    fields = {
        "project_id": "proj_alpha",
        "project_instance": "instance_1",
        "kind": DecisionKind.acceptance,
        "target_id": "clm_1",
        "candidate_proof_id": "cp_1",
        "candidate_proof_sha256": "ab" * 32,
        "decision": "accept",
        "rationale": "checked every step",
    }
    return DecisionPayload(**{**fields, **overrides})


ORIGIN = "http://localhost:8765"  # the software authenticator's default origin


def _verify(authenticator: SoftwareAuthenticator, signed: SignedDecision) -> str:
    return verify_signed_decision(
        signed, public_key_spki=authenticator.public_key_spki, alg=authenticator.alg, expected_origin=ORIGIN
    )


@pytest.mark.parametrize("alg", [ALG_ES256, ALG_EDDSA])
def test_a_real_assertion_verifies(alg: int):
    authenticator = SoftwareAuthenticator(alg)
    signed = authenticator.sign(_payload())
    assert _verify(authenticator, signed) == payload_hash(signed.payload)


def test_serialization_is_deterministic():
    payload = _payload()
    assert canonical_payload(payload) == canonical_payload(DecisionPayload.model_validate_json(payload.model_dump_json()))
    assert b" " not in canonical_payload(payload).split(b'"rationale"')[0]


@pytest.mark.parametrize(
    "field, value",
    [
        ("candidate_proof_sha256", "cd" * 32),
        ("candidate_proof_id", "cp_2"),
        ("target_id", "clm_2"),
        ("decision", "reject"),
        ("project_id", "proj_beta"),
        ("project_instance", "instance_2"),
        ("interface_fingerprint", "ef" * 32),
        ("resolves_challenges", ["ch_other"]),
        ("rationale", "something else"),
    ],
)
def test_a_signature_over_a_different_payload_is_rejected(field: str, value: str):
    authenticator = SoftwareAuthenticator()
    signed = authenticator.sign(_payload())
    forged = signed.model_copy(update={"payload": signed.payload.model_copy(update={field: value}), "batch": []})
    forged.batch = [payload_hash(forged.payload)]

    with pytest.raises(SignatureError) as exc_info:
        _verify(authenticator, forged)
    assert exc_info.value.code == "CHALLENGE_MISMATCH"


def test_a_payload_swapped_into_someone_elses_batch_is_rejected():
    authenticator = SoftwareAuthenticator()
    signed = authenticator.sign(_payload())
    smuggled = SignedDecision(payload=_payload(decision="reject"), batch=signed.batch, assertion=signed.assertion)

    with pytest.raises(SignatureError) as exc_info:
        _verify(authenticator, smuggled)
    assert exc_info.value.code == "NOT_IN_BATCH"


def test_one_assertion_covers_a_whole_batch():
    authenticator = SoftwareAuthenticator()
    signed = authenticator.sign_batch([_payload(target_id=f"clm_{index}") for index in range(5)])
    assert len({decision.assertion.signature for decision in signed}) == 1
    for decision in signed:
        _verify(authenticator, decision)
    assert batch_challenge(signed[0].batch) == batch_challenge([payload_hash(d.payload) for d in signed])


def test_another_key_cannot_verify():
    signer, stranger = SoftwareAuthenticator(), SoftwareAuthenticator()
    signed = signer.sign(_payload())
    with pytest.raises(SignatureError) as exc_info:
        _verify(stranger, signed)
    assert exc_info.value.code == "BAD_SIGNATURE"


@pytest.mark.parametrize(
    "options, code",
    [
        ({"flags": 0x01}, "USER_NOT_VERIFIED"),
        ({"flags": 0x04}, "USER_NOT_VERIFIED"),
        ({"origin": "https://evil.example"}, "ORIGIN_MISMATCH"),
        ({"origin": "http://localhost:9999"}, "ORIGIN_MISMATCH"),  # another localhost port is another origin
        ({"rp_id": "evil.example"}, "RP_ID_MISMATCH"),
        ({"ceremony": "webauthn.create"}, "MALFORMED_ASSERTION"),
    ],
)
def test_an_assertion_violating_the_relying_party_rules_is_rejected(options: dict, code: str):
    authenticator = SoftwareAuthenticator()
    signed = authenticator.sign(_payload(), **options)
    with pytest.raises(SignatureError) as exc_info:
        _verify(authenticator, signed)
    assert exc_info.value.code == code


def test_a_key_of_the_wrong_algorithm_is_rejected():
    authenticator = SoftwareAuthenticator(ALG_ES256)
    signed = authenticator.sign(_payload())
    with pytest.raises(SignatureError) as exc_info:
        verify_signed_decision(signed, public_key_spki=authenticator.public_key_spki, alg=ALG_EDDSA, expected_origin=ORIGIN)
    assert exc_info.value.code == "UNSUPPORTED_KEY"


def test_a_naive_timestamp_is_refused_when_the_payload_is_parsed():
    from datetime import datetime

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _payload(signed_at=datetime(2026, 1, 1, 12, 0))
    raw = _payload().model_dump(mode="json")
    raw["signed_at"] = "2026-01-01T12:00:00"
    with pytest.raises(ValidationError):
        DecisionPayload.model_validate(raw)
