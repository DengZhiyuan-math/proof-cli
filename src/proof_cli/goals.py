from __future__ import annotations

from pathlib import Path

from .domain import ProjectState
from .proof_state import add_goal as _add_goal, set_current_theorem as _set_current_theorem, set_current_context as _set_current_context, load_state
from .storage import ProjectStore


def set_current_theorem(store: ProjectStore, theorem_id: str) -> ProjectState:
    return _set_current_theorem(store, theorem_id)


def set_current_context(store: ProjectStore, assumptions: list[str]) -> ProjectState:
    return _set_current_context(store, assumptions)


def add_goal(store: ProjectStore, goal: str) -> ProjectState:
    return _add_goal(store, goal)


def list_goals(store: ProjectStore) -> list[str]:
    return list(load_state(store).open_goals)

