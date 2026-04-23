from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_serializer

from .collaboration import CollaborationState, list_review_records, load_collaboration
from .domain import ProjectSnapshot, TheoremContract, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, utc_now
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
    internal_draft = "internal_draft"
    collaborator_ready = "collaborator_ready"
    supplement_ready = "supplement_ready"
    paper_ready = "paper_ready"
    disputed = "disputed"
    blocked = "blocked"
    withdrawn = "withdrawn"
    superseded = "superseded"


PublicationState = PublicationReadiness


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
    release_status: PublicationReleaseStatus = PublicationReleaseStatus.approved
    release_notes: str = ""
    updated_by: str = "human"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

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


def _normalize_readiness(value: PublicationReadiness | str) -> PublicationReadiness:
    return value if isinstance(value, PublicationReadiness) else PublicationReadiness(value)


def _normalize_visibility(value: PublicationVisibility | str | None) -> PublicationVisibility:
    if value is None:
        return PublicationVisibility.internal_only
    return value if isinstance(value, PublicationVisibility) else PublicationVisibility(value)


def _claim_visibility(claim: PublicationClaim) -> PublicationVisibility:
    if claim.internal_only:
        return PublicationVisibility.internal_only
    if claim.readiness == PublicationReadiness.paper_ready:
        return PublicationVisibility.paper
    if claim.readiness in {
        PublicationReadiness.supplement_ready,
        PublicationReadiness.collaborator_ready,
    }:
        return PublicationVisibility.supplement
    return PublicationVisibility.internal_only


def _derived_readiness(theorem: TheoremContract) -> PublicationReadiness:
    if theorem.status in {TheoremStatus.blocked, TheoremStatus.failed}:
        return PublicationReadiness.blocked
    if theorem.review_state == TheoremReviewState.superseded:
        return PublicationReadiness.superseded
    if theorem.review_state == TheoremReviewState.rejected:
        return PublicationReadiness.disputed
    if theorem.review_state == TheoremReviewState.approved and theorem.provenance_kind == TheoremProvenanceKind.imported:
        return PublicationReadiness.supplement_ready
    if theorem.review_state == TheoremReviewState.approved:
        return PublicationReadiness.paper_ready
    if theorem.review_state == TheoremReviewState.candidate:
        return PublicationReadiness.collaborator_ready
    return PublicationReadiness.internal_draft


def _claim_from_theorem(theorem: TheoremContract) -> PublicationClaim:
    return PublicationClaim(
        object_type="theorem_contract",
        object_id=theorem.id,
        display_name=theorem.name,
        title=theorem.statement,
        section_placement="",
        readiness=_derived_readiness(theorem),
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
    claims.sort(key=_claim_sort_key)
    return claims


def set_publication_claim(
    store: ProjectStore,
    object_id: str,
    *,
    object_type: str = "theorem_contract",
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
    release_status: PublicationReleaseStatus | str = PublicationReleaseStatus.approved,
    release_notes: str = "",
    updated_by: str = "human",
) -> PublicationClaim:
    state = load_publication_state(store)
    claim = next((item for item in state.claims if item.object_type == object_type and item.object_id == object_id), None)
    if claim is None:
        claim = PublicationClaim(object_type=object_type, object_id=object_id)
        state.claims.append(claim)
    if not display_name:
        display_name = claim.display_name
    if not title:
        title = claim.title
    claim.display_name = display_name
    claim.title = title
    claim.section_placement = section_placement or claim.section_placement
    claim.readiness = _normalize_readiness(readiness)
    claim.internal_only = internal_only
    claim.citation_kind = citation_kind if isinstance(citation_kind, PublicationCitationKind) or citation_kind is None else PublicationCitationKind(citation_kind)
    if claim.citation_kind is None:
        claim.citation_kind = PublicationCitationKind.project_original
    if editorial_notes is not None:
        claim.editorial_notes = list(editorial_notes)
    if supporting_reference_ids is not None:
        claim.supporting_reference_ids = list(supporting_reference_ids)
    if supporting_theorem_ids is not None:
        claim.supporting_theorem_ids = list(supporting_theorem_ids)
    claim.release_status = release_status if isinstance(release_status, PublicationReleaseStatus) else PublicationReleaseStatus(release_status)
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
    object_type: str = "theorem_contract",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    reason: str = "",
    citation_kind: PublicationCitationKind | str | None = None,
    internal_only: bool = False,
    editorial_notes: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    supporting_theorem_ids: list[str] | None = None,
    release_status: PublicationReleaseStatus | str = PublicationReleaseStatus.approved,
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
    object_type: str = "theorem_contract",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    reason: str = "",
    citation_kind: PublicationCitationKind | str | None = None,
    internal_only: bool = False,
    editorial_notes: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    supporting_theorem_ids: list[str] | None = None,
    release_status: PublicationReleaseStatus | str = PublicationReleaseStatus.approved,
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


def get_publication_claim(store: ProjectStore, object_id: str, *, object_type: str = "theorem_contract") -> PublicationClaim | None:
    from .theorems import list_theorems

    state = load_publication_state(store)
    for claim in reversed(state.claims):
        if claim.object_type == object_type and claim.object_id == object_id:
            return claim
    if object_type == "theorem_contract":
        theorem = next((item for item in list_theorems(store) if item.id == object_id), None)
        if theorem is not None:
            return _claim_from_theorem(theorem)
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
        if claim.readiness in {PublicationReadiness.blocked, PublicationReadiness.disputed} and audience != PublicationAudience.internal:
            visible = False
            reasons.append(f"readiness={claim.readiness.value}")
        if audience == PublicationAudience.paper:
            if claim.readiness != PublicationReadiness.paper_ready:
                visible = False
                reasons.append("not paper ready")
        elif audience == PublicationAudience.supplement:
            if claim.readiness not in {
                PublicationReadiness.paper_ready,
                PublicationReadiness.supplement_ready,
                PublicationReadiness.collaborator_ready,
            }:
                visible = False
                reasons.append("not supplement ready")
        section_label = (section_mapping or {}).get(claim.object_id, claim.section_placement)
        selections.append(
            PublicationSelection(
                claim=claim,
                visible=visible,
                reason="; ".join(dict.fromkeys(reasons)),
                section_label=section_label,
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
    selections = _select_claims_for_audience(claims, audience=audience_enum)
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
    claims = [selection.claim.model_dump(mode="json") for selection in view.selections if selection.visible]
    suppressed_claim_ids = [selection.claim.object_id for selection in view.selections if not selection.visible]
    visible_claim_ids = {claim["object_id"] for claim in claims}
    references = [reference.model_dump(mode="json") for reference in list_references(store)]
    theorem_contracts = [theorem.model_dump(mode="json") for theorem in list_theorems(store) if theorem.id in visible_claim_ids]
    obligations = [obligation.model_dump(mode="json") for obligation in list_obligations(store)]
    blockers = [blocker.model_dump(mode="json") for blocker in list_blockers(store)]
    review_records = [record.model_dump(mode="json") for record in list_review_records(store) if record.object_id in visible_claim_ids]
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
        "collaboration": collaboration.model_dump(mode="json"),
        "memory": memory.model_dump(mode="json"),
        "claims": claims,
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


def publication_paper_export(store: ProjectStore, *, view_id: str = "") -> str:
    bundle = build_publication_paper(store, view_id=view_id)
    lines = [
        "# Publication Draft",
        f"Project: {bundle['project_id']}",
        f"Audience: {bundle['audience']}",
        f"View: {bundle['view']['name']} ({bundle['view']['id']})",
        "",
        "Claims:",
    ]
    if bundle["claims"]:
        for claim in bundle["claims"]:
            lines.append(
                f"- {claim['object_id']}: {claim['display_name'] or claim['title']} "
                f"[{claim['readiness']}] section={claim['section_placement'] or 'unspecified'}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Citations:",
        ]
    )
    if bundle["citation_provenance"]:
        for citation in bundle["citation_provenance"]:
            lines.append(
                f"- {citation['theorem_id']} <- {citation['source_reference_id']} [{citation['usage_type']}]"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Verification summaries:",
        ]
    )
    if bundle["verification_summaries"]:
        for summary in bundle["verification_summaries"]:
            lines.append(
                f"- {summary['scope']}: {summary['summary']} [{summary['publication_visibility']}]"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Editorial notes:",
        ]
    )
    if bundle["editorial_notes"]:
        for note in bundle["editorial_notes"]:
            lines.append(f"- {note['scope']}: {note['content']}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Suppressed claims:",
        ]
    )
    if bundle["suppressed_claim_ids"]:
        lines.extend(f"- {claim_id}" for claim_id in bundle["suppressed_claim_ids"])
    else:
        lines.append("- none")
    return "\n".join(lines)


def publication_supplement_export(store: ProjectStore, *, view_id: str = "") -> str:
    bundle = build_publication_supplement(store, view_id=view_id)
    lines = [
        "# Technical Supplement",
        f"Project: {bundle['project_id']}",
        f"Audience: {bundle['audience']}",
        "",
        "Claims:",
    ]
    if bundle["claims"]:
        for claim in bundle["claims"]:
            lines.append(
                f"- {claim['object_id']}: {claim['display_name'] or claim['title']} "
                f"[{claim['readiness']}] section={claim['section_placement'] or 'unspecified'}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Review history:",
        ]
    )
    if bundle["review_records"]:
        for record in bundle["review_records"]:
            lines.append(
                f"- {record['object_type']}/{record['object_id']}: {record['decision']} by {record['reviewer_id']}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Verification summaries:",
        ]
    )
    if bundle["verification_summaries"]:
        for summary in bundle["verification_summaries"]:
            lines.append(
                f"- {summary['scope']}: {summary['summary']} [{summary['publication_visibility']}]"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Internal exclusions:",
        ]
    )
    if bundle["suppressed_claim_ids"]:
        lines.extend(f"- {claim_id}" for claim_id in bundle["suppressed_claim_ids"])
    else:
        lines.append("- none")
    return "\n".join(lines)


def publication_bundle_export(store: ProjectStore, *, audience: PublicationAudience | str = PublicationAudience.paper, view_id: str = "") -> str:
    return render_publication_bundle(build_publication_bundle(store, audience=audience, view_id=view_id))


def publication_manifest_export(store: ProjectStore, *, audience: PublicationAudience | str = PublicationAudience.paper, view_id: str = "") -> str:
    return json.dumps(build_publication_manifest(store, audience=audience, view_id=view_id), indent=2, sort_keys=True)


def publication_view_json(store: ProjectStore, audience: PublicationAudience | str = PublicationAudience.paper, *, view_id: str = "") -> str:
    return build_publication_view(store, audience, view_id=view_id).model_dump_json(indent=2)


def publication_summary_json(store: ProjectStore, audience: PublicationAudience | str = PublicationAudience.paper, *, view_id: str = "") -> str:
    bundle = build_publication_bundle(store, audience=audience, view_id=view_id)
    summary = {
        "project_id": bundle["project_id"],
        "audience": bundle["audience"],
        "view": bundle["view"],
        "claim_count": len(bundle["claims"]),
        "suppressed_claim_count": len(bundle["suppressed_claim_ids"]),
        "verification_summary_count": len(bundle["verification_summaries"]),
        "release_count": len(bundle["release_history"]),
    }
    return json.dumps(summary, indent=2, sort_keys=True)


def publication_claim_json(store: ProjectStore, object_id: str, *, object_type: str = "theorem_contract") -> str:
    claim = get_publication_claim(store, object_id, object_type=object_type)
    return claim.model_dump_json(indent=2) if claim is not None else json.dumps({"error": f"publication claim not found: {object_type}/{object_id}"}, indent=2)


def _record_release(
    store: ProjectStore,
    *,
    bundle_id: str,
    audience: PublicationAudience,
    status: PublicationReleaseStatus | str,
    approved_by: list[str] | None = None,
    rationale: str = "",
    note: str = "",
) -> PublicationReleaseRecord:
    state = load_publication_state(store)
    record = PublicationReleaseRecord(
        bundle_id=bundle_id,
        audience=audience,
        status=status if isinstance(status, PublicationReleaseStatus) else PublicationReleaseStatus(status),
        approved_by=list(approved_by or []),
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
    audience_enum = _normalize_audience(audience)
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


def record_release_approval(
    store: ProjectStore,
    bundle_id: str,
    *,
    approved_by: list[str] | None = None,
    notes: str = "",
    status: PublicationReleaseStatus | str = PublicationReleaseStatus.approved,
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
        status=status,
        approved_by=approved_by,
        rationale=notes,
        note=notes,
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
        rationale=reason,
        note=reason,
    )


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
    return f"{claim.object_type}/{claim.object_id}: {name} [{claim.readiness.value}/{claim.visibility.value}]{section}{theorem_text}"


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
    return f"{record.bundle_id}: {record.status.value} [{record.audience.value}] approved_by={approvers} withdrawn_by={withdrawn}"


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
                f"[{selection.claim.readiness.value}]{section} {status}{reason}"
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


def publication_claim_json(store: ProjectStore, object_id: str, *, object_type: str = "theorem_contract") -> str:
    claim = get_publication_claim(store, object_id, object_type=object_type)
    return claim.model_dump_json(indent=2) if claim is not None else json.dumps({"error": f"publication claim not found: {object_type}/{object_id}"}, indent=2)


def publication_paper_export(store: ProjectStore, *, view_id: str = "") -> str:
    bundle = build_publication_paper(store, view_id=view_id)
    view = build_publication_view(store, PublicationAudience.paper, view_id=view_id)
    lines = [
        "# Publication Draft",
        f"Project: {bundle['project_id']}",
        f"Audience: {bundle['audience']}",
        f"View: {view.name} ({view.id})",
        "",
        "Claims:",
    ]
    visible = [selection.claim for selection in view.selections if selection.visible]
    if visible:
        for claim in visible:
            lines.append(
                f"- {claim.object_id}: {claim.display_name or claim.title or claim.object_id} "
                f"[{claim.readiness.value}] section={claim.section_placement or 'unspecified'}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Suppressed claims:",
        ]
    )
    suppressed = [selection.claim.object_id for selection in view.selections if not selection.visible]
    if suppressed:
        lines.extend(f"- {claim_id}" for claim_id in suppressed)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Citations:",
        ]
    )
    if bundle["citation_provenance"]:
        for citation in bundle["citation_provenance"]:
            lines.append(
                f"- {citation['theorem_id']} <- {citation['source_reference_id']} [{citation['usage_type']}]"
            )
    else:
        lines.append("- none")
    return "\n".join(lines)


def publication_supplement_export(store: ProjectStore, *, view_id: str = "") -> str:
    bundle = build_publication_supplement(store, view_id=view_id)
    view = build_publication_view(store, PublicationAudience.supplement, view_id=view_id)
    lines = [
        "# Technical Supplement",
        f"Project: {bundle['project_id']}",
        f"Audience: {bundle['audience']}",
        f"View: {view.name} ({view.id})",
        "",
        "Claims:",
    ]
    visible = [selection.claim for selection in view.selections if selection.visible]
    if visible:
        for claim in visible:
            lines.append(
                f"- {claim.object_id}: {claim.display_name or claim.title or claim.object_id} "
                f"[{claim.readiness.value}] section={claim.section_placement or 'unspecified'}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Review history:",
        ]
    )
    if bundle["review_records"]:
        for record in bundle["review_records"]:
            lines.append(
                f"- {record['object_type']}/{record['object_id']}: {record['decision']} by {record['reviewer_id']}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Verification summaries:",
        ]
    )
    if bundle["verification_summaries"]:
        for summary in bundle["verification_summaries"]:
            lines.append(f"- {summary['scope']}: {summary['summary']} [{summary['publication_visibility']}]")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Suppressed claims:",
        ]
    )
    suppressed = [selection.claim.object_id for selection in view.selections if not selection.visible]
    if suppressed:
        lines.extend(f"- {claim_id}" for claim_id in suppressed)
    else:
        lines.append("- none")
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
) -> PublicationReleaseRecord:
    return _record_release(
        store,
        bundle_id=bundle_id,
        audience=PublicationAudience.paper,
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
]
