from __future__ import annotations

import json
from pathlib import Path

from .bugs import ProofBugReport, ProofBugScan, ProofBugSeverity, ProofBugStatus
from .bugs import ProofBugReviewState
from .debug_tasks import ProofDebugTaskBatch
from .formalization_recommendations import rank_formalization_candidates
from .memory import accepted_verification_results, load_memory, stale_verification_fragments, verification_records
from .proof_state import load_state, summarize_state
from .storage import ProjectStore, list_references
from .review import describe_verification_fragment, describe_verification_result_record
from .verification_broker import build_default_verification_broker
from .verification_ir import VerificationFragmentStatus, VerificationReviewStatus
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


def _latest_payload(state, prefix: str) -> dict[str, object] | None:
    payload: dict[str, object] | None = None
    for entry in state.session_history:
        if entry.startswith(prefix):
            payload = json.loads(entry.removeprefix(prefix))
    return payload


def _bug_overrides(state) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    reviews: dict[str, dict[str, object]] = {}
    repairs: dict[str, dict[str, object]] = {}
    for entry in state.session_history:
        if entry.startswith("proof_bug_review:"):
            payload = json.loads(entry.removeprefix("proof_bug_review:"))
            reviews[str(payload["bug_id"])] = payload
        elif entry.startswith("proof_bug_repair:"):
            payload = json.loads(entry.removeprefix("proof_bug_repair:"))
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


def _evidence_recommendation(report: ProofBugReport) -> str:
    if report.status in {ProofBugStatus.dismissed, ProofBugStatus.superseded, ProofBugStatus.repaired}:
        return "accept"
    if report.status == ProofBugStatus.confirmed:
        return "block"
    if report.severity in {ProofBugSeverity.high, ProofBugSeverity.critical}:
        return "block"
    return "revise"


def _format_bug_summary(report: ProofBugReport) -> str:
    path = " -> ".join(report.reasoning_path or [report.id])
    missing = _join(report.missing_conditions)
    return (
        f"{report.id}: {report.bug_type.value} [{report.status.value}/{report.review_state.value}/{report.severity.value}] "
        f"confidence={report.confidence:g} path={path} missing={missing}"
    )


def _format_evidence_summary(report: ProofBugReport) -> str:
    evidence = _join(report.evidence)
    path = " -> ".join(report.reasoning_path or [report.id])
    return f"{report.id}: recommendation={_evidence_recommendation(report)} path={path} evidence={evidence}"


def _format_debug_task_summary(task) -> str:
    return (
        f"{task.id}: {task.task_type.value} [{task.priority.value}/{task.status.value}] "
        f"bug={task.bug_report_id} {task.title}"
    )


def _format_repair_state_line(bug_id: str, payload: dict[str, object]) -> str:
    bug_status = payload.get("bug_status", "unknown")
    review_state = payload.get("review_state", "unknown")
    note = payload.get("note") or payload.get("rationale") or ""
    note_text = f" note={note}" if note else ""
    return f"{bug_id}: status={bug_status} review_state={review_state}{note_text}"


def _format_verification_recommendation_line(recommendation) -> str:
    backend_text = recommendation.suggested_backend or "auto"
    return (
        f"{recommendation.fragment_id}: rank={recommendation.rank} score={recommendation.total_score:.2f} "
        f"backend={backend_text} [{recommendation.review_status}]"
    )


def _format_verification_result_line(record) -> str:
    return describe_verification_result_record(record)


def build_export(store: ProjectStore) -> str:
    state = summarize_state(store)
    live_state = load_state(store)
    memory = load_memory(store)
    references = sorted(list_references(store), key=lambda reference: (reference.id, reference.title))
    theorems = sorted(list_theorems(store), key=lambda theorem: (theorem.id, theorem.name))
    latest_reasoning = _latest_payload(live_state, "proof_reasoning:")
    latest_bug_scan_payload = _latest_payload(live_state, "proof_bug_scan:")
    latest_debug_batch_payload = _latest_payload(live_state, "proof_debug_batch:")
    reviews, repairs = _bug_overrides(live_state)

    grounded_theorems = [theorem for theorem in theorems if theorem.grounded_reference_ids]

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
        "Reasoning:",
    ]

    if latest_reasoning is not None:
        lines.append(json.dumps(latest_reasoning, indent=2))
    else:
        lines.append("- none")

    lines.append("Imported references:")
    if references:
        lines.extend(f"- {_format_reference_line(reference)}" for reference in references)
    else:
        lines.append("- none")

    lines.append("Grounded theorems:")
    if grounded_theorems:
        lines.extend(f"- {_format_theorem_grounding_line(theorem)}" for theorem in grounded_theorems)
    else:
        lines.append("- none")

    verification_lifecycle_records = verification_records(store)
    verification_fragments = [record.fragment for record in verification_lifecycle_records]
    verification_recommendations = (
        rank_formalization_candidates(verification_fragments, broker=build_default_verification_broker())
        if verification_fragments
        else []
    )
    accepted_results = accepted_verification_results(store)
    stale_fragments = stale_verification_fragments(store)
    machine_checked_results = [
        record.result_record
        for record in verification_lifecycle_records
        if record.result_record is not None and record.result_record.result_status == VerificationFragmentStatus.machine_checked
    ]
    rejected_results = [
        record.result_record
        for record in verification_lifecycle_records
        if record.result_record is not None and record.result_record.review_status == VerificationReviewStatus.rejected_by_human
    ]
    failed_fragments = [
        record.fragment
        for record in verification_lifecycle_records
        if record.fragment.status
        in {
            VerificationFragmentStatus.backend_failed,
            VerificationFragmentStatus.translation_failed,
            VerificationFragmentStatus.rejected_by_human,
        }
    ]

    lines.append("Verification support:")
    if verification_recommendations:
        lines.append("Heuristic recommendations:")
        lines.extend(f"- {_format_verification_recommendation_line(recommendation)}" for recommendation in verification_recommendations[:5])
    else:
        lines.append("- none")

    lines.append("Machine-checked results:")
    if machine_checked_results:
        lines.extend(f"- {_format_verification_result_line(record)}" for record in machine_checked_results if record is not None)
    else:
        lines.append("- none")

    lines.append("Accepted verification results:")
    if accepted_results:
        lines.extend(f"- {_format_verification_result_line(record)}" for record in accepted_results)
    else:
        lines.append("- none")

    lines.append("Rejected verification results:")
    if rejected_results:
        lines.extend(f"- {_format_verification_result_line(record)}" for record in rejected_results)
    else:
        lines.append("- none")

    lines.append("Stale verification fragments:")
    if stale_fragments:
        lines.extend(f"- {describe_verification_fragment(fragment)}" for fragment in stale_fragments)
    else:
        lines.append("- none")

    lines.append("Failed verification fragments:")
    if failed_fragments:
        lines.extend(f"- {describe_verification_fragment(fragment)}" for fragment in failed_fragments)
    else:
        lines.append("- none")

    lines.append("Verification detail:")
    lines.append(
        json.dumps(
            {
                "recommendations": [recommendation.model_dump(mode="json") for recommendation in verification_recommendations],
                "machine_checked_results": [record.model_dump(mode="json") for record in machine_checked_results if record is not None],
                "accepted_verification_results": [record.model_dump(mode="json") for record in accepted_results],
                "rejected_verification_results": [record.model_dump(mode="json") for record in rejected_results],
                "stale_verification_fragments": [fragment.model_dump(mode="json") for fragment in stale_fragments],
                "failed_verification_fragments": [fragment.model_dump(mode="json") for fragment in failed_fragments],
            },
            indent=2,
            sort_keys=True,
        )
    )

    lines.append("Bug reports:")
    if latest_bug_scan_payload is not None:
        latest_bug_scan = ProofBugScan.model_validate(latest_bug_scan_payload)
        bug_reports = [_apply_bug_overrides(report, reviews, repairs) for report in latest_bug_scan.reports]
        if bug_reports:
            lines.extend(f"- {_format_bug_summary(report)}" for report in bug_reports)
        else:
            lines.append("- none")
        lines.append("Bug scan detail:")
        adjusted_scan = latest_bug_scan.model_copy(update={"reports": bug_reports})
        lines.append(adjusted_scan.model_dump_json(indent=2))
    else:
        lines.append("- none")

    lines.append("Evidence chains:")
    if latest_bug_scan_payload is not None:
        latest_bug_scan = ProofBugScan.model_validate(latest_bug_scan_payload)
        evidence_reports = [_apply_bug_overrides(report, reviews, repairs) for report in latest_bug_scan.reports]
        if evidence_reports:
            lines.extend(f"- {_format_evidence_summary(report)}" for report in evidence_reports)
        else:
            lines.append("- none")
    else:
        lines.append("- none")

    lines.append("Debug tasks:")
    if latest_debug_batch_payload is not None:
        latest_debug_batch = ProofDebugTaskBatch.model_validate(latest_debug_batch_payload)
        if latest_debug_batch.tasks:
            lines.extend(f"- {_format_debug_task_summary(task)}" for task in latest_debug_batch.tasks)
        else:
            lines.append("- none")
        lines.append("Debug batch detail:")
        lines.append(latest_debug_batch.model_dump_json(indent=2))
    else:
        lines.append("- none")

    repair_lines = [
        _format_repair_state_line(bug_id, {**reviews.get(bug_id, {}), **repairs.get(bug_id, {})})
        for bug_id in sorted({*reviews.keys(), *repairs.keys()})
    ]
    lines.append("Repair state:")
    if repair_lines:
        lines.extend(f"- {line}" for line in repair_lines)
    else:
        lines.append("- none")

    memory_counts = {
        "working": len(memory.working),
        "semantic": len(memory.semantic),
        "episodic": len(memory.episodic),
        "procedural": len(memory.procedural),
        "handoffs": len(memory.handoff_snapshots),
    }
    lines.append("Memory layers: " + ", ".join(f"{name}={count}" for name, count in memory_counts.items()))

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
