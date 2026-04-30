from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field

from .domain import ProjectState, TheoremContract
from .domain_packs import DomainPack, DomainPackReviewStatus, DomainPackTrustLevel
from .memory import list_memory_artifacts, load_memory
from .reusable_assets import (
    ReusableAsset,
    ReusableAssetReuseStatus,
    ReusableAssetTrustLevel,
)
from .storage import ProjectStore, list_blockers, list_contracts, list_obligations, read_state


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class RetrievalSourceKind(str, Enum):
    project_local = "project_local"
    imported_reference = "imported_reference"
    external_bibliographic = "external_bibliographic"


class RetrievalContext(BaseModel):
    project_id: str
    current_theorem: str | None = None
    current_context: list[str] = Field(default_factory=list)
    open_goals: list[str] = Field(default_factory=list)
    open_obligations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recent_theorem_usage: list[str] = Field(default_factory=list)
    recent_memory: list[str] = Field(default_factory=list)
    explicit_neighborhood: list[str] = Field(default_factory=list)


class RetrievalCandidate(BaseModel):
    id: str
    title: str
    source_kind: RetrievalSourceKind
    source_ref: str
    source_priority: int
    score: float
    structural_score: float = 0.0
    lexical_score: float = 0.0
    rank: int = 0
    contract_id: str | None = None
    contract_status: str | None = None
    trust_level: str | None = None
    match_reasons: list[str] = Field(default_factory=list)
    structural_reasons: list[str] = Field(default_factory=list)
    lexical_reasons: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class RetrievalSourceTrace(BaseModel):
    source_kind: RetrievalSourceKind
    evaluated_count: int
    candidate_ids: list[str] = Field(default_factory=list)


class RetrievalReport(BaseModel):
    query: str
    project_context: RetrievalContext
    source_order: list[RetrievalSourceKind] = Field(default_factory=list)
    candidates: list[RetrievalCandidate] = Field(default_factory=list)
    trace: list[RetrievalSourceTrace] = Field(default_factory=list)


class CrossProjectSourceKind(str, Enum):
    project_local = "project_local"
    shared_domain = "shared_domain"
    prior_project = "prior_project"
    domain_pack = "domain_pack"


class CrossProjectRetrievalCandidate(BaseModel):
    id: str
    title: str
    source_kind: CrossProjectSourceKind
    source_ref: str
    origin_project_id: str = ""
    trust_level: str = ""
    reuse_status: str = ""
    trust_score: float = 0.0
    prior_usefulness_score: float = 0.0
    similarity_score: float = 0.0
    provenance_score: float = 0.0
    score: float = 0.0
    source_priority: int = 0
    rank: int = 0
    match_reasons: list[str] = Field(default_factory=list)
    provenance_reasons: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class CrossProjectRetrievalSourceTrace(BaseModel):
    source_kind: CrossProjectSourceKind
    evaluated_count: int
    candidate_ids: list[str] = Field(default_factory=list)


class CrossProjectRetrievalReport(BaseModel):
    query: str
    current_project_id: str
    source_order: list[CrossProjectSourceKind] = Field(default_factory=list)
    candidates: list[CrossProjectRetrievalCandidate] = Field(default_factory=list)
    trace: list[CrossProjectRetrievalSourceTrace] = Field(default_factory=list)


def _tokens(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(token.lower() for token in TOKEN_RE.findall(part or ""))
    return tokens


def _clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _score_text(query_terms: set[str], *parts: str) -> tuple[float, list[str]]:
    if not query_terms:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []
    for part in parts:
        part_terms = _tokens(part)
        overlap = sorted(query_terms & part_terms)
        if not overlap:
            continue
        score += float(len(overlap))
        reasons.append(f"matched {', '.join(overlap)}")
    return score, reasons


def _classify_contract(contract: TheoremContract) -> RetrievalSourceKind:
    if contract.source_ref.startswith("internal/"):
        return RetrievalSourceKind.project_local
    return RetrievalSourceKind.imported_reference


def _build_context(state: ProjectState) -> RetrievalContext:
    return RetrievalContext(
        project_id=state.project_id,
        current_theorem=state.current_theorem,
        current_context=list(state.current_context),
        open_goals=list(state.open_goals),
        open_obligations=list(state.open_obligations),
        blockers=list(state.blockers),
        recent_theorem_usage=list(state.recent_theorem_usage),
        recent_memory=[],
        explicit_neighborhood=[],
    )


def _query_terms(query: str | None, context: RetrievalContext) -> set[str]:
    if query and query.strip():
        return _tokens(query)
    return _tokens(
        context.current_theorem or "",
        " ".join(context.current_context),
        " ".join(context.open_goals),
        " ".join(context.open_obligations),
        " ".join(context.blockers),
        " ".join(context.recent_theorem_usage),
        " ".join(context.recent_memory),
        " ".join(context.explicit_neighborhood),
    )


def _candidate_text(contract: TheoremContract) -> str:
    return " ".join(
        part
        for part in [
            contract.id,
            contract.kind,
            contract.name,
            contract.statement,
            " ".join(contract.assumptions),
            " ".join(contract.exports),
            " ".join(contract.dependencies),
            contract.notes,
            contract.source_ref,
        ]
        if part
    )


def _structural_context(store: ProjectStore, state: ProjectState) -> tuple[list[str], list[str]]:
    memory = load_memory(store)
    contracts = list_contracts(store)
    obligations = list_obligations(store)
    blockers = list_blockers(store)
    contract_by_id = {contract.id: contract for contract in contracts}

    neighborhood: list[str] = []
    if state.current_theorem:
        neighborhood.append(f"theorem:{state.current_theorem}")
        current_contract = contract_by_id.get(state.current_theorem)
        if current_contract is not None:
            neighborhood.extend(f"dependency:{dependency}" for dependency in current_contract.dependencies)
            neighborhood.extend(
                f"dependent:{contract.id}"
                for contract in contracts
                if state.current_theorem in contract.dependencies
            )
    neighborhood.extend(f"goal:{goal}" for goal in state.open_goals)
    neighborhood.extend(f"obligation:{obligation.id}" for obligation in obligations if obligation.required_for in {None, state.current_theorem})
    neighborhood.extend(f"blocker:{blocker.id}" for blocker in blockers if blocker.scope in {state.current_theorem, "global"} or state.current_theorem in blocker.related_contracts)
    neighborhood.extend(
        f"memory:{artifact.id}"
        for artifact in list_memory_artifacts(store)
        if state.current_theorem is None
        or artifact.scope.theorem_id in {None, state.current_theorem}
        or artifact.linked_proof_state.theorem_id in {None, state.current_theorem}
    )
    neighborhood = list(dict.fromkeys(neighborhood))[-12:]
    recent_memory = [artifact.content for artifact in (memory.working[-3:] + memory.semantic[-3:] + memory.episodic[-2:] + memory.procedural[-2:])]
    return recent_memory[-5:], neighborhood


def _structural_score(candidate: TheoremContract, context: RetrievalContext) -> tuple[float, list[str]]:
    candidate_terms = _tokens(_candidate_text(candidate))
    score = 0.0
    reasons: list[str] = []

    if context.current_theorem and candidate.id == context.current_theorem:
        score += 0.65
        reasons.append(f"matches active theorem {context.current_theorem}")
    if context.current_theorem and context.current_theorem in candidate.dependencies:
        score += 0.35
        reasons.append(f"depends on active theorem {context.current_theorem}")

    for obligation in context.open_obligations:
        tokens = _tokens(obligation)
        overlap = sorted(tokens & candidate_terms)
        if overlap:
            score += 0.08 * len(overlap)
            reasons.append(f"aligns with open obligation {obligation}")

    for blocker in context.blockers:
        tokens = _tokens(blocker)
        overlap = sorted(tokens & candidate_terms)
        if overlap:
            score += 0.08 * len(overlap)
            reasons.append(f"aligns with blocker {blocker}")

    for memory_text in context.recent_memory:
        tokens = _tokens(memory_text)
        overlap = sorted(tokens & candidate_terms)
        if overlap:
            score += 0.04 * len(overlap)
            reasons.append(f"matches recent memory: {memory_text}")

    for neighborhood_item in context.explicit_neighborhood:
        tokens = _tokens(neighborhood_item)
        overlap = sorted(tokens & candidate_terms)
        if overlap:
            score += 0.06 * len(overlap)
            reasons.append(f"adjacent to {neighborhood_item}")

    if context.current_context:
        overlap = sorted(_tokens(" ".join(context.current_context)) & candidate_terms)
        if overlap:
            score += 0.1 * len(overlap)
            reasons.append(f"matches current context: {', '.join(overlap)}")

    if not reasons:
        reasons.append("no explicit structural link found")

    return _clamp(score, upper=1.5), reasons


def _candidate_payload(contract: TheoremContract) -> dict[str, Any]:
    return contract.model_dump(mode="json")


def _external_payload(reference: Mapping[str, Any]) -> dict[str, Any]:
    return dict(reference)


def _make_candidate(
    *,
    item_id: str,
    title: str,
    source_kind: RetrievalSourceKind,
    source_ref: str,
    source_priority: int,
    score: float,
    structural_score: float = 0.0,
    lexical_score: float = 0.0,
    contract: TheoremContract | None = None,
    reference: Mapping[str, Any] | None = None,
    match_reasons: list[str] | None = None,
    structural_reasons: list[str] | None = None,
    lexical_reasons: list[str] | None = None,
) -> RetrievalCandidate:
    payload: dict[str, Any]
    if contract is not None:
        payload = _candidate_payload(contract)
    elif reference is not None:
        payload = _external_payload(reference)
    else:
        payload = {}
    return RetrievalCandidate(
        id=item_id,
        title=title,
        source_kind=source_kind,
        source_ref=source_ref,
        source_priority=source_priority,
        score=score,
        structural_score=structural_score,
        lexical_score=lexical_score,
        contract_id=contract.id if contract is not None else None,
        contract_status=contract.status.value if contract is not None else None,
        trust_level=contract.trust_level.value if contract is not None else None,
        match_reasons=match_reasons or [],
        structural_reasons=structural_reasons or [],
        lexical_reasons=lexical_reasons or [],
        payload=payload,
    )


def _rank_candidates(candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            candidate.source_priority,
            -candidate.structural_score,
            -candidate.score,
            candidate.title.lower(),
            candidate.id,
        ),
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
    return ranked


def _asset_text(asset: ReusableAsset) -> str:
    payload = asset.payload
    provenance = asset.provenance
    return " ".join(
        part
        for part in [
            asset.id,
            asset.name,
            asset.summary,
            payload.statement,
            " ".join(payload.assumptions),
            " ".join(payload.exports),
            " ".join(payload.pattern_steps),
            " ".join(payload.repair_steps),
            " ".join(payload.bug_signals),
            " ".join(payload.verification_targets),
            " ".join(payload.method_steps),
            " ".join(payload.checklist_items),
            payload.notes,
            provenance.origin_project_id,
            provenance.origin_asset_id,
            " ".join(provenance.source_contract_ids),
            " ".join(provenance.source_reference_ids),
            " ".join(provenance.derived_from_asset_ids),
            " ".join(provenance.linked_blocker_ids),
            " ".join(provenance.linked_repair_ids),
            " ".join(provenance.linked_verification_fragment_ids),
            provenance.notes,
        ]
        if part
    ).lower()


def _pack_text(pack: DomainPack) -> str:
    content = pack.content
    compatibility = pack.compatibility
    return " ".join(
        part
        for part in [
            pack.id,
            pack.name,
            pack.summary,
            " ".join(content.theorem_templates),
            " ".join(content.method_templates),
            " ".join(content.omission_rules),
            " ".join(content.bug_patterns),
            " ".join(content.formalization_preferences),
            " ".join(content.debug_task_templates),
            " ".join(content.notation_conventions),
            content.notes,
            " ".join(compatibility.required_project_tags),
            " ".join(compatibility.required_asset_ids),
            " ".join(compatibility.required_asset_kinds),
            compatibility.required_notation_profile,
            " ".join(compatibility.allowed_pack_versions),
            compatibility.notes,
            pack.reviewed_by,
            pack.review_notes,
            pack.origin_project_id,
            " ".join(pack.source_asset_ids),
            pack.notes,
        ]
        if part
    ).lower()


def _normalized_score(score: float, *, query_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return _clamp(score / max(1.0, float(len(query_terms))))


def _prior_usefulness_score(item_id: str, prior_usefulness: Mapping[str, float] | None) -> float:
    if not prior_usefulness:
        return 0.0
    value = float(prior_usefulness.get(item_id, 0.0))
    return _clamp(value)


def _asset_trust_score(asset: ReusableAsset) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if asset.reuse_status in {
        ReusableAssetReuseStatus.approved_reusable,
        ReusableAssetReuseStatus.domain_shared,
    }:
        score = 0.92
        reasons.append(f"reuse status {asset.reuse_status.value} supports cross-project reuse")
    elif asset.reuse_status == ReusableAssetReuseStatus.private_experimental:
        score = 0.52
        reasons.append("private experimental asset keeps some provenance but still needs review")
    elif asset.reuse_status == ReusableAssetReuseStatus.project_local:
        score = 0.44
        reasons.append("project-local asset is useful but not yet cross-project reviewed")
    elif asset.reuse_status == ReusableAssetReuseStatus.deprecated:
        score = 0.18
        reasons.append("deprecated asset should be used cautiously")
    else:
        score = 0.3
        reasons.append(f"reuse status {asset.reuse_status.value} has limited trust")

    if asset.trust_level in {
        ReusableAssetTrustLevel.domain_trusted,
        ReusableAssetTrustLevel.reviewed_reusable,
        ReusableAssetTrustLevel.foundational,
    }:
        score += 0.06
        reasons.append(f"trust level {asset.trust_level.value} increases confidence")
    elif asset.trust_level == ReusableAssetTrustLevel.project_verified:
        score += 0.03
        reasons.append("project verification provides a modest trust bump")
    elif asset.trust_level == ReusableAssetTrustLevel.temporary_admit:
        reasons.append("temporary admit leaves the asset review-sensitive")

    return _clamp(score), reasons


def _pack_trust_score(pack: DomainPack) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if pack.review_status == DomainPackReviewStatus.approved:
        score = 0.94
        reasons.append("approved domain pack is reusable across projects")
    elif pack.review_status == DomainPackReviewStatus.pending_review:
        score = 0.48
        reasons.append("pending review pack is not yet broadly trusted")
    elif pack.review_status == DomainPackReviewStatus.rejected:
        score = 0.18
        reasons.append("rejected pack should not be promoted without review")
    else:
        score = 0.3
        reasons.append(f"pack review status {pack.review_status.value} is limited")

    if pack.trust_level in {
        DomainPackTrustLevel.reviewed_reusable,
        DomainPackTrustLevel.domain_trusted,
    }:
        score += 0.05
        reasons.append(f"trust level {pack.trust_level.value} strengthens the pack")
    elif pack.trust_level == DomainPackTrustLevel.temporary_admit:
        reasons.append("temporary admit leaves the pack review-sensitive")

    return _clamp(score), reasons


def _asset_provenance_score(asset: ReusableAsset) -> tuple[float, list[str]]:
    provenance = asset.provenance
    signal_count = sum(
        1
        for value in [
            provenance.origin_project_id,
            provenance.origin_asset_id,
            *provenance.source_contract_ids,
            *provenance.source_reference_ids,
            *provenance.derived_from_asset_ids,
            *provenance.linked_blocker_ids,
            *provenance.linked_repair_ids,
            *provenance.linked_verification_fragment_ids,
            provenance.notes,
        ]
        if value
    )
    score = _clamp(0.18 + (0.07 * min(signal_count, 6)))
    reasons = [f"asset provenance exposes {signal_count} supporting signal(s)"]
    if provenance.origin_project_id:
        reasons.append(f"originated in project {provenance.origin_project_id}")
    if provenance.source_contract_ids:
        reasons.append(f"linked contracts: {', '.join(provenance.source_contract_ids)}")
    if provenance.source_reference_ids:
        reasons.append(f"linked references: {', '.join(provenance.source_reference_ids)}")
    if provenance.derived_from_asset_ids:
        reasons.append(f"derived from asset(s): {', '.join(provenance.derived_from_asset_ids)}")
    if provenance.linked_blocker_ids:
        reasons.append(f"linked blocker(s): {', '.join(provenance.linked_blocker_ids)}")
    if provenance.linked_repair_ids:
        reasons.append(f"linked repair(s): {', '.join(provenance.linked_repair_ids)}")
    if provenance.linked_verification_fragment_ids:
        reasons.append(f"linked verification fragment(s): {', '.join(provenance.linked_verification_fragment_ids)}")
    if provenance.notes:
        reasons.append(provenance.notes)
    return score, reasons


def _pack_provenance_score(pack: DomainPack) -> tuple[float, list[str]]:
    signals = [
        pack.origin_project_id,
        *pack.source_asset_ids,
        pack.review_notes,
        pack.notes,
    ]
    signal_count = sum(1 for value in signals if value)
    score = _clamp(0.2 + (0.08 * min(signal_count, 5)))
    reasons = [f"domain pack provenance exposes {signal_count} supporting signal(s)"]
    if pack.origin_project_id:
        reasons.append(f"originated in project {pack.origin_project_id}")
    if pack.source_asset_ids:
        reasons.append(f"includes source asset(s): {', '.join(pack.source_asset_ids)}")
    if pack.review_notes:
        reasons.append(pack.review_notes)
    if pack.notes:
        reasons.append(pack.notes)
    return score, reasons


def _candidate_score(
    *,
    similarity_score: float,
    trust_score: float,
    prior_usefulness_score: float,
    provenance_score: float,
) -> float:
    return _clamp(
        (similarity_score * 0.42)
        + (trust_score * 0.24)
        + (prior_usefulness_score * 0.18)
        + (provenance_score * 0.16)
    )


def _asset_candidate(
    asset: ReusableAsset,
    *,
    source_kind: CrossProjectSourceKind,
    source_priority: int,
    query_terms: set[str],
    prior_usefulness: Mapping[str, float] | None,
) -> CrossProjectRetrievalCandidate:
    score, match_reasons = _score_text(
        query_terms,
        asset.name,
        asset.summary,
        asset.payload.statement,
        " ".join(asset.payload.assumptions),
        " ".join(asset.payload.exports),
        " ".join(asset.payload.pattern_steps),
        " ".join(asset.payload.repair_steps),
        " ".join(asset.payload.bug_signals),
        " ".join(asset.payload.verification_targets),
        " ".join(asset.payload.method_steps),
        " ".join(asset.payload.checklist_items),
        asset.payload.notes,
        asset.provenance.notes,
    )
    similarity_score = _normalized_score(score, query_terms=query_terms)
    trust_score, trust_reasons = _asset_trust_score(asset)
    provenance_score, provenance_reasons = _asset_provenance_score(asset)
    prior_score = _prior_usefulness_score(asset.id, prior_usefulness)
    total_score = _candidate_score(
        similarity_score=similarity_score,
        trust_score=trust_score,
        prior_usefulness_score=prior_score,
        provenance_score=provenance_score,
    )
    if not query_terms:
        match_reasons.append("no query terms supplied; scored from trust and provenance only")
    return CrossProjectRetrievalCandidate(
        id=asset.id,
        title=asset.name,
        source_kind=source_kind,
        source_ref=asset.provenance.origin_asset_id or asset.id,
        origin_project_id=asset.provenance.origin_project_id,
        trust_level=asset.trust_level.value,
        reuse_status=asset.reuse_status.value,
        trust_score=trust_score,
        prior_usefulness_score=prior_score,
        similarity_score=similarity_score,
        provenance_score=provenance_score,
        score=total_score,
        source_priority=source_priority,
        match_reasons=[*match_reasons, *trust_reasons],
        provenance_reasons=provenance_reasons,
        payload=asset.model_dump(mode="json"),
    )


def _pack_candidate(
    pack: DomainPack,
    *,
    source_priority: int,
    query_terms: set[str],
    prior_usefulness: Mapping[str, float] | None,
) -> CrossProjectRetrievalCandidate:
    score, match_reasons = _score_text(
        query_terms,
        pack.name,
        pack.summary,
        " ".join(pack.content.theorem_templates),
        " ".join(pack.content.method_templates),
        " ".join(pack.content.omission_rules),
        " ".join(pack.content.bug_patterns),
        " ".join(pack.content.formalization_preferences),
        " ".join(pack.content.debug_task_templates),
        " ".join(pack.content.notation_conventions),
        pack.content.notes,
        " ".join(pack.compatibility.required_project_tags),
        " ".join(pack.compatibility.required_asset_ids),
        " ".join(pack.compatibility.required_asset_kinds),
        pack.compatibility.required_notation_profile,
        pack.compatibility.notes,
        pack.review_notes,
        pack.notes,
    )
    similarity_score = _normalized_score(score, query_terms=query_terms)
    trust_score, trust_reasons = _pack_trust_score(pack)
    provenance_score, provenance_reasons = _pack_provenance_score(pack)
    prior_score = _prior_usefulness_score(pack.id, prior_usefulness)
    total_score = _candidate_score(
        similarity_score=similarity_score,
        trust_score=trust_score,
        prior_usefulness_score=prior_score,
        provenance_score=provenance_score,
    )
    if not query_terms:
        match_reasons.append("no query terms supplied; scored from trust and provenance only")
    return CrossProjectRetrievalCandidate(
        id=pack.id,
        title=pack.name,
        source_kind=CrossProjectSourceKind.domain_pack,
        source_ref=pack.id,
        origin_project_id=pack.origin_project_id,
        trust_level=pack.trust_level.value,
        reuse_status=pack.review_status.value,
        trust_score=trust_score,
        prior_usefulness_score=prior_score,
        similarity_score=similarity_score,
        provenance_score=provenance_score,
        score=total_score,
        source_priority=source_priority,
        match_reasons=[*match_reasons, *trust_reasons],
        provenance_reasons=provenance_reasons,
        payload=pack.model_dump(mode="json"),
    )


def _rank_cross_project_candidates(
    candidates: list[CrossProjectRetrievalCandidate],
) -> list[CrossProjectRetrievalCandidate]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            -candidate.trust_score,
            -candidate.prior_usefulness_score,
            -candidate.provenance_score,
            -candidate.similarity_score,
            candidate.source_priority,
            candidate.title.lower(),
            candidate.id,
        ),
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
    return ranked


def retrieve_cross_project_assets(
    *,
    current_project_id: str,
    query: str | None = None,
    current_project_assets: Sequence[ReusableAsset] | None = None,
    shared_assets: Sequence[ReusableAsset] | None = None,
    prior_project_assets: Sequence[ReusableAsset] | None = None,
    domain_packs: Sequence[DomainPack] | None = None,
    prior_usefulness: Mapping[str, float] | None = None,
    limit: int = 10,
) -> CrossProjectRetrievalReport:
    query_terms = _tokens(query or "")
    source_order = [
        CrossProjectSourceKind.project_local,
        CrossProjectSourceKind.shared_domain,
        CrossProjectSourceKind.prior_project,
        CrossProjectSourceKind.domain_pack,
    ]
    trace: list[CrossProjectRetrievalSourceTrace] = []
    candidates: list[CrossProjectRetrievalCandidate] = []

    grouped_sources: list[tuple[CrossProjectSourceKind, Sequence[Any]]] = [
        (CrossProjectSourceKind.project_local, list(current_project_assets or [])),
        (CrossProjectSourceKind.shared_domain, list(shared_assets or [])),
        (CrossProjectSourceKind.prior_project, list(prior_project_assets or [])),
    ]
    for source_kind, assets in grouped_sources:
        source_candidates: list[CrossProjectRetrievalCandidate] = []
        for asset in assets:
            source_candidates.append(
                _asset_candidate(
                    asset,
                    source_kind=source_kind,
                    source_priority=source_order.index(source_kind),
                    query_terms=query_terms,
                    prior_usefulness=prior_usefulness,
                )
            )
        trace.append(
            CrossProjectRetrievalSourceTrace(
                source_kind=source_kind,
                evaluated_count=len(assets),
                candidate_ids=[candidate.id for candidate in source_candidates],
            )
        )
        candidates.extend(source_candidates)

    pack_candidates: list[CrossProjectRetrievalCandidate] = []
    pack_list = list(domain_packs or [])
    for pack in pack_list:
        pack_candidates.append(
            _pack_candidate(
                pack,
                source_priority=source_order.index(CrossProjectSourceKind.domain_pack),
                query_terms=query_terms,
                prior_usefulness=prior_usefulness,
            )
        )
    trace.append(
        CrossProjectRetrievalSourceTrace(
            source_kind=CrossProjectSourceKind.domain_pack,
            evaluated_count=len(pack_list),
            candidate_ids=[candidate.id for candidate in pack_candidates],
        )
    )
    candidates.extend(pack_candidates)

    ranked = _rank_cross_project_candidates(candidates)[:limit]
    return CrossProjectRetrievalReport(
        query=query or " ".join(sorted(query_terms)),
        current_project_id=current_project_id,
        source_order=source_order,
        candidates=ranked,
        trace=trace,
    )


__all__ = [
    "CrossProjectRetrievalCandidate",
    "CrossProjectRetrievalReport",
    "CrossProjectRetrievalSourceTrace",
    "CrossProjectSourceKind",
    "RetrievalCandidate",
    "RetrievalContext",
    "RetrievalReport",
    "RetrievalSourceKind",
    "RetrievalSourceTrace",
    "retrieve_candidates",
    "retrieve_cross_project_assets",
]


def retrieve_candidates(
    store: ProjectStore,
    *,
    query: str | None = None,
    external_candidates: Sequence[Mapping[str, Any]] | None = None,
    limit: int = 10,
) -> RetrievalReport:
    state = read_state(store)
    context = _build_context(state)
    recent_memory, explicit_neighborhood = _structural_context(store, state)
    context.recent_memory = recent_memory
    context.explicit_neighborhood = explicit_neighborhood
    query_terms = _query_terms(query, context)
    source_order = [
        RetrievalSourceKind.project_local,
        RetrievalSourceKind.imported_reference,
        RetrievalSourceKind.external_bibliographic,
    ]

    trace: list[RetrievalSourceTrace] = []
    candidates: list[RetrievalCandidate] = []

    local_contracts = list_contracts(store)
    for source_kind in source_order[:2]:
        source_contracts = [contract for contract in local_contracts if _classify_contract(contract) == source_kind]
        source_candidates: list[RetrievalCandidate] = []
        for contract in source_contracts:
            lexical_score, lexical_reasons = _score_text(
                query_terms,
                _candidate_text(contract),
            )
            structural_score, structural_reasons = _structural_score(contract, context)
            score = _clamp((structural_score * 0.7) + (lexical_score * 0.3))
            source_candidates.append(
                _make_candidate(
                    item_id=contract.id,
                    title=contract.name,
                    source_kind=source_kind,
                    source_ref=contract.source_ref,
                    source_priority=source_order.index(source_kind),
                    score=score,
                    contract=contract,
                    structural_score=structural_score,
                    lexical_score=lexical_score,
                    match_reasons=[*structural_reasons, *lexical_reasons],
                    structural_reasons=structural_reasons,
                    lexical_reasons=lexical_reasons,
                )
            )
        trace.append(
            RetrievalSourceTrace(
                source_kind=source_kind,
                evaluated_count=len(source_contracts),
                candidate_ids=[candidate.id for candidate in source_candidates],
            )
        )
        candidates.extend(source_candidates)

    external_candidates = list(external_candidates or [])
    external_source_candidates: list[RetrievalCandidate] = []
    for index, reference in enumerate(external_candidates, start=1):
        reference_id = str(reference.get("id") or reference.get("identifier") or f"external_{index}")
        title = str(reference.get("title") or reference.get("name") or reference_id)
        summary = str(reference.get("summary") or reference.get("abstract") or reference.get("notes") or "")
        lexical_score, lexical_reasons = _score_text(
            query_terms,
            title,
            summary,
            str(reference.get("bibliographic_source") or ""),
            str(reference.get("url") or ""),
        )
        structural_score = 0.0
        structural_reasons = ["external candidate is evaluated after project-local context"]
        external_source_candidates.append(
            _make_candidate(
                item_id=reference_id,
                title=title,
                source_kind=RetrievalSourceKind.external_bibliographic,
                source_ref=str(reference.get("bibliographic_source") or reference.get("url") or "external/bibliography"),
                source_priority=source_order.index(RetrievalSourceKind.external_bibliographic),
                score=_clamp((structural_score * 0.7) + (lexical_score * 0.3)),
                reference=reference,
                structural_score=structural_score,
                lexical_score=lexical_score,
                match_reasons=[*structural_reasons, *lexical_reasons],
                structural_reasons=structural_reasons,
                lexical_reasons=lexical_reasons,
            )
        )
    trace.append(
        RetrievalSourceTrace(
            source_kind=RetrievalSourceKind.external_bibliographic,
            evaluated_count=len(external_candidates),
            candidate_ids=[candidate.id for candidate in external_source_candidates],
        )
    )
    candidates.extend(external_source_candidates)

    ranked = _rank_candidates(candidates)[:limit]
    return RetrievalReport(
        query=query or " ".join(sorted(query_terms)),
        project_context=context,
        source_order=source_order,
        candidates=ranked,
        trace=trace,
    )
