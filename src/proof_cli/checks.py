from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .memory import recent_symbols
from .obligations import list_obligations
from .references import ReferenceReviewStatus
from .storage import ProjectStore, get_reference
from .theorems import get_contract, theorem_callability
from .proof_state import load_state


Severity = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: Severity
    message: str


def assumption_presence_check(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("assumption_presence", "fail", f"theorem {theorem_id} not found")
    ok, reason = theorem_callability(store, theorem_id)
    if ok:
        if contract.provenance_kind.value == "imported":
            grounded_reference_ids = list(contract.grounded_reference_ids)
            grounded_theorem_ids = list(contract.grounded_theorem_ids)
            if not grounded_reference_ids and not grounded_theorem_ids:
                return CheckResult(
                    "assumption_presence",
                    "warn",
                    f"imported theorem {theorem_id} has weak grounding: no grounded references or grounded theorems",
                )
            weak_grounding: list[str] = []
            for reference_id in grounded_reference_ids:
                reference = get_reference(store, reference_id)
                if reference is None:
                    weak_grounding.append(f"missing reference {reference_id}")
                    continue
                if reference.review_status != ReferenceReviewStatus.approved or not reference.is_callable:
                    weak_grounding.append(
                        f"reference {reference_id} is {reference.review_status.value}"
                    )
            for grounded_theorem_id in grounded_theorem_ids:
                grounded_contract = get_contract(store, grounded_theorem_id)
                if grounded_contract is None:
                    weak_grounding.append(f"missing grounded theorem {grounded_theorem_id}")
                    continue
                grounded_ok, grounded_reason = theorem_callability(store, grounded_theorem_id)
                if not grounded_ok:
                    weak_grounding.append(f"{grounded_theorem_id}: {grounded_reason}")
            if weak_grounding:
                return CheckResult(
                    "assumption_presence",
                    "warn",
                    f"imported theorem {theorem_id} has weak grounding: {', '.join(weak_grounding)}",
                )
        return CheckResult("assumption_presence", "pass", f"assumptions satisfied for {theorem_id}")
    if reason.startswith("missing assumptions"):
        return CheckResult("assumption_presence", "fail", reason)
    return CheckResult("assumption_presence", "warn", reason)


def theorem_call_legality_check(store: ProjectStore, theorem_id: str) -> CheckResult:
    ok, reason = theorem_callability(store, theorem_id)
    return CheckResult("theorem_call_legality", "pass" if ok else "fail", reason)


def dependency_existence_check(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("dependency_existence", "fail", f"theorem {theorem_id} not found")
    missing = [dep for dep in contract.dependencies if get_contract(store, dep) is None]
    if missing:
        return CheckResult("dependency_existence", "fail", f"missing dependencies: {', '.join(missing)}")
    unsafe = []
    for dependency_id in contract.dependencies:
        dependency_ok, dependency_reason = theorem_callability(store, dependency_id)
        if not dependency_ok:
            unsafe.append(f"{dependency_id}: {dependency_reason}")
    if unsafe:
        return CheckResult("dependency_existence", "warn", f"dependencies need review: {', '.join(unsafe)}")
    return CheckResult("dependency_existence", "pass", "all dependencies exist")


def simple_circular_dependency_detection(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("circular_dependency", "fail", f"theorem {theorem_id} not found")
    visited: set[str] = set()
    stack: list[str] = []

    def visit(current_id: str) -> list[str] | None:
        if current_id in stack:
            cycle_start = stack.index(current_id)
            return stack[cycle_start:] + [current_id]
        if current_id in visited:
            return None
        visited.add(current_id)
        stack.append(current_id)
        current_contract = get_contract(store, current_id)
        if current_contract is not None:
            for dependency_id in current_contract.dependencies:
                cycle = visit(dependency_id)
                if cycle is not None:
                    return cycle
        stack.pop()
        return None

    cycle = visit(theorem_id)
    if cycle is not None:
        return CheckResult("circular_dependency", "fail", f"dependency cycle detected: {' -> '.join(cycle)}")
    return CheckResult("circular_dependency", "pass", "no direct cycle detected")


def export_strength_mismatch_warning(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("export_strength", "fail", f"theorem {theorem_id} not found")
    grounded_reference_ids = list(contract.grounded_reference_ids)
    grounded_theorem_ids = list(contract.grounded_theorem_ids)
    if contract.status.value == "imported" and not contract.exports:
        return CheckResult("export_strength", "warn", "imported theorem has no explicit exports")
    if contract.status.value == "verified" and not contract.exports:
        return CheckResult("export_strength", "warn", "verified theorem has no exports recorded")
    if contract.provenance_kind.value == "imported" and contract.exports and not grounded_reference_ids and not grounded_theorem_ids:
        return CheckResult(
            "export_strength",
            "warn",
            f"imported theorem {theorem_id} exports {', '.join(contract.exports)} without grounded support",
        )
    unsupported_exports = []
    for reference_id in grounded_reference_ids:
        reference = get_reference(store, reference_id)
        if reference is None:
            unsupported_exports.append(f"missing reference {reference_id}")
            continue
        if reference.review_status != ReferenceReviewStatus.approved:
            unsupported_exports.append(f"reference {reference_id} is {reference.review_status.value}")
    if unsupported_exports and contract.exports:
        return CheckResult(
            "export_strength",
            "warn",
            f"exports are grounded by weak references: {', '.join(unsupported_exports)}",
        )
    return CheckResult("export_strength", "pass", "exports align with current record")


def unresolved_omission_marker(store: ProjectStore) -> CheckResult:
    open_obligations = list_obligations(store)
    keywords = ("compressed", "omission", "omitted", "implicit", "gap", "sketch", "elided")
    flagged = []
    for obligation in open_obligations:
        if obligation.status.value != "open" and not obligation.blocking_reason:
            continue
        searchable = " ".join(
            part
            for part in (
                obligation.goal_statement,
                obligation.blocking_reason or "",
                " ".join(obligation.dependencies),
            )
            if part
        ).lower()
        if any(keyword in searchable for keyword in keywords):
            detail = obligation.blocking_reason or obligation.goal_statement
            flagged.append(f"{obligation.id} ({detail})")
    if flagged:
        return CheckResult("omission_marker", "warn", f"unresolved omission gaps: {', '.join(flagged)}")
    return CheckResult("omission_marker", "pass", "no omission markers found")


def notation_drift_warning(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("notation_drift", "fail", f"theorem {theorem_id} not found")
    tracked = set(recent_symbols(store))
    state = load_state(store)
    tracked.update(state.current_context)
    tracked.update(contract.assumptions)
    tracked.update(contract.exports)
    tracked.update(contract.grounded_theorem_ids)
    tokens = set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", contract.statement))
    drift = sorted(token for token in tokens if token not in tracked and token[:1].isupper())
    if drift:
        return CheckResult("notation_drift", "warn", f"untracked symbols: {', '.join(drift)}")
    return CheckResult("notation_drift", "pass", "notation aligns with tracked symbols")


def run_standard_checks(store: ProjectStore, theorem_id: str) -> list[CheckResult]:
    return [
        assumption_presence_check(store, theorem_id),
        theorem_call_legality_check(store, theorem_id),
        dependency_existence_check(store, theorem_id),
        simple_circular_dependency_detection(store, theorem_id),
        export_strength_mismatch_warning(store, theorem_id),
        unresolved_omission_marker(store),
        notation_drift_warning(store, theorem_id),
    ]
