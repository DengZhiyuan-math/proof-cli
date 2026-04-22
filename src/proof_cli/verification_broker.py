from __future__ import annotations

import re
from enum import Enum
from typing import Iterable, Sequence

from pydantic import BaseModel, Field

from .verification_ir import (
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationSourceKind,
)


class VerificationBackendCategory(str, Enum):
    proof_assistant = "proof_assistant"
    smt = "smt"
    symbolic = "symbolic"
    lightweight = "lightweight"


class VerificationBackendCapability(str, Enum):
    proof_search = "proof_search"
    quantifier_reasoning = "quantifier_reasoning"
    arithmetic_reasoning = "arithmetic_reasoning"
    symbolic_rewriting = "symbolic_rewriting"
    lightweight_check = "lightweight_check"
    trust_sensitive_check = "trust_sensitive_check"
    dependency_sanity = "dependency_sanity"


class VerificationBackendAdapter(BaseModel):
    id: str
    category: VerificationBackendCategory
    backend_name: str
    capabilities: list[VerificationBackendCapability] = Field(default_factory=list)
    priority: int = 0
    description: str = ""

    def supports(self, required_capabilities: Sequence[VerificationBackendCapability]) -> bool:
        supported = set(self.capabilities)
        return all(capability in supported for capability in required_capabilities)

    def matched_capabilities(self, required_capabilities: Sequence[VerificationBackendCapability]) -> list[VerificationBackendCapability]:
        supported = set(self.capabilities)
        return [capability for capability in required_capabilities if capability in supported]


class VerificationBrokerDecision(BaseModel):
    fragment_id: str
    source_type: VerificationSourceKind
    backend_target: VerificationBackendCategory
    adapter_id: str
    backend_name: str
    required_capabilities: list[VerificationBackendCapability] = Field(default_factory=list)
    matched_capabilities: list[VerificationBackendCapability] = Field(default_factory=list)
    missing_capabilities: list[VerificationBackendCapability] = Field(default_factory=list)
    fallback_categories: list[VerificationBackendCategory] = Field(default_factory=list)
    candidates_considered: list[str] = Field(default_factory=list)
    reason: str = ""


_CATEGORY_STRENGTH_ORDER = [
    VerificationBackendCategory.proof_assistant,
    VerificationBackendCategory.smt,
    VerificationBackendCategory.symbolic,
    VerificationBackendCategory.lightweight,
]

_QUANTIFIER_PATTERN = re.compile(r"\b(for all|there exists|forall|exists)\b|[∀∃]", re.IGNORECASE)
_ARITHMETIC_PATTERN = re.compile(r"(<=|>=|<|>|\+|/|\b(?:integer|natural|arith|arithmetic|linear|presburger|inequality|numeric)\b)", re.IGNORECASE)
_SYMBOLIC_PATTERN = re.compile(
    r"\b(?:rewrite|rewriting|simplify|normalize|normalise|equation|equality|substitute|substitution|factor|expand|algebra|cancel|term)\b",
    re.IGNORECASE,
)


def _unique(values: Iterable[VerificationBackendCapability | VerificationBackendCategory | str]) -> list:
    seen: list = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def default_backend_adapters() -> list[VerificationBackendAdapter]:
    return [
        VerificationBackendAdapter(
            id="proof_assistant.default",
            category=VerificationBackendCategory.proof_assistant,
            backend_name="proof-assistant-adapter",
            capabilities=[
                VerificationBackendCapability.proof_search,
                VerificationBackendCapability.quantifier_reasoning,
                VerificationBackendCapability.arithmetic_reasoning,
                VerificationBackendCapability.symbolic_rewriting,
                VerificationBackendCapability.lightweight_check,
                VerificationBackendCapability.trust_sensitive_check,
                VerificationBackendCapability.dependency_sanity,
            ],
            priority=100,
            description="capability-rich route for theorem-like fragments and fragile applications",
        ),
        VerificationBackendAdapter(
            id="smt.default",
            category=VerificationBackendCategory.smt,
            backend_name="smt-adapter",
            capabilities=[
                VerificationBackendCapability.quantifier_reasoning,
                VerificationBackendCapability.arithmetic_reasoning,
                VerificationBackendCapability.lightweight_check,
                VerificationBackendCapability.dependency_sanity,
            ],
            priority=80,
            description="constraint-style route for quantified and arithmetic obligations",
        ),
        VerificationBackendAdapter(
            id="symbolic.default",
            category=VerificationBackendCategory.symbolic,
            backend_name="symbolic-adapter",
            capabilities=[
                VerificationBackendCapability.symbolic_rewriting,
                VerificationBackendCapability.lightweight_check,
                VerificationBackendCapability.dependency_sanity,
            ],
            priority=60,
            description="rewrite and simplification route for algebraic or term-oriented fragments",
        ),
        VerificationBackendAdapter(
            id="lightweight.default",
            category=VerificationBackendCategory.lightweight,
            backend_name="lightweight-adapter",
            capabilities=[
                VerificationBackendCapability.lightweight_check,
                VerificationBackendCapability.dependency_sanity,
            ],
            priority=40,
            description="shallow sanity route for low-risk or review-only fragments",
        ),
    ]


def _fragment_text(fragment: VerificationFragment) -> str:
    theorem_applications = " ".join(application.statement for application in fragment.theorem_applications)
    quantified_goals = " ".join(goal.statement for goal in fragment.quantified_goals)
    side_conditions = " ".join(condition.statement for condition in fragment.side_conditions)
    assumptions = " ".join(assumption.statement for assumption in fragment.assumptions)
    return " ".join(
        part
        for part in [
            fragment.source_type.value,
            fragment.source_id,
            fragment.notes,
            theorem_applications,
            quantified_goals,
            side_conditions,
            assumptions,
            fragment.provenance.source_label,
        ]
        if part
    )


def _cue_tokens(fragment: VerificationFragment) -> dict[str, bool]:
    text = _fragment_text(fragment)
    theorem_like = bool(fragment.theorem_applications) or fragment.source_type in {
        VerificationSourceKind.theorem_contract,
        VerificationSourceKind.theorem_application,
    }
    fragile_application = any(application.fragile for application in fragment.theorem_applications)
    proof_obligation_blocked = fragment.source_type == VerificationSourceKind.proof_obligation and (
        "block" in text.lower() or "fragile" in text.lower() or "side condition" in text.lower()
    )
    imported_result = fragment.source_type == VerificationSourceKind.imported_result
    quantifier_cue = bool(_QUANTIFIER_PATTERN.search(text))
    arithmetic_cue = bool(_ARITHMETIC_PATTERN.search(text))
    symbolic_cue = bool(_SYMBOLIC_PATTERN.search(text))
    return {
        "theorem_like": theorem_like,
        "fragile_application": fragile_application,
        "proof_obligation_blocked": proof_obligation_blocked,
        "imported_result": imported_result,
        "quantifier_cue": quantifier_cue,
        "arithmetic_cue": arithmetic_cue,
        "symbolic_cue": symbolic_cue,
    }


def _preferred_category(fragment: VerificationFragment, cues: dict[str, bool]) -> tuple[VerificationBackendCategory, list[str], list[VerificationBackendCapability]]:
    reasons: list[str] = []
    required: list[VerificationBackendCapability] = [
        VerificationBackendCapability.dependency_sanity,
    ]

    if cues["theorem_like"] or cues["fragile_application"] or cues["proof_obligation_blocked"]:
        reasons.append("the fragment is theorem-like or fragile, so proof-assistant checking is the strongest practical route")
        required.extend(
            [
                VerificationBackendCapability.proof_search,
                VerificationBackendCapability.trust_sensitive_check,
            ]
        )
        if cues["quantifier_cue"]:
            required.append(VerificationBackendCapability.quantifier_reasoning)
        if cues["arithmetic_cue"]:
            required.append(VerificationBackendCapability.arithmetic_reasoning)
        if cues["symbolic_cue"]:
            required.append(VerificationBackendCapability.symbolic_rewriting)
        return VerificationBackendCategory.proof_assistant, reasons, _unique(required)

    if cues["symbolic_cue"]:
        reasons.append("the fragment is rewrite-oriented, so symbolic checking is the strongest practical route")
        required.append(VerificationBackendCapability.symbolic_rewriting)
        return VerificationBackendCategory.symbolic, reasons, _unique(required)

    if cues["quantifier_cue"] or cues["arithmetic_cue"]:
        reasons.append("the fragment contains quantifier or arithmetic cues, so SMT is the strongest practical route")
        required.extend(
            [
                VerificationBackendCapability.quantifier_reasoning,
                VerificationBackendCapability.arithmetic_reasoning,
            ]
        )
        return VerificationBackendCategory.smt, reasons, _unique(required)

    if cues["imported_result"]:
        reasons.append("the fragment is an imported result, so lightweight review is the default route")
    else:
        reasons.append("the fragment has no stronger cue, so lightweight checking is the default route")
    required.append(VerificationBackendCapability.lightweight_check)
    return VerificationBackendCategory.lightweight, reasons, _unique(required)


def _category_sequence(preferred: VerificationBackendCategory) -> list[VerificationBackendCategory]:
    return [preferred, *[category for category in _CATEGORY_STRENGTH_ORDER if category != preferred]]


class VerificationBroker(BaseModel):
    adapters: list[VerificationBackendAdapter] = Field(default_factory=default_backend_adapters)

    def adapters_for_category(self, category: VerificationBackendCategory) -> list[VerificationBackendAdapter]:
        return [adapter for adapter in self.adapters if adapter.category == category]

    def select(self, fragment: VerificationFragment) -> VerificationBrokerDecision:
        cues = _cue_tokens(fragment)
        preferred_category, reasons, required_capabilities = _preferred_category(fragment, cues)
        category_order = _category_sequence(preferred_category)
        fallback_categories = [category for category in category_order if category != preferred_category]

        candidates_considered: list[str] = []
        for category in category_order:
            category_adapters = self.adapters_for_category(category)
            if not category_adapters:
                continue
            for adapter in sorted(category_adapters, key=lambda item: (-item.priority, item.backend_name, item.id)):
                candidates_considered.append(adapter.id)
                if not adapter.supports(required_capabilities):
                    continue
                matched_capabilities = adapter.matched_capabilities(required_capabilities)
                missing_capabilities = [capability for capability in required_capabilities if capability not in matched_capabilities]
                return VerificationBrokerDecision(
                    fragment_id=fragment.id,
                    source_type=fragment.source_type,
                    backend_target=category,
                    adapter_id=adapter.id,
                    backend_name=adapter.backend_name,
                    required_capabilities=required_capabilities,
                    matched_capabilities=matched_capabilities,
                    missing_capabilities=missing_capabilities,
                    fallback_categories=fallback_categories,
                    candidates_considered=candidates_considered,
                    reason="; ".join(reasons),
                )

        raise ValueError(f"no backend adapter could satisfy fragment {fragment.id!r}")

    def route_fragment(self, fragment: VerificationFragment) -> tuple[VerificationFragment, VerificationBrokerDecision]:
        decision = self.select(fragment)
        routed_fragment = fragment.queue_for_verification(backend_target=decision.backend_target.value)
        return routed_fragment, decision


def build_default_verification_broker() -> VerificationBroker:
    return VerificationBroker()


def route_verification_fragment(
    fragment: VerificationFragment,
    *,
    broker: VerificationBroker | None = None,
) -> tuple[VerificationFragment, VerificationBrokerDecision]:
    return (broker or build_default_verification_broker()).route_fragment(fragment)


__all__ = [
    "VerificationBackendAdapter",
    "VerificationBackendCapability",
    "VerificationBackendCategory",
    "VerificationBroker",
    "VerificationBrokerDecision",
    "build_default_verification_broker",
    "default_backend_adapters",
    "route_verification_fragment",
]
