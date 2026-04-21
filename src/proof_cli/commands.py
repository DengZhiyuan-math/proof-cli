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
from .bugs import ProofBugReport, ProofBugReviewState, ProofBugScan, ProofBugSeverity, ProofBugStatus, ProofBugType, scan_proof_bugs
from .debug_tasks import ProofDebugTaskBatch, debug_task_batch_from_reports
from .export import build_export
from .evidence import EvidenceChain, build_evidence_chains
from .memory import MemoryArtifact, MemoryLayer, list_memory_artifacts, record_memory
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
from .references import ReferenceRecord, ReferenceReviewStatus, ReferenceSourceType
from .rendering import render_status
from .storage import (
    ProjectStore,
    approve_reference,
    defer_reference,
    ensure_project,
    get_reference,
    list_blockers,
    list_events,
    list_obligations,
    list_references,
    reject_reference,
    append_event,
    import_reference,
)
from .reasoning import ContractAdequacyCheck, DownstreamUse, LocalObligation, ReasoningProject, TheoremReasoningGoal
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


def _format_reference_line(reference: ReferenceRecord) -> str:
    callability = "callable" if reference.is_callable else "not callable"
    return (
        f"{reference.id}: {reference.title} "
        f"[{reference.source_type.value}, {reference.review_status.value}, {callability}]"
    )


def _format_memory_line(artifact: MemoryArtifact) -> str:
    scope_bits = []
    if artifact.scope.theorem_id:
        scope_bits.append(f"theorem={artifact.scope.theorem_id}")
    if artifact.scope.goal_id:
        scope_bits.append(f"goal={artifact.scope.goal_id}")
    if artifact.scope.obligation_id:
        scope_bits.append(f"obligation={artifact.scope.obligation_id}")
    if artifact.scope.blocker_id:
        scope_bits.append(f"blocker={artifact.scope.blocker_id}")
    if artifact.scope.route_id:
        scope_bits.append(f"route={artifact.scope.route_id}")
    scope_text = " ".join(scope_bits) if scope_bits else "project-scope"
    tag_text = f" tags={','.join(artifact.tags)}" if artifact.tags else ""
    return f"{artifact.id}: [{artifact.layer.value}/{artifact.status.value}/{artifact.importance.value}] {scope_text} {artifact.content}{tag_text}"


_BUG_SCAN_HISTORY_PREFIX = "proof_bug_scan:"
_BUG_REVIEW_HISTORY_PREFIX = "proof_bug_review:"
_BUG_REPAIR_HISTORY_PREFIX = "proof_bug_repair:"
_REASONING_HISTORY_PREFIX = "proof_reasoning:"
_DEBUG_BATCH_HISTORY_PREFIX = "proof_debug_batch:"


def _state_marker(prefix: str, payload: dict[str, object]) -> str:
    return f"{prefix}{json.dumps(payload, sort_keys=True)}"


def _append_state_marker(store: ProjectStore, prefix: str, payload: dict[str, object], *, event_kind: str, message: str, entity_id: str | None = None) -> None:
    state = load_state(store)
    state.session_history.append(_state_marker(prefix, payload))
    save_state(store, state, message=message)
    append_event(store, event_kind, message, entity_id=entity_id, payload=payload)


def _stable_bug_id(theorem_id: str, report: ProofBugReport) -> str:
    seed = (
        theorem_id,
        report.detector,
        report.bug_type.value,
        report.description,
        tuple(report.missing_conditions),
        tuple(report.linked_contract_ids),
        tuple(report.linked_obligation_ids),
        tuple(report.linked_blocker_ids),
    )
    return f"bug_{abs(hash(seed)) % 100000}"


def _normalize_bug_reports(theorem_id: str, reports: list[ProofBugReport]) -> list[ProofBugReport]:
    normalized: list[ProofBugReport] = []
    for report in reports:
        report_update = {
            "id": _stable_bug_id(theorem_id, report),
            "linked_contract_ids": [*report.linked_contract_ids] if theorem_id in report.linked_contract_ids or theorem_id else list(report.linked_contract_ids),
        }
        normalized.append(report.model_copy(update=report_update))
    return normalized


def _latest_marked_bug_scan(store: ProjectStore, theorem_id: str | None = None) -> ProofBugScan | None:
    state = load_state(store)
    latest: ProofBugScan | None = None
    for entry in state.session_history:
        if not entry.startswith(_BUG_SCAN_HISTORY_PREFIX):
            continue
        payload = json.loads(entry.removeprefix(_BUG_SCAN_HISTORY_PREFIX))
        if theorem_id is not None and payload.get("theorem_id") != theorem_id:
            continue
        latest = ProofBugScan.model_validate(payload)
    return latest


def _bug_overrides(store: ProjectStore) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    state = load_state(store)
    reviews: dict[str, dict[str, object]] = {}
    repairs: dict[str, dict[str, object]] = {}
    for entry in state.session_history:
        if entry.startswith(_BUG_REVIEW_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_REVIEW_HISTORY_PREFIX))
            reviews[str(payload["bug_id"])] = payload
        elif entry.startswith(_BUG_REPAIR_HISTORY_PREFIX):
            payload = json.loads(entry.removeprefix(_BUG_REPAIR_HISTORY_PREFIX))
            repairs[str(payload["bug_id"])] = payload
    return reviews, repairs


def _apply_bug_overrides(report: ProofBugReport, reviews: dict[str, dict[str, object]], repairs: dict[str, dict[str, object]]) -> ProofBugReport:
    update: dict[str, object] = {}
    review_payload = reviews.get(report.id)
    if review_payload is not None:
        update["status"] = ProofBugStatus(str(review_payload["bug_status"]))
        update["review_state"] = ProofBugReviewState(str(review_payload.get("review_state", "reviewed")))
    repair_payload = repairs.get(report.id)
    if repair_payload is not None:
        update["status"] = ProofBugStatus(str(repair_payload["bug_status"]))
        update["review_state"] = ProofBugReviewState(str(repair_payload.get("review_state", "reviewed")))
    if not update:
        return report
    return report.model_copy(update=update)


def _scan_and_store_bugs(store: ProjectStore, theorem_id: str) -> ProofBugScan:
    scan = scan_proof_bugs(store, theorem_id)
    normalized_reports = _normalize_bug_reports(theorem_id, scan.reports)
    scan = scan.model_copy(update={"reports": normalized_reports})
    _append_state_marker(
        store,
        _BUG_SCAN_HISTORY_PREFIX,
        scan.model_dump(mode="json"),
        event_kind="proof_bug_scan",
        message=f"scanned proof bugs for {theorem_id}",
        entity_id=theorem_id,
    )
    return scan


def _record_debug_batch(store: ProjectStore, batch: ProofDebugTaskBatch, *, theorem_id: str) -> ProofDebugTaskBatch:
    _append_state_marker(
        store,
        _DEBUG_BATCH_HISTORY_PREFIX,
        batch.model_dump(mode="json"),
        event_kind="proof_debug_batch",
        message=f"generated debug tasks for {theorem_id}",
        entity_id=theorem_id,
    )
    return batch


def _find_bug_report(store: ProjectStore, bug_id: str) -> tuple[ProofBugScan | None, ProofBugReport | None]:
    latest_scan: ProofBugScan | None = None
    found_report: ProofBugReport | None = None
    state = load_state(store)
    reviews, repairs = _bug_overrides(store)
    for entry in state.session_history:
        if not entry.startswith(_BUG_SCAN_HISTORY_PREFIX):
            continue
        payload = json.loads(entry.removeprefix(_BUG_SCAN_HISTORY_PREFIX))
        scan = ProofBugScan.model_validate(payload)
        scan = scan.model_copy(update={"reports": [_apply_bug_overrides(report, reviews, repairs) for report in scan.reports]})
        latest_scan = scan
        for report in scan.reports:
            if report.id == bug_id:
                found_report = report
    return latest_scan, found_report


def _format_bug_line(report: ProofBugReport) -> str:
    return f"{report.id}: {report.bug_type.value} [{report.status.value}/{report.severity.value}] {report.description}"


def _derive_reasoning_project(store: ProjectStore, theorem_id: str, *, notes: str = "") -> tuple[ReasoningProject, ContractAdequacyCheck, list[LocalObligation]]:
    contract = get_contract(store, theorem_id)
    if contract is None:
        raise KeyError(theorem_id)
    state = load_state(store)
    downstream_use = DownstreamUse(
        id=f"use_{theorem_id}_apply",
        label=f"apply {theorem_id}",
        required_assumptions=list(contract.assumptions),
        required_exports=list(contract.exports),
        reasoning_path=[theorem_id, "reason", "apply"],
        notes=notes or contract.notes,
    )
    goal = TheoremReasoningGoal(
        id=f"reason_{theorem_id}",
        theorem_id=theorem_id,
        statement=contract.statement,
        assumptions=list(state.current_context),
        exports=list(contract.exports),
        downstream_use=[downstream_use],
        dependencies=list(contract.dependencies),
    )
    project = ReasoningProject(project_id=state.project_id, theorem_goals=[goal])
    check = ContractAdequacyCheck.evaluate(
        contract_id=theorem_id,
        contract_assumptions=list(state.current_context),
        contract_exports=list(contract.exports),
        downstream_use=[downstream_use],
    )
    obligations = project.synthesize_obligations()
    return project, check, obligations


def _store_reasoning_obligations(store: ProjectStore, theorem_id: str, obligations: list[LocalObligation], check: ContractAdequacyCheck) -> list[ProofObligation]:
    derived: list[ProofObligation] = []
    for local_obligation in obligations:
        proof_obligation = ProofObligation(
            id=local_obligation.id,
            goal_statement=local_obligation.statement,
            source_step_id=local_obligation.source_unit_id,
            required_for=local_obligation.required_for,
            blocking_reason="; ".join(check.missing_conditions) if check.missing_conditions else "derived from reasoning",
            dependencies=list(local_obligation.dependencies),
        )
        add_obligation(store, proof_obligation)
        derived.append(proof_obligation)
    return derived


def _find_memory_artifact(store: ProjectStore, artifact_id: str) -> MemoryArtifact | None:
    for artifact in list_memory_artifacts(store):
        if artifact.id == artifact_id:
            return artifact
    return None


def _reference_review_action(action: str) -> ReferenceReviewStatus | None:
    normalized = action.strip().lower()
    mapping = {
        "approve": ReferenceReviewStatus.approved,
        "approved": ReferenceReviewStatus.approved,
        "reject": ReferenceReviewStatus.rejected,
        "rejected": ReferenceReviewStatus.rejected,
        "defer": ReferenceReviewStatus.deferred,
        "deferred": ReferenceReviewStatus.deferred,
        "candidate": ReferenceReviewStatus.candidate,
    }
    return mapping.get(normalized)


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


def cmd_reference_list(root: str | Path = ".") -> str:
    references = list_references(get_store(root))
    if not references:
        return "No references"
    lines = ["References:"]
    for reference in references:
        lines.append(f"- {_format_reference_line(reference)}")
    return "\n".join(lines)


def cmd_reference_show(reference_id: str, root: str | Path = ".") -> str:
    reference = get_reference(get_store(root), reference_id)
    return reference.model_dump_json(indent=2) if reference else f"Reference not found: {reference_id}"


def cmd_reference_import(
    reference_id: str,
    title: str,
    year: int,
    root: str | Path = ".",
    *,
    author: list[str] | None = None,
    source_type: ReferenceSourceType = ReferenceSourceType.other,
    origin: str = "",
    bibliographic_source: str = "",
    identifier: str = "",
    url: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    source_type_enum = source_type if isinstance(source_type, ReferenceSourceType) else ReferenceSourceType(source_type)
    reference = ReferenceRecord(
        id=reference_id,
        title=title,
        authors=list(author or []),
        year=year,
        source_type=source_type_enum,
        origin=origin,
        bibliographic_source=bibliographic_source,
        identifier=identifier,
        url=url,
        notes=notes,
    )
    stored = import_reference(store, reference)
    _append_history(store, f"reference_import:{reference_id}", message=f"imported reference {reference_id}")
    return stored.model_dump_json(indent=2)


def cmd_reference_review(reference_id: str, action: str, root: str | Path = ".", *, rationale: str = "") -> str:
    store = get_store(root)
    review_status = _reference_review_action(action)
    if review_status is None:
        return f"review:unsupported:{action}"
    reviewer = {
        ReferenceReviewStatus.approved: approve_reference,
        ReferenceReviewStatus.rejected: reject_reference,
        ReferenceReviewStatus.deferred: defer_reference,
        ReferenceReviewStatus.candidate: defer_reference,
    }[review_status]
    result = reviewer(store, reference_id, confirmed=True, rationale=rationale)
    if not result.allowed:
        return f"review:blocked:{result.message}"
    _append_history(store, f"reference_review:{reference_id}:{review_status.value}", message=f"reviewed reference {reference_id}")
    return f"review:{reference_id}:{review_status.value}"


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


def cmd_proof_reason(theorem_id: str, root: str | Path = ".", *, notes: str = "") -> str:
    store = get_store(root)
    contract = get_contract(store, theorem_id)
    if contract is None:
        return f"reason:blocked:theorem {theorem_id} not found"
    project, check, obligations = _derive_reasoning_project(store, theorem_id, notes=notes)
    derived = _store_reasoning_obligations(store, theorem_id, obligations, check)
    payload = {
        "theorem_id": theorem_id,
        "project": project.model_dump(mode="json"),
        "adequacy_check": check.model_dump(mode="json"),
        "derived_obligations": [obligation.model_dump(mode="json") for obligation in derived],
    }
    _append_state_marker(
        store,
        _REASONING_HISTORY_PREFIX,
        payload,
        event_kind="proof_reasoning",
        message=f"reasoned about {theorem_id}",
        entity_id=theorem_id,
    )
    return json.dumps(payload, indent=2)


def cmd_proof_obligation_derive(theorem_id: str, root: str | Path = ".", *, notes: str = "") -> str:
    store = get_store(root)
    contract = get_contract(store, theorem_id)
    if contract is None:
        return f"obligation:derive:blocked:theorem {theorem_id} not found"
    project, check, obligations = _derive_reasoning_project(store, theorem_id, notes=notes)
    derived = _store_reasoning_obligations(store, theorem_id, obligations, check)
    payload = {
        "theorem_id": theorem_id,
        "adequacy_check": check.model_dump(mode="json"),
        "obligations": [obligation.model_dump(mode="json") for obligation in derived],
        "reasoning_path": project.theorem_goals[0].downstream_use[0].reasoning_path if project.theorem_goals else [],
    }
    _append_state_marker(
        store,
        _REASONING_HISTORY_PREFIX,
        payload,
        event_kind="proof_obligation_derive",
        message=f"derived obligations for {theorem_id}",
        entity_id=theorem_id,
    )
    return json.dumps(payload, indent=2)


def cmd_proof_bug_scan(theorem_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    scan = _scan_and_store_bugs(store, theorem_id)
    return scan.model_dump_json(indent=2)


def cmd_proof_bug_list(root: str | Path = ".", *, theorem_id: str = "") -> str:
    store = get_store(root)
    scan = _latest_marked_bug_scan(store, theorem_id or None)
    if scan is None:
        return "No proof bug scans"
    reviews, repairs = _bug_overrides(store)
    reports = [_apply_bug_overrides(report, reviews, repairs) for report in scan.reports]
    if not reports:
        return "No proof bugs"
    return "\n".join(_format_bug_line(report) for report in reports)


def cmd_proof_bug_show(bug_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    _, report = _find_bug_report(store, bug_id)
    return report.model_dump_json(indent=2) if report is not None else f"Bug not found: {bug_id}"


def cmd_proof_evidence_show(bug_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    _, report = _find_bug_report(store, bug_id)
    if report is None:
        return f"Bug not found: {bug_id}"
    chain = EvidenceChain.from_bug_report(report)
    return chain.model_dump_json(indent=2)


def cmd_proof_debug_generate(theorem_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    scan = _latest_marked_bug_scan(store, theorem_id)
    if scan is None or scan.theorem_id != theorem_id:
        scan = _scan_and_store_bugs(store, theorem_id)
    reviews, repairs = _bug_overrides(store)
    reports = [_apply_bug_overrides(report, reviews, repairs) for report in scan.reports]
    evidence_chains = build_evidence_chains(reports)
    batch = debug_task_batch_from_reports(reports, evidence_chains=evidence_chains, theorem_id=theorem_id)
    batch = _record_debug_batch(store, batch, theorem_id=theorem_id)
    return batch.model_dump_json(indent=2)


def cmd_proof_debug_list(root: str | Path = ".", *, theorem_id: str = "") -> str:
    store = get_store(root)
    state = load_state(store)
    latest_batch: ProofDebugTaskBatch | None = None
    for entry in state.session_history:
        if not entry.startswith(_DEBUG_BATCH_HISTORY_PREFIX):
            continue
        payload = json.loads(entry.removeprefix(_DEBUG_BATCH_HISTORY_PREFIX))
        if theorem_id and payload.get("theorem_id") != theorem_id:
            continue
        latest_batch = ProofDebugTaskBatch.model_validate(payload)
    if latest_batch is None:
        return "No debug tasks"
    if not latest_batch.tasks:
        return "No debug tasks"
    lines = [
        f"{task.id}: {task.task_type.value} [{task.priority.value}/{task.status.value}] bug={task.bug_report_id} {task.description}"
        for task in latest_batch.tasks
    ]
    return "\n".join(lines)


def cmd_proof_repair_mark(bug_id: str, status: str, root: str | Path = ".", *, note: str = "") -> str:
    store = get_store(root)
    _, existing_report = _find_bug_report(store, bug_id)
    if existing_report is None:
        return f"repair:blocked:bug {bug_id} not found"
    normalized = status.strip().lower()
    status_map = {
        "repaired": ProofBugStatus.repaired,
        "superseded": ProofBugStatus.superseded,
        "confirmed": ProofBugStatus.confirmed,
        "dismissed": ProofBugStatus.dismissed,
    }
    bug_status = status_map.get(normalized)
    if bug_status is None:
        return f"repair:unsupported:{status}"
    payload = {
        "bug_id": bug_id,
        "bug_status": bug_status.value,
        "review_state": "reviewed",
        "note": note,
    }
    _append_state_marker(
        store,
        _BUG_REPAIR_HISTORY_PREFIX,
        payload,
        event_kind="proof_bug_repair",
        message=f"marked bug {bug_id} as {bug_status.value}",
        entity_id=bug_id,
    )
    return json.dumps(payload, indent=2)


def cmd_proof_review_suspicion(bug_id: str, status: str, root: str | Path = ".", *, rationale: str = "") -> str:
    store = get_store(root)
    _, existing_report = _find_bug_report(store, bug_id)
    if existing_report is None:
        return f"review:suspicion:blocked:bug {bug_id} not found"
    normalized = status.strip().lower() or "under_review"
    status_map = {
        "suspected": ProofBugStatus.suspected,
        "under_review": ProofBugStatus.under_review,
        "confirmed": ProofBugStatus.confirmed,
        "dismissed": ProofBugStatus.dismissed,
        "repaired": ProofBugStatus.repaired,
        "superseded": ProofBugStatus.superseded,
    }
    bug_status = status_map.get(normalized)
    if bug_status is None:
        return f"review:suspicion:unsupported:{status}"
    payload = {
        "bug_id": bug_id,
        "bug_status": bug_status.value,
        "review_state": "reviewed" if bug_status in {ProofBugStatus.confirmed, ProofBugStatus.dismissed, ProofBugStatus.repaired, ProofBugStatus.superseded} else "triaged",
        "rationale": rationale,
    }
    _append_state_marker(
        store,
        _BUG_REVIEW_HISTORY_PREFIX,
        payload,
        event_kind="proof_bug_review",
        message=f"reviewed suspicion for {bug_id}",
        entity_id=bug_id,
    )
    return json.dumps(payload, indent=2)


def cmd_proof_trace_dependency(target_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    contract = get_contract(store, target_id)
    obligations = [obligation.model_dump(mode="json") for obligation in list_obligations(store) if obligation.required_for == target_id or target_id in obligation.dependencies]
    blockers = [blocker.model_dump(mode="json") for blocker in list_blockers(store) if blocker.scope == target_id or target_id in blocker.related_contracts or target_id in blocker.related_steps]
    payload = {
        "target_id": target_id,
        "contract": contract.model_dump(mode="json") if contract is not None else None,
        "dependency_ids": list(contract.dependencies) if contract is not None else [],
        "open_obligations": obligations,
        "blockers": blockers,
        "recent_theorem_usage": list(load_state(store).recent_theorem_usage),
        "session_history": list(load_state(store).session_history[-10:]),
    }
    return json.dumps(payload, indent=2)


def cmd_proof_explain_apply(theorem_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    contract = get_contract(store, theorem_id)
    if contract is None:
        return f"explain:apply:blocked:theorem {theorem_id} not found"
    ok, reason = theorem_callability(store, theorem_id)
    state = load_state(store)
    open_obligations = [
        obligation.model_dump(mode="json")
        for obligation in list_obligations(store)
        if obligation.required_for == theorem_id
        or obligation.source_step_id == theorem_id
        or theorem_id in obligation.dependencies
        or (obligation.required_for or "").startswith(f"use_{theorem_id}")
    ]
    payload = {
        "theorem_id": theorem_id,
        "callable": ok,
        "callability_reason": reason,
        "statement": contract.statement,
        "assumptions": list(contract.assumptions),
        "exports": list(contract.exports),
        "current_context": list(state.current_context),
        "missing_assumptions": [assumption for assumption in contract.assumptions if assumption not in state.current_context],
        "dependencies": list(contract.dependencies),
        "grounded_reference_ids": list(contract.grounded_reference_ids),
        "grounded_theorem_ids": list(contract.grounded_theorem_ids),
        "open_obligations": open_obligations,
        "local_usage_notes": list(contract.local_usage_notes),
        "imported_usage_notes": list(contract.imported_usage_notes),
    }
    return json.dumps(payload, indent=2)


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


def cmd_theorem_extract(theorem_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    contract = show_theorem(store, theorem_id)
    if contract is None:
        return f"Theorem not found: {theorem_id}"
    ok, reason = theorem_callability(store, theorem_id)
    payload = contract.model_dump(mode="json")
    payload["callable"] = ok
    payload["callability_reason"] = reason
    return json.dumps(payload, indent=2)


def cmd_theorem_list(root: str | Path = ".") -> str:
    items = list_theorems(get_store(root))
    return "\n".join([f"{item.id}: {item.name} [{item.status.value}]" for item in items]) or "No theorems"


def cmd_theorem_apply(theorem_id: str, root: str | Path = ".") -> str:
    ok, reason = apply_theorem(get_store(root), theorem_id)
    return f"{theorem_id}: {reason}"


def cmd_theorem_ground(theorem_id: str, reference_ids: list[str], root: str | Path = ".", *, notes: str = "") -> str:
    return cmd_proof_ground(theorem_id, reference_ids, root=root, notes=notes)


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


def cmd_memory_add(
    content: str,
    root: str | Path = ".",
    *,
    layer: str = "working",
    theorem_id: str = "",
    goal_id: str = "",
    obligation_id: str = "",
    blocker_id: str = "",
    route_id: str = "",
    importance: str = "medium",
    status: str = "",
    source: str = "manual",
    tag: list[str] | None = None,
    notes: str = "",
) -> str:
    store = get_store(root)
    artifact = record_memory(
        store,
        layer,
        content,
        theorem_id=theorem_id or None,
        goal_id=goal_id or None,
        obligation_id=obligation_id or None,
        blocker_id=blocker_id or None,
        route_id=route_id or None,
        importance=importance,
        status=status or None,
        source=source,  # type: ignore[arg-type]
        tags=tag,
        notes=notes,
    )
    return artifact.model_dump_json(indent=2)


def cmd_memory_list(
    root: str | Path = ".",
    *,
    layer: str = "",
    theorem_id: str = "",
    goal_id: str = "",
) -> str:
    artifacts = list_memory_artifacts(
        get_store(root),
        layer=layer or None,
        theorem_id=theorem_id or None,
        goal_id=goal_id or None,
    )
    if not artifacts:
        return "No memory artifacts"
    lines = ["Memory:"]
    for artifact in artifacts:
        lines.append(f"- {_format_memory_line(artifact)}")
    return "\n".join(lines)


def cmd_memory_show(artifact_id: str, root: str | Path = ".") -> str:
    artifact = _find_memory_artifact(get_store(root), artifact_id)
    return artifact.model_dump_json(indent=2) if artifact else f"Memory artifact not found: {artifact_id}"


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


def cmd_search(query: str, root: str | Path = ".", *, external_candidates: list[dict[str, object]] | None = None, limit: int = 10) -> str:
    return cmd_proof_search(query, root=root, external_candidates=external_candidates, limit=limit)


def cmd_provenance_show(target_id: str, root: str | Path = ".") -> str:
    return cmd_proof_provenance_show(target_id, root=root)
