from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .collaboration import list_review_records, summarize_review_record
from .formalization_recommendations import FormalizationRecommendation
from .storage import ProjectStore
from .verification_ir import VerificationFragment, VerificationFragmentStatus, VerificationResult
from .verification_results import VerificationResultRecord, list_verification_results


def publication_review_summary(store: ProjectStore, *, object_type: str = "", object_id: str = "") -> list[str]:
    records = list_review_records(store, object_type=object_type, object_id=object_id)
    return [summarize_review_record(record) for record in records]


def publication_verification_summary(store: ProjectStore, *, theorem_id: str = "") -> list[str]:
    records = list_verification_results(store)
    if theorem_id:
        records = [record for record in records if record.theorem_id == theorem_id]
    return [describe_verification_result_record(record) for record in records]


def describe_verification_fragment(fragment: VerificationFragment) -> str:
    scope_parts: list[str] = []
    if fragment.scope.theorem_id:
        scope_parts.append(f"theorem={fragment.scope.theorem_id}")
    if fragment.scope.obligation_id:
        scope_parts.append(f"obligation={fragment.scope.obligation_id}")
    if fragment.scope.proof_step_id:
        scope_parts.append(f"proof_step={fragment.scope.proof_step_id}")
    if fragment.scope.goal_id:
        scope_parts.append(f"goal={fragment.scope.goal_id}")
    if fragment.scope.blocker_id:
        scope_parts.append(f"blocker={fragment.scope.blocker_id}")
    if fragment.scope.route_id:
        scope_parts.append(f"route={fragment.scope.route_id}")
    scope_text = ", ".join(scope_parts) if scope_parts else "unscoped"
    backend_text = fragment.backend_target or "auto"
    return (
        f"{fragment.id}: {fragment.source_type.value}/{fragment.source_id} "
        f"[{fragment.status.value}, translation={fragment.translation_status.value}, backend={backend_text}] "
        f"({scope_text})"
    )


def describe_verification_result_record(record: VerificationResultRecord) -> str:
    target_parts: list[str] = []
    if record.theorem_id:
        target_parts.append(f"theorem={record.theorem_id}")
    if record.obligation_id:
        target_parts.append(f"obligation={record.obligation_id}")
    if record.blocker_id:
        target_parts.append(f"blocker={record.blocker_id}")
    if record.proof_step_id:
        target_parts.append(f"proof_step={record.proof_step_id}")
    if record.route_id:
        target_parts.append(f"route={record.route_id}")
    target_text = ", ".join(target_parts) if target_parts else "unlinked"
    note_text = f" - {record.notes}" if record.notes else ""
    return (
        f"{record.result.id}: {record.source_kind.value}/{record.source_id} "
        f"[{record.result_status.value}/{record.review_status.value}] backend={record.result.backend} "
        f"effect={record.effect} summary={record.result.summary} ({target_text}){note_text}"
    )


def describe_verification_result(result: VerificationResult) -> str:
    return f"{result.id}: backend={result.backend} [{result.review_status.value}] {result.summary}"


def _verification_payload_lines(payload: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []

    if "result" not in payload and "fragment_id" in payload and "backend" in payload and "summary" in payload:
        result = VerificationResult.model_validate(payload)
        lines.append(f"Result: {describe_verification_result(result)}")

    if "result" in payload and "result_status" in payload and "review_status" in payload:
        record = VerificationResultRecord.model_validate(payload)
        lines.append(f"Verification record: {describe_verification_result_record(record)}")

    fragment_payload = payload.get("fragment")
    if isinstance(fragment_payload, dict):
        fragment = VerificationFragment.model_validate(fragment_payload)
        fragment_label = "Stale fragment" if payload.get("machine_check_status") == VerificationFragmentStatus.stale_after_change.value else "Fragment"
        lines.append(f"{fragment_label}: {describe_verification_fragment(fragment)}")

    stale_fragment_payload = payload.get("stale_fragment")
    if isinstance(stale_fragment_payload, dict):
        stale_fragment = VerificationFragment.model_validate(stale_fragment_payload)
        lines.append(f"Stale fragment: {describe_verification_fragment(stale_fragment)}")

    revalidated_fragment_payload = payload.get("revalidated_fragment")
    if isinstance(revalidated_fragment_payload, dict):
        revalidated_fragment = VerificationFragment.model_validate(revalidated_fragment_payload)
        lines.append(f"Revalidated fragment: {describe_verification_fragment(revalidated_fragment)}")

    recommendation_payload = payload.get("recommendation")
    if isinstance(recommendation_payload, dict):
        recommendation = FormalizationRecommendation.model_validate(recommendation_payload)
        backend_text = recommendation.suggested_backend or "auto"
        lines.append(
            f"Recommendation: rank={recommendation.rank} score={recommendation.total_score:.2f} "
            f"backend={backend_text} review={recommendation.review_status}"
        )

    result_payload = payload.get("result")
    if isinstance(result_payload, dict):
        if "result_status" in result_payload and "review_status" in result_payload:
            record = VerificationResultRecord.model_validate(result_payload)
            lines.append(f"Verification record: {describe_verification_result_record(record)}")
        else:
            result = VerificationResult.model_validate(result_payload)
            lines.append(f"Result: {describe_verification_result(result)}")

    verification_record_payload = payload.get("verification_record")
    if isinstance(verification_record_payload, dict):
        record = VerificationResultRecord.model_validate(verification_record_payload)
        lines.append(f"Verification record: {describe_verification_result_record(record)}")

    results_payload = payload.get("results")
    if isinstance(results_payload, list):
        lines.append(f"Additional results: {len(results_payload)}")

    trace_payload = payload.get("trace")
    if isinstance(trace_payload, dict):
        trace_kind = trace_payload.get("kind", "trace")
        trace_uri = trace_payload.get("uri", "")
        lines.append(f"Trace: {trace_kind} -> {trace_uri}")

    provenance_payload = payload.get("provenance")
    if isinstance(provenance_payload, dict):
        source_kind = provenance_payload.get("source_kind", "unknown")
        source_id = provenance_payload.get("source_id", "unknown")
        lines.append(f"Provenance: {source_kind}/{source_id}")

    return lines


def render_verification_payload(title: str, payload: Mapping[str, Any]) -> str:
    lines = [title]
    lines.extend(_verification_payload_lines(payload))
    lines.append("Details:")
    lines.append(json.dumps(payload, indent=2, sort_keys=True))
    return "\n".join(lines)


def render_verification_output(title: str, output: str) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return output
    if not isinstance(payload, dict):
        return output
    return render_verification_payload(title, payload)
