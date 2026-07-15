from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .domain import BlockerRecord, ProofObligation, ProjectState, TheoremContract, utc_now
from .memory import load_memory
from .retrieval import RetrievalCandidate, RetrievalReport, retrieve_candidates
from .storage import ProjectStore, list_blockers, list_contracts, list_obligations, read_state


class DiagnosticCandidateSummary(BaseModel):
    id: str
    title: str
    source_kind: str
    source_ref: str
    score: float
    match_reasons: list[str] = Field(default_factory=list)


class ProjectDiagnosticReport(BaseModel):
    project_id: str
    query: str
    current_theorem: str | None = None
    bottleneck_kind: str = "unknown"
    bottleneck_summary: str = ""
    central_obligations: list[str] = Field(default_factory=list)
    active_blockers: list[str] = Field(default_factory=list)
    recent_memory: list[str] = Field(default_factory=list)
    explicit_neighborhood: list[str] = Field(default_factory=list)
    failed_routes: list[str] = Field(default_factory=list)
    promising_next_steps: list[str] = Field(default_factory=list)
    top_candidates: list[DiagnosticCandidateSummary] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


def _contract_index(contracts: list[TheoremContract]) -> dict[str, TheoremContract]:
    return {contract.id: contract for contract in contracts}


def _memory_context(store: ProjectStore, state: ProjectState) -> list[str]:
    memory = load_memory(store)
    focused: list[str] = []
    for artifact in reversed(memory.working[-3:] + memory.semantic[-3:] + memory.episodic[-2:] + memory.procedural[-2:]):
        if state.current_theorem and artifact.scope.theorem_id not in {None, state.current_theorem}:
            continue
        focused.append(artifact.content)
    focused.reverse()
    return focused[-5:]


def _explicit_neighborhood(
    state: ProjectState,
    contracts: list[TheoremContract],
    obligations: list[ProofObligation],
    blockers: list[BlockerRecord],
) -> list[str]:
    contract_by_id = _contract_index(contracts)
    neighborhood: list[str] = []

    if state.current_theorem:
        neighborhood.append(f"theorem:{state.current_theorem}")
        current_contract = contract_by_id.get(state.current_theorem)
        if current_contract is not None:
            for dependency in current_contract.dependencies:
                neighborhood.append(f"depends_on:{dependency}")
            for contract in contracts:
                if state.current_theorem in contract.dependencies:
                    neighborhood.append(f"depended_on_by:{contract.id}")

    for obligation in obligations:
        if state.current_theorem and obligation.required_for not in {None, state.current_theorem}:
            continue
        neighborhood.append(f"obligation:{obligation.id}")
        if obligation.source_step_id:
            neighborhood.append(f"obligation_step:{obligation.source_step_id}")

    for blocker in blockers:
        if state.current_theorem and blocker.scope not in {state.current_theorem, "global"} and state.current_theorem not in blocker.related_contracts:
            continue
        neighborhood.append(f"blocker:{blocker.id}")
        neighborhood.extend(f"blocker_contract:{contract_id}" for contract_id in blocker.related_contracts)
        neighborhood.extend(f"blocker_step:{step_id}" for step_id in blocker.related_steps)

    return list(dict.fromkeys(neighborhood))[-12:]


def _bottleneck_summary(
    state: ProjectState,
    obligations: list[ProofObligation],
    blockers: list[BlockerRecord],
    failed_routes: list[str],
) -> tuple[str, str]:
    if blockers:
        blocker = blockers[0]
        return "blocker", f"{blocker.id}: {blocker.description}"
    if obligations:
        obligation = obligations[0]
        summary = obligation.blocking_reason or obligation.goal_statement
        return "obligation", f"{obligation.id}: {summary}"
    if failed_routes:
        return "route", failed_routes[-1]
    if state.unresolved_trust_sensitive_calls:
        target = state.unresolved_trust_sensitive_calls[-1]
        return "trust", f"unresolved trust-sensitive call: {target}"
    if state.current_theorem:
        return "theorem", f"{state.current_theorem} is active without an explicit blocker"
    return "idle", "No active theorem or open proof work detected"


def _next_steps(
    state: ProjectState,
    bottleneck_kind: str,
    bottleneck_summary: str,
    obligations: list[ProofObligation],
    blockers: list[BlockerRecord],
    retrieval: RetrievalReport,
    memory: list[str],
) -> list[str]:
    steps: list[str] = []
    if bottleneck_kind == "blocker" and blockers:
        blocker = blockers[0]
        steps.append(f"inspect blocker {blocker.id}")
        if blocker.related_contracts:
            steps.append(f"recheck related contract(s): {', '.join(blocker.related_contracts)}")
    elif bottleneck_kind == "obligation" and obligations:
        obligation = obligations[0]
        steps.append(f"resolve obligation {obligation.id}")
        if obligation.source_step_id:
            steps.append(f"revisit source step {obligation.source_step_id}")
    elif bottleneck_kind == "route":
        steps.append("avoid rerunning the failed route verbatim")
        steps.append("prefer nearby project-local candidates with explicit support")
    elif bottleneck_kind == "trust":
        steps.append("review the unresolved trust-sensitive call before reuse")
    else:
        steps.append("continue from the active theorem context")

    for candidate in retrieval.candidates[:3]:
        steps.append(f"consider {candidate.id} from {candidate.source_kind.value}")

    if memory:
        steps.append(f"revisit recent memory: {memory[-1]}")

    if state.current_theorem and state.current_theorem not in bottleneck_summary:
        steps.append(f"anchor work on theorem {state.current_theorem}")

    return list(dict.fromkeys(steps))[:5]


def _candidate_summaries(candidates: list[RetrievalCandidate]) -> list[DiagnosticCandidateSummary]:
    return [
        DiagnosticCandidateSummary(
            id=candidate.id,
            title=candidate.title,
            source_kind=candidate.source_kind.value,
            source_ref=candidate.source_ref,
            score=candidate.score,
            match_reasons=list(candidate.match_reasons),
        )
        for candidate in candidates[:3]
    ]


def build_project_diagnostic_report(
    store: ProjectStore,
    *,
    query: str | None = None,
    limit: int = 5,
) -> ProjectDiagnosticReport:
    state = read_state(store)
    contracts = list_contracts(store)
    obligations = list_obligations(store)
    blockers = list_blockers(store)
    memory = _memory_context(store, state)
    retrieval = retrieve_candidates(store, query=query, limit=limit)
    bottleneck_kind, bottleneck_summary = _bottleneck_summary(state, obligations, blockers, state.failed_routes)
    explicit_neighborhood = _explicit_neighborhood(state, contracts, obligations, blockers)
    return ProjectDiagnosticReport(
        project_id=state.project_id,
        query=query or retrieval.query,
        current_theorem=state.current_theorem,
        bottleneck_kind=bottleneck_kind,
        bottleneck_summary=bottleneck_summary,
        central_obligations=[obligation.id for obligation in obligations[:3]],
        active_blockers=[blocker.id for blocker in blockers[:3]],
        recent_memory=memory,
        explicit_neighborhood=explicit_neighborhood,
        failed_routes=list(state.failed_routes[-5:]),
        promising_next_steps=_next_steps(
            state,
            bottleneck_kind,
            bottleneck_summary,
            obligations,
            blockers,
            retrieval,
            memory,
        ),
        top_candidates=_candidate_summaries(retrieval.candidates),
    )
