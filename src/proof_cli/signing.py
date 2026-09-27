"""Signed Human Review decisions: canonical payloads and WebAuthn assertion checks (ADR-0009).

This module is pure: it knows how a decision payload is serialized and
hashed, and whether a WebAuthn assertion over it is valid for a given public
key. Which keys are trusted, and what a verified decision is allowed to do,
live in `authority.py`.
"""

from __future__ import annotations

import base64
import hashlib
import json
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from pydantic import AwareDatetime, BaseModel, Field

from .domain import utc_now

RP_ID = "localhost"

# COSE algorithm identifiers (RFC 9053) for the two passkey algorithms we accept.
ALG_ES256 = -7
ALG_EDDSA = -8
SUPPORTED_ALGORITHMS = frozenset({ALG_ES256, ALG_EDDSA})

_FLAG_USER_PRESENT = 0x01
_FLAG_USER_VERIFIED = 0x04


class DecisionKind(str, Enum):
    """Every Human Review decision kind ADR-0009 point 1 names."""

    acceptance = "acceptance"
    reference_review = "reference_review"
    evidence_review = "evidence_review"
    dependency_revalidation = "dependency_revalidation"
    challenge_resolution = "challenge_resolution"
    promote = "promote"
    force_release = "force_release"
    reviewer_enrollment = "reviewer_enrollment"
    # the researcher declining to keep a pre-ADR-0009 decision (#42)
    legacy_decline = "legacy_decline"
    # the researcher confirming they've looked at the Reviewer key registry (#36)
    registry_acknowledgement = "registry_acknowledgement"


class PinnedDependency(BaseModel):
    target_node_id: str
    pinned_version: int | None = None
    pinned_fingerprint: str | None = None


class DecisionPayload(BaseModel):
    """Exactly what the researcher's passkey signs (ADR-0009 point 1)."""

    project_id: str
    # this one project database's random instance id (not the shared display
    # id): a decision signed for any other project never verifies here
    project_instance: str
    kind: DecisionKind
    target_id: str
    candidate_proof_id: str | None = None
    candidate_proof_sha256: str | None = None
    # the accepted mathematical interface: for a local node its interface
    # fingerprint (statement, assumptions); for an imported result, its
    # statement and source
    interface_fingerprint: str | None = None
    dependency_pins: list[PinnedDependency] = Field(default_factory=list)
    # the Challenges this decision resolves, by id; a Challenge is resolved
    # only by a signed decision that names it
    resolves_challenges: list[str] = Field(default_factory=list)
    # for reviewer_enrollment: the WebAuthn credential being enrolled/revoked
    credential_id: str | None = None
    # a re-signed pre-ADR-0009 decision: the legacy item it re-signs (#42)
    resigns: str | None = None
    decision: str
    rationale: str = ""
    # timezone-aware only: a naive timestamp can't be compared, so it's
    # refused when the payload is parsed rather than crashing a read later
    signed_at: AwareDatetime = Field(default_factory=utc_now)
    # the newest row of each chain as the signer saw it: the payload commits
    # to those prefixes of the review history, the Reviewer key registry and
    # the proof ledger. Key validity is judged at that registry position, so
    # a revocation appended later can't reach back over this decision.
    previous_row_hash: str | None = None
    registry_head: str | None = None
    ledger_head: str | None = None


class WebAuthnAssertion(BaseModel):
    """A WebAuthn `navigator.credentials.get()` response, base64url-encoded."""

    credential_id: str
    authenticator_data: str
    client_data_json: str
    signature: str


class SignedDecision(BaseModel):
    """One decision, the batch it was signed in, and the assertion over that batch.

    A passkey tap signs one challenge; `batch` is the ordered list of payload
    hashes that challenge covers, so N decisions can share one tap (#36). A
    single decision is a batch of one.
    """

    payload: DecisionPayload
    batch: list[str] = Field(default_factory=list)
    assertion: WebAuthnAssertion

    def model_post_init(self, __context: Any) -> None:
        if not self.batch:
            self.batch = [payload_hash(self.payload)]


class SignatureError(Exception):
    """A signed decision that doesn't verify. `code` is stable for callers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical_json(value: Any) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_payload(payload: DecisionPayload) -> bytes:
    return canonical_json(payload.model_dump(mode="json"))


def payload_hash(payload: DecisionPayload) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def batch_challenge(batch: list[str]) -> bytes:
    """The WebAuthn challenge for a batch: SHA-256 over the ordered payload-hash list."""
    return hashlib.sha256(canonical_json(list(batch))).digest()


def public_key_fingerprint(public_key_spki: bytes) -> str:
    return hashlib.sha256(public_key_spki).hexdigest()


def load_public_key(public_key_spki: bytes, alg: int):
    key = serialization.load_der_public_key(public_key_spki)
    if alg == ALG_ES256 and isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1):
        return key
    if alg == ALG_EDDSA and isinstance(key, ed25519.Ed25519PublicKey):
        return key
    raise SignatureError("UNSUPPORTED_KEY", f"public key does not match algorithm {alg}; expected ES256 (P-256) or EdDSA (Ed25519)")


def _check_client_data(client_data: Any, *, ceremony: str, challenge: bytes, expected_origin: str) -> None:
    if not isinstance(client_data, dict) or client_data.get("type") != ceremony:
        raise SignatureError("MALFORMED_ASSERTION", f"client data is not a {ceremony} response")
    if client_data.get("challenge") != b64url_encode(challenge):
        raise SignatureError("CHALLENGE_MISMATCH", "the assertion signs a different challenge than this decision")
    origin = str(client_data.get("origin", ""))
    if origin != expected_origin or urlsplit(origin).hostname != RP_ID:
        raise SignatureError("ORIGIN_MISMATCH", f"assertion origin {origin!r} is not this project's review app ({expected_origin})")
    if client_data.get("crossOrigin") not in (None, False):
        raise SignatureError("ORIGIN_MISMATCH", "the assertion was made from a cross-origin frame")


def _check_authenticator_data(authenticator_data: bytes) -> int:
    """RP ID hash and the UP+UV flags; returns the flags byte."""
    if len(authenticator_data) < 37:
        raise SignatureError("MALFORMED_ASSERTION", "authenticator data is too short")
    if authenticator_data[:32] != hashlib.sha256(RP_ID.encode("ascii")).digest():
        raise SignatureError("RP_ID_MISMATCH", f"assertion is not for RP ID {RP_ID!r}")
    flags = authenticator_data[32]
    if not flags & _FLAG_USER_PRESENT or not flags & _FLAG_USER_VERIFIED:
        raise SignatureError("USER_NOT_VERIFIED", "the authenticator did not verify the user (Touch ID / PIN)")
    return flags


def sign_count(assertion: WebAuthnAssertion) -> int:
    """The authenticator's signature counter in an assertion (0 for most passkeys, which don't keep one)."""
    authenticator_data = b64url_decode(assertion.authenticator_data)
    return int.from_bytes(authenticator_data[33:37], "big") if len(authenticator_data) >= 37 else 0


def verify_assertion(
    assertion: WebAuthnAssertion, *, public_key_spki: bytes, alg: int, challenge: bytes, expected_origin: str
) -> None:
    """Check a WebAuthn assertion the way a relying party must (WebAuthn §7.2).

    Raises `SignatureError` unless: the client data is a same-origin
    `webauthn.get` for exactly `challenge` from exactly `expected_origin`
    (the project's own review app, never just any localhost port); the
    authenticator data is for RP ID `localhost` with user presence *and*
    user verification set; and the signature over
    `authenticatorData || SHA-256(clientDataJSON)` verifies under the key.
    """
    try:
        client_data_raw = b64url_decode(assertion.client_data_json)
        client_data = json.loads(client_data_raw)
        authenticator_data = b64url_decode(assertion.authenticator_data)
        signature = b64url_decode(assertion.signature)
    except (ValueError, TypeError) as exc:
        raise SignatureError("MALFORMED_ASSERTION", f"assertion is not valid base64url/JSON: {exc}") from exc

    _check_client_data(client_data, ceremony="webauthn.get", challenge=challenge, expected_origin=expected_origin)
    _check_authenticator_data(authenticator_data)

    key = load_public_key(public_key_spki, alg)
    signed_data = authenticator_data + hashlib.sha256(client_data_raw).digest()
    try:
        if alg == ALG_ES256:
            key.verify(signature, signed_data, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, signed_data)
    except InvalidSignature as exc:
        raise SignatureError("BAD_SIGNATURE", "the signature does not verify under the reviewer key") from exc


def verify_signed_decision(signed: SignedDecision, *, public_key_spki: bytes, alg: int, expected_origin: str) -> str:
    """Verify `signed` under one key, made on `expected_origin`; return its payload hash."""
    digest = payload_hash(signed.payload)
    if digest not in signed.batch:
        raise SignatureError("NOT_IN_BATCH", "the decision payload is not part of the batch its assertion signs")
    verify_assertion(
        signed.assertion,
        public_key_spki=public_key_spki,
        alg=alg,
        challenge=batch_challenge(signed.batch),
        expected_origin=expected_origin,
    )
    return digest


# -- registration (navigator.credentials.create) ------------------------------------


class RegisteredCredential(BaseModel):
    """What a WebAuthn registration yields: a new credential and its public key."""

    credential_id: str  # base64url
    public_key_spki: bytes
    alg: int
    aaguid: str  # hex; all zeros for authenticators that don't disclose their model (Apple passkeys)
    sign_count: int = 0


_CBOR_MAX_DEPTH = 8


def _cbor_decode(data: bytes, offset: int = 0, depth: int = 0) -> tuple[Any, int]:
    """Just enough CBOR (RFC 8949) for attestation objects and COSE keys:
    unsigned/negative ints, byte and text strings, arrays, maps, simple values.
    Nesting is capped: a registration never needs more than a few levels."""
    if depth > _CBOR_MAX_DEPTH:
        raise ValueError("CBOR nested too deeply")
    initial = data[offset]
    major, info = initial >> 5, initial & 0x1F
    offset += 1
    if info < 24:
        value = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        value = int.from_bytes(data[offset : offset + size], "big")
        offset += size
    else:
        raise ValueError(f"unsupported CBOR length encoding {info}")
    if major == 0:
        return value, offset
    if major == 1:
        return -1 - value, offset
    if major in (2, 3):
        chunk = data[offset : offset + value]
        if len(chunk) != value:
            raise ValueError("truncated CBOR string")
        return (chunk if major == 2 else chunk.decode("utf-8")), offset + value
    if major == 4:
        items = []
        for _ in range(value):
            item, offset = _cbor_decode(data, offset, depth + 1)
            items.append(item)
        return items, offset
    if major == 5:
        mapping = {}
        for _ in range(value):
            key, offset = _cbor_decode(data, offset, depth + 1)
            if isinstance(key, (list, dict)):
                raise ValueError("unsupported CBOR map key")
            mapping[key], offset = _cbor_decode(data, offset, depth + 1)
        return mapping, offset
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], offset
    raise ValueError(f"unsupported CBOR major type {major}")


def _cose_to_spki(cose: dict) -> tuple[bytes, int]:
    alg = cose.get(3)
    if cose.get(1) == 2 and alg == ALG_ES256 and cose.get(-1) == 1:
        numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"), ec.SECP256R1()
        )
        key = numbers.public_key()
    elif cose.get(1) == 1 and alg == ALG_EDDSA and cose.get(-1) == 6:
        key = ed25519.Ed25519PublicKey.from_public_bytes(cose[-2])
    else:
        raise SignatureError("UNSUPPORTED_KEY", "the passkey is neither ES256 (P-256) nor EdDSA (Ed25519)")
    spki = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return spki, alg


_FLAG_ATTESTED_CREDENTIAL = 0x40


def verify_registration(
    client_data_json: str, attestation_object: str, *, challenge: bytes, expected_origin: str
) -> RegisteredCredential:
    """Check a WebAuthn registration response (WebAuthn §7.1) and extract the new credential.

    Same-origin `webauthn.create` for exactly `challenge` from exactly
    `expected_origin`; RP ID `localhost` with user presence and user
    verification. The attestation statement itself isn't trusted — Apple
    passkeys send `none` — so registration proves nothing about *who*
    enrolled; proof of possession is the enrollment decision the new key
    then signs.
    """
    try:
        client_data = json.loads(b64url_decode(client_data_json))
        attestation, _ = _cbor_decode(b64url_decode(attestation_object))
        authenticator_data = attestation["authData"]
        if not isinstance(authenticator_data, bytes):
            raise ValueError("authData isn't a byte string")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise SignatureError("MALFORMED_ASSERTION", f"registration response can't be parsed: {exc}") from exc
    _check_client_data(client_data, ceremony="webauthn.create", challenge=challenge, expected_origin=expected_origin)
    flags = _check_authenticator_data(authenticator_data)
    if not flags & _FLAG_ATTESTED_CREDENTIAL or len(authenticator_data) < 55:
        raise SignatureError("MALFORMED_ASSERTION", "registration carries no attested credential")
    aaguid = authenticator_data[37:53]
    length = int.from_bytes(authenticator_data[53:55], "big")
    credential_id = authenticator_data[55 : 55 + length]
    try:
        cose, _ = _cbor_decode(authenticator_data, 55 + length)
        if not isinstance(cose, dict):
            raise ValueError("the public key isn't a COSE map")
        spki, alg = _cose_to_spki(cose)
    except SignatureError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise SignatureError("MALFORMED_ASSERTION", f"registration public key can't be parsed: {exc}") from exc
    return RegisteredCredential(
        credential_id=b64url_encode(credential_id),
        public_key_spki=spki,
        alg=alg,
        aaguid=aaguid.hex(),
        sign_count=int.from_bytes(authenticator_data[33:37], "big"),
    )


__all__ = [
    "ALG_EDDSA",
    "ALG_ES256",
    "DecisionKind",
    "DecisionPayload",
    "RegisteredCredential",
    "PinnedDependency",
    "RP_ID",
    "SUPPORTED_ALGORITHMS",
    "SignatureError",
    "SignedDecision",
    "WebAuthnAssertion",
    "b64url_decode",
    "b64url_encode",
    "batch_challenge",
    "canonical_json",
    "canonical_payload",
    "payload_hash",
    "public_key_fingerprint",
    "sign_count",
    "verify_assertion",
    "verify_registration",
    "verify_signed_decision",
]
