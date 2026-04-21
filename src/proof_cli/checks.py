from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .memory import recent_symbols
from .obligations import list_obligations
from .storage import ProjectStore, list_contracts
from .theorems import get_contract, theorem_callability


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
    return CheckResult("dependency_existence", "pass", "all dependencies exist")


def simple_circular_dependency_detection(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("circular_dependency", "fail", f"theorem {theorem_id} not found")
    if theorem_id in contract.dependencies:
        return CheckResult("circular_dependency", "fail", "direct self-dependency detected")
    return CheckResult("circular_dependency", "pass", "no direct cycle detected")


def export_strength_mismatch_warning(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("export_strength", "fail", f"theorem {theorem_id} not found")
    if contract.status.value == "imported" and not contract.exports:
        return CheckResult("export_strength", "warn", "imported theorem has no explicit exports")
    if contract.status.value == "verified" and not contract.exports:
        return CheckResult("export_strength", "warn", "verified theorem has no exports recorded")
    return CheckResult("export_strength", "pass", "exports align with current record")


def unresolved_omission_marker(store: ProjectStore) -> CheckResult:
    open_obligations = list_obligations(store)
    flagged = [obl.id for obl in open_obligations if obl.blocking_reason and "compressed" in obl.blocking_reason.lower()]
    if flagged:
        return CheckResult("omission_marker", "warn", f"unresolved omission markers: {', '.join(flagged)}")
    return CheckResult("omission_marker", "pass", "no omission markers found")


def notation_drift_warning(store: ProjectStore, theorem_id: str) -> CheckResult:
    contract = get_contract(store, theorem_id)
    if contract is None:
        return CheckResult("notation_drift", "fail", f"theorem {theorem_id} not found")
    tracked = set(recent_symbols(store))
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

