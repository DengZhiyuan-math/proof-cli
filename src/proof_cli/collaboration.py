from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from .domain import utc_now
from .storage import ProjectStore, append_event, collaboration_state_path, read_state


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class CollaborationRole(str, Enum):
    maintainer = "maintainer"
    reviewer = "reviewer"
    contributor = "contributor"
    observer = "observer"


class ContributorStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ReviewGovernanceState(str, Enum):
    draft = "draft"
    proposed_for_review = "proposed_for_review"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    disputed = "disputed"


class CommentThreadStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    disputed = "disputed"


class BranchStatus(str, Enum):
    active = "active"
    merged = "merged"
    abandoned = "abandoned"
    disputed = "disputed"


class SharedAssetPublicationStatus(str, Enum):
    draft = "draft"
    proposed_for_review = "proposed_for_review"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    disputed = "disputed"


class Contributor(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("contrib"))
    display_name: str
    role: CollaborationRole = CollaborationRole.contributor
    team_ids: list[str] = Field(default_factory=list)
    status: ContributorStatus = ContributorStatus.active
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CollaborationPolicy(BaseModel):
    project_id: str
    team_id: str = ""
    name: str = "default"
    who_can_propose: list[str] = Field(default_factory=lambda: ["maintainer", "reviewer", "contributor"])
    who_can_approve: list[str] = Field(default_factory=lambda: ["maintainer", "reviewer"])
    who_can_publish: list[str] = Field(default_factory=lambda: ["maintainer"])
    who_can_resolve_disputes: list[str] = Field(default_factory=lambda: ["maintainer", "reviewer"])
    one_reviewer_objects: list[str] = Field(default_factory=list)
    two_reviewer_objects: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReviewRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("review"))
    object_type: str
    object_id: str
    reviewer_id: str
    decision: ReviewGovernanceState = ReviewGovernanceState.proposed_for_review
    rationale: str = ""
    authorship: list[str] = Field(default_factory=list)
    provenance_notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CommentThread(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("thread"))
    object_type: str
    object_id: str
    status: CommentThreadStatus = CommentThreadStatus.open
    participants: list[str] = Field(default_factory=list)
    created_by: str = "human"
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Comment(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("comment"))
    thread_id: str
    author_id: str
    content: str
    status: CommentThreadStatus = CommentThreadStatus.open
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BranchRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("branch"))
    scope: str
    name: str
    status: BranchStatus = BranchStatus.active
    created_by: str = "human"
    derived_from: str | None = None
    downstream_asset_ids: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SharedAssetPublication(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("publication"))
    asset_id: str
    published_to: str
    status: SharedAssetPublicationStatus = SharedAssetPublicationStatus.draft
    approved_by: list[str] = Field(default_factory=list)
    created_by: str = "human"
    provenance_notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CollaborationState(BaseModel):
    project_id: str
    version: int = 1
    contributors: list[Contributor] = Field(default_factory=list)
    policies: list[CollaborationPolicy] = Field(default_factory=list)
    review_records: list[ReviewRecord] = Field(default_factory=list)
    comment_threads: list[CommentThread] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    branches: list[BranchRecord] = Field(default_factory=list)
    publications: list[SharedAssetPublication] = Field(default_factory=list)


def _collaboration_path(store: ProjectStore) -> Path:
    return collaboration_state_path(store)


def _project_id(store: ProjectStore) -> str:
    return read_state(store).project_id


def _load_json_model(value: Any, model: type[BaseModel]) -> BaseModel:
    if isinstance(value, model):
        return value
    if isinstance(value, dict):
        return model.model_validate(value)
    raise TypeError(f"unsupported collaboration payload: {type(value)!r}")


def _latest_by_id(items: Iterable[BaseModel], key_name: str) -> list[BaseModel]:
    seen: set[str] = set()
    ordered: list[BaseModel] = []
    for item in reversed(list(items)):
        key = str(getattr(item, key_name))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    ordered.reverse()
    return ordered


def load_collaboration(store: ProjectStore) -> CollaborationState:
    path = _collaboration_path(store)
    project_id = _project_id(store)
    if not path.exists():
        return CollaborationState(project_id=project_id)
    data = json.loads(path.read_text())
    state = CollaborationState.model_validate({**data, "project_id": data.get("project_id", project_id)})
    return state


def save_collaboration(store: ProjectStore, state: CollaborationState) -> CollaborationState:
    path = _collaboration_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.project_id = _project_id(store)
    state.version = 1
    path.write_text(state.model_dump_json(indent=2))
    return state


def _update_state(
    store: ProjectStore,
    state: CollaborationState,
    *,
    event_kind: str,
    message: str,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    save_collaboration(store, state)
    append_event(store, event_kind, message, entity_id=entity_id, payload=payload or {})


def upsert_contributor(store: ProjectStore, contributor: Contributor) -> Contributor:
    state = load_collaboration(store)
    contributor.updated_at = utc_now()
    existing = next((item for item in state.contributors if item.id == contributor.id), None)
    if existing is None:
        contributor.created_at = contributor.updated_at
        state.contributors.append(contributor)
        event_kind = "collaboration_contributor_added"
        message = f"added contributor {contributor.id}"
    else:
        existing.display_name = contributor.display_name
        existing.role = contributor.role
        existing.team_ids = list(contributor.team_ids)
        existing.status = contributor.status
        existing.notes = contributor.notes
        existing.updated_at = contributor.updated_at
        contributor = existing
        event_kind = "collaboration_contributor_updated"
        message = f"updated contributor {contributor.id}"
    _update_state(store, state, event_kind=event_kind, message=message, entity_id=contributor.id, payload=contributor.model_dump(mode="json"))
    return contributor


def get_contributor(store: ProjectStore, contributor_id: str) -> Contributor | None:
    state = load_collaboration(store)
    for contributor in reversed(state.contributors):
        if contributor.id == contributor_id:
            return contributor
    return None


def list_contributors(store: ProjectStore, *, team_id: str = "", status: str = "") -> list[Contributor]:
    state = load_collaboration(store)
    contributors = _latest_by_id(state.contributors, "id")
    if team_id:
        contributors = [item for item in contributors if team_id in item.team_ids]
    if status:
        contributors = [item for item in contributors if item.status.value == status]
    return contributors


def set_contributor_role(
    store: ProjectStore,
    contributor_id: str,
    role: CollaborationRole,
    *,
    notes: str = "",
) -> Contributor:
    state = load_collaboration(store)
    contributor = next((item for item in state.contributors if item.id == contributor_id), None)
    if contributor is None:
        raise KeyError(contributor_id)
    contributor.role = role
    contributor.notes = notes or contributor.notes
    contributor.updated_at = utc_now()
    _update_state(
        store,
        state,
        event_kind="collaboration_contributor_role_changed",
        message=f"changed contributor role for {contributor_id}",
        entity_id=contributor_id,
        payload=contributor.model_dump(mode="json"),
    )
    return contributor


def get_policy(store: ProjectStore, *, project_id: str = "") -> CollaborationPolicy | None:
    state = load_collaboration(store)
    if project_id and project_id != state.project_id:
        return None
    return state.policies[-1] if state.policies else None


def set_policy(store: ProjectStore, policy: CollaborationPolicy) -> CollaborationPolicy:
    state = load_collaboration(store)
    policy.updated_at = utc_now()
    if policy.project_id != state.project_id:
        policy.project_id = state.project_id
    state.policies.append(policy)
    _update_state(
        store,
        state,
        event_kind="collaboration_policy_recorded",
        message=f"recorded collaboration policy {policy.name}",
        entity_id=policy.project_id,
        payload=policy.model_dump(mode="json"),
    )
    return policy


def record_review_request(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    *,
    reviewer_id: str,
    rationale: str = "",
    authorship: list[str] | None = None,
    provenance_notes: str = "",
) -> ReviewRecord:
    state = load_collaboration(store)
    record = ReviewRecord(
        object_type=object_type,
        object_id=object_id,
        reviewer_id=reviewer_id,
        decision=ReviewGovernanceState.proposed_for_review,
        rationale=rationale,
        authorship=list(authorship or []),
        provenance_notes=provenance_notes,
    )
    state.review_records.append(record)
    _update_state(
        store,
        state,
        event_kind="collaboration_review_requested",
        message=f"requested review for {object_type} {object_id}",
        entity_id=object_id,
        payload=record.model_dump(mode="json"),
    )
    return record


def record_review_decision(
    store: ProjectStore,
    review_id: str,
    decision: ReviewGovernanceState,
    *,
    reviewer_id: str,
    rationale: str = "",
) -> ReviewRecord:
    state = load_collaboration(store)
    record = next((item for item in reversed(state.review_records) if item.id == review_id), None)
    if record is None:
        raise KeyError(review_id)
    record.decision = decision
    record.reviewer_id = reviewer_id
    record.rationale = rationale or record.rationale
    record.updated_at = utc_now()
    _update_state(
        store,
        state,
        event_kind="collaboration_review_decided",
        message=f"review {review_id} -> {decision.value}",
        entity_id=record.object_id,
        payload=record.model_dump(mode="json"),
    )
    return record


def list_review_records(store: ProjectStore, *, object_type: str = "", object_id: str = "") -> list[ReviewRecord]:
    state = load_collaboration(store)
    records = _latest_by_id(state.review_records, "id")
    if object_type:
        records = [record for record in records if record.object_type == object_type]
    if object_id:
        records = [record for record in records if record.object_id == object_id]
    return records


def get_review_record(store: ProjectStore, review_id: str) -> ReviewRecord | None:
    state = load_collaboration(store)
    for record in reversed(state.review_records):
        if record.id == review_id:
            return record
    return None


def ensure_comment_thread(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    *,
    created_by: str = "human",
    notes: str = "",
) -> CommentThread:
    state = load_collaboration(store)
    existing = next((thread for thread in state.comment_threads if thread.object_type == object_type and thread.object_id == object_id), None)
    if existing is not None:
        return existing
    thread = CommentThread(object_type=object_type, object_id=object_id, created_by=created_by, notes=notes)
    state.comment_threads.append(thread)
    _update_state(
        store,
        state,
        event_kind="collaboration_thread_created",
        message=f"created comment thread for {object_type} {object_id}",
        entity_id=object_id,
        payload=thread.model_dump(mode="json"),
    )
    return thread


def add_comment(
    store: ProjectStore,
    object_type: str,
    object_id: str,
    *,
    author_id: str,
    content: str,
    thread_id: str = "",
    status: CommentThreadStatus = CommentThreadStatus.open,
) -> Comment:
    state = load_collaboration(store)
    thread = None
    if thread_id:
        thread = next((item for item in state.comment_threads if item.id == thread_id), None)
    if thread is None:
        state = load_collaboration(store)
        ensure_comment_thread(store, object_type, object_id, created_by=author_id)
        state = load_collaboration(store)
        thread = next((item for item in state.comment_threads if item.object_type == object_type and item.object_id == object_id), None)
    if thread is None:
        raise KeyError(f"comment thread not found for {object_type} {object_id}")
    if author_id not in thread.participants:
        thread.participants.append(author_id)
    thread.status = status
    thread.updated_at = utc_now()
    comment = Comment(thread_id=thread.id, author_id=author_id, content=content, status=status)
    state.comments.append(comment)
    _update_state(
        store,
        state,
        event_kind="collaboration_comment_added",
        message=f"added comment to {thread.id}",
        entity_id=object_id,
        payload={"thread": thread.model_dump(mode="json"), "comment": comment.model_dump(mode="json")},
    )
    return comment


def list_comment_threads(store: ProjectStore, *, object_type: str = "", object_id: str = "") -> list[CommentThread]:
    state = load_collaboration(store)
    threads = _latest_by_id(state.comment_threads, "id")
    if object_type:
        threads = [thread for thread in threads if thread.object_type == object_type]
    if object_id:
        threads = [thread for thread in threads if thread.object_id == object_id]
    return threads


def list_comments(store: ProjectStore, *, thread_id: str = "", object_type: str = "", object_id: str = "") -> list[Comment]:
    state = load_collaboration(store)
    comments = _latest_by_id(state.comments, "id")
    if thread_id:
        comments = [comment for comment in comments if comment.thread_id == thread_id]
    if object_type or object_id:
        thread_ids = {
            thread.id
            for thread in list_comment_threads(store, object_type=object_type, object_id=object_id)
        }
        comments = [comment for comment in comments if comment.thread_id in thread_ids]
    return comments


def create_branch(
    store: ProjectStore,
    scope: str,
    name: str,
    *,
    created_by: str = "human",
    derived_from: str | None = None,
    notes: str = "",
    downstream_asset_ids: list[str] | None = None,
) -> BranchRecord:
    state = load_collaboration(store)
    branch = BranchRecord(
        scope=scope,
        name=name,
        created_by=created_by,
        derived_from=derived_from,
        notes=notes,
        downstream_asset_ids=list(downstream_asset_ids or []),
    )
    state.branches.append(branch)
    _update_state(
        store,
        state,
        event_kind="collaboration_branch_created",
        message=f"created branch {branch.name}",
        entity_id=scope,
        payload=branch.model_dump(mode="json"),
    )
    return branch


def list_branches(store: ProjectStore, *, scope: str = "", status: str = "") -> list[BranchRecord]:
    state = load_collaboration(store)
    branches = _latest_by_id(state.branches, "id")
    if scope:
        branches = [branch for branch in branches if branch.scope == scope]
    if status:
        branches = [branch for branch in branches if branch.status.value == status]
    return branches


def get_branch(store: ProjectStore, branch_id: str) -> BranchRecord | None:
    state = load_collaboration(store)
    for branch in reversed(state.branches):
        if branch.id == branch_id:
            return branch
    return None


class BranchComparison(BaseModel):
    left_branch_id: str
    right_branch_id: str
    same_scope: bool
    same_status: bool
    shared_downstream_asset_ids: list[str] = Field(default_factory=list)
    left_only_asset_ids: list[str] = Field(default_factory=list)
    right_only_asset_ids: list[str] = Field(default_factory=list)
    summary: str = ""


def compare_branches(store: ProjectStore, left_branch_id: str, right_branch_id: str) -> BranchComparison:
    left = get_branch(store, left_branch_id)
    right = get_branch(store, right_branch_id)
    if left is None:
        raise KeyError(left_branch_id)
    if right is None:
        raise KeyError(right_branch_id)
    left_assets = set(left.downstream_asset_ids)
    right_assets = set(right.downstream_asset_ids)
    shared = sorted(left_assets & right_assets)
    left_only = sorted(left_assets - right_assets)
    right_only = sorted(right_assets - left_assets)
    summary = (
        f"{left.name} vs {right.name}: "
        f"shared={len(shared)} left_only={len(left_only)} right_only={len(right_only)}"
    )
    return BranchComparison(
        left_branch_id=left_branch_id,
        right_branch_id=right_branch_id,
        same_scope=left.scope == right.scope,
        same_status=left.status == right.status,
        shared_downstream_asset_ids=shared,
        left_only_asset_ids=left_only,
        right_only_asset_ids=right_only,
        summary=summary,
    )


def merge_branch(
    store: ProjectStore,
    branch_id: str,
    *,
    into_branch_id: str | None = None,
    reviewer_id: str = "human",
    rationale: str = "",
) -> BranchRecord:
    state = load_collaboration(store)
    source = next((item for item in state.branches if item.id == branch_id), None)
    if source is None:
        raise KeyError(branch_id)
    source.status = BranchStatus.merged
    source.updated_at = utc_now()
    if into_branch_id:
        target = next((item for item in state.branches if item.id == into_branch_id), None)
        if target is None:
            raise KeyError(into_branch_id)
        for asset_id in source.downstream_asset_ids:
            if asset_id not in target.downstream_asset_ids:
                target.downstream_asset_ids.append(asset_id)
        target.updated_at = utc_now()
    _update_state(
        store,
        state,
        event_kind="collaboration_branch_merged",
        message=f"merged branch {branch_id}",
        entity_id=branch_id,
        payload={"branch": source.model_dump(mode="json"), "into_branch_id": into_branch_id, "reviewer_id": reviewer_id, "rationale": rationale},
    )
    return source


def publish_shared_asset(
    store: ProjectStore,
    asset_id: str,
    *,
    published_to: str,
    created_by: str = "human",
    approved_by: list[str] | None = None,
    status: SharedAssetPublicationStatus = SharedAssetPublicationStatus.approved,
    provenance_notes: str = "",
) -> SharedAssetPublication:
    state = load_collaboration(store)
    publication = SharedAssetPublication(
        asset_id=asset_id,
        published_to=published_to,
        created_by=created_by,
        approved_by=list(approved_by or []),
        status=status,
        provenance_notes=provenance_notes,
    )
    state.publications.append(publication)
    _update_state(
        store,
        state,
        event_kind="collaboration_publication_recorded",
        message=f"recorded publication for {asset_id}",
        entity_id=asset_id,
        payload=publication.model_dump(mode="json"),
    )
    return publication


def list_publications(store: ProjectStore, *, asset_id: str = "", published_to: str = "") -> list[SharedAssetPublication]:
    state = load_collaboration(store)
    publications = _latest_by_id(state.publications, "id")
    if asset_id:
        publications = [publication for publication in publications if publication.asset_id == asset_id]
    if published_to:
        publications = [publication for publication in publications if publication.published_to == published_to]
    return publications


def set_collaboration_policy(
    store: ProjectStore,
    *,
    team_id: str = "",
    name: str = "default",
    who_can_propose: list[str] | None = None,
    who_can_approve: list[str] | None = None,
    who_can_publish: list[str] | None = None,
    who_can_resolve_disputes: list[str] | None = None,
    one_reviewer_objects: list[str] | None = None,
    two_reviewer_objects: list[str] | None = None,
    notes: str = "",
) -> CollaborationPolicy:
    state = load_collaboration(store)
    policy = CollaborationPolicy(
        project_id=state.project_id,
        team_id=team_id,
        name=name,
        who_can_propose=list(who_can_propose or ["maintainer", "reviewer", "contributor"]),
        who_can_approve=list(who_can_approve or ["maintainer", "reviewer"]),
        who_can_publish=list(who_can_publish or ["maintainer"]),
        who_can_resolve_disputes=list(who_can_resolve_disputes or ["maintainer", "reviewer"]),
        one_reviewer_objects=list(one_reviewer_objects or []),
        two_reviewer_objects=list(two_reviewer_objects or []),
        notes=notes,
    )
    state.policies.append(policy)
    _update_state(
        store,
        state,
        event_kind="collaboration_policy_updated",
        message=f"set collaboration policy {policy.name}",
        entity_id=policy.project_id,
        payload=policy.model_dump(mode="json"),
    )
    return policy


def summarize_contributor(contributor: Contributor) -> str:
    teams = f" teams={','.join(contributor.team_ids)}" if contributor.team_ids else ""
    notes = f" - {contributor.notes}" if contributor.notes else ""
    return f"{contributor.id}: {contributor.display_name} [{contributor.role.value}/{contributor.status.value}]{teams}{notes}"


def summarize_review_record(record: ReviewRecord) -> str:
    return f"{record.id}: {record.object_type}/{record.object_id} [{record.decision.value}] reviewer={record.reviewer_id}"


def summarize_comment_thread(thread: CommentThread) -> str:
    participants = ",".join(thread.participants) or "none"
    return f"{thread.id}: {thread.object_type}/{thread.object_id} [{thread.status.value}] participants={participants}"


def summarize_comment(comment: Comment) -> str:
    note = comment.content.replace("\n", " ").strip()
    return f"{comment.id}: thread={comment.thread_id} author={comment.author_id} {note}"


def summarize_branch(branch: BranchRecord) -> str:
    derived = f" derived_from={branch.derived_from}" if branch.derived_from else ""
    downstream = f" downstream={','.join(branch.downstream_asset_ids)}" if branch.downstream_asset_ids else ""
    notes = f" - {branch.notes}" if branch.notes else ""
    return f"{branch.id}: {branch.name} [{branch.scope}/{branch.status.value}] created_by={branch.created_by}{derived}{downstream}{notes}"


def summarize_publication(publication: SharedAssetPublication) -> str:
    approvers = ",".join(publication.approved_by) or "none"
    notes = f" - {publication.provenance_notes}" if publication.provenance_notes else ""
    return f"{publication.id}: {publication.asset_id} -> {publication.published_to} [{publication.status.value}] approved_by={approvers}{notes}"


def summarize_policy(policy: CollaborationPolicy) -> str:
    return (
        f"{policy.name}: project={policy.project_id} team={policy.team_id or 'none'} "
        f"propose={','.join(policy.who_can_propose)} approve={','.join(policy.who_can_approve)} "
        f"publish={','.join(policy.who_can_publish)}"
    )


def summarize_state(store: ProjectStore) -> str:
    state = load_collaboration(store)
    lines = [f"Collaboration: project={state.project_id}"]
    lines.append("Contributors:")
    if state.contributors:
        lines.extend(f"- {summarize_contributor(contributor)}" for contributor in state.contributors)
    else:
        lines.append("- none")
    lines.append("Reviews:")
    if state.review_records:
        lines.extend(f"- {summarize_review_record(record)}" for record in state.review_records)
    else:
        lines.append("- none")
    lines.append("Comments:")
    if state.comment_threads:
        for thread in state.comment_threads:
            lines.append(f"- {summarize_comment_thread(thread)}")
    else:
        lines.append("- none")
    lines.append("Branches:")
    if state.branches:
        lines.extend(f"- {summarize_branch(branch)}" for branch in state.branches)
    else:
        lines.append("- none")
    lines.append("Publications:")
    if state.publications:
        lines.extend(f"- {summarize_publication(publication)}" for publication in state.publications)
    else:
        lines.append("- none")
    lines.append("Policies:")
    if state.policies:
        lines.extend(f"- {summarize_policy(policy)}" for policy in state.policies)
    else:
        lines.append("- none")
    return "\n".join(lines)


__all__ = [
    "BranchComparison",
    "BranchRecord",
    "BranchStatus",
    "CollaborationPolicy",
    "CollaborationRole",
    "CollaborationState",
    "Comment",
    "CommentThread",
    "CommentThreadStatus",
    "Contributor",
    "ContributorStatus",
    "ReviewGovernanceState",
    "ReviewRecord",
    "SharedAssetPublication",
    "SharedAssetPublicationStatus",
    "compare_branches",
    "create_branch",
    "get_branch",
    "get_contributor",
    "get_policy",
    "get_review_record",
    "list_branches",
    "list_comment_threads",
    "list_comments",
    "list_contributors",
    "list_publications",
    "list_review_records",
    "load_collaboration",
    "merge_branch",
    "publish_shared_asset",
    "record_review_decision",
    "record_review_request",
    "save_collaboration",
    "set_collaboration_policy",
    "set_contributor_role",
    "summarize_branch",
    "summarize_comment",
    "summarize_comment_thread",
    "summarize_contributor",
    "summarize_policy",
    "summarize_publication",
    "summarize_review_record",
    "summarize_state",
    "upsert_contributor",
]
