from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .domain import BlockerRecord, ProofObligation, ProofObligationStatus, ProjectSnapshot, ProjectState, utc_now
from .publication import load_publication_workspace
from .storage import (
    ProjectStore,
    append_event,
    read_latest_snapshot,
    read_state,
    store_blocker,
    store_obligation,
    store_snapshot,
    store_state,
)


LITERATURE_ROUTE_EVENT_PREFIX = "literature_route:"
VERIFICATION_RESULT_EVENT_PREFIX = "verification_result:"


class LiteratureRouteRecord(BaseModel):
    target_kind: Literal["goal", "obligation", "blocker"]
    target_id: str
    reference_id: str
    reference_title: str = ""
    outcome: Literal["candidate", "supporting", "failed", "rejected"] = "candidate"
    source_kind: str = "retrieval"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    def summary(self) -> str:
        title = self.reference_title or self.reference_id
        note = f" - {self.notes}" if self.notes else ""
        return f"{self.target_kind}:{self.target_id} <- {title} [{self.outcome}]{note}"


def _encode_route_entry(route: LiteratureRouteRecord) -> str:
    return f"{LITERATURE_ROUTE_EVENT_PREFIX}{route.model_dump_json()}"


def _append_route_to_state(state: ProjectState, route: LiteratureRouteRecord) -> None:
    state.session_history.append(_encode_route_entry(route))
    if route.outcome in {"failed", "rejected"}:
        failed_summary = route.summary()
        if failed_summary not in state.failed_routes:
            state.failed_routes.append(failed_summary)


def _collect_routes(state: ProjectState) -> list[LiteratureRouteRecord]:
    routes: list[LiteratureRouteRecord] = []
    for entry in state.session_history:
        if not entry.startswith(LITERATURE_ROUTE_EVENT_PREFIX):
            continue
        payload = entry[len(LITERATURE_ROUTE_EVENT_PREFIX) :]
        routes.append(LiteratureRouteRecord.model_validate_json(payload))
    return routes


def record_verification_result_entry(state: ProjectState, record: object) -> None:
    state.session_history.append(f"{VERIFICATION_RESULT_EVENT_PREFIX}{record.model_dump_json()}")


def list_verification_result_records(state: ProjectState) -> list[object]:
    from .verification_results import VerificationResultRecord

    records: list[VerificationResultRecord] = []
    for entry in state.session_history:
        if not entry.startswith(VERIFICATION_RESULT_EVENT_PREFIX):
            continue
        payload = entry[len(VERIFICATION_RESULT_EVENT_PREFIX) :]
        records.append(VerificationResultRecord.model_validate_json(payload))
    return records


def _reference_token(reference_id: str, kind: str) -> str:
    return f"{kind}_ref:{reference_id}"


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def load_state(store: ProjectStore) -> ProjectState:
    return read_state(store)


def save_state(store: ProjectStore, state: ProjectState, *, event_kind: str = "state_changed", message: str = "updated state") -> ProjectState:
    store_state(store, state)
    append_event(store, event_kind, message, entity_id=state.project_id, payload=state.model_dump(mode="json"))
    return state


def set_current_theorem(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    state.current_theorem = theorem_id
    if theorem_id not in state.open_goals:
        state.open_goals.append(theorem_id)
    state.session_history.append(f"current_theorem:{theorem_id}")
    return save_state(store, state, message=f"set current theorem to {theorem_id}")


def set_current_context(store: ProjectStore, assumptions: list[str]) -> ProjectState:
    state = load_state(store)
    state.current_context = assumptions
    state.session_history.append("updated proof context")
    return save_state(store, state, message="updated proof context")


def add_goal(store: ProjectStore, goal: str) -> ProjectState:
    state = load_state(store)
    if goal not in state.open_goals:
        state.open_goals.append(goal)
    state.session_history.append(f"goal:{goal}")
    return save_state(store, state, message=f"added goal {goal}")


def record_literature_route(
    store: ProjectStore,
    *,
    target_kind: Literal["goal", "obligation", "blocker"],
    target_id: str,
    reference_id: str,
    reference_title: str = "",
    outcome: Literal["candidate", "supporting", "failed", "rejected"] = "candidate",
    source_kind: str = "retrieval",
    notes: str = "",
) -> LiteratureRouteRecord:
    state = load_state(store)
    route = LiteratureRouteRecord(
        target_kind=target_kind,
        target_id=target_id,
        reference_id=reference_id,
        reference_title=reference_title,
        outcome=outcome,
        source_kind=source_kind,
        notes=notes,
    )
    _append_route_to_state(state, route)
    save_state(store, state, message=f"recorded literature route for {target_kind} {target_id}")
    append_event(
        store,
        "literature_route_recorded",
        f"recorded literature route for {target_kind} {target_id}",
        entity_id=target_id,
        payload=route.model_dump(mode="json"),
    )
    return route


def record_candidate_reference(
    store: ProjectStore,
    *,
    target_kind: Literal["goal", "obligation", "blocker"],
    target_id: str,
    reference_id: str,
    reference_title: str = "",
    source_kind: str = "retrieval",
    notes: str = "",
) -> LiteratureRouteRecord:
    return record_literature_route(
        store,
        target_kind=target_kind,
        target_id=target_id,
        reference_id=reference_id,
        reference_title=reference_title,
        outcome="candidate",
        source_kind=source_kind,
        notes=notes,
    )


def record_supporting_reference(
    store: ProjectStore,
    *,
    target_kind: Literal["goal", "obligation", "blocker"],
    target_id: str,
    reference_id: str,
    reference_title: str = "",
    source_kind: str = "retrieval",
    notes: str = "",
) -> LiteratureRouteRecord:
    return record_literature_route(
        store,
        target_kind=target_kind,
        target_id=target_id,
        reference_id=reference_id,
        reference_title=reference_title,
        outcome="supporting",
        source_kind=source_kind,
        notes=notes,
    )


def list_literature_routes(
    store: ProjectStore,
    *,
    target_id: str | None = None,
    target_kind: str | None = None,
    outcome: str | None = None,
) -> list[LiteratureRouteRecord]:
    state = load_state(store)
    routes = _collect_routes(state)
    filtered: list[LiteratureRouteRecord] = []
    for route in routes:
        if target_id is not None and route.target_id != target_id:
            continue
        if target_kind is not None and route.target_kind != target_kind:
            continue
        if outcome is not None and route.outcome != outcome:
            continue
        filtered.append(route)
    return filtered


def add_obligation(
    store: ProjectStore,
    obligation: ProofObligation,
    *,
    candidate_reference_ids: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    failed_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> ProofObligation:
    route_tokens = [
        *(_reference_token(reference_id, "candidate") for reference_id in candidate_reference_ids or []),
        *(_reference_token(reference_id, "supporting") for reference_id in supporting_reference_ids or []),
        *(_reference_token(reference_id, "failed") for reference_id in failed_reference_ids or []),
    ]
    if route_notes:
        route_tokens.append(f"route_note:{route_notes}")
    _extend_unique(obligation.dependencies, route_tokens)
    store_obligation(store, obligation)
    state = load_state(store)
    if obligation.id not in state.open_obligations and obligation.status == ProofObligationStatus.open:
        state.open_obligations.append(obligation.id)
        state.session_history.append(f"obligation:{obligation.id}")
        save_state(store, state, message=f"added obligation {obligation.id}")
    else:
        append_event(store, "obligation_added", f"added obligation {obligation.id}", entity_id=obligation.id, payload=obligation.model_dump(mode="json"))
    return obligation


def add_blocker(
    store: ProjectStore,
    blocker: BlockerRecord,
    *,
    candidate_reference_ids: list[str] | None = None,
    supporting_reference_ids: list[str] | None = None,
    failed_reference_ids: list[str] | None = None,
    route_notes: str = "",
) -> BlockerRecord:
    route_tokens = [
        *(_reference_token(reference_id, "candidate") for reference_id in candidate_reference_ids or []),
        *(_reference_token(reference_id, "supporting") for reference_id in supporting_reference_ids or []),
        *(_reference_token(reference_id, "failed") for reference_id in failed_reference_ids or []),
    ]
    if route_notes:
        route_tokens.append(f"route_note:{route_notes}")
    _extend_unique(blocker.related_contracts, route_tokens)
    store_blocker(store, blocker)
    state = load_state(store)
    if blocker.id not in state.blockers and blocker.status == "active":
        state.blockers.append(blocker.id)
    state.session_history.append(f"blocker:{blocker.id}")
    save_state(store, state, message=f"added blocker {blocker.id}")
    return blocker


def record_failed_route(
    store: ProjectStore,
    route: str,
    *,
    target_kind: Literal["goal", "obligation", "blocker"] = "goal",
    target_id: str = "",
    reference_id: str = "",
    reference_title: str = "",
    source_kind: str = "retrieval",
    notes: str = "",
) -> ProjectState:
    state = load_state(store)
    state.failed_routes.append(route)
    state.session_history.append(f"failed_route:{route}")
    if target_id or reference_id or notes:
        _append_route_to_state(
            state,
            LiteratureRouteRecord(
                target_kind=target_kind,
                target_id=target_id or route,
                reference_id=reference_id or route,
                reference_title=reference_title,
                outcome="failed",
                source_kind=source_kind,
                notes=notes or route,
            ),
        )
    return save_state(store, state, message=f"recorded failed route {route}")


def record_theorem_usage(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    if theorem_id not in state.recent_theorem_usage:
        state.recent_theorem_usage.append(theorem_id)
    state.session_history.append(f"used_theorem:{theorem_id}")
    return save_state(store, state, message=f"used theorem {theorem_id}")


def note_unresolved_trust_call(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    if theorem_id not in state.unresolved_trust_sensitive_calls:
        state.unresolved_trust_sensitive_calls.append(theorem_id)
    return save_state(store, state, message=f"noted unresolved trust-sensitive call {theorem_id}")


def clear_unresolved_trust_call(store: ProjectStore, theorem_id: str) -> ProjectState:
    state = load_state(store)
    if theorem_id in state.unresolved_trust_sensitive_calls:
        state.unresolved_trust_sensitive_calls.remove(theorem_id)
    return save_state(store, state, message=f"cleared unresolved trust-sensitive call {theorem_id}")


def build_snapshot(store: ProjectStore, handoff_note: str = "") -> ProjectSnapshot:
    from .analysis import build_project_diagnostic_report

    state = load_state(store)
    literature_routes = list_literature_routes(store)
    verification_results = list_verification_result_records(state)
    publication_workspace = load_publication_workspace(store)
    publication_view = publication_workspace.views[-1] if publication_workspace.views else None
    diagnostic_report = build_project_diagnostic_report(store, query=state.current_theorem or "", limit=3)
    promising_routes = [
        route.summary()
        for route in literature_routes
        if route.outcome in {"candidate", "supporting"}
    ]
    snapshot = ProjectSnapshot(
        project_id=state.project_id,
        active_theorem=state.current_theorem,
        current_goals=list(state.open_goals),
        validated_results=[
            *state.recent_theorem_usage,
            *[result.summary() for result in verification_results],
        ],
        open_obligations=list(state.open_obligations),
        active_blockers=list(state.blockers),
        recently_used_results=list(state.recent_theorem_usage),
        unresolved_trust_sensitive_calls=list(state.unresolved_trust_sensitive_calls),
        next_promising_routes=(promising_routes + list(state.failed_routes))[-3:],
        publication_view_id=publication_view.id if publication_view is not None else None,
        publication_audience=publication_view.visibility.value if publication_view is not None else None,
        publication_claim_ids=[state_record.object_id for state_record in publication_workspace.states],
        publication_release_ids=[release.bundle_id for release in publication_workspace.release_records],
        publication_bundle_snapshot_ids=[snapshot.id for snapshot in publication_workspace.bundle_snapshots],
        latest_diagnostic_report=diagnostic_report.model_dump(mode="json"),
        handoff_note=handoff_note or "resume from the latest proof state",
    )
    store_snapshot(store, snapshot)
    append_event(store, "snapshot_created", "created snapshot", entity_id=state.project_id, payload=snapshot.model_dump(mode="json"))
    state.latest_snapshot_id = snapshot.project_id
    save_state(store, state, message="updated latest snapshot reference")
    return snapshot


def project_history(store: ProjectStore) -> list[str]:
    return [event.message for event in list_events(store)]


def summarize_state(store: ProjectStore) -> dict[str, object]:
    state = load_state(store)
    snapshot = read_latest_snapshot(store)
    literature_routes = list_literature_routes(store)
    verification_results = list_verification_result_records(state)
    return {
        "project_id": state.project_id,
        "current_theorem": state.current_theorem,
        "open_goals": state.open_goals,
        "open_obligations": state.open_obligations,
        "blockers": state.blockers,
        "failed_routes": state.failed_routes,
        "recent_theorem_usage": state.recent_theorem_usage,
        "unresolved_trust_sensitive_calls": state.unresolved_trust_sensitive_calls,
        "literature_routes": [route.model_dump(mode="json") for route in literature_routes],
        "verification_results": [result.model_dump(mode="json") for result in verification_results],
        "verification_result_summaries": [result.summary() for result in verification_results],
        "validated_results": [
            *state.recent_theorem_usage,
            *[result.summary() for result in verification_results],
        ],
        "latest_snapshot": snapshot,
    }
