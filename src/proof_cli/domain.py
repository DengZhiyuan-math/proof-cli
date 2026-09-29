from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TheoremStatus(str, Enum):
    imported = "imported"
    verified = "verified"
    assumed = "assumed"
    draft = "draft"
    blocked = "blocked"
    failed = "failed"


class TrustLevel(str, Enum):
    foundational = "foundational"
    project_verified = "project_verified"
    external_reference = "external_reference"
    temporary_admit = "temporary_admit"


class TheoremProvenanceKind(str, Enum):
    local = "local"
    imported = "imported"


class TheoremReviewState(str, Enum):
    draft = "draft"
    candidate = "candidate"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class ProofObligationStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    closed = "resolved"
    blocked = "blocked"

    @classmethod
    def _missing_(cls, value: object) -> ProofObligationStatus | None:
        if value == "closed":
            return cls.resolved
        return None


class BlockerStatus(str, Enum):
    active = "active"
    resolved = "resolved"


class ProofMapNodeKind(str, Enum):
    theorem = "theorem"
    lemma = "lemma"
    claim = "claim"
    imported_result = "imported_result"


class EventRecord(BaseModel):
    id: str
    kind: str
    entity_id: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TheoremContract(BaseModel):
    id: str
    kind: Literal["theorem", "lemma", "proposition", "corollary", "result"] = "theorem"
    name: str
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    status: TheoremStatus = TheoremStatus.draft
    trust_level: TrustLevel = TrustLevel.temporary_admit
    provenance_kind: TheoremProvenanceKind = TheoremProvenanceKind.local
    review_state: TheoremReviewState = TheoremReviewState.draft
    dependencies: list[str] = Field(default_factory=list)
    source_ref: str = "internal/project"
    grounded_reference_ids: list[str] = Field(default_factory=list)
    grounded_theorem_ids: list[str] = Field(default_factory=list)
    local_usage_notes: list[str] = Field(default_factory=list)
    imported_usage_notes: list[str] = Field(default_factory=list)
    created_by: str = "human"
    updated_by: str = "human"
    contributors: list[str] = Field(default_factory=list)
    supersedes_version: int | None = None
    notes: str = ""
    version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProofObligation(BaseModel):
    id: str
    goal_statement: str
    source_step_id: str | None = None
    required_for: str | None = None
    status: ProofObligationStatus = ProofObligationStatus.open
    priority: Literal["low", "medium", "high"] = "medium"
    blocking_reason: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BlockerRecord(BaseModel):
    id: str
    scope: str
    description: str
    failure_type: str
    related_steps: list[str] = Field(default_factory=list)
    related_contracts: list[str] = Field(default_factory=list)
    status: BlockerStatus = BlockerStatus.active
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProofMapNode(BaseModel):
    """The single entity type for every vertex in a proof map. See ADR-0001.

    `source_locator`/`source_version`/`trust_level` are only meaningful for
    an `imported_result`-kind node: where it came from, which version of it,
    and how much it's trusted. An `imported_result` is immutable once
    created — a source correction is always a brand-new node, never an edit
    of this one (see ADR on imported results). `statement`/`assumptions`
    likewise never change in place on any node, for the same reason. Two
    narrow, deliberate exceptions exist to that rule: Promote changes `kind`
    from `claim` to `lemma` (issue #22), and Split appends new child ids to
    `dependencies` (issue #26) — both go through `update_proof_map_node`,
    the only in-place write path this model has.

    `derived_from` is set by Split: which node a purpose-built subclaim was
    split from, distinguishing it from a coincidentally-shared Lemma. `None`
    for a node that wasn't produced by a split.
    """

    id: str
    kind: ProofMapNodeKind
    display_label: str = ""
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    source_locator: str | None = None
    source_version: str | None = None
    trust_level: TrustLevel | None = None
    derived_from: str | None = None
    created_by: str = "human"
    updated_by: str = "human"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ClaimRecord(BaseModel):
    """A node's assignee while someone works on it: a wayfinder-style claim (ADR-0010).

    A planning signal that tells concurrent agents to skip the node, never a
    lock: it doesn't gate editing the node's working proof, and anyone may
    reassign or clear a stale one. At most one active (unreleased) claim per
    node, enforced by a SQLite partial unique index. `session_id` is kept
    for the record only; it proves nothing. See ADR-0006, ADR-0010.
    """

    id: str
    node_id: str
    claimant_id: str
    session_id: str
    claimed_at: datetime = Field(default_factory=utc_now)
    released_at: datetime | None = None
    released_by: str | None = None
    release_reason: str | None = None


class CandidateProofRecord(BaseModel):
    """One immutable, versioned proof attempt for a ProofMapNode.

    Its file is the source of truth for the proof text; this record is the
    SQLite index over it. That file is a Review snapshot: since ADR-0011 a
    folder, `proofs/<node_id>/snapshots/v<version>/`, whose `manifest.json`
    is `file_path` and whose manifest digest is `sha256`; before it (ADR-0010)
    a single `snapshots/v<version>.tex`, with its SHA-256. Attempts from before
    ADR-0010 are read-only history files with no `sha256`. `id`
    is stable and independent of `file_path` — a review record references a
    submission by `id`, never by where its file happens to live. See ADR
    (candidate proof storage) and ProofMapNode.

    `interface_fingerprint` is set once, at the moment this version's node
    is Accepted (a pure function of that already-immutable version's kind,
    statement, and assumptions), never recomputed afterward. A dependency
    that pinned this version compares against it to tell an
    interface-preserving revision from a substantive one.
    """

    id: str
    node_id: str
    version: int
    file_path: str
    is_current: bool = True
    review_record_id: str | None = None
    submitted_by: str = "human"
    scoping_rationale: str
    interface_fingerprint: str | None = None
    sha256: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DependencyPin(BaseModel):
    """What a node's own Candidate proof was actually checked against.

    Refreshed every time `node_id` submits a new Candidate proof — captures
    the target's current accepted candidate-proof version and interface
    fingerprint at that moment, so a later comparison can tell "the target
    moved on but its interface didn't" from "the target's interface itself
    changed" without re-deriving anything. `pinned_version` and
    `pinned_fingerprint` are `None` for an `imported_result` target (it's
    immutable, so there's nothing to have moved on) and also `None` if the
    target wasn't yet Accepted at pin time. One row per (node_id,
    target_node_id) — always the most recent pin, not a history.
    """

    id: str
    node_id: str
    target_node_id: str
    pinned_version: int | None = None
    pinned_fingerprint: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ChallengeStatus(str, Enum):
    """How a Challenge stands, read off the signed decision that closed it (#25, #38)."""

    open = "open"
    # a false alarm: dismissed, or the Imported result's review reaffirmed
    dismissed = "dismissed"
    # the concern stood: the revision was rejected or sent back, or the Imported result is no longer callable
    upheld = "upheld"
    # a revised Candidate proof was Accepted
    resolved_by_revision = "resolved-by-revision"


class Challenge(BaseModel):
    """A claim that an already-Accepted (or Reference-reviewed) node may no longer be safe to depend on.

    Addressable on its own, never folded into its target as a boolean.
    Opening one is ungated — any collaborator or agent may raise a concern
    without needing anyone's permission first. Only Human Review resolves
    one, by dismissing it (or by the revision/re-Acceptance/reference-review
    decision that addresses the concern directly). See ADR-0004 point 3,
    ADR-0005 Rule 4.
    """

    id: str
    target_node_id: str
    status: ChallengeStatus = ChallengeStatus.open
    rationale: str = ""
    opened_by: str = "human"
    created_at: datetime = Field(default_factory=utc_now)
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    # the signed Human Review decision that resolved it (ADR-0009, #35)
    resolution_review_id: str | None = None
    # that decision's signed rationale
    resolution_rationale: str | None = None


class EvidenceOutcome(str, Enum):
    passed = "passed"
    failed = "failed"
    inconclusive = "inconclusive"
    error = "error"
    stale = "stale"


class EvidenceCheck(BaseModel):
    """An automated or semi-automated check run against a specific Candidate proof.

    Purely advisory: recording one, or a Human Review judgment of `trusted`
    or `unusable` on it (a `kind=evidence_review` decision), can never
    grant, revoke, or otherwise touch a node's acceptance_state — only
    `decide_acceptance` can (ADR-0004 point 5).
    """

    id: str
    candidate_proof_id: str
    outcome: EvidenceOutcome
    notes: str = ""
    run_by: str = "system"
    created_at: datetime = Field(default_factory=utc_now)


class ProjectSnapshot(BaseModel):
    project_id: str
    active_theorem: str | None = None
    current_goals: list[str] = Field(default_factory=list)
    validated_results: list[str] = Field(default_factory=list)
    open_obligations: list[str] = Field(default_factory=list)
    active_blockers: list[str] = Field(default_factory=list)
    recently_used_results: list[str] = Field(default_factory=list)
    unresolved_trust_sensitive_calls: list[str] = Field(default_factory=list)
    next_promising_routes: list[str] = Field(default_factory=list)
    publication_view_id: str | None = None
    publication_audience: str | None = None
    publication_claim_ids: list[str] = Field(default_factory=list)
    publication_release_ids: list[str] = Field(default_factory=list)
    publication_bundle_snapshot_ids: list[str] = Field(default_factory=list)
    latest_diagnostic_report: dict[str, Any] | None = None
    handoff_note: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ProjectState(BaseModel):
    project_id: str
    current_theorem: str | None = None
    current_context: list[str] = Field(default_factory=list)
    open_goals: list[str] = Field(default_factory=list)
    open_obligations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    failed_routes: list[str] = Field(default_factory=list)
    session_history: list[str] = Field(default_factory=list)
    latest_snapshot_id: str | None = None
    recent_theorem_usage: list[str] = Field(default_factory=list)
    unresolved_trust_sensitive_calls: list[str] = Field(default_factory=list)
