from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from .db import connect, initialize
from .domain import (
    BlockerRecord,
    CandidateProofRecord,
    ClaimRecord,
    DependencyPin,
    EventRecord,
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
"""


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
        conn.commit()
        return conn


def project_proof_dir(store: ProjectStore) -> Path:
    return store.root / ".proof"


def collaboration_state_path(store: ProjectStore) -> Path:
    return project_proof_dir(store) / "collaboration.json"


def create_project(root: str | Path, project_id: str) -> ProjectStore:
    store = ProjectStore(Path(root))
    with store.connect() as conn:
        existing = conn.execute("SELECT value FROM project_meta WHERE key = ?", ("project_id",)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO project_meta(key, value) VALUES (?, ?)",
                ("project_id", project_id),
            )
        state_row = conn.execute("SELECT data FROM state WHERE project_id = ?", (project_id,)).fetchone()
        if state_row is None:
            state = ProjectState(project_id=project_id)
            conn.execute(
                "INSERT INTO state(project_id, data) VALUES (?, ?)",
                (project_id, state.model_dump_json()),
            )
        conn.commit()
    return store


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


def append_event(store: ProjectStore, kind: str, message: str, *, entity_id: str | None = None, payload: dict | None = None) -> EventRecord:
    event = EventRecord(
        id=str(uuid.uuid4()),
        kind=kind,
        entity_id=entity_id,
        message=message,
        payload=payload or {},
    )
    with store.connect() as conn:
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
        conn.commit()
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


def mark_claim_released(
    store: ProjectStore,
    claim_id: str,
    *,
    released_by: str,
    reason: str,
    released_at: datetime,
) -> bool:
    """Release a claim, but only if it is still active.

    The `released_at IS NULL` guard makes this the release-side counterpart
    of claim_node's unique-index guard: two concurrent releases of the same
    claim (e.g. the owner releasing at the same moment as a researcher's
    force-release) can't both silently win — only the first UPDATE to reach
    SQLite's write lock affects a row. Returns whether this call was the one
    that released it.
    """
    with store.connect() as conn:
        cursor = conn.execute(
            "UPDATE claims SET released_at = ?, released_by = ?, release_reason = ? WHERE id = ? AND released_at IS NULL",
            (released_at.isoformat(), released_by, reason, claim_id),
        )
        conn.commit()
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


def set_candidate_proof_interface_fingerprint(store: ProjectStore, candidate_proof_id: str, fingerprint: str) -> None:
    with store.connect() as conn:
        conn.execute(
            "UPDATE candidate_proofs SET interface_fingerprint = ? WHERE id = ?",
            (fingerprint, candidate_proof_id),
        )
        conn.commit()


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


def _row_to_dependency_pin(row: sqlite3.Row) -> DependencyPin:
    return DependencyPin(
        id=row["id"],
        node_id=row["node_id"],
        target_node_id=row["target_node_id"],
        pinned_version=row["pinned_version"],
        pinned_fingerprint=row["pinned_fingerprint"],
        created_at=row["created_at"],
    )


def upsert_dependency_pin(store: ProjectStore, pin: DependencyPin) -> DependencyPin:
    """Insert or refresh the pin for (node_id, target_node_id).

    One row per pair — always the most recent pin. `id` is preserved across
    a refresh so a caller holding an earlier pin's id can still look it up.
    """
    with store.connect() as conn:
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
        conn.commit()
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
