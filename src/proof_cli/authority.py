"""What counts as a Human Review decision, read off the git-tracked `reviews.jsonl` files (ADR-0010).

The proof map derives every acceptance, integrity and workflow fact from
these decisions (`proof_map`); this module is the one place that reads and
writes them. A decision counts when it is recorded here and still describes
what it decided on — the snapshot hash, interface and pins it names are
checked by `proof_map`. There are no signatures, keys or hash chains any
more (they were ADR-0009's): the reviewer is a git identity, and the commit
that records the decision is the evidence.

A pre-ADR-0010 project's decisions are moved out of the SQLite
`review_history` table once, the first time they're read. Signatures no
longer matter, so every decision the researcher made counts as a plain
decision — a signed one with what it was signed over, an older unsigned one
with what it was made on as the project stands at migration — and nothing
has to be re-signed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .reviews import (
    DECISION_ROWS,
    DecisionKind,
    DecisionPayload,
    PinnedDependency,
    ReviewEntry,
    append_entry,
    commit_decision,
    git_identity,
    in_git_repo,
    load_entries,
    new_review_id,
    next_seq,
    reviews_path,
    uncommitted_review_files,
)
from .storage import (
    ProjectStore,
    active_transaction,
    after_commit,
    before_commit,
    get_candidate_proof,
)


def decision_row_for(kind: DecisionKind, decision: str) -> tuple[str, str]:
    """(object_type, recorded state) a decision of this kind and value is recorded as."""
    return DECISION_ROWS[(kind, decision)]


class AuthorityError(Exception):
    """A human-only operation refused: it isn't something the CLI or an agent can do."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class AuthorityWarning(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


@dataclass
class RowVerdict:
    """Whether one recorded decision counts: `verified` (recorded, with what it was made on), or `invalid`."""

    status: Literal["verified", "invalid"]
    payload: DecisionPayload | None = None
    reason: str = ""


def human_review_required(kind: DecisionKind | str, target_id: str) -> AuthorityError:
    kind_name = kind.value if isinstance(kind, DecisionKind) else kind
    return AuthorityError(
        "HUMAN_REVIEW_REQUIRED",
        f"{kind_name} on {target_id} is a Human Review decision: the researcher makes it on the proof map page",
        details={"kind": kind_name, "target_id": target_id},
    )


def candidate_proof_sha256(store: ProjectStore, candidate_proof_id: str) -> str | None:
    """SHA-256 of a Candidate proof's file (a Review snapshot) as it is on disk now, or None if it's missing."""
    record = get_candidate_proof(store, candidate_proof_id)
    if record is None:
        return None
    path = store.root / record.file_path
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def build_decision_payload(
    store: ProjectStore,
    kind: DecisionKind,
    target_id: str,
    decision: str,
    *,
    rationale: str = "",
    candidate_proof_id: str | None = None,
    interface_fingerprint: str | None = None,
    dependency_pins: list[PinnedDependency] | None = None,
    resolves_challenges: list[str] | None = None,
) -> DecisionPayload:
    """What a decision of `kind` on `target_id` is made on, as of now."""
    return DecisionPayload(
        kind=kind,
        target_id=target_id,
        decision=decision,
        rationale=rationale,
        candidate_proof_id=candidate_proof_id,
        candidate_proof_sha256=candidate_proof_sha256(store, candidate_proof_id) if candidate_proof_id else None,
        interface_fingerprint=interface_fingerprint,
        dependency_pins=list(dependency_pins or []),
        resolves_challenges=list(resolves_challenges or []),
    )


# -- reading ------------------------------------------------------------------------


def _row(entry: ReviewEntry) -> dict:
    """A decision in the shape the proof map reads."""
    return {
        "id": entry.id,
        "review_id": entry.id,
        "seq": entry.seq,
        "entry": "decision",
        "object_type": entry.object_type,
        "object_id": entry.object_id,
        "kind": entry.kind,
        "decision": entry.decision,
        "reviewer_id": entry.reviewer,
        "rationale": entry.rationale,
        "created_at": entry.decided_at.isoformat(),
        "payload": entry.payload,
        "migrated": entry.migrated,
    }


def _entries(store: ProjectStore) -> tuple[list[ReviewEntry], list[str]]:
    _migrate_review_history(store)
    return load_entries(store.root)


def list_decisions(store: ProjectStore) -> list[dict]:
    """Every recorded decision in the project, oldest first."""
    return [_row(entry) for entry in _entries(store)[0]]


def decision_rows(store: ProjectStore, object_type: str, object_id: str, kind: str) -> list[dict]:
    """The decisions on one object and kind, oldest first."""
    return [
        _row(entry)
        for entry in _entries(store)[0]
        if entry.object_type == object_type and entry.object_id == object_id and entry.kind == kind
    ]


def verify_decision_row(store: ProjectStore, row_id: str | None) -> RowVerdict:
    """Whether the decision `row_id` counts: recorded, and made on something (its payload)."""
    if row_id is None:
        return RowVerdict("invalid", reason="no decision")
    entry = next((entry for entry in _entries(store)[0] if entry.id == row_id), None)
    if entry is None:
        return RowVerdict("invalid", reason="decision not found")
    if entry.payload is None:
        return RowVerdict("invalid", reason="recorded without what it was made on")
    payload = entry.payload
    if payload.kind.value != entry.kind or payload.target_id != entry.object_id or DECISION_ROWS.get((payload.kind, payload.decision)) != (
        entry.object_type,
        entry.decision,
    ):
        return RowVerdict("invalid", payload, "the recorded decision doesn't match what it says it decided")
    return RowVerdict("verified", payload)


_RESOLVING_KINDS = (DecisionKind.acceptance.value, DecisionKind.reference_review.value)


def challenge_resolution(store: ProjectStore, challenge_id: str) -> dict | None:
    """The newest counted decision that resolves `challenge_id`, if any.

    A `challenge_resolution` on its id, or an Acceptance / Reference review
    that listed it in `resolves_challenges`.
    """
    for entry in reversed(_entries(store)[0]):
        if entry.kind == DecisionKind.challenge_resolution.value:
            named = [entry.object_id]
        elif entry.kind in _RESOLVING_KINDS and entry.payload is not None:
            named = entry.payload.resolves_challenges
        else:
            continue
        if challenge_id in named and verify_decision_row(store, entry.id).status == "verified":
            return _row(entry)
    return None


def list_authority_warnings(store: ProjectStore) -> list[AuthorityWarning]:
    """What about the recorded decisions themselves doesn't count, or isn't in git yet."""
    entries, problems = _entries(store)
    warnings = [
        AuthorityWarning(code="REVIEW_LINE_UNREADABLE", message=f"{problem} can't be read and is ignored", details={"line": problem})
        for problem in problems
    ]
    if in_git_repo(store.root):
        for path in uncommitted_review_files(store.root):
            warnings.append(
                AuthorityWarning(
                    code="REVIEWS_NOT_COMMITTED",
                    message=f"{path} has decisions git doesn't have yet; commit and push it so the decisions have their record",
                    details={"path": path},
                )
            )
    return warnings


# -- writing ------------------------------------------------------------------------


def record_decision(
    store: ProjectStore,
    *,
    node_id: str,
    object_type: str,
    object_id: str,
    kind: DecisionKind,
    decision: str,
    reviewer: str | None,
    rationale: str,
    payload: DecisionPayload,
) -> ReviewEntry:
    """Record one decision in `proofs/<node_id>/reviews.jsonl` and commit it with its snapshot.

    Called inside the operation's SQLite transaction, after its checks. The
    line is appended as that transaction commits, still under its write lock
    (so concurrent decisions are ordered, and a failed write rolls the
    operation back), and committed to git as the reviewer's identity once it
    has committed.
    """
    entry = ReviewEntry(
        seq=0,
        id=new_review_id(),
        object_type=object_type,
        object_id=object_id,
        kind=kind.value,
        decision=decision,
        reviewer=reviewer or git_identity(store.root),
        rationale=rationale,
        payload=payload,
    )
    paths = [reviews_path(store.root, node_id)]
    if payload.candidate_proof_id:
        proof = get_candidate_proof(store, payload.candidate_proof_id)
        if proof is not None:
            snapshot = store.root / proof.file_path
            paths += [snapshot, snapshot.with_suffix(".pdf")]  # the PDF only if one was archived
    message = f"review: {kind.value} {payload.decision} on {object_id}\n\n{rationale}".rstrip()

    def _write() -> None:
        entry.seq = next_seq(store.root)  # on the write lock: concurrent decisions get distinct, ordered seqs
        append_entry(store.root, node_id, entry)

    before_commit(store, _write)
    after_commit(store, lambda: commit_decision(store.root, paths, message))
    return entry


# -- the one-time move out of review_history ----------------------------------------------

_MIGRATED_KEY = "reviews_jsonl_migrated"
_MIGRATED: set[str] = set()
_MIGRATING_KINDS = {kind.value for kind in DecisionKind}


def review_history_changed(store: ProjectStore, conn) -> None:
    """Decisions reached review_history after the move (a pre-#33 project's JSON records): move again."""
    conn.execute("DELETE FROM project_meta WHERE key = ?", (_MIGRATED_KEY,))
    _MIGRATED.discard(str(store.root.resolve()))


def _migrate_review_history(store: ProjectStore) -> None:
    """Move a pre-ADR-0010 project's proof-map decisions into reviews.jsonl, once."""
    key = str(store.root.resolve())
    if key in _MIGRATED or active_transaction(store) is not None:
        return
    from .collaboration import _migrate_legacy_review_records

    _migrate_legacy_review_records(store)  # a pre-#33 project's records reach review_history first
    written: list[Path] = []
    with store.transaction() as conn:
        if conn.execute("SELECT 1 FROM project_meta WHERE key = ?", (_MIGRATED_KEY,)).fetchone() is not None:
            _MIGRATED.add(key)
            return
        rows = [dict(row) for row in conn.execute("SELECT * FROM review_history ORDER BY seq").fetchall()]
        challenges = {row["id"]: row["target_node_id"] for row in conn.execute("SELECT id, target_node_id FROM challenges")}
        checks = {
            row["id"]: row["node_id"]
            for row in conn.execute(
                "SELECT evidence_checks.id AS id, candidate_proofs.node_id AS node_id FROM evidence_checks "
                "JOIN candidate_proofs ON candidate_proofs.id = evidence_checks.candidate_proof_id"
            )
        }
        decisions = [row for row in rows if row["entry"] == "decision"]
        declined = {row["object_id"] for row in decisions if row["kind"] == "legacy_decline" and row["signed_decision"]}
        signed_reviews = {row["review_id"] for row in decisions if row["signed_decision"]}
        already = {entry.id for entry in load_entries(store.root)[0]}  # idempotent: a rerun adds only what's new
        seq = next_seq(store.root)
        for row in decisions:
            if row["kind"] not in _MIGRATING_KINDS or row["review_id"] in already:
                continue
            if row["review_id"] in declined or (not row["signed_decision"] and row["review_id"] in signed_reviews):
                continue  # declined by the researcher, or an unsigned row behind a signed one: neither ever counted
            node_id = {"proof_map_node": row["object_id"], "challenge": challenges.get(row["object_id"]), "evidence_check": checks.get(row["object_id"])}.get(
                row["object_type"]
            )
            if not node_id:
                continue
            payload = None
            if row["signed_decision"]:
                try:
                    payload = DecisionPayload.model_validate(json.loads(row["signed_decision"])["payload"])
                except (ValidationError, ValueError, KeyError, TypeError):
                    payload = None
            if payload is None:
                payload = _legacy_payload(store, row)
            entry = ReviewEntry(
                seq=seq,
                id=row["review_id"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                kind=row["kind"],
                decision=row["decision"],
                reviewer=row["reviewer_id"],
                rationale=row["rationale"],
                decided_at=row["created_at"],
                payload=payload,
                migrated=True,
            )
            written.append(append_entry(store.root, node_id, entry))
            seq += 1
        conn.execute("INSERT OR IGNORE INTO project_meta(key, value) VALUES (?, ?)", (_MIGRATED_KEY, "1"))
    _MIGRATED.add(key)
    if written:
        commit_decision(store.root, sorted(set(written)), "review: move Human Review decisions into reviews.jsonl (ADR-0010)")


def _legacy_payload(store: ProjectStore, row: dict) -> DecisionPayload | None:
    """What an unsigned pre-ADR-0009 decision was made on, as the project stands at migration.

    Its Candidate proof is the one the review was linked to; its interface
    and pins are the node's own now, which is what that code read them as.
    """
    from . import proof_map
    from .reviews import payload_decision_for

    decision = payload_decision_for(row["kind"], row["object_type"], row["decision"])
    if decision is None:
        return None
    kind = DecisionKind(row["kind"])
    try:
        if kind in (DecisionKind.acceptance, DecisionKind.promote):
            node = proof_map.require_node(store, row["object_id"])
            linked = next(
                (proof for proof in proof_map.list_candidate_proofs(store, node.id) if proof.review_record_id == row["review_id"]),
                None,
            )
            proof_id = linked.id if linked is not None else proof_map._current_proof_id(store, node.id)
            binding = {"candidate_proof_id": proof_id, "interface_fingerprint": proof_map._interface_of(node), "dependency_pins": proof_map._pins_of(store, node.id)}
        elif kind == DecisionKind.dependency_revalidation:
            node = proof_map.require_node(store, row["object_id"])
            binding = {"candidate_proof_id": proof_map._current_proof_id(store, node.id), "interface_fingerprint": proof_map._interface_of(node), "dependency_pins": proof_map._pins_of(store, node.id)}
        else:
            binding = proof_map.decision_binding(store, kind, row["object_id"])
            binding["resolves_challenges"] = []
    except proof_map.ProofMapError:
        return None
    return build_decision_payload(store, kind, row["object_id"], decision, rationale=row["rationale"], **binding)


__all__ = [
    "AuthorityError",
    "AuthorityWarning",
    "DecisionKind",
    "DecisionPayload",
    "PinnedDependency",
    "RowVerdict",
    "build_decision_payload",
    "candidate_proof_sha256",
    "challenge_resolution",
    "decision_row_for",
    "decision_rows",
    "human_review_required",
    "list_authority_warnings",
    "list_decisions",
    "record_decision",
    "reviews_path",
    "verify_decision_row",
]
