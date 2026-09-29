from __future__ import annotations

import functools
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

-- Signed decisions another project made, kept for display only: nothing reads
-- them to derive a Human Review axis (ADR-0009 point 6, issue #38).
CREATE TABLE IF NOT EXISTS foreign_attestations (
  id TEXT PRIMARY KEY,
  object_id TEXT NOT NULL,
  data TEXT NOT NULL,
  imported_at TEXT NOT NULL
);
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
_CLAIM_DROPPED_COLUMNS = ("token_hash",)  # the #37 claim token, gone with ADR-0010
_CANDIDATE_PROOF_ADDED_COLUMNS = {"sha256": "TEXT"}  # a Review snapshot's hash (ADR-0010)

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
  aaguid TEXT,
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

# Whole-document state that used to be a JSON side file under `.proof/`
# (collaboration.json, memory.json; issue #39). Each document is one row,
# read, changed and written back inside one `store.transaction()`, so
# concurrent processes take turns on the SQLite write lock instead of
# overwriting each other's writes.
SIDE_DOCUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS side_documents (
  name TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

# Unsigned but chained facts an agent may legitimately record — a node's
# creation (its kind) and a Challenge's opening — kept append-only and
# hash-linked so they can't be quietly edited or deleted afterwards (#35 C).
PROOF_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS proof_ledger (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  entry TEXT NOT NULL CHECK (entry IN ('node_created', 'challenge_opened')),
  object_id TEXT NOT NULL,
  data TEXT NOT NULL,
  prev_row_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proof_ledger_object ON proof_ledger(entry, object_id, seq);

CREATE TRIGGER IF NOT EXISTS proof_ledger_no_update
BEFORE UPDATE ON proof_ledger
BEGIN
  SELECT RAISE(ABORT, 'proof_ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS proof_ledger_no_delete
BEFORE DELETE ON proof_ledger
BEGIN
  SELECT RAISE(ABORT, 'proof_ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS proof_ledger_no_overwrite
BEFORE INSERT ON proof_ledger
WHEN EXISTS (SELECT 1 FROM proof_ledger WHERE id = NEW.id OR seq = NEW.seq)
BEGIN
  SELECT RAISE(ABORT, 'proof_ledger is append-only');
END;
"""

CHAINED_TABLES = ("review_history", "reviewer_keys", "proof_ledger")

INSTANCE_ID_KEY = "instance_id"


def project_instance_id(conn: sqlite3.Connection) -> str:
    """This project database's random instance id, created on first use.

    Not the display `project_id` (many projects share the default one) and
    never carried by exchange import: it names this one database, so a
    signed decision or a history prefix from any other project — a copy of
    this one's history included — never matches here (ADR-0009, #35 E).
    """
    # read first: even an ignored INSERT takes the write lock, which would
    # stall a reader running beside an open decision transaction
    row = conn.execute("SELECT value FROM project_meta WHERE key = ?", (INSTANCE_ID_KEY,)).fetchone()
    if row is not None:
        return row["value"]
    conn.execute(
        "INSERT OR IGNORE INTO project_meta(key, value) VALUES (?, ?)", (INSTANCE_ID_KEY, uuid.uuid4().hex)
    )
    return conn.execute("SELECT value FROM project_meta WHERE key = ?", (INSTANCE_ID_KEY,)).fetchone()["value"]


def genesis_row_hash(instance_id: str) -> str:
    """The first link of both hash chains, unique to one project instance."""
    return hashlib.sha256(f"proof-cli chain genesis {instance_id}".encode("utf-8")).hexdigest()


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


def _drop_columns(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name in columns:
        if name in existing:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


def _last_row_hash(conn: sqlite3.Connection, table: str) -> str:
    last = conn.execute(f"SELECT * FROM {table} ORDER BY seq DESC LIMIT 1").fetchone()
    return chain_row_hash(dict(last)) if last is not None else genesis_row_hash(project_instance_id(conn))


class _ActiveTransaction(NamedTuple):
    db_path: Path
    thread_id: int
    conn: sqlite3.Connection
    after_commit: list
    before_commit: list
    on_rollback: list


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


class ProjectNotFoundError(Exception):
    """A read was pointed at a folder with no proof project (PROJECT_NOT_FOUND, #34)."""

    code = "PROJECT_NOT_FOUND"

    def __init__(self, root: Path) -> None:
        self.root = root
        super().__init__(f"no proof project at {root} (run `proof init` there, or check --root)")


# Set while a read-only CLI command runs: opening a project that doesn't exist
# is then an error, never a silent `proof init` of a mistyped --root.
_READ_ONLY: ContextVar[bool] = ContextVar("proof_cli_read_only", default=False)


@contextmanager
def read_only() -> Iterator[None]:
    """Refuse to create a project for the duration: a read of a missing one raises ProjectNotFoundError."""
    token = _READ_ONLY.set(True)
    try:
        yield
    finally:
        _READ_ONLY.reset(token)


@dataclass
class ProjectStore:
    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / ".proof" / "project.sqlite3"

    def connect(self) -> sqlite3.Connection:
        if _READ_ONLY.get() and not self.db_path.exists():
            raise ProjectNotFoundError(self.root)
        conn = connect(self.db_path)
        initialize(conn)
        conn.executescript(REFERENCE_SCHEMA)
        conn.executescript(PROOF_MAP_SCHEMA)
        conn.executescript(REVIEW_HISTORY_SCHEMA)
        _add_missing_columns(conn, "review_history", _REVIEW_HISTORY_ADDED_COLUMNS)
        _add_missing_columns(conn, "challenges", _CHALLENGE_ADDED_COLUMNS)
        _drop_columns(conn, "claims", _CLAIM_DROPPED_COLUMNS)
        _add_missing_columns(conn, "candidate_proofs", _CANDIDATE_PROOF_ADDED_COLUMNS)
        conn.executescript(REVIEW_HISTORY_TRIGGERS)
        conn.executescript(REVIEWER_KEYS_SCHEMA)
        conn.executescript(PROOF_LEDGER_SCHEMA)
        conn.executescript(SIDE_DOCUMENTS_SCHEMA)
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
            outer = _ACTIVE_TRANSACTION.get()
            own_from = len(outer.on_rollback)  # this block's on_rollback callbacks: those after these
            savepoint = f"nested_{uuid.uuid4().hex}"
            joined.execute(f"SAVEPOINT {savepoint}")
            try:
                yield joined
            except BaseException:
                try:
                    _run_rollback_callbacks(outer.on_rollback, own_from)
                finally:
                    joined.execute(f"ROLLBACK TO {savepoint}")
                    joined.execute(f"RELEASE {savepoint}")
                raise
            joined.execute(f"RELEASE {savepoint}")
            return
        conn = self.connect()
        active = _ActiveTransaction(self.db_path.resolve(), threading.get_ident(), conn, [], [], [])
        token = _ACTIVE_TRANSACTION.set(active)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            for callback in active.before_commit:  # still holding the write lock
                callback()
            conn.commit()
        except BaseException:
            try:
                # a failed commit (a reader it waited on, say) still holds the write lock too
                _run_rollback_callbacks(active.on_rollback, 0)
            finally:
                conn.rollback()
            raise
        finally:
            _ACTIVE_TRANSACTION.reset(token)
            conn.close()
        for callback in active.after_commit:
            callback()


def one_transaction(func):
    """Run `func(store, ...)` inside one `store.transaction()` on its store.

    For a read-modify-write of whole-document state (`side_documents`,
    #39): its load and its save both join the transaction, so a concurrent
    writer waits on the write lock instead of landing in between.
    """

    @functools.wraps(func)
    def wrapper(store: ProjectStore, *args, **kwargs):
        with store.transaction():
            return func(store, *args, **kwargs)

    return wrapper


def after_commit(store: ProjectStore, callback) -> None:
    """Run `callback` once this thread's open transaction on `store` has committed
    (never if it rolls back); right away if none is open."""
    active = _ACTIVE_TRANSACTION.get()
    if active is not None and active.thread_id == threading.get_ident() and active.db_path == store.db_path.resolve():
        if callback not in active.after_commit:
            active.after_commit.append(callback)
        return
    callback()


def before_commit(store: ProjectStore, callback) -> None:
    """Run `callback` just before this thread's open transaction on `store` commits,
    still holding its write lock (an exception rolls the transaction back);
    right away if none is open."""
    active = _ACTIVE_TRANSACTION.get()
    if active is not None and active.thread_id == threading.get_ident() and active.db_path == store.db_path.resolve():
        active.before_commit.append(callback)
        return
    callback()


def on_rollback(store: ProjectStore, callback) -> None:
    """Run `callback` if this thread's open transaction on `store` rolls back — the block
    raising, a `before_commit` callback raising, or the commit itself failing — while it still
    holds the write lock, so no other writer has run in between. Inside a nested
    `transaction()`, when that block's SAVEPOINT rolls back. Never after a commit; nothing to
    do when no transaction is open. For undoing a side effect outside SQLite, such as a file
    the transaction wrote."""
    active = _ACTIVE_TRANSACTION.get()
    if active is not None and active.thread_id == threading.get_ident() and active.db_path == store.db_path.resolve():
        active.on_rollback.append(callback)


def _run_rollback_callbacks(callbacks: list, start: int) -> None:
    """Run `callbacks[start:]`, latest first, and drop them; each runs even if one before it raised."""
    pending = callbacks[start:]
    del callbacks[start:]
    errors: list[BaseException] = []
    for callback in reversed(pending):
        try:
            callback()
        except BaseException as exc:
            errors.append(exc)
    if errors:
        raise errors[0]


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


LEDGER_ADOPTED_KEY = "ledger_adopted"


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


@contextmanager
def _reading(store: ProjectStore, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """The connection a read helper should use: the caller's, which sees its own uncommitted
    writes and holds its write lock, or else a fresh one, closed afterwards."""
    if conn is not None:
        yield conn
        return
    own = store.connect()
    try:
        yield own
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


# The JSON side files moved into `side_documents` (issue #39), by document name.
SIDE_DOCUMENT_FILES = {"collaboration": "collaboration.json", "memory": "memory.json"}
# Top-level keys a side file may hold that are never carried into its
# document: `collaboration.json`'s review records are Human Review history,
# which the #33 migration reads from the file itself.
_SIDE_DOCUMENT_EXCLUDED_KEYS = {"collaboration": ("review_records",), "memory": ()}


def _side_document_migrated_key(name: str) -> str:
    return f"{name}_json_migrated"


def _is_side_document_migrated(conn: sqlite3.Connection, name: str) -> bool:
    key = _side_document_migrated_key(name)
    return conn.execute("SELECT 1 FROM project_meta WHERE key = ? LIMIT 1", (key,)).fetchone() is not None


def _mark_side_document_migrated(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO project_meta(key, value) VALUES (?, ?)",
        (_side_document_migrated_key(name), utc_now().isoformat()),
    )


def _migrate_side_document(store: ProjectStore, conn: sqlite3.Connection, name: str) -> None:
    """Move `.proof/<name>.json` into `side_documents` — once, on `conn`'s transaction.

    The file's JSON is stored as it stands (bar the excluded keys), so the
    loader's handling of older layouts still applies to it and nothing is
    lost. The file itself is left where it is, unchanged: it is never read
    for this document again. A file that isn't valid JSON (a half-written
    `memory.json` from the old non-atomic save, say) is refused rather than
    replaced by an empty document; the migration stays pending until the
    file is fixed or removed.
    """
    if _is_side_document_migrated(conn, name):
        return
    path = project_proof_dir(store) / SIDE_DOCUMENT_FILES[name]
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path} is not valid JSON ({exc}); it moves into the project database once, "
                "so fix or remove it to continue"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path} does not hold a JSON object; fix or remove it to continue")
        for key in _SIDE_DOCUMENT_EXCLUDED_KEYS[name]:
            data.pop(key, None)
        conn.execute(
            "INSERT OR IGNORE INTO side_documents(name, data, updated_at) VALUES (?, ?, ?)",
            (name, json.dumps(data), utc_now().isoformat()),
        )
        append_event(
            store,
            f"{name}_json_migrated",
            f"moved {path.name} into the project database",
            payload={"path": str(path)},
            conn=conn,
        )
    _mark_side_document_migrated(conn, name)


def _select_side_document(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT data FROM side_documents WHERE name = ?", (name,)).fetchone()
    return json.loads(row["data"]) if row is not None else None


def read_side_document(store: ProjectStore, name: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """The stored document `name` (see `SIDE_DOCUMENT_FILES`), or None if none was ever saved.

    Reads on the caller's transaction (`conn`, or the one this thread holds
    open), so a read-modify-write inside `store.transaction()` sees its own
    writes and no other process's in between. The first read of a project
    that still has the JSON side file migrates it.
    """
    if conn is None:
        conn = active_transaction(store)
    with _reading(store, conn) as reader:
        if _is_side_document_migrated(reader, name):
            return _select_side_document(reader, name)
    with in_transaction(store, conn) as tx:
        _migrate_side_document(store, tx, name)
        return _select_side_document(tx, name)


def write_side_document(store: ProjectStore, name: str, data: str, conn: sqlite3.Connection | None = None) -> None:
    """Replace the stored document `name` with `data` (JSON text).

    Joins the caller's transaction if there is one. A read-modify-write must
    run inside one `store.transaction()` for concurrent writers not to
    overwrite each other; this call on its own is only atomic.
    """
    with _writing(store, conn) as writer:
        _migrate_side_document(store, writer, name)  # a pending file is never overwritten unread
        writer.execute(
            "INSERT OR REPLACE INTO side_documents(name, data, updated_at) VALUES (?, ?, ?)",
            (name, data, utc_now().isoformat()),
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
            project_instance_id(conn)
            # a brand-new project has nothing to adopt into the ledger
            conn.execute("INSERT OR IGNORE INTO project_meta(key, value) VALUES (?, ?)", (LEDGER_ADOPTED_KEY, utc_now().isoformat()))
            if not collaboration_state_path(store).exists():
                # a brand-new project has no JSON-era review records, so its
                # one-shot migration is done before it ever starts
                mark_review_history_migrated(conn)
            for name, file_name in SIDE_DOCUMENT_FILES.items():
                if not (project_proof_dir(store) / file_name).exists():
                    _mark_side_document_migrated(conn, name)  # nothing to move, so it's done
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
    if get_reference(store, reference.id) is not None:
        # importing again would reset a reviewed reference to a candidate (issue #37)
        raise ValueError(f"reference {reference.id} already exists; import the new record under a new id")
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


def insert_proof_map_node(store: ProjectStore, node: ProofMapNode, *, conn: sqlite3.Connection | None = None) -> ProofMapNode:
    with _writing(store, conn) as conn:
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
    return node


def update_proof_map_node(store: ProjectStore, node: ProofMapNode, *, conn: sqlite3.Connection | None = None) -> ProofMapNode:
    """Overwrite an existing node's row in place.

    Its callers are the node's sanctioned edits: Promote (issue #22)
    changing `kind` from `claim` to `lemma`, Split (issue #26) appending
    children to `dependencies`, and moving dependents off a withdrawn
    imported result (issue #20) swapping one dependency for its correction.
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


def insert_claim(store: ProjectStore, claim: ClaimRecord, *, conn: sqlite3.Connection | None = None) -> ClaimRecord:
    with _writing(store, conn) as conn:
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
    return claim


def get_active_claim(store: ProjectStore, node_id: str, *, conn: sqlite3.Connection | None = None) -> ClaimRecord | None:
    """`conn`: read inside the caller's `store.transaction()`, so the answer holds until it commits."""
    with _reading(store, conn) as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE node_id = ? AND released_at IS NULL LIMIT 1",
            (node_id,),
        ).fetchone()
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
        sha256=row["sha256"],
        created_at=row["created_at"],
    )


def next_candidate_proof_version(store: ProjectStore, node_id: str, *, conn: sqlite3.Connection | None = None) -> int:
    """One past the highest indexed version; see `request_review` for files on disk the index doesn't know."""
    with _reading(store, conn) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM candidate_proofs WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    return int(row["max_version"]) + 1


def insert_candidate_proof(
    store: ProjectStore, record: CandidateProofRecord, *, conn: sqlite3.Connection | None = None
) -> CandidateProofRecord:
    """Index a new candidate proof, marking every prior version of this node not-current.

    The unique index on (node_id, version) is the real guarantee against two
    requests racing onto the same version number; `request_review` already
    takes the version inside its own write transaction, but the constraint
    means a double insert fails loudly instead of corrupting the index.
    """
    with _writing(store, conn) as conn:
        conn.execute("UPDATE candidate_proofs SET is_current = 0 WHERE node_id = ?", (record.node_id,))
        conn.execute(
            """
            INSERT INTO candidate_proofs(id, node_id, version, file_path, is_current, review_record_id, submitted_by, scoping_rationale, interface_fingerprint, sha256, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record.sha256,
                record.created_at.isoformat(),
            ),
        )
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


def get_current_candidate_proof(
    store: ProjectStore, node_id: str, *, conn: sqlite3.Connection | None = None
) -> CandidateProofRecord | None:
    with _reading(store, conn) as conn:
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


def delete_dependency_pin(store: ProjectStore, node_id: str, target_node_id: str, *, conn: sqlite3.Connection | None = None) -> None:
    with _writing(store, conn) as conn:
        conn.execute("DELETE FROM dependency_pins WHERE node_id = ? AND target_node_id = ?", (node_id, target_node_id))


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


def insert_challenge(store: ProjectStore, challenge: Challenge, *, conn: sqlite3.Connection | None = None) -> Challenge:
    with _writing(store, conn) as conn:
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
    if _READ_ONLY.get() and not ProjectStore(path).db_path.exists():
        raise ProjectNotFoundError(path)  # before the mkdir: a mistyped --root is left as it was
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


def read_project_instance_id(store: ProjectStore) -> str:
    """The instance id, created (once, on the caller's transaction if one is open) for a pre-#35 project."""
    with store.connect() as conn:
        row = conn.execute("SELECT value FROM project_meta WHERE key = ?", (INSTANCE_ID_KEY,)).fetchone()
    if row is not None:
        return row["value"]
    with _writing(store, None) as conn:
        return project_instance_id(conn)


_REVIEWER_KEY_COLUMNS = (
    "id",
    "entry",
    "credential_id",
    "public_key_spki",
    "alg",
    "fingerprint",
    "display_name",
    "aaguid",
    "signed_decision",
    "created_at",
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


