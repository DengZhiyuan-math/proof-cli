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

The Reader's turn has no node either, so it is kept here (#224): `record_reader_turn` writes a
`reader_turn` event when it starts and when it ends, the ended one with its conversation (its events, as its
backend reported them, previews cut at the backend's limits, which the host records with it) under
.proof/reader-turns/, as a node's turns are kept under .proof/agent-turns/. A launch refused before
any job exists is no turn and leaves none.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .domain import EventRecord
from .proof_map import _TURN_ID, READER_TURN_EVENT, ProofMapError  # a Reader turn's id is a node turn's
from .storage import ProjectStore, append_event, list_events_of_kind, put_turn_transcript

PURSUIT_EVENT = "pursuit"

# start: the researcher started it; reader_end: the Reader's turn ended (outcome ok, failed, or unknown);
# theorem: work moved to a Theorem (or a Theorem's Coordinator ended: outcome is its status);
# stop: the researcher stopped it; release_failed: releasing the claims failed (a retry may follow);
# end: the pursuit ended, outcome its final status (done, stuck, released, budget, ...)
PHASES = ("start", "reader_end", "theorem", "stop", "release_failed", "end")

READER_TURNS_DIR = Path(".proof") / "reader-turns"
READER_OUTCOMES = ("ok", "failed", "stopped")

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
    results: dict[str, Any] | None = None,
    launched: bool | None = None,
) -> EventRecord:
    """Append one `pursuit` event. `start` makes the pursuit's id (read it from the event's payload);
    every other phase names a started pursuit that has not ended, and `end` names its outcome. `budget` is the
    pursuit's whole total and what it has spent so far, `results` each Theorem's result so far (#223). On a
    `reader_end`, `launched` says whether the Reader's turn began (its job existed) or was refused before (#224)."""
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
        "results": results,
        "launched": launched,
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
        "results": p.get("results"),
        "launched": p.get("launched"),
        "created_at": event.created_at.isoformat(),
    }


def project_progress(store: ProjectStore, *, live: str | None = None) -> list[dict[str, Any]]:
    """Every pursuit, oldest first, with its events. An ended one reads its end's outcome and reason;
    one with no end reads `interrupted`, except `live`, the pursuit the calling process runs now,
    which reads `running`."""
    pursuits: dict[str, list[dict[str, Any]]] = {}
    kept_reader_turns = reader_turns(store)
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
        results = [e["results"] for e in events if e["results"] is not None]  # none recorded: unknown, not empty
        # a Reader that may have begun: a reader_end that did not say it was refused before its job existed
        reader_may_have_run = any(e["phase"] == "reader_end" and e["launched"] is not False for e in events)
        its_reader_turns = [turn for turn in kept_reader_turns if turn["pursuit_id"] == pursuit_id]
        views.append(
            {
                "pursuit_id": pursuit_id,
                "status": status,
                "reason": reason,
                "provider": events[0]["provider"],
                "theorem": theorems[-1] if theorems else None,
                "budget": budgets[-1] if budgets else None,
                "results": results[-1] if results else None,
                "last_phase": events[-1]["phase"],
                "started_at": events[0]["created_at"],
                "ended_at": end["created_at"] if end else None,
                # the Reader's turns kept with it; None when a Reader ended and nothing was kept (history from before #224)
                "reader_turns": its_reader_turns if its_reader_turns or not reader_may_have_run else None,
                "events": events,
            }
        )
    return views


def record_reader_turn(
    store: ProjectStore,
    *,
    phase: str,
    turn: str,
    by: str,
    pursuit_id: str,
    provider: str = "",
    prompt: str | None = None,
    job: int | None = None,
    session_id: str | None = None,
    outcome: str | None = None,
    reason: str = "",
    exit: int | None = None,
    is_error: bool | None = None,
    events: list[dict] | None = None,
    backend: str | None = None,
    preview_limits: dict[str, int | dict | None] | None = None,
) -> None:
    """The Reader's turn in a project Pursue (#224): `started` once its job exists, `ended` with its job, its backend
    session, its outcome (ok, failed, stopped), the provider's exit and its conversation (`events`, as the `backend`
    reported them: previews cut at its `preview_limits`, `<event>.<field>[<tool>]` or `<event>.<field>` to the
    characters kept from the start, `{"chars": N, "keeps": "end"}` for a field whose end is kept, None for a field
    kept whole; the host passes the backend's own, e.g. latex_agent's), kept under
    .proof/reader-turns/. Project state, no node's; never a decision. A record that can't be written raises
    READER_TURN_RECORD_FAILED, so the host can say the turn is not kept rather than take it as kept; the transcript is
    put in place only with its `ended` event, and removed again when that event or its commit fails. A second end of
    a turn already ended is refused (READER_TURN_ENDED) and touches nothing."""
    if phase not in ("started", "ended"):
        raise ProofMapError("INVALID_REQUEST", f"a Reader turn is started or ended, not {phase!r}")
    if not _TURN_ID.fullmatch(turn or ""):
        raise ProofMapError("INVALID_REQUEST", f"not a turn id: {turn!r}")
    if phase == "ended" and outcome not in READER_OUTCOMES:
        raise ProofMapError("INVALID_REQUEST", f"a Reader turn ends {', '.join(READER_OUTCOMES)}, not {outcome!r}",
                            details={"outcomes": list(READER_OUTCOMES)})
    payload: dict[str, Any] = {"phase": phase, "turn": turn, "by": by, "provider": provider, "pursuit_id": pursuit_id}
    if phase == "ended":
        payload.update(job=job, session_id=session_id, outcome=outcome, reason=reason.strip(), exit=exit, is_error=is_error,
                       # its failed tool calls, apart from how the whole turn ended; unknown without its conversation
                       tool_failures=None if events is None else sum(1 for e in events if e.get("t") == "tool_result" and e.get("error")),
                       backend=backend, preview_limits=preview_limits)
    try:
        with store.transaction() as conn:
            if not any(e.payload.get("pursuit_id") == pursuit_id for e in list_events_of_kind(store, PURSUIT_EVENT, conn=conn)):
                raise ProofMapError("PURSUIT_NOT_FOUND", f"no pursuit has the id {pursuit_id}")
            this_turn = [e.payload for e in list_events_of_kind(store, READER_TURN_EVENT, conn=conn) if e.payload.get("turn") == turn]
            if phase == "ended" and any(p.get("phase") == "ended" for p in this_turn):
                raise ProofMapError("READER_TURN_ENDED", f"the Reader's turn {turn} has ended already; its record is kept as it is")
            if phase == "ended" and events is not None:
                if prompt is None:  # the transcript holds the turn's prompt too, as its start recorded it
                    prompt = next((p.get("prompt") for p in this_turn if p.get("phase") == "started"), None)
                # kept only with the recorded end: see put_turn_transcript
                payload["transcript"] = put_turn_transcript(store, READER_TURNS_DIR / f"{turn}.json",
                                                            {**payload, "prompt": prompt, "events": events})
            elif phase == "started":
                payload["prompt"] = str(prompt or "")
            append_event(store, READER_TURN_EVENT, f"the Reader's turn {turn} {phase}", entity_id=None, payload=payload, conn=conn)
    except (sqlite3.Error, OSError) as exc:
        raise ProofMapError(
            "READER_TURN_RECORD_FAILED", f"the Reader's turn {turn} could not be recorded ({phase}): {exc}", details={"phase": phase}
        ) from exc


def reader_turns(store: ProjectStore) -> list[dict[str, Any]]:
    """The Reader's turns kept with the project, oldest first, one entry per turn. A turn with no recorded end reads
    `ended: False` and no outcome: it is not taken for one that ended ok. A transcript is named only while its file
    is there."""
    turns: dict[str, dict[str, Any]] = {}
    for event in list_events_of_kind(store, READER_TURN_EVENT):
        p = event.payload or {}
        entry = turns.setdefault(str(p.get("turn") or ""), {
            "turn": p.get("turn"), "pursuit_id": p.get("pursuit_id"), "by": p.get("by"), "provider": p.get("provider", ""),
            "at": event.created_at.isoformat(), "ended": False, "ended_at": None, "job": None, "session_id": None,
            "outcome": None, "reason": "", "exit": None, "is_error": None, "tool_failures": None,
            "backend": None, "preview_limits": None, "transcript": None})
        if p.get("phase") == "ended":
            transcript = p.get("transcript")
            entry.update(ended=True, ended_at=event.created_at.isoformat(), job=p.get("job"), session_id=p.get("session_id"),
                         outcome=p.get("outcome"), reason=p.get("reason", ""), exit=p.get("exit"), is_error=p.get("is_error"),
                         tool_failures=p.get("tool_failures"), backend=p.get("backend"), preview_limits=p.get("preview_limits"),
                         transcript=transcript if transcript and (store.root / transcript).is_file() else None)  # only while its file is there
    return list(turns.values())


def reader_turn_transcript(store: ProjectStore, turn: str) -> dict | None:
    """A Reader turn's record with its conversation (`events`), as record_reader_turn kept it; None when there is none."""
    if not _TURN_ID.fullmatch(turn or ""):
        return None
    try:
        return json.loads((store.root / READER_TURNS_DIR / f"{turn}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def reader_turn(store: ProjectStore, turn: str) -> dict | None:
    """One Reader turn kept with the project, read back (#224): its record (as `reader_turns` gives it), its prompt,
    its events as its backend reported them (None when its conversation is not kept), and the event fields whose length
    reached that backend's preview limit (`possibly_shortened`: event number from 1, field, limit, and which end the
    backend keeps; None when the limits were not recorded), and the fields its events have that the backend stated
    nothing about (`unstated_fields`, `<event>.<field>`: whether those were shortened is unknown; None when the limits
    were not recorded). The backends mark no cut, so a field at its limit may or may not have been shortened.
    None when no such turn is kept."""
    record = next((entry for entry in reader_turns(store) if entry["turn"] == turn), None)
    if record is None:
        return None
    transcript = reader_turn_transcript(store, turn) if record["transcript"] else None
    events = transcript.get("events") if transcript else None
    limits = record["preview_limits"]
    return {**record, "prompt": (transcript or {}).get("prompt"), "events": events,
            "possibly_shortened": _at_preview_limit(events, limits), "unstated_fields": _unstated_fields(events, limits)}


def _unstated_fields(events: list[dict] | None, limits: dict | None) -> list[str] | None:
    """The `<event>.<field>`s of `events` the backend's limits say nothing of; None when the limits are unknown."""
    if limits is None:
        return None
    return sorted({f"{event.get('t')}.{field}" for event in events or [] for field, value in event.items()
                   if field != "t" and isinstance(value, str) and not _field_limit(limits, event, field)[0]})


def _field_limit(limits: dict, event: dict, field: str) -> tuple[bool, int | None, str]:
    """What the backend stated of one event field: (stated at all, the characters it keeps or None when it keeps the
    field whole, which end it keeps)."""
    key = f"{event.get('t')}.{field}"
    named = f"{key}[{event.get('name')}]"
    if named in limits:
        stated = limits[named]
    elif key in limits:
        stated = limits[key]
    else:
        return False, None, "start"
    if isinstance(stated, dict):
        return True, stated.get("chars"), "end" if stated.get("keeps") == "end" else "start"
    return True, stated, "start"


def _at_preview_limit(events: list[dict] | None, limits: dict[str, int | dict | None] | None) -> list[dict] | None:
    """The fields of `events` whose length reached their backend's limit; None when the limits are unknown."""
    if limits is None:
        return None
    reached = []
    for number, event in enumerate(events or [], 1):
        for field, value in event.items():
            if not isinstance(value, str):
                continue
            _, limit, keeps = _field_limit(limits, event, field)
            if isinstance(limit, int) and len(value) >= limit:
                reached.append({"event": number, "field": field, "limit": limit, "keeps": keeps})
    return reached
