from __future__ import annotations

from dataclasses import dataclass

from .checks import run_standard_checks
from .blockers import resolve_blocker
from .domain import BlockerRecord, ProofObligation, TheoremContract, TheoremStatus, TrustLevel
from .obligations import close_obligation
from .storage import ProjectStore, append_event
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
