"""A project Pursue's history: the `pursuit` events (ADR-0021 audit section 1, issue #201).

A project Pursue (proof-agents' `ProjectPursuit`) runs a Reader turn and then one Coordinator per
Theorem. The host that runs it records each step here, through `record_pursuit`, as an
append-only event in the project's own SQLite events (`entity_id` None: a pursuit is no node, and
no node is borrowed to hold a Reader's failure). `project_progress` reads them back, for
`proof project progress` and for the page after a restart.

A pursuit with no `end` event reads `interrupted`: nothing here claims the process that ran it
still works. Nothing is resumed either: no agent process is restored and no provider budget is
spent; a new Start rechecks claims, snapshots and node states itself.

A recording failure is a visible error (PURSUIT_RECORD_FAILED). The host starts no provider when
the `start` event can't be written.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from .domain import EventRecord
from .proof_map import ProofMapError
from .storage import ProjectStore, append_event, list_events_of_kind

PURSUIT_EVENT = "pursuit"

# start: the researcher started it; reader_end: the Reader's turn ended (outcome ok or failed);
# theorem: work moved to a Theorem (or a Theorem's Coordinator ended: outcome is its status);
# stop: the researcher stopped it; release_failed: releasing the claims failed (a retry may follow);
# end: the pursuit ended, outcome its final status (done, stuck, released, budget, ...)
PHASES = ("start", "reader_end", "theorem", "stop", "release_failed", "end")

INTERRUPTED = "interrupted"
RUNNING = "running"


def record_pursuit(
    store: ProjectStore,
    phase: str,
    *,
    pursuit_id: str | None = None,
    provider: str = "",
    outcome: str = "",
    reason: str = "",
    theorem: str | None = None,
    budget: dict[str, Any] | None = None,
) -> EventRecord:
    """Append one `pursuit` event. `start` makes the pursuit's id (read it from the event's payload);
    every other phase names a started pursuit that has not ended, and `end` names its outcome."""
    if phase not in PHASES:
        raise ProofMapError("INVALID_PURSUIT_PHASE", f"not a pursuit phase: {phase!r}", details={"phases": list(PHASES)})
    if phase == "start":
        if pursuit_id is not None:
            raise ProofMapError("INVALID_PURSUIT_PHASE", "a start makes its own pursuit id; none is given")
        pursuit_id = str(uuid.uuid4())
    elif not pursuit_id:
        raise ProofMapError("PURSUIT_NOT_FOUND", f"a {phase} names the pursuit it belongs to")
    if phase == "end" and not outcome.strip():
        raise ProofMapError("PURSUIT_OUTCOME_REQUIRED", "a pursuit's end names its outcome")
    payload = {
        "pursuit_id": pursuit_id,
        "phase": phase,
        "outcome": outcome.strip(),
        "reason": reason.strip(),
        "provider": provider,
        "theorem": theorem,
        "budget": budget,
    }
    message = f"pursuit {pursuit_id}: {phase}" + (f" {payload['outcome']}" if payload["outcome"] else "") + (f": {payload['reason']}" if payload["reason"] else "")
    try:
        with store.transaction() as conn:
            if phase != "start":
                earlier = [e for e in list_events_of_kind(store, PURSUIT_EVENT, conn=conn) if e.payload.get("pursuit_id") == pursuit_id]
                if not earlier:
                    raise ProofMapError("PURSUIT_NOT_FOUND", f"no pursuit has the id {pursuit_id}")
                if any(e.payload.get("phase") == "end" for e in earlier):
                    raise ProofMapError("PURSUIT_ENDED", f"pursuit {pursuit_id} has ended; nothing more is recorded for it")
            return append_event(store, PURSUIT_EVENT, message, entity_id=None, payload=payload, conn=conn)
    except sqlite3.Error as exc:
        raise ProofMapError(
            "PURSUIT_RECORD_FAILED", f"the pursuit's {phase} could not be recorded: {exc}", details={"phase": phase}
        ) from exc


def _event_view(event: EventRecord) -> dict[str, Any]:
    p = event.payload
    return {
        "id": event.id,
        "phase": p.get("phase"),
        "outcome": p.get("outcome", ""),
        "reason": p.get("reason", ""),
        "provider": p.get("provider", ""),
        "theorem": p.get("theorem"),
        "budget": p.get("budget"),
        "created_at": event.created_at.isoformat(),
    }


def project_progress(store: ProjectStore, *, live: str | None = None) -> list[dict[str, Any]]:
    """Every pursuit, oldest first, with its events. An ended one reads its end's outcome and reason;
    one with no end reads `interrupted`, except `live`, the pursuit the calling process runs now,
    which reads `running`."""
    pursuits: dict[str, list[dict[str, Any]]] = {}
    for event in list_events_of_kind(store, PURSUIT_EVENT):
        pursuits.setdefault(event.payload.get("pursuit_id", ""), []).append(_event_view(event))
    views = []
    for pursuit_id, events in pursuits.items():
        end = next((e for e in events if e["phase"] == "end"), None)
        if end is not None:
            status, reason = end["outcome"], end["reason"]
        elif pursuit_id == live:
            status, reason = RUNNING, ""
        else:
            status = INTERRUPTED
            reason = "no end was recorded: the process that ran it stopped; a new Start rechecks claims, snapshots and node states"
        theorems = [e["theorem"] for e in events if e["theorem"]]
        budgets = [e["budget"] for e in events if e["budget"] is not None]
        views.append(
            {
                "pursuit_id": pursuit_id,
                "status": status,
                "reason": reason,
                "provider": events[0]["provider"],
                "theorem": theorems[-1] if theorems else None,
                "budget": budgets[-1] if budgets else None,
                "last_phase": events[-1]["phase"],
                "started_at": events[0]["created_at"],
                "ended_at": end["created_at"] if end else None,
                "events": events,
            }
        )
    return views
