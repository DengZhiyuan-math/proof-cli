from __future__ import annotations

from .domain import ProofObligation, ProofObligationStatus
from .proof_state import (
    add_obligation as _add_obligation,
    record_candidate_reference as _record_candidate_reference,
    record_failed_route as _record_failed_route,
    record_supporting_reference as _record_supporting_reference,
)
from .reasoning import LocalObligation, TheoremReasoningGoal
from .storage import ProjectStore, append_event, list_obligations as _list_obligations


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _to_proof_obligation(
    local_obligation: LocalObligation,
    *,
    note: str = "",
) -> ProofObligation:
    dependencies = list(local_obligation.dependencies)
    if local_obligation.source_unit_id:
        _extend_unique(dependencies, [f"source_unit:{local_obligation.source_unit_id}"])
    if local_obligation.required_for:
        _extend_unique(dependencies, [f"required_for:{local_obligation.required_for}"])
    if note:
        _extend_unique(dependencies, [f"synthesis_note:{note}"])
    return ProofObligation(
        id=local_obligation.id,
        goal_statement=local_obligation.statement,
        source_step_id=local_obligation.source_unit_id,
        required_for=local_obligation.required_for,
        status=ProofObligationStatus(local_obligation.status),
        blocking_reason=f"derived from {local_obligation.required_for or local_obligation.source_unit_id}",
        dependencies=dependencies,
        created_at=local_obligation.created_at,
        updated_at=local_obligation.created_at,
    )


def add_obligation(
    store: ProjectStore,
    obligation: ProofObligation,
    *,
    candidate_reference_ids: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    failed_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> ProofObligation:
    obligation = _add_obligation(
        store,
        obligation,
        candidate_reference_ids=candidate_reference_ids,
        supporting_reference_ids=supporting_reference_ids,
        failed_reference_ids=failed_reference_ids,
        route_notes=route_notes,
    )
    for reference_id in candidate_reference_ids or []:
        _record_candidate_reference(
            store,
            target_kind="obligation",
            target_id=obligation.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    for reference_id in supporting_reference_ids or []:
        _record_supporting_reference(
            store,
            target_kind="obligation",
            target_id=obligation.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    for reference_id in failed_reference_ids or []:
        _record_failed_route(
            store,
            f"obligation:{obligation.id}:{reference_id}",
            target_kind="obligation",
            target_id=obligation.id,
            reference_id=reference_id,
            notes=route_notes,
        )
    return obligation


def list_obligations(store: ProjectStore) -> list[ProofObligation]:
    return _list_obligations(store)


def synthesize_obligations(
    theorem_goal: TheoremReasoningGoal,
    *,
    contract_assumptions: list[str] | None = None,
    contract_exports: list[str] | None = None,
) -> list[ProofObligation]:
    return [
        _to_proof_obligation(local_obligation)
        for local_obligation in theorem_goal.synthesize_obligations(
            contract_assumptions=contract_assumptions,
            contract_exports=contract_exports,
        )
    ]


def derive_obligations(
    store: ProjectStore,
    theorem_goal: TheoremReasoningGoal,
    *,
    contract_assumptions: list[str] | None = None,
    contract_exports: list[str] | None = None,
    route_notes: str = "",
) -> list[ProofObligation]:
    synthesized = synthesize_obligations(
        theorem_goal,
        contract_assumptions=contract_assumptions,
        contract_exports=contract_exports,
    )
    persisted: list[ProofObligation] = []
    for obligation in synthesized:
        stored = _add_obligation(
            store,
            obligation,
            route_notes=route_notes or f"derived from theorem intent {theorem_goal.id}",
        )
        append_event(
            store,
            "obligation_synthesized",
            f"synthesized obligation {obligation.id} from downstream use",
            entity_id=obligation.id,
            payload={
                "obligation": stored.model_dump(mode="json"),
                "theorem_goal_id": theorem_goal.id,
                "downstream_use_ids": [use.id for use in theorem_goal.downstream_use],
            },
        )
        persisted.append(stored)
    return persisted
