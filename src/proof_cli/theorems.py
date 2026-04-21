from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    TheoremContract,
    TheoremStatus,
    TrustLevel,
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
    dependencies: list[str] | None = None,
    source_ref: str = "internal/project",
    notes: str = "",
) -> TheoremContract:
    contract = TheoremContract(
        id=theorem_id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        statement=statement,
        assumptions=assumptions or [],
        exports=exports or [],
        status=status,
        trust_level=trust_level,
        dependencies=dependencies or [],
        source_ref=source_ref,
        notes=notes,
    )
    store_contract(store, contract)
    append_event(store, "theorem_added", f"added theorem {theorem_id}", entity_id=theorem_id, payload=contract.model_dump(mode="json"))
    return contract


def update_theorem(store: ProjectStore, theorem_id: str, **changes) -> TheoremContract:
    contract = get_contract(store, theorem_id)
    if contract is None:
        raise KeyError(theorem_id)
    updated = contract.model_copy(update=changes)
    store_contract(store, updated)
    append_event(store, "theorem_updated", f"updated theorem {theorem_id}", entity_id=theorem_id, payload=updated.model_dump(mode="json"))
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
