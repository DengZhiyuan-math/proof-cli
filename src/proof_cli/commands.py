from __future__ import annotations

import json
from pathlib import Path

from .domain import (
    BlockerRecord,
    ProofObligation,
    TheoremProvenanceKind,
    TheoremReviewState,
    TheoremStatus,
    TrustLevel,
)
from .export import build_export
from .proof_state import (
    add_blocker,
    add_goal,
    add_obligation,
    build_snapshot,
    load_state,
    record_failed_route,
    set_current_theorem,
    save_state,
    summarize_state,
    note_unresolved_trust_call,
    record_theorem_usage,
)
from .rendering import render_export, render_status
from .storage import (
    ProjectStore,
    approve_reference,
    defer_reference,
    ensure_project,
    get_reference,
    list_blockers,
    list_events,
    list_obligations,
    reject_reference,
    append_event,
)
from .retrieval import retrieve_candidates
from .theorems import (
    add_theorem,
    apply_theorem,
    get_contract,
    list_theorems,
    show_theorem,
    theorem_callability,
    update_theorem,
)


def get_store(root: str | Path = ".") -> ProjectStore:
    return ensure_project(root)


def _append_history(store: ProjectStore, entry: str, *, message: str) -> None:
    state = load_state(store)
    state.session_history.append(entry)
    save_state(store, state, message=message)


def _next_obligation_id(*parts: str) -> str:
    return f"obl_{abs(hash(parts)) % 100000}"


def _format_candidate_line(rank: int, title: str, source_kind: str, score: float, candidate_id: str) -> str:
    return f"{rank}. {candidate_id}: {title} [{source_kind}] score={score:g}"


def cmd_proof_search(
    query: str,
    root: str | Path = ".",
    *,
    external_candidates: list[dict[str, object]] | None = None,
    limit: int = 10,
) -> str:
    store = get_store(root)
    _append_history(store, f"search:{query}", message=f"searched {query}")
    report = retrieve_candidates(
        store,
        query=query,
        external_candidates=external_candidates,
        limit=limit,
    )
    lines = [
        f"query: {report.query}",
        "sources: " + ", ".join(source.value for source in report.source_order),
    ]
    for candidate in report.candidates[:limit]:
        lines.append(
            _format_candidate_line(
                candidate.rank,
                candidate.title,
                candidate.source_kind.value,
                candidate.score,
                candidate.id,
            )
        )
    return "\n".join(lines)


def cmd_proof_import(theorem_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    _append_history(store, f"import:{theorem_id}", message=f"import request for {theorem_id}")
    ok, reason = theorem_callability(store, theorem_id)
    if ok:
        record_theorem_usage(store, theorem_id)
        append_event(
            store,
            "dsl_imported",
            f"imported theorem {theorem_id}",
            entity_id=theorem_id,
            payload={"theorem_id": theorem_id},
        )
        return f"import:{theorem_id}"

    note_unresolved_trust_call(store, theorem_id)
    if reason.startswith("missing assumptions:"):
        missing = [item.strip() for item in reason.split(":", 1)[1].split(",") if item.strip()]
        for item in missing:
            add_obligation(
                store,
                ProofObligation(
                    id=_next_obligation_id(theorem_id, item, "import"),
                    goal_statement=item,
                    required_for=theorem_id,
                    blocking_reason=reason,
                ),
            )
    else:
        add_obligation(
            store,
            ProofObligation(
                id=_next_obligation_id(theorem_id, "import"),
                goal_statement=f"ground {theorem_id}",
                required_for=theorem_id,
                blocking_reason=reason,
            ),
        )
    record_failed_route(store, f"import:{theorem_id}")
    append_event(
        store,
        "dsl_import_blocked",
        f"blocked import for {theorem_id}",
        entity_id=theorem_id,
        payload={"reason": reason},
    )
    return f"import:blocked:{reason}"


def cmd_proof_ground(
    theorem_id: str,
    reference_ids: list[str],
    root: str | Path = ".",
    *,
    notes: str = "",
) -> str:
    store = get_store(root)
    contract = get_contract(store, theorem_id)
    if contract is None:
        return f"ground:blocked:theorem {theorem_id} not found"

    _append_history(store, f"ground:{theorem_id}:{','.join(reference_ids)}", message=f"ground request for {theorem_id}")
    approved: list[str] = []
    missing: list[str] = []
    blocked_reference_ids: list[str] = []
    for reference_id in reference_ids:
        reference = get_reference(store, reference_id)
        if reference is None:
            missing.append(f"reference {reference_id} not found")
            blocked_reference_ids.append(reference_id)
            continue
        if not reference.is_callable:
            missing.append(f"reference {reference_id} is not callable")
            blocked_reference_ids.append(reference_id)
            continue
        approved.append(reference_id)

    if missing:
        add_obligation(
            store,
            ProofObligation(
                id=_next_obligation_id(theorem_id, *reference_ids, "ground"),
                goal_statement=f"ground {theorem_id}",
                required_for=theorem_id,
                blocking_reason="; ".join(missing),
            ),
            failed_reference_ids=blocked_reference_ids,
            route_notes=notes or "grounding check failed",
        )
        append_event(
            store,
            "dsl_ground_blocked",
            f"blocked grounding for {theorem_id}",
            entity_id=theorem_id,
            payload={"missing": missing, "references": reference_ids},
        )
        return f"ground:blocked:{'; '.join(missing)}"

    update_theorem(
        store,
        theorem_id,
        grounded_reference_ids=approved,
        imported_usage_notes=[f"grounded against {', '.join(approved)}" if approved else "grounded against no references"],
        notes=(contract.notes + ("\n" if contract.notes and notes else "") + notes).strip(),
    )
    append_event(
        store,
        "dsl_grounded",
        f"grounded theorem {theorem_id}",
        entity_id=theorem_id,
        payload={"theorem_id": theorem_id, "grounded_reference_ids": approved, "notes": notes},
    )
    return f"ground:{theorem_id}:{','.join(approved)}"


def cmd_proof_review(
    target_id: str,
    action: str,
    root: str | Path = ".",
    *,
    rationale: str = "",
) -> str:
    store = get_store(root)
    normalized = action.strip().lower()
    status_map = {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "defer": "deferred",
        "deferred": "deferred",
        "candidate": "candidate",
        "downgrade": "deferred",
    }
    status_name = status_map.get(normalized)
    if status_name is None:
        return f"review:unsupported:{action}"

    reference = get_reference(store, target_id)
    if reference is not None:
        reviewer = {
            "approved": approve_reference,
            "rejected": reject_reference,
            "deferred": defer_reference,
            "candidate": defer_reference,
        }[status_name]
        result = reviewer(store, target_id, confirmed=True, rationale=rationale)
        _append_history(store, f"review:{target_id}:{status_name}", message=f"reviewed reference {target_id}")
        return f"review:{target_id}:{status_name}" if result.allowed else f"review:blocked:{result.message}"

    contract = get_contract(store, target_id)
    if contract is None:
        return f"review:blocked:target {target_id} not found"

    if status_name == "approved" and contract.provenance_kind == TheoremProvenanceKind.imported and not contract.grounded_reference_ids:
        add_obligation(
            store,
            ProofObligation(
                id=_next_obligation_id(target_id, "review", "grounding"),
                goal_statement=f"ground {target_id}",
                required_for=target_id,
                blocking_reason="imported theorem requires grounding before approval",
            ),
            supporting_reference_ids=list(contract.grounded_reference_ids),
            route_notes=rationale or "grounding required before approval",
        )
        append_event(
            store,
            "dsl_review_blocked",
            f"review blocked for {target_id}",
            entity_id=target_id,
            payload={"reason": "grounding required before approval"},
        )
        _append_history(store, f"review:{target_id}:{normalized}:blocked", message=f"blocked review for {target_id}")
        return "review:blocked:grounding required before approval"

    update_data: dict[str, object] = {"review_state": TheoremReviewState(status_name)}
    if status_name == "approved":
        update_data["status"] = TheoremStatus.verified if contract.provenance_kind == TheoremProvenanceKind.local else TheoremStatus.imported
        update_data["trust_level"] = TrustLevel.project_verified if contract.provenance_kind == TheoremProvenanceKind.local else TrustLevel.external_reference
    elif status_name == "rejected":
        update_data["status"] = TheoremStatus.blocked
    elif status_name == "deferred":
        update_data["status"] = TheoremStatus.draft
    updated = update_theorem(store, target_id, **update_data)
    append_event(
        store,
        "dsl_reviewed",
        f"reviewed theorem {target_id}",
        entity_id=target_id,
        payload={"action": normalized, "rationale": rationale, "review_state": updated.review_state.value},
    )
    _append_history(store, f"review:{target_id}:{normalized}", message=f"reviewed {target_id}")
    return f"review:{target_id}:{updated.review_state.value}"


def cmd_proof_provenance_show(target_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    theorem = get_contract(store, target_id)
    if theorem is not None:
        ok, reason = theorem_callability(store, target_id)
        payload = {
            "kind": "theorem",
            "id": target_id,
            "source_ref": theorem.source_ref,
            "grounded_reference_ids": theorem.grounded_reference_ids,
            "grounded_theorem_ids": theorem.grounded_theorem_ids,
            "review_state": theorem.review_state.value,
            "trust_level": theorem.trust_level.value,
            "callable": ok,
            "callability_reason": reason,
            "local_usage_notes": theorem.local_usage_notes,
            "imported_usage_notes": theorem.imported_usage_notes,
            "notes": theorem.notes,
        }
        return json.dumps(payload, indent=2)

    reference = get_reference(store, target_id)
    if reference is not None:
        return json.dumps(
            {
                "kind": "reference",
                "id": target_id,
                "review_status": reference.review_status.value,
                "trust_level": reference.trust_level.value,
                "source_type": reference.source_type.value,
                "is_callable": reference.is_callable,
                "bibliographic_source": reference.bibliographic_source,
                "identifier": reference.identifier,
                "url": reference.url,
                "notes": reference.notes,
            },
            indent=2,
        )

    return f"provenance:not-found:{target_id}"


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
