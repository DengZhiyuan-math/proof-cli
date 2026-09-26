from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, NamedTuple

from pydantic import TypeAdapter

from .db import connect, initialize
from .domain import (
    BlockerRecord,
    CandidateProofRecord,
    Challenge,
    ClaimRecord,
    DependencyPin,
    EventRecord,
    EvidenceCheck,
    ProofMapNode,
    ProofObligation,
    ProjectSnapshot,
    ProjectState,
    TheoremContract,
)
from .references import (
    ReferenceRecord,
    ReferenceReviewRecord,
    ReferenceReviewResult,
    ReferenceReviewStatus,
    ReferenceSourceType,
    ReferenceTrustLevel,
    utc_now,
)


def _dump(model) -> str:
    return model.model_dump_json()


def _load(adapter, value: str):
    return adapter.validate_json(value)


THEOREM_ADAPTER = TypeAdapter(TheoremContract)
PROOF_MAP_NODE_ADAPTER = TypeAdapter(ProofMapNode)
CANDIDATE_PROOF_ADAPTER = TypeAdapter(CandidateProofRecord)
DEPENDENCY_PIN_ADAPTER = TypeAdapter(DependencyPin)
OBLIGATION_ADAPTER = TypeAdapter(ProofObligation)
BLOCKER_ADAPTER = TypeAdapter(BlockerRecord)
SNAPSHOT_ADAPTER = TypeAdapter(ProjectSnapshot)
STATE_ADAPTER = TypeAdapter(ProjectState)
EVENT_ADAPTER = TypeAdapter(EventRecord)
REFERENCE_ADAPTER = TypeAdapter(ReferenceRecord)
REFERENCE_REVIEW_ADAPTER = TypeAdapter(ReferenceReviewRecord)

REFERENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_records (
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  review_status TEXT NOT NULL,
  trust_level TEXT NOT NULL,
  is_callable INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_reviews (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL,
  data TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reference_reviews_reference_id
  ON reference_reviews(reference_id, created_at);
"""

PROOF_MAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS proof_map_nodes (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  data TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_proof_map_nodes_one_theorem
  ON proof_map_nodes(kind)
  WHERE kind = 'theorem';

CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  claimant_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  claimed_at TEXT NOT NULL,
  released_at TEXT,
  released_by TEXT,
  release_reason TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_one_active_per_node
  ON claims(node_id)
  WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_claims_node_id ON claims(node_id, claimed_at);

CREATE TABLE IF NOT EXISTS candidate_proofs (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  file_path TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 1,
  review_record_id TEXT,
  submitted_by TEXT NOT NULL,
  scoping_rationale TEXT NOT NULL,
  interface_fingerprint TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(node_id, version)
);

CREATE INDEX IF NOT EXISTS idx_candidate_proofs_node_id ON candidate_proofs(node_id, version);

CREATE TABLE IF NOT EXISTS dependency_pins (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  target_node_id TEXT NOT NULL,
  pinned_version INTEGER,
  pinned_fingerprint TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(node_id, target_node_id)
);

CREATE INDEX IF NOT EXISTS idx_dependency_pins_node_id ON dependency_pins(node_id);

CREATE TABLE IF NOT EXISTS challenges (
  id TEXT PRIMARY KEY,
  target_node_id TEXT NOT NULL,
  status TEXT NOT NULL,
  rationale TEXT NOT NULL,
  opened_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_by TEXT,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_challenges_target_node_id ON challenges(target_node_id, status);

CREATE TABLE IF NOT EXISTS evidence_checks (
  id TEXT PRIMARY KEY,
  candidate_proof_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  notes TEXT NOT NULL,
  run_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_checks_candidate_proof_id ON evidence_checks(candidate_proof_id);

CREATE TABLE IF NOT EXISTS governance_records (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  data TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_governance_records_kind ON governance_records(kind, created_at);
"""

# Human Review history (issue #33): insert-only. A request is a row whose
# `review_id` is its own `id`; a decision is a later row carrying the
# request's `review_id`, never an edit of the request. The triggers make the
# table append-only for every writer, not just this module: UPDATE and
# DELETE abort, and so does an INSERT that would collide with an existing
# row (which `INSERT OR REPLACE` would otherwise resolve by deleting it).
REVIEW_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_history (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  review_id TEXT NOT NULL,
  entry TEXT NOT NULL CHECK (entry IN ('request', 'decision')),
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  kind TEXT,
  decision TEXT NOT NULL,
  reviewer_id TEXT NOT NULL,
  rationale TEXT NOT NULL,
  authorship TEXT NOT NULL,
  provenance_notes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  prev_row_hash TEXT,
  signed_decision TEXT,
  payload_hash TEXT,
  CHECK ((entry = 'request') = (review_id = id))
);
"""

# Added by issue #35 (ADR-0009): the hash chain link and the signed decision.
# Existing databases get them by ALTER TABLE before the triggers below, which
# reference `payload_hash`, are (re)created.
_REVIEW_HISTORY_ADDED_COLUMNS = {"prev_row_hash": "TEXT", "signed_decision": "TEXT", "payload_hash": "TEXT"}
_CHALLENGE_ADDED_COLUMNS = {"resolution_review_id": "TEXT"}

REVIEW_HISTORY_TRIGGERS = """
CREATE INDEX IF NOT EXISTS idx_review_history_object ON review_history(object_type, object_id, seq);
CREATE INDEX IF NOT EXISTS idx_review_history_review_id ON review_history(review_id, seq);
CREATE INDEX IF NOT EXISTS idx_review_history_payload_hash ON review_history(payload_hash);

CREATE TRIGGER IF NOT EXISTS review_history_no_update
BEFORE UPDATE ON review_history
BEGIN
  SELECT RAISE(ABORT, 'review_history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS review_history_no_delete
BEFORE DELETE ON review_history
BEGIN
  SELECT RAISE(ABORT, 'review_history is append-only');
END;

DROP TRIGGER IF EXISTS review_history_no_overwrite;
CREATE TRIGGER IF NOT EXISTS review_history_no_overwrite_v2
BEFORE INSERT ON review_history
WHEN EXISTS (
  SELECT 1 FROM review_history
  WHERE id = NEW.id OR seq = NEW.seq OR (NEW.payload_hash IS NOT NULL AND payload_hash = NEW.payload_hash)
)
BEGIN
  SELECT RAISE(ABORT, 'review_history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS review_history_decision_needs_request
BEFORE INSERT ON review_history
WHEN NEW.entry = 'decision' AND NOT EXISTS (
  SELECT 1 FROM review_history
  WHERE id = NEW.review_id AND entry = 'request'
    AND object_type = NEW.object_type AND object_id = NEW.object_id AND kind IS NEW.kind
)
BEGIN
  SELECT RAISE(ABORT, 'a review decision must reference an existing request for the same object');
END;
"""

# The Reviewer key registry (ADR-0009 point 5): append-only and hash-chained
# like review_history. A revoke row repeats the revoked key's fields.
REVIEWER_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviewer_keys (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  entry TEXT NOT NULL CHECK (entry IN ('enroll', 'revoke')),
  credential_id TEXT NOT NULL,
  public_key_spki TEXT NOT NULL,
  alg INTEGER NOT NULL,
  fingerprint TEXT NOT NULL,
  display_name TEXT NOT NULL,
  signed_decision TEXT NOT NULL,
  prev_row_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS reviewer_keys_no_update
BEFORE UPDATE ON reviewer_keys
BEGIN
  SELECT RAISE(ABORT, 'reviewer_keys is append-only');
END;

CREATE TRIGGER IF NOT EXISTS reviewer_keys_no_delete
BEFORE DELETE ON reviewer_keys
BEGIN
  SELECT RAISE(ABORT, 'reviewer_keys is append-only');
END;

CREATE TRIGGER IF NOT EXISTS reviewer_keys_no_overwrite
BEFORE INSERT ON reviewer_keys
WHEN EXISTS (SELECT 1 FROM reviewer_keys WHERE id = NEW.id OR seq = NEW.seq)
BEGIN
  SELECT RAISE(ABORT, 'reviewer_keys is append-only');
END;
"""

# The first link of every hash chain.
GENESIS_ROW_HASH = "0" * 64


def chain_row_hash(row: dict) -> str:
    """SHA-256 over a stored row's canonical JSON — every column, `seq` and
    `prev_row_hash` included, so editing, reordering or re-linking any row
    changes its hash and breaks the next row's link."""
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")


def _last_row_hash(conn: sqlite3.Connection, table: str) -> str:
    last = conn.execute(f"SELECT * FROM {table} ORDER BY seq DESC LIMIT 1").fetchone()
    return chain_row_hash(dict(last)) if last is not None else GENESIS_ROW_HASH


class _ActiveTransaction(NamedTuple):
    db_path: Path
    thread_id: int
    conn: sqlite3.Connection


# The write transaction this thread currently holds open. A nested
# `store.transaction()` — or a `_writing` helper called without `conn` —
# joins it instead of opening a second connection that would wait on this
# one's own write lock until the busy timeout expired. Keyed by resolved
# database path and by thread: a task or worker thread that copies this
# context never picks up a connection belonging to another thread.
#
# Only helpers that go through `_writing` join. The older helpers that open
# `store.connect()` and commit it themselves (write_state, store_contract,
# ...) must not be called inside a transaction.
_ACTIVE_TRANSACTION: ContextVar[_ActiveTransaction | None] = ContextVar("proof_cli_active_transaction", default=None)


@dataclass
class ProjectStore:
    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / ".proof" / "project.sqlite3"

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        initialize(conn)
        conn.executescript(REFERENCE_SCHEMA)
        conn.executescript(PROOF_MAP_SCHEMA)
        conn.executescript(REVIEW_HISTORY_SCHEMA)
        _add_missing_columns(conn, "review_history", _REVIEW_HISTORY_ADDED_COLUMNS)
        _add_missing_columns(conn, "challenges", _CHALLENGE_ADDED_COLUMNS)
        conn.executescript(REVIEW_HISTORY_TRIGGERS)
        conn.executescript(REVIEWER_KEYS_SCHEMA)
        conn.commit()
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One SQLite write transaction: every write made on the yielded
        connection commits together, or — on any exception — none do.

        `BEGIN IMMEDIATE` takes the write lock up front, so a concurrent
        writer waits on the busy timeout instead of failing mid-transaction
        when a deferred read lock can't be upgraded.

        Nested inside another `transaction()` on the same database in the
        same thread, it joins the outer one as a SAVEPOINT: an exception out
        of the nested block undoes the nested block's writes, and whatever
        it did write only commits when the outer transaction does — so code
        after a nested `transaction()` must not assume its writes are
        durable yet (see `active_transaction`).
        """
        joined = active_transaction(self)
        if joined is not None:
            savepoint = f"nested_{uuid.uuid4().hex}"
            joined.execute(f"SAVEPOINT {savepoint}")
            try:
                yield joined
            except BaseException:
                joined.execute(f"ROLLBACK TO {savepoint}")
                joined.execute(f"RELEASE {savepoint}")
                raise
            joined.execute(f"RELEASE {savepoint}")
            return
        conn = self.connect()
        token = _ACTIVE_TRANSACTION.set(_ActiveTransaction(self.db_path.resolve(), threading.get_ident(), conn))
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            _ACTIVE_TRANSACTION.reset(token)
            conn.close()


def active_transaction(store: ProjectStore) -> sqlite3.Connection | None:
    """The `store.transaction()` connection this thread currently holds open, if any.

    Code with a side effect outside SQLite that must only happen once its
    writes are committed (the review-history migration's JSON strip, say)
    checks this to know whether it is running inside someone else's
    transaction.
    """
    active = _ACTIVE_TRANSACTION.get()
    if active is not None and active.thread_id == threading.get_ident() and active.db_path == store.db_path.resolve():
        return active.conn
    return None


@contextmanager
def in_transaction(store: ProjectStore, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Join the caller's `store.transaction()` if it passed one, else open one."""
    if conn is not None:
        yield conn
        return
    with store.transaction() as own:
        yield own


@contextmanager
def _writing(store: ProjectStore, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """The connection a write helper should use: the caller's, inside its
    `store.transaction()` (left for the caller to commit), or else its own,
    committed on success. With no `conn` inside an open `store.transaction()`,
    it joins that transaction."""
    if conn is None:
        conn = active_transaction(store)
    if conn is not None:
        yield conn
        return
    own = store.connect()
    try:
        yield own
        own.commit()
    finally:
        own.close()


def project_proof_dir(store: ProjectStore) -> Path:
    return store.root / ".proof"


def collaboration_state_path(store: ProjectStore) -> Path:
    return project_proof_dir(store) / "collaboration.json"


REVIEW_HISTORY_MIGRATED_KEY = "review_history_migrated"


def is_review_history_migrated(conn: sqlite3.Connection) -> bool:
    """Whether this project's one-shot `collaboration.json` → `review_history`
    migration (issue #33) has already run."""
    row = conn.execute("SELECT 1 FROM project_meta WHERE key = ? LIMIT 1", (REVIEW_HISTORY_MIGRATED_KEY,)).fetchone()
    return row is not None


def mark_review_history_migrated(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO project_meta(key, value) VALUES (?, ?)",
        (REVIEW_HISTORY_MIGRATED_KEY, utc_now().isoformat()),
    )


def create_project(root: str | Path, project_id: str) -> ProjectStore:
    store = ProjectStore(Path(root))
    with store.connect() as conn:
        existing = conn.execute("SELECT value FROM project_meta WHERE key = ?", ("project_id",)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO project_meta(key, value) VALUES (?, ?)",
                ("project_id", project_id),
            )
            if not collaboration_state_path(store).exists():
                # a brand-new project has no JSON-era review records, so its
                # one-shot migration is done before it ever starts
                mark_review_history_migrated(conn)
        state_row = conn.execute("SELECT data FROM state WHERE project_id = ?", (project_id,)).fetchone()
        if state_row is None:
            state = ProjectState(project_id=project_id)
            conn.execute(
                "INSERT INTO state(project_id, data) VALUES (?, ?)",
                (project_id, state.model_dump_json()),
            )
        conn.commit()
    return store


def set_project_id(store: ProjectStore, project_id: str) -> None:
    """Force the project's own id in `project_meta`, overwriting whatever was there.

    Unlike `create_project`'s `INSERT`-if-absent, this always overwrites —
    exchange import (issue #31) uses it to retarget a project onto an
    imported bundle's project id even when the target already has one.
    """
    with store.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO project_meta(key, value) VALUES (?, ?)", ("project_id", project_id))
        conn.commit()


def load_project(root: str | Path) -> ProjectStore:
    store = ProjectStore(Path(root))
    with store.connect():
        pass
    return store


def read_state(store: ProjectStore) -> ProjectState:
    with store.connect() as conn:
        row = conn.execute("SELECT data FROM state LIMIT 1").fetchone()
        if row is None:
            raise ValueError("project state not found")
        return STATE_ADAPTER.validate_json(row["data"])


def write_state(store: ProjectStore, state: ProjectState) -> None:
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO state(project_id, data) VALUES (?, ?)",
            (state.project_id, state.model_dump_json()),
        )
        conn.commit()


def append_event(
    store: ProjectStore,
    kind: str,
    message: str,
    *,
    entity_id: str | None = None,
    payload: dict | None = None,
    conn: sqlite3.Connection | None = None,
) -> EventRecord:
    event = EventRecord(
        id=str(uuid.uuid4()),
        kind=kind,
        entity_id=entity_id,
        message=message,
        payload=payload or {},
    )
    with _writing(store, conn) as conn:
        conn.execute(
            "INSERT INTO events(id, kind, entity_id, message, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.kind,
                event.entity_id,
                event.message,
                json.dumps(
                    event.payload,
                    default=lambda o: o.isoformat() if hasattr(o, "isoformat") else (o.value if hasattr(o, "value") else str(o)),
                ),
                event.created_at.isoformat(),
            ),
        )
    return event


def store_contract(store: ProjectStore, contract: TheoremContract) -> TheoremContract:
    with store.connect() as conn:
        current = conn.execute(
            "SELECT MAX(version) AS version FROM theorem_contracts WHERE id = ?",
            (contract.id,),
        ).fetchone()
        current_version = int(current["version"]) if current and current["version"] is not None else 0
        contract.version = current_version + 1
        conn.execute(
            "UPDATE theorem_contracts SET is_current = 0 WHERE id = ?",
            (contract.id,),
        )
        conn.execute(
            "INSERT INTO theorem_contracts(id, version, is_current, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                contract.id,
                contract.version,
                1,
                contract.model_dump_json(),
                contract.created_at.isoformat(),
                contract.updated_at.isoformat(),
            ),
        )
        conn.commit()
    return contract


def import_theorem_contract(store: ProjectStore, contract: TheoremContract) -> TheoremContract:
    """Reinsert an already-versioned contract exactly as given, for exchange import fidelity (issue #31).

    `store_contract` always bumps `version` and appends a new row — right
    for normal writes, wrong for import, which must reproduce exactly what
    was exported rather than mint yet another version on top of it. Keyed
    on `(id, version)`, so re-importing the same bundle twice updates the
    same row rather than erroring or duplicating.
    """
    with store.connect() as conn:
        conn.execute("UPDATE theorem_contracts SET is_current = 0 WHERE id = ?", (contract.id,))
        conn.execute(
            """
            INSERT INTO theorem_contracts(id, version, is_current, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id, version) DO UPDATE SET
              is_current = excluded.is_current,
              data = excluded.data,
              created_at = excluded.created_at,
              updated_at = excluded.updated_at
            """,
            (
                contract.id,
                contract.version,
                1,
                contract.model_dump_json(),
                contract.created_at.isoformat(),
                contract.updated_at.isoformat(),
            ),
        )
        conn.commit()
    return contract


def update_contract(store: ProjectStore, contract: TheoremContract) -> TheoremContract:
    return store_contract(store, contract)


def list_contracts(store: ProjectStore) -> list[TheoremContract]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT data FROM theorem_contracts
            WHERE is_current = 1
            ORDER BY id
            """
        ).fetchall()
    return [THEOREM_ADAPTER.validate_json(row["data"]) for row in rows]


def get_contract(store: ProjectStore, contract_id: str) -> TheoremContract | None:
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT data FROM theorem_contracts
            WHERE id = ? AND is_current = 1
            ORDER BY version DESC
            LIMIT 1
            """,
            (contract_id,),
        ).fetchone()
    return THEOREM_ADAPTER.validate_json(row["data"]) if row else None


def list_events(store: ProjectStore) -> list[EventRecord]:
    with store.connect() as conn:
        rows = conn.execute("SELECT id, kind, entity_id, message, payload, created_at FROM events ORDER BY created_at").fetchall()
    events: list[EventRecord] = []
    for row in rows:
        events.append(
            EventRecord(
                id=row["id"],
                kind=row["kind"],
                entity_id=row["entity_id"],
                message=row["message"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
        )
    return events


def _upsert_reference(store: ProjectStore, reference: ReferenceRecord) -> ReferenceRecord:
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO reference_records(id, data, review_status, trust_level, is_callable, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              data = excluded.data,
              review_status = excluded.review_status,
              trust_level = excluded.trust_level,
              is_callable = excluded.is_callable,
              updated_at = excluded.updated_at
            """,
            (
                reference.id,
                reference.model_dump_json(),
                reference.review_status.value,
                reference.trust_level.value,
                int(reference.is_callable),
                reference.created_at.isoformat(),
                reference.updated_at.isoformat(),
            ),
        )
        conn.commit()
    return reference


def _append_reference_review(store: ProjectStore, review: ReferenceReviewRecord) -> ReferenceReviewRecord:
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO reference_reviews(id, reference_id, data, created_at) VALUES (?, ?, ?, ?)",
            (
                review.id,
                review.reference_id,
                review.model_dump_json(),
                review.created_at.isoformat(),
            ),
        )
        conn.commit()
    return review


def import_reference_review(store: ProjectStore, review: ReferenceReviewRecord) -> ReferenceReviewRecord:
    """Reinsert an already-constructed reference review record for exchange import fidelity (issue #31).

    `_append_reference_review` always mints a fresh row for a brand-new
    review decision; import needs to reproduce an existing one's exact id
    and timestamp instead, so `id` upserts rather than erroring on a
    re-import of the same bundle.
    """
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO reference_reviews(id, reference_id, data, created_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              reference_id = excluded.reference_id,
              data = excluded.data,
              created_at = excluded.created_at
            """,
            (review.id, review.reference_id, review.model_dump_json(), review.created_at.isoformat()),
        )
        conn.commit()
    return review


def _reference_trust_level(reference: ReferenceRecord, review_status: ReferenceReviewStatus) -> ReferenceTrustLevel:
    if review_status != ReferenceReviewStatus.approved:
        return reference.trust_level
    if reference.trust_level == ReferenceTrustLevel.foundational:
        return reference.trust_level
    if reference.source_type == ReferenceSourceType.standard_reference:
        return ReferenceTrustLevel.standard_reference
    return ReferenceTrustLevel.external_research_source


def store_reference(store: ProjectStore, reference: ReferenceRecord) -> ReferenceRecord:
    return _upsert_reference(store, reference)


def import_reference(store: ProjectStore, reference: ReferenceRecord) -> ReferenceRecord:
    candidate = reference.model_copy(
        update={
            "review_status": ReferenceReviewStatus.candidate,
            "is_callable": False,
            "updated_at": utc_now(),
        }
    )
    stored = _upsert_reference(store, candidate)
    review = ReferenceReviewRecord(
        id=str(uuid.uuid4()),
        reference_id=stored.id,
        previous_status=None,
        review_status=ReferenceReviewStatus.candidate,
        trust_level=stored.trust_level,
        is_callable=False,
        reviewer="system",
        rationale="imported candidate reference",
    )
    _append_reference_review(store, review)
    append_event(
        store,
        "reference_imported",
        f"imported reference {stored.id}",
        entity_id=stored.id,
        payload={"reference": stored.model_dump(mode="json"), "review": review.model_dump(mode="json")},
    )
    return stored


def review_reference(
    store: ProjectStore,
    reference_id: str,
    review_status: ReferenceReviewStatus,
    *,
    confirmed: bool = False,
    rationale: str = "",
    reviewer: str = "human",
) -> ReferenceReviewResult:
    if not confirmed:
        append_event(
            store,
            "reference_review_blocked",
            f"review blocked for {reference_id}: confirmation required",
            entity_id=reference_id,
            payload={"review_status": review_status.value, "reason": "confirmation required"},
        )
        return ReferenceReviewResult(False, "confirmation required")

    reference = get_reference(store, reference_id)
    if reference is None:
        return ReferenceReviewResult(False, "reference not found")

    updated = reference.model_copy(
        update={
            "review_status": review_status,
            "trust_level": _reference_trust_level(reference, review_status),
            "is_callable": review_status == ReferenceReviewStatus.approved,
            "updated_at": utc_now(),
        }
    )
    stored = _upsert_reference(store, updated)
    review = ReferenceReviewRecord(
        id=str(uuid.uuid4()),
        reference_id=stored.id,
        previous_status=reference.review_status,
        review_status=review_status,
        trust_level=stored.trust_level,
        is_callable=stored.is_callable,
        reviewer=reviewer,
        rationale=rationale,
    )
    _append_reference_review(store, review)
    event_kind = {
        ReferenceReviewStatus.approved: "reference_review_approved",
        ReferenceReviewStatus.rejected: "reference_review_rejected",
        ReferenceReviewStatus.deferred: "reference_review_deferred",
        ReferenceReviewStatus.candidate: "reference_review_candidate",
    }[review_status]
    append_event(
        store,
        event_kind,
        f"{event_kind.replace('_', ' ')} for {stored.id}",
        entity_id=stored.id,
        payload={"reference": stored.model_dump(mode="json"), "review": review.model_dump(mode="json")},
    )
    return ReferenceReviewResult(True, review_status.value)


def approve_reference(
    store: ProjectStore,
    reference_id: str,
    *,
    confirmed: bool = False,
    rationale: str = "",
    reviewer: str = "human",
) -> ReferenceReviewResult:
    return review_reference(
        store,
        reference_id,
        ReferenceReviewStatus.approved,
        confirmed=confirmed,
        rationale=rationale,
        reviewer=reviewer,
    )


def reject_reference(
    store: ProjectStore,
    reference_id: str,
    *,
    confirmed: bool = False,
    rationale: str = "",
    reviewer: str = "human",
) -> ReferenceReviewResult:
    return review_reference(
        store,
        reference_id,
        ReferenceReviewStatus.rejected,
        confirmed=confirmed,
        rationale=rationale,
        reviewer=reviewer,
    )


def defer_reference(
    store: ProjectStore,
    reference_id: str,
    *,
    confirmed: bool = False,
    rationale: str = "",
    reviewer: str = "human",
) -> ReferenceReviewResult:
    return review_reference(
        store,
        reference_id,
        ReferenceReviewStatus.deferred,
        confirmed=confirmed,
        rationale=rationale,
        reviewer=reviewer,
    )


def get_reference(store: ProjectStore, reference_id: str) -> ReferenceRecord | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT data FROM reference_records WHERE id = ? LIMIT 1",
            (reference_id,),
        ).fetchone()
    return REFERENCE_ADAPTER.validate_json(row["data"]) if row else None


def list_references(store: ProjectStore) -> list[ReferenceRecord]:
    with store.connect() as conn:
        rows = conn.execute("SELECT data FROM reference_records ORDER BY updated_at, id").fetchall()
    return [REFERENCE_ADAPTER.validate_json(row["data"]) for row in rows]


def list_reference_reviews(store: ProjectStore) -> list[ReferenceReviewRecord]:
    with store.connect() as conn:
        rows = conn.execute("SELECT data FROM reference_reviews ORDER BY created_at, id").fetchall()
    return [REFERENCE_REVIEW_ADAPTER.validate_json(row["data"]) for row in rows]


def store_obligation(store: ProjectStore, obligation: ProofObligation) -> ProofObligation:
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO obligations(id, data) VALUES (?, ?)",
            (obligation.id, obligation.model_dump_json()),
        )
        conn.commit()
    return obligation


def list_obligations(store: ProjectStore) -> list[ProofObligation]:
    with store.connect() as conn:
        rows = conn.execute("SELECT data FROM obligations ORDER BY id").fetchall()
    return [OBLIGATION_ADAPTER.validate_json(row["data"]) for row in rows]


def store_blocker(store: ProjectStore, blocker: BlockerRecord) -> BlockerRecord:
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO blockers(id, data) VALUES (?, ?)",
            (blocker.id, blocker.model_dump_json()),
        )
        conn.commit()
    return blocker


def list_blockers(store: ProjectStore) -> list[BlockerRecord]:
    with store.connect() as conn:
        rows = conn.execute("SELECT data FROM blockers ORDER BY id").fetchall()
    return [BLOCKER_ADAPTER.validate_json(row["data"]) for row in rows]


def insert_proof_map_node(store: ProjectStore, node: ProofMapNode) -> ProofMapNode:
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO proof_map_nodes(id, kind, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                node.id,
                node.kind.value,
                node.model_dump_json(),
                node.created_at.isoformat(),
                node.updated_at.isoformat(),
            ),
        )
        conn.commit()
    return node


def update_proof_map_node(store: ProjectStore, node: ProofMapNode, *, conn: sqlite3.Connection | None = None) -> ProofMapNode:
    """Overwrite an existing node's row in place.

    The only legitimate caller is Promote (issue #22) changing `kind` from
    `claim` to `lemma` on an already-Accepted node — every other ProofMapNode
    field stays whatever it already was, since nothing else in the system
    has a supported path to edit a node after creation.
    """
    with _writing(store, conn) as conn:
        conn.execute(
            "UPDATE proof_map_nodes SET kind = ?, data = ?, updated_at = ? WHERE id = ?",
            (node.kind.value, node.model_dump_json(), node.updated_at.isoformat(), node.id),
        )
    return node


def get_proof_map_node(store: ProjectStore, node_id: str) -> ProofMapNode | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT data FROM proof_map_nodes WHERE id = ? LIMIT 1",
            (node_id,),
        ).fetchone()
    return PROOF_MAP_NODE_ADAPTER.validate_json(row["data"]) if row else None


def list_proof_map_nodes(store: ProjectStore) -> list[ProofMapNode]:
    with store.connect() as conn:
        rows = conn.execute("SELECT data FROM proof_map_nodes ORDER BY id").fetchall()
    return [PROOF_MAP_NODE_ADAPTER.validate_json(row["data"]) for row in rows]


def _row_to_claim(row: sqlite3.Row) -> ClaimRecord:
    return ClaimRecord(
        id=row["id"],
        node_id=row["node_id"],
        claimant_id=row["claimant_id"],
        session_id=row["session_id"],
        claimed_at=row["claimed_at"],
        released_at=row["released_at"],
        released_by=row["released_by"],
        release_reason=row["release_reason"],
    )


def insert_claim(store: ProjectStore, claim: ClaimRecord) -> ClaimRecord:
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO claims(id, node_id, claimant_id, session_id, claimed_at, released_at, released_by, release_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.id,
                claim.node_id,
                claim.claimant_id,
                claim.session_id,
                claim.claimed_at.isoformat(),
                claim.released_at.isoformat() if claim.released_at else None,
                claim.released_by,
                claim.release_reason,
            ),
        )
        conn.commit()
    return claim


def get_active_claim(store: ProjectStore, node_id: str) -> ClaimRecord | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE node_id = ? AND released_at IS NULL LIMIT 1",
            (node_id,),
        ).fetchone()
    return _row_to_claim(row) if row else None


def get_claim(store: ProjectStore, claim_id: str) -> ClaimRecord | None:
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM claims WHERE id = ? LIMIT 1", (claim_id,)).fetchone()
    return _row_to_claim(row) if row else None


def list_all_claims(store: ProjectStore) -> list[ClaimRecord]:
    """Every claim in the project — active and released — for a full-fidelity export (issue #31)."""
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM claims ORDER BY claimed_at").fetchall()
    return [_row_to_claim(row) for row in rows]


def mark_claim_released(
    store: ProjectStore,
    claim_id: str,
    *,
    released_by: str,
    reason: str,
    released_at: datetime,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Release a claim, but only if it is still active.

    The `released_at IS NULL` guard makes this the release-side counterpart
    of claim_node's unique-index guard: two concurrent releases of the same
    claim (e.g. the owner releasing at the same moment as a researcher's
    force-release) can't both silently win — only the first UPDATE to reach
    SQLite's write lock affects a row. Returns whether this call was the one
    that released it.
    """
    with _writing(store, conn) as conn:
        cursor = conn.execute(
            "UPDATE claims SET released_at = ?, released_by = ?, release_reason = ? WHERE id = ? AND released_at IS NULL",
            (released_at.isoformat(), released_by, reason, claim_id),
        )
        return cursor.rowcount > 0


def _row_to_candidate_proof(row: sqlite3.Row) -> CandidateProofRecord:
    return CandidateProofRecord(
        id=row["id"],
        node_id=row["node_id"],
        version=row["version"],
        file_path=row["file_path"],
        is_current=bool(row["is_current"]),
        review_record_id=row["review_record_id"],
        submitted_by=row["submitted_by"],
        scoping_rationale=row["scoping_rationale"],
        interface_fingerprint=row["interface_fingerprint"],
        created_at=row["created_at"],
    )


def next_candidate_proof_version(store: ProjectStore, node_id: str) -> int:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM candidate_proofs WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    return int(row["max_version"]) + 1


def insert_candidate_proof(store: ProjectStore, record: CandidateProofRecord) -> CandidateProofRecord:
    """Index a new candidate proof, marking every prior version of this node not-current.

    The unique index on (node_id, version) is the real guarantee against two
    submissions racing onto the same version number; `submit_candidate_proof`
    is the only caller, and it's already gated by claim exclusivity, but the
    constraint means a double-submit fails loudly instead of corrupting the
    index.
    """
    with store.connect() as conn:
        conn.execute("UPDATE candidate_proofs SET is_current = 0 WHERE node_id = ?", (record.node_id,))
        conn.execute(
            """
            INSERT INTO candidate_proofs(id, node_id, version, file_path, is_current, review_record_id, submitted_by, scoping_rationale, interface_fingerprint, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.node_id,
                record.version,
                record.file_path,
                int(record.is_current),
                record.review_record_id,
                record.submitted_by,
                record.scoping_rationale,
                record.interface_fingerprint,
                record.created_at.isoformat(),
            ),
        )
        conn.commit()
    return record


def set_candidate_proof_interface_fingerprint(
    store: ProjectStore, candidate_proof_id: str, fingerprint: str, *, conn: sqlite3.Connection | None = None
) -> None:
    with _writing(store, conn) as conn:
        conn.execute(
            "UPDATE candidate_proofs SET interface_fingerprint = ? WHERE id = ?",
            (fingerprint, candidate_proof_id),
        )


def set_candidate_proof_review_record_id(
    store: ProjectStore, candidate_proof_id: str, review_record_id: str, *, conn: sqlite3.Connection | None = None
) -> None:
    with _writing(store, conn) as conn:
        conn.execute(
            "UPDATE candidate_proofs SET review_record_id = ? WHERE id = ?",
            (review_record_id, candidate_proof_id),
        )


def get_candidate_proof(store: ProjectStore, candidate_proof_id: str) -> CandidateProofRecord | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidate_proofs WHERE id = ? LIMIT 1",
            (candidate_proof_id,),
        ).fetchone()
    return _row_to_candidate_proof(row) if row else None


def list_candidate_proofs_for_node(store: ProjectStore, node_id: str) -> list[CandidateProofRecord]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM candidate_proofs WHERE node_id = ? ORDER BY version",
            (node_id,),
        ).fetchall()
    return [_row_to_candidate_proof(row) for row in rows]


def get_current_candidate_proof(store: ProjectStore, node_id: str) -> CandidateProofRecord | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidate_proofs WHERE node_id = ? AND is_current = 1 LIMIT 1",
            (node_id,),
        ).fetchone()
    return _row_to_candidate_proof(row) if row else None


def list_all_candidate_proofs(store: ProjectStore) -> list[CandidateProofRecord]:
    """Every candidate proof's index row across the whole project (issue #31).

    Only the index — id, version, file_path, fingerprint, etc. The proof
    text itself lives in the git-tracked Proof vault, not here; exchange
    carries this index for fidelity, and relies on git for the vault files
    themselves, same as it always has for the rest of the working tree.
    """
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM candidate_proofs ORDER BY node_id, version").fetchall()
    return [_row_to_candidate_proof(row) for row in rows]


def _row_to_dependency_pin(row: sqlite3.Row) -> DependencyPin:
    return DependencyPin(
        id=row["id"],
        node_id=row["node_id"],
        target_node_id=row["target_node_id"],
        pinned_version=row["pinned_version"],
        pinned_fingerprint=row["pinned_fingerprint"],
        created_at=row["created_at"],
    )


def upsert_dependency_pin(store: ProjectStore, pin: DependencyPin, *, conn: sqlite3.Connection | None = None) -> DependencyPin:
    """Insert or refresh the pin for (node_id, target_node_id).

    One row per pair — always the most recent pin. `id` is preserved across
    a refresh so a caller holding an earlier pin's id can still look it up.
    """
    with _writing(store, conn) as conn:
        existing = conn.execute(
            "SELECT id FROM dependency_pins WHERE node_id = ? AND target_node_id = ? LIMIT 1",
            (pin.node_id, pin.target_node_id),
        ).fetchone()
        pin_id = existing["id"] if existing else pin.id
        conn.execute(
            """
            INSERT INTO dependency_pins(id, node_id, target_node_id, pinned_version, pinned_fingerprint, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id, target_node_id) DO UPDATE SET
              pinned_version = excluded.pinned_version,
              pinned_fingerprint = excluded.pinned_fingerprint,
              created_at = excluded.created_at
            """,
            (
                pin_id,
                pin.node_id,
                pin.target_node_id,
                pin.pinned_version,
                pin.pinned_fingerprint,
                pin.created_at.isoformat(),
            ),
        )
    return pin.model_copy(update={"id": pin_id})


def get_dependency_pin(store: ProjectStore, node_id: str, target_node_id: str) -> DependencyPin | None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT * FROM dependency_pins WHERE node_id = ? AND target_node_id = ? LIMIT 1",
            (node_id, target_node_id),
        ).fetchone()
    return _row_to_dependency_pin(row) if row else None


def list_dependency_pins_for_node(store: ProjectStore, node_id: str) -> list[DependencyPin]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM dependency_pins WHERE node_id = ? ORDER BY target_node_id",
            (node_id,),
        ).fetchall()
    return [_row_to_dependency_pin(row) for row in rows]


def list_all_dependency_pins(store: ProjectStore) -> list[DependencyPin]:
    """Every dependency pin across the whole project, for a full-fidelity export (issue #31)."""
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM dependency_pins ORDER BY node_id, target_node_id").fetchall()
    return [_row_to_dependency_pin(row) for row in rows]


def _row_to_challenge(row: sqlite3.Row) -> Challenge:
    return Challenge(
        id=row["id"],
        target_node_id=row["target_node_id"],
        status=row["status"],
        rationale=row["rationale"],
        opened_by=row["opened_by"],
        created_at=row["created_at"],
        resolved_by=row["resolved_by"],
        resolved_at=row["resolved_at"],
        resolution_review_id=row["resolution_review_id"],
    )


def insert_challenge(store: ProjectStore, challenge: Challenge) -> Challenge:
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO challenges(id, target_node_id, status, rationale, opened_by, created_at, resolved_by, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                challenge.id,
                challenge.target_node_id,
                challenge.status.value,
                challenge.rationale,
                challenge.opened_by,
                challenge.created_at.isoformat(),
                challenge.resolved_by,
                challenge.resolved_at.isoformat() if challenge.resolved_at else None,
            ),
        )
        conn.commit()
    return challenge


def get_challenge(store: ProjectStore, challenge_id: str) -> Challenge | None:
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM challenges WHERE id = ? LIMIT 1", (challenge_id,)).fetchone()
    return _row_to_challenge(row) if row else None


def list_challenges(store: ProjectStore, *, target_node_id: str = "", status: str = "") -> list[Challenge]:
    query = "SELECT * FROM challenges"
    conditions = []
    params: list[str] = []
    if target_node_id:
        conditions.append("target_node_id = ?")
        params.append(target_node_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at"
    with store.connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_challenge(row) for row in rows]


def mark_challenge_dismissed(
    store: ProjectStore,
    challenge_id: str,
    *,
    resolved_by: str,
    resolved_at: datetime,
    resolution_review_id: str | None = None,
    reopened: bool = False,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Dismiss a challenge, recording the signed decision that resolved it.

    By default only a still-open row is updated — the guard that stops two
    racing dismissals both winning; returns whether this call changed it.
    `resolution_review_id` names the signed Human Review decision; a
    dismissal counts only while that decision verifies (ADR-0009 point 2).
    `reopened=True` also re-dismisses a row whose stored dismissal no longer
    counts; the caller has then already settled the race by re-reading the
    Challenge on its own write transaction.
    """
    with _writing(store, conn) as conn:
        cursor = conn.execute(
            "UPDATE challenges SET status = 'dismissed', resolved_by = ?, resolved_at = ?, resolution_review_id = ? "
            "WHERE id = ?" + ("" if reopened else " AND status = 'open'"),
            (resolved_by, resolved_at.isoformat(), resolution_review_id, challenge_id),
        )
        return cursor.rowcount > 0


def _row_to_evidence_check(row: sqlite3.Row) -> EvidenceCheck:
    return EvidenceCheck(
        id=row["id"],
        candidate_proof_id=row["candidate_proof_id"],
        outcome=row["outcome"],
        notes=row["notes"],
        run_by=row["run_by"],
        created_at=row["created_at"],
    )


def insert_evidence_check(store: ProjectStore, check: EvidenceCheck) -> EvidenceCheck:
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO evidence_checks(id, candidate_proof_id, outcome, notes, run_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (check.id, check.candidate_proof_id, check.outcome.value, check.notes, check.run_by, check.created_at.isoformat()),
        )
        conn.commit()
    return check


def get_evidence_check(store: ProjectStore, check_id: str) -> EvidenceCheck | None:
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM evidence_checks WHERE id = ? LIMIT 1", (check_id,)).fetchone()
    return _row_to_evidence_check(row) if row else None


def list_evidence_checks_for_candidate_proof(store: ProjectStore, candidate_proof_id: str) -> list[EvidenceCheck]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM evidence_checks WHERE candidate_proof_id = ? ORDER BY created_at",
            (candidate_proof_id,),
        ).fetchall()
    return [_row_to_evidence_check(row) for row in rows]


def list_all_evidence_checks(store: ProjectStore) -> list[EvidenceCheck]:
    """Every evidence check across the whole project, for a full-fidelity export (issue #31)."""
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM evidence_checks ORDER BY candidate_proof_id, created_at").fetchall()
    return [_row_to_evidence_check(row) for row in rows]


def insert_governance_record(store: ProjectStore, *, kind: str, data: str) -> None:
    """Append-only store for the frozen asset/pack/policy/recommend/reuse/
    automate/benchmark modules (issue #28) — isolated off
    `ProjectState.session_history`, which is core proof-map bookkeeping,
    not a place for these peripheral modules' own records. `kind` is one of
    their history-prefix constants; behavior is otherwise unchanged from
    before this table existed.
    """
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO governance_records(id, kind, data, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), kind, data, utc_now().isoformat()),
        )
        conn.commit()


def list_governance_records(store: ProjectStore, *, kind: str) -> list[str]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT data FROM governance_records WHERE kind = ? ORDER BY created_at, rowid",
            (kind,),
        ).fetchall()
    return [row["data"] for row in rows]


def store_snapshot(store: ProjectStore, snapshot: ProjectSnapshot) -> ProjectSnapshot:
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots(id, data, created_at) VALUES (?, ?, ?)",
            (snapshot.project_id, snapshot.model_dump_json(), snapshot.created_at.isoformat()),
        )
        conn.commit()
    return snapshot


def read_latest_snapshot(store: ProjectStore) -> ProjectSnapshot | None:
    with store.connect() as conn:
        row = conn.execute("SELECT data FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
    return SNAPSHOT_ADAPTER.validate_json(row["data"]) if row else None


def store_publication_state(store: ProjectStore, project_id: str, data: str, *, updated_at: datetime | None = None) -> None:
    timestamp = (updated_at or utc_now()).isoformat()
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO publication_state(project_id, data, updated_at) VALUES (?, ?, ?)",
            (project_id, data, timestamp),
        )
        conn.commit()


def read_publication_state(store: ProjectStore) -> str | None:
    with store.connect() as conn:
        row = conn.execute("SELECT data FROM publication_state ORDER BY updated_at DESC LIMIT 1").fetchone()
    return row["data"] if row else None


def store_publication_bundle_snapshot(
    store: ProjectStore,
    snapshot_id: str,
    project_id: str,
    data: str,
    *,
    created_at: datetime | None = None,
) -> None:
    timestamp = (created_at or utc_now()).isoformat()
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO publication_bundle_snapshots(id, project_id, data, created_at) VALUES (?, ?, ?, ?)",
            (snapshot_id, project_id, data, timestamp),
        )
        conn.commit()


def list_publication_bundle_snapshots(store: ProjectStore) -> list[str]:
    with store.connect() as conn:
        rows = conn.execute("SELECT data FROM publication_bundle_snapshots ORDER BY created_at, id").fetchall()
    return [row["data"] for row in rows]


def read_latest_publication_bundle_snapshot(store: ProjectStore) -> str | None:
    with store.connect() as conn:
        row = conn.execute("SELECT data FROM publication_bundle_snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
    return row["data"] if row else None


def store_state(store: ProjectStore, state: ProjectState) -> ProjectState:
    write_state(store, state)
    return state


def ensure_project(root: str | Path, project_id: str = "proj_alpha") -> ProjectStore:
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return create_project(path, project_id)


_REVIEW_HISTORY_COLUMNS = (
    "id",
    "review_id",
    "entry",
    "object_type",
    "object_id",
    "kind",
    "decision",
    "reviewer_id",
    "rationale",
    "authorship",
    "provenance_notes",
    "created_at",
    "prev_row_hash",
    "signed_decision",
    "payload_hash",
)


def insert_review_history_row(conn: sqlite3.Connection, row: dict) -> None:
    """Append one Human Review history row on the caller's transaction.

    The only write path into `review_history`; there is deliberately no
    update or delete counterpart (the table's triggers would refuse one).
    The row is linked to the hash of the row before it (`prev_row_hash`),
    computed here, on the write lock — callers never supply it.
    """
    stored = {**row, "prev_row_hash": _last_row_hash(conn, "review_history")}
    stored.setdefault("signed_decision", None)
    stored.setdefault("payload_hash", None)
    values = [stored[column] for column in _REVIEW_HISTORY_COLUMNS]
    values[_REVIEW_HISTORY_COLUMNS.index("authorship")] = json.dumps(row["authorship"])
    placeholders = ", ".join("?" for _ in _REVIEW_HISTORY_COLUMNS)
    conn.execute(
        f"INSERT INTO review_history({', '.join(_REVIEW_HISTORY_COLUMNS)}) VALUES ({placeholders})",
        values,
    )


def review_history_payload_recorded(conn: sqlite3.Connection, payload_hash: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM review_history WHERE payload_hash = ? LIMIT 1", (payload_hash,)).fetchone()
        is not None
    )


def review_history_head(conn: sqlite3.Connection) -> str:
    """The hash of the latest review-history row: what a new signed payload commits to."""
    return _last_row_hash(conn, "review_history")


def list_raw_chain_rows(store: ProjectStore, table: str) -> list[dict]:
    """Every row of a hash-chained table (`review_history`, `reviewer_keys`), exactly as stored."""
    if table not in {"review_history", "reviewer_keys"}:
        raise ValueError(f"{table} is not a hash-chained table")
    with store.connect() as conn:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY seq").fetchall()
    return [dict(row) for row in rows]


_REVIEWER_KEY_COLUMNS = (
    "id",
    "entry",
    "credential_id",
    "public_key_spki",
    "alg",
    "fingerprint",
    "display_name",
    "signed_decision",
    "created_at",
)


def insert_reviewer_key_row(conn: sqlite3.Connection, row: dict) -> None:
    """Append one enrollment/revocation row to the Reviewer key registry, hash-linked."""
    columns = (*_REVIEWER_KEY_COLUMNS, "prev_row_hash")
    values = [row[column] for column in _REVIEWER_KEY_COLUMNS] + [_last_row_hash(conn, "reviewer_keys")]
    conn.execute(
        f"INSERT INTO reviewer_keys({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        values,
    )


def review_history_row_exists(conn: sqlite3.Connection, row_id: str) -> bool:
    return conn.execute("SELECT 1 FROM review_history WHERE id = ? LIMIT 1", (row_id,)).fetchone() is not None


def _row_to_review_history(row: sqlite3.Row) -> dict:
    data = {column: row[column] for column in _REVIEW_HISTORY_COLUMNS}
    data["seq"] = row["seq"]
    data["authorship"] = json.loads(row["authorship"])
    return data


def list_review_history_rows(
    store: ProjectStore,
    *,
    object_type: str = "",
    object_id: str = "",
    review_id: str = "",
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Review history rows in append order, optionally narrowed to one object or one review."""
    query = "SELECT * FROM review_history"
    conditions: list[str] = []
    params: list[str] = []
    if object_type:
        conditions.append("object_type = ?")
        params.append(object_type)
    if object_id:
        conditions.append("object_id = ?")
        params.append(object_id)
    if review_id:
        conditions.append("review_id = ?")
        params.append(review_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY seq"
    if conn is not None:
        rows = conn.execute(query, params).fetchall()
    else:
        with store.connect() as own:
            rows = own.execute(query, params).fetchall()
    return [_row_to_review_history(row) for row in rows]
