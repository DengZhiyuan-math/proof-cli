from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .checks import run_standard_checks
from .blockers import resolve_blocker
from .domain import BlockerRecord, ProofObligation, TheoremContract, TheoremStatus, TrustLevel
from .formalization_recommendations import FormalizationRecommendation
from .obligations import close_obligation
from .storage import ProjectStore, append_event
from .verification_ir import VerificationFragment, VerificationFragmentStatus, VerificationResult
from .verification_results import VerificationResultRecord
from .theorems import get_contract, update_theorem


@dataclass(frozen=True)
class ReviewResult:
    allowed: bool
    message: str


def _checker_context(store: ProjectStore, theorem_id: str) -> list[dict[str, str]]:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return []
    return [
        {"name": check.name, "severity": check.severity, "message": check.message}
        for check in run_standard_checks(store, theorem_id)
    ]


def _blocked(
    store: ProjectStore,
    action: str,
    target: str,
    reason: str,
    *,
    checker_context: list[dict[str, str]] | None = None,
) -> ReviewResult:
    payload = {"action": action, "reason": reason}
    if checker_context is not None:
        payload["checker_context"] = checker_context
    append_event(store, "review_blocked", f"{action} blocked for {target}: {reason}", entity_id=target, payload=payload)
    return ReviewResult(False, reason)


def change_trust_level(
    store: ProjectStore,
    theorem_id: str,
    trust_level: TrustLevel,
    *,
    confirmed: bool = False,
    rationale: str = "",
) -> ReviewResult:
    if not confirmed:
        return _blocked(store, "trust_change", theorem_id, "confirmation required", checker_context=_checker_context(store, theorem_id))
    contract = get_contract(store, theorem_id)
    if contract is None:
        return ReviewResult(False, "theorem not found")
    checker_context = _checker_context(store, theorem_id)
    updated = update_theorem(store, theorem_id, trust_level=trust_level)
    append_event(
        store,
        "review_approved",
        f"trust level changed for {theorem_id}",
        entity_id=theorem_id,
        payload={"trust_level": trust_level.value, "rationale": rationale, "checker_context": checker_context},
    )
    return ReviewResult(True, updated.trust_level.value)


def mark_verified(
    store: ProjectStore,
    theorem_id: str,
    *,
    confirmed: bool = False,
    rationale: str = "",
) -> ReviewResult:
    if not confirmed:
        return _blocked(store, "mark_verified", theorem_id, "confirmation required", checker_context=_checker_context(store, theorem_id))
    contract = get_contract(store, theorem_id)
    if contract is None:
        return ReviewResult(False, "theorem not found")
    checker_context = _checker_context(store, theorem_id)
    update_theorem(store, theorem_id, status=TheoremStatus.verified, trust_level=TrustLevel.project_verified)
    append_event(
        store,
        "review_approved",
        f"marked verified {theorem_id}",
        entity_id=theorem_id,
        payload={"rationale": rationale, "checker_context": checker_context},
    )
    return ReviewResult(True, "verified")


def supersede_theorem_contract(
    store: ProjectStore,
    theorem_id: str,
    *,
    replacement_statement: str,
    confirmed: bool = False,
    rationale: str = "",
) -> ReviewResult:
    if not confirmed:
        return _blocked(store, "supersede_theorem", theorem_id, "confirmation required", checker_context=_checker_context(store, theorem_id))
    contract = get_contract(store, theorem_id)
    if contract is None:
        return ReviewResult(False, "theorem not found")
    checker_context = _checker_context(store, theorem_id)
    update_theorem(store, theorem_id, statement=replacement_statement, notes=(contract.notes + "\n" + rationale).strip())
    append_event(
        store,
        "review_approved",
        f"superseded theorem {theorem_id}",
        entity_id=theorem_id,
        payload={"replacement_statement": replacement_statement, "rationale": rationale, "checker_context": checker_context},
    )
    return ReviewResult(True, "superseded")


def approve_imported_result(
    store: ProjectStore,
    theorem_id: str,
    *,
    confirmed: bool = False,
    rationale: str = "",
) -> ReviewResult:
    if not confirmed:
        return _blocked(store, "approve_import", theorem_id, "confirmation required", checker_context=_checker_context(store, theorem_id))
    contract = get_contract(store, theorem_id)
    if contract is None:
        return ReviewResult(False, "theorem not found")
    checker_context = _checker_context(store, theorem_id)
    update_theorem(store, theorem_id, status=TheoremStatus.imported, trust_level=TrustLevel.external_reference)
    append_event(
        store,
        "review_approved",
        f"approved imported result {theorem_id}",
        entity_id=theorem_id,
        payload={"rationale": rationale, "checker_context": checker_context},
    )
    return ReviewResult(True, "import approved")


def resolve_blocker_review(
    store: ProjectStore,
    blocker_id: str,
    *,
    confirmed: bool = False,
    rationale: str = "",
) -> ReviewResult:
    if not confirmed:
        return _blocked(store, "resolve_blocker", blocker_id, "confirmation required")
    blocker = resolve_blocker(store, blocker_id, rationale=rationale)
    append_event(store, "review_approved", f"resolved blocker {blocker_id}", entity_id=blocker_id, payload={"rationale": rationale})
    return ReviewResult(True, blocker.status.value)


def close_obligation_review(
    store: ProjectStore,
    obligation_id: str,
    *,
    confirmed: bool = False,
    proof_text: str = "",
    rationale: str = "",
) -> ReviewResult:
    if not confirmed:
        return _blocked(store, "close_obligation", obligation_id, "confirmation required")
    if not proof_text and not rationale:
        return _blocked(store, "close_obligation", obligation_id, "proof text or rationale required")
    obligation = close_obligation(store, obligation_id, rationale=rationale or proof_text)
    append_event(
        store,
        "review_approved",
        f"closed obligation {obligation_id}",
        entity_id=obligation_id,
        payload={"proof_text": proof_text, "rationale": rationale},
    )
    return ReviewResult(True, obligation.status.value)


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
        f"effect={record.effect} ({target_text}){note_text}"
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
