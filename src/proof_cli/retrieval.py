from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field

from .domain import ProjectState, TheoremContract
from .storage import ProjectStore, list_contracts, read_state


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


class RetrievalCandidate(BaseModel):
    id: str
    title: str
    source_kind: RetrievalSourceKind
    source_ref: str
    source_priority: int
    score: float
    rank: int = 0
    contract_id: str | None = None
    contract_status: str | None = None
    trust_level: str | None = None
    match_reasons: list[str] = Field(default_factory=list)
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


def _tokens(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(token.lower() for token in TOKEN_RE.findall(part or ""))
    return tokens


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
    )


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
    contract: TheoremContract | None = None,
    reference: Mapping[str, Any] | None = None,
    match_reasons: list[str] | None = None,
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
        contract_id=contract.id if contract is not None else None,
        contract_status=contract.status.value if contract is not None else None,
        trust_level=contract.trust_level.value if contract is not None else None,
        match_reasons=match_reasons or [],
        payload=payload,
    )


def _rank_candidates(candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            candidate.source_priority,
            -candidate.score,
            candidate.title.lower(),
            candidate.id,
        ),
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
    return ranked


def retrieve_candidates(
    store: ProjectStore,
    *,
    query: str | None = None,
    external_candidates: Sequence[Mapping[str, Any]] | None = None,
    limit: int = 10,
) -> RetrievalReport:
    state = read_state(store)
    context = _build_context(state)
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
            score, reasons = _score_text(
                query_terms,
                contract.name,
                contract.statement,
                " ".join(contract.assumptions),
                " ".join(contract.exports),
                " ".join(contract.dependencies),
                contract.notes,
                contract.source_ref,
            )
            source_candidates.append(
                _make_candidate(
                    item_id=contract.id,
                    title=contract.name,
                    source_kind=source_kind,
                    source_ref=contract.source_ref,
                    source_priority=source_order.index(source_kind),
                    score=score,
                    contract=contract,
                    match_reasons=reasons,
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
        score, reasons = _score_text(
            query_terms,
            title,
            summary,
            str(reference.get("bibliographic_source") or ""),
            str(reference.get("url") or ""),
        )
        external_source_candidates.append(
            _make_candidate(
                item_id=reference_id,
                title=title,
                source_kind=RetrievalSourceKind.external_bibliographic,
                source_ref=str(reference.get("bibliographic_source") or reference.get("url") or "external/bibliography"),
                source_priority=source_order.index(RetrievalSourceKind.external_bibliographic),
                score=score,
                reference=reference,
                match_reasons=reasons,
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
