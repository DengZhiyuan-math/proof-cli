"""Human Review authority: who may decide, and which decisions count (ADR-0009, issue #35).

A Human Review decision counts only if it is signed by an enrolled Reviewer
passkey. This module owns:

- the **Reviewer key registry**: append-only and hash-chained, replayed and
  re-verified on every read. The first key is trust-on-first-use (it signs
  its own enrollment); every later enrollment or revocation must be signed
  by a key active at that point of the registry chain. Key validity is a
  matter of *chain position*, never of a timestamp anyone chose.
- **the pin**: the researcher's user-level config records the first key's
  fingerprint and the newest row of each chain this machine has seen. A
  registry that disagrees with the pin, has none, or has lost a pinned row,
  is not trusted; trust on first use is never re-run once a project has
  ever had keys.
- **authorization at decision time** (`authorize`): whether a signed
  decision is valid for exactly the operation about to run — this project
  instance, the exact Candidate proof text, the accepted interface, the
  dependency pins, the Challenges it resolves, and the chain prefixes the
  signer saw.
- **verification on read** (`verify_decision_row`): whether a stored
  decision row still carries a valid signature from a key active at the
  registry position it committed to, is exactly what was signed, and still
  commits to this project's chains. What a verified decision *means* for a
  node is `proof_map`'s call.
- **integrity warnings**: everything that doesn't verify is surfaced, never
  silently dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .domain import utc_now
from .signing import (
    RP_ID,
    SUPPORTED_ALGORITHMS,
    DecisionKind,
    DecisionPayload,
    PinnedDependency,
    SignatureError,
    SignedDecision,
    b64url_decode,
    payload_hash,
    public_key_fingerprint,
    sign_count,
    verify_signed_decision,
)
from .storage import (
    ProjectStore,
    active_transaction,
    adopt_legacy_into_ledger,
    after_commit,
    chain_head,
    chain_row_hash,
    genesis_row_hash,
    get_candidate_proof,
    in_transaction,
    insert_reviewer_key_row,
    list_events,
    list_raw_chain_rows,
    read_project_instance_id,
    read_state,
    review_history_payload_recorded,
)

USER_CONFIG_ENV_VAR = "PROOF_CLI_CONFIG_HOME"

_ORIGIN_PORT_BASE = 20000
_ORIGIN_PORT_SPAN = 30000


def origin_port(instance: str) -> int:
    """The review app's port for one project instance: stable, so its origin is too."""
    return _ORIGIN_PORT_BASE + int(hashlib.sha256(f"proof-cli origin {instance}".encode()).hexdigest()[:8], 16) % _ORIGIN_PORT_SPAN


def project_origin(store: ProjectStore) -> str:
    """The one WebAuthn origin a signature for this project may come from (#36).

    Derived from the project's instance id, so it's fixed for the project
    and differs between projects: an assertion made on some other localhost
    page — another project's review app included — never verifies here.
    """
    return f"http://{RP_ID}:{origin_port(read_project_instance_id(store))}"

ENROLL = "enroll"
REVOKE = "revoke"

# how far a signature's own timestamp may run ahead of the clock that records it
_CLOCK_SKEW = timedelta(minutes=5)

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
    (DecisionKind.legacy_decline, "decline"): ("legacy_item", "superseded"),
}


def decision_row_for(kind: DecisionKind, decision: str) -> tuple[str, str]:
    """(row object_type, row decision value) a signed decision of this kind and value is recorded as."""
    return _DECISION_ROWS[(kind, decision)]


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
    aaguid: str | None = None  # the authenticator model, where it discloses one
    # where in the registry chain the key was enrolled / revoked: the key is
    # valid for exactly the registry prefixes between the two
    enrolled_seq: int
    revoked_seq: int | None = None
    # when those rows were appended — for display only, never for validity
    enrolled_at: datetime
    revoked_at: datetime | None = None

    def active_in(self, registry_seq: int) -> bool:
        """Whether the key is active in the registry as of its row `registry_seq`."""
        return self.enrolled_seq <= registry_seq and (self.revoked_seq is None or registry_seq < self.revoked_seq)

    @property
    def reviewer_id(self) -> str:
        """Who decided, as recorded: the key itself, never the self-declared
        `display_name` (CONTEXT.md, Reviewer passkey)."""
        return f"passkey:{self.fingerprint[:16]}"


class EnrollmentRequest(BaseModel):
    """A new Reviewer passkey plus the signed `reviewer_enrollment` decision authorizing it.

    Produced by the web app's WebAuthn registration ceremony (#36) — there
    is deliberately no CLI path. For the very first key the decision is
    signed by that key itself (proof of possession, trust on first use);
    for every later key it must be signed by a key that is already active.
    """

    credential_id: str
    public_key_spki: str
    alg: int
    display_name: str
    aaguid: str | None = None
    signed_decision: SignedDecision


# -- user-level config: the pin -----------------------------------------------------


def user_config_dir() -> Path:
    if os.environ.get(USER_CONFIG_ENV_VAR):
        return Path(os.environ[USER_CONFIG_ENV_VAR])
    base = Path(os.environ["XDG_CONFIG_HOME"]) if os.environ.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "proof-cli"


def _pins_path() -> Path:
    return user_config_dir() / "reviewer-pins.json"


def _read_pin_file() -> tuple[bool, dict[str, Any]]:
    """(readable, contents). A missing file is readable and empty; a corrupt one is not readable."""
    path = _pins_path()
    if not path.exists():
        return True, {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False, {}
    return (True, data) if isinstance(data, dict) else (False, {})


def _project_key(store: ProjectStore) -> str:
    # keyed by where the project lives, not its id: two projects on one
    # machine commonly share the default id
    return str(store.root.resolve())


def _project_pin(store: ProjectStore) -> tuple[bool, dict[str, Any] | None]:
    readable, data = _read_pin_file()
    entry = data.get("projects", {}).get(_project_key(store)) if readable else None
    return readable, entry if isinstance(entry, dict) else None


def pinned_first_fingerprint(store: ProjectStore) -> str | None:
    return (_project_pin(store)[1] or {}).get("first_key_fingerprint")


def _write_pin(store: ProjectStore, **fields: Any) -> None:
    """Create or advance this project's pin. The first key and instance are written once, never overwritten."""
    readable, data = _read_pin_file()
    if not readable:
        raise AuthorityError("PIN_FILE_UNREADABLE", f"{_pins_path()} can't be read; fix or restore it by hand")
    projects = data.setdefault("projects", {})
    entry = dict(projects.get(_project_key(store)) or {})
    for once in ("first_key_fingerprint", "project_instance"):
        if once in entry:
            fields.pop(once, None)
    entry.update({"project_id": read_state(store).project_id, **fields})
    projects[_project_key(store)] = entry
    path = _pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _advance_history_pins(store: ProjectStore) -> None:
    """Record the newest review-history and ledger rows in the pin, best-effort.

    Run after each signed decision and ledger append commits. A pinned row
    that later goes missing means the newest history was deleted — the one
    edit the hash chain alone can't see. Best-effort because the pin file
    may, by design, be unwritable for an agent's sandbox (see ADR-0009): a
    pin that isn't advanced is an older lower bound, still present, never a
    false alarm.
    """
    if _project_pin(store)[1] is None:
        return
    try:
        _write_pin(
            store,
            review_head=chain_head(store, "review_history"),
            ledger_head=chain_head(store, "proof_ledger"),
        )
    except (OSError, AuthorityError):
        pass


def schedule_history_pin_advance(store: ProjectStore) -> None:
    """Advance the history pins once the current transaction (if any) commits."""
    after_commit(store, lambda: _advance_history_pins(store))


# -- the verified view of the chains -----------------------------------------------


@dataclass
class RowVerdict:
    """Whether one decision row carries authority: `verified`, `unsigned`
    (legacy, or appended without a signature), or `invalid`."""

    status: Literal["verified", "unsigned", "invalid"]
    payload: DecisionPayload | None = None
    reason: str = ""


@dataclass
class _Snapshot:
    instance: str
    origin: str
    trusted: bool
    keys: dict[str, ReviewerKey]  # by credential id, every key that was ever validly enrolled
    first_fingerprint: str | None
    registry_hashes: dict[str, int]  # registry row hash -> seq; genesis -> 0
    registry_latest_seq: int
    history_rows: dict[str, dict]  # review-history rows by id
    history_hashes: dict[str, int]  # row hash -> seq; genesis -> 0
    ledger_hashes: dict[str, int]
    # (object_type, object_id, kind) -> its decision rows, oldest first
    rows_by_object: dict[tuple[str, str, str | None], list[dict]]
    # entry -> object_id -> the *first* ledger row for it (later ones are ignored)
    ledger: dict[str, dict[str, dict]]
    has_signed_history: bool
    warnings: list[AuthorityWarning]
    verdicts: dict[str, RowVerdict] = field(default_factory=dict)
    resolutions: dict[str, dict] | None = None
    legacy_handled: dict[str, tuple[str, dict]] | None = None


_SNAPSHOTS: dict[tuple, _Snapshot] = {}
_WATCHER_LIMIT = 8


class _Watcher:
    """One open, read-only connection per database, shared by every thread.

    SQLite bumps a connection's `PRAGMA data_version` whenever *any other*
    connection commits — an in-place edit with the triggers dropped and
    the file's mtime put back included. A snapshot cached under (this
    watcher's generation, its data_version) is therefore stale the moment
    anyone changes anything, however long the process runs (#36). Each
    watcher gets a fresh generation, so a closed-and-reopened connection
    can never alias an older cache entry (an `id()` could).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, tuple[int, sqlite3.Connection]] = {}
        self._generation = 0

    def version(self, store: ProjectStore) -> tuple[int, int]:
        path = str(store.db_path.resolve())
        with self._lock:
            entry = self._connections.pop(path, None)
            if entry is None:
                if len(self._connections) >= _WATCHER_LIMIT:
                    oldest_path = next(iter(self._connections))
                    self._connections.pop(oldest_path)[1].close()
                self._generation += 1
                entry = (self._generation, sqlite3.connect(path, timeout=30.0, check_same_thread=False))
            self._connections[path] = entry  # most recently used last
            generation, conn = entry
            return generation, conn.execute("PRAGMA data_version").fetchone()[0]


_WATCHER = _Watcher()


def _data_version(store: ProjectStore) -> tuple[int, int]:
    return _WATCHER.version(store)


def _chain_hashes(rows: list[dict], table: str, genesis: str, warnings: list[AuthorityWarning]) -> dict[str, int]:
    """Row hash -> seq for a chained table, recording a warning at every broken link.

    Rows appended before the chain existed (pre-#35 review history) carry
    no link; once a linked row appears, every later row must be linked.
    """
    hashes = {genesis: 0}
    previous_hash = genesis
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
    except (ValidationError, ValueError, TypeError):
        return None


def _recorded_at(row: dict) -> datetime:
    """When the service appended a row (display only). Timezone-aware, or the row is invalid."""
    moment = datetime.fromisoformat(row["created_at"])
    if moment.tzinfo is None:
        raise ValueError("naive timestamp")
    return moment


def _registry_row_problem(
    row: dict,
    *,
    position: int,
    project_id: str,
    instance: str,
    keys: dict[str, ReviewerKey],
    seen_payloads: set[str],
) -> str | None:
    """Why a registry row can't be honored, or None.

    `position` is the registry seq of the row before it: the signer must be
    active in exactly that prefix — its place in the chain, not any time.
    """
    signed = _parse_signed(row["signed_decision"])
    if signed is None:
        return "no parseable signed decision"
    payload = signed.payload
    if payload.kind != DecisionKind.reviewer_enrollment or payload.decision != row["entry"]:
        return "the signed decision is not this enrollment/revocation"
    if payload.project_id != project_id or payload.project_instance != instance:
        return "signed for a different project"
    if payload.target_id != row["fingerprint"] or payload.credential_id != row["credential_id"]:
        return "the signed decision names a different key or credential"
    if payload_hash(payload) in seen_payloads:
        return "a replay of a registry decision already recorded"
    spki = b64url_decode(row["public_key_spki"])
    if public_key_fingerprint(spki) != row["fingerprint"] or row["alg"] not in SUPPORTED_ALGORITHMS:
        return "fingerprint or algorithm doesn't match the public key"
    _recorded_at(row)

    signer_id = signed.assertion.credential_id
    active = [key for key in keys.values() if key.active_in(position)]
    if row["entry"] == ENROLL:
        if row["credential_id"] in keys or any(key.fingerprint == row["fingerprint"] for key in keys.values()):
            return "that key is already enrolled (or was, and is revoked)"
        if not keys:
            # trust on first use, only while no key has ever been enrolled:
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
        if not [key for key in keys.values() if key.fingerprint == row["fingerprint"] and key.active_in(position)]:
            return "revokes a key that isn't enrolled and active"
        signer = next((key for key in active if key.credential_id == signer_id), None)
        if signer is None:
            return "not signed by an active Reviewer key"
        signer_spki, signer_alg = b64url_decode(signer.public_key_spki), signer.alg
    try:
        verify_signed_decision(
            signed, public_key_spki=signer_spki, alg=signer_alg, expected_origin=f"http://{RP_ID}:{origin_port(instance)}"
        )
    except SignatureError as exc:
        return exc.message
    return None


def _replay_registry(
    rows: list[dict], *, project_id: str, instance: str, warnings: list[AuthorityWarning]
) -> tuple[bool, dict[str, ReviewerKey], str | None, dict[str, int]]:
    chain_warnings: list[AuthorityWarning] = []
    hashes = _chain_hashes(rows, "reviewer_keys", genesis_row_hash(instance), chain_warnings)
    warnings.extend(chain_warnings)
    trusted = not chain_warnings

    keys: dict[str, ReviewerKey] = {}
    seen_payloads: set[str] = set()
    first_fingerprint: str | None = None
    position = 0
    for row in rows:
        try:
            problem = _registry_row_problem(
                row, position=position, project_id=project_id, instance=instance, keys=keys, seen_payloads=seen_payloads
            )
        except Exception as exc:  # a junk row must never make every read fail
            problem = f"unreadable ({type(exc).__name__})"
        position = row["seq"]
        if problem is not None:
            warnings.append(
                AuthorityWarning(
                    code="INVALID_REGISTRY_ENTRY",
                    message=f"reviewer key registry row {row['seq']} is not honored: {problem}",
                    details={"seq": row["seq"], "fingerprint": row.get("fingerprint")},
                )
            )
            continue
        payload = _parse_signed(row["signed_decision"]).payload
        seen_payloads.add(payload_hash(payload))
        if row["entry"] == ENROLL:
            keys[row["credential_id"]] = ReviewerKey(
                credential_id=row["credential_id"],
                public_key_spki=row["public_key_spki"],
                alg=row["alg"],
                fingerprint=row["fingerprint"],
                display_name=row["display_name"],
                aaguid=row.get("aaguid"),
                enrolled_seq=row["seq"],
                enrolled_at=_recorded_at(row),
            )
            first_fingerprint = first_fingerprint or row["fingerprint"]
        else:
            for key in keys.values():
                if key.fingerprint == row["fingerprint"] and key.revoked_seq is None:
                    key.revoked_seq = row["seq"]
                    key.revoked_at = _recorded_at(row)
    return trusted, keys, first_fingerprint, hashes


def _check_pin(
    store: ProjectStore,
    *,
    instance: str,
    registry_rows: list[dict],
    first_fingerprint: str | None,
    hashes: dict[str, dict[str, int]],
    warnings: list[AuthorityWarning],
) -> bool:
    """Whether the registry agrees with this machine's pin (warning about each way it doesn't)."""
    trusted = True

    def _untrust(code: str, message: str, **details: Any) -> None:
        nonlocal trusted
        trusted = False
        warnings.append(AuthorityWarning(code=code, message=message, details=details))

    readable, pin = _project_pin(store)
    if not readable:
        _untrust("PIN_FILE_UNREADABLE", f"{_pins_path()} can't be read; no Reviewer key is trusted until it's restored")
        return trusted
    if pin is None:
        if registry_rows:
            _untrust(
                "REVIEWER_PIN_MISSING",
                "this project has Reviewer keys but no pin in your user config (moved, cloned, or the pin was "
                "deleted); no decision is trusted until you re-pin it by hand (see ADR-0009, recovery)",
            )
        return trusted
    if not registry_rows:
        _untrust("REVIEWER_REGISTRY_EMPTIED", "your user config pins a Reviewer key, but this project's registry is empty")
        return trusted
    if pin.get("project_instance") not in (None, instance) or pin.get("first_key_fingerprint") != first_fingerprint:
        _untrust(
            "REVIEWER_REGISTRY_MISMATCH",
            "this project's Reviewer keys don't match the ones pinned in your user config; no decision is trusted",
            registry_first_fingerprint=first_fingerprint,
            pinned_first_fingerprint=pin.get("first_key_fingerprint"),
        )
    for pin_field, table in (("registry_head", "reviewer_keys"), ("review_head", "review_history"), ("ledger_head", "proof_ledger")):
        pinned = pin.get(pin_field)
        if pinned is not None and pinned not in hashes[table]:
            _untrust(
                "HISTORY_TRUNCATED",
                f"{table} no longer contains the newest row your user config recorded: rows were deleted",
                table=table,
            )
    return trusted


def _ledger(rows: list[dict], warnings: list[AuthorityWarning]) -> dict[str, dict[str, dict]]:
    ledger: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_object = ledger.setdefault(row["entry"], {})
        if row["object_id"] in by_object:
            warnings.append(
                AuthorityWarning(
                    code="LEDGER_DUPLICATE_IGNORED",
                    message=f"a second {row['entry']} entry for {row['object_id']} was ignored",
                    details={"entry": row["entry"], "object_id": row["object_id"], "seq": row["seq"]},
                )
            )
            continue
        try:
            by_object[row["object_id"]] = {**json.loads(row["data"]), "_seq": row["seq"]}
        except ValueError:
            warnings.append(AuthorityWarning(code="LEDGER_ROW_UNREADABLE", message=f"ledger row {row['seq']} is unreadable"))
    return ledger


def _snapshot(store: ProjectStore) -> _Snapshot:
    # One-shot upkeep before any read of the history: a pre-#33 project's
    # review records still sit in collaboration.json until migrated, and a
    # pre-#35 project's nodes and Challenges aren't in the ledger until
    # adopted. Never inside an open transaction: the snapshot reads committed
    # state through separate connections, so rows written on the caller's
    # transaction would be invisible to it. (Imported lazily: collaboration
    # itself imports this module.)
    if active_transaction(store) is None:
        from .collaboration import _migrate_legacy_review_records

        _migrate_legacy_review_records(store)
        adopt_legacy_into_ledger(store)
    cache_key = (
        _project_key(store),
        _data_version(store),
        json.dumps(_project_pin(store), sort_keys=True, default=str),
    )
    cached = _SNAPSHOTS.get(cache_key)
    if cached is not None:
        return cached
    project_id = read_state(store).project_id
    instance = read_project_instance_id(store)
    genesis = genesis_row_hash(instance)
    warnings: list[AuthorityWarning] = []
    registry_rows = list_raw_chain_rows(store, "reviewer_keys")
    trusted, keys, first_fingerprint, registry_hashes = _replay_registry(
        registry_rows, project_id=project_id, instance=instance, warnings=warnings
    )
    history = list_raw_chain_rows(store, "review_history")
    history_hashes = _chain_hashes(history, "review_history", genesis, warnings)
    ledger_rows = list_raw_chain_rows(store, "proof_ledger")
    ledger_hashes = _chain_hashes(ledger_rows, "proof_ledger", genesis, warnings)
    hashes = {"reviewer_keys": registry_hashes, "review_history": history_hashes, "proof_ledger": ledger_hashes}
    trusted = (
        _check_pin(
            store,
            instance=instance,
            registry_rows=registry_rows,
            first_fingerprint=first_fingerprint,
            hashes=hashes,
            warnings=warnings,
        )
        and trusted
    )
    rows_by_object: dict[tuple[str, str, str | None], list[dict]] = {}
    for row in history:
        if row["entry"] == "decision":
            rows_by_object.setdefault((row["object_type"], row["object_id"], row["kind"]), []).append(row)
    snapshot = _Snapshot(
        instance=instance,
        origin=f"http://{RP_ID}:{origin_port(instance)}",
        trusted=trusted,
        keys=keys,
        first_fingerprint=first_fingerprint,
        registry_hashes=registry_hashes,
        registry_latest_seq=registry_rows[-1]["seq"] if registry_rows else 0,
        history_rows={row["id"]: row for row in history},
        history_hashes=history_hashes,
        ledger_hashes=ledger_hashes,
        rows_by_object=rows_by_object,
        ledger=_ledger(ledger_rows, warnings),
        has_signed_history=any(row["signed_decision"] for row in history),
        warnings=warnings,
    )
    if len(_SNAPSHOTS) > 64:
        _SNAPSHOTS.clear()
    _SNAPSHOTS[cache_key] = snapshot
    return snapshot


def ledger_entries(store: ProjectStore, entry: str) -> dict[str, dict]:
    """The first `proof_ledger` fact of this kind per object (a node's creation, a Challenge's opening). Read-only."""
    return _snapshot(store).ledger.get(entry, {})


# -- registry operations ------------------------------------------------------------


def list_reviewer_keys(store: ProjectStore) -> list[ReviewerKey]:
    """Every validly enrolled Reviewer key, revoked ones included, in enrollment order."""
    return [key.model_copy() for key in _snapshot(store).keys.values()]


def active_reviewer_keys(store: ProjectStore) -> list[ReviewerKey]:
    snapshot = _snapshot(store)
    if not snapshot.trusted:
        return []
    return [key.model_copy() for key in snapshot.keys.values() if key.active_in(snapshot.registry_latest_seq)]


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
        "aaguid": credential.aaguid,
        "signed_decision": signed.model_dump_json(),
        "created_at": utc_now().isoformat(),
    }


def _append_registry_row(store: ProjectStore, row: dict, *, refusal_code: str, refusal: str) -> None:
    project_id = read_state(store).project_id
    _snapshot(store)  # one-shot upkeep (migration, ledger adoption) runs outside the transaction
    with store.transaction() as conn:
        # re-read under the write lock: two concurrent enrollments must not
        # both see an empty registry and both take trust on first use
        snapshot = _snapshot(store)
        readable, pin = _project_pin(store)
        registry_rows = list_raw_chain_rows(store, "reviewer_keys")
        if registry_rows and not snapshot.trusted:
            raise AuthorityError(
                "REGISTRY_NOT_TRUSTED", "the Reviewer key registry doesn't verify; resolve its integrity warnings first"
            )
        if not registry_rows and (not readable or pin is not None or snapshot.has_signed_history):
            raise AuthorityError(
                "REGISTRY_NOT_TRUSTED",
                "this project has had Reviewer keys (its user-config pin or its signed history says so), but its "
                "registry is empty: trust on first use is never re-run — see ADR-0009, recovery",
            )
        try:
            problem = _registry_row_problem(
                row,
                position=snapshot.registry_latest_seq,
                project_id=project_id,
                instance=snapshot.instance,
                keys={key.credential_id: key.model_copy() for key in snapshot.keys.values()},
                seen_payloads=set(),
            )
        except Exception as exc:
            problem = f"unreadable ({type(exc).__name__})"
        if problem is not None:
            raise AuthorityError(refusal_code, f"{refusal}: {problem}")
        insert_reviewer_key_row(conn, row)


def _advance_registry_pin(store: ProjectStore) -> None:
    rows = list_raw_chain_rows(store, "reviewer_keys")
    snapshot = _snapshot(store)
    _write_pin(
        store,
        project_instance=snapshot.instance,
        first_key_fingerprint=snapshot.first_fingerprint or rows[0]["fingerprint"],
        registry_head=chain_row_hash(rows[-1]),
        review_head=chain_head(store, "review_history"),
        ledger_head=chain_head(store, "proof_ledger"),
    )


def enroll_reviewer_key(store: ProjectStore, request: EnrollmentRequest) -> ReviewerKey:
    """Append a Reviewer passkey to the registry (ADR-0009 point 5). Called by the web app's registration ceremony.

    The first key is trust-on-first-use — allowed only for a project that
    has never had keys (no registry, no pin, no signed history) — and is
    pinned in the user-level config; any later key needs a
    `reviewer_enrollment` decision signed by an active key.
    """
    _append_registry_row(
        store,
        _key_row(request, entry=ENROLL, signed=request.signed_decision),
        refusal_code="ENROLLMENT_REFUSED",
        refusal="enrollment refused",
    )
    _advance_registry_pin(store)
    return next(key for key in list_reviewer_keys(store) if key.credential_id == request.credential_id)


def revoke_reviewer_key(store: ProjectStore, signed_decision: SignedDecision | None) -> ReviewerKey:
    """Revoke the key whose fingerprint the signed `revoke` decision names; never the last active one.

    Takes effect at its position in the registry chain: decisions that
    committed to an earlier registry prefix still count, later ones by the
    revoked key never do — whatever timestamp anyone put on the revocation.
    """
    if signed_decision is None:
        raise human_review_required(DecisionKind.reviewer_enrollment, "revoke")
    snapshot = _snapshot(store)
    latest = snapshot.registry_latest_seq
    target = next(
        (key for key in snapshot.keys.values() if key.fingerprint == signed_decision.payload.target_id and key.active_in(latest)),
        None,
    )
    if target is None:
        raise AuthorityError("NOT_ENROLLED", f"no active Reviewer key {signed_decision.payload.target_id}")
    if not [key for key in snapshot.keys.values() if key.fingerprint != target.fingerprint and key.active_in(latest)]:
        raise AuthorityError("LAST_REVIEWER_KEY", "refusing to revoke the only active Reviewer key; enroll another first")
    _append_registry_row(
        store,
        _key_row(target, entry=REVOKE, signed=signed_decision),
        refusal_code="REVOCATION_REFUSED",
        refusal="revocation refused",
    )
    _advance_registry_pin(store)
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
    interface_fingerprint: str | None = None,
    dependency_pins: list[PinnedDependency] | None = None,
    resolves_challenges: list[str] | None = None,
    credential_id: str | None = None,
    resigns: str | None = None,
) -> DecisionPayload:
    """The exact payload a reviewer's passkey must sign for this decision, as of now."""
    return DecisionPayload(
        project_id=read_state(store).project_id,
        project_instance=read_project_instance_id(store),
        kind=kind,
        target_id=target_id,
        candidate_proof_id=candidate_proof_id,
        candidate_proof_sha256=candidate_proof_sha256(store, candidate_proof_id) if candidate_proof_id else None,
        interface_fingerprint=interface_fingerprint,
        dependency_pins=list(dependency_pins or []),
        resolves_challenges=list(resolves_challenges or []),
        credential_id=credential_id,
        resigns=resigns,
        decision=decision,
        rationale=rationale,
        previous_row_hash=chain_head(store, "review_history"),
        registry_head=chain_head(store, "reviewer_keys"),
        ledger_head=chain_head(store, "proof_ledger"),
    )


def human_review_required(kind: DecisionKind | str, target_id: str) -> AuthorityError:
    kind_name = kind.value if isinstance(kind, DecisionKind) else kind
    return AuthorityError(
        "HUMAN_REVIEW_REQUIRED",
        f"{kind_name} on {target_id} is a Human Review decision and needs a signed decision from an enrolled "
        "Reviewer passkey",
        details={"kind": kind_name, "target_id": target_id},
    )


def _signing_key(snapshot: _Snapshot, signed: SignedDecision, *also_at: int) -> ReviewerKey:
    """The key that signed, if it's active at the registry prefix the payload committed to (and at `also_at`)."""
    committed = snapshot.registry_hashes.get(signed.payload.registry_head or "")
    key = snapshot.keys.get(signed.assertion.credential_id)
    if committed is None or key is None or not all(key.active_in(seq) for seq in (committed, *also_at)):
        raise AuthorityError(
            "UNKNOWN_REVIEWER_KEY",
            "the decision isn't signed by a Reviewer key active in the registry it was signed against",
            details={"credential_id": signed.assertion.credential_id},
        )
    return key


def signature_key(store: ProjectStore, signed: SignedDecision) -> ReviewerKey:
    """The trusted key, active now, that a decision's signature verifies under — or AuthorityError.

    Only the signature: whether it authorizes a given operation is `authorize`.
    """
    snapshot = _snapshot(store)
    if not snapshot.trusted:
        raise AuthorityError("REGISTRY_NOT_TRUSTED", "the Reviewer key registry doesn't verify; no decision can be trusted")
    key = _signing_key(snapshot, signed, snapshot.registry_latest_seq)
    try:
        verify_signed_decision(
            signed, public_key_spki=b64url_decode(key.public_key_spki), alg=key.alg, expected_origin=snapshot.origin
        )
    except SignatureError as exc:
        raise AuthorityError(exc.code, exc.message) from exc
    return key.model_copy()


def authorize(
    store: ProjectStore,
    signed: SignedDecision | None,
    *,
    kind: DecisionKind,
    target_id: str,
    decision: str,
    candidate_proof_id: str | None = None,
    interface_fingerprint: str | None = None,
    dependency_pins: list[PinnedDependency] | None = None,
    resolves_challenges: list[str] | None = None,
    resigns: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ReviewerKey:
    """Check that `signed` authorizes exactly this operation, now; return the signing key.

    Everything the service is about to do must be what was signed: this
    project instance, kind, target and decision, the current Candidate proof
    and the SHA-256 of its text on disk, the accepted interface, the
    dependency pins, and the Challenges it resolves. The payload must commit
    to chain prefixes this project has — a review history already holding
    every earlier decision on the same target, a registry in which the key
    is active (and still active now), a proof ledger — must not have been
    recorded already, and must verify.

    Call it on the operation's transaction *before* that operation writes
    anything: the history it checks against is the committed one. Once the
    transaction commits, the pin's history heads advance.
    """
    if signed is None:
        raise human_review_required(kind, target_id)
    payload = signed.payload
    expected = {
        "project_id": read_state(store).project_id,
        "project_instance": read_project_instance_id(store),
        "kind": kind,
        "target_id": target_id,
        "decision": decision,
        "candidate_proof_id": candidate_proof_id,
        "candidate_proof_sha256": candidate_proof_sha256(store, candidate_proof_id) if candidate_proof_id else None,
        "interface_fingerprint": interface_fingerprint,
        "dependency_pins": list(dependency_pins or []),
        "resolves_challenges": list(resolves_challenges or []),
        "resigns": resigns,
    }
    for name, value in expected.items():
        if getattr(payload, name) != value:
            raise AuthorityError(
                "SIGNATURE_MISMATCH",
                f"the signed decision's {name} doesn't match this operation; the reviewer signed something else",
                details={"field": name},
            )
    if payload.signed_at > utc_now() + _CLOCK_SKEW:
        raise AuthorityError("SIGNATURE_MISMATCH", "the decision is dated in the future", details={"field": "signed_at"})
    with in_transaction(store, conn) as tx:
        if review_history_payload_recorded(tx, payload_hash(payload)):
            raise AuthorityError("DECISION_ALREADY_RECORDED", "this signed decision has already been recorded")
        snapshot = _snapshot(store)
        committed_seq = snapshot.history_hashes.get(payload.previous_row_hash or "")
        if committed_seq is None or (payload.ledger_head or "") not in snapshot.ledger_hashes:
            raise AuthorityError(
                "UNKNOWN_HISTORY_HEAD", "the decision commits to a review history or ledger this project doesn't have"
            )
        object_type = _DECISION_ROWS[(kind, decision)][0]
        earlier = snapshot.rows_by_object.get((object_type, target_id, kind.value), [])
        if earlier and committed_seq < earlier[-1]["seq"]:
            raise AuthorityError(
                "STALE_DECISION",
                "another decision on this target was recorded after this one was signed; re-sign against the current history",
            )
        key = signature_key(store, signed)
        schedule_history_pin_advance(store)
        return key


def verify_decision_row(store: ProjectStore, row_id: str | None) -> RowVerdict:
    """Whether the review-history decision row `row_id` carries authority (ADR-0009 point 2).

    `verified` means: it carries a signed decision for this project instance
    that verifies under a key active in the registry prefix the payload
    committed to; the row says exactly what was signed (kind, target,
    decision, rationale, reviewer); and the review-history and ledger
    prefixes it commits to are still there — the history one ahead of it,
    holding every earlier decision on the same object and kind (so a replay
    or reorder never verifies).
    """
    if row_id is None:
        return RowVerdict("invalid", reason="no decision row")
    snapshot = _snapshot(store)
    verdict = snapshot.verdicts.get(row_id)
    if verdict is None:
        try:
            verdict = _row_verdict(store, snapshot, row_id)
        except Exception as exc:  # a malformed row is unverifiable, never a crash
            verdict = RowVerdict("invalid", reason=f"unreadable ({type(exc).__name__})")
        snapshot.verdicts[row_id] = verdict
    return verdict


def _row_verdict(store: ProjectStore, snapshot: _Snapshot, row_id: str) -> RowVerdict:
    row = snapshot.history_rows.get(row_id)
    if row is None:
        return RowVerdict("invalid", reason="row not found")
    if not row["signed_decision"]:
        return RowVerdict("unsigned", reason="unsigned (legacy, or appended without a signature)")
    signed = _parse_signed(row["signed_decision"])
    if signed is None:
        return RowVerdict("invalid", reason="the signed decision can't be parsed")
    payload = signed.payload
    mapped = _DECISION_ROWS.get((payload.kind, payload.decision))
    if (
        mapped is None
        or payload.kind.value != row["kind"]
        or payload.target_id != row["object_id"]
        or mapped != (row["object_type"], row["decision"])
    ):
        return RowVerdict("invalid", payload, "the signed payload is a different decision than the recorded one")
    if payload.project_id != read_state(store).project_id or payload.project_instance != snapshot.instance:
        return RowVerdict("invalid", payload, "signed for a different project")
    if row["payload_hash"] != payload_hash(payload):
        return RowVerdict("invalid", payload, "payload hash doesn't match")
    committed_seq = snapshot.history_hashes.get(payload.previous_row_hash or "")
    if committed_seq is None or committed_seq >= row["seq"]:
        return RowVerdict("invalid", payload, "the history it was signed against has been changed")
    if (payload.ledger_head or "") not in snapshot.ledger_hashes:
        return RowVerdict("invalid", payload, "the proof ledger it was signed against has been changed")
    earlier = [other["seq"] for other in snapshot.rows_by_object[(row["object_type"], row["object_id"], row["kind"])] if other["seq"] < row["seq"]]
    if earlier and committed_seq < earlier[-1]:
        return RowVerdict("invalid", payload, "signed without seeing a later decision on the same object (replayed or reordered)")
    if not snapshot.trusted:
        return RowVerdict("invalid", payload, "the Reviewer key registry isn't trusted")
    try:
        key = _signing_key(snapshot, signed)
        verify_signed_decision(
            signed, public_key_spki=b64url_decode(key.public_key_spki), alg=key.alg, expected_origin=snapshot.origin
        )
    except (AuthorityError, SignatureError) as exc:
        return RowVerdict("invalid", payload, exc.message)
    if row["rationale"] != payload.rationale or row["reviewer_id"] != key.reviewer_id:
        return RowVerdict("invalid", payload, "the recorded rationale or reviewer isn't what was signed")
    return RowVerdict("verified", payload)


def decision_rows(store: ProjectStore, object_type: str, object_id: str, kind: str) -> list[dict]:
    """The decision rows on one object and kind, oldest first, as they count.

    For a review that has a signed decision row, unsigned rows appended to
    it later are dropped: only the signed row speaks for that review (B).
    A legacy decision the researcher declined (#42) is dropped too — every
    legacy row predates every signed one, so that can only ever expose
    older unsigned rows, never bring back a signed decision.
    """
    rows = _snapshot(store).rows_by_object.get((object_type, object_id, kind), [])
    signed_reviews = {row["review_id"] for row in rows if row["signed_decision"]}
    declined = {item for item, (how, _) in legacy_handled(store).items() if how == "declined"}
    return [
        row
        for row in rows
        if (row["signed_decision"] or row["review_id"] not in signed_reviews) and row["review_id"] not in declined
    ]


def legacy_handled(store: ProjectStore) -> dict[str, tuple[str, dict]]:
    """Legacy items (#42) the researcher has dealt with: item id -> ("resigned" | "declined", the signed row).

    A re-sign is a verified signed decision whose payload `resigns` the
    item; a decline is a verified `legacy_decline` on it. Computed once per
    snapshot.
    """
    snapshot = _snapshot(store)
    if snapshot.legacy_handled is None:
        handled: dict[str, tuple[str, dict]] = {}
        for row in sorted(snapshot.history_rows.values(), key=lambda row: row["seq"]):
            if row["entry"] != "decision" or not row["signed_decision"]:
                continue
            if row["kind"] != DecisionKind.legacy_decline.value and '"resigns":"' not in row["signed_decision"]:
                continue  # neither a decline nor a re-sign (a set `resigns` is a JSON string)
            verdict = verify_decision_row(store, row["id"])
            if verdict.status != "verified":
                continue
            if row["kind"] == DecisionKind.legacy_decline.value:
                handled.setdefault(row["object_id"], ("declined", row))
            elif verdict.payload.resigns:
                handled.setdefault(verdict.payload.resigns, ("resigned", row))
        snapshot.legacy_handled = handled
    return snapshot.legacy_handled


_RESOLVING_KINDS = (DecisionKind.acceptance.value, DecisionKind.reference_review.value)


def challenge_resolution(store: ProjectStore, challenge_id: str) -> dict | None:
    """The newest verified decision row that resolves `challenge_id`, if any.

    Only a signed decision that *names* the Challenge resolves it: a
    `challenge_resolution` on its id, or an Acceptance / Reference review
    that listed it in `resolves_challenges`. The `challenges` table's own
    status is advisory (C). Computed once per snapshot.
    """
    snapshot = _snapshot(store)
    if snapshot.resolutions is None:
        resolutions: dict[str, dict] = {}
        for row in sorted(snapshot.history_rows.values(), key=lambda row: row["seq"], reverse=True):
            if row["entry"] != "decision" or not row["signed_decision"]:
                continue
            if row["kind"] == DecisionKind.challenge_resolution.value:
                named = [row["object_id"]]
            elif row["kind"] in _RESOLVING_KINDS:
                named = None  # read from the verified payload below
            else:
                continue
            verdict = verify_decision_row(store, row["id"])
            if verdict.status != "verified":
                continue
            for resolved in named if named is not None else verdict.payload.resolves_challenges:
                resolutions.setdefault(resolved, row)
        snapshot.resolutions = resolutions
    return snapshot.resolutions.get(challenge_id)


def _sign_count_warnings(snapshot: _Snapshot) -> list[AuthorityWarning]:
    """An authenticator's counter going backwards means the credential was cloned (#36).

    Most passkeys don't keep a counter (always 0); those are skipped. One
    batch assertion covers several rows with the same counter, so a
    signature already seen isn't a regression.
    """
    warnings: list[AuthorityWarning] = []
    highest: dict[str, int] = {}
    seen: dict[str, set[str]] = {}
    for row in sorted(snapshot.history_rows.values(), key=lambda row: row["seq"]):
        signed = _parse_signed(row["signed_decision"]) if row["entry"] == "decision" else None
        if signed is None:
            continue
        credential, count = signed.assertion.credential_id, sign_count(signed.assertion)
        signatures = seen.setdefault(credential, set())
        if count and signed.assertion.signature not in signatures:
            previous = highest.get(credential)
            if previous is not None and count <= previous:
                key = snapshot.keys.get(credential)
                warnings.append(
                    AuthorityWarning(
                        code="SIGN_COUNT_REGRESSION",
                        message=(
                            f"the signature counter of Reviewer key {key.reviewer_id if key else credential} went "
                            f"backwards ({previous} → {count}): the credential may have been cloned"
                        ),
                        details={"credential_id": credential, "seq": row["seq"]},
                    )
                )
            highest[credential] = max(count, previous or 0)
        signatures.add(signed.assertion.signature)
    return warnings


ACKNOWLEDGE = "acknowledge"


def _acknowledgement_problem(store: ProjectStore, signed: SignedDecision, head: str) -> str | None:
    payload = signed.payload
    if (
        payload.kind != DecisionKind.registry_acknowledgement
        or payload.decision != ACKNOWLEDGE
        or payload.target_id != head
        or payload.project_instance != read_project_instance_id(store)
    ):
        return "not an acknowledgement of the registry as it stands now"
    try:
        signature_key(store, signed)
    except AuthorityError as exc:
        return exc.message
    return None


def registry_status(store: ProjectStore) -> dict[str, Any]:
    """What the review app's banner shows on every page (#36).

    Whether the registry is trusted, and whether the researcher has
    acknowledged it as it stands. The acknowledgement is a passkey-signed
    decision kept in the pin and re-verified here on every read, so editing
    the pin file can't make the banner go away.
    """
    snapshot = _snapshot(store)
    head = chain_head(store, "reviewer_keys")
    stored = (_project_pin(store)[1] or {}).get("acknowledgement")
    signed = _parse_signed(stored) if isinstance(stored, str) else None
    return {
        "trusted": snapshot.trusted,
        "registry_head": head,
        "acknowledged": signed is not None and _acknowledgement_problem(store, signed, head) is None,
        "has_keys": bool(snapshot.keys),
        "origin": snapshot.origin,
    }


def acknowledge_registry(store: ProjectStore, signed: SignedDecision) -> None:
    """Record, with a passkey tap, that the researcher has looked at the current registry."""
    problem = _acknowledgement_problem(store, signed, chain_head(store, "reviewer_keys"))
    if problem is not None:
        raise AuthorityError("SIGNATURE_MISMATCH", f"acknowledgement refused: {problem}")
    _write_pin(store, acknowledgement=signed.model_dump_json())


# -- integrity warnings -----------------------------------------------------------


def list_authority_warnings(store: ProjectStore) -> list[AuthorityWarning]:
    """Everything about Human Review authority itself that doesn't verify.

    Registry, pin and chain problems; every trust-bearing decision row that
    carries no authority — `UNSIGNED_DECISION` for one with no signature at
    all (legacy, or appended behind the service's back), and
    `UNVERIFIABLE_REVIEW_RECORD` for one whose signature is there but
    doesn't verify; and review records found in `collaboration.json`
    (issue #33). What a verified decision no longer means for a node is
    added by `proof_map.list_integrity_warnings`.
    """
    snapshot = _snapshot(store)
    warnings = list(snapshot.warnings)
    handled = legacy_handled(store)
    for row_id, row in snapshot.history_rows.items():
        if row["entry"] != "decision" or row["kind"] is None or row["review_id"] in handled:
            continue
        verdict = verify_decision_row(store, row_id)
        if verdict.status == "verified":
            continue
        details = {"review_id": row["review_id"], "object_type": row["object_type"], "object_id": row["object_id"], "kind": row["kind"]}
        if verdict.status == "unsigned":
            warnings.append(
                AuthorityWarning(
                    code="UNSIGNED_DECISION",
                    message=f"{row['kind']} decision on {row['object_id']} is unsigned (legacy or forged); re-sign to keep it",
                    details=details,
                )
            )
        else:
            warnings.append(
                AuthorityWarning(
                    code="UNVERIFIABLE_REVIEW_RECORD",
                    message=f"{row['kind']} decision on {row['object_id']} doesn't verify: {verdict.reason}",
                    details=details,
                )
            )
    warnings.extend(_sign_count_warnings(snapshot))
    for event in list_events(store):
        if event.kind == "review_history_integrity_warning":
            warnings.append(AuthorityWarning(code="IGNORED_JSON_REVIEW_RECORDS", message=event.message, details=event.payload))
    return warnings


__all__ = [
    "AuthorityError",
    "AuthorityWarning",
    "EnrollmentRequest",
    "ReviewerKey",
    "RowVerdict",
    "USER_CONFIG_ENV_VAR",
    "ACKNOWLEDGE",
    "acknowledge_registry",
    "active_reviewer_keys",
    "authorize",
    "build_decision_payload",
    "candidate_proof_sha256",
    "challenge_resolution",
    "decision_row_for",
    "decision_rows",
    "enroll_reviewer_key",
    "human_review_required",
    "ledger_entries",
    "legacy_handled",
    "list_authority_warnings",
    "list_reviewer_keys",
    "origin_port",
    "pinned_first_fingerprint",
    "project_origin",
    "registry_status",
    "revoke_reviewer_key",
    "schedule_history_pin_advance",
    "signature_key",
    "user_config_dir",
    "verify_decision_row",
]
