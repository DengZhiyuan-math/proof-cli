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
    EventRecord,
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
