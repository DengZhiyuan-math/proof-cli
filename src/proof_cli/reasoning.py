from __future__ import annotations

import re
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


def _dedupe_obligations(obligations: list["LocalObligation"]) -> list["LocalObligation"]:
    unique: list[LocalObligation] = []
    seen: set[str] = set()
    for obligation in obligations:
        if obligation.id in seen:
            continue
        seen.add(obligation.id)
        unique.append(obligation)
    return unique


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "item"


def _obligation_id(*parts: str) -> str:
    return "obl_" + "__".join(_slug(part) for part in parts if part)


class DownstreamUse(BaseModel):
    id: str
    label: str
    required_assumptions: list[str] = Field(default_factory=list)
    required_exports: list[str] = Field(default_factory=list)
    reasoning_path: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    def missing_assumptions(self, contract_assumptions: list[str]) -> list[str]:
        return [assumption for assumption in self.required_assumptions if assumption not in contract_assumptions]

    def missing_exports(self, contract_exports: list[str]) -> list[str]:
        return [export for export in self.required_exports if export not in contract_exports]

    def synthesize_obligations(
        self,
        *,
        goal_id: str,
        contract_assumptions: list[str],
        contract_exports: list[str],
        claim_labels: dict[str, str] | None = None,
    ) -> list["LocalObligation"]:
        claim_labels = claim_labels or {}
        obligations: list[LocalObligation] = []
        path_tokens = [f"downstream_use:{self.id}", f"theorem_intent:{goal_id}"]
        if self.notes:
            path_tokens.append(f"use_note:{_slug(self.notes)}")

        for assumption in self.missing_assumptions(contract_assumptions):
            obligations.append(
                LocalObligation(
                    id=_obligation_id(goal_id, self.id, "missing_assumption", assumption),
                    statement=f"establish missing assumption {assumption} for downstream use {self.label}",
                    source_unit_id=goal_id,
                    required_for=self.id,
                    dependencies=_dedupe([*path_tokens, f"missing_assumption:{assumption}"]),
                )
            )

        for export in self.missing_exports(contract_exports):
            obligations.append(
                LocalObligation(
                    id=_obligation_id(goal_id, self.id, "missing_export", export),
                    statement=f"strengthen export {export} for downstream use {self.label}",
                    source_unit_id=goal_id,
                    required_for=self.id,
                    dependencies=_dedupe([*path_tokens, f"missing_export:{export}"]),
                )
            )

        for claim_id in self.reasoning_path[1:-1]:
            claim_label = claim_labels.get(claim_id, claim_id)
            obligations.append(
                LocalObligation(
                    id=_obligation_id(goal_id, self.id, "intermediate_claim", claim_id),
                    statement=f"establish intermediate claim {claim_label} for downstream use {self.label}",
                    source_unit_id=claim_id,
                    required_for=self.id,
                    dependencies=_dedupe([*path_tokens, f"intermediate_claim:{claim_id}"]),
                )
            )

        return _dedupe_obligations(obligations)


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

    def synthesize_obligations(
        self,
        *,
        contract_assumptions: list[str] | None = None,
        contract_exports: list[str] | None = None,
    ) -> list[LocalObligation]:
        contract_assumptions = contract_assumptions if contract_assumptions is not None else list(self.assumptions)
        contract_exports = contract_exports if contract_exports is not None else list(self.exports)
        claim_labels = {lemma.id: lemma.label for lemma in self.lemma_units}
        obligations: list[LocalObligation] = [obligation for lemma in self.lemma_units for obligation in lemma.local_obligations]
        for downstream_use in self.downstream_use:
            obligations.extend(
                downstream_use.synthesize_obligations(
                    goal_id=self.id,
                    contract_assumptions=contract_assumptions,
                    contract_exports=contract_exports,
                    claim_labels=claim_labels,
                )
            )
        return _dedupe_obligations(obligations)


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

    def synthesize_obligations(
        self,
        *,
        contract_assumptions: list[str] | None = None,
        contract_exports: list[str] | None = None,
    ) -> list[LocalObligation]:
        return self.theorem_goal.synthesize_obligations(
            contract_assumptions=contract_assumptions,
            contract_exports=contract_exports,
        )


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

    def to_obligations(self) -> list[LocalObligation]:
        obligations: list[LocalObligation] = []
        for condition in self.missing_conditions:
            condition_slug = _slug(condition)
            obligations.append(
                LocalObligation(
                    id=_obligation_id(self.contract_id, condition_slug),
                    statement=condition,
                    source_unit_id=self.contract_id,
                    required_for=self.contract_id,
                    dependencies=_dedupe(
                        [
                            f"contract:{self.contract_id}",
                            *[f"reasoning_path:{path}" for path in self.reasoning_path],
                            f"missing_condition:{condition_slug}",
                        ]
                    ),
                )
            )
        return obligations


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

    def synthesize_obligations(self) -> list[LocalObligation]:
        obligations: list[LocalObligation] = []
        for goal in self.theorem_goals:
            obligations.extend(goal.synthesize_obligations())
        for adequacy_check in self.adequacy_checks:
            obligations.extend(adequacy_check.to_obligations())
        return _dedupe_obligations(obligations)
