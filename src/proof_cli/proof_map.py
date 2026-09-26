from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from enum import Enum
from typing import Any

from .collaboration import (
    ReviewGovernanceState,
    ReviewRecord,
    ReviewRecordKind,
    list_review_records,
    record_decided_review,
)
from .domain import (
    CandidateProofRecord,
    Challenge,
    ChallengeStatus,
    ClaimRecord,
    DependencyPin,
    EvidenceCheck,
    EvidenceOutcome,
    ProofMapNode,
    ProofMapNodeKind,
    TrustLevel,
    utc_now,
)
from .storage import (
    ProjectStore,
    append_event,
    get_active_claim,
    get_candidate_proof as _get_candidate_proof,
    get_challenge as _get_challenge,
    get_current_candidate_proof,
    get_dependency_pin as _get_dependency_pin,
    get_evidence_check as _get_evidence_check,
    get_proof_map_node,
    insert_challenge,
    insert_claim,
    insert_candidate_proof,
    insert_evidence_check,
    insert_proof_map_node,
    list_candidate_proofs_for_node,
    list_challenges as _list_challenges,
    list_dependency_pins_for_node,
    list_evidence_checks_for_candidate_proof,
    list_open_challenge_ids,
    list_proof_map_nodes,
    mark_challenge_dismissed,
    mark_claim_released,
    next_candidate_proof_version,
    set_candidate_proof_interface_fingerprint,
    set_candidate_proof_review_record_id,
    update_proof_map_node,
    upsert_dependency_pin,
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
    source_locator: str | None = None,
    source_version: str | None = None,
    trust_level: TrustLevel | str | None = None,
    derived_from: str | None = None,
) -> ProofMapNode:
    if get_proof_map_node(store, node_id) is not None:
        raise ProofMapError("NODE_ALREADY_EXISTS", f"proof map node {node_id} already exists")

    if derived_from is not None and get_proof_map_node(store, derived_from) is None:
        raise ProofMapError("DERIVED_FROM_NOT_FOUND", f"derived_from node {derived_from} does not exist")

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

    resolved_trust_level: TrustLevel | None = None
    if trust_level is not None:
        try:
            resolved_trust_level = TrustLevel(trust_level)
        except ValueError as exc:
            valid_levels = ", ".join(member.value for member in TrustLevel)
            raise ProofMapError(
                "INVALID_TRUST_LEVEL",
                f"'{trust_level}' is not a valid trust level; expected one of: {valid_levels}",
            ) from exc

    if resolved_kind == ProofMapNodeKind.imported_result:
        if not (source_locator or "").strip() or not (source_version or "").strip():
            raise ProofMapError(
                "IMPORTED_RESULT_REQUIRES_SOURCE",
                "an imported_result node requires both a source_locator and a source_version",
            )

    node = ProofMapNode(
        id=node_id,
        kind=resolved_kind,
        display_label=display_label,
        statement=statement,
        assumptions=assumptions or [],
        dependencies=dependencies or [],
        source_locator=source_locator,
        source_version=source_version,
        trust_level=resolved_trust_level,
        derived_from=derived_from,
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


def split_node(
    store: ProjectStore,
    parent_id: str,
    child_specs: list[dict[str, Any]],
    *,
    created_by: str = "human",
) -> list[ProofMapNode]:
    """Decompose `parent_id` into one or more new `claim`-kind children.

    Ungated — no researcher approval needed, so "split first, don't force a
    proof" is genuinely the path of least resistance. Each child gets
    `derived_from=parent_id` and is appended to the parent's dependencies;
    the parent's own pre-existing dependencies are untouched. This alone
    doesn't get the parent any closer to Accepted — once every child is
    Accepted the parent simply stops being `blocked`, and still needs its
    own Candidate proof and Acceptance like any other node ("how the pieces
    combine" is never assumed true without a human looking at it).

    Each spec in `child_specs` is `{"id": str, "statement": str,
    "assumptions": list[str] (optional), "display_label": str (optional)}`.
    """
    parent = require_node(store, parent_id)

    if parent.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError("IMMUTABLE_NODE", f"imported_result node {parent_id} cannot be split")

    if get_acceptance_state(store, parent_id) == "rejected":
        raise ProofMapError(
            "NODE_REJECTED", f"node {parent_id} was Rejected and should not be pursued further; split is unavailable"
        )

    if not child_specs:
        raise ProofMapError("SPLIT_REQUIRES_CHILDREN", "split requires at least one child claim")

    children: list[ProofMapNode] = []
    for spec in child_specs:
        child = create_node(
            store,
            node_id=spec["id"],
            kind=ProofMapNodeKind.claim,
            statement=spec["statement"],
            display_label=spec.get("display_label", ""),
            assumptions=spec.get("assumptions"),
            created_by=created_by,
            derived_from=parent_id,
        )
        children.append(child)

    updated_parent = parent.model_copy(update={"dependencies": [*parent.dependencies, *(c.id for c in children)]})
    update_proof_map_node(store, updated_parent)

    append_event(
        store,
        "proof_map_node_split",
        f"split {parent_id} into {len(children)} claim(s)",
        entity_id=parent_id,
        payload={"child_ids": [c.id for c in children], "created_by": created_by},
    )
    return children


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

    Refuses a node that's Rejected (CONTEXT.md: "should not be pursued
    further") — terminal for the Acceptance axis, reopening the claim/submit
    cycle on it would let a fresh submission silently contradict a decision
    Human Review already made. Also refuses an already-Accepted node,
    *unless* it's the target of an open Challenge: that's the one sanctioned
    way to revise and re-Accept an Accepted node (ADR-0005 Rule 4) — without
    an open Challenge there is no supported path to reclaim and revise one.
    """
    node = require_node(store, node_id)
    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE",
            f"imported_result node {node_id} has no claim/submit workflow; use Reference review instead",
        )

    acceptance_state = get_acceptance_state(store, node_id)
    if acceptance_state == "rejected":
        raise ProofMapError(
            "NODE_REJECTED",
            f"node {node_id} was Rejected and should not be pursued further; create a new node instead",
        )
    if acceptance_state == "accepted" and not has_open_challenge(store, node_id):
        raise ProofMapError(
            "NODE_ALREADY_ACCEPTED",
            f"node {node_id} is already Accepted; open a Challenge before reclaiming it to revise",
        )

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

    try:
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
    except FileExistsError as exc:
        raise ProofMapError(
            "CANDIDATE_PROOF_VERSION_CONFLICT",
            f"version {version} of node {node_id} is already indexed",
        ) from exc

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

    pin_dependencies(store, node)

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


def record_evidence_check(
    store: ProjectStore,
    candidate_proof_id: str,
    outcome: EvidenceOutcome | str,
    *,
    notes: str = "",
    run_by: str = "system",
) -> EvidenceCheck:
    """Record an automated or semi-automated check against a specific Candidate proof.

    Purely advisory and ungated — an automated checker records its own
    outcome directly, no Human Review needed to log a result. Nothing here
    can close, block, or otherwise touch acceptance_state; the sole write
    is this check's own row (ADR-0004 point 5).
    """
    require_candidate_proof(store, candidate_proof_id)

    try:
        resolved_outcome = EvidenceOutcome(outcome)
    except ValueError as exc:
        valid = ", ".join(member.value for member in EvidenceOutcome)
        raise ProofMapError(
            "INVALID_OUTCOME", f"'{outcome}' is not a valid evidence outcome; expected one of: {valid}"
        ) from exc

    check = EvidenceCheck(
        id=str(uuid.uuid4()), candidate_proof_id=candidate_proof_id, outcome=resolved_outcome, notes=notes, run_by=run_by
    )
    insert_evidence_check(store, check)
    append_event(
        store,
        "proof_map_evidence_check_recorded",
        f"evidence check {resolved_outcome.value} for candidate proof {candidate_proof_id}",
        entity_id=candidate_proof_id,
        payload={"evidence_check_id": check.id, "outcome": resolved_outcome.value, "run_by": run_by},
    )
    return check


def get_evidence_check(store: ProjectStore, check_id: str) -> EvidenceCheck | None:
    return _get_evidence_check(store, check_id)


def require_evidence_check(store: ProjectStore, check_id: str) -> EvidenceCheck:
    check = get_evidence_check(store, check_id)
    if check is None:
        raise ProofMapError("EVIDENCE_CHECK_NOT_FOUND", f"evidence check {check_id} not found")
    return check


def list_evidence_checks(store: ProjectStore, candidate_proof_id: str) -> list[EvidenceCheck]:
    require_candidate_proof(store, candidate_proof_id)
    return list_evidence_checks_for_candidate_proof(store, candidate_proof_id)


class EvidenceTrustDecision(str, Enum):
    trusted = "trusted"
    unusable = "unusable"


_EVIDENCE_DECISION_TO_GOVERNANCE_STATE = {
    EvidenceTrustDecision.trusted: ReviewGovernanceState.trusted,
    EvidenceTrustDecision.unusable: ReviewGovernanceState.unusable,
}

_EVIDENCE_CHECK_OBJECT_TYPE = "evidence_check"


def decide_evidence_review(
    store: ProjectStore,
    evidence_check_id: str,
    decision: EvidenceTrustDecision | str,
    *,
    reviewer_id: str = "human",
    rationale: str = "",
    confirmed: bool = False,
) -> ReviewRecord:
    """Human Review's trust judgment on an Evidence check itself.

    `trusted` or `unusable` — never `approved`/`rejected`, and never
    against `object_type=proof_map_node`, so this can't be confused with,
    or feed, acceptance_state no matter what it decides (ADR-0004 point 5).
    """
    check = require_evidence_check(store, evidence_check_id)

    try:
        resolved_decision = EvidenceTrustDecision(decision)
    except ValueError as exc:
        valid = ", ".join(member.value for member in EvidenceTrustDecision)
        raise ProofMapError(
            "INVALID_DECISION", f"'{decision}' is not a valid evidence trust judgment; expected one of: {valid}"
        ) from exc

    if not confirmed:
        raise ProofMapError(
            "CONFIRMATION_REQUIRED",
            "a Human Review decision requires explicit confirmation; only a researcher may confirm one",
        )

    governance_state = _EVIDENCE_DECISION_TO_GOVERNANCE_STATE[resolved_decision]
    with store.transaction() as conn:
        record = record_decided_review(
            store,
            _EVIDENCE_CHECK_OBJECT_TYPE,
            evidence_check_id,
            governance_state,
            reviewer_id=reviewer_id,
            rationale=rationale,
            kind=ReviewRecordKind.evidence_review,
            conn=conn,
        )
        append_event(
            store,
            "proof_map_evidence_review_decided",
            f"evidence review for {evidence_check_id}: {resolved_decision.value}",
            entity_id=check.candidate_proof_id,
            payload={"decision": resolved_decision.value, "reviewer_id": reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def compute_interface_fingerprint(kind: str, statement: str, assumptions: list[str]) -> str:
    """SHA-256 hex digest over the canonical JSON tuple `(kind, statement, assumptions)`.

    Statement and each assumption are whitespace-normalized (trimmed,
    internal runs collapsed) first, so two statements differing only by
    whitespace produce the same fingerprint. "Mathematical scope" is treated
    as already captured within statement + assumptions for v1.
    """
    canonical = json.dumps(
        [kind, _normalize_whitespace(statement), [_normalize_whitespace(a) for a in assumptions]],
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_accepted_interface_fingerprint(store: ProjectStore, node_id: str) -> str | None:
    """The interface fingerprint of `node_id`'s current Accepted candidate proof, or `None`.

    `None` when the node isn't `accepted`, or (should it ever happen) it is
    but has no current candidate proof to have fingerprinted.
    """
    if get_acceptance_state(store, node_id) != "accepted":
        return None
    current = get_current_candidate_proof(store, node_id)
    return current.interface_fingerprint if current else None


def pin_dependencies(store: ProjectStore, node: ProofMapNode) -> list[DependencyPin]:
    """Snapshot what each of `node`'s dependencies currently offers.

    Called on every Candidate proof submission, refreshing the pin to
    reflect what this particular submission was actually checked against.
    An `imported_result` target pins no version/fingerprint — it's
    immutable, so there's nothing to have moved on. A local target not yet
    Accepted pins `None` for both: nothing confirmed exists yet to check
    against.
    """
    pins: list[DependencyPin] = []
    for target_id in node.dependencies:
        target = get_proof_map_node(store, target_id)
        if target is None:
            continue
        if target.kind == ProofMapNodeKind.imported_result:
            pinned_version, pinned_fingerprint = None, None
        else:
            pinned_fingerprint = get_accepted_interface_fingerprint(store, target_id)
            if pinned_fingerprint is None:
                pinned_version = None
            else:
                current = get_current_candidate_proof(store, target_id)
                pinned_version = current.version if current else None
        pin = DependencyPin(
            id=str(uuid.uuid4()),
            node_id=node.id,
            target_node_id=target_id,
            pinned_version=pinned_version,
            pinned_fingerprint=pinned_fingerprint,
        )
        pins.append(upsert_dependency_pin(store, pin))
    return pins


def get_dependency_pin(store: ProjectStore, node_id: str, target_node_id: str) -> DependencyPin | None:
    return _get_dependency_pin(store, node_id, target_node_id)


def list_dependency_pins(store: ProjectStore, node_id: str) -> list[DependencyPin]:
    require_node(store, node_id)
    return list_dependency_pins_for_node(store, node_id)


def dependency_pin_is_current(store: ProjectStore, pin: DependencyPin) -> bool:
    """Whether a pinned dependency's interface still matches what the target now offers.

    Compared by fingerprint, never by version number: a target can move to
    a new Accepted version whose interface fingerprint is unchanged (a
    proof-only revision), and that must read as still current, not stale.
    """
    target = get_proof_map_node(store, pin.target_node_id)
    if target is None or target.kind == ProofMapNodeKind.imported_result:
        return True
    current_fingerprint = get_accepted_interface_fingerprint(store, pin.target_node_id)
    return pin.pinned_fingerprint is not None and pin.pinned_fingerprint == current_fingerprint


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


def _require_awaiting_acceptance_review(store: ProjectStore, node_id: str) -> None:
    """A decision only ever answers a Candidate proof awaiting review.

    `rejected` is terminal (story 24). Otherwise the node must read
    `review-needed`: that one state already excludes a node with no
    Candidate proof (`open`), one under an active claim (`claimed`), one
    whose dependencies aren't settled (`blocked`), and a second decision on
    a submission that was already decided (`open`/`revision-requested`).
    """
    if get_acceptance_state(store, node_id) == "rejected":
        raise ProofMapError(
            "NODE_REJECTED", f"node {node_id} was Rejected; that decision is permanent and can't be revisited"
        )
    workflow_state = get_workflow_state(store, node_id)
    if workflow_state != "review-needed":
        raise ProofMapError(
            "NOT_REVIEW_NEEDED",
            f"node {node_id} is {workflow_state}, not review-needed; "
            "a Human Review decision only applies to a submitted Candidate proof awaiting review",
            details={"workflow_state": workflow_state},
        )


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

    Only for a node in `review-needed`, and never once it's `rejected` (see
    `_require_awaiting_acceptance_review`).

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
    # the review rows, the candidate-proof link and fingerprint, the
    # Challenges it resolves and the events all commit together or not at
    # all: a decision interrupted part-way leaves the node exactly as it was.
    with store.transaction() as conn:
        # checked on the write lock, so no concurrent decision or submission
        # can land between the check and the write
        _require_awaiting_acceptance_review(store, node_id)
        current_proof = get_current_candidate_proof(store, node_id)
        record = record_decided_review(
            store,
            _ACCEPTANCE_OBJECT_TYPE,
            node_id,
            governance_state,
            reviewer_id=reviewer_id,
            rationale=rationale,
            kind=ReviewRecordKind.acceptance,
            conn=conn,
        )
        if current_proof is not None:
            set_candidate_proof_review_record_id(store, current_proof.id, record.id, conn=conn)
            if resolved_decision == AcceptanceDecision.accept:
                fingerprint = compute_interface_fingerprint(node.kind.value, node.statement, node.assumptions)
                set_candidate_proof_interface_fingerprint(store, current_proof.id, fingerprint, conn=conn)

        _resolve_open_challenges(store, node_id, resolved_by=reviewer_id, conn=conn)

        append_event(
            store,
            "proof_map_acceptance_decided",
            f"acceptance decision for {node_id}: {resolved_decision.value}",
            entity_id=node_id,
            payload={"decision": resolved_decision.value, "reviewer_id": reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _decided_reviews(store: ProjectStore, node_id: str, kind: ReviewRecordKind) -> list[ReviewRecord]:
    """`node_id`'s reviews of `kind` that carry a decision, oldest first.

    A request still at `proposed_for_review` is no decision at all, so it is
    never the "latest" one a derived axis reads — a pending request can't
    revoke an earlier Acceptance.
    """
    return [
        record
        for record in list_review_records(store, object_type=_ACCEPTANCE_OBJECT_TYPE, object_id=node_id)
        if record.kind == kind and record.decision != ReviewGovernanceState.proposed_for_review
    ]


def get_acceptance_state(store: ProjectStore, node_id: str) -> str:
    """The node's acceptance_state, computed from its Human Review history.

    One of `unreviewed`, `accepted`, `rejected` — never stored, always
    re-derived from the latest `kind=acceptance` ReviewRecord for this node,
    so it can never drift out of sync with what a human actually decided.
    """
    require_node(store, node_id)
    records = _decided_reviews(store, node_id, ReviewRecordKind.acceptance)
    if not records:
        return "unreviewed"
    latest = records[-1]
    if latest.decision == ReviewGovernanceState.approved:
        return "accepted"
    if latest.decision == ReviewGovernanceState.rejected:
        return "rejected"
    return "unreviewed"


def promote_to_lemma(store: ProjectStore, node_id: str, *, promoted_by: str = "human", confirmed: bool = False) -> ProofMapNode:
    """Promote an Accepted Claim to a Lemma, marking it independently reusable.

    The researcher's explicit decision, never automatic. Only available for
    `kind=claim` nodes that are already Accepted; there is no demote. Every
    field but `kind` is unchanged — including the Candidate-proof history —
    but since the interface fingerprint is a function of `(kind, statement,
    assumptions)`, it's recomputed for the new kind on the currently
    Accepted Candidate proof, so a dependent pinning this node afterward
    isn't told its interface "changed" over a relabeling that changed
    nothing it actually asserts.
    """
    node = require_node(store, node_id)

    if node.kind != ProofMapNodeKind.claim:
        raise ProofMapError("NOT_A_CLAIM", f"node {node_id} is kind={node.kind.value}, not claim; only a claim can be promoted")

    if get_acceptance_state(store, node_id) != "accepted":
        raise ProofMapError("NOT_ACCEPTED", f"node {node_id} must be Accepted before it can be promoted to Lemma")

    if not confirmed:
        raise ProofMapError(
            "CONFIRMATION_REQUIRED",
            "promoting a node requires explicit confirmation; only a researcher may confirm one",
        )

    promoted = node.model_copy(update={"kind": ProofMapNodeKind.lemma, "updated_by": promoted_by, "updated_at": utc_now()})
    update_proof_map_node(store, promoted)

    current_proof = get_current_candidate_proof(store, node_id)
    if current_proof is not None and current_proof.interface_fingerprint is not None:
        fingerprint = compute_interface_fingerprint(promoted.kind.value, promoted.statement, promoted.assumptions)
        set_candidate_proof_interface_fingerprint(store, current_proof.id, fingerprint)

    append_event(
        store,
        "proof_map_node_promoted",
        f"promoted {node_id} from claim to lemma",
        entity_id=node_id,
        payload={"promoted_by": promoted_by},
    )
    return promoted


REFERENCE_REVIEW_DECISION = "reference-review"


def decide_reference_review(
    store: ProjectStore,
    node_id: str,
    decision: str,
    *,
    reviewer_id: str = "human",
    rationale: str = "",
    confirmed: bool = False,
) -> ReviewRecord:
    """Grant Reference review to an imported_result node.

    Judges the trustworthiness of a citation — never the node's
    acceptance_state, which stays `unreviewed` for every imported_result
    node forever; it is Reference-reviewed or it isn't, independently of
    Acceptance (see ADR on imported results / story 22).
    """
    node = require_node(store, node_id)

    if node.kind != ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "NOT_IMPORTED_RESULT",
            f"node {node_id} is not an imported_result; use Human Review acceptance instead",
        )

    if decision != REFERENCE_REVIEW_DECISION:
        raise ProofMapError(
            "INVALID_DECISION",
            f"'{decision}' is not a valid reference review decision; expected: {REFERENCE_REVIEW_DECISION}",
        )

    if not confirmed:
        raise ProofMapError(
            "CONFIRMATION_REQUIRED",
            "a Reference review decision requires explicit confirmation; only a researcher may confirm one",
        )

    with store.transaction() as conn:
        record = record_decided_review(
            store,
            _ACCEPTANCE_OBJECT_TYPE,
            node_id,
            ReviewGovernanceState.approved,
            reviewer_id=reviewer_id,
            rationale=rationale,
            kind=ReviewRecordKind.reference_review,
            conn=conn,
        )
        _resolve_open_challenges(store, node_id, resolved_by=reviewer_id, conn=conn)
        append_event(
            store,
            "proof_map_reference_review_granted",
            f"reference review granted for {node_id}",
            entity_id=node_id,
            payload={"reviewer_id": reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def get_reference_review_state(store: ProjectStore, node_id: str) -> str:
    """`unreviewed` or `reviewed`, derived from `kind=reference_review` records only — never acceptance_state."""
    require_node(store, node_id)
    records = _decided_reviews(store, node_id, ReviewRecordKind.reference_review)
    if records and records[-1].decision == ReviewGovernanceState.approved:
        return "reviewed"
    return "unreviewed"


def revalidate_dependency(
    store: ProjectStore,
    node_id: str,
    target_node_id: str,
    *,
    reviewer_id: str = "human",
    rationale: str = "",
    confirmed: bool = False,
) -> ReviewRecord:
    """Lightweight re-review: confirm an existing Candidate proof still holds after a dependency advanced.

    Only available when the target's interface fingerprint hasn't changed
    since it was last pinned — if it has, the old Candidate proof no longer
    demonstrably accounts for the new premise, and a whole new Candidate
    proof is required instead (`INTERFACE_CHANGED`). Records
    `kind=dependency_revalidation, decision=reaffirmed` — deliberately
    distinct from `approved` so it can never be misread as a fresh
    Acceptance of `node_id` itself — and refreshes the dependency edge's
    pin to the target's current accepted version and fingerprint.

    The pin refresh and the review rows are written in one SQLite
    transaction: neither lands without the other.
    """
    node = require_node(store, node_id)
    target = require_node(store, target_node_id)

    if target_node_id not in node.dependencies:
        raise ProofMapError(
            "NOT_A_DEPENDENCY", f"{target_node_id} is not a dependency of {node_id}"
        )

    if target.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE",
            f"{target_node_id} is an imported_result; it has no accepted-version history to revalidate against",
        )

    pin = get_dependency_pin(store, node_id, target_node_id)
    if pin is None:
        raise ProofMapError(
            "NO_DEPENDENCY_PIN",
            f"{node_id} has never pinned {target_node_id}; submit a Candidate proof first",
        )

    current_fingerprint = get_accepted_interface_fingerprint(store, target_node_id)
    if current_fingerprint is None:
        raise ProofMapError(
            "TARGET_NOT_ACCEPTED", f"{target_node_id} is not currently Accepted; nothing to revalidate against"
        )

    if pin.pinned_fingerprint != current_fingerprint:
        raise ProofMapError(
            "INTERFACE_CHANGED",
            f"{target_node_id}'s accepted interface changed since {node_id} last pinned it; "
            "a new Candidate proof is required, lightweight re-review is not available",
        )

    if not confirmed:
        raise ProofMapError(
            "CONFIRMATION_REQUIRED",
            "a Human Review decision requires explicit confirmation; only a researcher may confirm one",
        )

    current_target_proof = get_current_candidate_proof(store, target_node_id)
    new_version = current_target_proof.version if current_target_proof else None
    old_pin = pin

    refreshed_pin = DependencyPin(
        id=pin.id,
        node_id=node_id,
        target_node_id=target_node_id,
        pinned_version=new_version,
        pinned_fingerprint=current_fingerprint,
    )
    with store.transaction() as conn:
        upsert_dependency_pin(store, refreshed_pin, conn=conn)
        record = record_decided_review(
            store,
            _ACCEPTANCE_OBJECT_TYPE,
            node_id,
            ReviewGovernanceState.reaffirmed,
            reviewer_id=reviewer_id,
            rationale=rationale,
            kind=ReviewRecordKind.dependency_revalidation,
            conn=conn,
        )
        append_event(
            store,
            "proof_map_dependency_revalidated",
            f"revalidated {node_id}'s dependency on {target_node_id}",
            entity_id=node_id,
            payload={
                "target_node_id": target_node_id,
                "old_pinned_version": old_pin.pinned_version,
                "new_pinned_version": new_version,
                "review_id": record.id,
            },
            conn=conn,
        )
    return record


def open_challenge(store: ProjectStore, target_node_id: str, *, opened_by: str = "human", rationale: str = "") -> Challenge:
    """Raise a Challenge against an already-Accepted (or Reference-reviewed) node.

    Ungated: any agent or collaborator may open one, no confirmation, no
    permission check — raising a concern is not a mathematical judgment
    ("this deserves a second look," not "this is wrong"), so it needs no
    gate the way resolving one does (ADR-0005 Rule 4).
    """
    node = require_node(store, target_node_id)

    if node.kind == ProofMapNodeKind.imported_result:
        if get_reference_review_state(store, target_node_id) != "reviewed":
            raise ProofMapError(
                "TARGET_NOT_REVIEWED",
                f"{target_node_id} has not been Reference-reviewed yet; nothing to Challenge",
            )
    elif get_acceptance_state(store, target_node_id) != "accepted":
        raise ProofMapError(
            "TARGET_NOT_ACCEPTED",
            f"{target_node_id} is not Accepted; a Challenge only makes sense against a result someone might depend on",
        )

    challenge = Challenge(
        id=str(uuid.uuid4()),
        target_node_id=target_node_id,
        rationale=rationale,
        opened_by=opened_by,
    )
    insert_challenge(store, challenge)
    append_event(
        store,
        "proof_map_challenge_opened",
        f"challenge opened against {target_node_id} by {opened_by}",
        entity_id=target_node_id,
        payload={"challenge_id": challenge.id, "opened_by": opened_by, "rationale": rationale},
    )
    return challenge


def get_challenge(store: ProjectStore, challenge_id: str) -> Challenge | None:
    return _get_challenge(store, challenge_id)


def require_challenge(store: ProjectStore, challenge_id: str) -> Challenge:
    challenge = get_challenge(store, challenge_id)
    if challenge is None:
        raise ProofMapError("CHALLENGE_NOT_FOUND", f"challenge {challenge_id} not found")
    return challenge


def list_challenges(store: ProjectStore, *, target_node_id: str = "", status: str = "") -> list[Challenge]:
    return _list_challenges(store, target_node_id=target_node_id, status=status)


def has_open_challenge(store: ProjectStore, node_id: str) -> bool:
    return len(_list_challenges(store, target_node_id=node_id, status="open")) > 0


def _resolve_open_challenges(store: ProjectStore, node_id: str, *, resolved_by: str, conn: sqlite3.Connection) -> None:
    """Dismiss every open Challenge against `node_id`.

    Called from `decide_acceptance` and `decide_reference_review`: per
    ADR-0005 Rule 4, only Human Review resolves a Challenge, either by an
    explicit `challenge dismiss` or by directly addressing the concern —
    revising and re-Accepting a local node, or reaffirming trust in an
    Imported result's Reference review. Without this, a Challenge-driven
    reclaim (`claim_node`'s one sanctioned way to revise an Accepted node)
    would leave the node permanently `challenged` even after the concern was
    addressed.

    Runs on the deciding review's own transaction (`conn`), so the Challenges
    it resolves are dismissed exactly when that decision commits.
    """
    resolved_at = utc_now()
    for challenge_id in list_open_challenge_ids(conn, node_id):
        if mark_challenge_dismissed(store, challenge_id, resolved_by=resolved_by, resolved_at=resolved_at, conn=conn):
            append_event(
                store,
                "proof_map_challenge_dismissed",
                f"challenge {challenge_id} dismissed by {resolved_by} (resolved via review decision)",
                entity_id=node_id,
                payload={"challenge_id": challenge_id, "reviewer_id": resolved_by},
                conn=conn,
            )


def dismiss_challenge(
    store: ProjectStore,
    challenge_id: str,
    *,
    reviewer_id: str = "human",
    rationale: str = "",
    confirmed: bool = False,
) -> Challenge:
    """Dismiss a Challenge — Human Review only.

    Nothing un-sets `potentially-stale`/`challenged` by hand: both are
    computed fresh from the set of *open* Challenges (and stale pins) on
    every read, so dismissing one simply removes it from that set — every
    overlay it alone was causing clears itself the next time anyone asks.
    """
    challenge = require_challenge(store, challenge_id)
    if challenge.status != ChallengeStatus.open:
        raise ProofMapError("CHALLENGE_NOT_OPEN", f"challenge {challenge_id} is already {challenge.status.value}")

    if not confirmed:
        raise ProofMapError(
            "CONFIRMATION_REQUIRED",
            "a Human Review decision requires explicit confirmation; only a researcher may confirm one",
        )

    resolved_at = utc_now()
    with store.transaction() as conn:
        won_race = mark_challenge_dismissed(store, challenge_id, resolved_by=reviewer_id, resolved_at=resolved_at, conn=conn)
        if not won_race:
            raise ProofMapError("CHALLENGE_NOT_OPEN", f"challenge {challenge_id} is already dismissed")
        append_event(
            store,
            "proof_map_challenge_dismissed",
            f"challenge {challenge_id} dismissed by {reviewer_id}",
            entity_id=challenge.target_node_id,
            payload={"challenge_id": challenge_id, "reviewer_id": reviewer_id, "rationale": rationale},
            conn=conn,
        )
    return challenge.model_copy(update={"status": ChallengeStatus.dismissed, "resolved_by": reviewer_id, "resolved_at": resolved_at})


def _is_downstream_of_challenge_or_stale_pin(store: ProjectStore, node_id: str) -> bool:
    """Whether `node_id` is itself Challenged, or reachable (via dependency edges,
    transitively) from a Challenged node or a dependency edge whose pin no
    longer matches its target's current accepted interface.

    Pure graph reachability over persisted Challenge and DependencyPin
    records — nothing is stored per node. See ADR-0004 point 4. Walked with
    an explicit worklist, not recursion: a long-running project's dependency
    chain can run hundreds of nodes deep, well past Python's default
    recursion limit.
    """
    visited: set[str] = set()
    pending = [node_id]
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)

        if has_open_challenge(store, current_id):
            return True

        node = get_proof_map_node(store, current_id)
        if node is None:
            continue

        for dependency_id in node.dependencies:
            pin = _get_dependency_pin(store, current_id, dependency_id)
            if pin is not None and not dependency_pin_is_current(store, pin):
                return True
            pending.append(dependency_id)
    return False


def _dependency_satisfied(store: ProjectStore, dependency_id: str) -> bool:
    """Whether a dependency has reached the standing that unblocks its dependents.

    For a local node that's Acceptance; for an imported_result that's
    Reference review. A dangling dependency id can't happen through
    `create_node` (it validates dependencies exist), so a missing node here
    is treated as satisfied rather than as a block this axis can't explain.

    Also false whenever the dependency is itself Challenged, or reachable
    from a Challenge/stale pin further upstream — an Accepted-but-Challenged
    dependency is not something a *new* dependent should treat as settled
    (ADR-0004 point 4: a not-yet-accepted node downstream of a Challenge
    reads `blocked`, same underlying cause, distinct reason).
    """
    dependency = get_proof_map_node(store, dependency_id)
    if dependency is None:
        return True
    if dependency.kind == ProofMapNodeKind.imported_result:
        reached_standing = get_reference_review_state(store, dependency_id) == "reviewed"
    else:
        reached_standing = get_acceptance_state(store, dependency_id) == "accepted"
    if not reached_standing:
        return False
    return not _is_downstream_of_challenge_or_stale_pin(store, dependency_id)


def _has_unresolved_dependency(store: ProjectStore, node: ProofMapNode) -> bool:
    return any(not _dependency_satisfied(store, dependency_id) for dependency_id in node.dependencies)


def _already_accepted(store: ProjectStore, node: ProofMapNode) -> bool:
    return node.kind != ProofMapNodeKind.imported_result and get_acceptance_state(store, node.id) == "accepted"


def get_workflow_state(store: ProjectStore, node_id: str) -> str:
    """One of `open`, `claimed`, `review-needed`, `revision-requested`, `blocked`.

    Always recomputed from the claim, candidate-proof, review, and
    dependency records — never read off a stored field, so it can never
    drift out of sync with what actually happened. `blocked` overrides every
    other workflow value but is a separate axis from acceptance/integrity,
    not a priority ladder across all three — and, per ADR-0004's note on
    ADR-0002, never overrides an already-Accepted node either: a Challenge
    or a stale dependency opened against an Accepted node's own dependency
    shows up on the integrity axis (`potentially-stale`), not by reverting
    this node's own already-settled workflow state to `blocked`.
    """
    node = require_node(store, node_id)

    if not _already_accepted(store, node) and _has_unresolved_dependency(store, node):
        return "blocked"

    if get_active_claim(store, node_id) is not None:
        return "claimed"

    if node.kind == ProofMapNodeKind.imported_result:
        # no claim/submit/Candidate-proof cycle exists for this kind; Reference
        # review governs it independently and doesn't move this axis.
        return "open"

    current_proof = get_current_candidate_proof(store, node_id)
    acceptance_records = _decided_reviews(store, node_id, ReviewRecordKind.acceptance)
    latest_review = acceptance_records[-1] if acceptance_records else None

    # Whether the latest Human Review decision already covers the current
    # submission (nothing has been submitted since it was made). Keyed off
    # the structural review_record_id link `decide_acceptance` stamps onto
    # whatever candidate proof was current at decision time, never off
    # timestamps — two writes can otherwise land within the same
    # timestamp-resolution tick.
    review_is_current = latest_review is not None and (
        current_proof is None or current_proof.review_record_id == latest_review.id
    )

    if review_is_current and latest_review.decision == ReviewGovernanceState.revision_requested:
        return "revision-requested"

    if current_proof is not None and not review_is_current:
        return "review-needed"

    return "open"


def get_blocked_reason(store: ProjectStore, node_id: str) -> str | None:
    """Why `get_workflow_state` reads `blocked`, or `None` if it doesn't.

    `dependency-challenged` when an unresolved dependency is itself
    Challenged or downstream of a Challenge/stale pin — distinct from the
    ordinary `not-accepted` case of a dependency simply not having reached
    Acceptance/Reference-review yet.
    """
    node = require_node(store, node_id)
    if _already_accepted(store, node) or not _has_unresolved_dependency(store, node):
        return None
    for dependency_id in node.dependencies:
        if not _dependency_satisfied(store, dependency_id) and _is_downstream_of_challenge_or_stale_pin(
            store, dependency_id
        ):
            return "dependency-challenged"
    return "not-accepted"


def get_integrity_state(store: ProjectStore, node_id: str) -> str:
    """One of `current`, `potentially-stale`, `challenged`.

    `challenged` if the node is itself the target of an open Challenge.
    `potentially-stale` if the node is Accepted and reachable (via
    dependency edges) from an open Challenge's target or a stale dependency
    pin — computed by graph reachability, nothing set directly (ADR-0004
    point 4). `current` otherwise.
    """
    require_node(store, node_id)
    if has_open_challenge(store, node_id):
        return "challenged"
    if get_acceptance_state(store, node_id) == "accepted" and _is_downstream_of_challenge_or_stale_pin(
        store, node_id
    ):
        return "potentially-stale"
    return "current"


def get_frontier(store: ProjectStore) -> list[ProofMapNode]:
    """Nodes with no unresolved dependency and no active claim.

    What an agent could pick up right now without inspecting the whole graph
    by hand.
    """
    return [
        node
        for node in list_nodes(store)
        if get_active_claim(store, node.id) is None and not _has_unresolved_dependency(store, node)
    ]
