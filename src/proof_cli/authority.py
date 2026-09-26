"""Human Review authority: who may decide, and which decisions count (ADR-0009, issue #35).

A Human Review decision counts only if it is signed by an enrolled Reviewer
passkey. This module owns:

- the **Reviewer key registry**: append-only and hash-chained, replayed and
  re-verified on every read. The first key is trust-on-first-use (it signs
  its own enrollment); every later enrollment or revocation must be signed
  by an already-active key. The first key's fingerprint is also pinned in the
  researcher's user-level config, and a registry that disagrees is not trusted.
- **authorization at decision time** (`authorize`): a service function asks
  whether a signed decision is valid for exactly the operation it is about
  to perform, bound to the exact Candidate proof text and dependency pins.
- **verification on read** (`decision_row_verifies`): derived axes count a
  review-history row only while its signature still verifies against the
  registry, its hash-chain commitment still holds, and the Candidate proof
  text it was signed over is unchanged.
- **integrity warnings**: everything that doesn't verify is surfaced, never
  silently dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .domain import utc_now
from .signing import (
    SUPPORTED_ALGORITHMS,
    DecisionKind,
    DecisionPayload,
    PinnedDependency,
    SignatureError,
    SignedDecision,
    b64url_decode,
    payload_hash,
    public_key_fingerprint,
    verify_signed_decision,
)
from .storage import (
    GENESIS_ROW_HASH,
    ProjectStore,
    chain_row_hash,
    get_candidate_proof,
    in_transaction,
    insert_reviewer_key_row,
    list_events,
    list_raw_chain_rows,
    read_state,
    review_history_head,
    review_history_payload_recorded,
)

USER_CONFIG_ENV_VAR = "PROOF_CLI_CONFIG_HOME"

ENROLL = "enroll"
REVOKE = "revoke"

# What each signed decision value means once recorded as a review-history
# row: (kind, payload decision) -> (row object_type, row decision value).
_DECISION_ROWS: dict[tuple[DecisionKind, str], tuple[str, str]] = {
    (DecisionKind.acceptance, "accept"): ("proof_map_node", "approved"),
    (DecisionKind.acceptance, "revision-requested"): ("proof_map_node", "revision_requested"),
    (DecisionKind.acceptance, "reject"): ("proof_map_node", "rejected"),
    (DecisionKind.reference_review, "reference-review"): ("proof_map_node", "approved"),
    (DecisionKind.evidence_review, "trusted"): ("evidence_check", "trusted"),
    (DecisionKind.evidence_review, "unusable"): ("evidence_check", "unusable"),
    (DecisionKind.dependency_revalidation, "reaffirmed"): ("proof_map_node", "reaffirmed"),
    (DecisionKind.challenge_resolution, "dismissed"): ("challenge", "dismissed"),
    (DecisionKind.promote, "promote"): ("proof_map_node", "approved"),
    (DecisionKind.force_release, "force-release"): ("claim", "approved"),
}


class AuthorityError(Exception):
    """A human-only operation refused for lack of a valid signed decision."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class AuthorityWarning(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ReviewerKey(BaseModel):
    credential_id: str
    public_key_spki: str
    alg: int
    fingerprint: str
    display_name: str
    enrolled_at: datetime
    revoked_at: datetime | None = None

    def active_at(self, moment: datetime) -> bool:
        return self.enrolled_at <= moment and (self.revoked_at is None or moment < self.revoked_at)

    @property
    def reviewer_id(self) -> str:
        """Who decided, as recorded: the key itself, never the self-declared
        `display_name` (CONTEXT.md, Reviewer passkey)."""
        return f"passkey:{self.fingerprint[:16]}"


class EnrollmentRequest(BaseModel):
    """A new Reviewer passkey plus the signed `reviewer_enrollment` decision authorizing it.

    For the very first key the decision is signed by that key itself (proof
    of possession, trust on first use); for every later key it must be
    signed by a key that is already active.
    """

    credential_id: str
    public_key_spki: str
    alg: int
    display_name: str
    signed_decision: SignedDecision


# -- user-level config ----------------------------------------------------------


def user_config_dir() -> Path:
    if os.environ.get(USER_CONFIG_ENV_VAR):
        return Path(os.environ[USER_CONFIG_ENV_VAR])
    base = Path(os.environ["XDG_CONFIG_HOME"]) if os.environ.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "proof-cli"


def _pins_path() -> Path:
    return user_config_dir() / "reviewer-pins.json"


def _read_pins() -> dict[str, Any]:
    path = _pins_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _project_key(store: ProjectStore) -> str:
    # keyed by where the project lives, not its id: two projects on one
    # machine commonly share the default id
    return str(store.root.resolve())


def pinned_first_fingerprint(store: ProjectStore) -> str | None:
    entry = _read_pins().get("projects", {}).get(_project_key(store))
    return entry.get("first_key_fingerprint") if isinstance(entry, dict) else None


def _pin_first_fingerprint(store: ProjectStore, fingerprint: str) -> None:
    """Record the project's first Reviewer key on this machine, once; never overwritten."""
    if pinned_first_fingerprint(store) is not None:
        return
    data = _read_pins()
    projects = data.setdefault("projects", {})
    projects[_project_key(store)] = {"project_id": read_state(store).project_id, "first_key_fingerprint": fingerprint}
    path = _pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


# -- the verified view of both chains ---------------------------------------------


@dataclass
class _Snapshot:
    """The registry and review-history chain as verified at one chain version."""

    trusted: bool
    keys: dict[str, ReviewerKey]  # by credential id, every key that was ever validly enrolled
    first_fingerprint: str | None
    history_rows: dict[str, dict]  # review-history rows by id
    # row hash -> seq of that row; GENESIS maps to 0
    history_hashes: dict[str, int]
    # (object_type, object_id, kind) -> seqs of its decision rows, ascending
    decision_seqs: dict[tuple[str, str, str | None], list[int]]
    warnings: list[AuthorityWarning]
    verified_rows: dict[str, bool] = field(default_factory=dict)
    row_warnings: dict[str, AuthorityWarning] = field(default_factory=dict)


_SNAPSHOTS: dict[tuple[str, int, int, str | None], _Snapshot] = {}


def _chain_hashes(rows: list[dict], table: str, warnings: list[AuthorityWarning]) -> dict[str, int]:
    """Row hash -> seq for a chained table, recording a warning at every broken link.

    Rows appended before the chain existed (pre-#35 review history) carry
    no link; once a linked row appears, every later row must be linked.
    """
    hashes = {GENESIS_ROW_HASH: 0}
    previous_hash = GENESIS_ROW_HASH
    chained = False
    for row in rows:
        link = row.get("prev_row_hash")
        if link is None:
            if chained:
                warnings.append(
                    AuthorityWarning(
                        code="HISTORY_CHAIN_BROKEN",
                        message=f"{table} row {row['seq']} was appended outside the hash chain",
                        details={"table": table, "seq": row["seq"]},
                    )
                )
        else:
            chained = True
            if link != previous_hash:
                warnings.append(
                    AuthorityWarning(
                        code="HISTORY_CHAIN_BROKEN",
                        message=f"{table} row {row['seq']} doesn't link to the row before it: history was edited or deleted",
                        details={"table": table, "seq": row["seq"]},
                    )
                )
        previous_hash = chain_row_hash(row)
        hashes[previous_hash] = row["seq"]
    return hashes


def _parse_signed(raw: str | None) -> SignedDecision | None:
    if not raw:
        return None
    try:
        return SignedDecision.model_validate_json(raw)
    except ValidationError:
        return None


def _replay_registry(
    store: ProjectStore, project_id: str, warnings: list[AuthorityWarning]
) -> tuple[bool, dict[str, ReviewerKey], str | None]:
    rows = list_raw_chain_rows(store, "reviewer_keys")
    chain_warnings: list[AuthorityWarning] = []
    _chain_hashes(rows, "reviewer_keys", chain_warnings)
    warnings.extend(chain_warnings)
    trusted = not chain_warnings

    keys: dict[str, ReviewerKey] = {}
    first_fingerprint: str | None = None
    for row in rows:
        problem = _registry_row_problem(row, project_id, keys)
        if problem is not None:
            warnings.append(
                AuthorityWarning(
                    code="INVALID_REGISTRY_ENTRY",
                    message=f"reviewer key registry row {row['seq']} is not validly signed: {problem}",
                    details={"seq": row["seq"], "fingerprint": row["fingerprint"]},
                )
            )
            continue
        signed = _parse_signed(row["signed_decision"])
        assert signed is not None
        if row["entry"] == ENROLL:
            keys[row["credential_id"]] = ReviewerKey(
                credential_id=row["credential_id"],
                public_key_spki=row["public_key_spki"],
                alg=row["alg"],
                fingerprint=row["fingerprint"],
                display_name=row["display_name"],
                enrolled_at=signed.payload.signed_at,
            )
            if first_fingerprint is None:
                first_fingerprint = row["fingerprint"]
        else:
            keys[row["credential_id"]].revoked_at = signed.payload.signed_at

    pinned = pinned_first_fingerprint(store)
    if pinned is not None and first_fingerprint is not None and pinned != first_fingerprint:
        trusted = False
        warnings.append(
            AuthorityWarning(
                code="REVIEWER_REGISTRY_MISMATCH",
                message=(
                    "this project's first Reviewer key doesn't match the one recorded in your user config; "
                    "no decision in it is trusted until that's resolved"
                ),
                details={"registry_first_fingerprint": first_fingerprint, "pinned_first_fingerprint": pinned},
            )
        )
    return trusted, keys, first_fingerprint


def _registry_row_problem(row: dict, project_id: str, keys: dict[str, ReviewerKey]) -> str | None:
    """Why a registry row can't be honored given the keys validly enrolled before it, or None."""
    signed = _parse_signed(row["signed_decision"])
    if signed is None:
        return "no parseable signed decision"
    payload = signed.payload
    if payload.kind != DecisionKind.reviewer_enrollment or payload.decision != row["entry"]:
        return "the signed decision is not this enrollment/revocation"
    if payload.project_id != project_id or payload.target_id != row["fingerprint"]:
        return "the signed decision names a different project or key"
    try:
        spki = b64url_decode(row["public_key_spki"])
    except ValueError:
        return "malformed public key"
    if public_key_fingerprint(spki) != row["fingerprint"] or row["alg"] not in SUPPORTED_ALGORITHMS:
        return "fingerprint or algorithm doesn't match the public key"

    active = [key for key in keys.values() if key.active_at(payload.signed_at)]
    signer_id = signed.assertion.credential_id
    if row["entry"] == ENROLL:
        if row["credential_id"] in keys:
            return "that credential is already enrolled"
        if not keys:
            # trust on first use — only while no key has *ever* been enrolled,
            # so a self-signed enrollment can't be backdated in ahead of one
            # the key proves possession by signing its own enrollment
            if signer_id != row["credential_id"]:
                return "a first enrollment must be signed by the key being enrolled"
            signer_spki, signer_alg = spki, row["alg"]
        else:
            signer = next((key for key in active if key.credential_id == signer_id), None)
            if signer is None:
                return "not signed by an already-enrolled, active Reviewer key"
            signer_spki, signer_alg = b64url_decode(signer.public_key_spki), signer.alg
    else:
        revoked = keys.get(row["credential_id"])
        if revoked is None or revoked.revoked_at is not None:
            return "revokes a key that isn't enrolled"
        signer = next((key for key in active if key.credential_id == signer_id), None)
        if signer is None:
            return "not signed by an active Reviewer key"
        signer_spki, signer_alg = b64url_decode(signer.public_key_spki), signer.alg
    try:
        verify_signed_decision(signed, public_key_spki=signer_spki, alg=signer_alg)
    except SignatureError as exc:
        return exc.message
    return None


def _snapshot(store: ProjectStore) -> _Snapshot:
    # Keyed by the database file's mtime and size, not by row counts: an
    # in-place edit (triggers dropped) leaves the row counts alone but still
    # rewrites the file, so a long-running process never keeps trusting a
    # history that was edited under it.
    db_stat = store.db_path.stat()
    cache_key = (_project_key(store), db_stat.st_mtime_ns, db_stat.st_size, pinned_first_fingerprint(store))
    cached = _SNAPSHOTS.get(cache_key)
    if cached is not None:
        return cached
    project_id = read_state(store).project_id
    warnings: list[AuthorityWarning] = []
    trusted, keys, first_fingerprint = _replay_registry(store, project_id, warnings)
    history = list_raw_chain_rows(store, "review_history")
    hashes = _chain_hashes(history, "review_history", warnings)
    decision_seqs: dict[tuple[str, str, str | None], list[int]] = {}
    for row in history:
        if row["entry"] == "decision":
            decision_seqs.setdefault((row["object_type"], row["object_id"], row["kind"]), []).append(row["seq"])
    snapshot = _Snapshot(
        trusted=trusted,
        keys=keys,
        first_fingerprint=first_fingerprint,
        history_rows={row["id"]: row for row in history},
        history_hashes=hashes,
        decision_seqs=decision_seqs,
        warnings=warnings,
    )
    if len(_SNAPSHOTS) > 64:
        _SNAPSHOTS.clear()
    _SNAPSHOTS[cache_key] = snapshot
    return snapshot


# -- registry operations ------------------------------------------------------------


def list_reviewer_keys(store: ProjectStore) -> list[ReviewerKey]:
    """Every validly enrolled Reviewer key, revoked ones included, in enrollment order."""
    return [key.model_copy() for key in _snapshot(store).keys.values()]


def active_reviewer_keys(store: ProjectStore) -> list[ReviewerKey]:
    snapshot = _snapshot(store)
    if not snapshot.trusted:
        return []
    now = utc_now()
    return [key.model_copy() for key in snapshot.keys.values() if key.active_at(now)]


def _key_row(credential: EnrollmentRequest | ReviewerKey, *, entry: str, signed: SignedDecision) -> dict:
    """A registry row for `credential`: the key being enrolled, or the one being revoked."""
    return {
        "id": f"reviewer_key_{uuid.uuid4().hex[:12]}",
        "entry": entry,
        "credential_id": credential.credential_id,
        "public_key_spki": credential.public_key_spki,
        "alg": credential.alg,
        "fingerprint": public_key_fingerprint(b64url_decode(credential.public_key_spki)),
        "display_name": credential.display_name,
        "signed_decision": signed.model_dump_json(),
        "created_at": utc_now().isoformat(),
    }


def enroll_reviewer_key(store: ProjectStore, request: EnrollmentRequest) -> ReviewerKey:
    """Append a Reviewer passkey to the registry (ADR-0009 point 5).

    The first key is trust-on-first-use and is pinned in the user-level
    config; any later key needs a `reviewer_enrollment` decision signed by
    a key that's already active.
    """
    project_id = read_state(store).project_id
    with store.transaction() as conn:
        snapshot = _snapshot(store)
        if not snapshot.trusted:
            raise AuthorityError(
                "REGISTRY_NOT_TRUSTED",
                "the Reviewer key registry doesn't verify; resolve its integrity warnings before enrolling",
            )
        row = _key_row(request, entry=ENROLL, signed=request.signed_decision)
        problem = _registry_row_problem(row, project_id, snapshot.keys)
        if problem is not None:
            raise AuthorityError("ENROLLMENT_REFUSED", f"enrollment refused: {problem}")
        insert_reviewer_key_row(conn, row)
    key = next(key for key in list_reviewer_keys(store) if key.credential_id == request.credential_id)
    if snapshot.first_fingerprint is None:
        _pin_first_fingerprint(store, key.fingerprint)
    return key


def revoke_reviewer_key(store: ProjectStore, signed_decision: SignedDecision | None) -> ReviewerKey:
    """Revoke the key whose fingerprint the signed `revoke` decision names; never the last active one."""
    if signed_decision is None:
        raise human_review_required(DecisionKind.reviewer_enrollment, "revoke")
    project_id = read_state(store).project_id
    revoked_at = signed_decision.payload.signed_at
    with store.transaction() as conn:
        snapshot = _snapshot(store)
        if not snapshot.trusted:
            raise AuthorityError("REGISTRY_NOT_TRUSTED", "the Reviewer key registry doesn't verify")
        target = next(
            (key for key in snapshot.keys.values() if key.fingerprint == signed_decision.payload.target_id), None
        )
        if target is None or target.revoked_at is not None:
            raise AuthorityError("NOT_ENROLLED", f"no active Reviewer key {signed_decision.payload.target_id}")
        others = [
            key for key in snapshot.keys.values() if key.credential_id != target.credential_id and key.active_at(revoked_at)
        ]
        if not others:
            raise AuthorityError("LAST_REVIEWER_KEY", "refusing to revoke the only active Reviewer key; enroll another first")
        row = _key_row(target, entry=REVOKE, signed=signed_decision)
        problem = _registry_row_problem(row, project_id, snapshot.keys)
        if problem is not None:
            raise AuthorityError("REVOCATION_REFUSED", f"revocation refused: {problem}")
        insert_reviewer_key_row(conn, row)
    return next(key for key in list_reviewer_keys(store) if key.credential_id == target.credential_id)


# -- decisions ----------------------------------------------------------------------


def candidate_proof_sha256(store: ProjectStore, candidate_proof_id: str) -> str | None:
    """SHA-256 of a Candidate proof's vault file as it is on disk now, or None if it's missing."""
    record = get_candidate_proof(store, candidate_proof_id)
    if record is None:
        return None
    path = store.root / record.file_path
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_decision_payload(
    store: ProjectStore,
    kind: DecisionKind,
    target_id: str,
    decision: str,
    *,
    rationale: str = "",
    candidate_proof_id: str | None = None,
    dependency_pins: list[PinnedDependency] | None = None,
) -> DecisionPayload:
    """The exact payload a reviewer's passkey must sign for this decision, as of now."""
    with store.connect() as conn:
        head = review_history_head(conn)
    return DecisionPayload(
        project_id=read_state(store).project_id,
        kind=kind,
        target_id=target_id,
        candidate_proof_id=candidate_proof_id,
        candidate_proof_sha256=candidate_proof_sha256(store, candidate_proof_id) if candidate_proof_id else None,
        dependency_pins=list(dependency_pins or []),
        decision=decision,
        rationale=rationale,
        previous_row_hash=head,
    )


def human_review_required(kind: DecisionKind, target_id: str) -> AuthorityError:
    return AuthorityError(
        "HUMAN_REVIEW_REQUIRED",
        f"{kind.value} on {target_id} is a Human Review decision and needs a signed decision from an enrolled "
        "Reviewer passkey",
        details={"kind": kind.value, "target_id": target_id},
    )


def _key_for(snapshot: _Snapshot, signed: SignedDecision) -> ReviewerKey:
    key = snapshot.keys.get(signed.assertion.credential_id)
    if key is None or not key.active_at(signed.payload.signed_at):
        raise AuthorityError(
            "UNKNOWN_REVIEWER_KEY",
            "the decision isn't signed by a Reviewer key that was enrolled and active when it was signed",
            details={"credential_id": signed.assertion.credential_id},
        )
    return key


def authorize(
    store: ProjectStore,
    signed: SignedDecision | None,
    *,
    kind: DecisionKind,
    target_id: str,
    decision: str,
    candidate_proof_id: str | None = None,
    dependency_pins: list[PinnedDependency] | None = None,
    conn: sqlite3.Connection | None = None,
) -> ReviewerKey:
    """Check that `signed` authorizes exactly this operation, now; return the signing key.

    Everything the service is about to do must be what was signed: the
    project, kind, target and decision, the current Candidate proof and the
    SHA-256 of its text on disk, and the dependency pins. The payload must
    commit to a real point in the review history, not have been recorded
    already, and verify under a Reviewer key active when it was signed.

    Call it on the operation's transaction *before* that operation writes
    anything: the history it checks against is the committed one, so rows
    the same transaction has already appended would be invisible to it.
    """
    if signed is None:
        raise human_review_required(kind, target_id)
    payload = signed.payload
    expected = {
        "project_id": read_state(store).project_id,
        "kind": kind,
        "target_id": target_id,
        "decision": decision,
        "candidate_proof_id": candidate_proof_id,
        "candidate_proof_sha256": candidate_proof_sha256(store, candidate_proof_id) if candidate_proof_id else None,
        "dependency_pins": list(dependency_pins or []),
    }
    for name, value in expected.items():
        if getattr(payload, name) != value:
            raise AuthorityError(
                "SIGNATURE_MISMATCH",
                f"the signed decision's {name} doesn't match this operation; the reviewer signed something else",
                details={"field": name},
            )
    with in_transaction(store, conn) as tx:
        digest = payload_hash(payload)
        if review_history_payload_recorded(tx, digest):
            raise AuthorityError("DECISION_ALREADY_RECORDED", "this signed decision has already been recorded")
        snapshot = _snapshot(store)
        if not snapshot.trusted:
            raise AuthorityError("REGISTRY_NOT_TRUSTED", "the Reviewer key registry doesn't verify; no decision can be trusted")
        committed_seq = snapshot.history_hashes.get(payload.previous_row_hash or "")
        if committed_seq is None:
            raise AuthorityError(
                "UNKNOWN_HISTORY_HEAD", "the decision commits to a review history this project doesn't have"
            )
        object_type = _DECISION_ROWS[(kind, decision)][0]
        earlier = snapshot.decision_seqs.get((object_type, target_id, kind.value), [])
        if earlier and committed_seq < earlier[-1]:
            raise AuthorityError(
                "STALE_DECISION",
                "another decision on this target was recorded after this one was signed; re-sign against the current history",
            )
        key = _key_for(snapshot, signed)
        try:
            verify_signed_decision(signed, public_key_spki=b64url_decode(key.public_key_spki), alg=key.alg)
        except SignatureError as exc:
            raise AuthorityError(exc.code, exc.message) from exc
    return key.model_copy()


def decision_row_verifies(store: ProjectStore, row_id: str | None) -> bool:
    """Whether the review-history decision row `row_id` counts (ADR-0009 point 2).

    It must carry a signed decision that verifies under a key the trusted
    registry had active when it was signed; that decision must be exactly
    this row (kind, target, decision value); the history prefix it commits
    to must still be there, ahead of it; and — for a decision about a
    Candidate proof — the proof text on disk must still be what was signed.
    """
    if row_id is None:
        return False
    snapshot = _snapshot(store)
    if row_id not in snapshot.verified_rows:
        problem = _row_problem(store, snapshot, row_id)
        snapshot.verified_rows[row_id] = problem is None
        if problem is not None:
            snapshot.row_warnings[row_id] = problem
    if not snapshot.verified_rows[row_id]:
        return False
    # the text check isn't cached: the vault file can change without the chain moving
    payload = _parse_signed(snapshot.history_rows[row_id]["signed_decision"]).payload
    if payload.candidate_proof_id is not None:
        return candidate_proof_sha256(store, payload.candidate_proof_id) == payload.candidate_proof_sha256
    return True


def _row_problem(store: ProjectStore, snapshot: _Snapshot, row_id: str) -> AuthorityWarning | None:
    row = snapshot.history_rows.get(row_id)
    if row is None:
        return AuthorityWarning(code="UNVERIFIABLE_REVIEW_RECORD", message=f"review row {row_id} not found")
    details = {"review_id": row["review_id"], "object_type": row["object_type"], "object_id": row["object_id"], "kind": row["kind"]}
    signed = _parse_signed(row["signed_decision"])
    if signed is None:
        return AuthorityWarning(
            code="UNSIGNED_DECISION",
            message=f"{row['kind']} decision on {row['object_id']} is unsigned (legacy or forged); re-sign to keep it",
            details=details,
        )

    def _unverifiable(reason: str) -> AuthorityWarning:
        return AuthorityWarning(
            code="UNVERIFIABLE_REVIEW_RECORD",
            message=f"{row['kind']} decision on {row['object_id']} doesn't verify: {reason}",
            details=details,
        )

    payload = signed.payload
    mapped = _DECISION_ROWS.get((payload.kind, payload.decision))
    if (
        mapped is None
        or payload.kind.value != row["kind"]
        or payload.target_id != row["object_id"]
        or mapped != (row["object_type"], row["decision"])
    ):
        return _unverifiable("the signed payload is a different decision than the recorded one")
    if payload.project_id != read_state(store).project_id:
        return _unverifiable("signed for a different project")
    if row["payload_hash"] != payload_hash(payload):
        return _unverifiable("payload hash doesn't match")
    committed_seq = snapshot.history_hashes.get(payload.previous_row_hash or "")
    if committed_seq is None or committed_seq >= row["seq"]:
        return _unverifiable("the history it was signed against has been changed")
    # Anyone can append a validly-linked row, so the chain alone doesn't stop
    # a replay: a decision counts only if the history it was signed against
    # already held every earlier decision on the same object and kind. That
    # rules out a replayed, duplicated or reordered decision overriding a
    # later one the reviewer never saw.
    earlier = [seq for seq in snapshot.decision_seqs[(row["object_type"], row["object_id"], row["kind"])] if seq < row["seq"]]
    if earlier and committed_seq < earlier[-1]:
        return _unverifiable("it was signed without seeing a later decision on the same object (replayed or reordered)")
    if not snapshot.trusted:
        return _unverifiable("the Reviewer key registry isn't trusted")
    try:
        key = _key_for(snapshot, signed)
        verify_signed_decision(signed, public_key_spki=b64url_decode(key.public_key_spki), alg=key.alg)
    except (AuthorityError, SignatureError) as exc:
        return _unverifiable(exc.message)
    # what users read off the row must be what was signed, by whom it was signed
    if row["rationale"] != payload.rationale or row["reviewer_id"] != key.reviewer_id:
        return _unverifiable("the recorded rationale or reviewer isn't what was signed")
    return None


# -- integrity warnings -----------------------------------------------------------


def list_authority_warnings(store: ProjectStore) -> list[AuthorityWarning]:
    """Everything about this project's Human Review authority that doesn't verify.

    Registry and chain problems, every trust-bearing decision row that
    doesn't count (unsigned legacy decisions included), Candidate proof text
    changed after it was signed, and review records found in
    `collaboration.json` (issue #33).
    """
    snapshot = _snapshot(store)
    warnings = list(snapshot.warnings)
    for row_id, row in snapshot.history_rows.items():
        if row["entry"] != "decision" or row["kind"] is None:
            continue
        if decision_row_verifies(store, row_id):
            continue
        warning = snapshot.row_warnings.get(row_id)
        if warning is None:
            warning = AuthorityWarning(
                code="CANDIDATE_PROOF_CHANGED",
                message=f"the Candidate proof text behind {row['kind']} decision on {row['object_id']} changed after it was signed",
                details={"review_id": row["review_id"], "object_id": row["object_id"], "kind": row["kind"]},
            )
        warnings.append(warning)
    for event in list_events(store):
        if event.kind == "review_history_integrity_warning":
            warnings.append(AuthorityWarning(code="IGNORED_JSON_REVIEW_RECORDS", message=event.message, details=event.payload))
    return warnings


__all__ = [
    "AuthorityError",
    "AuthorityWarning",
    "EnrollmentRequest",
    "ReviewerKey",
    "USER_CONFIG_ENV_VAR",
    "active_reviewer_keys",
    "authorize",
    "build_decision_payload",
    "candidate_proof_sha256",
    "decision_row_verifies",
    "enroll_reviewer_key",
    "human_review_required",
    "list_authority_warnings",
    "list_reviewer_keys",
    "pinned_first_fingerprint",
    "revoke_reviewer_key",
    "user_config_dir",
]
