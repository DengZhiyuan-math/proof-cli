from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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


@dataclass
class ProjectStore:
    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / ".proof" / "project.sqlite3"

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        initialize(conn)
        return conn


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


def store_state(store: ProjectStore, state: ProjectState) -> ProjectState:
    write_state(store, state)
    return state


def ensure_project(root: str | Path, project_id: str = "proj_alpha") -> ProjectStore:
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return create_project(path, project_id)
