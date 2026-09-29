from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_serializer, model_validator

from .collaboration import CollaborationState, load_collaboration
from .domain import ProjectSnapshot, ProofMapNode, TheoremContract, TheoremProvenanceKind, utc_now
from .proof_map import ProofMapError, get_acceptance_state, get_integrity_state, get_node, list_nodes
from .references import ReferenceRecord
from .storage import (
    ProjectStore,
    list_blockers,
    list_obligations,
    list_references,
    read_latest_snapshot,
    read_publication_state,
    store_publication_bundle_snapshot,
    store_publication_state,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class PublicationAudience(str, Enum):
    internal = "internal"
    supplement = "supplement"
    paper = "paper"


class PublicationReadiness(str, Enum):
    """The editorial track (issue #30): how far a claim has got towards a paper.

    Editorial, never a Human Review decision, and settable by agents. It says
    nothing about whether the mathematics holds; that is the node's own
    acceptance and integrity, read live (`node_acceptance_and_integrity`).
    """

    internal_draft = "internal_draft"
    collaborator_ready = "collaborator_ready"
    supplement_ready = "supplement_ready"
    paper_ready = "paper_ready"
    withdrawn = "withdrawn"


PublicationState = PublicationReadiness

# The moves the editorial track allows, documented in CONTEXT.md ("Editorial
# readiness"): one step forward or back, withdraw from anywhere, and a
# withdrawn claim starts again at internal_draft. Re-setting the current state
# (to edit a claim's details) is always allowed.
ALLOWED_TRANSITIONS: dict[PublicationReadiness, tuple[PublicationReadiness, ...]] = {
    PublicationReadiness.internal_draft: (PublicationReadiness.collaborator_ready, PublicationReadiness.withdrawn),
    PublicationReadiness.collaborator_ready: (
        PublicationReadiness.internal_draft,
        PublicationReadiness.supplement_ready,
        PublicationReadiness.withdrawn,
    ),
    PublicationReadiness.supplement_ready: (
        PublicationReadiness.collaborator_ready,
        PublicationReadiness.paper_ready,
        PublicationReadiness.withdrawn,
    ),
    PublicationReadiness.paper_ready: (PublicationReadiness.supplement_ready, PublicationReadiness.withdrawn),
    PublicationReadiness.withdrawn: (PublicationReadiness.internal_draft,),
}

# States that put a claim in front of readers outside the project: only a node
# that is `accepted · current` may be moved to one (the write gate), and an
# export withholds a claim at one that no longer is.
READY_STATES = frozenset({PublicationReadiness.supplement_ready, PublicationReadiness.paper_ready})

# Readiness values the enum used to hold, and what a stored claim carrying one
# becomes when it is loaded. `disputed` and `blocked` were mathematical or
# workflow facts, which the node's own axes now carry, so the claim drops back
# to a draft; `superseded` means another claim replaced it, so it is withdrawn.
LEGACY_READINESS: dict[str, PublicationReadiness] = {
    "disputed": PublicationReadiness.internal_draft,
    "blocked": PublicationReadiness.internal_draft,
    "superseded": PublicationReadiness.withdrawn,
}

PUBLICATION_OBJECT_TYPES = ("proof_map_node", "theorem_contract")

EDITORIAL_LABEL = "editorial, not a Human Review decision"


class PublicationCitationKind(str, Enum):
    project_original = "project_original"
    imported_reference = "imported_reference"
    imported_standard_result = "imported_standard_result"
    adapted = "adapted"
    conditional = "conditional"


class PublicationVisibility(str, Enum):
    internal_only = "internal_only"
    supplement = "supplement"
    paper = "paper"


class PublicationReleaseStatus(str, Enum):
    approved = "approved"
    corrected = "corrected"
    withdrawn = "withdrawn"


class PublicationClaim(BaseModel):
    """A claim's editorial record. Every field here is editorial (`track`)."""

    id: str = Field(default_factory=lambda: _new_id("pubclaim"))
    object_type: str
    object_id: str
    display_name: str = ""
    title: str = ""
    section_placement: str = ""
    readiness: PublicationReadiness = PublicationReadiness.internal_draft
    citation_kind: PublicationCitationKind = PublicationCitationKind.project_original
    internal_only: bool = False
    editorial_notes: list[str] = Field(default_factory=list)
    supporting_reference_ids: list[str] = Field(default_factory=list)
    supporting_theorem_ids: list[str] = Field(default_factory=list)
    # None until a release status is explicitly given (issue #30: no default approval)
    release_status: PublicationReleaseStatus | None = None
    release_notes: str = ""
    updated_by: str = "human"
    # the retired readiness value this claim was loaded with, if any (LEGACY_READINESS)
    migrated_from: str | None = None
    track: str = "editorial"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_readiness(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("readiness") in LEGACY_READINESS:
            legacy = data["readiness"]
            migrated = LEGACY_READINESS[legacy].value
            data = {
                **data,
                "readiness": migrated,
                "migrated_from": legacy,
                "editorial_notes": [
                    *data.get("editorial_notes", []),
                    f"readiness '{legacy}' is retired; migrated to '{migrated}' (issue #30)",
                ],
            }
        return data

    @property
    def publication_state(self) -> PublicationReadiness:
        return self.readiness

    @property
    def visibility(self) -> PublicationVisibility:
        return _claim_visibility(self)


PublicationStateRecord = PublicationClaim


class PublicationSelection(BaseModel):
    claim: PublicationClaim
    visible: bool = True
    reason: str = ""
    section_label: str = ""
    # Read live from the core model at selection time, never stored on the
    # claim itself — orthogonal to the claim's own editorial `readiness`
    # (issue #30). `None` for a claim not backed by a proof_map_node.
    acceptance_state: str | None = None
    integrity_state: str | None = None
    # at a ready state for this audience, but not `accepted · current` now
    withheld: bool = False


class PublicationView(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("pubview"))
    name: str
    audience: PublicationAudience = PublicationAudience.paper
    scope: str = "project"
    visibility: PublicationVisibility = PublicationVisibility.paper
    selections: list[PublicationSelection] = Field(default_factory=list)
    included_object_ids: list[str] = Field(default_factory=list)
    excluded_object_ids: list[str] = Field(default_factory=list)
    section_mapping: dict[str, str] = Field(default_factory=dict)
    notes: str = ""
    status: str = "draft"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PublicationVerificationSummary(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("versum"))
    scope: str
    included_fragments: list[str] = Field(default_factory=list)
    summary: str = ""
    publication_visibility: PublicationVisibility = PublicationVisibility.supplement
    created_at: datetime = Field(default_factory=utc_now)


class PublicationEditorialNote(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("ednote"))
    scope: str
    section_label: str = ""
    content: str
    updated_by: str = "human"
    created_at: datetime = Field(default_factory=utc_now)


class PublicationReleaseRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("release"))
    bundle_id: str
    audience: PublicationAudience = PublicationAudience.paper
    status: PublicationReleaseStatus = PublicationReleaseStatus.approved
    approved_by: list[str] = Field(default_factory=list)
    withdrawn_by: list[str] = Field(default_factory=list)
    rationale: str = ""
    notes: str = ""
    # an editorial record: `approved_by` names who said so, and is not a Human
    # Review decision; a release sign-off on record is the release commit's git author
    track: str = "editorial"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PublicationBundleSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("pbundle"))
    bundle_id: str
    bundle_kind: str
    audience: PublicationAudience = PublicationAudience.paper
    note: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class PublicationWorkspace(BaseModel):
    project_id: str
    version: int = 1
    claims: list[PublicationClaim] = Field(default_factory=list)
    views: list[PublicationView] = Field(default_factory=list)
    citation_provenance: list[dict[str, Any]] = Field(default_factory=list)
    verification_summaries: list[PublicationVerificationSummary] = Field(default_factory=list)
    editorial_notes: list[PublicationEditorialNote] = Field(default_factory=list)
    release_history: list[PublicationReleaseRecord] = Field(default_factory=list)
    bundle_snapshots: list[PublicationBundleSnapshot] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def states(self) -> list[PublicationClaim]:
        return self.claims

    @states.setter
    def states(self, value: list[PublicationClaim]) -> None:
        self.claims = value

    @property
    def release_records(self) -> list[PublicationReleaseRecord]:
        return self.release_history

    @release_records.setter
    def release_records(self, value: list[PublicationReleaseRecord]) -> None:
        self.release_history = value

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        data["states"] = data.get("claims", [])
        data["release_records"] = data.get("release_history", [])
        return data


def _state_row(store: ProjectStore) -> dict[str, Any] | None:
    raw = read_publication_state(store)
    if raw is None:
        return None
    return json.loads(raw)


def load_publication_state(store: ProjectStore) -> PublicationWorkspace:
    from .proof_state import load_state

    state = load_state(store)
    row = _state_row(store)
    if row is None:
        return PublicationWorkspace(project_id=state.project_id)
    payload = dict(row)
    payload.setdefault("project_id", state.project_id)
    return PublicationWorkspace.model_validate(payload)


load_publication_workspace = load_publication_state


def save_publication_state(store: ProjectStore, state: PublicationWorkspace) -> PublicationWorkspace:
    from .proof_state import load_state

    state.project_id = load_state(store).project_id
    state.version += 1
    state.updated_at = utc_now()
    store_publication_state(store, state.project_id, json.dumps(state.model_dump(mode="json")), updated_at=state.updated_at)
    return state


save_publication_workspace = save_publication_state


def _save_state_with_event(
    store: ProjectStore,
    state: PublicationWorkspace,
    *,
    event_kind: str,
    message: str,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> PublicationWorkspace:
    save_publication_state(store, state)
    from .storage import append_event

    append_event(store, event_kind, message, entity_id=entity_id, payload=payload or {})
    return state


def _normalize_audience(value: PublicationAudience | str) -> PublicationAudience:
    return value if isinstance(value, PublicationAudience) else PublicationAudience(value)


def _normalize_visibility(value: PublicationVisibility | str | None) -> PublicationVisibility:
    if value is None:
        return PublicationVisibility.internal_only
    return value if isinstance(value, PublicationVisibility) else PublicationVisibility(value)


def _claim_visibility(claim: PublicationClaim) -> PublicationVisibility:
    if claim.internal_only:
        return PublicationVisibility.internal_only
    if claim.readiness == PublicationReadiness.paper_ready:
        return PublicationVisibility.paper
    if claim.readiness == PublicationReadiness.supplement_ready:
        return PublicationVisibility.supplement
    return PublicationVisibility.internal_only


def _claim_from_theorem(theorem: TheoremContract) -> PublicationClaim:
    """A default publication claim for a theorem with no explicit editorial decision yet.

    `readiness` starts at `internal_draft` — the editorial track is never
    auto-derived from the theorem's own status/review_state (issue #30);
    reaching anything past `internal_draft`, `paper_ready` above all,
    always requires an explicit `set_publication_claim`/`set_publication_state`
    call from a human editor.
    """
    return PublicationClaim(
        object_type="theorem_contract",
        object_id=theorem.id,
        display_name=theorem.name,
        title=theorem.statement,
        section_placement="",
        readiness=PublicationReadiness.internal_draft,
        citation_kind=PublicationCitationKind.project_original if theorem.provenance_kind == TheoremProvenanceKind.local else PublicationCitationKind.imported_reference,
        internal_only=False,
        editorial_notes=list(theorem.local_usage_notes) or list(theorem.imported_usage_notes),
        supporting_reference_ids=list(theorem.grounded_reference_ids),
        supporting_theorem_ids=list(theorem.grounded_theorem_ids),
        release_notes=theorem.notes,
        updated_by=theorem.updated_by,
        created_at=theorem.created_at,
        updated_at=theorem.updated_at,
    )


def _claim_from_proof_map_node(node: ProofMapNode) -> PublicationClaim:
    """A default publication claim for a ProofMapNode with no explicit editorial decision yet.

    Same rule as `_claim_from_theorem`: `readiness` starts at `internal_draft`
    regardless of the node's own acceptance_state — accepted and
    paper-ready are orthogonal, and only a human editor's explicit call
    ever moves the editorial track.
    """
    return PublicationClaim(
        object_type="proof_map_node",
        object_id=node.id,
        display_name=node.display_label or node.id,
        title=node.statement,
        section_placement="",
        readiness=PublicationReadiness.internal_draft,
        citation_kind=PublicationCitationKind.project_original,
        internal_only=False,
        # a node's dependencies are node ids, not theorem-contract ids: they stay
        # on the node, and aren't copied into supporting_theorem_ids (issue #30)
        updated_by=node.updated_by,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def node_acceptance_and_integrity(store: ProjectStore, object_type: str, object_id: str) -> tuple[str | None, str | None]:
    """The claim's underlying node's acceptance_state/integrity_state, read live from the core model.

    `None, None` for anything that isn't a `proof_map_node` claim (e.g. a
    `theorem_contract` claim, which predates the unified node model and has
    no acceptance/integrity axes of its own). Never stored or cached here —
    publication's own editorial `readiness` is a completely separate,
    explicitly-set track (issue #30).
    """
    if object_type != "proof_map_node" or get_node(store, object_id) is None:
        return None, None
    return get_acceptance_state(store, object_id), get_integrity_state(store, object_id)


def standing_problem(object_type: str, acceptance_state: str | None, integrity_state: str | None) -> str | None:
    """Why a claim can't stand at a ready state, or None when its node is `accepted · current`."""
    if object_type != "proof_map_node":
        return f"a {object_type} claim has no acceptance axis"
    if acceptance_state is None:
        return "no such proof map node"
    if acceptance_state != "accepted" or integrity_state != "current":
        return f"not accepted · current (acceptance={acceptance_state}, integrity={integrity_state})"
    return None


def _axes_text(acceptance_state: str | None, integrity_state: str | None) -> str:
    if acceptance_state is None:
        return "acceptance=none integrity=none"
    return f"acceptance={acceptance_state} integrity={integrity_state}"


def claim_payload(store: ProjectStore, claim: PublicationClaim) -> dict[str, Any]:
    """A claim as the CLI and the exports show it: its editorial record, and its node's live axes beside it."""
    acceptance_state, integrity_state = node_acceptance_and_integrity(store, claim.object_type, claim.object_id)
    return {
        **claim.model_dump(mode="json"),
        "track": "editorial",
        "acceptance_state": acceptance_state,
        "integrity_state": integrity_state,
    }


def _normalize_object_type(object_type: str) -> str:
    if object_type not in PUBLICATION_OBJECT_TYPES:
        raise ProofMapError(
            "INVALID_OBJECT_TYPE",
            f"not a publication object type: {object_type!r}",
            details={"object_type": object_type, "allowed": list(PUBLICATION_OBJECT_TYPES)},
        )
    return object_type


def _require_object(store: ProjectStore, object_type: str, object_id: str) -> Any:
    from .theorems import list_theorems

    if object_type == "proof_map_node":
        node = get_node(store, object_id)
        if node is None:
            raise ProofMapError("NODE_NOT_FOUND", f"no proof map node {object_id!r}", details={"node_id": object_id})
        return node
    theorem = next((item for item in list_theorems(store) if item.id == object_id), None)
    if theorem is None:
        raise ProofMapError("THEOREM_NOT_FOUND", f"no theorem contract {object_id!r}", details={"theorem_id": object_id})
    return theorem


def _parse_enum(enum: type[Enum], value: Any, code: str, what: str) -> Any:
    if isinstance(value, enum):
        return value
    try:
        return enum(value)
    except ValueError:
        raise ProofMapError(
            code, f"not a {what}: {value!r}", details={"value": value, "allowed": [member.value for member in enum]}
        ) from None


def parse_readiness(value: PublicationReadiness | str) -> PublicationReadiness:
    return _parse_enum(PublicationReadiness, value, "INVALID_READINESS", "readiness")


def parse_audience(value: PublicationAudience | str) -> PublicationAudience:
    return _parse_enum(PublicationAudience, value, "INVALID_AUDIENCE", "publication audience")


def parse_release_status(value: PublicationReleaseStatus | str) -> PublicationReleaseStatus:
    return _parse_enum(PublicationReleaseStatus, value, "INVALID_RELEASE_STATUS", "release status")


def parse_citation_kind(value: PublicationCitationKind | str) -> PublicationCitationKind:
    return _parse_enum(PublicationCitationKind, value, "INVALID_CITATION_KIND", "citation kind")


def check_readiness_write(
    store: ProjectStore, object_type: str, object_id: str, current: PublicationReadiness, target: PublicationReadiness
) -> None:
    """The editorial track's rules for one write (issue #30), raising a stable ProofMapError.

    The move must be one ALLOWED_TRANSITIONS lists, and a ready state needs a
    node that is `accepted · current` now. A theorem_contract claim has no
    acceptance axis, so it never reaches one.
    """
    if target != current and target not in ALLOWED_TRANSITIONS[current]:
        raise ProofMapError(
            "INVALID_READINESS_TRANSITION",
            f"the editorial track doesn't move {current.value} -> {target.value}",
            details={
                "from": current.value,
                "to": target.value,
                "allowed": [current.value, *(state.value for state in ALLOWED_TRANSITIONS[current])],
            },
        )
    if target not in READY_STATES:
        return
    if object_type != "proof_map_node":
        raise ProofMapError(
            "PUBLICATION_NO_ACCEPTANCE_AXIS",
            f"{object_type}/{object_id} has no acceptance axis, so it can't be marked {target.value}",
            details={"object_type": object_type, "object_id": object_id, "readiness": target.value},
        )
    acceptance_state, integrity_state = node_acceptance_and_integrity(store, object_type, object_id)
    if acceptance_state != "accepted" or integrity_state != "current":
        raise ProofMapError(
            "PUBLICATION_NOT_ACCEPTED",
            f"{object_id} is {acceptance_state} · {integrity_state}; only a node that is accepted · current "
            f"may be marked {target.value}",
            details={
                "node_id": object_id,
                "readiness": target.value,
                "acceptance_state": acceptance_state,
                "integrity_state": integrity_state,
            },
        )


def _claim_sort_key(claim: PublicationClaim) -> tuple[str, str, str]:
    section = claim.section_placement or ""
    return (section, claim.object_type, claim.object_id)


def _explicit_claims_by_key(state: PublicationWorkspace) -> dict[tuple[str, str], PublicationClaim]:
    return {(claim.object_type, claim.object_id): claim for claim in state.claims}


def _all_claims(store: ProjectStore) -> list[PublicationClaim]:
    from .theorems import list_theorems

    state = load_publication_state(store)
    explicit = _explicit_claims_by_key(state)
    claims = list(explicit.values())
    for theorem in list_theorems(store):
        key = ("theorem_contract", theorem.id)
        if key not in explicit:
            claims.append(_claim_from_theorem(theorem))
    for node in list_nodes(store):
        key = ("proof_map_node", node.id)
        if key not in explicit:
            claims.append(_claim_from_proof_map_node(node))
    claims.sort(key=_claim_sort_key)
    return claims


def set_publication_claim(
    store: ProjectStore,
    object_id: str,
    *,
    object_type: str = "proof_map_node",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    readiness: PublicationReadiness | str = PublicationReadiness.internal_draft,
    readiness_reason: str = "",
    citation_kind: PublicationCitationKind | str | None = None,
    internal_only: bool = False,
    editorial_notes: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    supporting_theorem_ids: list[str] | None = None,
    release_status: PublicationReleaseStatus | str | None = None,
    release_notes: str = "",
    updated_by: str = "human",
) -> PublicationClaim:
    """Set a claim's editorial record: an editorial write, open to agents, never a Human Review decision.

    Refused, with a stable code, for an object that doesn't exist, a move the
    editorial track doesn't allow, or a ready state on a node that isn't
    `accepted · current` (`check_readiness_write`). Nothing is written then.
    """
    _normalize_object_type(object_type)
    target_object = _require_object(store, object_type, object_id)
    target = parse_readiness(readiness)
    citation = parse_citation_kind(citation_kind) if citation_kind else None
    release = parse_release_status(release_status) if release_status else None
    state = load_publication_state(store)
    claim = next((item for item in state.claims if item.object_type == object_type and item.object_id == object_id), None)
    check_readiness_write(
        store, object_type, object_id, claim.readiness if claim is not None else PublicationReadiness.internal_draft, target
    )
    if claim is None:
        claim = _claim_from_proof_map_node(target_object) if object_type == "proof_map_node" else _claim_from_theorem(target_object)
        claim.created_at = claim.updated_at = utc_now()
        state.claims.append(claim)
    if not display_name:
        display_name = claim.display_name
    if not title:
        title = claim.title
    claim.display_name = display_name
    claim.title = title
    claim.section_placement = section_placement or claim.section_placement
    claim.readiness = target
    claim.internal_only = internal_only
    if citation is not None:
        claim.citation_kind = citation
    if editorial_notes is not None:
        claim.editorial_notes = list(editorial_notes)
    if supporting_reference_ids is not None:
        claim.supporting_reference_ids = list(supporting_reference_ids)
    if supporting_theorem_ids is not None:
        claim.supporting_theorem_ids = list(supporting_theorem_ids)
    if release is not None:
        claim.release_status = release
    claim.release_notes = release_notes or readiness_reason or claim.release_notes
    claim.updated_by = updated_by
    claim.updated_at = utc_now()
    _save_state_with_event(
        store,
        state,
        event_kind="publication_claim_updated",
        message=f"updated publication claim {object_type}/{object_id}",
        entity_id=object_id,
        payload=claim.model_dump(mode="json"),
    )
    return claim


def set_publication_state(
    store: ProjectStore,
    object_id: str,
    publication_state: PublicationReadiness | str,
    *,
    object_type: str = "proof_map_node",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    reason: str = "",
    citation_kind: PublicationCitationKind | str | None = None,
    internal_only: bool = False,
    editorial_notes: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    supporting_theorem_ids: list[str] | None = None,
    release_status: PublicationReleaseStatus | str | None = None,
    release_notes: str = "",
    updated_by: str = "human",
) -> PublicationClaim:
    return set_publication_claim(
        store,
        object_id,
        object_type=object_type,
        display_name=display_name,
        title=title,
        section_placement=section_placement,
        readiness=publication_state,
        readiness_reason=reason,
        citation_kind=citation_kind,
        internal_only=internal_only,
        editorial_notes=editorial_notes,
        supporting_reference_ids=supporting_reference_ids,
        supporting_theorem_ids=supporting_theorem_ids,
        release_status=release_status,
        release_notes=release_notes,
        updated_by=updated_by,
    )


def set_publication_readiness(
    store: ProjectStore,
    object_id: str,
    readiness: PublicationReadiness | str,
    *,
    object_type: str = "proof_map_node",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    reason: str = "",
    citation_kind: PublicationCitationKind | str | None = None,
    internal_only: bool = False,
    editorial_notes: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    supporting_theorem_ids: list[str] | None = None,
    release_status: PublicationReleaseStatus | str | None = None,
    release_notes: str = "",
    updated_by: str = "human",
) -> PublicationClaim:
    return set_publication_claim(
        store,
        object_id,
        object_type=object_type,
        display_name=display_name,
        title=title,
        section_placement=section_placement,
        readiness=readiness,
        readiness_reason=reason,
        citation_kind=citation_kind,
        internal_only=internal_only,
        editorial_notes=editorial_notes,
        supporting_reference_ids=supporting_reference_ids,
        supporting_theorem_ids=supporting_theorem_ids,
        release_status=release_status,
        release_notes=release_notes,
        updated_by=updated_by,
    )


def list_publication_claims(store: ProjectStore, *, object_type: str = "") -> list[PublicationClaim]:
    claims = _all_claims(store)
    if object_type:
        claims = [claim for claim in claims if claim.object_type == object_type]
    return claims


def get_publication_claim(store: ProjectStore, object_id: str, *, object_type: str = "proof_map_node") -> PublicationClaim | None:
    from .theorems import list_theorems

    state = load_publication_state(store)
    for claim in reversed(state.claims):
        if claim.object_type == object_type and claim.object_id == object_id:
            return claim
    if object_type == "theorem_contract":
        theorem = next((item for item in list_theorems(store) if item.id == object_id), None)
        if theorem is not None:
            return _claim_from_theorem(theorem)
    if object_type == "proof_map_node":
        node = get_node(store, object_id)
        if node is not None:
            return _claim_from_proof_map_node(node)
    return None


def list_publication_views(store: ProjectStore) -> list[PublicationView]:
    return list(load_publication_state(store).views)


def list_publication_state_records(store: ProjectStore, *, object_type: str = "", object_id: str = "") -> list[PublicationClaim]:
    claims = list_publication_claims(store, object_type=object_type)
    if object_id:
        claims = [claim for claim in claims if claim.object_id == object_id]
    return claims


def create_publication_view(
    store: ProjectStore,
    name: str,
    *,
    audience: PublicationAudience | str = PublicationAudience.paper,
    scope: str = "project",
    visibility: PublicationVisibility | str | None = None,
    included_object_ids: list[str] | None = None,
    excluded_object_ids: list[str] | None = None,
    section_mapping: dict[str, str] | None = None,
    notes: str = "",
) -> PublicationView:
    state = load_publication_state(store)
    audience_enum = _normalize_audience(audience)
    view = PublicationView(
        name=name,
        audience=audience_enum,
        scope=scope,
        visibility=_normalize_visibility(visibility) if visibility is not None else (PublicationVisibility.paper if audience_enum == PublicationAudience.paper else PublicationVisibility.supplement),
        included_object_ids=included_object_ids or [],
        excluded_object_ids=excluded_object_ids or [],
        section_mapping=section_mapping or {},
        notes=notes,
    )
    state.views.append(view)
    _save_state_with_event(
        store,
        state,
        event_kind="publication_view_created",
        message=f"created publication view {name}",
        entity_id=view.id,
        payload=view.model_dump(mode="json"),
    )
    return view


def get_publication_view(store: ProjectStore, view_id: str) -> PublicationView | None:
    return next((view for view in load_publication_state(store).views if view.id == view_id), None)


def _select_claims_for_audience(
    store: ProjectStore,
    claims: list[PublicationClaim],
    *,
    audience: PublicationAudience,
    included_object_ids: list[str] | None = None,
    excluded_object_ids: list[str] | None = None,
    section_mapping: dict[str, str] | None = None,
) -> list[PublicationSelection]:
    included = set(included_object_ids or [])
    excluded = set(excluded_object_ids or [])
    selections: list[PublicationSelection] = []
    for claim in claims:
        visible = True
        reasons: list[str] = []
        if claim.object_id in excluded:
            visible = False
            reasons.append("excluded by view")
        if included and claim.object_id not in included:
            visible = False
            reasons.append("not included in view")
        if claim.internal_only:
            visible = False
            reasons.append("internal only")
        if claim.readiness == PublicationReadiness.withdrawn and audience != PublicationAudience.internal:
            visible = False
            reasons.append("withdrawn")
        if audience == PublicationAudience.paper:
            if claim.readiness != PublicationReadiness.paper_ready:
                visible = False
                reasons.append("not paper ready")
        elif audience == PublicationAudience.supplement:
            if claim.readiness not in READY_STATES:
                visible = False
                reasons.append("not supplement ready")
        section_label = (section_mapping or {}).get(claim.object_id, claim.section_placement)
        acceptance_state, integrity_state = node_acceptance_and_integrity(store, claim.object_type, claim.object_id)
        # the mathematical track: a claim at a ready state whose node isn't
        # `accepted · current` any more is withheld from outside readers, and flagged
        withheld = False
        if visible and audience != PublicationAudience.internal:
            problem = standing_problem(claim.object_type, acceptance_state, integrity_state)
            if problem is not None:
                visible = False
                withheld = True
                reasons.append(f"withheld: {problem}")
        selections.append(
            PublicationSelection(
                claim=claim,
                visible=visible,
                reason="; ".join(dict.fromkeys(reasons)),
                section_label=section_label,
                acceptance_state=acceptance_state,
                integrity_state=integrity_state,
                withheld=withheld,
            )
        )
    return selections


def build_publication_view(
    store: ProjectStore,
    audience: PublicationAudience | str,
    *,
    view_id: str = "",
) -> PublicationView:
    audience_enum = _normalize_audience(audience)
    state = load_publication_state(store)
    claims = list_publication_claims(store)
    explicit_view = get_publication_view(store, view_id) if view_id else next((view for view in reversed(state.views) if view.audience == audience_enum), None)
    if explicit_view is not None:
        selections = _select_claims_for_audience(
            store,
            claims,
            audience=audience_enum,
            included_object_ids=explicit_view.included_object_ids,
            excluded_object_ids=explicit_view.excluded_object_ids,
            section_mapping=explicit_view.section_mapping,
        )
        if audience_enum != PublicationAudience.internal and not any(selection.visible for selection in selections):
            explicit_view = None
        else:
            return explicit_view.model_copy(update={"selections": selections, "updated_at": utc_now()})
    selections = _select_claims_for_audience(store, claims, audience=audience_enum)
    return PublicationView(
        name=f"{audience_enum.value}_view",
        audience=audience_enum,
        scope="project",
        visibility=PublicationVisibility.paper if audience_enum == PublicationAudience.paper else PublicationVisibility.supplement,
        selections=selections,
    )


def record_citation_provenance(
    store: ProjectStore,
    theorem_id: str,
    source_reference_id: str,
    *,
    usage_type: PublicationCitationKind | str = PublicationCitationKind.project_original,
    citation_note: str = "",
) -> dict[str, Any]:
    state = load_publication_state(store)
    usage = usage_type.value if isinstance(usage_type, PublicationCitationKind) else str(usage_type)
    record = {
        "id": _new_id("citeprov"),
        "theorem_id": theorem_id,
        "source_reference_id": source_reference_id,
        "usage_type": usage,
        "citation_note": citation_note,
        "created_at": utc_now().isoformat(),
    }
    state.citation_provenance.append(record)
    _save_state_with_event(
        store,
        state,
        event_kind="publication_citation_recorded",
        message=f"recorded citation provenance for {theorem_id}",
        entity_id=theorem_id,
        payload=record,
    )
    return record


def list_citation_provenance(store: ProjectStore, *, theorem_id: str = "") -> list[dict[str, Any]]:
    records = list(load_publication_state(store).citation_provenance)
    if theorem_id:
        records = [record for record in records if record.get("theorem_id") == theorem_id]
    return records


def record_verification_summary(
    store: ProjectStore,
    scope: str,
    *,
    included_fragments: list[str] | None = None,
    summary: str = "",
    publication_visibility: PublicationVisibility | str = PublicationVisibility.supplement,
) -> PublicationVerificationSummary:
    state = load_publication_state(store)
    record = PublicationVerificationSummary(
        scope=scope,
        included_fragments=included_fragments or [],
        summary=summary,
        publication_visibility=_normalize_visibility(publication_visibility),
    )
    state.verification_summaries.append(record)
    _save_state_with_event(
        store,
        state,
        event_kind="publication_verification_summary_recorded",
        message=f"recorded verification summary for {scope}",
        entity_id=scope,
        payload=record.model_dump(mode="json"),
    )
    return record


def list_verification_summaries(store: ProjectStore, *, scope: str = "") -> list[PublicationVerificationSummary]:
    records = list(load_publication_state(store).verification_summaries)
    if scope:
        records = [record for record in records if record.scope == scope]
    return records


def record_editorial_note(
    store: ProjectStore,
    scope: str,
    content: str,
    *,
    section_label: str = "",
    updated_by: str = "human",
) -> PublicationEditorialNote:
    state = load_publication_state(store)
    note = PublicationEditorialNote(scope=scope, content=content, section_label=section_label, updated_by=updated_by)
    state.editorial_notes.append(note)
    _save_state_with_event(
        store,
        state,
        event_kind="publication_editorial_note_recorded",
        message=f"recorded editorial note for {scope}",
        entity_id=scope,
        payload=note.model_dump(mode="json"),
    )
    return note


def list_editorial_notes(store: ProjectStore, *, scope: str = "") -> list[PublicationEditorialNote]:
    records = list(load_publication_state(store).editorial_notes)
    if scope:
        records = [record for record in records if record.scope == scope]
    return records


def _selection_payload(selection: PublicationSelection) -> dict[str, Any]:
    return {
        **selection.claim.model_dump(mode="json"),
        "track": "editorial",
        "acceptance_state": selection.acceptance_state,
        "integrity_state": selection.integrity_state,
    }


def _withheld_payload(selection: PublicationSelection) -> dict[str, Any]:
    claim = selection.claim
    return {
        "object_type": claim.object_type,
        "object_id": claim.object_id,
        "display_name": claim.display_name,
        "readiness": claim.readiness.value,
        "track": "editorial",
        "acceptance_state": selection.acceptance_state,
        "integrity_state": selection.integrity_state,
        "reason": standing_problem(claim.object_type, selection.acceptance_state, selection.integrity_state),
    }


def publication_review_records(store: ProjectStore, object_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """The review records on these objects, with what counts kept apart from what doesn't (issue #30).

    - `human_review_decisions`: the counted Human Review decisions from
      `reviews.jsonl`, each one checked with `verify_decision_row`.
    - `not_counted`: a recorded decision that doesn't verify. It carries its
      recorded value as `recorded_decision`, never as a `decision`.
    - `editorial_reviews`: the generic `review_history` reviews (`proof review
      request/decide`). They are editorial: they never change acceptance, and
      their outcome is `editorial_decision`, so none reads as an approval.
    """
    from . import authority
    from .collaboration import _fold_review_history, list_review_history

    counted: list[dict[str, Any]] = []
    not_counted: list[dict[str, Any]] = []
    for row in authority.list_decisions(store):
        if row["object_id"] not in object_ids:
            continue
        base = {
            "review_id": row["review_id"],
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "kind": row["kind"],
            "reviewer_id": row["reviewer_id"],
            "rationale": row["rationale"],
            "created_at": row["created_at"],
        }
        verdict = authority.verify_decision_row(store, row["id"])
        if verdict.status == "verified":
            counted.append({**base, "decision": row["decision"], "counted": True, "track": "human_review"})
        else:
            not_counted.append({**base, "recorded_decision": row["decision"], "counted": False, "reason": verdict.reason})
    editorial = [
        {
            "review_id": record.id,
            "object_type": record.object_type,
            "object_id": record.object_id,
            "reviewer_id": record.reviewer_id,
            "editorial_decision": record.decision.value,
            "rationale": record.rationale,
            "counted": False,
            "track": "editorial",
            "created_at": record.created_at.isoformat(),
        }
        for record in _fold_review_history(list_review_history(store))
        if record.object_id in object_ids
    ]
    return {"human_review_decisions": counted, "not_counted": not_counted, "editorial_reviews": editorial}


def _bundle_payload(
    store: ProjectStore,
    *,
    audience: PublicationAudience,
    view_id: str = "",
) -> dict[str, Any]:
    from .memory import latest_handoff_snapshot, load_memory
    from .proof_state import load_state
    from .theorems import list_theorems

    state = load_state(store)
    publication_state = load_publication_state(store)
    collaboration = load_collaboration(store)
    memory = load_memory(store)
    view = build_publication_view(store, audience, view_id=view_id)
    claims = [_selection_payload(selection) for selection in view.selections if selection.visible]
    withheld_claims = [_withheld_payload(selection) for selection in view.selections if selection.withheld]
    suppressed_claim_ids = [selection.claim.object_id for selection in view.selections if not selection.visible]
    visible_claim_ids = {claim["object_id"] for claim in claims}
    references = [reference.model_dump(mode="json") for reference in list_references(store)]
    theorem_contracts = [theorem.model_dump(mode="json") for theorem in list_theorems(store) if theorem.id in visible_claim_ids]
    obligations = [obligation.model_dump(mode="json") for obligation in list_obligations(store)]
    blockers = [blocker.model_dump(mode="json") for blocker in list_blockers(store)]
    review_records = publication_review_records(store, visible_claim_ids)
    citations = [record for record in publication_state.citation_provenance if record.get("theorem_id") in visible_claim_ids]
    verification_summaries = [record.model_dump(mode="json") for record in publication_state.verification_summaries if record.scope in visible_claim_ids]
    editorial_notes = [record.model_dump(mode="json") for record in publication_state.editorial_notes if record.scope in visible_claim_ids]
    bundle_snapshots = [
        {
            "id": record.id,
            "bundle_id": record.bundle_id,
            "bundle_kind": record.bundle_kind,
            "audience": record.audience.value,
            "note": record.note,
            "created_at": record.created_at.isoformat(),
        }
        for record in publication_state.bundle_snapshots
    ]
    snapshot = read_latest_snapshot(store)
    handoff_snapshot = latest_handoff_snapshot(store)
    return {
        "project_id": state.project_id,
        "audience": audience.value,
        "view": view.model_dump(mode="json"),
        "project_state": state.model_dump(mode="json"),
        # its raw review listing is left out: `review_records` below separates what counts
        "collaboration": collaboration.model_dump(mode="json", exclude={"review_records"}),
        "memory": memory.model_dump(mode="json"),
        "claims": claims,
        "withheld_claims": withheld_claims,
        "suppressed_claim_ids": suppressed_claim_ids,
        "theorem_contracts": theorem_contracts,
        "obligations": obligations,
        "blockers": blockers,
        "references": references,
        "citation_provenance": citations,
        "verification_summaries": verification_summaries,
        "editorial_notes": editorial_notes,
        "review_records": review_records,
        "release_history": [record.model_dump(mode="json") for record in publication_state.release_history],
        "bundle_snapshots": bundle_snapshots,
        "latest_snapshot": snapshot.model_dump(mode="json") if snapshot is not None else None,
        "handoff_snapshot": handoff_snapshot.model_dump(mode="json") if handoff_snapshot is not None else None,
    }


def build_publication_paper(store: ProjectStore, *, view_id: str = "") -> dict[str, Any]:
    return _bundle_payload(store, audience=PublicationAudience.paper, view_id=view_id)


def build_publication_supplement(store: ProjectStore, *, view_id: str = "") -> dict[str, Any]:
    return _bundle_payload(store, audience=PublicationAudience.supplement, view_id=view_id)


def build_publication_bundle(store: ProjectStore, *, view_id: str = "", audience: PublicationAudience | str = PublicationAudience.paper) -> dict[str, Any]:
    audience_enum = _normalize_audience(audience)
    payload = _bundle_payload(store, audience=audience_enum, view_id=view_id)
    payload["publication_state"] = load_publication_state(store).model_dump(mode="json")
    record_publication_bundle_snapshot(
        store,
        f"{audience_enum.value}:{payload['project_id']}",
        audience_enum.value,
        payload,
        note="bundle export",
    )
    return payload


def build_publication_manifest(store: ProjectStore, *, view_id: str = "", audience: PublicationAudience | str = PublicationAudience.paper) -> dict[str, Any]:
    bundle = build_publication_bundle(store, view_id=view_id, audience=audience)
    all_claims = list_publication_claims(store)
    return {
        "project_id": bundle["project_id"],
        "audience": bundle["audience"],
        "view_id": bundle["view"]["id"],
        "claim_count": len(all_claims),
        "visible_claim_count": len(bundle["claims"]),
        "suppressed_claim_count": len(bundle["suppressed_claim_ids"]),
        "withheld_claim_count": len(bundle["withheld_claims"]),
        "withheld_claim_ids": [item["object_id"] for item in bundle["withheld_claims"]],
        "reference_count": len(bundle["references"]),
        "verification_summary_count": len(bundle["verification_summaries"]),
        "release_count": len(bundle["release_history"]),
        "bundle_snapshot_count": len(bundle["bundle_snapshots"]),
        "manifest": {
            "claims": [claim.object_id for claim in all_claims],
            "suppressed_claim_ids": list(bundle["suppressed_claim_ids"]),
            "references": [reference["id"] for reference in bundle["references"]],
        },
    }


def render_publication_bundle(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2, sort_keys=True)


def _record_release(
    store: ProjectStore,
    *,
    bundle_id: str,
    audience: PublicationAudience,
    status: PublicationReleaseStatus | str,
    approved_by: list[str] | None = None,
    withdrawn_by: list[str] | None = None,
    rationale: str = "",
    note: str = "",
) -> PublicationReleaseRecord:
    """Append an editorial release record. `approved_by` is who said so, not a Human Review decision."""
    state = load_publication_state(store)
    record = PublicationReleaseRecord(
        bundle_id=bundle_id,
        audience=audience,
        status=parse_release_status(status),
        approved_by=list(approved_by or []),
        withdrawn_by=list(withdrawn_by or []),
        rationale=rationale,
        notes=note,
    )
    state.release_history.append(record)
    _save_state_with_event(
        store,
        state,
        event_kind="publication_release_recorded",
        message=f"recorded publication release {bundle_id}",
        entity_id=bundle_id,
        payload=record.model_dump(mode="json"),
    )
    return record


def record_publication_release(
    store: ProjectStore,
    *,
    audience: PublicationAudience | str = PublicationAudience.paper,
    status: PublicationReleaseStatus | str = PublicationReleaseStatus.approved,
    approved_by: list[str] | None = None,
    rationale: str = "",
    note: str = "",
    bundle_id: str = "",
) -> PublicationReleaseRecord:
    audience_enum = parse_audience(audience)
    if not bundle_id:
        bundle_id = f"{audience_enum.value}:{load_publication_state(store).project_id}"
    return _record_release(
        store,
        bundle_id=bundle_id,
        audience=audience_enum,
        status=status,
        approved_by=approved_by,
        rationale=rationale,
        note=note,
    )


def record_release_withdrawal(
    store: ProjectStore,
    bundle_id: str,
    *,
    withdrawn_by: list[str] | None = None,
    reason: str = "",
) -> PublicationReleaseRecord:
    state = load_publication_state(store)
    audience = PublicationAudience.paper
    existing = next((record for record in reversed(state.release_history) if record.bundle_id == bundle_id), None)
    if existing is not None:
        audience = existing.audience
    return _record_release(
        store,
        bundle_id=bundle_id,
        audience=audience,
        status=PublicationReleaseStatus.withdrawn,
        approved_by=[],
        withdrawn_by=withdrawn_by,
        rationale=reason,
        note=reason,
    )


def withdraw_release(
    store: ProjectStore,
    release_or_bundle_id: str,
    *,
    withdrawn_by: list[str] | None = None,
    reason: str = "",
) -> PublicationReleaseRecord:
    """Withdraw a recorded release, named by its release id or its bundle id: an editorial record.

    Appends a `withdrawn` record for that bundle, with the release's audience.
    Refused with RELEASE_NOT_FOUND when nothing was released under that name.
    """
    history = load_publication_state(store).release_history
    release = next((record for record in reversed(history) if release_or_bundle_id in (record.id, record.bundle_id)), None)
    if release is None:
        raise ProofMapError(
            "RELEASE_NOT_FOUND", f"no release has id or bundle id {release_or_bundle_id!r}", details={"release_id": release_or_bundle_id}
        )
    return record_release_withdrawal(store, release.bundle_id, withdrawn_by=withdrawn_by, reason=reason)


def list_publication_releases(store: ProjectStore, *, audience: PublicationAudience | str = "", status: str = "") -> list[PublicationReleaseRecord]:
    releases = list(load_publication_state(store).release_history)
    if audience:
        audience_enum = _normalize_audience(audience)
        releases = [record for record in releases if record.audience == audience_enum]
    if status:
        releases = [record for record in releases if record.status.value == status]
    return releases


def list_release_records(store: ProjectStore, *, bundle_id: str = "") -> list[PublicationReleaseRecord]:
    releases = list(load_publication_state(store).release_history)
    if bundle_id:
        releases = [record for record in releases if record.bundle_id == bundle_id]
    return releases


def withdraw_publication_release(
    store: ProjectStore,
    release_id: str,
    *,
    rationale: str = "",
    approved_by: list[str] | None = None,
) -> PublicationReleaseRecord:
    state = load_publication_state(store)
    record = next((item for item in reversed(state.release_history) if item.id == release_id), None)
    if record is None:
        raise KeyError(release_id)
    record.status = PublicationReleaseStatus.withdrawn
    record.withdrawn_by = list(approved_by or [])
    record.rationale = rationale or record.rationale
    record.notes = rationale or record.notes
    record.updated_at = utc_now()
    _save_state_with_event(
        store,
        state,
        event_kind="publication_release_withdrawn",
        message=f"withdrew publication release {release_id}",
        entity_id=release_id,
        payload=record.model_dump(mode="json"),
    )
    return record


def record_publication_bundle_snapshot(
    store: ProjectStore,
    bundle_or_audience: PublicationAudience | str,
    bundle_kind: str = "",
    bundle_data: dict[str, Any] | None = None,
    *,
    note: str = "",
) -> PublicationBundleSnapshot:
    state = load_publication_state(store)
    if isinstance(bundle_or_audience, PublicationAudience) or (isinstance(bundle_or_audience, str) and bundle_or_audience in PublicationAudience.__members__.keys()):
        audience = _normalize_audience(bundle_or_audience)
        payload = build_publication_bundle(store, audience=audience)
        snapshot = PublicationBundleSnapshot(
            bundle_id=f"{audience.value}:{state.project_id}",
            bundle_kind=audience.value,
            audience=audience,
            note=note,
            data=payload,
        )
    else:
        audience = PublicationAudience.paper
        snapshot = PublicationBundleSnapshot(
            bundle_id=str(bundle_or_audience),
            bundle_kind=bundle_kind or "bundle",
            audience=audience,
            note=note,
            data=bundle_data or {},
        )
    state.bundle_snapshots.append(snapshot)
    _save_state_with_event(
        store,
        state,
        event_kind="publication_bundle_snapshot_recorded",
        message=f"recorded publication bundle snapshot {snapshot.bundle_id}",
        entity_id=snapshot.bundle_id,
        payload=snapshot.model_dump(mode="json"),
    )
    store_publication_bundle_snapshot(store, snapshot.id, state.project_id, snapshot.model_dump_json(), created_at=snapshot.created_at)
    return snapshot


def list_publication_bundle_snapshots(store: ProjectStore, *, bundle_id: str = "") -> list[PublicationBundleSnapshot]:
    snapshots = list(load_publication_state(store).bundle_snapshots)
    if bundle_id:
        snapshots = [snapshot for snapshot in snapshots if snapshot.bundle_id == bundle_id]
    return snapshots


def summarize_publication_claim(claim: PublicationClaim, theorem: TheoremContract | None = None) -> str:
    name = claim.display_name or claim.title or claim.object_id
    theorem_text = f" theorem={theorem.name}" if theorem is not None else ""
    section = f" section={claim.section_placement}" if claim.section_placement else ""
    return f"{claim.object_type}/{claim.object_id}: {name} [{claim.readiness.value}/{claim.visibility.value} · editorial]{section}{theorem_text}"


def summarize_claim_with_axes(store: ProjectStore, claim: PublicationClaim) -> str:
    """One claim's line: its editorial readiness, then its node's live acceptance and integrity."""
    acceptance_state, integrity_state = node_acceptance_and_integrity(store, claim.object_type, claim.object_id)
    return f"{summarize_publication_claim(claim)} {_axes_text(acceptance_state, integrity_state)}"


def summarize_publication_view(view: PublicationView) -> str:
    visible = sum(1 for selection in view.selections if selection.visible)
    total = len(view.selections)
    included = ",".join(view.included_object_ids) or "none"
    return f"{view.id}: {view.name} [{view.audience.value}/{view.visibility.value}] visible={visible}/{total} included={included}"


def summarize_publication_state(record: PublicationStateRecord) -> str:
    return summarize_publication_claim(record)


def summarize_publication_release(record: PublicationReleaseRecord) -> str:
    approvers = ",".join(record.approved_by) or "none"
    withdrawn = ",".join(record.withdrawn_by) or "none"
    return (
        f"{record.bundle_id}: {record.status.value} [{record.audience.value} · editorial] "
        f"approved_by={approvers} withdrawn_by={withdrawn}"
    )


def summarize_publication_editorial_note(note: PublicationEditorialNote) -> str:
    section = f" section={note.section_label}" if note.section_label else ""
    return f"{note.scope}:{section} {note.content}"


def summarize_publication_citation(record: dict[str, Any]) -> str:
    return f"{record.get('theorem_id', '')} <- {record.get('source_reference_id', '')} [{record.get('usage_type', '')}]"


def summarize_publication_verification(record: PublicationVerificationSummary) -> str:
    fragments = ",".join(record.included_fragments) or "none"
    return f"{record.scope}: {record.summary} fragments={fragments} [{record.publication_visibility.value}]"


def summarize_publication_bundle_snapshot(snapshot: PublicationBundleSnapshot) -> str:
    return f"{snapshot.bundle_id}: {snapshot.bundle_kind} [{snapshot.audience.value}] note={snapshot.note or 'none'}"


def render_publication_summary(view: PublicationView, *, store: ProjectStore | None = None, include_context: bool = True) -> str:
    lines = [
        f"Publication view: {view.name} ({view.audience.value})",
        f"View id: {view.id}",
        f"Visible claims: {sum(1 for selection in view.selections if selection.visible)} / {len(view.selections)}",
    ]
    if include_context and store is not None:
        state = load_publication_state(store)
        lines.append(f"Publication claims: {len(state.claims)}")
        lines.append(f"Release history: {len(state.release_history)}")
        lines.append(f"Bundle snapshots: {len(state.bundle_snapshots)}")
    lines.append("Selections:")
    if view.selections:
        for selection in view.selections:
            status = "visible" if selection.visible else "hidden"
            reason = f" ({selection.reason})" if selection.reason else ""
            section = f" section={selection.section_label}" if selection.section_label else ""
            lines.append(
                f"- {selection.claim.object_type}/{selection.claim.object_id}: "
                f"{selection.claim.display_name or selection.claim.title or selection.claim.object_id} "
                f"[{selection.claim.readiness.value} · editorial] "
                f"{_axes_text(selection.acceptance_state, selection.integrity_state)}{section} {status}{reason}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines)


def publication_view_json(store: ProjectStore, audience: PublicationAudience | str = PublicationAudience.paper, *, view_id: str = "") -> str:
    return build_publication_view(store, audience, view_id=view_id).model_dump_json(indent=2)


def publication_summary_json(store: ProjectStore, audience: PublicationAudience | str = PublicationAudience.paper, *, view_id: str = "") -> str:
    bundle = build_publication_bundle(store, audience=audience, view_id=view_id)
    return json.dumps(
        {
            "project_id": bundle["project_id"],
            "audience": bundle["audience"],
            "view_id": bundle["view"]["id"],
            "claim_count": len(bundle["claims"]),
            "suppressed_claim_count": len(bundle["suppressed_claim_ids"]),
            "verification_summary_count": len(bundle["verification_summaries"]),
            "release_count": len(bundle["release_history"]),
        },
        indent=2,
        sort_keys=True,
    )


def publication_claim_json(store: ProjectStore, object_id: str, *, object_type: str = "proof_map_node") -> str:
    claim = get_publication_claim(store, object_id, object_type=object_type)
    return claim.model_dump_json(indent=2) if claim is not None else json.dumps({"error": f"publication claim not found: {object_type}/{object_id}"}, indent=2)


def _claim_line(selection: PublicationSelection) -> str:
    claim = selection.claim
    return (
        f"- {claim.object_id}: {claim.display_name or claim.title or claim.object_id} "
        f"[{claim.readiness.value} · editorial] {_axes_text(selection.acceptance_state, selection.integrity_state)} "
        f"section={selection.section_label or claim.section_placement or 'unspecified'}"
    )


def _withheld_lines(view: PublicationView) -> list[str]:
    lines = ["", "Withheld (marked ready, but not accepted · current):"]
    withheld = [selection for selection in view.selections if selection.withheld]
    if withheld:
        for selection in withheld:
            claim = selection.claim
            lines.append(
                f"- {claim.object_id} [{claim.readiness.value} · editorial] "
                f"{_axes_text(selection.acceptance_state, selection.integrity_state)}: WITHHELD, "
                f"{standing_problem(claim.object_type, selection.acceptance_state, selection.integrity_state)}"
            )
    else:
        lines.append("- none")
    return lines


def _export_header(title: str, bundle: dict[str, Any], view: PublicationView) -> list[str]:
    return [
        title,
        f"Project: {bundle['project_id']}",
        f"Audience: {bundle['audience']}",
        f"View: {view.name} ({view.id})",
        "Readiness is editorial, not a Human Review decision; acceptance and integrity are the node's own, read live.",
        "",
        "Claims:",
    ]


def _visible_lines(view: PublicationView) -> list[str]:
    visible = [selection for selection in view.selections if selection.visible]
    return [_claim_line(selection) for selection in visible] or ["- none"]


def _suppressed_lines(view: PublicationView) -> list[str]:
    suppressed = [selection.claim.object_id for selection in view.selections if not selection.visible and not selection.withheld]
    return ["", "Suppressed claims:", *([f"- {claim_id}" for claim_id in suppressed] or ["- none"])]


def publication_export_data(store: ProjectStore, audience: PublicationAudience | str, *, view_id: str = "") -> dict[str, Any]:
    """What a paper or supplement export contains, for `--json`: the claims shown, the ones withheld, and why."""
    audience_enum = parse_audience(audience)
    bundle = _bundle_payload(store, audience=audience_enum, view_id=view_id)
    return {
        "project_id": bundle["project_id"],
        "audience": bundle["audience"],
        "view_id": bundle["view"]["id"],
        "claims": bundle["claims"],
        "withheld_claims": bundle["withheld_claims"],
        "suppressed_claim_ids": bundle["suppressed_claim_ids"],
        "citation_provenance": bundle["citation_provenance"],
        "verification_summaries": bundle["verification_summaries"],
        "review_records": bundle["review_records"],
    }


def publication_paper_export(store: ProjectStore, *, view_id: str = "") -> str:
    bundle = build_publication_paper(store, view_id=view_id)
    view = build_publication_view(store, PublicationAudience.paper, view_id=view_id)
    lines = _export_header("# Publication Draft", bundle, view)
    lines.extend(_visible_lines(view))
    lines.extend(_withheld_lines(view))
    lines.extend(_suppressed_lines(view))
    lines.extend(["", "Citations:"])
    if bundle["citation_provenance"]:
        for citation in bundle["citation_provenance"]:
            lines.append(f"- {citation['theorem_id']} <- {citation['source_reference_id']} [{citation['usage_type']}]")
    else:
        lines.append("- none")
    return "\n".join(lines)


def publication_supplement_export(store: ProjectStore, *, view_id: str = "") -> str:
    bundle = build_publication_supplement(store, view_id=view_id)
    view = build_publication_view(store, PublicationAudience.supplement, view_id=view_id)
    lines = _export_header("# Technical Supplement", bundle, view)
    lines.extend(_visible_lines(view))
    lines.extend(_withheld_lines(view))
    records = bundle["review_records"]
    lines.extend(["", "Human Review decisions (counted):"])
    lines.extend(
        [f"- {row['object_type']}/{row['object_id']}: {row['kind']} {row['decision']} by {row['reviewer_id']}" for row in records["human_review_decisions"]]
        or ["- none"]
    )
    if records["not_counted"]:
        lines.extend(["", "Recorded decisions that don't count:"])
        lines.extend(
            f"- {row['object_type']}/{row['object_id']}: {row['kind']}, not counted ({row['reason']})" for row in records["not_counted"]
        )
    lines.extend(["", "Editorial reviews (not Human Review; they don't change acceptance):"])
    lines.extend(
        [
            f"- {row['object_type']}/{row['object_id']}: editorial {row['editorial_decision']} by {row['reviewer_id']}"
            for row in records["editorial_reviews"]
        ]
        or ["- none"]
    )
    lines.extend(["", "Verification summaries:"])
    if bundle["verification_summaries"]:
        for summary in bundle["verification_summaries"]:
            lines.append(f"- {summary['scope']}: {summary['summary']} [{summary['publication_visibility']}]")
    else:
        lines.append("- none")
    lines.extend(_suppressed_lines(view))
    return "\n".join(lines)


def publication_bundle_export(store: ProjectStore, *, audience: PublicationAudience | str = PublicationAudience.paper, view_id: str = "") -> str:
    return render_publication_bundle(build_publication_bundle(store, audience=audience, view_id=view_id))


def publication_manifest_export(store: ProjectStore, *, audience: PublicationAudience | str = PublicationAudience.paper, view_id: str = "") -> str:
    return json.dumps(build_publication_manifest(store, audience=audience, view_id=view_id), indent=2, sort_keys=True)


def record_release_history_snapshot(store: ProjectStore, *, audience: PublicationAudience | str = PublicationAudience.paper, note: str = "") -> PublicationBundleSnapshot:
    return record_publication_bundle_snapshot(store, _normalize_audience(audience), note=note)


def _load_snapshot_value(value: Any) -> Any | None:
    from .memory import HandoffSnapshot

    if value is None:
        return None
    if isinstance(value, HandoffSnapshot):
        return value
    return HandoffSnapshot.model_validate(value)


def read_snapshot(store: ProjectStore) -> ProjectSnapshot | None:
    return read_latest_snapshot(store)


def read_handoff_snapshot(store: ProjectStore) -> Any | None:
    from .memory import latest_handoff_snapshot

    return _load_snapshot_value(latest_handoff_snapshot(store))


def record_release_approval(
    store: ProjectStore,
    bundle_id: str,
    *,
    approved_by: list[str] | None = None,
    notes: str = "",
    status: PublicationReleaseStatus | str = PublicationReleaseStatus.approved,
    audience: PublicationAudience | str = PublicationAudience.paper,
) -> PublicationReleaseRecord:
    return _record_release(
        store,
        bundle_id=bundle_id,
        audience=parse_audience(audience),
        status=status,
        approved_by=approved_by,
        rationale=notes,
        note=notes,
    )


def build_publication_paper_view(store: ProjectStore, *, view_id: str = "") -> PublicationView:
    return build_publication_view(store, PublicationAudience.paper, view_id=view_id)


def build_publication_supplement_view(store: ProjectStore, *, view_id: str = "") -> PublicationView:
    return build_publication_view(store, PublicationAudience.supplement, view_id=view_id)

__all__ = [
    "PublicationAudience",
    "PublicationBundleSnapshot",
    "PublicationClaim",
    "PublicationCitationKind",
    "PublicationEditorialNote",
    "PublicationReadiness",
    "PublicationReleaseRecord",
    "PublicationReleaseStatus",
    "PublicationSelection",
    "PublicationState",
    "PublicationStateRecord",
    "PublicationVerificationSummary",
    "PublicationView",
    "PublicationVisibility",
    "build_publication_bundle",
    "build_publication_manifest",
    "build_publication_paper",
    "build_publication_paper_view",
    "build_publication_supplement",
    "build_publication_supplement_view",
    "build_publication_view",
    "create_publication_view",
    "get_publication_claim",
    "get_publication_view",
    "list_citation_provenance",
    "list_editorial_notes",
    "list_publication_bundle_snapshots",
    "list_publication_claims",
    "list_publication_releases",
    "list_publication_views",
    "list_release_records",
    "list_verification_summaries",
    "load_publication_state",
    "publication_bundle_export",
    "publication_claim_json",
    "publication_manifest_export",
    "publication_paper_export",
    "publication_summary_json",
    "publication_supplement_export",
    "publication_view_json",
    "read_handoff_snapshot",
    "read_snapshot",
    "record_citation_provenance",
    "record_editorial_note",
    "record_publication_bundle_snapshot",
    "record_publication_release",
    "record_release_approval",
    "record_release_history_snapshot",
    "record_release_withdrawal",
    "record_verification_summary",
    "render_publication_bundle",
    "render_publication_summary",
    "save_publication_state",
    "set_publication_claim",
    "set_publication_readiness",
    "summarize_publication_bundle_snapshot",
    "summarize_publication_claim",
    "summarize_publication_citation",
    "summarize_publication_editorial_note",
    "summarize_publication_release",
    "summarize_publication_state",
    "summarize_publication_verification",
    "summarize_publication_view",
    "withdraw_publication_release",
    "withdraw_release",
    "ALLOWED_TRANSITIONS",
    "READY_STATES",
    "LEGACY_READINESS",
    "EDITORIAL_LABEL",
    "claim_payload",
    "check_readiness_write",
    "node_acceptance_and_integrity",
    "parse_audience",
    "parse_readiness",
    "publication_export_data",
    "publication_review_records",
    "standing_problem",
    "summarize_claim_with_axes",
]
