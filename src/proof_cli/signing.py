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


def _origin_is_local(origin: str) -> bool:
    parts = urlsplit(origin)
    return parts.scheme in {"http", "https"} and parts.hostname == RP_ID


def verify_assertion(assertion: WebAuthnAssertion, *, public_key_spki: bytes, alg: int, challenge: bytes) -> None:
    """Check a WebAuthn assertion the way a relying party must (WebAuthn §7.2).

    Raises `SignatureError` unless: the client data is a `webauthn.get` for
    exactly `challenge` from a `localhost` origin; the authenticator data is
    for RP ID `localhost` with user presence *and* user verification set;
    and the signature over `authenticatorData || SHA-256(clientDataJSON)`
    verifies under the given key.
    """
    try:
        client_data_raw = b64url_decode(assertion.client_data_json)
        client_data = json.loads(client_data_raw)
        authenticator_data = b64url_decode(assertion.authenticator_data)
        signature = b64url_decode(assertion.signature)
    except (ValueError, TypeError) as exc:
        raise SignatureError("MALFORMED_ASSERTION", f"assertion is not valid base64url/JSON: {exc}") from exc

    if not isinstance(client_data, dict) or client_data.get("type") != "webauthn.get":
        raise SignatureError("MALFORMED_ASSERTION", "client data is not a webauthn.get assertion")
    if client_data.get("challenge") != b64url_encode(challenge):
        raise SignatureError("CHALLENGE_MISMATCH", "the assertion signs a different challenge than this decision")
    if not _origin_is_local(str(client_data.get("origin", ""))):
        raise SignatureError("ORIGIN_MISMATCH", f"assertion origin {client_data.get('origin')!r} is not localhost")

    if len(authenticator_data) < 37:
        raise SignatureError("MALFORMED_ASSERTION", "authenticator data is too short")
    if authenticator_data[:32] != hashlib.sha256(RP_ID.encode("ascii")).digest():
        raise SignatureError("RP_ID_MISMATCH", f"assertion is not for RP ID {RP_ID!r}")
    flags = authenticator_data[32]
    if not flags & _FLAG_USER_PRESENT or not flags & _FLAG_USER_VERIFIED:
        raise SignatureError("USER_NOT_VERIFIED", "the authenticator did not verify the user (Touch ID / PIN)")

    key = load_public_key(public_key_spki, alg)
    signed_data = authenticator_data + hashlib.sha256(client_data_raw).digest()
    try:
        if alg == ALG_ES256:
            key.verify(signature, signed_data, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, signed_data)
    except InvalidSignature as exc:
        raise SignatureError("BAD_SIGNATURE", "the signature does not verify under the reviewer key") from exc


def verify_signed_decision(signed: SignedDecision, *, public_key_spki: bytes, alg: int) -> str:
    """Verify `signed` under one key; return its payload hash."""
    digest = payload_hash(signed.payload)
    if digest not in signed.batch:
        raise SignatureError("NOT_IN_BATCH", "the decision payload is not part of the batch its assertion signs")
    verify_assertion(signed.assertion, public_key_spki=public_key_spki, alg=alg, challenge=batch_challenge(signed.batch))
    return digest


__all__ = [
    "ALG_EDDSA",
    "ALG_ES256",
    "DecisionKind",
    "DecisionPayload",
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
    "verify_assertion",
    "verify_signed_decision",
]
