"""A software WebAuthn authenticator for tests (ADR-0009, issue #35).

It holds a real key pair and produces real assertions, so every test exercises
the same verification path a Touch ID / security-key signature would. It lives
under tests/ on purpose: shipping it in the package would hand any agent a
ready-made way to sign decisions.
"""

from __future__ import annotations

import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from proof_cli.authority import project_origin
from proof_cli.signing import (
    ALG_EDDSA,
    ALG_ES256,
    RP_ID,
    DecisionPayload,
    SignedDecision,
    WebAuthnAssertion,
    b64url_decode,
    b64url_encode,
    batch_challenge,
    payload_hash,
)

_FLAGS_UP_UV = 0x05


def cbor_encode(value) -> bytes:
    """Just enough CBOR to build attestation objects and COSE keys in tests."""

    def head(major: int, length: int) -> bytes:
        if length < 24:
            return bytes([major << 5 | length])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if length < 1 << (8 * size):
                return bytes([major << 5 | info]) + length.to_bytes(size, "big")
        raise ValueError("too long")

    if isinstance(value, bool) or value is None:
        return bytes([0xF5 if value is True else 0xF4 if value is False else 0xF6])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return head(3, len(encoded)) + encoded
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor_encode(item) for item in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor_encode(k) + cbor_encode(v) for k, v in value.items())
    raise TypeError(type(value))


class SoftwareAuthenticator:
    def __init__(self, alg: int = ALG_ES256, *, display_name: str = "researcher", counter: bool = False) -> None:
        self.alg = alg
        self.display_name = display_name
        # most passkeys keep no signature counter (always 0); a security key does
        self.counter = counter
        self.sign_count = 0
        self.credential_id = b64url_encode(os.urandom(16))
        if alg == ALG_ES256:
            self._private_key = ec.generate_private_key(ec.SECP256R1())
        elif alg == ALG_EDDSA:
            self._private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            raise ValueError(f"unsupported alg {alg}")

    @property
    def public_key_spki(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def assert_challenge(
        self,
        challenge: bytes,
        *,
        origin: str = "http://localhost:8765",
        rp_id: str = RP_ID,
        flags: int = _FLAGS_UP_UV,
        ceremony: str = "webauthn.get",
    ) -> WebAuthnAssertion:
        client_data = json.dumps(
            {"type": ceremony, "challenge": b64url_encode(challenge), "origin": origin, "crossOrigin": False}
        ).encode("utf-8")
        if self.counter:
            self.sign_count += 1
        authenticator_data = hashlib.sha256(rp_id.encode("ascii")).digest() + bytes([flags]) + self.sign_count.to_bytes(4, "big")
        signed_data = authenticator_data + hashlib.sha256(client_data).digest()
        if self.alg == ALG_ES256:
            signature = self._private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
        else:
            signature = self._private_key.sign(signed_data)
        return WebAuthnAssertion(
            credential_id=self.credential_id,
            authenticator_data=b64url_encode(authenticator_data),
            client_data_json=b64url_encode(client_data),
            signature=b64url_encode(signature),
        )

    def register(self, challenge: bytes, *, origin: str, rp_id: str = RP_ID, flags: int = _FLAGS_UP_UV | 0x40) -> dict:
        """A `navigator.credentials.create()` response with `none` attestation, as an Apple passkey gives."""
        public = self._private_key.public_key()
        if self.alg == ALG_ES256:
            numbers = public.public_numbers()
            cose = {1: 2, 3: ALG_ES256, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
        else:
            raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            cose = {1: 1, 3: ALG_EDDSA, -1: 6, -2: raw}
        credential = b64url_decode(self.credential_id)
        authenticator_data = (
            hashlib.sha256(rp_id.encode("ascii")).digest()
            + bytes([flags])
            + self.sign_count.to_bytes(4, "big")
            + bytes(16)  # AAGUID: not disclosed
            + len(credential).to_bytes(2, "big")
            + credential
            + cbor_encode(cose)
        )
        client_data = json.dumps({"type": "webauthn.create", "challenge": b64url_encode(challenge), "origin": origin, "crossOrigin": False}).encode()
        return {
            "client_data_json": b64url_encode(client_data),
            "attestation_object": b64url_encode(cbor_encode({"fmt": "none", "attStmt": {}, "authData": authenticator_data})),
        }

    def sign(self, payload: DecisionPayload, **assertion_options) -> SignedDecision:
        return self.sign_batch([payload], **assertion_options)[0]

    def sign_batch(self, payloads: list[DecisionPayload], **assertion_options) -> list[SignedDecision]:
        """One tap, N decisions (#36): a single assertion over the ordered payload-hash list."""
        batch = [payload_hash(payload) for payload in payloads]
        assertion = self.assert_challenge(batch_challenge(batch), **assertion_options)
        return [SignedDecision(payload=payload, batch=batch, assertion=assertion) for payload in payloads]


# -- a researcher with an enrolled passkey ------------------------------------------


def enroll(store, authenticator: "SoftwareAuthenticator", *, signer: "SoftwareAuthenticator | None" = None):
    """Enroll `authenticator`'s key: self-signed if it's the first, else signed by `signer`."""
    from proof_cli.authority import EnrollmentRequest, build_decision_payload, enroll_reviewer_key, project_origin
    from proof_cli.signing import DecisionKind, public_key_fingerprint

    payload = build_decision_payload(
        store,
        DecisionKind.reviewer_enrollment,
        public_key_fingerprint(authenticator.public_key_spki),
        "enroll",
        credential_id=authenticator.credential_id,
    )
    request = EnrollmentRequest(
        credential_id=authenticator.credential_id,
        public_key_spki=b64url_encode(authenticator.public_key_spki),
        alg=authenticator.alg,
        display_name=authenticator.display_name,
        signed_decision=(signer or authenticator).sign(payload, origin=project_origin(store)),
    )
    return enroll_reviewer_key(store, request)


class Researcher:
    """The human side of a test: an enrolled passkey that signs each Human Review
    decision exactly the way the web app will (prepare the payload, one tap).

    Methods mirror the service functions they sign for."""

    def __init__(self, store, authenticator: "SoftwareAuthenticator | None" = None) -> None:
        from proof_cli.authority import list_reviewer_keys

        self.store = store
        self.authenticator = authenticator or SoftwareAuthenticator()
        if not any(key.credential_id == self.authenticator.credential_id for key in list_reviewer_keys(store)):
            enroll(store, self.authenticator)

    @property
    def reviewer_id(self) -> str:
        """How this researcher's decisions are attributed: by key, never by display name."""
        from proof_cli.signing import public_key_fingerprint

        return f"passkey:{public_key_fingerprint(self.authenticator.public_key_spki)[:16]}"

    def sign(self, kind, target_id: str, decision: str, *, rationale: str = "", dependency_id: str | None = None):
        from proof_cli.proof_map import prepare_decision

        payload = prepare_decision(self.store, kind, target_id, decision, rationale=rationale, dependency_id=dependency_id)
        return self.authenticator.sign(payload, origin=project_origin(self.store))

    def decide_acceptance(self, node_id: str, decision: str, *, rationale: str = ""):
        from proof_cli.proof_map import decide_acceptance

        signed = self.sign("acceptance", node_id, decision, rationale=rationale)
        return decide_acceptance(self.store, node_id, decision, signed_decision=signed)

    def decide_reference_review(self, node_id: str, decision: str = "reference-review", *, rationale: str = ""):
        from proof_cli.proof_map import decide_reference_review

        signed = self.sign("reference_review", node_id, decision, rationale=rationale)
        return decide_reference_review(self.store, node_id, decision, signed_decision=signed)

    def decide_evidence_review(self, check_id: str, decision: str, *, rationale: str = ""):
        from proof_cli.proof_map import decide_evidence_review

        signed = self.sign("evidence_review", check_id, decision, rationale=rationale)
        return decide_evidence_review(self.store, check_id, decision, signed_decision=signed)

    def revalidate_dependency(self, node_id: str, target_node_id: str, *, rationale: str = ""):
        from proof_cli.proof_map import revalidate_dependency

        signed = self.sign("dependency_revalidation", node_id, "reaffirmed", rationale=rationale, dependency_id=target_node_id)
        return revalidate_dependency(self.store, node_id, target_node_id, signed_decision=signed)

    def promote_to_lemma(self, node_id: str, *, rationale: str = ""):
        from proof_cli.proof_map import promote_to_lemma

        return promote_to_lemma(self.store, node_id, signed_decision=self.sign("promote", node_id, "promote", rationale=rationale))

    def dismiss_challenge(self, challenge_id: str, *, rationale: str = ""):
        from proof_cli.proof_map import dismiss_challenge

        signed = self.sign("challenge_resolution", challenge_id, "dismissed", rationale=rationale)
        return dismiss_challenge(self.store, challenge_id, signed_decision=signed)

    def force_release(self, node_id: str, *, reason: str = "researcher override", claimant_id: str = "human", session_id: str = "default"):
        from proof_cli.proof_map import release_node
        from proof_cli.storage import get_active_claim

        claim = get_active_claim(self.store, node_id)
        signed = self.sign("force_release", claim.id if claim else "", "force-release", rationale=reason)
        return release_node(self.store, node_id, claimant_id=claimant_id, session_id=session_id, force=True, signed_decision=signed)


_RESEARCHERS: dict = {}


def researcher(store) -> Researcher:
    """The one enrolled researcher for `store`'s project, created on first use."""
    key = str(store.root.resolve())
    if key not in _RESEARCHERS:
        _RESEARCHERS[key] = Researcher(store)
    return _RESEARCHERS[key]
