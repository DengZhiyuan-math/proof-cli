from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    TheoremContract,
    TheoremProvenanceKind,
    TheoremReviewState,
    TheoremStatus,
    TrustLevel,
    utc_now,
)
from .proof_state import load_state, note_unresolved_trust_call, record_theorem_usage
from .storage import ProjectStore, append_event, get_contract, list_contracts, store_contract


def add_theorem(
    store: ProjectStore,
    *,
    theorem_id: str,
    kind: str,
    name: str,
    statement: str,
    assumptions: list[str] | None = None,
    exports: list[str] | None = None,
    status: TheoremStatus = TheoremStatus.draft,
    trust_level: TrustLevel = TrustLevel.temporary_admit,
    provenance_kind: TheoremProvenanceKind = TheoremProvenanceKind.local,
    review_state: TheoremReviewState = TheoremReviewState.draft,
    dependencies: list[str] | None = None,
    source_ref: str = "internal/project",
    grounded_reference_ids: list[str] | None = None,
    grounded_theorem_ids: list[str] | None = None,
    local_usage_notes: list[str] | None = None,
    imported_usage_notes: list[str] | None = None,
    notes: str = "",
    supersedes_version: int | None = None,
) -> TheoremContract:
    if provenance_kind == TheoremProvenanceKind.imported and review_state == TheoremReviewState.draft:
        review_state = TheoremReviewState.candidate
    contract = TheoremContract(
        id=theorem_id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        statement=statement,
        assumptions=assumptions or [],
        exports=exports or [],
        status=status,
        trust_level=trust_level,
        provenance_kind=provenance_kind,
        review_state=review_state,
        dependencies=dependencies or [],
        source_ref=source_ref,
        grounded_reference_ids=grounded_reference_ids or [],
        grounded_theorem_ids=grounded_theorem_ids or [],
        local_usage_notes=local_usage_notes or [],
        imported_usage_notes=imported_usage_notes or [],
        supersedes_version=supersedes_version,
        notes=notes,
    )
    store_contract(store, contract)
    append_event(store, "theorem_added", f"added theorem {theorem_id}", entity_id=theorem_id, payload=contract.model_dump(mode="json"))
    return contract


def update_theorem(store: ProjectStore, theorem_id: str, **changes) -> TheoremContract:
    contract = get_contract(store, theorem_id)
    if contract is None:
        raise KeyError(theorem_id)
    update_data = dict(changes)
    for field_name in (
        "grounded_reference_ids",
        "grounded_theorem_ids",
        "local_usage_notes",
        "imported_usage_notes",
    ):
        if field_name in update_data and update_data[field_name] is not None:
            existing_values = list(getattr(contract, field_name))
            incoming_values = list(update_data[field_name])
            update_data[field_name] = existing_values + [value for value in incoming_values if value not in existing_values]
    update_data.setdefault("supersedes_version", contract.version)
    update_data.setdefault("updated_at", utc_now())
    updated = contract.model_copy(update=update_data)
    store_contract(store, updated)
    append_event(store, "theorem_updated", f"updated theorem {theorem_id}", entity_id=theorem_id, payload=updated.model_dump(mode="json"))
    return updated


def add_usage_note(
    store: ProjectStore,
    theorem_id: str,
    note: str,
    *,
    provenance_kind: TheoremProvenanceKind = TheoremProvenanceKind.local,
) -> TheoremContract:
    contract = get_contract(store, theorem_id)
    if contract is None:
        raise KeyError(theorem_id)
    field_name = "local_usage_notes" if provenance_kind == TheoremProvenanceKind.local else "imported_usage_notes"
    notes = list(getattr(contract, field_name))
    notes.append(note)
    updated = update_theorem(store, theorem_id, **{field_name: notes})
    append_event(
        store,
        "theorem_usage_note_added",
        f"added {provenance_kind.value} usage note for {theorem_id}",
        entity_id=theorem_id,
        payload={
            "provenance_kind": provenance_kind.value,
            "note": note,
            "field_name": field_name,
        },
    )
    if contract.provenance_kind != provenance_kind:
        append_event(
            store,
            "theorem_usage_note_mismatch",
            f"{provenance_kind.value} usage note recorded for {theorem_id} with {contract.provenance_kind.value} provenance",
            entity_id=theorem_id,
            payload={
                "provenance_kind": provenance_kind.value,
                "contract_provenance_kind": contract.provenance_kind.value,
            },
        )
    return updated


def show_theorem(store: ProjectStore, theorem_id: str) -> TheoremContract | None:
    return get_contract(store, theorem_id)


def list_theorems(store: ProjectStore) -> list[TheoremContract]:
    return list_contracts(store)


def theorem_callability(store: ProjectStore, theorem_id: str) -> tuple[bool, str]:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return False, f"theorem {theorem_id} not found"
    state = load_state(store)
    if contract.status in {TheoremStatus.blocked, TheoremStatus.failed}:
        return False, f"theorem {theorem_id} is {contract.status.value}"
    if contract.review_state == TheoremReviewState.rejected:
        return False, f"theorem {theorem_id} is rejected"
    if contract.review_state == TheoremReviewState.superseded:
        return False, f"theorem {theorem_id} has been superseded"
    if contract.provenance_kind == TheoremProvenanceKind.imported and contract.review_state != TheoremReviewState.approved:
        return False, f"imported theorem {theorem_id} is not approved"
    if contract.trust_level == TrustLevel.temporary_admit:
        return False, f"theorem {theorem_id} is not trust-approved"
    missing = [assumption for assumption in contract.assumptions if assumption not in state.current_context]
    if missing:
        return False, f"missing assumptions: {', '.join(missing)}"
    return True, "callable"


def apply_theorem(store: ProjectStore, theorem_id: str) -> tuple[bool, str]:
    ok, reason = theorem_callability(store, theorem_id)
    if not ok:
        note_unresolved_trust_call(store, theorem_id)
        append_event(store, "theorem_apply_rejected", reason, entity_id=theorem_id, payload={"reason": reason})
        return False, reason
    record_theorem_usage(store, theorem_id)
    append_event(store, "theorem_applied", f"applied theorem {theorem_id}", entity_id=theorem_id, payload={"theorem_id": theorem_id})
    return True, "applied"
