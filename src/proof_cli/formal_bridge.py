from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from .domain import ProofObligation, TheoremContract, utc_now
from .verification_ir import (
    VerificationArtifact,
    VerificationAssumption,
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationQuantifiedGoal,
    VerificationScope,
    VerificationSideCondition,
    VerificationSourceKind,
    VerificationTheoremApplication,
    VerificationTranslationStatus,
)


def _dedupe(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "item"


def _infer_dependency_kind(dependency_id: str) -> Literal[
    "theorem_contract",
    "proof_obligation",
    "imported_result",
    "proof_step",
    "external_reference",
]:
    if dependency_id.startswith("thm_") or dependency_id.startswith("lemma_"):
        return "theorem_contract"
    if dependency_id.startswith("obl_"):
        return "proof_obligation"
    if dependency_id.startswith("vfrag_") or dependency_id.startswith("vchk_"):
        return "imported_result"
    if dependency_id.startswith("step_"):
        return "proof_step"
    return "external_reference"


def _dependency_versions(dependencies: Iterable[str], *, default_version: int = 1) -> list[VerificationDependencyVersion]:
    versions: list[VerificationDependencyVersion] = []
    for dependency_id in _dedupe(dependencies):
        versions.append(
            VerificationDependencyVersion(
                dependency_id=dependency_id,
                version=default_version,
                kind=_infer_dependency_kind(dependency_id),
                digest=f"bridge:{_slug(dependency_id)}:{default_version}",
            )
        )
    return versions


def _scope(
    *,
    project_id: str,
    theorem_id: str | None = None,
    goal_id: str | None = None,
    obligation_id: str | None = None,
    proof_step_id: str | None = None,
    route_id: str | None = None,
    tags: list[str] | None = None,
) -> VerificationScope:
    return VerificationScope(
        project_id=project_id,
        theorem_id=theorem_id,
        goal_id=goal_id,
        obligation_id=obligation_id,
        proof_step_id=proof_step_id,
        route_id=route_id,
        tags=list(tags or []),
    )


def _provenance(
    *,
    source_kind: VerificationSourceKind,
    source_id: str,
    source_label: str = "",
    source_scope: VerificationScope | None = None,
    derived_from_ids: Iterable[str] | None = None,
    machine_path: Iterable[str] | None = None,
    reviewed_by: str | None = None,
) -> VerificationProvenance:
    return VerificationProvenance(
        source_kind=source_kind,
        source_id=source_id,
        source_label=source_label,
        source_scope=source_scope,
        derived_from_ids=_dedupe(derived_from_ids or []),
        machine_path=_dedupe(machine_path or []),
        reviewed_by=reviewed_by,
    )


class FormalBridgeProofStep(BaseModel):
    id: str
    statement: str
    theorem_id: str | None = None
    goal_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    side_conditions: list[str] = Field(default_factory=list)
    fragile: bool = False
    notes: str = ""
    route_id: str | None = None


class FormalBridgeTranslationFailure(BaseModel):
    source_kind: VerificationSourceKind
    source_id: str
    provenance: VerificationProvenance
    reason: str
    lossy_fields: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class FormalBridgeTranslation(BaseModel):
    fragment: VerificationFragment | None = None
    failure: FormalBridgeTranslationFailure | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        return self.fragment is not None and self.failure is None


class FormalBridgeBatchTranslation(BaseModel):
    fragments: list[VerificationFragment] = Field(default_factory=list)
    failures: list[FormalBridgeTranslationFailure] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        return not self.failures


def _translation_failure(
    *,
    source_kind: VerificationSourceKind,
    source_id: str,
    provenance: VerificationProvenance,
    reason: str,
    lossy_fields: Iterable[str] | None = None,
    details: dict[str, Any] | None = None,
) -> FormalBridgeTranslation:
    failure = FormalBridgeTranslationFailure(
        source_kind=source_kind,
        source_id=source_id,
        provenance=provenance,
        reason=reason,
        lossy_fields=_dedupe(lossy_fields or []),
        details=dict(details or {}),
    )
    return FormalBridgeTranslation(failure=failure)


def _fragment(
    *,
    source_type: VerificationSourceKind,
    source_id: str,
    scope: VerificationScope,
    provenance: VerificationProvenance,
    assumptions: list[VerificationAssumption] | None = None,
    quantified_goals: list[VerificationQuantifiedGoal] | None = None,
    theorem_applications: list[VerificationTheoremApplication] | None = None,
    side_conditions: list[VerificationSideCondition] | None = None,
    dependency_versions: list[VerificationDependencyVersion] | None = None,
    backend_target: str | None = None,
    notes: str = "",
) -> VerificationFragment:
    return VerificationFragment(
        source_type=source_type,
        source_id=source_id,
        scope=scope,
        status=VerificationFragmentStatus.queued_for_verification,
        translation_status=VerificationTranslationStatus.translated,
        backend_target=backend_target,
        assumptions=assumptions or [],
        quantified_goals=quantified_goals or [],
        theorem_applications=theorem_applications or [],
        side_conditions=side_conditions or [],
        dependency_versions=dependency_versions or [],
        provenance=provenance,
        notes=notes,
    )


def _standard_step_side_conditions(statement: str, *, explicit_side_conditions: Iterable[str]) -> list[VerificationSideCondition]:
    conditions: list[VerificationSideCondition] = [
        VerificationSideCondition(statement=side_condition, origin="explicit proof-step side condition")
        for side_condition in explicit_side_conditions
    ]
    lower = statement.lower()
    if any(token in lower for token in ("standard", "routine", "obvious", "immediate")):
        conditions.append(
            VerificationSideCondition(
                statement=f"justify the compressed step: {statement}",
                origin="compressed reasoning expanded into an explicit side condition",
            )
        )
    return conditions


def translate_theorem_contract(
    contract: TheoremContract,
    *,
    project_id: str,
    route_id: str | None = None,
    backend_target: str | None = None,
) -> FormalBridgeTranslation:
    if not contract.statement.strip():
        provenance = _provenance(
            source_kind=VerificationSourceKind.theorem_contract,
            source_id=contract.id,
            source_label=contract.name,
            source_scope=_scope(project_id=project_id, theorem_id=contract.id, route_id=route_id, tags=["formal_bridge", "theorem_contract"]),
            derived_from_ids=[contract.id, *contract.dependencies],
            machine_path=["inspect theorem contract", "translate theorem contract"],
        )
        return _translation_failure(
            source_kind=VerificationSourceKind.theorem_contract,
            source_id=contract.id,
            provenance=provenance,
            reason="theorem contract is missing a statement",
            lossy_fields=["statement"],
        )

    scope = _scope(
        project_id=project_id,
        theorem_id=contract.id,
        route_id=route_id,
        tags=["formal_bridge", "theorem_contract"],
    )
    provenance = _provenance(
        source_kind=VerificationSourceKind.theorem_contract,
        source_id=contract.id,
        source_label=contract.name or contract.id,
        source_scope=scope,
        derived_from_ids=[contract.id, *contract.dependencies],
        machine_path=["inspect theorem contract", "translate theorem contract"],
    )
    assumptions = [VerificationAssumption(statement=assumption, source_id=contract.id) for assumption in contract.assumptions]
    quantified_goals = [
        VerificationQuantifiedGoal(
            statement=contract.statement,
            quantifiers=[],
            free_variables=[],
        )
    ]
    fragment = _fragment(
        source_type=VerificationSourceKind.theorem_contract,
        source_id=contract.id,
        scope=scope,
        provenance=provenance,
        assumptions=assumptions,
        quantified_goals=quantified_goals,
        dependency_versions=_dependency_versions(contract.dependencies),
        backend_target=backend_target,
        notes=contract.notes,
    )
    return FormalBridgeTranslation(fragment=fragment)


def translate_proof_obligation(
    obligation: ProofObligation,
    *,
    project_id: str,
    theorem_id: str | None = None,
    route_id: str | None = None,
    backend_target: str | None = None,
) -> FormalBridgeTranslation:
    if not obligation.goal_statement.strip():
        scope = _scope(
            project_id=project_id,
            theorem_id=theorem_id or obligation.required_for,
            obligation_id=obligation.id,
            route_id=route_id,
            tags=["formal_bridge", "proof_obligation"],
        )
        provenance = _provenance(
            source_kind=VerificationSourceKind.proof_obligation,
            source_id=obligation.id,
            source_label=obligation.required_for or obligation.id,
            source_scope=scope,
            derived_from_ids=[obligation.id, *(obligation.dependencies or [])],
            machine_path=["inspect proof obligation", "translate obligation"],
        )
        return _translation_failure(
            source_kind=VerificationSourceKind.proof_obligation,
            source_id=obligation.id,
            provenance=provenance,
            reason="proof obligation is missing a goal statement",
            lossy_fields=["goal_statement"],
        )

    scope = _scope(
        project_id=project_id,
        theorem_id=theorem_id or obligation.required_for,
        obligation_id=obligation.id,
        route_id=route_id,
        tags=["formal_bridge", "proof_obligation"],
    )
    provenance = _provenance(
        source_kind=VerificationSourceKind.proof_obligation,
        source_id=obligation.id,
        source_label=obligation.required_for or obligation.id,
        source_scope=scope,
        derived_from_ids=[obligation.id, *obligation.dependencies, obligation.source_step_id or ""],
        machine_path=["inspect proof obligation", "translate obligation"],
    )
    theorem_applications = []
    if obligation.required_for or obligation.source_step_id:
        theorem_applications.append(
            VerificationTheoremApplication(
                theorem_id=obligation.required_for or obligation.source_step_id or obligation.id,
                theorem_name=obligation.required_for or obligation.id,
                statement=obligation.goal_statement,
                assumptions_used=[],
                side_conditions=[],
                fragile=obligation.status.value != "open",
                notes=obligation.blocking_reason or "machine-checkable obligation",
                reasoning_path=_dedupe([obligation.required_for or obligation.id, obligation.source_step_id or "", obligation.id]),
            )
        )
    fragment = _fragment(
        source_type=VerificationSourceKind.proof_obligation,
        source_id=obligation.id,
        scope=scope,
        provenance=provenance,
        assumptions=[VerificationAssumption(statement=dependency, source_id=obligation.id) for dependency in obligation.dependencies],
        quantified_goals=[VerificationQuantifiedGoal(statement=obligation.goal_statement)],
        theorem_applications=theorem_applications,
        side_conditions=[
            VerificationSideCondition(statement=obligation.blocking_reason, origin="proof obligation blocker")
        ]
        if obligation.blocking_reason
        else [],
        dependency_versions=_dependency_versions([*obligation.dependencies, obligation.source_step_id or ""]),
        backend_target=backend_target,
        notes=obligation.blocking_reason or "",
    )
    return FormalBridgeTranslation(fragment=fragment)


def translate_proof_step(
    step: FormalBridgeProofStep,
    *,
    project_id: str,
    theorem_id: str | None = None,
    goal_id: str | None = None,
    route_id: str | None = None,
    backend_target: str | None = None,
) -> FormalBridgeTranslation:
    if not step.statement.strip():
        scope = _scope(
            project_id=project_id,
            theorem_id=theorem_id or step.theorem_id,
            goal_id=goal_id or step.goal_id,
            proof_step_id=step.id,
            route_id=route_id or step.route_id,
            tags=["formal_bridge", "proof_step"],
        )
        provenance = _provenance(
            source_kind=VerificationSourceKind.proof_step,
            source_id=step.id,
            source_label=step.notes or step.id,
            source_scope=scope,
            derived_from_ids=[step.id, *(step.dependencies or [])],
            machine_path=["inspect proof step", "translate proof step"],
        )
        return _translation_failure(
            source_kind=VerificationSourceKind.proof_step,
            source_id=step.id,
            provenance=provenance,
            reason="proof step is missing a statement",
            lossy_fields=["statement"],
        )

    scope = _scope(
        project_id=project_id,
        theorem_id=theorem_id or step.theorem_id,
        goal_id=goal_id or step.goal_id,
        proof_step_id=step.id,
        route_id=route_id or step.route_id,
        tags=["formal_bridge", "proof_step"],
    )
    provenance = _provenance(
        source_kind=VerificationSourceKind.proof_step,
        source_id=step.id,
        source_label=step.notes or step.id,
        source_scope=scope,
        derived_from_ids=[step.id, step.theorem_id or "", step.goal_id or "", *step.dependencies],
        machine_path=["inspect proof step", "translate proof step", "expand side conditions"],
    )
    assumptions = [VerificationAssumption(statement=assumption, source_id=step.id) for assumption in step.assumptions]
    theorem_application = VerificationTheoremApplication(
        theorem_id=step.theorem_id or step.id,
        theorem_name=step.theorem_id or step.id,
        statement=step.statement,
        assumptions_used=list(step.assumptions),
        side_conditions=list(step.side_conditions),
        fragile=step.fragile,
        notes=step.notes,
        reasoning_path=_dedupe([goal_id or step.goal_id or "", theorem_id or step.theorem_id or "", step.id]),
    )
    fragment = _fragment(
        source_type=VerificationSourceKind.proof_step,
        source_id=step.id,
        scope=scope,
        provenance=provenance,
        assumptions=assumptions,
        quantified_goals=[VerificationQuantifiedGoal(statement=step.statement)],
        theorem_applications=[theorem_application],
        side_conditions=_standard_step_side_conditions(step.statement, explicit_side_conditions=step.side_conditions),
        dependency_versions=_dependency_versions([step.id, *step.dependencies]),
        backend_target=backend_target,
        notes=step.notes,
    )
    return FormalBridgeTranslation(fragment=fragment)


def translate_selection(
    sources: Iterable[TheoremContract | ProofObligation | FormalBridgeProofStep],
    *,
    project_id: str,
    route_id: str | None = None,
    backend_target: str | None = None,
) -> FormalBridgeBatchTranslation:
    fragments: list[VerificationFragment] = []
    failures: list[FormalBridgeTranslationFailure] = []
    for source in sources:
        if isinstance(source, TheoremContract):
            translation = translate_theorem_contract(
                source,
                project_id=project_id,
                route_id=route_id,
                backend_target=backend_target,
            )
        elif isinstance(source, ProofObligation):
            translation = translate_proof_obligation(
                source,
                project_id=project_id,
                route_id=route_id,
                backend_target=backend_target,
            )
        elif isinstance(source, FormalBridgeProofStep):
            translation = translate_proof_step(
                source,
                project_id=project_id,
                route_id=route_id,
                backend_target=backend_target,
            )
        else:
            raise TypeError(f"Unsupported source type: {type(source)!r}")

        if translation.fragment is not None:
            fragments.append(translation.fragment)
        if translation.failure is not None:
            failures.append(translation.failure)

    return FormalBridgeBatchTranslation(fragments=fragments, failures=failures)


def machine_check_trace(fragment: VerificationFragment, *, backend: str, summary: str) -> VerificationArtifact:
    return VerificationArtifact(
        kind="machine-check-trace",
        uri=f"verification://{fragment.id}/{backend}",
        description=summary,
    )


__all__ = [
    "FormalBridgeBatchTranslation",
    "FormalBridgeProofStep",
    "FormalBridgeTranslation",
    "FormalBridgeTranslationFailure",
    "machine_check_trace",
    "translate_proof_obligation",
    "translate_proof_step",
    "translate_selection",
    "translate_theorem_contract",
]
