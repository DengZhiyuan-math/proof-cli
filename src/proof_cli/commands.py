from __future__ import annotations

from pathlib import Path

from .domain import BlockerRecord, ProofObligation, ProjectState, TheoremStatus, TrustLevel
from .export import build_export
from .proof_state import (
    add_blocker,
    add_goal,
    add_obligation,
    build_snapshot,
    load_state,
    record_failed_route,
    set_current_theorem,
    summarize_state,
)
from .rendering import render_export, render_status
from .storage import ProjectStore, ensure_project, list_blockers, list_events, list_obligations
from .theorems import add_theorem, apply_theorem, list_theorems, show_theorem, update_theorem, theorem_callability


def get_store(root: str | Path = ".") -> ProjectStore:
    return ensure_project(root)


def cmd_init(root: str | Path = ".") -> str:
    store = ensure_project(root)
    state = load_state(store)
    return f"Initialized proof project {state.project_id} at {store.db_path}"


def cmd_status(root: str | Path = ".") -> str:
    return render_status(summarize_state(get_store(root)))


def cmd_goal_set(goal: str, root: str | Path = ".") -> str:
    state = add_goal(get_store(root), goal)
    return f"Current goal set: {state.open_goals[-1]}"


def cmd_goal_list(root: str | Path = ".") -> str:
    state = load_state(get_store(root))
    return "\n".join(state.open_goals) if state.open_goals else "No goals"


def cmd_theorem_add(
    theorem_id: str,
    name: str,
    statement: str,
    root: str | Path = ".",
    kind: str = "theorem",
    assumption: list[str] | None = None,
    export: list[str] | None = None,
    source_ref: str = "internal/project",
    notes: str = "",
) -> str:
    contract = add_theorem(
        get_store(root),
        theorem_id=theorem_id,
        kind=kind,
        name=name,
        statement=statement,
        assumptions=assumption,
        exports=export,
        source_ref=source_ref,
        notes=notes,
    )
    return contract.model_dump_json(indent=2)


def cmd_theorem_show(theorem_id: str, root: str | Path = ".") -> str:
    contract = show_theorem(get_store(root), theorem_id)
    return contract.model_dump_json(indent=2) if contract else "Theorem not found"


def cmd_theorem_list(root: str | Path = ".") -> str:
    items = list_theorems(get_store(root))
    return "\n".join([f"{item.id}: {item.name} [{item.status.value}]" for item in items]) or "No theorems"


def cmd_theorem_apply(theorem_id: str, root: str | Path = ".") -> str:
    ok, reason = apply_theorem(get_store(root), theorem_id)
    return f"{theorem_id}: {reason}"


def cmd_obligation_add(goal_statement: str, root: str | Path = ".", source_step_id: str | None = None, required_for: str | None = None) -> str:
    obligation = ProofObligation(id=f"obl_{abs(hash(goal_statement)) % 100000}", goal_statement=goal_statement, source_step_id=source_step_id, required_for=required_for)
    add_obligation(get_store(root), obligation)
    return obligation.model_dump_json(indent=2)


def cmd_obligation_list(root: str | Path = ".") -> str:
    items = list_obligations(get_store(root))
    return "\n".join([f"{item.id}: {item.goal_statement} [{item.status.value}]" for item in items]) or "No obligations"


def cmd_blocker_add(description: str, root: str | Path = ".", scope: str = "global", failure_type: str = "unknown") -> str:
    blocker = BlockerRecord(
        id=f"blk_{abs(hash((scope, description))) % 100000}",
        scope=scope,
        description=description,
        failure_type=failure_type,
    )
    add_blocker(get_store(root), blocker)
    return blocker.model_dump_json(indent=2)


def cmd_blocker_list(root: str | Path = ".") -> str:
    items = list_blockers(get_store(root))
    return "\n".join([f"{item.id}: {item.description} [{item.status.value}]" for item in items]) or "No blockers"


def cmd_snapshot(root: str | Path = ".", handoff_note: str = "") -> str:
    snapshot = build_snapshot(get_store(root), handoff_note=handoff_note)
    return snapshot.model_dump_json(indent=2)


def cmd_history(root: str | Path = ".") -> str:
    events = list_events(get_store(root))
    return "\n".join([f"{event.created_at.isoformat()} {event.kind}: {event.message}" for event in events]) or "No history"


def cmd_export(root: str | Path = ".") -> str:
    return build_export(get_store(root))


def cmd_goal_open(theorem_id: str, root: str | Path = ".") -> str:
    return cmd_goal_set(theorem_id, root=root)
