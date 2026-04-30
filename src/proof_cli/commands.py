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
from .automation import (
    AutomationActionStatus,
    AutomationExecutionMode,
    AutomationPolicyDecision,
    AutomationPolicyProfile,
    AutomationRunStatus,
    AutomationTaskType,
    AutomationTraceEntry,
    AutomationTraceKind,
    default_policy_profile,
)
from .automation_eval import AutomationEvaluationRecord, replay_automation_benchmark
from .analysis import build_project_diagnostic_report
from .debug_tasks import ProofDebugTaskBatch, debug_task_batch_from_reports
from .exchange import (
    bundle_from_json,
    bundle_to_json,
    export_exchange_bundle,
    import_exchange_bundle,
    inspect_exchange_bundle,
    report_to_json,
    summarize_import_report,
    summarize_inspect_report,
)
from .export import build_export
from .evidence import EvidenceChain, build_evidence_chains
from .formal_bridge import FormalBridgeProofStep, machine_check_trace, translate_selection
from .formalization_recommendations import FormalizationRecommendation, rank_formalization_candidates
from .publication import (
    PublicationCitationKind,
    PublicationReleaseStatus,
    PublicationReadiness,
    PublicationVisibility,
    build_publication_bundle,
    build_publication_manifest,
    build_publication_paper,
    build_publication_supplement,
    create_publication_view,
    list_citation_provenance,
    list_publication_bundle_snapshots,
    list_publication_state_records,
    list_publication_views,
    list_release_records,
    list_verification_summaries,
    record_citation_provenance,
    record_editorial_note,
    record_publication_bundle_snapshot,
    record_release_approval,
    record_release_withdrawal,
    record_verification_summary,
    publication_paper_export,
    publication_supplement_export,
    render_publication_bundle,
    save_publication_workspace,
    set_publication_state,
    summarize_publication_bundle_snapshot,
    summarize_publication_citation,
    summarize_publication_release,
    summarize_publication_state,
    summarize_publication_verification,
    summarize_publication_view,
)
from .governance import (
    GovernanceAssetRecord,
    GovernanceAutomationRecord,
    GovernanceBenchmarkRecord,
    GovernancePackRecord,
    GovernancePolicyRecord,
    GovernanceRecommendationRecord,
    GovernanceReuseRecord,
    build_automation_run as build_governance_automation_run,
    get_automation_record,
    get_domain_pack_record,
    get_latest_policy_profile,
    get_reusable_asset_record,
    install_domain_pack,
    list_automation_records,
    list_benchmark_records,
    list_domain_pack_records,
    list_policy_records,
    list_recommendation_records,
    list_reusable_asset_records,
    list_reuse_records,
    publish_reusable_asset,
    record_automation_run,
    record_benchmark_replay,
    record_cross_project_recommendation,
    record_reuse_outcome,
    render_json,
    set_policy_profile,
    summarize_automation_record,
    summarize_benchmark_record,
    summarize_domain_pack,
    summarize_policy_record,
    summarize_recommendation_record,
    summarize_reusable_asset,
    summarize_reuse_record,
    update_domain_pack,
)
from .domain_packs import DomainPack
from .collaboration import (
    BranchComparison,
    BranchStatus,
    CollaborationPolicy,
    CollaborationRole,
    CommentThreadStatus,
    Contributor,
    ReviewGovernanceState,
    SharedAssetPublicationStatus,
    add_comment,
    compare_branches,
    create_branch,
    get_branch,
    get_contributor,
    get_policy as get_collaboration_policy,
    list_branches,
    list_comment_threads,
    list_comments,
    list_contributors,
    list_publications,
    list_review_records,
    merge_branch,
    publish_shared_asset,
    record_review_decision,
    record_review_request,
    set_collaboration_policy,
    set_contributor_role,
    summarize_branch,
    summarize_comment,
    summarize_comment_thread,
    summarize_contributor,
    summarize_policy,
    summarize_publication,
    summarize_review_record,
    summarize_state as summarize_collaboration_state,
    upsert_contributor,
)
from .memory import MemoryArtifact, MemoryLayer, list_memory_artifacts, record_memory
from .recommendations import recommend_cross_project_assets
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
from .snapshot import create_snapshot
from .references import ReferenceRecord, ReferenceReviewStatus, ReferenceSourceType
from .rendering import render_status
from .reusable_assets import ReusableAsset
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
from .verification_broker import build_default_verification_broker, route_verification_fragment
from .verification_ir import (
    VerificationArtifact,
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
    VerificationSourceKind,
)
from .verification_results import list_verification_results, record_verification_result
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


def _load_model_json(value: str, model: type[object]):
    return model.model_validate_json(value)  # type: ignore[attr-defined]


def _load_model_json_list(values: list[str] | None, model: type[object]) -> list[object]:
    return [model.model_validate_json(value) for value in values or []]  # type: ignore[attr-defined]


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


def _render_retrieval_report(report) -> str:
    lines = [f"query: {report.query}"]
    context = report.project_context
    if context.current_theorem:
        lines.append(f"current theorem: {context.current_theorem}")
    if context.open_obligations:
        lines.append("obligations: " + ", ".join(context.open_obligations))
    if context.blockers:
        lines.append("blockers: " + ", ".join(context.blockers))
    if context.recent_memory:
        lines.append("recent memory: " + "; ".join(context.recent_memory[:3]))
    if context.explicit_neighborhood:
        lines.append("neighborhood: " + ", ".join(context.explicit_neighborhood[:5]))
    lines.append("sources: " + ", ".join(source.value for source in report.source_order))
    if report.candidates:
        lines.append("candidates:")
        for candidate in report.candidates:
            lines.append(
                _format_candidate_line(
                    candidate.rank,
                    candidate.title,
                    candidate.source_kind.value,
                    candidate.score,
                    candidate.id,
                )
            )
    else:
        lines.append("No candidates")
    return "\n".join(lines)


_BUG_SCAN_HISTORY_PREFIX = "proof_bug_scan:"
_BUG_REVIEW_HISTORY_PREFIX = "proof_bug_review:"
_BUG_REPAIR_HISTORY_PREFIX = "proof_bug_repair:"
_REASONING_HISTORY_PREFIX = "proof_reasoning:"
_DEBUG_BATCH_HISTORY_PREFIX = "proof_debug_batch:"
_FORMALIZATION_RECOMMENDATION_PREFIX = "formalization_recommendation:"
_VERIFICATION_FRAGMENT_PREFIX = "verification_fragment:"
_VERIFICATION_REVIEW_PREFIX = "verification_review:"
_VERIFICATION_TRACE_PREFIX = "verification_trace:"


def _state_marker(prefix: str, payload: dict[str, object]) -> str:
    return f"{prefix}{json.dumps(payload, sort_keys=True)}"


def _append_state_marker(store: ProjectStore, prefix: str, payload: dict[str, object], *, event_kind: str, message: str, entity_id: str | None = None) -> None:
    state = load_state(store)
    state.session_history.append(_state_marker(prefix, payload))
    save_state(store, state, message=message)
    append_event(store, event_kind, message, entity_id=entity_id, payload=payload)


def _verification_source_entry(store: ProjectStore, source_id: str) -> object | None:
    contract = get_contract(store, source_id)
    if contract is not None:
        return contract
    for obligation in list_obligations(store):
        if obligation.id == source_id:
            return obligation
    for fragment in _verification_fragments(store):
        if fragment.id == source_id:
            return fragment
    return None


def _verification_fragments(store: ProjectStore) -> list[VerificationFragment]:
    state = load_state(store)
    fragments: list[VerificationFragment] = []
    for entry in state.session_history:
        if not entry.startswith(_VERIFICATION_FRAGMENT_PREFIX):
            continue
        payload = entry.removeprefix(_VERIFICATION_FRAGMENT_PREFIX)
        fragments.append(VerificationFragment.model_validate_json(payload))
    return fragments


def _latest_verification_fragment(store: ProjectStore, source_id: str) -> VerificationFragment | None:
    for fragment in reversed(_verification_fragments(store)):
        if (
            fragment.id == source_id
            or fragment.source_id == source_id
            or fragment.scope.theorem_id == source_id
            or fragment.scope.obligation_id == source_id
            or fragment.scope.goal_id == source_id
            or fragment.scope.proof_step_id == source_id
        ):
            return fragment
    return None


def _verification_results(store: ProjectStore) -> list[object]:
    return list_verification_results(store)


def _latest_verification_result(store: ProjectStore, source_id: str) -> object | None:
    for record in reversed(_verification_results(store)):
        result = record.result
        if (
            result.id == source_id
            or result.fragment_id == source_id
            or record.source_id == source_id
        ):
            return record
        fragment = _latest_verification_fragment(store, result.fragment_id)
        if fragment is not None and (
            fragment.source_id == source_id
            or fragment.scope.theorem_id == source_id
            or fragment.scope.obligation_id == source_id
            or fragment.scope.goal_id == source_id
            or fragment.scope.proof_step_id == source_id
        ):
            return record
    return None


def _dedupe_verification_result_records(records: list[object]) -> list[object]:
    seen: set[str] = set()
    unique: list[object] = []
    for record in reversed(records):
        result_id = getattr(getattr(record, "result", None), "id", None)
        if result_id is None or result_id in seen:
            continue
        seen.add(result_id)
        unique.append(record)
    unique.reverse()
    return unique


def _verification_summary_payload(
    store: ProjectStore,
    *,
    source_id: str,
    fragment: VerificationFragment | None = None,
    result_record: object | None = None,
) -> dict[str, object]:
    state = load_state(store)
    fragment = fragment or _latest_verification_fragment(store, source_id)
    if result_record is None and fragment is not None:
        result_record = _latest_verification_result(store, fragment.id)
    if result_record is None:
        result_record = _latest_verification_result(store, source_id)
    recommendation: FormalizationRecommendation | None = None
    if fragment is not None:
        ranked = rank_formalization_candidates([fragment], broker=build_default_verification_broker())
        recommendation = ranked[0] if ranked else None
    payload: dict[str, object] = {
        "project_id": state.project_id,
        "source_id": source_id,
        "current_context": list(state.current_context),
        "open_obligations": list(state.open_obligations),
        "fragment": fragment.model_dump(mode="json") if fragment is not None else None,
        "machine_check_status": fragment.status.value if fragment is not None else "missing",
        "translation_status": fragment.translation_status.value if fragment is not None else "missing",
        "result": result_record.model_dump(mode="json") if result_record is not None else None,
        "recommendation": recommendation.model_dump(mode="json") if recommendation is not None else None,
    }
    if fragment is not None:
        payload["provenance"] = fragment.provenance.model_dump(mode="json")
    return payload


def _persist_verification_fragment(
    store: ProjectStore,
    fragment: VerificationFragment,
    *,
    event_kind: str,
    message: str,
) -> VerificationFragment:
    _append_state_marker(
        store,
        _VERIFICATION_FRAGMENT_PREFIX,
        fragment.model_dump(mode="json"),
        event_kind=event_kind,
        message=message,
        entity_id=fragment.id,
    )
    return fragment


def _translate_source_fragment(
    store: ProjectStore,
    source_id: str,
    *,
    backend_target: str | None = None,
    route_id: str | None = None,
) -> VerificationFragment | str:
    state = load_state(store)
    source = _verification_source_entry(store, source_id)
    if source is None:
        return f"verify:blocked:source {source_id} not found"

    if isinstance(source, VerificationFragment):
        provenance = source.provenance.model_copy(
            update={
                "derived_from_ids": list(dict.fromkeys([*source.provenance.derived_from_ids, source.id])),
                "machine_path": [*source.provenance.machine_path, "clone verification fragment"],
            }
        )
        fragment = source.model_copy(
            update={
                "id": f"vfrag_{source.id.split('_', 1)[-1]}_{len(_verification_fragments(store)) + 1}",
                "scope": source.scope.model_copy(update={"route_id": route_id or source.scope.route_id}),
                "provenance": provenance,
                "status": VerificationFragmentStatus.queued_for_verification,
                "translation_status": source.translation_status,
                "backend_target": backend_target or source.backend_target,
                "result_id": None,
                "updated_at": source.updated_at,
            }
        )
        return fragment

    translation = translate_selection(
        [source],
        project_id=state.project_id,
        route_id=route_id,
        backend_target=backend_target,
    )
    if translation.failures:
        return f"verify:blocked:translation_failed:{translation.failures[0].reason}"
    fragment = translation.fragments[0]
    routed_fragment, _ = route_verification_fragment(fragment, broker=build_default_verification_broker())
    if backend_target is not None:
        routed_fragment = routed_fragment.model_copy(update={"backend_target": backend_target})
    return routed_fragment


def _run_machine_check(
    store: ProjectStore,
    fragment: VerificationFragment,
    *,
    backend_target: str | None = None,
    summary: str = "",
) -> tuple[VerificationFragment, VerificationResult, VerificationResult | None]:
    backend = backend_target or fragment.backend_target or "proof_assistant"
    checks: list[str] = []
    if fragment.side_conditions:
        checks.extend(condition.statement for condition in fragment.side_conditions)
    if fragment.theorem_applications:
        checks.extend(application.statement for application in fragment.theorem_applications)
    if fragment.translation_status == VerificationFragmentStatus.translation_failed:
        failed_fragment = fragment.record_translation_failure("translation failed before run")
        result = VerificationResult(
            fragment_id=fragment.id,
            backend=backend,
            summary="translation failed before machine-check",
            review_status=VerificationReviewStatus.rejected_by_human,
            notes=summary or "translation failure",
            metadata={"checks": checks, "fragment_status": failed_fragment.status.value},
        )
        return failed_fragment, result, None

    if fragment.status == VerificationFragmentStatus.stale_after_change:
        result = VerificationResult(
            fragment_id=fragment.id,
            backend=backend,
            summary="fragment is stale after dependency change",
            review_status=VerificationReviewStatus.rejected_by_human,
            notes=summary or "stale fragment",
            metadata={"checks": checks},
        )
        return fragment, result, None

    if fragment.theorem_applications and any(application.fragile for application in fragment.theorem_applications):
        result = VerificationResult(
            fragment_id=fragment.id,
            backend=backend,
            summary=summary or "machine-check completed for fragile theorem application",
            artifacts=[machine_check_trace(fragment, backend=backend, summary=summary or "fragile application checked")],
            notes="fragile theorem application checked with explicit status",
            metadata={"checks": checks, "fragile": True},
        )
        return fragment.record_machine_check(result_id=result.id, backend_target=backend), result, None

    result = VerificationResult(
        fragment_id=fragment.id,
        backend=backend,
        summary=summary or "machine-check completed",
        artifacts=[machine_check_trace(fragment, backend=backend, summary=summary or "machine-check completed")],
        notes=summary or "machine-check completed",
        metadata={"checks": checks},
    )
    return fragment.record_machine_check(result_id=result.id, backend_target=backend), result, None


def _record_verification_result(
    store: ProjectStore,
    fragment: VerificationFragment,
    result: VerificationResult,
    *,
    theorem_id: str | None = None,
    obligation_id: str | None = None,
    blocker_id: str | None = None,
    proof_step_id: str | None = None,
    route_id: str | None = None,
    notes: str = "",
):
    record = record_verification_result(
        store,
        fragment,
        result,
        theorem_id=theorem_id,
        obligation_id=obligation_id,
        blocker_id=blocker_id,
        proof_step_id=proof_step_id,
        route_id=route_id,
        notes=notes,
    )
    _append_state_marker(
        store,
        _VERIFICATION_REVIEW_PREFIX,
        {
            "fragment_id": fragment.id,
            "result_id": result.id,
            "review_status": result.review_status.value,
            "fragment_status": fragment.status.value,
            "backend": result.backend,
        },
        event_kind="verification_result_reviewed",
        message=f"recorded review state for verification result {result.id}",
        entity_id=result.id,
    )
    return record


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
    return _render_retrieval_report(report)


def cmd_proof_retrieve(
    query: str,
    root: str | Path = ".",
    *,
    external_candidates: list[dict[str, object]] | None = None,
    limit: int = 10,
) -> str:
    store = get_store(root)
    _append_history(store, f"retrieve:{query}", message=f"retrieved {query}")
    report = retrieve_candidates(
        store,
        query=query,
        external_candidates=external_candidates,
        limit=limit,
    )
    return report.model_dump_json(indent=2)


def cmd_project_analyze(root: str | Path = ".", *, query: str = "", limit: int = 5) -> str:
    store = get_store(root)
    _append_history(store, f"analyze:{query}", message=f"analyzed {query or 'current project'}")
    report = build_project_diagnostic_report(store, query=query or None, limit=limit)
    return render_json(report)


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


def cmd_proof_formalize_recommend(source_id: str, root: str | Path = ".", *, backend_target: str = "", notes: str = "") -> str:
    store = get_store(root)
    fragment_or_error = _translate_source_fragment(store, source_id, backend_target=backend_target or None)
    if isinstance(fragment_or_error, str):
        return fragment_or_error
    fragment = fragment_or_error
    if notes:
        fragment = fragment.model_copy(
            update={
                "notes": notes if not fragment.notes else f"{fragment.notes}; {notes}",
                "provenance": fragment.provenance.model_copy(
                    update={
                        "machine_path": [*fragment.provenance.machine_path, "formalization recommendation"],
                    }
                ),
            }
        )
    _persist_verification_fragment(
        store,
        fragment,
        event_kind="verification_fragment_recommended",
        message=f"recommended formalization for {source_id}",
    )
    recommendation = rank_formalization_candidates([fragment], broker=build_default_verification_broker())[0]
    _append_state_marker(
        store,
        _FORMALIZATION_RECOMMENDATION_PREFIX,
        recommendation.model_dump(mode="json"),
        event_kind="formalization_recommendation_recorded",
        message=f"recorded formalization recommendation for {source_id}",
        entity_id=fragment.id,
    )
    return json.dumps(
        {
            "source_id": source_id,
            "fragment": fragment.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
        },
        indent=2,
    )


def cmd_proof_formalize_show(source_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    recommendation = None
    if fragment is not None:
        ranked = rank_formalization_candidates([fragment], broker=build_default_verification_broker())
        recommendation = ranked[0] if ranked else None
    if fragment is None:
        return f"formalize:blocked:source {source_id} not found"
    payload = {
        "source_id": source_id,
        "fragment": fragment.model_dump(mode="json"),
        "recommendation": recommendation.model_dump(mode="json") if recommendation is not None else None,
        "machine_check_status": fragment.status.value,
        "translation_status": fragment.translation_status.value,
        "provenance": fragment.provenance.model_dump(mode="json"),
    }
    return json.dumps(payload, indent=2)


def cmd_proof_formalize_edit(
    source_id: str,
    root: str | Path = ".",
    *,
    backend_target: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    if fragment is None:
        translated = _translate_source_fragment(store, source_id, backend_target=backend_target or None)
        if isinstance(translated, str):
            return translated
        fragment = translated
    update_data: dict[str, object] = {}
    if backend_target:
        update_data["backend_target"] = backend_target
    if notes:
        update_data["notes"] = notes if not fragment.notes else f"{fragment.notes}; {notes}"
    update_data["provenance"] = fragment.provenance.model_copy(
        update={
            "machine_path": [*fragment.provenance.machine_path, "formalization edit"],
        }
    )
    edited = fragment.model_copy(update=update_data)
    _persist_verification_fragment(
        store,
        edited,
        event_kind="verification_fragment_edited",
        message=f"edited formalization for {source_id}",
    )
    recommendation = rank_formalization_candidates([edited], broker=build_default_verification_broker())[0]
    _append_state_marker(
        store,
        _FORMALIZATION_RECOMMENDATION_PREFIX,
        recommendation.model_dump(mode="json"),
        event_kind="formalization_recommendation_recorded",
        message=f"updated formalization recommendation for {source_id}",
        entity_id=edited.id,
    )
    return json.dumps(
        {
            "source_id": source_id,
            "fragment": edited.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
        },
        indent=2,
    )


def cmd_proof_verify_queue(
    source_id: str,
    root: str | Path = ".",
    *,
    backend_target: str = "",
    route_id: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    fragment_or_error = _translate_source_fragment(store, source_id, backend_target=backend_target or None, route_id=route_id or None)
    if isinstance(fragment_or_error, str):
        return fragment_or_error
    fragment = fragment_or_error
    if notes:
        fragment = fragment.model_copy(
            update={
                "notes": notes if not fragment.notes else f"{fragment.notes}; {notes}",
            }
        )
    queued = fragment.queue_for_verification(backend_target=backend_target or fragment.backend_target)
    _persist_verification_fragment(
        store,
        queued,
        event_kind="verification_fragment_queued",
        message=f"queued verification for {source_id}",
    )
    recommendation = rank_formalization_candidates([queued], broker=build_default_verification_broker())[0]
    return json.dumps(
        {
            "source_id": source_id,
            "machine_check_status": queued.status.value,
            "translation_status": queued.translation_status.value,
            "fragment": queued.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
        },
        indent=2,
    )


def cmd_proof_verify_run(
    source_id: str,
    root: str | Path = ".",
    *,
    backend_target: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    if fragment is None:
        queued = cmd_proof_verify_queue(source_id, root=root, backend_target=backend_target, notes=notes)
        if queued.startswith("verify:blocked:"):
            return queued
        fragment_payload = json.loads(queued)["fragment"]
        fragment = VerificationFragment.model_validate(fragment_payload)
    run_fragment, result, _ = _run_machine_check(store, fragment, backend_target=backend_target or None, summary=notes)
    scoped_result = _record_verification_result(
        store,
        run_fragment,
        result,
        theorem_id=run_fragment.scope.theorem_id,
        obligation_id=run_fragment.scope.obligation_id,
        blocker_id=run_fragment.scope.blocker_id,
        proof_step_id=run_fragment.scope.proof_step_id,
        route_id=run_fragment.scope.route_id,
        notes=notes,
    )
    _persist_verification_fragment(
        store,
        run_fragment,
        event_kind="verification_fragment_ran",
        message=f"ran machine check for {source_id}",
    )
    payload = {
        "source_id": source_id,
        "machine_check_status": run_fragment.status.value,
        "translation_status": run_fragment.translation_status.value,
        "fragment": run_fragment.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "verification_record": scoped_result.model_dump(mode="json"),
        "trace": machine_check_trace(run_fragment, backend=result.backend, summary=result.summary).model_dump(mode="json"),
    }
    return json.dumps(payload, indent=2)


def cmd_proof_verify_status(source_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    result_record = _latest_verification_result(store, source_id)
    payload = _verification_summary_payload(store, source_id=source_id, fragment=fragment, result_record=result_record)
    payload["results"] = [
        record.model_dump(mode="json")
        for record in _dedupe_verification_result_records(
            [record for record in _verification_results(store) if record.source_id == source_id or getattr(record.result, "fragment_id", "") == source_id]
        )
    ]
    return json.dumps(payload, indent=2)


def cmd_proof_verify_result(source_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    record = _latest_verification_result(store, source_id)
    if record is None:
        return f"verify:result:not-found:{source_id}"
    return json.dumps(record.model_dump(mode="json"), indent=2)


def cmd_proof_verify_accept(source_id: str, root: str | Path = ".", *, notes: str = "") -> str:
    store = get_store(root)
    record = _latest_verification_result(store, source_id)
    if record is None:
        return f"verify:accept:blocked:verification result {source_id} not found"
    fragment = _latest_verification_fragment(store, record.result.fragment_id)
    if fragment is None:
        return f"verify:accept:blocked:fragment {record.result.fragment_id} not found"
    result = record.result.accept(notes=notes or None)
    updated_fragment = fragment.accept_after_review(result_id=result.id, notes=notes)
    _persist_verification_fragment(
        store,
        updated_fragment,
        event_kind="verification_fragment_accepted",
        message=f"accepted verification result {result.id}",
    )
    scoped_record = _record_verification_result(
        store,
        updated_fragment,
        result,
        theorem_id=updated_fragment.scope.theorem_id,
        obligation_id=updated_fragment.scope.obligation_id,
        blocker_id=updated_fragment.scope.blocker_id,
        proof_step_id=updated_fragment.scope.proof_step_id,
        route_id=updated_fragment.scope.route_id,
        notes=notes,
    )
    return json.dumps(
        {
            "source_id": source_id,
            "machine_check_status": updated_fragment.status.value,
            "translation_status": updated_fragment.translation_status.value,
            "fragment": updated_fragment.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "verification_record": scoped_record.model_dump(mode="json"),
        },
        indent=2,
    )


def cmd_proof_verify_reject(source_id: str, root: str | Path = ".", *, notes: str = "") -> str:
    store = get_store(root)
    record = _latest_verification_result(store, source_id)
    if record is None:
        return f"verify:reject:blocked:verification result {source_id} not found"
    fragment = _latest_verification_fragment(store, record.result.fragment_id)
    if fragment is None:
        return f"verify:reject:blocked:fragment {record.result.fragment_id} not found"
    result = record.result.reject(notes=notes or None)
    updated_fragment = fragment.reject_by_human(result_id=result.id, notes=notes)
    _persist_verification_fragment(
        store,
        updated_fragment,
        event_kind="verification_fragment_rejected",
        message=f"rejected verification result {result.id}",
    )
    scoped_record = _record_verification_result(
        store,
        updated_fragment,
        result,
        theorem_id=updated_fragment.scope.theorem_id,
        obligation_id=updated_fragment.scope.obligation_id,
        blocker_id=updated_fragment.scope.blocker_id,
        proof_step_id=updated_fragment.scope.proof_step_id,
        route_id=updated_fragment.scope.route_id,
        notes=notes,
    )
    return json.dumps(
        {
            "source_id": source_id,
            "machine_check_status": updated_fragment.status.value,
            "translation_status": updated_fragment.translation_status.value,
            "fragment": updated_fragment.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "verification_record": scoped_record.model_dump(mode="json"),
        },
        indent=2,
    )


def cmd_proof_verify_stale(
    source_id: str,
    root: str | Path = ".",
    *,
    reason: str = "",
    changed_dependency_ids: list[str] | None = None,
) -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    if fragment is None:
        return f"verify:stale:blocked:source {source_id} not found"
    changed_versions = [
        VerificationDependencyVersion(
            dependency_id=dependency_id,
            version=fragment.ir_version + 1,
            kind="external_reference",
            digest=f"stale:{dependency_id}:{fragment.ir_version + 1}",
        )
        for dependency_id in (changed_dependency_ids or [])
    ]
    stale_fragment = fragment.mark_stale_after_change(changed_dependency_versions=changed_versions or None, reason=reason)
    _persist_verification_fragment(
        store,
        stale_fragment,
        event_kind="verification_fragment_stale",
        message=f"marked verification fragment {stale_fragment.id} stale",
    )
    return json.dumps(
        {
            "source_id": source_id,
            "machine_check_status": stale_fragment.status.value,
            "translation_status": stale_fragment.translation_status.value,
            "fragment": stale_fragment.model_dump(mode="json"),
        },
        indent=2,
    )


def cmd_proof_revalidate(
    source_id: str,
    root: str | Path = ".",
    *,
    backend_target: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    if fragment is None:
        return f"revalidate:blocked:source {source_id} not found"
    stale_fragment = fragment.mark_stale_after_change(reason=notes or "revalidated after dependency change")
    _persist_verification_fragment(
        store,
        stale_fragment,
        event_kind="verification_fragment_stale",
        message=f"marked verification fragment {stale_fragment.id} stale for revalidation",
    )
    if fragment.source_type == VerificationSourceKind.theorem_contract:
        source = get_contract(store, fragment.source_id)
        if source is None:
            return f"revalidate:blocked:source {fragment.source_id} not found"
        translation = translate_selection([source], project_id=load_state(store).project_id, route_id=fragment.scope.route_id, backend_target=backend_target or fragment.backend_target)
        if translation.failures:
            return f"revalidate:blocked:translation_failed:{translation.failures[0].reason}"
        revalidated = translation.fragments[0]
    elif fragment.source_type == VerificationSourceKind.proof_obligation:
        obligation = next((item for item in list_obligations(store) if item.id == fragment.source_id), None)
        if obligation is None:
            return f"revalidate:blocked:source {fragment.source_id} not found"
        translation = translate_selection([obligation], project_id=load_state(store).project_id, route_id=fragment.scope.route_id, backend_target=backend_target or fragment.backend_target)
        if translation.failures:
            return f"revalidate:blocked:translation_failed:{translation.failures[0].reason}"
        revalidated = translation.fragments[0]
    else:
        revalidated = fragment.model_copy(
            update={
                "id": f"vfrag_{fragment.id.split('_', 1)[-1]}_{len(_verification_fragments(store)) + 1}",
                "backend_target": backend_target or fragment.backend_target,
            }
        )
    revalidated = revalidated.model_copy(
        update={
            "provenance": revalidated.provenance.model_copy(
                update={
                    "derived_from_ids": list(dict.fromkeys([*revalidated.provenance.derived_from_ids, fragment.id])),
                    "machine_path": [*revalidated.provenance.machine_path, "revalidate fragment"],
                }
            )
        }
    )
    revalidated = revalidated.queue_for_verification(backend_target=backend_target or revalidated.backend_target)
    _persist_verification_fragment(
        store,
        revalidated,
        event_kind="verification_fragment_revalidated",
        message=f"revalidated verification fragment {source_id}",
    )
    return json.dumps(
        {
            "source_id": source_id,
            "stale_fragment": stale_fragment.model_dump(mode="json"),
            "revalidated_fragment": revalidated.model_dump(mode="json"),
            "machine_check_status": revalidated.status.value,
            "translation_status": revalidated.translation_status.value,
        },
        indent=2,
    )


def cmd_proof_trace_machine_check(source_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    fragment = _latest_verification_fragment(store, source_id)
    if fragment is None:
        return f"trace:machine-check:blocked:source {source_id} not found"
    record = _latest_verification_result(store, source_id)
    trace_artifact: VerificationArtifact | None = None
    if record is not None:
        trace_artifact = machine_check_trace(fragment, backend=record.result.backend, summary=record.result.summary)
    payload = _verification_summary_payload(store, source_id=source_id, fragment=fragment, result_record=record)
    payload["trace"] = trace_artifact.model_dump(mode="json") if trace_artifact is not None else None
    _append_state_marker(
        store,
        _VERIFICATION_TRACE_PREFIX,
        payload,
        event_kind="verification_trace_recorded",
        message=f"traced machine check for {source_id}",
        entity_id=fragment.id,
    )
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


def cmd_publication_list(root: str | Path = ".", *, object_type: str = "") -> str:
    store = get_store(root)
    records = list_publication_state_records(store, object_type=object_type)
    if not records:
        return "No publication claims"
    lines = ["Publication claims:"]
    lines.extend(f"- {summarize_publication_state(record)}" for record in records)
    return "\n".join(lines)


def cmd_publication_show(object_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    records = list_publication_state_records(store, object_id=object_id)
    if not records:
        return f"Publication claim not found: {object_id}"
    return json.dumps([record.model_dump(mode="json") for record in records], indent=2)


def cmd_publication_set(
    object_id: str,
    readiness: str,
    root: str | Path = ".",
    *,
    object_type: str = "theorem_contract",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    reason: str = "",
    citation_kind: str = "",
    internal_only: bool = False,
    editorial_note: list[str] | None = None,
    supporting_reference_id: list[str] | None = None,
    supporting_theorem_id: list[str] | None = None,
    release_status: str = "draft",
    release_notes: str = "",
) -> str:
    store = get_store(root)
    release_status_value = PublicationReleaseStatus.approved if release_status == "draft" else PublicationReleaseStatus(release_status)
    state_record = set_publication_state(
        store,
        object_id,
        PublicationReadiness(readiness),
        object_type=object_type,
        display_name=display_name,
        title=title,
        section_placement=section_placement,
        reason=reason,
        citation_kind=PublicationCitationKind(citation_kind) if citation_kind else None,
        internal_only=internal_only,
        editorial_notes=editorial_note,
        supporting_reference_ids=supporting_reference_id,
        supporting_theorem_ids=supporting_theorem_id,
        release_status=release_status_value,
        release_notes=release_notes,
        updated_by=display_name or "human",
    )
    if readiness == "paper_ready":
        view_audience = "paper"
        view_visibility = PublicationVisibility.paper
    elif readiness == "supplement_ready":
        view_audience = "supplement"
        view_visibility = PublicationVisibility.supplement
    else:
        view_audience = "internal"
        view_visibility = PublicationVisibility.internal_only
    if internal_only:
        view_visibility = PublicationVisibility.internal_only
    if title or section_placement or citation_kind or editorial_note or supporting_reference_id or supporting_theorem_id or release_notes:
        view = create_publication_view(
            store,
            name=title or display_name or object_id,
            scope=object_type,
            audience=view_audience,
            visibility=view_visibility,
            included_object_ids=[object_id],
            section_mapping={object_id: section_placement} if section_placement else None,
            notes=release_notes or reason,
        )
        record_editorial_note(store, object_id, release_notes or reason, section_label=section_placement, updated_by=display_name or "human")
        if supporting_reference_id:
            for reference_id in supporting_reference_id:
                record_citation_provenance(store, object_id, reference_id, usage_type=citation_kind or "project-original", citation_note=reason)
        if supporting_theorem_id:
            for theorem_id in supporting_theorem_id:
                record_citation_provenance(store, theorem_id, object_id, usage_type=citation_kind or "project-original", citation_note=reason)
        if release_status and release_status != "draft":
            release_enum = PublicationReleaseStatus(release_status)
            if release_enum == PublicationReleaseStatus.withdrawn:
                record_release_withdrawal(store, view.id, withdrawn_by=[display_name] if display_name else [], reason=release_notes or reason)
            else:
                record_release_approval(store, view.id, approved_by=[display_name] if display_name else [], notes=release_notes or reason, status=release_enum)
    return state_record.model_dump_json(indent=2)


def cmd_publication_view(root: str | Path = ".", *, audience: str = "paper") -> str:
    store = get_store(root)
    state_records = list_publication_state_records(store)
    views = [view for view in list_publication_views(store) if audience == "" or view.visibility.value == audience or audience == "paper" and view.visibility == PublicationVisibility.paper]
    lines = ["Publication workspace:"]
    lines.append("State records:")
    if state_records:
        lines.extend(f"- {summarize_publication_state(record)}" for record in state_records)
    else:
        lines.append("- none")
    lines.append("Views:")
    if views:
        lines.extend(f"- {summarize_publication_view(view)}" for view in views)
    else:
        lines.append("- none")
    return "\n".join(lines)


def cmd_publication_export(root: str | Path = ".", *, audience: str = "paper", format: str = "paper") -> str:
    store = get_store(root)
    if format == "paper":
        return publication_paper_export(store)
    if format == "supplement":
        return publication_supplement_export(store)
    if format == "bundle":
        return render_publication_bundle(build_publication_bundle(store))
    if format == "manifest":
        return json.dumps(build_publication_manifest(store), indent=2, sort_keys=True)
    return f"publication:unsupported-format:{format}"


def cmd_publication_release(
    root: str | Path = ".",
    *,
    audience: str = "paper",
    status: str = "approved",
    approved_by: list[str] | None = None,
    rationale: str = "",
    note: str = "",
) -> str:
    store = get_store(root)
    record = record_release_approval(store, bundle_id=audience, approved_by=approved_by, notes=note or rationale, status=PublicationReleaseStatus(status))
    return record.model_dump_json(indent=2)


def cmd_publication_withdraw(
    release_id: str,
    root: str | Path = ".",
    *,
    rationale: str = "",
    approved_by: list[str] | None = None,
) -> str:
    release = record_release_withdrawal(get_store(root), release_id, withdrawn_by=approved_by, reason=rationale)
    return release.model_dump_json(indent=2)


def cmd_init(root: str | Path = ".") -> str:
    store = ensure_project(root)
    state = load_state(store)
    return f"Initialized proof project {state.project_id} at {store.db_path}"


def cmd_status(root: str | Path = ".") -> str:
    store = get_store(root)
    return render_status(summarize_state(store)) + "\n" + summarize_collaboration_state(store)


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
    created_by: str = "human",
    updated_by: str = "human",
    contributor: list[str] | None = None,
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
        created_by=created_by,
        updated_by=updated_by,
        contributors=contributor,
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


def cmd_exchange_export(root: str | Path = ".", *, note: str = "") -> str:
    return bundle_to_json(export_exchange_bundle(get_store(root), note=note))


def cmd_exchange_import(bundle_json: str, root: str | Path = ".") -> str:
    report = import_exchange_bundle(get_store(root), bundle_from_json(bundle_json))
    return report_to_json(report)


def cmd_handoff_create(root: str | Path = ".", *, note: str = "") -> str:
    snapshot = create_snapshot(get_store(root), note=note)
    bundle = export_exchange_bundle(get_store(root), note=note or snapshot.handoff_note)
    return bundle_to_json(bundle)


def cmd_handoff_inspect(bundle_json: str = "", root: str | Path = ".") -> str:
    if bundle_json:
        report = inspect_exchange_bundle(bundle_from_json(bundle_json))
        return report_to_json(report)
    store = get_store(root)
    bundle = export_exchange_bundle(store)
    report = inspect_exchange_bundle(bundle)
    return report_to_json(report)


def cmd_contributor_list(root: str | Path = ".", *, team_id: str = "", status: str = "") -> str:
    records = list_contributors(get_store(root), team_id=team_id, status=status)
    if not records:
        return "No contributors"
    return "\n".join(summarize_contributor(record) for record in records)


def cmd_role_show(contributor_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    contributor = get_contributor(store, contributor_id)
    if contributor is None:
        return f"Contributor not found: {contributor_id}"
    policy = get_collaboration_policy(store)
    payload = {
        "contributor": contributor.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json") if policy is not None else None,
    }
    return json.dumps(payload, indent=2)


def cmd_review_request(
    object_type: str,
    object_id: str,
    root: str | Path = ".",
    *,
    reviewer_id: str = "human",
    rationale: str = "",
) -> str:
    record = record_review_request(get_store(root), object_type, object_id, reviewer_id=reviewer_id, rationale=rationale)
    return json.dumps(record.model_dump(mode="json"), indent=2)


def cmd_review_list(root: str | Path = ".", *, object_type: str = "", object_id: str = "") -> str:
    records = list_review_records(get_store(root), object_type=object_type, object_id=object_id)
    if not records:
        return "No review records"
    return "\n".join(summarize_review_record(record) for record in records)


def cmd_review_decide(
    review_id: str,
    decision: str,
    root: str | Path = ".",
    *,
    reviewer_id: str = "human",
    rationale: str = "",
) -> str:
    record = record_review_decision(
        get_store(root),
        review_id,
        ReviewGovernanceState(decision),
        reviewer_id=reviewer_id,
        rationale=rationale,
    )
    return json.dumps(record.model_dump(mode="json"), indent=2)


def cmd_comment_add(
    object_type: str,
    object_id: str,
    content: str,
    root: str | Path = ".",
    *,
    author_id: str = "human",
    thread_id: str = "",
    status: str = "open",
) -> str:
    comment = add_comment(
        get_store(root),
        object_type,
        object_id,
        author_id=author_id,
        content=content,
        thread_id=thread_id,
        status=CommentThreadStatus(status),
    )
    return json.dumps(comment.model_dump(mode="json"), indent=2)


def cmd_comment_list(
    root: str | Path = ".",
    *,
    thread_id: str = "",
    object_type: str = "",
    object_id: str = "",
) -> str:
    threads = list_comment_threads(get_store(root), object_type=object_type, object_id=object_id)
    comments = list_comments(get_store(root), thread_id=thread_id, object_type=object_type, object_id=object_id)
    if not threads and not comments:
        return "No comments"
    lines = ["Comment threads:"]
    if threads:
        lines.extend(f"- {summarize_comment_thread(thread)}" for thread in threads)
    else:
        lines.append("- none")
    lines.append("Comments:")
    if comments:
        lines.extend(f"- {summarize_comment(comment)}" for comment in comments)
    else:
        lines.append("- none")
    return "\n".join(lines)


def cmd_branch_create(
    scope: str,
    name: str,
    root: str | Path = ".",
    *,
    created_by: str = "human",
    derived_from: str = "",
    notes: str = "",
    downstream_asset_id: list[str] | None = None,
) -> str:
    branch = create_branch(
        get_store(root),
        scope,
        name,
        created_by=created_by,
        derived_from=derived_from or None,
        notes=notes,
        downstream_asset_ids=downstream_asset_id or [],
    )
    return json.dumps(branch.model_dump(mode="json"), indent=2)


def cmd_branch_list(root: str | Path = ".", *, scope: str = "", status: str = "") -> str:
    branches = list_branches(get_store(root), scope=scope, status=status)
    if not branches:
        return "No branches"
    return "\n".join(summarize_branch(branch) for branch in branches)


def cmd_branch_compare(left_branch_id: str, right_branch_id: str, root: str | Path = ".") -> str:
    comparison = compare_branches(get_store(root), left_branch_id, right_branch_id)
    return json.dumps(comparison.model_dump(mode="json"), indent=2)


def cmd_branch_merge(
    branch_id: str,
    root: str | Path = ".",
    *,
    into_branch_id: str = "",
    reviewer_id: str = "human",
    rationale: str = "",
) -> str:
    branch = merge_branch(get_store(root), branch_id, into_branch_id=into_branch_id or None, reviewer_id=reviewer_id, rationale=rationale)
    return json.dumps(branch.model_dump(mode="json"), indent=2)


def cmd_goal_open(theorem_id: str, root: str | Path = ".") -> str:
    return cmd_goal_set(theorem_id, root=root)


def cmd_search(query: str, root: str | Path = ".", *, external_candidates: list[dict[str, object]] | None = None, limit: int = 10) -> str:
    return cmd_proof_search(query, root=root, external_candidates=external_candidates, limit=limit)


def cmd_provenance_show(target_id: str, root: str | Path = ".") -> str:
    return cmd_proof_provenance_show(target_id, root=root)


def cmd_proof_asset_list(root: str | Path = ".", *, project_id: str = "", kind: str = "", status: str = "") -> str:
    records = list_reusable_asset_records(get_store(root), project_id=project_id, kind=kind, status=status)
    if not records:
        return "No reusable assets"
    return "\n".join(summarize_reusable_asset(record) for record in records)


def cmd_proof_asset_show(asset_id: str, root: str | Path = ".") -> str:
    record = get_reusable_asset_record(get_store(root), asset_id)
    return render_json(record) if record is not None else f"Reusable asset not found: {asset_id}"


def cmd_proof_asset_publish(
    asset_json: str,
    root: str | Path = ".",
    *,
    review_action: str = "publish",
    reviewer: str = "human",
    notes: str = "",
) -> str:
    store = get_store(root)
    asset = _load_model_json(asset_json, ReusableAsset)
    record = publish_reusable_asset(store, asset, review_action=review_action, reviewer=reviewer, notes=notes)
    publish_shared_asset(
        store,
        record.asset.id,
        published_to="team_library" if record.asset.is_reusable() else "project_library",
        created_by=reviewer,
        approved_by=[reviewer],
        status=SharedAssetPublicationStatus.approved if record.asset.is_reusable() else SharedAssetPublicationStatus.proposed_for_review,
        provenance_notes=notes or record.asset.provenance.notes,
    )
    return render_json(record)


def cmd_proof_asset_review(
    asset_id: str,
    action: str,
    root: str | Path = ".",
    *,
    reviewer: str = "human",
    notes: str = "",
) -> str:
    store = get_store(root)
    existing = get_reusable_asset_record(store, asset_id)
    if existing is None:
        return f"asset:review:blocked:asset {asset_id} not found"
    record = publish_reusable_asset(store, existing.asset, review_action=action, reviewer=reviewer, notes=notes)
    publish_shared_asset(
        store,
        record.asset.id,
        published_to="team_library" if record.asset.is_reusable() else "project_library",
        created_by=reviewer,
        approved_by=[reviewer],
        status=SharedAssetPublicationStatus.approved if record.asset.is_reusable() else SharedAssetPublicationStatus.proposed_for_review,
        provenance_notes=notes or record.asset.provenance.notes,
    )
    return render_json(record)


def cmd_proof_pack_list(root: str | Path = ".", *, project_id: str = "") -> str:
    records = list_domain_pack_records(get_store(root), project_id=project_id)
    if not records:
        return "No domain packs"
    return "\n".join(summarize_domain_pack(record) for record in records)


def cmd_proof_pack_show(pack_id: str, root: str | Path = ".") -> str:
    record = get_domain_pack_record(get_store(root), pack_id)
    return render_json(record) if record is not None else f"Domain pack not found: {pack_id}"


def cmd_proof_pack_install(
    pack_json: str,
    root: str | Path = ".",
    *,
    installed_by: str = "human",
    project_tags: list[str] | None = None,
    available_asset_ids: list[str] | None = None,
    available_asset_kinds: list[str] | None = None,
    notation_profile: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    pack = _load_model_json(pack_json, DomainPack)
    record = install_domain_pack(
        store,
        pack,
        installed_by=installed_by,
        project_tags=project_tags or [],
        available_asset_ids=available_asset_ids or [],
        available_asset_kinds=available_asset_kinds or [],
        notation_profile=notation_profile,
        notes=notes,
    )
    return render_json(record)


def cmd_proof_pack_update(
    pack_json: str,
    root: str | Path = ".",
    *,
    reviewer: str = "human",
    notes: str = "",
) -> str:
    store = get_store(root)
    pack = _load_model_json(pack_json, DomainPack)
    record = update_domain_pack(store, pack, reviewer=reviewer, notes=notes)
    return render_json(record)


def cmd_proof_policy_list(root: str | Path = ".", *, project_id: str = "") -> str:
    records = list_policy_records(get_store(root), project_id=project_id)
    if not records:
        profile = get_latest_policy_profile(get_store(root), project_id=project_id) or default_policy_profile()
        return render_json(profile)
    return "\n".join(summarize_policy_record(record) for record in records)


def cmd_proof_policy_set(
    profile_json: str,
    root: str | Path = ".",
    *,
    reviewer: str = "human",
    notes: str = "",
) -> str:
    store = get_store(root)
    profile = _load_model_json(profile_json, AutomationPolicyProfile)
    record = set_policy_profile(store, profile, reviewer=reviewer, notes=notes)  # type: ignore[arg-type]
    return render_json(record)


def cmd_proof_recommend(
    root: str | Path = ".",
    *,
    query: str = "",
    current_project_id: str = "",
    current_project_assets_json: list[str] | None = None,
    shared_assets_json: list[str] | None = None,
    prior_project_assets_json: list[str] | None = None,
    domain_packs_json: list[str] | None = None,
    prior_usefulness_json: str = "",
    limit: int = 10,
) -> str:
    store = get_store(root)
    state = load_state(store)
    current_assets = [_load_model_json(value, ReusableAsset) for value in current_project_assets_json or []]
    shared_assets = [_load_model_json(value, ReusableAsset) for value in shared_assets_json or []]
    prior_assets = [_load_model_json(value, ReusableAsset) for value in prior_project_assets_json or []]
    packs = [_load_model_json(value, DomainPack) for value in domain_packs_json or []]
    prior_usefulness = json.loads(prior_usefulness_json) if prior_usefulness_json else None
    report = recommend_cross_project_assets(
        current_project_id=current_project_id or state.project_id,
        query=query or None,
        current_project_assets=current_assets,
        shared_assets=shared_assets,
        prior_project_assets=prior_assets,
        domain_packs=packs,
        prior_usefulness=prior_usefulness,
        limit=limit,
    )
    record = record_cross_project_recommendation(store, report, notes=f"query={query}" if query else "")
    return render_json(record)


def cmd_proof_reuse_show(root: str | Path = ".", *, asset_id: str = "", project_id: str = "") -> str:
    store = get_store(root)
    assets = list_reusable_asset_records(store, project_id=project_id)
    reuse_records = list_reuse_records(store, project_id=project_id, asset_id=asset_id)
    payload = {
        "assets": [record.model_dump(mode="json") for record in assets if not asset_id or record.asset.id == asset_id],
        "reuse_records": [record.model_dump(mode="json") for record in reuse_records],
    }
    return json.dumps(payload, indent=2)


def cmd_proof_automate_plan(
    root: str | Path = ".",
    *,
    scope: str,
    task_type: str,
    action_json: list[str] | None = None,
    policy_json: str = "",
    execution_mode: str = "supervised",
    notes: str = "",
    dry_run: bool | None = None,
    approval_required: bool | None = None,
) -> str:
    store = get_store(root)
    state = load_state(store)
    policy_profile = None
    if policy_json:
        policy_profile = _load_model_json(policy_json, AutomationPolicyProfile)
    action_specs = [json.loads(value) for value in action_json or []]
    run = build_governance_automation_run(
        project_id=state.project_id,
        scope=scope,
        task_type=AutomationTaskType(task_type),
        action_specs=action_specs,
        policy_profile=policy_profile,
        execution_mode=AutomationExecutionMode(execution_mode),
        notes=notes,
        dry_run=dry_run,
        approval_required=approval_required,
    )
    record = record_automation_run(store, run, review_status="planned", notes=notes)
    return render_json(record)


def cmd_proof_automate_run(
    run_id: str,
    root: str | Path = ".",
    *,
    approvals_json: str = "",
    interrupt_after: int | None = None,
    notes: str = "",
) -> str:
    store = get_store(root)
    record = get_automation_record(store, run_id)
    if record is None:
        return f"automation:run:blocked:run {run_id} not found"
    approvals = json.loads(approvals_json) if approvals_json else {}
    run = record.run.execute(approvals=approvals, interrupt_after=interrupt_after)
    updated = record_automation_run(store, run, review_status="completed" if run.status.value == "completed" else run.status.value, notes=notes)
    return render_json(updated)


def cmd_proof_automate_trace(run_id: str, root: str | Path = ".") -> str:
    store = get_store(root)
    record = get_automation_record(store, run_id)
    if record is None:
        return f"automation:trace:blocked:run {run_id} not found"
    payload = {
        "run": record.run.model_dump(mode="json"),
        "trace": [entry.model_dump(mode="json") for entry in record.run.trace],
    }
    return json.dumps(payload, indent=2)


def cmd_proof_automate_review(
    run_id: str,
    action_id: str,
    root: str | Path = ".",
    *,
    decision: str = "approve",
    reviewer: str = "human",
    rationale: str = "",
) -> str:
    store = get_store(root)
    record = get_automation_record(store, run_id)
    if record is None:
        return f"automation:review:blocked:run {run_id} not found"
    action = next((item for item in record.run.planned_actions if item.id == action_id), None)
    if action is None:
        return f"automation:review:blocked:action {action_id} not found"
    normalized = decision.strip().lower()
    if normalized in {"approve", "approved"}:
        reviewed_run = record.run.approve_action(action_id, reviewer=reviewer, rationale=rationale)
        review_status = "accepted_after_review"
    else:
        updated_action = action.mark(
            status=AutomationActionStatus.rejected,
            policy_decision=AutomationPolicyDecision.deny,
            requires_review=True,
            reviewer=reviewer,
            review_notes=rationale,
            result_summary=rationale or "rejected by human reviewer",
        )
        reviewed_actions = [updated_action if item.id == action_id else item for item in record.run.planned_actions]
        reviewed_run = record.run.model_copy(
            update={
                "planned_actions": reviewed_actions,
                "status": AutomationRunStatus.rejected,
                "trace": [
                    *record.run.trace,
                    AutomationTraceEntry(
                        kind=AutomationTraceKind.action_rejected,
                        message=f"rejected {action_id} by {reviewer}",
                        action_id=action_id,
                        payload={"rationale": rationale},
                    ),
                ],
            }
        )
        review_status = "rejected_by_human"
    updated = record_automation_run(store, reviewed_run, review_status=review_status, notes=rationale)
    return render_json(updated)


def cmd_proof_benchmark_run(
    root: str | Path = ".",
    *,
    record_json: list[str] | None = None,
    benchmark_name: str = "",
    scenario_id: str = "",
    notes: str = "",
) -> str:
    store = get_store(root)
    records = [_load_model_json(value, AutomationEvaluationRecord) for value in record_json or []]
    replay = replay_automation_benchmark(
        records,
        benchmark_name=benchmark_name or None,
        scenario_id=scenario_id or None,
        notes=notes,
    )
    record = record_benchmark_replay(store, replay, notes=notes)
    return render_json(record)
