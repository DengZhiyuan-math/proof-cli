from __future__ import annotations

from .domain import ProofObligation, ProofObligationStatus, ProjectState
from .proof_state import add_obligation as _add_obligation, load_state, save_state
from .storage import ProjectStore, append_event, list_obligations as _list_obligations, store_obligation


def add_obligation(store: ProjectStore, obligation: ProofObligation) -> ProofObligation:
    return _add_obligation(store, obligation)


def list_obligations(store: ProjectStore) -> list[ProofObligation]:
    return _list_obligations(store)


def close_obligation(store: ProjectStore, obligation_id: str, rationale: str | None = None) -> ProofObligation:
    obligations = list_obligations(store)
    for obligation in obligations:
        if obligation.id == obligation_id:
            obligation.status = ProofObligationStatus.closed
            obligation.blocking_reason = rationale
            store_obligation(store, obligation)
            append_event(
                store,
                "obligation_closed",
                f"closed obligation {obligation_id}",
                entity_id=obligation_id,
                payload=obligation.model_dump(mode="json"),
            )
            state = load_state(store)
            if obligation_id in state.open_obligations:
                state.open_obligations.remove(obligation_id)
                save_state(store, state, message=f"closed obligation {obligation_id}")
            return obligation
    raise KeyError(obligation_id)


def block_obligation(store: ProjectStore, obligation_id: str, reason: str) -> ProofObligation:
    obligations = list_obligations(store)
    for obligation in obligations:
        if obligation.id == obligation_id:
            obligation.status = ProofObligationStatus.blocked
            obligation.blocking_reason = reason
            store_obligation(store, obligation)
            append_event(
                store,
                "obligation_blocked",
                f"blocked obligation {obligation_id}",
                entity_id=obligation_id,
                payload=obligation.model_dump(mode="json"),
            )
            return obligation
    raise KeyError(obligation_id)

