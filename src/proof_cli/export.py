from __future__ import annotations

from pathlib import Path

from .memory import load_memory
from .proof_state import load_state, summarize_state
from .storage import ProjectStore, list_references
from .theorems import list_theorems


def _join(values: list[str] | tuple[str, ...] | None) -> str:
    items = list(values or [])
    return ", ".join(items) if items else "none"


def _format_reference_line(reference) -> str:
    callable_state = "callable" if reference.is_callable else "not callable"
    return (
        f"{reference.id}: {reference.title} "
        f"[{reference.source_type.value}, {reference.review_status.value}, {reference.trust_level.value}, {callable_state}]"
    )


def _format_theorem_grounding_line(theorem) -> str:
    refs = _join(theorem.grounded_reference_ids)
    return f"{theorem.id}: {theorem.name} <- {refs}"


def build_export(store: ProjectStore) -> str:
    state = summarize_state(store)
    live_state = load_state(store)
    memory = load_memory(store)
    references = sorted(list_references(store), key=lambda reference: (reference.id, reference.title))
    theorems = sorted(list_theorems(store), key=lambda theorem: (theorem.id, theorem.name))

    grounded_theorems = [theorem for theorem in theorems if theorem.grounded_reference_ids]
    imported_references = references

    lines = [
        "Proof Export",
        f"Project: {state['project_id']}",
        f"Current theorem: {state['current_theorem'] or 'none'}",
        f"Goals: {_join(state['open_goals'])}",
        f"Assumed: {_join(live_state.current_context)}",
        f"Open obligations: {_join(state['open_obligations'])}",
        f"Proved: {_join(state['recent_theorem_usage'])}",
        f"Blockers: {_join(state['blockers'])}",
        f"Failed routes: {_join(state['failed_routes'])}",
        f"Trust-sensitive calls: {_join(state['unresolved_trust_sensitive_calls'])}",
        "Imported references:",
    ]

    if imported_references:
        lines.extend(f"- {_format_reference_line(reference)}" for reference in imported_references)
    else:
        lines.append("- none")

    lines.append("Grounded theorems:")
    if grounded_theorems:
        lines.extend(f"- {_format_theorem_grounding_line(theorem)}" for theorem in grounded_theorems)
    else:
        lines.append("- none")

    memory_counts = {
        "working": len(memory.working),
        "semantic": len(memory.semantic),
        "episodic": len(memory.episodic),
        "procedural": len(memory.procedural),
        "handoffs": len(memory.handoff_snapshots),
    }
    lines.append(
        "Memory layers: "
        + ", ".join(f"{name}={count}" for name, count in memory_counts.items())
    )

    snapshot = state["latest_snapshot"]
    if snapshot is not None:
        lines.append("Latest snapshot:")
        lines.append(snapshot.model_dump_json(indent=2))

    return "\n".join(lines)


def write_export(store: ProjectStore, path: str | Path) -> str:
    content = build_export(store)
    output = Path(path)
    output.write_text(content)
    return content
