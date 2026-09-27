"""Signed decisions travelling between projects: foreign attestations (ADR-0009 point 6, issue #38).

An exchange bundle carries its project's signed decisions and the public
half of the keys that signed them. On import they become foreign
attestations: checked against the key the bundle names, shown next to their
node, and never read by anything that derives a Human Review axis. Nothing
here grants, revokes or resolves anything; the receiving researcher can only
make the same decision again, locally, with their own passkey.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from .authority import RP_ID, decision_row_for, list_reviewer_keys, origin_port, payload_decision_for
from .collaboration import ReviewGovernanceState, ReviewRecord
from .domain import ExportedReviewerKey, ForeignAttestation
from .signing import DecisionKind, SignatureError, SignedDecision, b64url_decode, canonical_json, public_key_fingerprint, verify_signed_decision
from .storage import ProjectStore, insert_foreign_attestation, list_review_history_rows


def exported_signatures(store: ProjectStore, records: Iterable[ReviewRecord]) -> tuple[dict[str, dict], list[ExportedReviewerKey]]:
    """(signed decision per review record id, the public keys that signed them) for a bundle."""
    signed_decisions: dict[str, dict] = {}
    for record in records:
        if not record.signed or not record.decision_row_id:
            continue
        row = next((row for row in list_review_history_rows(store, review_id=record.id) if row["id"] == record.decision_row_id), None)
        if row is not None and row["signed_decision"]:
            signed_decisions[record.id] = json.loads(row["signed_decision"])
    keys = [
        ExportedReviewerKey(credential_id=key.credential_id, public_key_spki=key.public_key_spki, alg=key.alg, display_name=key.display_name)
        for key in list_reviewer_keys(store)
    ]
    return signed_decisions, keys


def _payload_decision(record: ReviewRecord) -> str:
    """The decision value an unsigned record's row stands for."""
    return payload_decision_for(DecisionKind(record.kind.value), record.object_type, record.decision.value) or record.decision.value


def _signature_status(record: ReviewRecord, signed: SignedDecision | None, key: ExportedReviewerKey | None) -> str:
    if signed is None:
        return "unsigned"
    if key is None:
        return "invalid"  # the bundle doesn't name the key that signed it
    payload = signed.payload
    try:
        if payload.target_id != record.object_id or decision_row_for(payload.kind, payload.decision) != (record.object_type, record.decision.value):
            return "invalid"
        # made on the other project's own review app, as a signature there must be
        verify_signed_decision(
            signed,
            public_key_spki=b64url_decode(key.public_key_spki),
            alg=key.alg,
            expected_origin=f"http://{RP_ID}:{origin_port(payload.project_instance)}",
        )
    except (SignatureError, KeyError, ValueError, TypeError):
        return "invalid"  # whatever a hostile bundle put there, it never aborts the import
    return "valid"


def _attestation_id(*, bundle_source: str, record: ReviewRecord, signed: dict | None) -> str:
    content = {"source": bundle_source, "record": record.model_dump(mode="json"), "signed": signed}
    return "attestation_" + hashlib.sha256(canonical_json(content)).hexdigest()[:32]


def _fingerprint(key: ExportedReviewerKey | None) -> str | None:
    try:
        return public_key_fingerprint(b64url_decode(key.public_key_spki)) if key else None
    except (ValueError, TypeError):
        return None


def record_foreign_attestations(
    store: ProjectStore,
    *,
    bundle_id: str,
    source_project_id: str,
    records: Iterable[ReviewRecord],
    signed_decisions: dict[str, dict],
    reviewer_keys: list[ExportedReviewerKey],
) -> int:
    """Keep each of a bundle's Human Review decisions as a foreign attestation; returns how many are new."""
    keys = {key.credential_id: key for key in reviewer_keys}
    kept = 0
    for record in records:
        if record.kind is None or record.decision == ReviewGovernanceState.proposed_for_review:
            continue  # a request, not a decision
        try:
            signed = SignedDecision.model_validate(signed_decisions[record.id]) if record.id in signed_decisions else None
        except ValueError:
            signed = None
        key = keys.get(signed.assertion.credential_id) if signed else None
        status = _signature_status(record, signed, key)
        counted = signed if status == "valid" else None
        attestation = ForeignAttestation(
            # by content, not the bundle's own record id: a crafted bundle can't
            # take an id first and so hide a genuine attestation imported later
            id=_attestation_id(bundle_source=source_project_id, record=record, signed=signed_decisions.get(record.id)),
            bundle_id=bundle_id,
            source_project_id=source_project_id,
            object_type=record.object_type,
            object_id=record.object_id,
            kind=record.kind.value,
            decision=counted.payload.decision if counted else _payload_decision(record),
            reviewer_id=record.reviewer_id,
            rationale=counted.payload.rationale if counted else record.rationale,
            decided_at=record.updated_at,
            signature=status,
            signer_credential_id=key.credential_id if key else None,
            # computed from the public key, never taken from what the bundle says
            signer_fingerprint=_fingerprint(key),
            signer_name=key.display_name if key else None,
            signer_public_key_spki=key.public_key_spki if key else None,
            signer_alg=key.alg if key else None,
        )
        kept += insert_foreign_attestation(store, attestation)
    return kept


__all__ = ["exported_signatures", "record_foreign_attestations"]
