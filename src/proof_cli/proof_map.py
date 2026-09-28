from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .authority import (
    AuthorityWarning,
    RowVerdict,
    build_decision_payload,
    candidate_proof_sha256,
    challenge_resolution,
    decision_rows,
    list_authority_warnings,
    record_decision,
    verify_decision_row,
)
from .collaboration import (
    ReviewGovernanceState,
    ReviewRecord,
    ReviewRecordKind,
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
from .reviews import DecisionKind, DecisionPayload, PinnedDependency, git_identity
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
    list_proof_map_nodes,
    mark_challenge_dismissed,
    mark_claim_released,
    next_candidate_proof_version,
    on_rollback,
    set_candidate_proof_interface_fingerprint,
    set_candidate_proof_review_record_id,
    update_proof_map_node,
    upsert_dependency_pin,
)
from .vault import build_is_current, build_pdf_path, node_folder, snapshot_path, snapshots_on_disk, working_proof_path, write_snapshot, write_working_proof


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


@dataclass
class _Decision:
    """A Human Review decision about to be recorded: what it's made on, and who makes it (ADR-0010)."""

    payload: DecisionPayload
    reviewer_id: str


def _decide(
    store: ProjectStore,
    *,
    kind: DecisionKind,
    target_id: str,
    decision: str,
    reviewer: str | None,
    rationale: str,
    dependency_id: str | None = None,
) -> _Decision:
    """Bind the decision to what it's made on as of now; called on the operation's write transaction."""
    payload = build_decision_payload(
        store, kind, target_id, decision, rationale=rationale, **decision_binding(store, kind, target_id, dependency_id=dependency_id)
    )
    return _Decision(payload=payload, reviewer_id=reviewer or git_identity(store.root))


def _node_folder(store: ProjectStore, object_type: str, object_id: str) -> str:
    """The node whose reviews.jsonl records a decision on this object."""
    if object_type == "evidence_check":
        return require_candidate_proof(store, require_evidence_check(store, object_id).candidate_proof_id).node_id
    if object_type == "challenge":
        return require_challenge(store, object_id).target_node_id
    return object_id


def _record(
    store: ProjectStore, decided: _Decision, object_type: str, object_id: str, state: ReviewGovernanceState
) -> ReviewRecord:
    """Record `decided` in its node's reviews.jsonl (committed with its snapshot once the transaction commits)."""
    payload = decided.payload
    entry = record_decision(
        store,
        node_id=_node_folder(store, object_type, object_id),
        object_type=object_type,
        object_id=object_id,
        kind=payload.kind,
        decision=state.value,
        reviewer=decided.reviewer_id,
        rationale=payload.rationale,
        payload=payload,
    )
    return ReviewRecord(
        id=entry.id,
        object_type=object_type,
        object_id=object_id,
        reviewer_id=entry.reviewer,
        decision=state,
        kind=ReviewRecordKind(payload.kind.value),
        rationale=payload.rationale,
        created_at=entry.decided_at,
        updated_at=entry.decided_at,
        decision_row_id=entry.id,
    )


_SAFE_NODE_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")


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
    if not _SAFE_NODE_ID.fullmatch(node_id):
        # the id names the node's folder under proofs/ (ADR-0010), so it must be a plain folder name
        raise ProofMapError(
            "INVALID_NODE_ID", f"node id {node_id!r} must be letters, digits, '.', '_' or '-', not starting with '.'"
        )
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
        with store.transaction() as conn:
            insert_proof_map_node(store, node, conn=conn)
            append_event(
                store,
                "proof_map_node_created",
                f"created {resolved_kind.value} node {node.id}",
                entity_id=node.id,
                payload=node.model_dump(mode="json"),
                conn=conn,
            )
    except sqlite3.IntegrityError as exc:
        if resolved_kind == ProofMapNodeKind.theorem:
            raise ProofMapError(
                "DUPLICATE_THEOREM",
                "a theorem-kind node already exists for this project; only one is allowed",
            ) from exc
        raise ProofMapError("NODE_ALREADY_EXISTS", f"proof map node {node_id} already exists") from exc
    if resolved_kind != ProofMapNodeKind.imported_result:
        write_working_proof(store.root, node_id=node.id, kind=resolved_kind.value, statement=statement)
    return node


def _promoted(store: ProjectStore, node_id: str) -> bool:
    return any(
        verify_decision_row(store, row["id"]).status == "verified"
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewRecordKind.promote.value)
    )


def _effective_kind(store: ProjectStore, node: ProofMapNode) -> ProofMapNodeKind:
    """A node's kind as it counts: its stored kind, plus a recorded Promote."""
    kind = node.kind
    if kind == ProofMapNodeKind.claim and _promoted(store, node.id):
        kind = ProofMapNodeKind.lemma
    return kind


def _as_counted(store: ProjectStore, node: ProofMapNode | None) -> ProofMapNode | None:
    if node is None:
        return None
    kind = _effective_kind(store, node)
    return node if kind == node.kind else node.model_copy(update={"kind": kind})


def get_node(store: ProjectStore, node_id: str) -> ProofMapNode | None:
    return _as_counted(store, get_proof_map_node(store, node_id))


def require_node(store: ProjectStore, node_id: str) -> ProofMapNode:
    node = get_node(store, node_id)
    if node is None:
        raise ProofMapError("NODE_NOT_FOUND", f"proof map node {node_id} not found")
    return node


def list_nodes(store: ProjectStore) -> list[ProofMapNode]:
    return [_as_counted(store, node) for node in list_proof_map_nodes(store)]


def split_node(
    store: ProjectStore,
    parent_id: str,
    child_specs: list[dict[str, Any]],
    *,
    created_by: str = "human",
    reassign: bool = False,
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

    A node someone else has claimed is theirs to split (NOT_CLAIMANT), unless
    `reassign` takes the claim over for `created_by`, recorded as `claim --reassign`
    records it — but without claim's frontier check: a split parent is usually
    Blocked on its earlier children, and splitting it again is still fine.
    All or nothing (#26): the checks, every child and the parent's new
    dependencies are one write transaction, and a failed split leaves no
    child, no child folder, and the parent as it was.

    Each spec in `child_specs` is `{"id": str, "statement": str,
    "assumptions": list[str] (optional), "display_label": str (optional)}`.
    """
    if not child_specs:
        require_node(store, parent_id)
        raise ProofMapError("SPLIT_REQUIRES_CHILDREN", "split requires at least one child claim")
    with store.transaction() as conn:
        # Under the write lock, a child with no node yet and no folder yet is ours alone: no one
        # else can create that node until this commits. Any other folder may be another writer's
        # (create_node writes its proof.tex after committing), so a failed split leaves it be.
        # The cleanup is an on_rollback callback: it runs before the lock goes, while nobody else
        # can have taken the id, and a failed commit runs it too.
        ours = {
            node_folder(store.root, spec["id"])
            for spec in child_specs
            if _SAFE_NODE_ID.fullmatch(spec["id"]) and get_proof_map_node(store, spec["id"]) is None
        }
        ours = {folder for folder in ours if not folder.exists()}
        on_rollback(store, lambda: _remove_folders(ours))
        return _split(store, conn, parent_id, child_specs, created_by=created_by, reassign=reassign)


def _remove_folders(folders: set[Path]) -> None:
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)


def _split(
    store: ProjectStore,
    conn: sqlite3.Connection,
    parent_id: str,
    child_specs: list[dict[str, Any]],
    *,
    created_by: str,
    reassign: bool,
) -> list[ProofMapNode]:
    parent = require_node(store, parent_id)

    if parent.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError("IMMUTABLE_NODE", f"imported_result node {parent_id} cannot be split")

    acceptance = get_acceptance_state(store, parent_id)
    if acceptance == "rejected":
        raise ProofMapError(
            "NODE_REJECTED", f"node {parent_id} was Rejected and should not be pursued further; split is unavailable"
        )
    if acceptance in ("accepted", "unverifiable"):
        # new dependencies would change the interface the researcher accepted, and
        # silently void the acceptance: that's a decision, not a split (#37)
        raise ProofMapError(
            "NODE_ACCEPTED", f"node {parent_id} is {acceptance}; splitting it would void that decision, so split is unavailable"
        )

    claim = get_active_claim(store, parent_id, conn=conn)
    if claim is not None and claim.claimant_id != created_by:
        if not reassign:
            raise _not_claimant(parent_id, claim)
        mark_claim_released(store, claim.id, released_by=created_by, reason=f"reassigned to {created_by}", released_at=utc_now(), conn=conn)
        taken = ClaimRecord(id=str(uuid.uuid4()), node_id=parent_id, claimant_id=created_by, session_id="")
        insert_claim(store, taken, conn=conn)
        append_event(
            store,
            "proof_map_claim_reassigned",
            f"claimed node {parent_id} by {created_by}",
            entity_id=parent_id,
            payload={"claim_id": taken.id, "claimant_id": created_by, "previous_claimant_id": claim.claimant_id},
            conn=conn,
        )

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
    update_proof_map_node(store, updated_parent, conn=conn)

    append_event(
        store,
        "proof_map_node_split",
        f"split {parent_id} into {len(children)} claim(s)",
        entity_id=parent_id,
        payload={"child_ids": [c.id for c in children], "created_by": created_by},
        conn=conn,
    )
    return children


def _claim_conflict(existing: ClaimRecord) -> ProofMapError:
    return ProofMapError(
        "CLAIM_CONFLICT",
        f"node {existing.node_id} is already claimed by {existing.claimant_id}; pass --reassign to take it over",
        details={"node_id": existing.node_id, "assignee": existing.claimant_id, "claimed_at": existing.claimed_at.isoformat()},
    )


def _not_claimant(node_id: str, claim: ClaimRecord) -> ProofMapError:
    return ProofMapError(
        "NOT_CLAIMANT",
        f"{node_id} is claimed by {claim.claimant_id}",
        details={"node_id": node_id, "assignee": claim.claimant_id, "claimed_at": claim.claimed_at.isoformat()},
    )


def _not_pickable(store: ProjectStore, node: ProofMapNode) -> ProofMapError | None:
    """Why `node` isn't on the frontier for anyone to claim, or None if it is.

    The frontier and `claim_node` share this, so what the frontier offers is
    exactly what can be claimed. Accepted nodes are off it unless an open
    Challenge invites a revision (ADR-0005 Rule 4); Rejected ones for good.
    """
    if node.kind == ProofMapNodeKind.imported_result:
        return ProofMapError("IMMUTABLE_NODE", f"imported_result node {node.id} has no proof to work on; use Reference review instead")
    acceptance_state = get_acceptance_state(store, node.id)
    if acceptance_state == "rejected":
        return ProofMapError("NODE_REJECTED", f"node {node.id} was Rejected and should not be pursued further; create a new node instead")
    if acceptance_state == "accepted" and not has_open_challenge(store, node.id):
        return ProofMapError("NODE_ALREADY_ACCEPTED", f"node {node.id} is already Accepted; open a Challenge before reclaiming it to revise")
    if acceptance_state == "unverifiable":
        return ProofMapError(
            "NODE_UNVERIFIABLE",
            f"node {node.id}'s latest Human Review decision doesn't count; the researcher must decide it afresh before anyone picks it up",
        )
    if _has_unresolved_dependency(store, node):
        return ProofMapError("NODE_BLOCKED", f"node {node.id} is Blocked: a dependency isn't Accepted (or Reference-reviewed) yet")
    return None


def claim_node(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str = "",
    reassign: bool = False,
) -> ClaimRecord:
    """Assign a node to `claimant_id` before working on it: a wayfinder-style claim (ADR-0010).

    Idempotent for the same assignee. A node someone else holds is refused
    with CLAIM_CONFLICT naming the assignee, unless `reassign` takes it
    over — a claim is a planning signal, not a lock, so a stale one is simply
    reassigned. Only a node on the frontier can be claimed (see
    `_not_pickable`). The one-active-claim-per-node rule is the `claims`
    table's partial unique index, so a race between two claimants still
    resolves to one.
    """
    node = require_node(store, node_id)
    existing = get_active_claim(store, node_id)
    if existing is not None and existing.claimant_id == claimant_id:
        return existing
    problem = _not_pickable(store, node)
    if problem is not None:
        raise problem
    if existing is not None:
        if not reassign:
            raise _claim_conflict(existing)
        mark_claim_released(store, existing.id, released_by=claimant_id, reason=f"reassigned to {claimant_id}", released_at=utc_now())

    claim = ClaimRecord(id=str(uuid.uuid4()), node_id=node_id, claimant_id=claimant_id, session_id=session_id)
    try:
        insert_claim(store, claim)
    except sqlite3.IntegrityError as exc:
        existing = get_active_claim(store, node_id)
        if existing is not None and existing.claimant_id == claimant_id:
            return existing
        if existing is not None:
            raise _claim_conflict(existing) from exc
        raise ProofMapError("CLAIM_CONFLICT", f"node {node_id} is currently claimed") from exc
    except sqlite3.OperationalError as exc:
        # e.g. "database is locked" under heavy concurrent contention past
        # SQLite's busy_timeout — we don't know who, if anyone, won, so this
        # is honestly a contention error, not a confirmed conflict.
        raise ProofMapError("CLAIM_CONTENDED", f"could not claim node {node_id} due to database contention; retry") from exc

    append_event(
        store,
        "proof_map_claim_reassigned" if existing is not None else "proof_map_node_claimed",
        f"claimed node {node_id} by {claimant_id}",
        entity_id=node_id,
        payload={
            "claim_id": claim.id,
            "claimant_id": claimant_id,
            "previous_claimant_id": existing.claimant_id if existing is not None else None,
        },
    )
    return claim


def release_node(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str = "",
    reason: str | None = None,
) -> ClaimRecord:
    """Unassign a node: end its claim, whoever holds it (ADR-0010).

    A claim is a planning signal, so its holder, the researcher, or anyone
    by agreement may clear it; `claimant_id` is who did, recorded with the
    reason. Claims never expire on their own.
    """
    require_node(store, node_id)
    claim = get_active_claim(store, node_id)
    if claim is None:
        raise ProofMapError("NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim")
    release_reason = reason or ("released by claimant" if claim.claimant_id == claimant_id else f"unassigned by {claimant_id}")
    released_at = utc_now()
    if not mark_claim_released(store, claim.id, released_by=claimant_id, reason=release_reason, released_at=released_at):
        # someone else's concurrent release reached SQLite's write lock first
        raise ProofMapError("NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim")
    append_event(
        store,
        "proof_map_claim_released",
        f"released claim on {node_id} by {claimant_id}",
        entity_id=node_id,
        payload={"claim_id": claim.id, "original_claimant_id": claim.claimant_id, "released_by": claimant_id, "reason": release_reason},
    )
    return claim.model_copy(update={"released_by": claimant_id, "release_reason": release_reason, "released_at": released_at})


def request_review(store: ProjectStore, node_id: str, *, requested_by: str, rationale: str) -> CandidateProofRecord:
    """Snapshot a node's working `proof.tex` for review (ADR-0010).

    The working file is edited freely — by agents, the researcher, prism-local
    — and never reviewed directly: this copies it, byte for byte, to a new
    `snapshots/v<N>.tex` that is never overwritten, and records its SHA-256.
    Needs no claim. A node someone has claimed is theirs to hand over, and
    their claim ends here, as a wayfinder ticket's does when its work is.
    """
    node = require_node(store, node_id)
    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE", f"imported_result node {node_id} has no proof to review; use Reference review instead"
        )
    if not rationale.strip():
        raise ProofMapError(
            "SCOPING_RATIONALE_REQUIRED",
            "requesting review requires stating why this node is now appropriately scoped to prove directly",
        )
    working = working_proof_path(store.root, node_id)
    if not working.is_file():
        raise ProofMapError("WORKING_PROOF_MISSING", f"{working.relative_to(store.root).as_posix()} doesn't exist")
    content = working.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()

    # The holder check and every write are one SQLite write transaction (#18): a reassignment
    # can't slip in between them, it waits for this to commit. The files written go if it rolls
    # back, before its write lock does, so no later request can have taken their version yet.
    with store.transaction() as conn:
        claim = get_active_claim(store, node_id, conn=conn)
        if claim is not None and claim.claimant_id != requested_by:  # a node someone holds is theirs to hand over
            raise _not_claimant(node_id, claim)
        current = get_current_candidate_proof(store, node_id, conn=conn)
        if current is not None and current.sha256 == sha256:
            raise ProofMapError(
                "WORKING_PROOF_UNCHANGED",
                f"{node_id}'s working proof is unchanged since snapshot v{current.version}, which is already the one under review",
            )

        # past any snapshot already on disk too: one the index never got is an orphan, reported
        # by list_integrity_warnings, and never overwritten
        version = max([next_candidate_proof_version(store, node_id, conn=conn), *(n + 1 for n in snapshots_on_disk(store.root, node_id))])
        path = snapshot_path(store.root, node_id, version)
        # listed before writing, so a write that fails partway still goes; and only if absent
        # now, under the write lock, so a rollback never removes a file this request didn't write
        ours = [p for p in (path, path.with_suffix(".pdf")) if not p.exists()]
        on_rollback(store, lambda: _remove_files(ours))
        write_snapshot(path, content)
        if build_is_current(store.root, node_id):
            # a PDF compiled from this very text, preamble included (prism-local's build): archived beside the snapshot
            shutil.copyfile(build_pdf_path(store.root, node_id), path.with_suffix(".pdf"))
        record = CandidateProofRecord(
            id=str(uuid.uuid4()),
            node_id=node_id,
            version=version,
            file_path=path.relative_to(store.root).as_posix(),
            submitted_by=requested_by,
            scoping_rationale=rationale,
            sha256=sha256,
        )
        try:
            insert_candidate_proof(store, record, conn=conn)
        except sqlite3.IntegrityError as exc:
            raise ProofMapError("CANDIDATE_PROOF_VERSION_CONFLICT", f"version {version} of node {node_id} is already indexed") from exc

        pin_dependencies(store, node)
        if claim is not None:
            mark_claim_released(store, claim.id, released_by=requested_by, reason="review requested", released_at=utc_now(), conn=conn)
        append_event(
            store,
            "proof_map_review_requested",
            f"snapshot v{version} of {node_id} requested for review",
            entity_id=node_id,
            payload={"candidate_proof_id": record.id, "version": version, "file_path": record.file_path, "sha256": sha256, "requested_by": requested_by},
            conn=conn,
        )
    return record


def _remove_files(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


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
    reviewer: str | None = None, rationale: str = "",
) -> ReviewRecord:
    """Human Review's trust judgment on an Evidence check itself.

    Recorded in reviews.jsonl bound to the checked Candidate proof's
    snapshot (ADR-0010).

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

    governance_state = _EVIDENCE_DECISION_TO_GOVERNANCE_STATE[resolved_decision]
    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.evidence_review, target_id=evidence_check_id, decision=resolved_decision.value, reviewer=reviewer, rationale=rationale)
        record = _record(store, decided, _EVIDENCE_CHECK_OBJECT_TYPE, evidence_check_id, governance_state)
        append_event(
            store,
            "proof_map_evidence_review_decided",
            f"evidence review for {evidence_check_id}: {resolved_decision.value}",
            entity_id=check.candidate_proof_id,
            payload={"decision": resolved_decision.value, "reviewer_id": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def compute_interface_fingerprint(statement: str, assumptions: list[str]) -> str:
    """SHA-256 hex digest over the canonical JSON pair `(statement, assumptions)`.

    That pair is the node's mathematical interface — what a dependent
    actually relies on. `kind` is deliberately left out: claim vs lemma is a
    label about reusability, and relabeling (Promote) must never read as an
    interface change to existing dependents (#22). Statement and each
    assumption are whitespace-normalized (trimmed, internal runs collapsed)
    first, so two statements differing only by whitespace produce the same
    fingerprint. "Mathematical scope" is treated as already captured within
    statement + assumptions for v1.
    """
    return _digest([_normalize_whitespace(statement), [_normalize_whitespace(a) for a in assumptions]])


def _digest(parts: list) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()


_FINGERPRINTED_KINDS = (ProofMapNodeKind.theorem, ProofMapNodeKind.lemma, ProofMapNodeKind.claim)


def _legacy_with_kind_fingerprint(kind: str, statement: str, assumptions: list[str]) -> str:
    """The fingerprint as it was computed before #22, with `kind` inside it."""
    return _digest([kind, _normalize_whitespace(statement), [_normalize_whitespace(a) for a in assumptions]])


def _same_interface(store: ProjectStore, node_id: str, left: str | None, right: str | None) -> bool:
    """Whether two stored fingerprints of `node_id` describe the same interface.

    Fingerprints stored before #22 included the node's `kind`, so existing
    projects hold several spellings of one interface: the current
    `(statement, assumptions)` form and a with-kind form per kind. Any two
    of those, for this node's statement and assumptions, are the same
    interface — which is also what repairs a pin broken by a pre-#22 Promote.
    """
    if left is None or right is None:
        return False
    if left == right:
        return True
    node = get_node(store, node_id)
    if node is None:
        return False
    spellings = {compute_interface_fingerprint(node.statement, node.assumptions)} | {
        _legacy_with_kind_fingerprint(kind.value, node.statement, node.assumptions) for kind in _FINGERPRINTED_KINDS
    }
    return left in spellings and right in spellings


def _interface_of(node: ProofMapNode) -> str:
    """What a decision about `node` binds as its mathematical interface.

    A local node: its interface fingerprint. An imported result: its
    statement and source, so a Reference review can't be carried over to a
    different citation behind the same id (#35 C)."""
    if node.kind == ProofMapNodeKind.imported_result:
        return _digest(
            ["imported_result", _normalize_whitespace(node.statement), node.source_locator or "", node.source_version or ""]
        )
    return compute_interface_fingerprint(node.statement, node.assumptions)


def get_accepted_interface_fingerprint(store: ProjectStore, node_id: str) -> str | None:
    """The interface fingerprint of `node_id` if it is Accepted, else `None`.

    Recomputed from the node itself, never read off a stored column: an
    Acceptance only counts while the node still asserts exactly the
    interface that was accepted, so the two can't disagree (#35 C).
    """
    node = get_node(store, node_id)
    if node is None or get_acceptance_state(store, node_id) != "accepted":
        return None
    return compute_interface_fingerprint(node.statement, node.assumptions)


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
        target = get_node(store, target_id)
        if target is None:
            continue
        if target.kind == ProofMapNodeKind.imported_result:
            pinned_version, pinned_fingerprint = None, None
        else:
            pinned_fingerprint = get_accepted_interface_fingerprint(store, target_id)
            accepted = _accepted_proof(store, target_id) if pinned_fingerprint is not None else None
            pinned_version = accepted.version if accepted else None
        pin = DependencyPin(
            id=str(uuid.uuid4()),
            node_id=node.id,
            target_node_id=target_id,
            pinned_version=pinned_version,
            pinned_fingerprint=pinned_fingerprint,
        )
        pins.append(upsert_dependency_pin(store, pin))
    return pins


def _signed_pins(store: ProjectStore, node_id: str) -> dict[str, PinnedDependency] | None:
    """For an Accepted node: the pins its counted Acceptance was made on,
    as later refreshed by verified Lightweight re-reviews. `None` for a node
    that isn't Accepted, whose pins are just what its submission recorded."""
    node = get_node(store, node_id)
    if node is None:
        return None
    state, latest, _ = _acceptance(store, node)
    if state != "accepted":
        return None
    pins = {pin.target_node_id: pin for pin in latest.verdict.payload.dependency_pins}
    for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewRecordKind.dependency_revalidation.value):
        if row["seq"] <= latest.row["seq"]:
            continue
        verdict = verify_decision_row(store, row["id"])
        if verdict.status == "verified":
            pins.update({pin.target_node_id: pin for pin in verdict.payload.dependency_pins})
    return pins


def get_dependency_pin(store: ProjectStore, node_id: str, target_node_id: str) -> DependencyPin | None:
    """The pin as it counts. For an Accepted node that's the signed pin, not
    the `dependency_pins` row, which a direct edit could change (#35 C)."""
    stored = _get_dependency_pin(store, node_id, target_node_id)
    signed = (_signed_pins(store, node_id) or {}).get(target_node_id)
    if signed is None:
        return stored
    return DependencyPin(
        id=stored.id if stored else f"signed:{node_id}:{target_node_id}",
        node_id=node_id,
        target_node_id=target_node_id,
        pinned_version=signed.pinned_version,
        pinned_fingerprint=signed.pinned_fingerprint,
    )


def list_dependency_pins(store: ProjectStore, node_id: str) -> list[DependencyPin]:
    require_node(store, node_id)
    return [get_dependency_pin(store, node_id, pin.target_node_id) for pin in list_dependency_pins_for_node(store, node_id)]


def dependency_pin_is_current(store: ProjectStore, pin: DependencyPin) -> bool:
    """Whether a pinned dependency's interface still matches what the target now offers.

    Compared by fingerprint, never by version number: a target can move to
    a new Accepted version whose interface fingerprint is unchanged (a
    proof-only revision), and that must read as still current, not stale.
    """
    target = get_node(store, pin.target_node_id)
    if target is None or target.kind == ProofMapNodeKind.imported_result:
        return True
    current_fingerprint = get_accepted_interface_fingerprint(store, pin.target_node_id)
    return _same_interface(store, pin.target_node_id, pin.pinned_fingerprint, current_fingerprint)


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
    reviewer: str | None = None, rationale: str = "",
) -> ReviewRecord:
    """Record a Human Review acceptance decision for a local node.

    Only for a node in `review-needed`, and never once it's `rejected` (see
    `_require_awaiting_acceptance_review`). Recorded in the node's
    reviews.jsonl, bound to the current snapshot's SHA-256 and the node's
    dependency pins, and committed as the reviewer's git identity
    (ADR-0010); it counts only while it still describes the node.

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

    governance_state = _ACCEPTANCE_DECISION_TO_GOVERNANCE_STATE[resolved_decision]
    # the review rows, the candidate-proof link and fingerprint, the
    # Challenges it resolves and the events all commit together or not at
    # all: a decision interrupted part-way leaves the node exactly as it was.
    with store.transaction() as conn:
        # checked on the write lock, so no concurrent decision or submission
        # can land between the check and the write
        _require_awaiting_acceptance_review(store, node_id)
        decided = _decide(store, kind=DecisionKind.acceptance, target_id=node_id, decision=resolved_decision.value, reviewer=reviewer, rationale=rationale)
        current_proof = get_current_candidate_proof(store, node_id)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, governance_state)
        if current_proof is not None:
            set_candidate_proof_review_record_id(store, current_proof.id, record.id, conn=conn)
            if resolved_decision == AcceptanceDecision.accept:
                fingerprint = compute_interface_fingerprint(node.statement, node.assumptions)
                set_candidate_proof_interface_fingerprint(store, current_proof.id, fingerprint, conn=conn)

        _resolve_open_challenges(
            store,
            node_id,
            resolved_by=decided.reviewer_id,
            review_id=record.id,
            challenge_ids=decided.payload.resolves_challenges,
            conn=conn,
        )

        append_event(
            store,
            "proof_map_acceptance_decided",
            f"acceptance decision for {node_id}: {resolved_decision.value}",
            entity_id=node_id,
            payload={"decision": resolved_decision.value, "reviewer_id": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _pins_of(store: ProjectStore, node_id: str) -> list[PinnedDependency]:
    return [
        PinnedDependency(
            target_node_id=pin.target_node_id, pinned_version=pin.pinned_version, pinned_fingerprint=pin.pinned_fingerprint
        )
        for pin in list_dependency_pins_for_node(store, node_id)
    ]


def _refreshed_pin(store: ProjectStore, target_node_id: str) -> PinnedDependency:
    """What a Lightweight re-review re-pins a dependency to: its current accepted version and interface."""
    fingerprint = get_accepted_interface_fingerprint(store, target_node_id)
    accepted = _accepted_proof(store, target_node_id) if fingerprint is not None else None
    return PinnedDependency(
        target_node_id=target_node_id,
        pinned_version=accepted.version if accepted else None,
        pinned_fingerprint=fingerprint,
    )


def _current_proof_id(store: ProjectStore, node_id: str) -> str | None:
    current = get_current_candidate_proof(store, node_id)
    return current.id if current else None


def decision_binding(
    store: ProjectStore,
    kind: DecisionKind,
    target_id: str,
    *,
    dependency_id: str | None = None,
) -> dict[str, Any]:
    """What a decision of `kind` on `target_id` is made on, as of now.

    The Candidate proof (its id; `authority` adds the SHA-256 of its
    snapshot), the node's accepted mathematical interface, the dependency
    pins the reviewer is deciding against, and the open Challenges an
    Acceptance or Reference review resolves.
    """
    none = {"candidate_proof_id": None, "interface_fingerprint": None, "dependency_pins": [], "resolves_challenges": []}
    if kind in (DecisionKind.acceptance, DecisionKind.promote):
        node = require_node(store, target_id)
        return {
            "candidate_proof_id": _current_proof_id(store, target_id),
            "interface_fingerprint": _interface_of(node),
            "dependency_pins": _pins_of(store, target_id),
            "resolves_challenges": _open_challenge_ids(store, target_id) if kind == DecisionKind.acceptance else [],
        }
    if kind == DecisionKind.reference_review:
        node = require_node(store, target_id)
        return {**none, "interface_fingerprint": _interface_of(node), "resolves_challenges": _open_challenge_ids(store, target_id)}
    if kind == DecisionKind.dependency_revalidation:
        if dependency_id is None:
            raise ProofMapError("DEPENDENCY_REQUIRED", "a Lightweight re-review names the dependency it re-pins")
        node = require_node(store, target_id)
        return {
            **none,
            "candidate_proof_id": _current_proof_id(store, target_id),
            "interface_fingerprint": _interface_of(node),
            "dependency_pins": [_refreshed_pin(store, dependency_id)],
        }
    if kind == DecisionKind.evidence_review:
        check = require_evidence_check(store, target_id)
        proof = require_candidate_proof(store, check.candidate_proof_id)
        return {**none, "candidate_proof_id": proof.id, "interface_fingerprint": _interface_of(require_node(store, proof.node_id))}
    if kind == DecisionKind.challenge_resolution:
        challenge = require_challenge(store, target_id)
        return {**none, "interface_fingerprint": _interface_of(require_node(store, challenge.target_node_id))}
    raise ProofMapError("INVALID_DECISION_KIND", f"{kind.value} is not a proof-map decision")


def prepare_decision(
    store: ProjectStore,
    kind: DecisionKind | str,
    target_id: str,
    decision: str,
    *,
    rationale: str = "",
    dependency_id: str | None = None,
) -> DecisionPayload:
    """What a decision would be made on right now, for a page to show before the researcher decides. Decides nothing."""
    try:
        resolved_kind = DecisionKind(kind)
    except ValueError as exc:
        raise ProofMapError("INVALID_DECISION_KIND", f"'{kind}' is not a decision kind") from exc
    return build_decision_payload(
        store, resolved_kind, target_id, decision, rationale=rationale, **decision_binding(store, resolved_kind, target_id, dependency_id=dependency_id)
    )


def apply_decision(
    store: ProjectStore,
    kind: DecisionKind | str,
    target_id: str,
    decision: str,
    *,
    reviewer: str | None = None,
    rationale: str = "",
    dependency_id: str | None = None,
) -> Any:
    """Make one Human Review decision by kind: the proof map page's single entry point (ADR-0010)."""
    try:
        resolved_kind = DecisionKind(kind)
    except ValueError as exc:
        raise ProofMapError("INVALID_DECISION_KIND", f"'{kind}' is not a decision kind") from exc
    who = {"reviewer": reviewer, "rationale": rationale}
    if resolved_kind == DecisionKind.acceptance:
        return decide_acceptance(store, target_id, decision, **who)
    if resolved_kind == DecisionKind.reference_review:
        return decide_reference_review(store, target_id, decision, **who)
    if resolved_kind == DecisionKind.evidence_review:
        return decide_evidence_review(store, target_id, decision, **who)
    if resolved_kind == DecisionKind.dependency_revalidation:
        return revalidate_dependency(store, target_id, dependency_id or "", **who)
    if resolved_kind == DecisionKind.challenge_resolution:
        return dismiss_challenge(store, target_id, **who)
    if resolved_kind == DecisionKind.promote:
        return promote_to_lemma(store, target_id, **who)
    raise ProofMapError("UNSUPPORTED_DECISION", f"{resolved_kind.value} decisions aren't applied here")


@dataclass
class _Counted:
    """The newest decision row on a node for one kind, and what it's worth."""

    row: dict
    verdict: RowVerdict

    @property
    def decision(self) -> ReviewGovernanceState:
        return ReviewGovernanceState(self.row["decision"])


def _latest_decision(store: ProjectStore, node_id: str, kind: ReviewRecordKind) -> _Counted | None:
    rows = [
        row
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, kind.value)
        if row["decision"] != ReviewGovernanceState.proposed_for_review.value
    ]
    if not rows:
        return None
    return _Counted(rows[-1], verify_decision_row(store, rows[-1]["id"]))


def _binding_problem(store: ProjectStore, node: ProofMapNode, payload: DecisionPayload) -> str | None:
    """Why a verified decision no longer applies to `node` as it stands, or None."""
    proof = _get_candidate_proof(store, payload.candidate_proof_id) if payload.candidate_proof_id else None
    if proof is None or proof.node_id != node.id:
        return "it was made on a Candidate proof that isn't this node's"
    if candidate_proof_sha256(store, proof.id) != payload.candidate_proof_sha256:
        return "the snapshot's text changed after it was decided on"
    if payload.interface_fingerprint != _interface_of(node):
        return "the node's statement or assumptions changed after it was decided on"
    if set(node.dependencies) != {pin.target_node_id for pin in payload.dependency_pins}:
        return "the node's dependencies changed after it was decided on"
    return None


def _acceptance(store: ProjectStore, node: ProofMapNode) -> tuple[str, _Counted | None, str | None]:
    """(acceptance_state, the newest acceptance decision, why it doesn't count).

    Only the *newest* decision is ever read (B): if it doesn't verify, the
    node reads `unverifiable` — never an older decision it superseded. A
    Reject is terminal, and bound to the node, not to the proof text: a
    later edit never reopens a Rejected node.
    """
    rows = [
        row
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node.id, ReviewRecordKind.acceptance.value)
        if row["decision"] != ReviewGovernanceState.proposed_for_review.value
    ]
    if not rows:
        return "unreviewed", None, None
    # Reject is terminal, so legitimately nothing ever follows one: any
    # Reject row keeps the node rejected, even if something (a replay, a
    # forged row) was appended after it.
    reject = next((row for row in reversed(rows) if row["decision"] == ReviewGovernanceState.rejected.value), None)
    if reject is not None:
        verdict = verify_decision_row(store, reject["id"])
        return "rejected", _Counted(reject, verdict), None if verdict.status == "verified" else verdict.reason
    latest = _Counted(rows[-1], verify_decision_row(store, rows[-1]["id"]))
    if latest.verdict.status != "verified":
        return "unverifiable", latest, latest.verdict.reason
    problem = _binding_problem(store, node, latest.verdict.payload)
    if problem is not None:
        return "unverifiable", latest, problem
    if latest.decision == ReviewGovernanceState.approved:
        return "accepted", latest, None
    return "unreviewed", latest, None


def _accepted_proof(store: ProjectStore, node_id: str) -> CandidateProofRecord | None:
    """The Candidate proof an Accepted node's counted Acceptance was made on."""
    node = get_node(store, node_id)
    if node is None:
        return None
    state, latest, _ = _acceptance(store, node)
    if state != "accepted":
        return None
    return _get_candidate_proof(store, latest.verdict.payload.candidate_proof_id)


def get_accepted_version(store: ProjectStore, node_id: str) -> int | None:
    """The version of the Candidate proof a node's counted Acceptance names, or None if it isn't Accepted."""
    proof = _accepted_proof(store, node_id)
    return proof.version if proof else None


def get_acceptance_state(store: ProjectStore, node_id: str) -> str:
    """The node's acceptance_state, computed from its recorded Human Review decisions.

    One of `unreviewed`, `accepted`, `rejected`, `unverifiable` — never
    stored, always re-derived from the *newest* `kind=acceptance` decision
    (see `_acceptance`). An Acceptance counts only while it still describes
    this node: the Candidate proof it was made on is this node's and its
    text is unchanged, and the node still asserts the accepted interface. That accepted proof may be an
    earlier version while a newer one awaits review (the workflow axis then
    reads `review-needed`).
    """
    return _acceptance(store, require_node(store, node_id))[0]


def promote_to_lemma(store: ProjectStore, node_id: str, *, reviewer: str | None = None, rationale: str = "") -> ProofMapNode:
    """Promote an Accepted Claim to a Lemma, marking it independently reusable.

    The researcher's explicit decision, never automatic, recorded as its
    own review decision (ADR-0010). Only
    available for `kind=claim` nodes that are already Accepted and not under
    an open Challenge (a node whose soundness is in question isn't something
    to advertise as reusable); there is no demote. Every field but `kind` is
    unchanged — the Candidate-proof history and the interface fingerprint
    included, since `kind` isn't part of the interface (#22): every
    dependent's pin stays current across a promotion.
    """
    node = require_node(store, node_id)

    if node.kind != ProofMapNodeKind.claim:
        raise ProofMapError("NOT_A_CLAIM", f"node {node_id} is kind={node.kind.value}, not claim; only a claim can be promoted")

    if get_acceptance_state(store, node_id) != "accepted":
        raise ProofMapError("NOT_ACCEPTED", f"node {node_id} must be Accepted before it can be promoted to Lemma")

    if has_open_challenge(store, node_id):
        raise ProofMapError(
            "NODE_CHALLENGED", f"node {node_id} is under an open Challenge; resolve it before promoting to Lemma"
        )

    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.promote, target_id=node_id, decision="promote", reviewer=reviewer, rationale=rationale)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.approved)
        promoted = node.model_copy(
            update={"kind": ProofMapNodeKind.lemma, "updated_by": decided.reviewer_id, "updated_at": utc_now()}
        )
        update_proof_map_node(store, promoted, conn=conn)
        append_event(
            store,
            "proof_map_node_promoted",
            f"promoted {node_id} from claim to lemma",
            entity_id=node_id,
            payload={"promoted_by": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return promoted


REFERENCE_REVIEW_DECISION = "reference-review"
# the citation was found wanting: terminal, like a Reject — a corrected source is a new node (#20, #38)
REFERENCE_NOT_CALLABLE_DECISION = "no-longer-callable"
REFERENCE_REVIEW_DECISIONS = (REFERENCE_REVIEW_DECISION, REFERENCE_NOT_CALLABLE_DECISION)


def decide_reference_review(
    store: ProjectStore,
    node_id: str,
    decision: str,
    *,
    reviewer: str | None = None, rationale: str = "",
) -> ReviewRecord:
    """Grant Reference review to an imported_result node (a `reference_review` decision, ADR-0010).

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

    if decision not in REFERENCE_REVIEW_DECISIONS:
        raise ProofMapError(
            "INVALID_DECISION",
            f"'{decision}' is not a valid reference review decision; expected one of: {', '.join(REFERENCE_REVIEW_DECISIONS)}",
        )
    if _no_longer_callable(store, node_id):
        raise ProofMapError(
            "REFERENCE_NOT_CALLABLE",
            f"{node_id} is no longer callable, and that is final; cite a corrected source as a new imported_result node",
        )
    not_callable = decision == REFERENCE_NOT_CALLABLE_DECISION

    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.reference_review, target_id=node_id, decision=decision, reviewer=reviewer, rationale=rationale)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.rejected if not_callable else ReviewGovernanceState.approved)
        _resolve_open_challenges(
            store,
            node_id,
            resolved_by=decided.reviewer_id,
            review_id=record.id,
            challenge_ids=decided.payload.resolves_challenges,
            conn=conn,
        )
        append_event(
            store,
            "proof_map_no_longer_callable" if not_callable else "proof_map_reference_review_granted",
            f"{node_id} is no longer callable" if not_callable else f"reference review granted for {node_id}",
            entity_id=node_id,
            payload={"reviewer_id": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _no_longer_callable(store: ProjectStore, node_id: str) -> bool:
    """Whether any Reference review row says `no-longer-callable`: terminal however it's recorded, like a Reject."""
    return any(
        row["decision"] == ReviewGovernanceState.rejected.value
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewRecordKind.reference_review.value)
    )


def get_reference_review_state(store: ProjectStore, node_id: str) -> str:
    """`unreviewed`, `reviewed`, `unverifiable` or `no-longer-callable`, from the newest `kind=reference_review` decision.

    Counts only while the imported result still cites what was reviewed
    (statement and source) — never acceptance_state. Once found
    wanting, an imported result stays `no-longer-callable`.
    """
    node = require_node(store, node_id)
    if _no_longer_callable(store, node_id):
        return "no-longer-callable"
    latest = _latest_decision(store, node_id, ReviewRecordKind.reference_review)
    if latest is None:
        return "unreviewed"
    if latest.verdict.status != "verified" or latest.verdict.payload.interface_fingerprint != _interface_of(node):
        return "unverifiable"
    return "reviewed" if latest.decision == ReviewGovernanceState.approved else "unreviewed"


def revalidate_dependency(
    store: ProjectStore,
    node_id: str,
    target_node_id: str,
    *,
    reviewer: str | None = None, rationale: str = "",
) -> ReviewRecord:
    """Lightweight re-review: confirm an existing Candidate proof still holds after a dependency advanced.

    Recorded as a `dependency_revalidation` decision whose pins are exactly
    the refreshed pin this writes (ADR-0010).

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

    if not _same_interface(store, target_node_id, pin.pinned_fingerprint, current_fingerprint):
        raise ProofMapError(
            "INTERFACE_CHANGED",
            f"{target_node_id}'s accepted interface changed since {node_id} last pinned it; "
            "a new Candidate proof is required, lightweight re-review is not available",
        )

    refreshed = _refreshed_pin(store, target_node_id)
    new_version = refreshed.pinned_version
    old_pin = pin

    refreshed_pin = DependencyPin(
        id=pin.id,
        node_id=node_id,
        target_node_id=target_node_id,
        pinned_version=new_version,
        pinned_fingerprint=current_fingerprint,
    )
    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.dependency_revalidation, target_id=node_id, decision="reaffirmed", reviewer=reviewer, rationale=rationale, dependency_id=target_node_id)
        upsert_dependency_pin(store, refreshed_pin, conn=conn)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.reaffirmed)
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
    with store.transaction() as conn:
        insert_challenge(store, challenge, conn=conn)
        append_event(
            store,
            "proof_map_challenge_opened",
            f"challenge opened against {target_node_id} by {opened_by}",
            entity_id=target_node_id,
            payload={"challenge_id": challenge.id, "opened_by": opened_by, "rationale": rationale},
            conn=conn,
        )
    return challenge




def _derived_challenges(store: ProjectStore) -> list[Challenge]:
    """Every Challenge, with its status as it counts.

    Resolved by a recorded decision that names it; one dismissed before
    ADR-0010 with no such decision behind it keeps its stored status.
    """
    return [_with_resolution(store, challenge) for challenge in _list_challenges(store)]


def _challenge_outcome(row: dict) -> ChallengeStatus:
    """How the decision `row` ended the Challenges it names (#25)."""
    if row["kind"] == ReviewRecordKind.challenge_resolution.value:
        return ChallengeStatus.dismissed
    approved = row["decision"] == ReviewGovernanceState.approved.value
    if row["kind"] == ReviewRecordKind.reference_review.value:
        return ChallengeStatus.dismissed if approved else ChallengeStatus.upheld
    return ChallengeStatus.resolved_by_revision if approved else ChallengeStatus.upheld


def _with_resolution(store: ProjectStore, challenge: Challenge) -> Challenge:
    row = challenge_resolution(store, challenge.id)
    if row is not None:
        return challenge.model_copy(
            update={
                "status": _challenge_outcome(row),
                "resolved_by": row["reviewer_id"],
                "resolved_at": row["created_at"],
                "resolution_review_id": row["review_id"],
                "resolution_rationale": verify_decision_row(store, row["id"]).payload.rationale,
            }
        )
    if challenge.status == ChallengeStatus.dismissed and challenge.resolution_review_id is None:
        return challenge  # dismissed before ADR-0010, with nothing recorded behind it: it stays closed
    return challenge.model_copy(update={"status": ChallengeStatus.open, "resolved_by": None, "resolved_at": None, "resolution_review_id": None})


def get_challenge(store: ProjectStore, challenge_id: str) -> Challenge | None:
    return next((challenge for challenge in _derived_challenges(store) if challenge.id == challenge_id), None)


def require_challenge(store: ProjectStore, challenge_id: str) -> Challenge:
    challenge = get_challenge(store, challenge_id)
    if challenge is None:
        raise ProofMapError("CHALLENGE_NOT_FOUND", f"challenge {challenge_id} not found")
    return challenge


def list_challenges(store: ProjectStore, *, target_node_id: str = "", status: str = "") -> list[Challenge]:
    return [
        challenge
        for challenge in _derived_challenges(store)
        if (not target_node_id or challenge.target_node_id == target_node_id)
        and (not status or challenge.status.value == status)
    ]


def _open_challenge_ids(store: ProjectStore, node_id: str) -> list[str]:
    return [challenge.id for challenge in list_challenges(store, target_node_id=node_id, status="open")]


def has_open_challenge(store: ProjectStore, node_id: str) -> bool:
    return bool(list_challenges(store, target_node_id=node_id, status="open"))


def _resolve_open_challenges(
    store: ProjectStore,
    node_id: str,
    *,
    resolved_by: str,
    review_id: str,
    challenge_ids: list[str],
    conn: sqlite3.Connection,
) -> None:
    """Dismiss every open Challenge against `node_id`, as resolved by review `review_id`.

    Called from `decide_acceptance` and `decide_reference_review`: per
    ADR-0005 Rule 4, only Human Review resolves a Challenge, either by an
    explicit `challenge dismiss` or by directly addressing the concern —
    revising and re-Accepting a local node, or reaffirming trust in an
    Imported result's Reference review. Without this, a Challenge-driven
    reclaim (`claim_node`'s one sanctioned way to revise an Accepted node)
    would leave the node permanently `challenged` even after the concern was
    addressed.

    Runs on the deciding review's own transaction (`conn`). What resolves
    them is the recorded decision itself, which lists `challenge_ids` in its
    payload; marking the `challenges` rows here only keeps that advisory
    table in step.
    """
    resolved_at = utc_now()
    for challenge in [_get_challenge(store, challenge_id) for challenge_id in challenge_ids]:
        if challenge is None:
            continue
        reopened = challenge.status != ChallengeStatus.open
        if mark_challenge_dismissed(
            store,
            challenge.id,
            resolved_by=resolved_by,
            resolved_at=resolved_at,
            resolution_review_id=review_id,
            reopened=reopened,
            conn=conn,
        ):
            append_event(
                store,
                "proof_map_challenge_dismissed",
                f"challenge {challenge.id} dismissed by {resolved_by} (resolved via review decision)",
                entity_id=node_id,
                payload={"challenge_id": challenge.id, "reviewer_id": resolved_by, "review_id": review_id},
                conn=conn,
            )


def dismiss_challenge(
    store: ProjectStore,
    challenge_id: str,
    *,
    reviewer: str | None = None, rationale: str = "",
) -> Challenge:
    """Dismiss a Challenge — Human Review only: a `challenge_resolution` decision (ADR-0010).

    Nothing un-sets `potentially-stale`/`challenged` by hand: both are
    computed fresh from the set of *open* Challenges (and stale pins) on
    every read, so dismissing one simply removes it from that set — every
    overlay it alone was causing clears itself the next time anyone asks.
    """
    challenge = require_challenge(store, challenge_id)
    if challenge.status != ChallengeStatus.open:
        raise ProofMapError("CHALLENGE_NOT_OPEN", f"challenge {challenge_id} is already {challenge.status.value}")

    resolved_at = utc_now()
    with store.transaction() as conn:
        # re-read on the write lock: a concurrent dismissal may have landed
        if require_challenge(store, challenge_id).status != ChallengeStatus.open:
            raise ProofMapError("CHALLENGE_NOT_OPEN", f"challenge {challenge_id} is already dismissed")
        decided = _decide(store, kind=DecisionKind.challenge_resolution, target_id=challenge_id, decision="dismissed", reviewer=reviewer, rationale=rationale)
        record = _record(store, decided, "challenge", challenge_id, ReviewGovernanceState.dismissed)
        mark_challenge_dismissed(
            store,
            challenge_id,
            resolved_by=decided.reviewer_id,
            resolved_at=resolved_at,
            resolution_review_id=record.id,
            reopened=True,
            conn=conn,
        )
        append_event(
            store,
            "proof_map_challenge_dismissed",
            f"challenge {challenge_id} dismissed by {decided.reviewer_id}",
            entity_id=challenge.target_node_id,
            payload={
                "challenge_id": challenge_id,
                "reviewer_id": decided.reviewer_id,
                "rationale": decided.payload.rationale,
                "review_id": record.id,
            },
            conn=conn,
        )
    return challenge.model_copy(
        update={
            "status": ChallengeStatus.dismissed,
            "resolved_by": decided.reviewer_id,
            "resolved_at": resolved_at,
            "resolution_review_id": record.id,
        }
    )


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

        node = get_node(store, current_id)
        if node is None:
            continue
        if node.kind == ProofMapNodeKind.imported_result and _no_longer_callable(store, current_id):
            return True  # a citation found wanting: whatever rests on it needs a second look

        for dependency_id in node.dependencies:
            pin = get_dependency_pin(store, current_id, dependency_id)
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
    dependency = get_node(store, dependency_id)
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
    state, latest, _ = _acceptance(store, node)
    if state == "rejected":
        return "open"  # terminal: nothing further happens on a Rejected node

    # Whether the newest Human Review decision already covers the current
    # submission: the Candidate proof its *recorded payload* names is the
    # current one. Never the `review_record_id` column (advisory, and a
    # direct edit could point it anywhere), never timestamps. A decision
    # that doesn't count covers nothing, so the proof reads review-needed
    # again, for the researcher to decide afresh.
    review_is_current = (
        latest is not None
        and state != "unverifiable"
        and (current_proof is None or latest.verdict.payload.candidate_proof_id == current_proof.id)
    )

    if review_is_current and latest.decision == ReviewGovernanceState.revision_requested:
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
        dependency = get_node(store, dependency_id)
        if dependency is not None and dependency.kind == ProofMapNodeKind.imported_result and _no_longer_callable(store, dependency_id):
            return "dependency-not-callable"
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
    """The open, unblocked, unclaimed nodes: what an agent could claim right now (ADR-0010).

    The nodes `claim_node` would accept from anyone — the same check,
    `_not_pickable` — that nobody has claimed yet and that aren't already
    awaiting the researcher's review.
    """
    return [
        node
        for node in list_nodes(store)
        if get_active_claim(store, node.id) is None
        and _not_pickable(store, node) is None
        and get_workflow_state(store, node.id) != "review-needed"
    ]


def list_integrity_warnings(store: ProjectStore) -> list[AuthorityWarning]:
    """What about the recorded Human Review decisions doesn't count, node by node.

    The authority layer's own findings (unreadable lines, unconfirmed
    pre-ADR-0010 decisions, decisions git doesn't have yet) plus what only
    the proof map can see: a recorded Acceptance that no longer describes
    its node, and a Review snapshot on disk the index never recorded (an orphan
    of a crashed `request_review`, #18).
    """
    warnings = list_authority_warnings(store)
    for node in list_nodes(store):
        if node.kind == ProofMapNodeKind.imported_result:
            continue
        indexed = {proof.file_path for proof in list_candidate_proofs_for_node(store, node.id)}
        for _, path in sorted(snapshots_on_disk(store.root, node.id).items()):
            file_path = path.relative_to(store.root).as_posix()
            if file_path not in indexed:
                warnings.append(
                    AuthorityWarning(
                        code="ORPHAN_SNAPSHOT",
                        message=f"{file_path} was never indexed as a Candidate proof of {node.id}; review skips past it",
                        details={"node_id": node.id, "file_path": file_path},
                    )
                )
        state, latest, problem = _acceptance(store, node)
        if state == "unverifiable" and latest is not None and latest.verdict.status == "verified":
            warnings.append(
                AuthorityWarning(
                    code="DECISION_NO_LONGER_APPLIES",
                    message=f"{node.id}'s acceptance decision no longer counts: {problem}",
                    details={"node_id": node.id, "review_id": latest.row["review_id"]},
                )
            )
    return warnings
