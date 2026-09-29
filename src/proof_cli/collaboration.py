from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, ValidationError

from .authority import human_review_required
from .domain import EventRecord, utc_now
from .storage import (
    ProjectStore,
    active_transaction,
    append_event,
    collaboration_state_path,
    in_transaction,
    insert_review_history_row,
    is_review_history_migrated,
    list_events,
    list_review_history_rows,
    mark_review_history_migrated,
    read_state,
    review_history_row_exists,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class CollaborationRole(str, Enum):
    maintainer = "maintainer"
    reviewer = "reviewer"
    contributor = "contributor"
    observer = "observer"


class ContributorStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ReviewGovernanceState(str, Enum):
    draft = "draft"
    proposed_for_review = "proposed_for_review"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    disputed = "disputed"
    revision_requested = "revision_requested"
    reaffirmed = "reaffirmed"
    trusted = "trusted"
    unusable = "unusable"
    dismissed = "dismissed"


class ReviewRecordKind(str, Enum):
    """What a ReviewRecord's decision actually governs.

    `None` (the field's default) means "predates this vocabulary" — every
    review recorded before this existed, and every caller that hasn't been
    migrated to it yet. Only `acceptance` is wired up as of this ticket; the
    others are reserved for later tickets (#20, #27, #24). This is what makes
    Human Acceptance Authority enforceable: `acceptance_state` is computed
    exclusively from `kind == acceptance` records, so no other review flow
    can accidentally feed it.
    """

    acceptance = "acceptance"
    reference_review = "reference_review"
    evidence_review = "evidence_review"
    dependency_revalidation = "dependency_revalidation"
    # ADR-0009's other human-only operations, recorded as signed rows (#35)
    challenge_resolution = "challenge_resolution"
    promote = "promote"
    dependent_migration = "dependent_migration"
    force_release = "force_release"  # retired by ADR-0010; kept to read old rows
    legacy_decline = "legacy_decline"


class CommentThreadStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    disputed = "disputed"


class BranchStatus(str, Enum):
    active = "active"
    merged = "merged"
    abandoned = "abandoned"
    disputed = "disputed"


class SharedAssetPublicationStatus(str, Enum):
    draft = "draft"
    proposed_for_review = "proposed_for_review"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    disputed = "disputed"


class Contributor(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("contrib"))
    display_name: str
    role: CollaborationRole = CollaborationRole.contributor
    team_ids: list[str] = Field(default_factory=list)
    status: ContributorStatus = ContributorStatus.active
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CollaborationPolicy(BaseModel):
    project_id: str
    team_id: str = ""
    name: str = "default"
    who_can_propose: list[str] = Field(default_factory=lambda: ["maintainer", "reviewer", "contributor"])
    who_can_approve: list[str] = Field(default_factory=lambda: ["maintainer", "reviewer"])
    who_can_publish: list[str] = Field(default_factory=lambda: ["maintainer"])
    who_can_resolve_disputes: list[str] = Field(default_factory=lambda: ["maintainer", "reviewer"])
    one_reviewer_objects: list[str] = Field(default_factory=list)
    two_reviewer_objects: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReviewRecord(BaseModel):
    """One review, as currently decided — a view folded from its
    `review_history` rows (its request plus every later decision on it),
    never a stored, editable record of its own."""

    id: str = Field(default_factory=lambda: _new_id("review"))
    object_type: str
    object_id: str
    reviewer_id: str
    decision: ReviewGovernanceState = ReviewGovernanceState.proposed_for_review
    kind: ReviewRecordKind | None = None
    rationale: str = ""
    authorship: list[str] = Field(default_factory=list)
    provenance_notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    # the history row of the latest decision, and whether it carries a
    # signed decision (ADR-0009); whether that signature *verifies* is
    # `authority.decision_row_verifies(store, decision_row_id)`
    decision_row_id: str | None = None
    signed: bool = False


class ReviewHistoryEntry(BaseModel):
    """One append-only `review_history` row (issue #33).

    `entry=request` opens a review (its `review_id` is its own `id`);
    `entry=decision` records a decision on the request named by
    `review_id`. Rows are never edited or deleted — a re-decision is simply
    a later row.
    """

    seq: int
    id: str
    review_id: str
    entry: Literal["request", "decision"]
    object_type: str
    object_id: str
    kind: ReviewRecordKind | None = None
    decision: ReviewGovernanceState
    reviewer_id: str
    rationale: str = ""
    authorship: list[str] = Field(default_factory=list)
    provenance_notes: str = ""
    created_at: datetime
    prev_row_hash: str | None = None
    signed_decision: str | None = None
    payload_hash: str | None = None


class CommentThread(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("thread"))
    object_type: str
    object_id: str
    status: CommentThreadStatus = CommentThreadStatus.open
    participants: list[str] = Field(default_factory=list)
    created_by: str = "human"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Comment(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("comment"))
    thread_id: str
    author_id: str
    content: str
    status: CommentThreadStatus = CommentThreadStatus.open
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BranchRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("branch"))
    scope: str
    name: str
    status: BranchStatus = BranchStatus.active
    created_by: str = "human"
    derived_from: str | None = None
    downstream_asset_ids: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SharedAssetPublication(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("publication"))
    asset_id: str
    published_to: str
    status: SharedAssetPublicationStatus = SharedAssetPublicationStatus.draft
    approved_by: list[str] = Field(default_factory=list)
    created_by: str = "human"
    provenance_notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CollaborationState(BaseModel):
    project_id: str
    version: int = 1
    contributors: list[Contributor] = Field(default_factory=list)
    policies: list[CollaborationPolicy] = Field(default_factory=list)
    # A read-only view of the SQLite review history, filled in by
    # `load_collaboration`; `save_collaboration` never writes it back (issue #33).
    review_records: list[ReviewRecord] = Field(default_factory=list)
    comment_threads: list[CommentThread] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    branches: list[BranchRecord] = Field(default_factory=list)
    publications: list[SharedAssetPublication] = Field(default_factory=list)


def _collaboration_path(store: ProjectStore) -> Path:
    return collaboration_state_path(store)


def _project_id(store: ProjectStore) -> str:
    return read_state(store).project_id


def _load_json_model(value: Any, model: type[BaseModel]) -> BaseModel:
    if isinstance(value, model):
        return value
    if isinstance(value, dict):
        return model.model_validate(value)
    raise TypeError(f"unsupported collaboration payload: {type(value)!r}")


def _latest_by_id(items: Iterable[BaseModel], key_name: str) -> list[BaseModel]:
    seen: set[str] = set()
    ordered: list[BaseModel] = []
    for item in reversed(list(items)):
        key = str(getattr(item, key_name))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    ordered.reverse()
    return ordered


def _read_collaboration_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_collaboration_json(path: Path, data: str) -> None:
    # write-then-rename, so a concurrent reader never sees a half-written file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def load_collaboration(store: ProjectStore) -> CollaborationState:
    _migrate_legacy_review_records(store)
    path = _collaboration_path(store)
    project_id = _project_id(store)
    data = _read_collaboration_json(path) or {}
    data.pop("review_records", None)
    state = CollaborationState.model_validate({**data, "project_id": data.get("project_id", project_id)})
    state.review_records = list_review_records(store)
    return state


def save_collaboration(store: ProjectStore, state: CollaborationState) -> CollaborationState:
    """Persist the JSON-backed, non-trust-bearing collaboration state.

    `state.review_records` is never written: Human Review history lives
    only in the append-only SQLite table, so no caller — exchange import
    included — can revoke or forge a decision by saving a whole state.
    """
    path = _collaboration_path(store)
    state.project_id = _project_id(store)
    state.version = 1
    _write_collaboration_json(path, state.model_dump_json(indent=2, exclude={"review_records"}))
    return state


def _update_state(
    store: ProjectStore,
    state: CollaborationState,
    *,
    event_kind: str,
    message: str,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    save_collaboration(store, state)
    append_event(store, event_kind, message, entity_id=entity_id, payload=payload or {})


def upsert_contributor(store: ProjectStore, contributor: Contributor) -> Contributor:
    state = load_collaboration(store)
    contributor.updated_at = utc_now()
    existing = next((item for item in state.contributors if item.id == contributor.id), None)
    if existing is None:
        contributor.created_at = contributor.updated_at
        state.contributors.append(contributor)
        event_kind = "collaboration_contributor_added"
        message = f"added contributor {contributor.id}"
    else:
        existing.display_name = contributor.display_name
        existing.role = contributor.role
        existing.team_ids = list(contributor.team_ids)
        existing.status = contributor.status
        existing.notes = contributor.notes
        existing.updated_at = contributor.updated_at
        contributor = existing
        event_kind = "collaboration_contributor_updated"
        message = f"updated contributor {contributor.id}"
    _update_state(store, state, event_kind=event_kind, message=message, entity_id=contributor.id, payload=contributor.model_dump(mode="json"))
    return contributor


def get_contributor(store: ProjectStore, contributor_id: str) -> Contributor | None:
    state = load_collaboration(store)
    for contributor in reversed(state.contributors):
        if contributor.id == contributor_id:
            return contributor
    return None


def list_contributors(store: ProjectStore, *, team_id: str = "", status: str = "") -> list[Contributor]:
    state = load_collaboration(store)
    contributors = _latest_by_id(state.contributors, "id")
    if team_id:
        contributors = [item for item in contributors if team_id in item.team_ids]
    if status:
        contributors = [item for item in contributors if item.status.value == status]
    return contributors


def set_contributor_role(
    store: ProjectStore,
    contributor_id: str,
    role: CollaborationRole,
    *,
    notes: str = "",
) -> Contributor:
    state = load_collaboration(store)
    contributor = next((item for item in state.contributors if item.id == contributor_id), None)
    if contributor is None:
        raise KeyError(contributor_id)
    contributor.role = role
    contributor.notes = notes or contributor.notes
    contributor.updated_at = utc_now()
    _update_state(
        store,
        state,
        event_kind="collaboration_contributor_role_changed",
        message=f"changed contributor role for {contributor_id}",
        entity_id=contributor_id,
        payload=contributor.model_dump(mode="json"),
    )
    return contributor


def get_policy(store: ProjectStore, *, project_id: str = "") -> CollaborationPolicy | None:
    state = load_collaboration(store)
    if project_id and project_id != state.project_id:
        return None
    return state.policies[-1] if state.policies else None


def set_policy(store: ProjectStore, policy: CollaborationPolicy) -> CollaborationPolicy:
    state = load_collaboration(store)
    policy.updated_at = utc_now()
    if policy.project_id != state.project_id:
        policy.project_id = state.project_id
    state.policies.append(policy)
    _update_state(
        store,
        state,
        event_kind="collaboration_policy_recorded",
        message=f"recorded collaboration policy {policy.name}",
        entity_id=policy.project_id,
        payload=policy.model_dump(mode="json"),
    )
    return policy


def _row_to_history_entry(row: dict[str, Any]) -> ReviewHistoryEntry:
    return ReviewHistoryEntry.model_validate(row)


def _fold_review_history(entries: Iterable[ReviewHistoryEntry]) -> list[ReviewRecord]:
    """Each review's current state: its request, overlaid by its latest decision.

    Ordered by when each review was requested — the same order the old
    in-place-edited JSON list had, so "latest record" keeps its meaning.
    """
    records: dict[str, ReviewRecord] = {}
    for entry in entries:
        if entry.entry == "request":
            records[entry.review_id] = ReviewRecord(
                id=entry.review_id,
                object_type=entry.object_type,
                object_id=entry.object_id,
                reviewer_id=entry.reviewer_id,
                decision=entry.decision,
                kind=entry.kind,
                rationale=entry.rationale,
                authorship=list(entry.authorship),
                provenance_notes=entry.provenance_notes,
                created_at=entry.created_at,
                updated_at=entry.created_at,
            )
            continue
        record = records.get(entry.review_id)
        if record is None:
            continue
        record.decision = entry.decision
        record.reviewer_id = entry.reviewer_id
        record.rationale = entry.rationale or record.rationale
        record.updated_at = entry.created_at
        record.decision_row_id = entry.id
        record.signed = entry.signed_decision is not None
    return list(records.values())


def _history_row(
    *,
    entry: str,
    row_id: str,
    review_id: str,
    object_type: str,
    object_id: str,
    kind: ReviewRecordKind | None,
    decision: ReviewGovernanceState,
    reviewer_id: str,
    rationale: str,
    authorship: list[str],
    provenance_notes: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "review_id": review_id,
        "entry": entry,
        "object_type": object_type,
        "object_id": object_id,
        "kind": kind.value if kind is not None else None,
        "decision": decision.value,
        "reviewer_id": reviewer_id,
        "rationale": rationale,
        "authorship": list(authorship),
        "provenance_notes": provenance_notes,
        "created_at": created_at.isoformat(),
    }


def _request_row(record: ReviewRecord) -> dict[str, Any]:
    return _history_row(
        entry="request",
        row_id=record.id,
        review_id=record.id,
        object_type=record.object_type,
        object_id=record.object_id,
        kind=record.kind,
        decision=ReviewGovernanceState.proposed_for_review,
        reviewer_id=record.reviewer_id,
        rationale=record.rationale,
        authorship=record.authorship,
        provenance_notes=record.provenance_notes,
        created_at=record.created_at,
    )


def _decision_row(
    record: ReviewRecord,
    decision: ReviewGovernanceState,
    *,
    reviewer_id: str,
    rationale: str,
    created_at: datetime,
    row_id: str | None = None,
) -> dict[str, Any]:
    row = _history_row(
        entry="decision",
        row_id=row_id or _new_id("decision"),
        review_id=record.id,
        object_type=record.object_type,
        object_id=record.object_id,
        kind=record.kind,
        decision=decision,
        reviewer_id=reviewer_id,
        rationale=rationale,
        authorship=record.authorship,
        provenance_notes=record.provenance_notes,
        created_at=created_at,
    )
    return row


def _append_legacy_record(conn: sqlite3.Connection, record: ReviewRecord) -> bool:
    """Append a JSON-era ReviewRecord (request, plus its decision if it has one)
    unless its request is already in the history. Whether anything was appended."""
    if review_history_row_exists(conn, record.id):
        return False
    insert_review_history_row(conn, _request_row(record))
    if record.decision != ReviewGovernanceState.proposed_for_review:
        insert_review_history_row(
            conn,
            _decision_row(
                record,
                record.decision,
                reviewer_id=record.reviewer_id,
                rationale=record.rationale,
                created_at=record.updated_at,
                row_id=f"{record.id}_decision",
            ),
        )
    return True


REVIEW_HISTORY_INTEGRITY_WARNING = "review_history_integrity_warning"


def _legacy_review_records(path: Path) -> tuple[list[ReviewRecord], list[Any]]:
    """The review records sitting in `collaboration.json`, as `(valid, malformed)`.

    Validated one by one: JSON-held records are untrusted input, and a
    single malformed entry must not stop the rest from being handled — or
    stop the file from ever being cleaned, which would make every read that
    derives Human Review state fail from then on.
    """
    if not path.exists() or '"review_records"' not in path.read_text():
        return [], []
    data = _read_collaboration_json(path)
    raw_records = data.get("review_records") if isinstance(data, dict) else None
    if not raw_records:
        return [], []
    if not isinstance(raw_records, list):
        return [], [raw_records]
    valid: list[ReviewRecord] = []
    malformed: list[Any] = []
    for raw in raw_records:
        try:
            valid.append(ReviewRecord.model_validate(raw))
        except ValidationError:
            malformed.append(raw)
    return _latest_by_id(valid, "id"), malformed


def _strip_legacy_review_records(path: Path) -> None:
    # re-read right before writing, so contributors/comments another
    # process saved since the migration started aren't overwritten
    data = _read_collaboration_json(path)
    if not isinstance(data, dict) or "review_records" not in data:
        return
    data.pop("review_records")
    _write_collaboration_json(path, json.dumps(data, indent=2))


def _warn_ignored_review_records(
    store: ProjectStore, conn: sqlite3.Connection, *, injected: list[ReviewRecord], malformed: list[Any]
) -> None:
    if not injected and not malformed:
        return
    append_event(
        store,
        REVIEW_HISTORY_INTEGRITY_WARNING,
        f"ignored {len(injected) + len(malformed)} review record(s) found in collaboration.json "
        f"({len(injected)} unknown, {len(malformed)} malformed); "
        "Human Review decisions are never read from JSON",
        payload={"records": [record.model_dump(mode="json") for record in injected], "malformed": malformed},
        conn=conn,
    )


def _migrate_legacy_review_records(store: ProjectStore, conn: sqlite3.Connection | None = None) -> None:
    """Move review records out of a pre-#33 `collaboration.json` into `review_history` — once.

    The migration is one-shot: it runs in the same transaction that sets
    `project_meta.review_history_migrated`, and never again after. Review
    records that turn up in the JSON after that are not Human Review
    decisions — nothing legitimate writes them there any more — so they
    are never appended (an append-only row could never be taken back).
    Records whose ids are already in the history are leftovers of the
    migration itself (it committed, but the JSON strip didn't happen yet)
    and are dropped quietly; any other id is recorded as a
    `review_history_integrity_warning` event carrying the raw records, then
    dropped too. A malformed record, before or after the migration, is
    never appended either: it goes into that same warning and is dropped.

    Run on a caller's transaction (`conn`), a pending migration appends
    there, and the JSON is left alone — the caller may still roll back —
    for a later call that owns its own commit to warn about anything
    malformed and strip.
    """
    path = _collaboration_path(store)
    legacy, malformed = _legacy_review_records(path)
    # called with no `conn` from inside an open transaction (a read helper,
    # say), it must still act as the caller's-transaction case: the JSON
    # can't be stripped until that transaction has actually committed
    if conn is None:
        conn = active_transaction(store)
    if conn is not None:
        if not is_review_history_migrated(conn):
            _run_review_history_migration(store, conn, legacy)
        return

    # the common case — migrated long ago, nothing in the JSON — must not
    # take the write lock on what is usually a read path
    reader = store.connect()
    try:
        migrated = is_review_history_migrated(reader)
    finally:
        reader.close()
    if migrated and not legacy and not malformed:
        return

    with store.transaction() as tx:
        if not is_review_history_migrated(tx):
            _run_review_history_migration(store, tx, legacy)
            injected: list[ReviewRecord] = []
        else:
            injected = [record for record in legacy if not review_history_row_exists(tx, record.id)]
        _warn_ignored_review_records(store, tx, injected=injected, malformed=malformed)
    _strip_legacy_review_records(path)


def _run_review_history_migration(store: ProjectStore, conn: sqlite3.Connection, legacy: list[ReviewRecord]) -> None:
    migrated = [record.id for record in legacy if _append_legacy_record(conn, record)]
    mark_review_history_migrated(conn)
    if migrated:
        from .authority import review_history_changed

        review_history_changed(store, conn)  # these decisions still have to reach reviews.jsonl
    if migrated:
        append_event(
            store,
            "collaboration_review_history_migrated",
            f"migrated {len(migrated)} review record(s) from collaboration.json into review history",
            payload={"review_ids": migrated},
            conn=conn,
        )


def list_review_history_integrity_warnings(store: ProjectStore) -> list[EventRecord]:
    """Every time review records in `collaboration.json` were ignored —
    found after the one-shot migration, or malformed — a sign someone
    tried to write a decision around Human Review."""
    _migrate_legacy_review_records(store)
    return [event for event in list_events(store) if event.kind == REVIEW_HISTORY_INTEGRITY_WARNING]


def record_review_request(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    *,
    reviewer_id: str,
    rationale: str = "",
    authorship: list[str] | None = None,
    provenance_notes: str = "",
    kind: ReviewRecordKind | None = None,
    conn: sqlite3.Connection | None = None,
) -> ReviewRecord:
    _migrate_legacy_review_records(store, conn)
    _refuse_if_trust_bearing(object_type, kind)
    record = ReviewRecord(
        object_type=object_type,
        object_id=object_id,
        reviewer_id=reviewer_id,
        decision=ReviewGovernanceState.proposed_for_review,
        kind=kind,
        rationale=rationale,
        authorship=list(authorship or []),
        provenance_notes=provenance_notes,
    )
    with in_transaction(store, conn) as tx:
        insert_review_history_row(tx, _request_row(record))
        append_event(
            store,
            "collaboration_review_requested",
            f"requested review for {object_type} {object_id}",
            entity_id=object_id,
            payload=record.model_dump(mode="json"),
            conn=tx,
        )
    return record


def record_review_decision(
    store: ProjectStore,
    review_id: str,
    decision: ReviewGovernanceState,
    *,
    reviewer_id: str,
    rationale: str = "",
    conn: sqlite3.Connection | None = None,
) -> ReviewRecord:
    """Append a decision on an existing review request. The request row is
    never modified; the returned record is the review as it now reads.

    A trust-bearing review (any `kind`, or an object type a derived axis
    reads) is refused outright: those are Human Review decisions, recorded in
    the node's reviews.jsonl from the proof map page (ADR-0010), never in
    this generic, editorial history."""
    _migrate_legacy_review_records(store, conn)
    def _current(tx: sqlite3.Connection) -> ReviewRecord | None:
        rows = list_review_history_rows(store, review_id=review_id, conn=tx)
        folded = _fold_review_history(_row_to_history_entry(row) for row in rows)
        return folded[0] if folded else None

    with in_transaction(store, conn) as tx:
        record = _current(tx)
        if record is None:
            raise KeyError(review_id)
        _refuse_if_trust_bearing(record.object_type, record.kind)
        insert_review_history_row(
            tx,
            _decision_row(
                record,
                decision,
                reviewer_id=reviewer_id,
                rationale=rationale,
                created_at=utc_now(),
            ),
        )
        record = _current(tx)
        append_event(
            store,
            "collaboration_review_decided",
            f"review {review_id} -> {decision.value}",
            entity_id=record.object_id,
            payload=record.model_dump(mode="json"),
            conn=tx,
        )
    return record


def record_decided_review(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    decision: ReviewGovernanceState,
    *,
    reviewer_id: str,
    rationale: str = "",
    authorship: list[str] | None = None,
    provenance_notes: str = "",
    kind: ReviewRecordKind | None = None,
    conn: sqlite3.Connection | None = None,
) -> ReviewRecord:
    """A review requested and decided in one step: both rows land in the same
    transaction (the caller's, if given), so there is never a moment — not
    even after a crash — when the request exists without its decision."""
    with in_transaction(store, conn) as tx:
        request = record_review_request(
            store,
            object_type,
            object_id,
            reviewer_id=reviewer_id,
            rationale=rationale,
            authorship=authorship,
            provenance_notes=provenance_notes,
            kind=kind,
            conn=tx,
        )
        return record_review_decision(
            store,
            request.id,
            decision,
            reviewer_id=reviewer_id,
            rationale=rationale,
            conn=tx,
        )


def _refuse_if_trust_bearing(object_type: str, kind: ReviewRecordKind | None) -> None:
    """A review a derived Human Review axis would read is never recorded here (ADR-0010).

    Those decisions are the proof map's, written to the git-tracked
    reviews.jsonl by `authority.record_decision` from the proof map page;
    this generic review history keeps only the untrusted, editorial kind.
    """
    if kind is not None or object_type in TRUST_BEARING_OBJECT_TYPES:
        raise human_review_required(kind or object_type, object_type)


def import_review_records(store: ProjectStore, records: Iterable[ReviewRecord]) -> tuple[list[str], list[str]]:
    """Append another project's review records to the local history, for exchange import.

    Only non-trust-bearing reviews are taken; a record that could feed a
    derived Human Review axis (any `kind`, or an object type the proof map
    derives state from) is refused, so an imported bundle can never forge
    — or, since nothing here overwrites, revoke — a local decision. A record
    whose id is already in the local history is skipped. Returns
    `(imported_ids, refused_ids)`.
    """
    imported: list[str] = []
    refused: list[str] = []
    candidates = list(records)
    if not candidates:
        return imported, refused
    _migrate_legacy_review_records(store)
    with store.transaction() as conn:
        for record in _latest_by_id(candidates, "id"):
            if is_trust_bearing_review(record):
                refused.append(record.id)
            elif _append_legacy_record(conn, record):
                imported.append(record.id)
    return imported, refused


TRUST_BEARING_OBJECT_TYPES = frozenset({"proof_map_node", "evidence_check", "challenge", "claim", "legacy_item"})


def is_trust_bearing_review(record: ReviewRecord) -> bool:
    """Whether this review feeds a derived proof-map axis, and so may only be
    written by its own Human Review service function (never the generic
    `proof review` commands, never an import)."""
    return record.kind is not None or record.object_type in TRUST_BEARING_OBJECT_TYPES


def list_review_history(store: ProjectStore, *, object_type: str = "", object_id: str = "", review_id: str = "") -> list[ReviewHistoryEntry]:
    """The raw append-only rows, in append order."""
    _migrate_legacy_review_records(store)
    return [
        _row_to_history_entry(row)
        for row in list_review_history_rows(store, object_type=object_type, object_id=object_id, review_id=review_id)
    ]


def list_review_records(store: ProjectStore, *, object_type: str = "", object_id: str = "") -> list[ReviewRecord]:
    """Every review: the generic ones in review_history, then the proof map's Human Review
    decisions from the git-tracked reviews.jsonl files (ADR-0010)."""
    from .authority import list_decisions

    records = _fold_review_history(list_review_history(store, object_type=object_type, object_id=object_id))
    for row in list_decisions(store):
        if (object_type and row["object_type"] != object_type) or (object_id and row["object_id"] != object_id):
            continue
        records.append(
            ReviewRecord(
                id=row["review_id"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                reviewer_id=row["reviewer_id"],
                decision=ReviewGovernanceState(row["decision"]),
                kind=ReviewRecordKind(row["kind"]),
                rationale=row["rationale"],
                created_at=row["created_at"],
                updated_at=row["created_at"],
                decision_row_id=row["id"],
            )
        )
    return records


def get_review_record(store: ProjectStore, review_id: str) -> ReviewRecord | None:
    folded = _fold_review_history(list_review_history(store, review_id=review_id))
    if folded:
        return folded[0]
    return next((record for record in list_review_records(store) if record.id == review_id), None)


def ensure_comment_thread(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    *,
    created_by: str = "human",
    notes: str = "",
) -> CommentThread:
    state = load_collaboration(store)
    existing = next((thread for thread in state.comment_threads if thread.object_type == object_type and thread.object_id == object_id), None)
    if existing is not None:
        return existing
    thread = CommentThread(object_type=object_type, object_id=object_id, created_by=created_by, notes=notes)
    state.comment_threads.append(thread)
    _update_state(
        store,
        state,
        event_kind="collaboration_thread_created",
        message=f"created comment thread for {object_type} {object_id}",
        entity_id=object_id,
        payload=thread.model_dump(mode="json"),
    )
    return thread


def add_comment(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    *,
    author_id: str,
    content: str,
    thread_id: str = "",
    status: CommentThreadStatus = CommentThreadStatus.open,
) -> Comment:
    state = load_collaboration(store)
    thread = None
    if thread_id:
        thread = next((item for item in state.comment_threads if item.id == thread_id), None)
    if thread is None:
        state = load_collaboration(store)
        ensure_comment_thread(store, object_type, object_id, created_by=author_id)
        state = load_collaboration(store)
        thread = next((item for item in state.comment_threads if item.object_type == object_type and item.object_id == object_id), None)
    if thread is None:
        raise KeyError(f"comment thread not found for {object_type} {object_id}")
    if author_id not in thread.participants:
        thread.participants.append(author_id)
    thread.status = status
    thread.updated_at = utc_now()
    comment = Comment(thread_id=thread.id, author_id=author_id, content=content, status=status)
    state.comments.append(comment)
    _update_state(
        store,
        state,
        event_kind="collaboration_comment_added",
        message=f"added comment to {thread.id}",
        entity_id=object_id,
        payload={"thread": thread.model_dump(mode="json"), "comment": comment.model_dump(mode="json")},
    )
    return comment


def list_comment_threads(store: ProjectStore, *, object_type: str = "", object_id: str = "") -> list[CommentThread]:
    state = load_collaboration(store)
    threads = _latest_by_id(state.comment_threads, "id")
    if object_type:
        threads = [thread for thread in threads if thread.object_type == object_type]
    if object_id:
        threads = [thread for thread in threads if thread.object_id == object_id]
    return threads


def list_comments(store: ProjectStore, *, thread_id: str = "", object_type: str = "", object_id: str = "") -> list[Comment]:
    state = load_collaboration(store)
    comments = _latest_by_id(state.comments, "id")
    if thread_id:
        comments = [comment for comment in comments if comment.thread_id == thread_id]
    if object_type or object_id:
        thread_ids = {
            thread.id
            for thread in list_comment_threads(store, object_type=object_type, object_id=object_id)
        }
        comments = [comment for comment in comments if comment.thread_id in thread_ids]
    return comments


def create_branch(
    store: ProjectStore,
    scope: str,
    name: str,
    *,
    created_by: str = "human",
    derived_from: str | None = None,
    notes: str = "",
    downstream_asset_ids: list[str] | None = None,
) -> BranchRecord:
    state = load_collaboration(store)
    branch = BranchRecord(
        scope=scope,
        name=name,
        created_by=created_by,
        derived_from=derived_from,
        notes=notes,
        downstream_asset_ids=list(downstream_asset_ids or []),
    )
    state.branches.append(branch)
    _update_state(
        store,
        state,
        event_kind="collaboration_branch_created",
        message=f"created branch {branch.name}",
        entity_id=scope,
        payload=branch.model_dump(mode="json"),
    )
    return branch


def list_branches(store: ProjectStore, *, scope: str = "", status: str = "") -> list[BranchRecord]:
    state = load_collaboration(store)
    branches = _latest_by_id(state.branches, "id")
    if scope:
        branches = [branch for branch in branches if branch.scope == scope]
    if status:
        branches = [branch for branch in branches if branch.status.value == status]
    return branches


def get_branch(store: ProjectStore, branch_id: str) -> BranchRecord | None:
    state = load_collaboration(store)
    for branch in reversed(state.branches):
        if branch.id == branch_id:
            return branch
    return None


class BranchComparison(BaseModel):
    left_branch_id: str
    right_branch_id: str
    same_scope: bool
    same_status: bool
    shared_downstream_asset_ids: list[str] = Field(default_factory=list)
    left_only_asset_ids: list[str] = Field(default_factory=list)
    right_only_asset_ids: list[str] = Field(default_factory=list)
    summary: str = ""


def compare_branches(store: ProjectStore, left_branch_id: str, right_branch_id: str) -> BranchComparison:
    left = get_branch(store, left_branch_id)
    right = get_branch(store, right_branch_id)
    if left is None:
        raise KeyError(left_branch_id)
    if right is None:
        raise KeyError(right_branch_id)
    left_assets = set(left.downstream_asset_ids)
    right_assets = set(right.downstream_asset_ids)
    shared = sorted(left_assets & right_assets)
    left_only = sorted(left_assets - right_assets)
    right_only = sorted(right_assets - left_assets)
    summary = (
        f"{left.name} vs {right.name}: "
        f"shared={len(shared)} left_only={len(left_only)} right_only={len(right_only)}"
    )
    return BranchComparison(
        left_branch_id=left_branch_id,
        right_branch_id=right_branch_id,
        same_scope=left.scope == right.scope,
        same_status=left.status == right.status,
        shared_downstream_asset_ids=shared,
        left_only_asset_ids=left_only,
        right_only_asset_ids=right_only,
        summary=summary,
    )


def merge_branch(
    store: ProjectStore,
    branch_id: str,
    *,
    into_branch_id: str | None = None,
    reviewer_id: str = "human",
    rationale: str = "",
) -> BranchRecord:
    state = load_collaboration(store)
    source = next((item for item in state.branches if item.id == branch_id), None)
    if source is None:
        raise KeyError(branch_id)
    source.status = BranchStatus.merged
    source.updated_at = utc_now()
    if into_branch_id:
        target = next((item for item in state.branches if item.id == into_branch_id), None)
        if target is None:
            raise KeyError(into_branch_id)
        for asset_id in source.downstream_asset_ids:
            if asset_id not in target.downstream_asset_ids:
                target.downstream_asset_ids.append(asset_id)
        target.updated_at = utc_now()
    _update_state(
        store,
        state,
        event_kind="collaboration_branch_merged",
        message=f"merged branch {branch_id}",
        entity_id=branch_id,
        payload={"branch": source.model_dump(mode="json"), "into_branch_id": into_branch_id, "reviewer_id": reviewer_id, "rationale": rationale},
    )
    return source


def publish_shared_asset(
    store: ProjectStore,
    asset_id: str,
    *,
    published_to: str,
    created_by: str = "human",
    approved_by: list[str] | None = None,
    status: SharedAssetPublicationStatus = SharedAssetPublicationStatus.approved,
    provenance_notes: str = "",
) -> SharedAssetPublication:
    state = load_collaboration(store)
    publication = SharedAssetPublication(
        asset_id=asset_id,
        published_to=published_to,
        created_by=created_by,
        approved_by=list(approved_by or []),
        status=status,
        provenance_notes=provenance_notes,
    )
    state.publications.append(publication)
    _update_state(
        store,
        state,
        event_kind="collaboration_publication_recorded",
        message=f"recorded publication for {asset_id}",
        entity_id=asset_id,
        payload=publication.model_dump(mode="json"),
    )
    return publication


def list_publications(store: ProjectStore, *, asset_id: str = "", published_to: str = "") -> list[SharedAssetPublication]:
    state = load_collaboration(store)
    publications = _latest_by_id(state.publications, "id")
    if asset_id:
        publications = [publication for publication in publications if publication.asset_id == asset_id]
    if published_to:
        publications = [publication for publication in publications if publication.published_to == published_to]
    return publications


def set_collaboration_policy(
    store: ProjectStore,
    *,
    team_id: str = "",
    name: str = "default",
    who_can_propose: list[str] | None = None,
    who_can_approve: list[str] | None = None,
    who_can_publish: list[str] | None = None,
    who_can_resolve_disputes: list[str] | None = None,
    one_reviewer_objects: list[str] | None = None,
    two_reviewer_objects: list[str] | None = None,
    notes: str = "",
) -> CollaborationPolicy:
    state = load_collaboration(store)
    policy = CollaborationPolicy(
        project_id=state.project_id,
        team_id=team_id,
        name=name,
        who_can_propose=list(who_can_propose or ["maintainer", "reviewer", "contributor"]),
        who_can_approve=list(who_can_approve or ["maintainer", "reviewer"]),
        who_can_publish=list(who_can_publish or ["maintainer"]),
        who_can_resolve_disputes=list(who_can_resolve_disputes or ["maintainer", "reviewer"]),
        one_reviewer_objects=list(one_reviewer_objects or []),
        two_reviewer_objects=list(two_reviewer_objects or []),
        notes=notes,
    )
    state.policies.append(policy)
    _update_state(
        store,
        state,
        event_kind="collaboration_policy_updated",
        message=f"set collaboration policy {policy.name}",
        entity_id=policy.project_id,
        payload=policy.model_dump(mode="json"),
    )
    return policy


def summarize_contributor(contributor: Contributor) -> str:
    teams = f" teams={','.join(contributor.team_ids)}" if contributor.team_ids else ""
    notes = f" - {contributor.notes}" if contributor.notes else ""
    return f"{contributor.id}: {contributor.display_name} [{contributor.role.value}/{contributor.status.value}]{teams}{notes}"


def summarize_review_record(record: ReviewRecord) -> str:
    kind = f" kind={record.kind.value}" if record.kind is not None else ""
    return f"{record.id}: {record.object_type}/{record.object_id} [{record.decision.value}]{kind} reviewer={record.reviewer_id}"


def summarize_comment_thread(thread: CommentThread) -> str:
    participants = ",".join(thread.participants) or "none"
    return f"{thread.id}: {thread.object_type}/{thread.object_id} [{thread.status.value}] participants={participants}"


def summarize_comment(comment: Comment) -> str:
    note = comment.content.replace("\n", " ").strip()
    return f"{comment.id}: thread={comment.thread_id} author={comment.author_id} {note}"


def summarize_branch(branch: BranchRecord) -> str:
    derived = f" derived_from={branch.derived_from}" if branch.derived_from else ""
    downstream = f" downstream={','.join(branch.downstream_asset_ids)}" if branch.downstream_asset_ids else ""
    notes = f" - {branch.notes}" if branch.notes else ""
    return f"{branch.id}: {branch.name} [{branch.scope}/{branch.status.value}] created_by={branch.created_by}{derived}{downstream}{notes}"


def summarize_publication(publication: SharedAssetPublication) -> str:
    approvers = ",".join(publication.approved_by) or "none"
    notes = f" - {publication.provenance_notes}" if publication.provenance_notes else ""
    return f"{publication.id}: {publication.asset_id} -> {publication.published_to} [{publication.status.value}] approved_by={approvers}{notes}"


def summarize_policy(policy: CollaborationPolicy) -> str:
    return (
        f"{policy.name}: project={policy.project_id} team={policy.team_id or 'none'} "
        f"propose={','.join(policy.who_can_propose)} approve={','.join(policy.who_can_approve)} "
        f"publish={','.join(policy.who_can_publish)}"
    )


def summarize_state(store: ProjectStore) -> str:
    state = load_collaboration(store)
    lines = [f"Collaboration: project={state.project_id}"]
    lines.append("Contributors:")
    if state.contributors:
        lines.extend(f"- {summarize_contributor(contributor)}" for contributor in state.contributors)
    else:
        lines.append("- none")
    lines.append("Reviews:")
    if state.review_records:
        lines.extend(f"- {summarize_review_record(record)}" for record in state.review_records)
    else:
        lines.append("- none")
    lines.append("Comments:")
    if state.comment_threads:
        for thread in state.comment_threads:
            lines.append(f"- {summarize_comment_thread(thread)}")
    else:
        lines.append("- none")
    lines.append("Branches:")
    if state.branches:
        lines.extend(f"- {summarize_branch(branch)}" for branch in state.branches)
    else:
        lines.append("- none")
    lines.append("Publications:")
    if state.publications:
        lines.extend(f"- {summarize_publication(publication)}" for publication in state.publications)
    else:
        lines.append("- none")
    lines.append("Policies:")
    if state.policies:
        lines.extend(f"- {summarize_policy(policy)}" for policy in state.policies)
    else:
        lines.append("- none")
    return "\n".join(lines)


__all__ = [
    "BranchComparison",
    "BranchRecord",
    "BranchStatus",
    "CollaborationPolicy",
    "CollaborationRole",
    "CollaborationState",
    "Comment",
    "CommentThread",
    "CommentThreadStatus",
    "Contributor",
    "ContributorStatus",
    "ReviewGovernanceState",
    "ReviewHistoryEntry",
    "ReviewRecord",
    "ReviewRecordKind",
    "SharedAssetPublication",
    "SharedAssetPublicationStatus",
    "compare_branches",
    "create_branch",
    "get_branch",
    "get_contributor",
    "get_policy",
    "get_review_record",
    "import_review_records",
    "is_trust_bearing_review",
    "list_branches",
    "list_comment_threads",
    "list_comments",
    "list_contributors",
    "list_publications",
    "list_review_history",
    "list_review_history_integrity_warnings",
    "list_review_records",
    "load_collaboration",
    "merge_branch",
    "publish_shared_asset",
    "record_decided_review",
    "record_review_decision",
    "record_review_request",
    "save_collaboration",
    "set_collaboration_policy",
    "set_contributor_role",
    "summarize_branch",
    "summarize_comment",
    "summarize_comment_thread",
    "summarize_contributor",
    "summarize_policy",
    "summarize_publication",
    "summarize_review_record",
    "summarize_state",
    "upsert_contributor",
]
