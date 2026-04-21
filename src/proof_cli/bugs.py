from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field, field_validator

from .blockers import list_blockers
from .checks import (
    export_strength_mismatch_warning,
    notation_drift_warning,
    simple_circular_dependency_detection,
    unresolved_omission_marker,
)
from .domain import ProofObligation, utc_now
from .obligations import list_obligations
from .proof_state import load_state
from .storage import ProjectStore, get_contract
from .theorems import theorem_callability


class ProofBugType(str, Enum):
    assumption_mismatch = "assumption_mismatch"
    export_overstretch = "export_overstretch"
    omitted_side_condition = "omitted_side_condition"
    circular_dependency = "circular_dependency"
    notation_drift = "notation_drift"


class ProofBugSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ProofBugStatus(str, Enum):
    suspected = "suspected"
    under_review = "under_review"
    confirmed = "confirmed"
    dismissed = "dismissed"
    repaired = "repaired"
    superseded = "superseded"


class ProofBugReviewState(str, Enum):
    unreviewed = "unreviewed"
    triaged = "triaged"
    reviewed = "reviewed"


class ProofBugReport(BaseModel):
    id: str = Field(default_factory=lambda: f"bug_{uuid.uuid4().hex[:12]}")
    bug_type: ProofBugType
    description: str
    severity: ProofBugSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    status: ProofBugStatus = ProofBugStatus.suspected
    review_state: ProofBugReviewState = ProofBugReviewState.unreviewed
    linked_contract_ids: list[str] = Field(default_factory=list)
    linked_obligation_ids: list[str] = Field(default_factory=list)
    linked_blocker_ids: list[str] = Field(default_factory=list)
    reasoning_path: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    detector: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class ProofBugScan(BaseModel):
    theorem_id: str | None = None
    reports: list[ProofBugReport] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def report_ids(self) -> list[str]:
        return [report.id for report in self.reports]

    def bug_types(self) -> list[str]:
        return [report.bug_type.value for report in self.reports]


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _contract(store: ProjectStore, theorem_id: str):
    return get_contract(store, theorem_id)


def _state_context(store: ProjectStore) -> list[str]:
    return list(load_state(store).current_context)


def _obligation_links(store: ProjectStore, theorem_id: str, needles: Iterable[str] = ()) -> list[str]:
    matched: list[str] = []
    lowered_needles = [needle.lower() for needle in needles if needle]
    for obligation in list_obligations(store):
        haystack = " ".join(
            part
            for part in (
                obligation.id,
                obligation.goal_statement,
                obligation.required_for or "",
                obligation.blocking_reason or "",
                " ".join(obligation.dependencies),
            )
            if part
        ).lower()
        if obligation.required_for == theorem_id or theorem_id in obligation.dependencies or any(needle in haystack for needle in lowered_needles):
            matched.append(obligation.id)
    return _unique(matched)


def _blocker_links(store: ProjectStore, theorem_id: str, needles: Iterable[str] = ()) -> list[str]:
    matched: list[str] = []
    lowered_needles = [needle.lower() for needle in needles if needle]
    for blocker in list_blockers(store):
        haystack = " ".join(
            part
            for part in (
                blocker.id,
                blocker.scope,
                blocker.description,
                blocker.failure_type,
                " ".join(blocker.related_contracts),
                " ".join(blocker.related_steps),
            )
            if part
        ).lower()
        if blocker.scope == theorem_id or theorem_id in blocker.related_contracts or any(needle in haystack for needle in lowered_needles):
            matched.append(blocker.id)
    return _unique(matched)


def _build_report(
    *,
    bug_type: ProofBugType,
    description: str,
    severity: ProofBugSeverity,
    confidence: float,
    detector: str,
    linked_contract_ids: list[str] | None = None,
    linked_obligation_ids: list[str] | None = None,
    linked_blocker_ids: list[str] | None = None,
    reasoning_path: list[str] | None = None,
    missing_conditions: list[str] | None = None,
    evidence: list[str] | None = None,
    status: ProofBugStatus = ProofBugStatus.suspected,
    review_state: ProofBugReviewState = ProofBugReviewState.unreviewed,
) -> ProofBugReport:
    return ProofBugReport(
        bug_type=bug_type,
        description=description,
        severity=severity,
        confidence=confidence,
        status=status,
        review_state=review_state,
        linked_contract_ids=_unique(linked_contract_ids or []),
        linked_obligation_ids=_unique(linked_obligation_ids or []),
        linked_blocker_ids=_unique(linked_blocker_ids or []),
        reasoning_path=list(reasoning_path or []),
        missing_conditions=list(missing_conditions or []),
        evidence=list(evidence or []),
        detector=detector,
    )


def detect_assumption_mismatch(store: ProjectStore, theorem_id: str) -> list[ProofBugReport]:
    contract = _contract(store, theorem_id)
    if contract is None:
        return []
    ok, reason = theorem_callability(store, theorem_id)
    if ok or not reason.startswith("missing assumptions:"):
        return []
    missing_assumptions = [item.strip() for item in reason.removeprefix("missing assumptions:").split(",") if item.strip()]
    context = _state_context(store)
    linked_obligations = _obligation_links(store, theorem_id, missing_assumptions)
    linked_blockers = _blocker_links(store, theorem_id, missing_assumptions)
    evidence = [
        f"callability check: {reason}",
        f"current context: {', '.join(context) if context else 'empty'}",
    ]
    return [
        _build_report(
            bug_type=ProofBugType.assumption_mismatch,
            description=f"theorem {theorem_id} is missing assumptions: {', '.join(missing_assumptions)}",
            severity=ProofBugSeverity.high,
            confidence=0.96,
            detector="detect_assumption_mismatch",
            linked_contract_ids=[theorem_id],
            linked_obligation_ids=linked_obligations,
            linked_blocker_ids=linked_blockers,
            reasoning_path=[theorem_id, "assumption_check"],
            missing_conditions=missing_assumptions,
            evidence=evidence,
        )
    ]


def detect_export_overstretch(store: ProjectStore, theorem_id: str) -> list[ProofBugReport]:
    contract = _contract(store, theorem_id)
    if contract is None:
        return []
    check = export_strength_mismatch_warning(store, theorem_id)
    if check.severity == "pass":
        return []
    if check.message == "imported theorem has no explicit exports":
        description = f"theorem {theorem_id} has no explicit exports recorded"
        severity = ProofBugSeverity.medium
        confidence = 0.72
    elif "without grounded support" in check.message or "weak references" in check.message:
        description = f"theorem {theorem_id} exports stronger than its grounding supports"
        severity = ProofBugSeverity.high
        confidence = 0.9
    else:
        description = f"theorem {theorem_id} has an export-strength mismatch"
        severity = ProofBugSeverity.medium
        confidence = 0.8
    grounded_obligations = _obligation_links(store, theorem_id, contract.exports)
    grounded_blockers = _blocker_links(store, theorem_id, contract.exports)
    evidence = [f"checker output: {check.message}"]
    if contract.exports:
        evidence.append(f"exports: {', '.join(contract.exports)}")
    return [
        _build_report(
            bug_type=ProofBugType.export_overstretch,
            description=description,
            severity=severity,
            confidence=confidence,
            detector="detect_export_overstretch",
            linked_contract_ids=[theorem_id],
            linked_obligation_ids=grounded_obligations,
            linked_blocker_ids=grounded_blockers,
            reasoning_path=[theorem_id, "export_strength_check"],
            missing_conditions=list(contract.exports),
            evidence=evidence,
        )
    ]


def detect_omitted_side_conditions(store: ProjectStore, theorem_id: str | None = None) -> list[ProofBugReport]:
    check = unresolved_omission_marker(store)
    if check.severity == "pass":
        return []
    obligations = list_obligations(store)
    flagged_obligations: list[ProofObligation] = []
    for obligation in obligations:
        searchable = " ".join(
            part
            for part in (
                obligation.goal_statement,
                obligation.blocking_reason or "",
                " ".join(obligation.dependencies),
            )
            if part
        ).lower()
        if any(keyword in searchable for keyword in ("compressed", "omission", "omitted", "implicit", "gap", "sketch", "elided")):
            flagged_obligations.append(obligation)
    linked_contract_ids = _unique(
        [
            *([theorem_id] if theorem_id else []),
            *[obligation.required_for for obligation in flagged_obligations if obligation.required_for],
        ]
    )
    linked_obligation_ids = [obligation.id for obligation in flagged_obligations]
    linked_blocker_ids = _blocker_links(
        store,
        theorem_id or "",
        [obligation.id for obligation in flagged_obligations] + [obligation.blocking_reason or "" for obligation in flagged_obligations],
    )
    evidence = [f"checker output: {check.message}"]
    evidence.extend(f"{obligation.id}: {obligation.blocking_reason or obligation.goal_statement}" for obligation in flagged_obligations)
    return [
        _build_report(
            bug_type=ProofBugType.omitted_side_condition,
            description="open obligations indicate omitted side conditions or compressed proof gaps",
            severity=ProofBugSeverity.high,
            confidence=0.88,
            detector="detect_omitted_side_conditions",
            linked_contract_ids=linked_contract_ids,
            linked_obligation_ids=linked_obligation_ids,
            linked_blocker_ids=linked_blocker_ids,
            reasoning_path=[theorem_id] if theorem_id else [],
            missing_conditions=[obligation.blocking_reason or obligation.goal_statement for obligation in flagged_obligations],
            evidence=evidence,
        )
    ]


def detect_circular_dependency(store: ProjectStore, theorem_id: str) -> list[ProofBugReport]:
    contract = _contract(store, theorem_id)
    if contract is None:
        return []
    check = simple_circular_dependency_detection(store, theorem_id)
    if check.severity == "pass":
        return []
    cycle_text = check.message.split(":", 1)[1].strip() if ":" in check.message else check.message
    cycle = [part.strip() for part in cycle_text.split("->") if part.strip()]
    linked_contract_ids = _unique([theorem_id, *cycle])
    linked_obligation_ids = _obligation_links(store, theorem_id, cycle)
    linked_blocker_ids = _blocker_links(store, theorem_id, cycle)
    return [
        _build_report(
            bug_type=ProofBugType.circular_dependency,
            description=f"dependency cycle detected for {theorem_id}",
            severity=ProofBugSeverity.critical,
            confidence=0.99,
            detector="detect_circular_dependency",
            linked_contract_ids=linked_contract_ids,
            linked_obligation_ids=linked_obligation_ids,
            linked_blocker_ids=linked_blocker_ids,
            reasoning_path=cycle or [theorem_id],
            missing_conditions=[check.message],
            evidence=[f"checker output: {check.message}"],
        )
    ]


def detect_notation_drift(store: ProjectStore, theorem_id: str) -> list[ProofBugReport]:
    contract = _contract(store, theorem_id)
    if contract is None:
        return []
    check = notation_drift_warning(store, theorem_id)
    if check.severity == "pass":
        return []
    drifted_symbols = [
        symbol.strip()
        for symbol in (check.message.split(":", 1)[1].split(",") if ":" in check.message else [])
        if symbol.strip()
    ]
    linked_obligations = _obligation_links(store, theorem_id, drifted_symbols)
    linked_blockers = _blocker_links(store, theorem_id, drifted_symbols)
    return [
        _build_report(
            bug_type=ProofBugType.notation_drift,
            description=f"notation drift detected in theorem {theorem_id}",
            severity=ProofBugSeverity.low,
            confidence=0.7,
            detector="detect_notation_drift",
            linked_contract_ids=[theorem_id],
            linked_obligation_ids=linked_obligations,
            linked_blocker_ids=linked_blockers,
            reasoning_path=[theorem_id, "notation_drift_check"],
            missing_conditions=drifted_symbols,
            evidence=[f"checker output: {check.message}"],
        )
    ]


def scan_proof_bugs(store: ProjectStore, theorem_id: str) -> ProofBugScan:
    reports = [
        *detect_assumption_mismatch(store, theorem_id),
        *detect_export_overstretch(store, theorem_id),
        *detect_omitted_side_conditions(store, theorem_id),
        *detect_circular_dependency(store, theorem_id),
        *detect_notation_drift(store, theorem_id),
    ]
    return ProofBugScan(theorem_id=theorem_id, reports=reports)


def bug_reports_to_json(reports: list[ProofBugReport]) -> str:
    return ProofBugScan(reports=reports).model_dump_json(indent=2)


__all__ = [
    "ProofBugReport",
    "ProofBugReviewState",
    "ProofBugScan",
    "ProofBugSeverity",
    "ProofBugStatus",
    "ProofBugType",
    "bug_reports_to_json",
    "detect_assumption_mismatch",
    "detect_circular_dependency",
    "detect_export_overstretch",
    "detect_notation_drift",
    "detect_omitted_side_conditions",
    "scan_proof_bugs",
]
