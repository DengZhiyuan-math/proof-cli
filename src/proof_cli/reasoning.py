from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .domain import utc_now


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


class DownstreamUse(BaseModel):
    id: str
    label: str
    required_assumptions: list[str] = Field(default_factory=list)
    required_exports: list[str] = Field(default_factory=list)
    reasoning_path: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class LocalObligation(BaseModel):
    id: str
    statement: str
    source_unit_id: str
    required_for: str
    dependencies: list[str] = Field(default_factory=list)
    status: Literal["open", "closed", "blocked"] = "open"
    created_at: datetime = Field(default_factory=utc_now)


class LemmaReasoningUnit(BaseModel):
    id: str
    theorem_id: str
    label: str
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    local_obligations: list[LocalObligation] = Field(default_factory=list)
    downstream_use_ids: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def local_unit_ids(self) -> list[str]:
        return [obligation.id for obligation in self.local_obligations]


class TheoremReasoningGoal(BaseModel):
    id: str
    theorem_id: str
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    lemma_units: list[LemmaReasoningUnit] = Field(default_factory=list)
    downstream_use: list[DownstreamUse] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def decompose(self) -> "ReasoningDecomposition":
        return ReasoningDecomposition(
            theorem_goal=self,
            lemma_units=list(self.lemma_units),
            local_obligations=[obligation for lemma in self.lemma_units for obligation in lemma.local_obligations],
        )


class ReasoningDecomposition(BaseModel):
    theorem_goal: TheoremReasoningGoal
    lemma_units: list[LemmaReasoningUnit] = Field(default_factory=list)
    local_obligations: list[LocalObligation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def reasoning_unit_ids(self) -> list[str]:
        ids = [self.theorem_goal.id]
        ids.extend(lemma.id for lemma in self.lemma_units)
        ids.extend(obligation.id for obligation in self.local_obligations)
        return _dedupe(ids)


class ContractAdequacyCheck(BaseModel):
    contract_id: str
    downstream_use: list[DownstreamUse] = Field(default_factory=list)
    required_assumptions: list[str] = Field(default_factory=list)
    required_exports: list[str] = Field(default_factory=list)
    satisfied_assumptions: list[str] = Field(default_factory=list)
    satisfied_exports: list[str] = Field(default_factory=list)
    missing_assumptions: list[str] = Field(default_factory=list)
    missing_exports: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    adequate: bool = False
    review_recommendation: Literal["accept", "revise", "block"] = "revise"
    reasoning_path: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def evaluate(
        cls,
        *,
        contract_id: str,
        contract_assumptions: list[str],
        contract_exports: list[str],
        downstream_use: list[DownstreamUse],
    ) -> "ContractAdequacyCheck":
        required_assumptions = _dedupe([assumption for use in downstream_use for assumption in use.required_assumptions])
        required_exports = _dedupe([export for use in downstream_use for export in use.required_exports])
        satisfied_assumptions = [assumption for assumption in required_assumptions if assumption in contract_assumptions]
        satisfied_exports = [export for export in required_exports if export in contract_exports]
        missing_assumptions = [assumption for assumption in required_assumptions if assumption not in contract_assumptions]
        missing_exports = [export for export in required_exports if export not in contract_exports]
        missing_conditions = [
            *[f"missing assumption: {assumption}" for assumption in missing_assumptions],
            *[f"missing export: {export}" for export in missing_exports],
        ]
        adequate = not missing_conditions
        if adequate:
            recommendation: Literal["accept", "revise", "block"] = "accept"
        elif missing_assumptions:
            recommendation = "block"
        else:
            recommendation = "revise"
        reasoning_path = _dedupe([path for use in downstream_use for path in use.reasoning_path])
        return cls(
            contract_id=contract_id,
            downstream_use=downstream_use,
            required_assumptions=required_assumptions,
            required_exports=required_exports,
            satisfied_assumptions=satisfied_assumptions,
            satisfied_exports=satisfied_exports,
            missing_assumptions=missing_assumptions,
            missing_exports=missing_exports,
            missing_conditions=missing_conditions,
            adequate=adequate,
            review_recommendation=recommendation,
            reasoning_path=reasoning_path,
        )


class ReasoningProject(BaseModel):
    project_id: str
    theorem_goals: list[TheoremReasoningGoal] = Field(default_factory=list)
    adequacy_checks: list[ContractAdequacyCheck] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def all_reasoning_units(self) -> list[str]:
        ids = [goal.id for goal in self.theorem_goals]
        for goal in self.theorem_goals:
            ids.extend(goal.decompose().reasoning_unit_ids())
        return _dedupe(ids)
