from __future__ import annotations

import sqlite3
import uuid
from enum import Enum
from typing import Any

from .collaboration import (
    ReviewGovernanceState,
    ReviewRecord,
    ReviewRecordKind,
    list_review_records,
    record_review_decision,
    record_review_request,
)
from .domain import CandidateProofRecord, ClaimRecord, ProofMapNode, ProofMapNodeKind, utc_now
from .storage import (
    ProjectStore,
    append_event,
    get_active_claim,
    get_candidate_proof as _get_candidate_proof,
    get_proof_map_node,
    insert_claim,
    insert_candidate_proof,
    insert_proof_map_node,
    list_candidate_proofs_for_node,
    list_proof_map_nodes,
    mark_claim_released,
    next_candidate_proof_version,
)
from .vault import candidate_proof_path, write_candidate_proof_file


class ProofMapError(Exception):
    """A domain-rule violation in the proof map service layer.

    Carries a stable `code` so CLI callers can surface it as a JSON envelope
    `error.code` per the spec's agent-facing protocol.
    """

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def create_node(
    store: ProjectStore,
    *,
    node_id: str,
    kind: ProofMapNodeKind | str,
    statement: str,
    display_label: str = "",
    assumptions: list[str] | None = None,
    dependencies: list[str] | None = None,
    created_by: str = "human",
) -> ProofMapNode:
    if get_proof_map_node(store, node_id) is not None:
        raise ProofMapError("NODE_ALREADY_EXISTS", f"proof map node {node_id} already exists")

    try:
        resolved_kind = ProofMapNodeKind(kind)
    except ValueError as exc:
        valid_kinds = ", ".join(member.value for member in ProofMapNodeKind)
        raise ProofMapError(
            "INVALID_KIND",
            f"'{kind}' is not a valid proof map node kind; expected one of: {valid_kinds}",
        ) from exc

    for dependency_id in dependencies or []:
        if get_proof_map_node(store, dependency_id) is None:
            raise ProofMapError(
                "DEPENDENCY_NOT_FOUND",
                f"dependency {dependency_id} does not exist; create it before depending on it",
            )

    node = ProofMapNode(
        id=node_id,
        kind=resolved_kind,
        display_label=display_label,
        statement=statement,
        assumptions=assumptions or [],
        dependencies=dependencies or [],
        created_by=created_by,
        updated_by=created_by,
    )
    try:
        insert_proof_map_node(store, node)
    except sqlite3.IntegrityError as exc:
        if resolved_kind == ProofMapNodeKind.theorem:
            raise ProofMapError(
                "DUPLICATE_THEOREM",
                "a theorem-kind node already exists for this project; only one is allowed",
            ) from exc
        raise ProofMapError("NODE_ALREADY_EXISTS", f"proof map node {node_id} already exists") from exc

    append_event(
        store,
        "proof_map_node_created",
        f"created {resolved_kind.value} node {node.id}",
        entity_id=node.id,
        payload=node.model_dump(mode="json"),
    )
    return node


def get_node(store: ProjectStore, node_id: str) -> ProofMapNode | None:
    return get_proof_map_node(store, node_id)


def require_node(store: ProjectStore, node_id: str) -> ProofMapNode:
    node = get_node(store, node_id)
    if node is None:
        raise ProofMapError("NODE_NOT_FOUND", f"proof map node {node_id} not found")
    return node


def list_nodes(store: ProjectStore) -> list[ProofMapNode]:
    return list_proof_map_nodes(store)


def _claim_conflict(existing: ClaimRecord) -> ProofMapError:
    return ProofMapError(
        "CLAIM_CONFLICT",
        f"node {existing.node_id} is already claimed by {existing.claimant_id}",
        details={
            "claimant_id": existing.claimant_id,
            "session_id": existing.session_id,
            "claimed_at": existing.claimed_at.isoformat(),
        },
    )


def claim_node(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str,
) -> ClaimRecord:
    """Claim exclusive ownership of a node.

    Idempotent for the same (claimant_id, session_id) re-claiming the node it
    already holds. Exclusivity is guaranteed by the `claims` table's partial
    unique index on `node_id WHERE released_at IS NULL` at INSERT time — the
    lookup below is only an optimization, never the source of truth, so a
    genuine race between two claimants is still resolved correctly (see
    `tests/test_proof_map.py::test_claim_concurrency_...`).
    """
    require_node(store, node_id)

    existing = get_active_claim(store, node_id)
    if existing is not None:
        if existing.claimant_id == claimant_id and existing.session_id == session_id:
            return existing
        raise _claim_conflict(existing)

    claim = ClaimRecord(id=str(uuid.uuid4()), node_id=node_id, claimant_id=claimant_id, session_id=session_id)
    try:
        insert_claim(store, claim)
    except sqlite3.IntegrityError as exc:
        existing = get_active_claim(store, node_id)
        if existing is not None and existing.claimant_id == claimant_id and existing.session_id == session_id:
            return existing
        if existing is not None:
            raise _claim_conflict(existing) from exc
        raise ProofMapError("CLAIM_CONFLICT", f"node {node_id} is currently claimed") from exc
    except sqlite3.OperationalError as exc:
        # e.g. "database is locked" under heavy concurrent contention past
        # SQLite's busy_timeout — we don't know who, if anyone, won, so this
        # is honestly a contention error, not a confirmed conflict.
        raise ProofMapError(
            "CLAIM_CONTENDED",
            f"could not claim node {node_id} due to database contention; retry",
        ) from exc

    append_event(
        store,
        "proof_map_node_claimed",
        f"claimed node {node_id} by {claimant_id}",
        entity_id=node_id,
        payload={"claim_id": claim.id, "claimant_id": claimant_id, "session_id": session_id},
    )
    return claim


def release_node(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str,
    force: bool = False,
    actor: str | None = None,
    reason: str | None = None,
) -> ClaimRecord:
    """Release the active claim on a node.

    The owning (claimant_id, session_id) can release its own claim at any
    time. Releasing someone else's claim requires `force=True` with both an
    explicit `actor` and `reason` — an audit trail, never a hidden bypass.
    Claims never expire on their own; this is the only way one ends besides
    a Candidate proof submission (a later ticket).
    """
    require_node(store, node_id)
    claim = get_active_claim(store, node_id)
    if claim is None:
        raise ProofMapError("NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim")

    is_owner = claim.claimant_id == claimant_id and claim.session_id == session_id

    if force:
        if not actor or not reason:
            raise ProofMapError(
                "FORCE_RELEASE_REQUIRES_REASON",
                "force-release requires an explicit actor and reason",
            )
        released_by = actor
        release_reason = reason
        event_kind = "proof_map_claim_force_released"
    elif is_owner:
        released_by = claimant_id
        release_reason = reason or "released by claimant"
        event_kind = "proof_map_claim_released"
    else:
        raise ProofMapError(
            "NOT_CLAIMANT",
            f"{claimant_id}/{session_id} does not hold the active claim on {node_id}",
            details={
                "claimant_id": claim.claimant_id,
                "session_id": claim.session_id,
                "claimed_at": claim.claimed_at.isoformat(),
            },
        )

    released_at = utc_now()
    won_race = mark_claim_released(
        store, claim.id, released_by=released_by, reason=release_reason, released_at=released_at
    )
    if not won_race:
        # Someone else's concurrent release/force-release reached SQLite's
        # write lock first; this claim is no longer active.
        raise ProofMapError("NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim")
    append_event(
        store,
        event_kind,
        f"released claim on {node_id} by {released_by}",
        entity_id=node_id,
        payload={
            "claim_id": claim.id,
            "original_claimant_id": claim.claimant_id,
            "original_session_id": claim.session_id,
            "released_by": released_by,
            "reason": release_reason,
        },
    )
    return claim.model_copy(update={"released_by": released_by, "release_reason": release_reason, "released_at": released_at})


def submit_candidate_proof(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str,
    scoping_rationale: str,
    content: str,
) -> CandidateProofRecord:
    """Submit a Candidate proof for a claimed node.

    Only the node's current claimant may submit; a successful submission ends
    that claim automatically (ownership passes from agent to researcher the
    moment the work is done) and writes an immutable, versioned Markdown file
    to the Proof vault, indexed by a stable id independent of its file path.
    """
    node = require_node(store, node_id)

    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE",
            f"imported_result node {node_id} is immutable and has no candidate proof to submit; "
            "use Reference review instead",
        )

    if not scoping_rationale.strip():
        raise ProofMapError(
            "SCOPING_RATIONALE_REQUIRED",
            "submitting a candidate proof requires stating why this node is now appropriately "
            "scoped to prove directly",
        )

    claim = get_active_claim(store, node_id)
    if claim is None:
        raise ProofMapError(
            "NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim; claim it before submitting"
        )
    if claim.claimant_id != claimant_id or claim.session_id != session_id:
        raise ProofMapError(
            "NOT_CLAIMANT",
            f"{claimant_id}/{session_id} does not hold the active claim on {node_id}",
            details={
                "claimant_id": claim.claimant_id,
                "session_id": claim.session_id,
                "claimed_at": claim.claimed_at.isoformat(),
            },
        )

    version = next_candidate_proof_version(store, node_id)
    proof_id = str(uuid.uuid4())
    submitted_at = utc_now()
    file_path = candidate_proof_path(store.root, node_id, version)

    write_candidate_proof_file(
        file_path,
        id=proof_id,
        node_id=node_id,
        version=version,
        submitted_by=claimant_id,
        created_at=submitted_at.isoformat(),
        scoping_rationale=scoping_rationale,
        content=content,
    )

    record = CandidateProofRecord(
        id=proof_id,
        node_id=node_id,
        version=version,
        file_path=file_path.relative_to(store.root).as_posix(),
        is_current=True,
        submitted_by=claimant_id,
        scoping_rationale=scoping_rationale,
        created_at=submitted_at,
    )
    try:
        insert_candidate_proof(store, record)
    except sqlite3.IntegrityError as exc:
        raise ProofMapError(
            "CANDIDATE_PROOF_VERSION_CONFLICT",
            f"version {version} of node {node_id} is already indexed",
        ) from exc

    mark_claim_released(
        store, claim.id, released_by=claimant_id, reason="candidate proof submitted", released_at=utc_now()
    )

    append_event(
        store,
        "proof_map_candidate_proof_submitted",
        f"submitted candidate proof v{version} for {node_id}",
        entity_id=node_id,
        payload={
            "candidate_proof_id": proof_id,
            "version": version,
            "file_path": record.file_path,
            "submitted_by": claimant_id,
        },
    )
    return record


def get_candidate_proof(store: ProjectStore, candidate_proof_id: str) -> CandidateProofRecord | None:
    return _get_candidate_proof(store, candidate_proof_id)


def require_candidate_proof(store: ProjectStore, candidate_proof_id: str) -> CandidateProofRecord:
    record = get_candidate_proof(store, candidate_proof_id)
    if record is None:
        raise ProofMapError("CANDIDATE_PROOF_NOT_FOUND", f"candidate proof {candidate_proof_id} not found")
    return record


def list_candidate_proofs(store: ProjectStore, node_id: str) -> list[CandidateProofRecord]:
    require_node(store, node_id)
    return list_candidate_proofs_for_node(store, node_id)


class AcceptanceDecision(str, Enum):
    """The only three ways a local node's acceptance_state may ever change.

    Nothing else in the system — not a claim, not a submission, not an
    Evidence check — is allowed to write acceptance_state; `decide_acceptance`
    is the sole entry point, and it always requires explicit human
    confirmation. See ADR (Human Acceptance Authority).
    """

    accept = "accept"
    revision_requested = "revision-requested"
    reject = "reject"


_ACCEPTANCE_DECISION_TO_GOVERNANCE_STATE = {
    AcceptanceDecision.accept: ReviewGovernanceState.approved,
    AcceptanceDecision.revision_requested: ReviewGovernanceState.revision_requested,
    AcceptanceDecision.reject: ReviewGovernanceState.rejected,
}

_ACCEPTANCE_OBJECT_TYPE = "proof_map_node"


def decide_acceptance(
    store: ProjectStore,
    node_id: str,
    decision: AcceptanceDecision | str,
    *,
    reviewer_id: str = "human",
    rationale: str = "",
    confirmed: bool = False,
) -> ReviewRecord:
    """Record a Human Review acceptance decision for a local node.

    `revision_requested` keeps the node open for another claim/submit cycle
    on the same node id, never a new node. `reject` is permanent: the node
    and this decision remain in the project forever, and this function never
    touches `ProjectState.failed_routes` — once a node exists for a route,
    the node's own history is the record of it, never both.
    """
    node = require_node(store, node_id)

    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE",
            f"imported_result node {node_id} is judged by Reference review, not Acceptance",
        )

    try:
        resolved_decision = AcceptanceDecision(decision)
    except ValueError as exc:
        valid = ", ".join(member.value for member in AcceptanceDecision)
        raise ProofMapError(
            "INVALID_DECISION", f"'{decision}' is not a valid acceptance decision; expected one of: {valid}"
        ) from exc

    if not confirmed:
        raise ProofMapError(
            "CONFIRMATION_REQUIRED",
            "a Human Review decision requires explicit confirmation; only a researcher may confirm one",
        )

    governance_state = _ACCEPTANCE_DECISION_TO_GOVERNANCE_STATE[resolved_decision]
    request = record_review_request(
        store,
        _ACCEPTANCE_OBJECT_TYPE,
        node_id,
        reviewer_id=reviewer_id,
        rationale=rationale,
        kind=ReviewRecordKind.acceptance,
    )
    record = record_review_decision(store, request.id, governance_state, reviewer_id=reviewer_id, rationale=rationale)

    append_event(
        store,
        "proof_map_acceptance_decided",
        f"acceptance decision for {node_id}: {resolved_decision.value}",
        entity_id=node_id,
        payload={"decision": resolved_decision.value, "reviewer_id": reviewer_id, "review_id": record.id},
    )
    return record


def get_acceptance_state(store: ProjectStore, node_id: str) -> str:
    """The node's acceptance_state, computed from its Human Review history.

    One of `unreviewed`, `accepted`, `rejected` — never stored, always
    re-derived from the latest `kind=acceptance` ReviewRecord for this node,
    so it can never drift out of sync with what a human actually decided.
    """
    require_node(store, node_id)
    records = [
        record
        for record in list_review_records(store, object_type=_ACCEPTANCE_OBJECT_TYPE, object_id=node_id)
        if record.kind == ReviewRecordKind.acceptance
    ]
    if not records:
        return "unreviewed"
    latest = records[-1]
    if latest.decision == ReviewGovernanceState.approved:
        return "accepted"
    if latest.decision == ReviewGovernanceState.rejected:
        return "rejected"
    return "unreviewed"
