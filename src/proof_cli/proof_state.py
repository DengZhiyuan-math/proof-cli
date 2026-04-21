from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .domain import BlockerRecord, ProofObligation, ProjectSnapshot, ProjectState
from .storage import (
    ProjectStore,
    append_event,
    list_blockers,
    list_contracts,
    list_obligations,
    read_latest_snapshot,
    read_state,
    store_blocker,
    store_obligation,
    store_snapshot,
    store_state,
)
from .domain import ProofObligationStatus


def load_state(store: ProjectStore) -> ProjectState:
    return read_state(store)


def save_state(store: ProjectStore, state: ProjectState, *, event_kind: str = "state_changed", message: str = "updated state") -> ProjectState:
    store_state(store, state)
    append_event(store, event_kind, message, entity_id=state.project_id, payload=state.model_dump(mode="json"))
    return state


def set_current_theorem(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    state.current_theorem = theorem_id
    if theorem_id not in state.open_goals:
        state.open_goals.append(theorem_id)
    state.session_history.append(f"current_theorem:{theorem_id}")
    return save_state(store, state, message=f"set current theorem to {theorem_id}")


def set_current_context(store: ProjectStore, assumptions: list[str]) -> ProjectState:
    state = load_state(store)
    state.current_context = assumptions
    state.session_history.append("updated proof context")
    return save_state(store, state, message="updated proof context")


def add_goal(store: ProjectStore, goal: str) -> ProjectState:
    state = load_state(store)
    if goal not in state.open_goals:
        state.open_goals.append(goal)
    state.session_history.append(f"goal:{goal}")
    return save_state(store, state, message=f"added goal {goal}")


def add_obligation(store: ProjectStore, obligation: ProofObligation) -> ProofObligation:
    store_obligation(store, obligation)
    state = load_state(store)
    if obligation.id not in state.open_obligations and obligation.status == ProofObligationStatus.open:
        state.open_obligations.append(obligation.id)
        state.session_history.append(f"obligation:{obligation.id}")
        save_state(store, state, message=f"added obligation {obligation.id}")
    else:
        append_event(store, "obligation_added", f"added obligation {obligation.id}", entity_id=obligation.id, payload=obligation.model_dump(mode="json"))
    return obligation


def add_blocker(store: ProjectStore, blocker: BlockerRecord) -> BlockerRecord:
    store_blocker(store, blocker)
    state = load_state(store)
    if blocker.id not in state.blockers and blocker.status == "active":
        state.blockers.append(blocker.id)
    state.session_history.append(f"blocker:{blocker.id}")
    save_state(store, state, message=f"added blocker {blocker.id}")
    return blocker


def record_failed_route(store: ProjectStore, route: str) -> ProjectState:
    state = load_state(store)
    state.failed_routes.append(route)
    state.session_history.append(f"failed_route:{route}")
    return save_state(store, state, message=f"recorded failed route {route}")


def record_theorem_usage(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    if theorem_id not in state.recent_theorem_usage:
        state.recent_theorem_usage.append(theorem_id)
    state.session_history.append(f"used_theorem:{theorem_id}")
    return save_state(store, state, message=f"used theorem {theorem_id}")


def note_unresolved_trust_call(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    if theorem_id not in state.unresolved_trust_sensitive_calls:
        state.unresolved_trust_sensitive_calls.append(theorem_id)
    return save_state(store, state, message=f"noted unresolved trust-sensitive call {theorem_id}")


def build_snapshot(store: ProjectStore, handoff_note: str = "") -> ProjectSnapshot:
    state = load_state(store)
    snapshot = ProjectSnapshot(
        project_id=state.project_id,
        active_theorem=state.current_theorem,
        current_goals=list(state.open_goals),
        validated_results=list(state.recent_theorem_usage),
        open_obligations=list(state.open_obligations),
        active_blockers=list(state.blockers),
        recently_used_results=list(state.recent_theorem_usage),
        unresolved_trust_sensitive_calls=list(state.unresolved_trust_sensitive_calls),
        next_promising_routes=list(state.failed_routes[-3:]),
        handoff_note=handoff_note or "resume from the latest proof state",
    )
    store_snapshot(store, snapshot)
    append_event(store, "snapshot_created", "created snapshot", entity_id=state.project_id, payload=snapshot.model_dump(mode="json"))
    state.latest_snapshot_id = snapshot.project_id
    save_state(store, state, message="updated latest snapshot reference")
    return snapshot


def project_history(store: ProjectStore) -> list[str]:
    return [event.message for event in []]


def summarize_state(store: ProjectStore) -> dict[str, object]:
    state = load_state(store)
    snapshot = read_latest_snapshot(store)
    return {
        "project_id": state.project_id,
        "current_theorem": state.current_theorem,
        "open_goals": state.open_goals,
        "open_obligations": state.open_obligations,
        "blockers": state.blockers,
        "failed_routes": state.failed_routes,
        "recent_theorem_usage": state.recent_theorem_usage,
        "unresolved_trust_sensitive_calls": state.unresolved_trust_sensitive_calls,
        "latest_snapshot": snapshot,
    }
