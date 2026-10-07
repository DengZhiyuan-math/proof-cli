from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Iterator

from .authority import (
    AuthorityWarning,
    RowVerdict,
    build_decision_payload,
    candidate_proof_sha256,
    challenge_resolution,
    decision_rows,
    list_authority_warnings,
    list_decisions,
    record_decision,
    snapshot_matches,
    verify_decision_row,
)
from .collaboration import (
    ReviewGovernanceState,
    ReviewRecord,
    ReviewRecordKind,
)
from .domain import (
    AGENT_ROLES,
    CandidateProofRecord,
    Challenge,
    ChallengeStatus,
    ClaimRecord,
    DependencyPin,
    EventRecord,
    EvidenceCheck,
    EvidenceOutcome,
    Medium,
    ProofMapNode,
    ProofMapNodeKind,
    TrustLevel,
    is_computation,
    utc_now,
)
from .reviews import TRUST_RULES_FILE, DecisionKind, DecisionPayload, PinnedDependency, git_identity
from .storage import (
    get_definition,
    append_event,
    delete_dependency_pin,
    get_active_claim,
    get_candidate_proof as _get_candidate_proof,
    get_challenge as _get_challenge,
    get_current_candidate_proof,
    get_dependency_pin as _get_dependency_pin,
    get_evidence_check as _get_evidence_check,
    get_proof_map_node,
    get_reference,
    insert_candidate_proof,
    insert_challenge,
    insert_claim,
    insert_evidence_check,
    insert_proof_map_node,
    latest_event,
    list_candidate_proofs_for_node,
    list_challenges as _list_challenges,
    list_dependency_pins_for_node,
    list_events,
    list_evidence_checks_for_candidate_proof,
    list_fog_items,
    list_proof_map_nodes,
    mark_challenge_dismissed,
    mark_claim_released,
    memoized_read,
    next_candidate_proof_version,
    on_rollback,
    ProjectStore,
    read_scope,
    read_scoped,
    scoped_memo,
    set_candidate_proof_interface_fingerprint,
    set_candidate_proof_review_record_id,
    update_proof_map_node,
    upsert_dependency_pin,
)
from . import key_ideas
from .errors import notice
from .trust_rules import (
    SiblingCitation,
    TrustConditionKind,
    TrustRule,
    TrustRuleDecision,
    TrustRuleError,
    check_rule_decision,
    get_trust_rule,
    list_trust_rules,
    parse_conditions,
    record_rule_decision,
    rule_matches,
)
from .vault import (
    SNAPSHOT_MANIFEST,
    archived_pdf_path,
    preamble_path,
    build_is_current,
    build_pdf_path,
    NodeFolderLinks,
    frozen_output_bytes,
    large_output_threshold,
    node_folder,
    read_working_snapshot,
    remove_snapshot,
    run_script_path,
    snapshot_dir,
    snapshots_on_disk,
    vault_dir,
    working_entry_path,
    working_proof_path,
    write_snapshot_folder,
    write_working_computation,
    write_working_proof,
)


class ProofMapError(Exception):
    """A domain-rule violation in the proof map service layer.

    Carries a stable `code` so CLI callers can surface it as a JSON envelope
    `error.code` per the spec's agent-facing protocol.
    """

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class _Decision:
    """A Human Review decision about to be recorded: what it's made on, and who makes it (ADR-0010)."""

    payload: DecisionPayload
    reviewer_id: str


def _decide(
    store: ProjectStore,
    *,
    kind: DecisionKind,
    target_id: str,
    decision: str,
    reviewer: str | None,
    rationale: str,
    dependency_id: str | None = None,
    viewed_binding: str | None = None,
) -> _Decision:
    """Bind the decision to what it's made on as of now; called on the operation's write transaction.

    `viewed_binding`: the `binding_digest` of what the page showed. If the
    decision would now bind anything else — another snapshot, interface,
    dependency pins, Challenges, dependents — it is refused (STALE_VIEW),
    still inside the transaction, so nothing can change in between. A
    decision on a snapshot that is missing or can't be read is refused
    (SNAPSHOT_UNREADABLE): it would bind nothing (#92).
    """
    payload = build_decision_payload(
        store, kind, target_id, decision, rationale=rationale, **decision_binding(store, kind, target_id, dependency_id=dependency_id)
    )
    if payload.candidate_proof_id is not None and payload.candidate_proof_sha256 is None:
        raise ProofMapError(
            "SNAPSHOT_UNREADABLE",
            f"the Review snapshot {target_id}'s decision would be made on is missing or can't be read; "
            "nothing can be decided on it until it is restored, or you request review again "
            "(an unchanged working proof is then re-snapshotted as a new version, which needs its own review)",
            details={"candidate_proof_id": payload.candidate_proof_id},
        )
    if viewed_binding is not None and viewed_binding != binding_digest(payload):
        raise ProofMapError(
            "STALE_VIEW", f"what this decision on {target_id} is made on changed since you viewed it; reload and read it again"
        )
    return _Decision(payload=payload, reviewer_id=reviewer or git_identity(store.root))


def binding_digest(payload: DecisionPayload) -> str:
    """A digest of everything a decision is bound to (never its rationale): what a page shows, and sends back."""
    bound = payload.model_dump(mode="json", exclude={"rationale"})
    return hashlib.sha256(json.dumps(bound, sort_keys=True).encode("utf-8")).hexdigest()


def _node_folder(store: ProjectStore, object_type: str, object_id: str) -> str:
    """The node whose reviews.jsonl records a decision on this object."""
    if object_type == "evidence_check":
        return require_candidate_proof(store, require_evidence_check(store, object_id).candidate_proof_id).node_id
    if object_type == "challenge":
        return require_challenge(store, object_id).target_node_id
    return object_id


def _record(
    store: ProjectStore, decided: _Decision, object_type: str, object_id: str, state: ReviewGovernanceState
) -> ReviewRecord:
    """Record `decided` in its node's reviews.jsonl (committed with its snapshot once the transaction commits)."""
    payload = decided.payload
    entry = record_decision(
        store,
        node_id=_node_folder(store, object_type, object_id),
        object_type=object_type,
        object_id=object_id,
        kind=payload.kind,
        decision=state.value,
        reviewer=decided.reviewer_id,
        rationale=payload.rationale,
        payload=payload,
    )
    return ReviewRecord(
        id=entry.id,
        object_type=object_type,
        object_id=object_id,
        reviewer_id=entry.reviewer,
        decision=state,
        kind=ReviewRecordKind(payload.kind.value),
        rationale=payload.rationale,
        created_at=entry.decided_at,
        updated_at=entry.decided_at,
        decision_row_id=entry.id,
    )


_SAFE_NODE_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
# the vault's own files and folders, beside the node folders: a node folder can't take their place, in any letter
# case (a case-insensitive file system, macOS's default among them, would put `TRUST-RULES.JSONL/` where the file
# goes). `fog/` holds the Proof fog items' folders (ADR-0008, spec #136).
_RESERVED_NODE_IDS = frozenset({TRUST_RULES_FILE.casefold(), preamble_path(Path(".")).name.casefold(), "fog"})


def node_id_problem(node_id: str) -> str | None:
    """Why `node_id` can't name a node folder under proofs/ (ADR-0010), or None when it can."""
    if not _SAFE_NODE_ID.fullmatch(node_id):
        return f"node id {node_id!r} must be letters, digits, '.', '_' or '-', not starting with '.'"
    if node_id.casefold() in _RESERVED_NODE_IDS:
        return f"node id {node_id!r} is the name of one of the vault's own files or folders (proofs/{node_id.casefold()}), in any letter case"
    return None


def create_node(
    store: ProjectStore,
    *,
    node_id: str,
    kind: ProofMapNodeKind | str,
    statement: str,
    display_label: str = "",
    assumptions: list[str] | None = None,
    dependencies: list[str] | None = None,
    created_by: str = "human",
    source_locator: str | None = None,
    source_version: str | None = None,
    trust_level: TrustLevel | str | None = None,
    derived_from: str | None = None,
    reference_id: str | None = None,
    medium: Medium | str | None = None,
    definitions: list[str] | None = None,
) -> ProofMapNode:
    problem = node_id_problem(node_id)
    if problem is not None:
        # the id names the node's folder under proofs/ (ADR-0010), so it must be a plain, free folder name
        raise ProofMapError("INVALID_NODE_ID", problem)
    if get_proof_map_node(store, node_id) is not None:
        raise ProofMapError("NODE_ALREADY_EXISTS", f"proof map node {node_id} already exists")

    if derived_from is not None and get_proof_map_node(store, derived_from) is None:
        raise ProofMapError("DERIVED_FROM_NOT_FOUND", f"derived_from node {derived_from} does not exist")

    try:
        resolved_kind = ProofMapNodeKind(kind)
    except ValueError as exc:
        valid_kinds = ", ".join(member.value for member in ProofMapNodeKind)
        raise ProofMapError(
            "INVALID_KIND",
            f"'{kind}' is not a valid proof map node kind; expected one of: {valid_kinds}",
        ) from exc

    if resolved_kind == ProofMapNodeKind.imported_result and dependencies:
        raise ProofMapError(
            "IMPORTED_RESULT_HAS_NO_DEPENDENCIES",
            "an imported_result is established elsewhere, so nothing in this map is a premise of it",
        )

    for dependency_id in dependencies or []:
        if get_proof_map_node(store, dependency_id) is None:
            raise ProofMapError(
                "DEPENDENCY_NOT_FOUND",
                f"dependency {dependency_id} does not exist; create it before depending on it",
            )

    resolved_trust_level: TrustLevel | None = None
    if trust_level is not None:
        try:
            resolved_trust_level = TrustLevel(trust_level)
        except ValueError as exc:
            valid_levels = ", ".join(member.value for member in TrustLevel)
            raise ProofMapError(
                "INVALID_TRUST_LEVEL",
                f"'{trust_level}' is not a valid trust level; expected one of: {valid_levels}",
            ) from exc

    if resolved_kind == ProofMapNodeKind.imported_result:
        if not (source_locator or "").strip() or not (source_version or "").strip():
            raise ProofMapError(
                "IMPORTED_RESULT_REQUIRES_SOURCE",
                "an imported_result node requires both a source_locator and a source_version",
            )

    resolved_medium = _resolve_medium(resolved_kind, medium)

    if reference_id is not None:
        # the citation an imported result links (issue #91, ADR-0012): only there, and only one that exists
        if resolved_kind != ProofMapNodeKind.imported_result:
            raise ProofMapError(
                "REFERENCE_ID_NOT_IMPORTED_RESULT",
                f"only an imported_result links a reference; a {resolved_kind.value} has no citation",
            )
        if get_reference(store, reference_id) is None:
            raise ProofMapError(
                "REFERENCE_NOT_FOUND", f"reference {reference_id} does not exist; import it first with `proof reference import`"
            )

    node = ProofMapNode(
        id=node_id,
        kind=resolved_kind,
        display_label=display_label,
        statement=statement,
        assumptions=assumptions or [],
        definitions=list(dict.fromkeys(definitions or [])),   # each once, in the order named
        dependencies=dependencies or [],
        source_locator=source_locator,
        source_version=source_version,
        trust_level=resolved_trust_level,
        reference_id=reference_id,
        derived_from=derived_from,
        medium=resolved_medium,
        created_by=created_by,
        updated_by=created_by,
    )
    try:
        with store.transaction() as conn:
            for definition_id in node.definitions:  # in the write: a definition can't be removed between the check and the node (ADR-0020)
                if get_definition(store, definition_id, conn=conn) is None:
                    raise ProofMapError(
                        "DEFINITION_NOT_FOUND", f"definition {definition_id} does not exist; add it with `proof definition add` before a statement names it"
                    )
            insert_proof_map_node(store, node, conn=conn)
            append_event(
                store,
                "proof_map_node_created",
                f"created {resolved_kind.value} node {node.id}",
                entity_id=node.id,
                payload=node.model_dump(mode="json"),
                conn=conn,
            )
    except sqlite3.IntegrityError as exc:
        if resolved_kind == ProofMapNodeKind.theorem:
            raise ProofMapError(
                "DUPLICATE_THEOREM",
                "a theorem-kind node already exists for this project; only one is allowed",
            ) from exc
        raise ProofMapError("NODE_ALREADY_EXISTS", f"proof map node {node_id} already exists") from exc
    if resolved_kind != ProofMapNodeKind.imported_result:
        _write_working_files(store, node)
    elif reference_id is not None:
        # a citation may meet a Trust rule the moment it is linked (ADR-0014): on record from then
        note_trust_rule_matches(store, [node.id])
    return node


# -- the Proof agent's work log (spec #145, decided in #144) ---------------------------------------
# A run reports its plan and each step through `proof node progress`, as project state written through
# `proof` like everything else: an event on the node, never a decision, never a file in the node folder
# (a snapshot would freeze it). The work log the studio shows is these reports merged, in time order,
# with what the agent did through other `proof` commands: a split, a review request, an Evidence check,
# a fog item, a dependency edit — each carrying the role of the run's turn it happened in — and with
# the turns themselves: each its job, its backend session, the step it belongs to, and its conversation.

# a step's status; `needs-human` names, in its note, a decision only the researcher can make (the run stops for it)
PROGRESS_STATUSES = ("started", "done", "stuck", "needs-human")
# a Verifier's verdict on the working proof as it stands (ADR-0019 point 2); the objections carry the nuance
VERDICT_OUTCOMES = ("passed", "failed")
PROGRESS_EVENT = "agent_progress"
TURN_EVENT = "agent_turn"
# a turn's raw conversation, kept with the project's state (never the node folder, which a snapshot freezes)
TURNS_DIR = Path(".proof") / "agent-turns"
_TURN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def record_progress(
    store: ProjectStore,
    node_id: str,
    *,
    role: str | None,
    by: str,
    plan: list[str] | None = None,
    step: int | None = None,
    status: str | None = None,
    note: str = "",
    handoff: str | None = None,
    verdict: str | None = None,
    attempt: str | None = None,
    method: str | None = None,
    failed_on: str | None = None,
    coordinator: str | None = None,
    question: str | None = None,
) -> dict:
    """Report a plan (the steps the run means to take), one step's status, a handoff to another role, the
    Verifier's verdict on the working proof, an attempt the role abandoned (ADR-0019), or — on a Theorem or Lemma
    a Coordinator works — what the Coordinator did (`coordinator`: started a node's run, redirected a dependent,
    stopped; ADR-0019 point 18). A Coordinator holds no node and takes no turn, so its note names no role.
    Returns the log entry.

    A verdict is `passed` or `failed` with the objections as its note, and carries the inputs digest of the node
    folder as it stands — what a Review snapshot's manifest would hash — so a later edit makes it stale by
    construction; only the Verifier records one. An attempt is what the role tried to establish, how, and what it
    failed on; any role records one. Both are insert-only events like the rest of the work log.

    A question is a Standing question (ADR-0021 point 8): a judgement call the role made itself instead of stopping,
    worded as the choice made and the alternative. It gets an id and stays open until the researcher answers it
    (`answer_question`)."""
    node = require_node(store, node_id)
    if coordinator is not None:
        if not coordinator.strip():
            raise ProofMapError("PROGRESS_EMPTY", "say what the Coordinator did: --coordinator \"<what it started, redirected or stopped>\"")
        payload = {"kind": "coordinator", "role": None, "by": by, "note": coordinator.strip()}
        with store.transaction() as conn:
            append_event(store, PROGRESS_EVENT, f"coordinator on {node_id}: {coordinator.strip()}", entity_id=node_id, payload=payload, conn=conn)
        return {**payload, "node_id": node_id, "at": utc_now().isoformat()}
    if not role:
        raise ProofMapError("ROLE_REQUIRED", f"say which role reports: {', '.join(AGENT_ROLES)} (an agent's runtime sets PROOF_AGENT_ROLE)")
    if role not in AGENT_ROLES:
        raise ProofMapError("INVALID_ROLE", f"'{role}' is not a Proof agent role; expected one of: {', '.join(AGENT_ROLES)}")
    steps = [str(item).strip() for item in (plan or []) if str(item).strip()]
    if question is not None:
        if not question.strip():
            raise ProofMapError("PROGRESS_EMPTY", "say what was chosen and the alternative: --question \"<the choice made; the alternative>\"")
        payload = {"kind": "question", "id": f"q_{uuid.uuid4().hex[:10]}", "role": role, "by": by, "question": question.strip()}
        message = f"{role} on {node_id}: chose {question.strip()}"
    elif verdict is not None:
        if role != "verifier":
            raise ProofMapError("VERDICT_ROLE_REQUIRED", f"only the verifier records a verdict; {role} reports steps, attempts and handoffs")
        if verdict not in VERDICT_OUTCOMES:
            raise ProofMapError("INVALID_VERDICT", f"'{verdict}' is not a verdict; expected one of: {', '.join(VERDICT_OUTCOMES)}")
        if verdict == "failed" and not note.strip():
            raise ProofMapError("OBJECTIONS_REQUIRED", "a failed verdict names its objections: --note \"1. <the step or citation it attacks> …\"")
        payload = {"kind": "verdict", "role": role, "by": by, "outcome": verdict, "note": note.strip(), "inputs_sha256": _working_digest_or_none(store, node)}
        message = f"{role} on {node_id}: verdict {verdict}" + (f" — {note.strip()}" if note.strip() else "")
    elif attempt is not None or failed_on is not None:
        goal = (attempt or "").strip()
        obstruction = (failed_on or "").strip()
        if not goal or not obstruction:
            raise ProofMapError("ATTEMPT_INCOMPLETE", "an attempt is what was tried and what it failed on: --attempt \"<goal>\" --failed-on \"<the objection or obstruction>\"")
        payload = {"kind": "attempt", "role": role, "by": by, "goal": goal, "method": (method or "").strip(), "failed_on": obstruction}
        message = f"{role} on {node_id}: attempt at {goal} failed on {obstruction}"
    elif handoff is not None:
        if handoff not in AGENT_ROLES:
            raise ProofMapError("INVALID_ROLE", f"'{handoff}' is not a Proof agent role to hand off to; expected one of: {', '.join(AGENT_ROLES)}")
        payload = {"kind": "handoff", "role": role, "by": by, "to": handoff, "note": note.strip()}
        message = f"{role} on {node_id}: handed off to {handoff}" + (f" — {note.strip()}" if note.strip() else "")
    elif steps:
        payload = {"kind": "plan", "role": role, "by": by, "plan": steps, "note": note.strip()}
        message = f"{role} on {node_id}: plan of {len(steps)} step(s)"
    elif step is not None:
        if status is None:
            raise ProofMapError("PROGRESS_STATUS_REQUIRED", "a step report needs --status started, done or stuck")
        if status not in PROGRESS_STATUSES:
            raise ProofMapError("INVALID_PROGRESS_STATUS", f"'{status}' is not a step status; expected one of: {', '.join(PROGRESS_STATUSES)}")
        if int(step) < 1:
            raise ProofMapError("INVALID_PROGRESS_STEP", "steps count from 1")
        if status == "needs-human" and not note.strip():
            raise ProofMapError("DECISION_REQUIRED", "name the decision the researcher must make: --note \"<the decision>\"")
        payload = {"kind": "step", "role": role, "by": by, "step": int(step), "status": status, "note": note.strip()}
        message = f"{role} on {node_id}: step {step} {status}" + (f" — {note.strip()}" if note.strip() else "")
    else:
        raise ProofMapError("PROGRESS_EMPTY", "report a plan (--plan, repeatable), a step (--step N --status …), a handoff (--handoff <role>), a verdict (--verdict passed|failed), an attempt (--attempt … --failed-on …) or a choice made (--question …)")
    with store.transaction() as conn:
        append_event(store, PROGRESS_EVENT, message, entity_id=node_id, payload=payload, conn=conn)
    return {**payload, "node_id": node_id, "at": utc_now().isoformat()}


def _working_digest_or_none(store: ProjectStore, node: ProofMapNode) -> str | None:
    """The digest a verdict is about (ADR-0019 point 2): the SHA-256 a Review snapshot of the folder as it stands would
    be known by — every file the Verifier read, a computation's `out/` and the key-ideas summary included, not the
    inputs alone (those are a Run's Evidence rule, ADR-0015). None when the folder can't be read or holds a link where
    a snapshot would read: the verdict is still recorded — it is the Verifier's reading, not a snapshot — and a verdict
    without a hash matches no snapshot, so it opens no gate."""
    try:
        return read_working_snapshot(store.root, node.id, node.medium).digest()
    except (OSError, NodeFolderLinks):
        return None


def _progress_entries(store: ProjectStore, node_id: str, kind: str) -> list[dict]:
    """The node's `agent_progress` events of one kind, oldest first, each with its time."""
    require_node(store, node_id)
    return [
        {"at": event.created_at.isoformat(), **(event.payload or {})}
        for event in list_events(store)
        if event.kind == PROGRESS_EVENT and event.entity_id == node_id and (event.payload or {}).get("kind") == kind
    ]


def verdicts(store: ProjectStore, node_id: str) -> list[dict]:
    """The Verifier's verdicts on the node, newest last (ADR-0019 point 2): each its outcome, its objections (`note`),
    the role and agent that made it, the inputs digest it was about (`inputs_sha256`, None if unreadable then), and
    whether it is `stale`: the text it read the proof against — the node's or anything it rests on — was restated
    after it (ADR-0021 point 6). A stale verdict opens no gate, whatever its digest."""
    restated = restated_at(store, node_id)
    return [
        {**entry, "stale": restated is not None and datetime.fromisoformat(entry["at"]) < restated}
        for entry in _progress_entries(store, node_id, "verdict")
    ]


def latest_verdict(store: ProjectStore, node_id: str) -> dict | None:
    """The newest verdict on the node, or None: what the run compares with the working inputs' digest now to know
    whether the Prover may request review (ADR-0019 point 3). A verdict whose hash is not the folder's is stale."""
    found = verdicts(store, node_id)
    return found[-1] if found else None


def questions(store: ProjectStore, node_id: str) -> list[dict]:
    """The node's Standing questions, oldest first (ADR-0021 point 8): each its id, the choice made and the
    alternative (`question`), the role and agent that made it, `state` (`open` or `answered`) and the researcher's
    `answer` (who, whether the choice was kept, the other reading, and the redirect it made), or None while open."""
    answers = {entry.get("question_id"): entry for entry in _progress_entries(store, node_id, "answer")}
    found = []
    for entry in _progress_entries(store, node_id, "question"):
        answer = answers.get(entry.get("id"))
        found.append({
            **entry,
            "state": "open" if answer is None else "answered",
            "answer": None if answer is None else {key: answer.get(key) for key in ("at", "by", "keep", "answer", "redirect")},
        })
    return found


def answer_question(
    store: ProjectStore, node_id: str, question_id: str, *, keep: bool = False, answer: str | None = None, by: str = "human"
) -> dict:
    """The researcher's answer to a Standing question (ADR-0021 point 8): `keep` the choice the role made, or give the
    other reading as `answer`. An answer that differs from the choice is a redirect: recorded as the answer's
    `redirect`, the line the node's next run is briefed with. Each question is answered once. Never a Review
    decision: it fixes nothing and decides no trust."""
    text = (answer or "").strip()
    if keep == bool(text):
        raise ProofMapError("ANSWER_REQUIRED", "keep the choice (--keep) or give the other reading (--answer \"<the reading to follow>\"), not both")
    with store.transaction() as conn:
        asked = next((entry for entry in questions(store, node_id) if entry.get("id") == question_id), None)
        if asked is None:
            raise ProofMapError("QUESTION_NOT_FOUND", f"{node_id} has no standing question {question_id}", details={"node_id": node_id, "question_id": question_id})
        if asked["state"] == "answered":
            raise ProofMapError(
                "QUESTION_ANSWERED",
                f"{question_id} on {node_id} was already answered by {asked['answer']['by']}; a further redirect goes to the node's run",
                details={"answer": asked["answer"]},
            )
        payload = {
            "kind": "answer", "role": None, "by": by, "question_id": question_id,
            "keep": keep, "answer": text or None, "redirect": text or None,
        }
        message = f"{by} answered {question_id} on {node_id}: " + ("the choice stands" if keep else f"redirect — {text}")
        append_event(store, PROGRESS_EVENT, message, entity_id=node_id, payload=payload, conn=conn)
    return {**payload, "node_id": node_id, "at": utc_now().isoformat()}


def attempts(store: ProjectStore, node_id: str) -> list[dict]:
    """What the roles tried on the node and abandoned, oldest first (ADR-0019 point 7): each its goal, its method
    and what it failed on. The run briefs its next turn from these, newest first."""
    return _progress_entries(store, node_id, "attempt")


def record_agent_turn(
    store: ProjectStore,
    node_id: str,
    *,
    phase: str,
    turn: str,
    role: str,
    by: str,
    provider: str = "",
    job: int | None = None,
    session_id: str | None = None,
    step: int | None = None,
    events: list[dict] | None = None,
    prompt: str | None = None,
    changed: list[dict] | None = None,
) -> None:
    """A run's turn on the node: `started` before it runs, `ended` when it is over, with its job, its backend session
    (where the backend keeps the conversation too), the step it belongs to, and the conversation itself, kept under
    .proof/agent-turns/ so it outlives the studio's memory: a new Start, a restart. Never a decision."""
    require_node(store, node_id)
    if not _TURN_ID.fullmatch(turn):
        raise ProofMapError("INVALID_REQUEST", f"not a turn id: {turn!r}")
    payload: dict = {"phase": phase, "turn": turn, "role": role, "by": by, "provider": provider}
    if phase == "ended":
        payload.update(job=job, session_id=session_id, step=step)
        if changed is not None:  # the files it changed, each with the first line it changed (spec #145, story 18)
            payload["changed"] = [{"path": str(c.get("path")), "line": int(c.get("line") or 1)} for c in changed]
        if events is not None:
            path = TURNS_DIR / node_id / f"{turn}.json"
            target = store.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            # write-then-rename, as the project's own side files are: a reader never sees half a transcript
            tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps({**payload, "prompt": prompt, "events": events}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
            payload["transcript"] = path.as_posix()
    with store.transaction() as conn:
        append_event(store, TURN_EVENT, f"{role} on {node_id}: turn {turn} {phase}", entity_id=node_id, payload=payload, conn=conn)


# the map-level discussion (issue #177): the researcher and the map's agent on the proof plan, kept with the project
DISCUSSION_EVENT = "map_discussion"
DISCUSSION_DIR = Path(".proof") / "discussion"
DISCUSSION_REPLY_KEPT = 4000   # characters of the reply kept in the event itself; the transcript holds the whole


def record_discussion_turn(
    store: ProjectStore,
    *,
    phase: str,
    turn: str,
    by: str,
    provider: str = "",
    prompt: str | None = None,
    fresh: bool = False,
    job: int | None = None,
    session_id: str | None = None,
    events: list[dict] | None = None,
    reply: str | None = None,
    is_error: bool = False,
) -> None:
    """One exchange of the map-level discussion (issue #177): `started` with the researcher's message (and whether it
    opens a new conversation, `fresh`), `ended` with the backend's session (how the next message continues it), the
    reply's text and the conversation itself, kept under .proof/discussion/ as a node's agent turns are. Project state,
    never a node's: the discussion is about the map. Never a decision."""
    if phase not in ("started", "ended"):
        raise ProofMapError("INVALID_REQUEST", f"a discussion turn is started or ended, not {phase!r}")
    if not _TURN_ID.fullmatch(turn or ""):
        raise ProofMapError("INVALID_REQUEST", f"not a turn id: {turn!r}")
    payload: dict = {"phase": phase, "turn": turn, "by": by, "provider": provider}
    if phase == "started":
        payload.update(prompt=str(prompt or ""), fresh=bool(fresh))
    else:
        payload.update(job=job, session_id=session_id, reply=str(reply or "")[:DISCUSSION_REPLY_KEPT], is_error=bool(is_error))
        if events is not None:
            path = DISCUSSION_DIR / f"{turn}.json"
            target = store.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")  # write-then-rename: never half a transcript
            tmp.write_text(json.dumps({**payload, "prompt": prompt, "events": events}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
            payload["transcript"] = path.as_posix()
    with store.transaction() as conn:
        append_event(store, DISCUSSION_EVENT, f"discussion with {by}: turn {turn} {phase}", payload=payload, conn=conn)


def discussion_turns(store: ProjectStore, limit: int = 50) -> list[dict]:
    """The map-level discussion, oldest first, one entry per turn: the message, whether it opened a new conversation, and —
    once the turn ended — the reply, the session it left and whether the backend failed. The last `limit` turns."""
    turns: dict[str, dict] = {}
    for event in list_events(store):
        if event.kind != DISCUSSION_EVENT:
            continue
        payload = event.payload or {}
        turn = str(payload.get("turn") or "")
        entry = turns.setdefault(turn, {"turn": turn, "at": None, "by": payload.get("by"), "provider": payload.get("provider"), "prompt": "",
                                        "fresh": False, "ended": False, "ended_at": None, "reply": "", "session_id": None, "is_error": False, "transcript": None})
        if payload.get("phase") == "started":
            entry.update(at=event.created_at.isoformat(), prompt=payload.get("prompt") or "", fresh=bool(payload.get("fresh")),
                         by=payload.get("by"), provider=payload.get("provider"))
        else:
            entry.update(ended=True, ended_at=event.created_at.isoformat(), reply=payload.get("reply") or "", session_id=payload.get("session_id"),
                         is_error=bool(payload.get("is_error")), transcript=payload.get("transcript"))
    ordered = [entry for entry in turns.values()]
    return ordered[-limit:] if limit and limit > 0 else ordered


def discussion_transcript(store: ProjectStore, turn: str) -> dict | None:
    """A discussion turn's record with its conversation (`events`), as record_discussion_turn kept it; None when there is none."""
    if not _TURN_ID.fullmatch(turn or ""):
        return None
    try:
        return json.loads((store.root / DISCUSSION_DIR / f"{turn}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def agent_turn_transcript(store: ProjectStore, node_id: str, turn: str) -> dict | None:
    """A turn's record with its conversation (`events`), as record_agent_turn kept it; None when there is none."""
    if not _TURN_ID.fullmatch(turn or "") or not _SAFE_NODE_ID.fullmatch(node_id or ""):  # as node folders are named
        return None
    try:
        return json.loads((store.root / TURNS_DIR / node_id / f"{turn}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def work_log(store: ProjectStore, node_id: str) -> list[dict]:
    """The node's work log: the agent's reports merged, in time order, with what it did through `proof` and its turns.
    What the run's agent did during one of its turns carries that turn's role; anything else — outside a turn, or by
    someone else while a turn runs (the researcher's own split, a fog item from the map) — keeps its own actor and has none."""
    require_node(store, node_id)
    proof_ids = {proof.id for proof in list_candidate_proofs(store, node_id)}
    fog = {item.id: item for item in list_fog_items(store)}
    near_fog = {fog_id for fog_id, item in fog.items() if node_id in item.near}  # the fog about this node: its Experiments belong here
    entries: list[dict] = []
    turn: dict | None = None  # the run's turn running at this point of the log: its role, and the agent name it acts as
    for event in list_events(store):
        at = event.created_at.isoformat()
        payload = event.payload or {}
        if event.kind == TURN_EVENT and event.entity_id == node_id:
            if payload.get("phase") == "started":
                turn = payload
                continue
            turn = None
            if payload.get("job") is not None:  # a turn that never began (stopped before it existed) has nothing to show
                entries.append({"at": at, "kind": "turn", **{key: value for key, value in payload.items() if key != "phase"}})
            continue
        before = len(entries)
        if event.kind == PROGRESS_EVENT and event.entity_id == node_id:
            entries.append({"at": at, **payload})
        elif event.kind == "proof_map_node_split" and event.entity_id == node_id:
            entries.append({"at": at, "kind": "split", "by": payload.get("created_by"), "nodes": list(payload.get("child_ids") or [])})
        elif event.kind == "proof_map_review_requested" and event.entity_id == node_id:
            entries.append({"at": at, "kind": "review-requested", "by": payload.get("requested_by"), "version": payload.get("version"), "candidate_proof_id": payload.get("candidate_proof_id")})
        elif event.kind == "proof_map_evidence_check_recorded" and event.entity_id in proof_ids:
            entries.append({"at": at, "kind": "evidence", "by": payload.get("run_by"), "outcome": payload.get("outcome"), "evidence_check_id": payload.get("evidence_check_id")})
        elif event.kind == "proof_fog_added" and node_id in (payload.get("near") or []):
            text = payload.get("text") or (fog[event.entity_id].text if event.entity_id in fog else None)  # older events: the item's text
            entries.append({"at": at, "kind": "fog", "by": payload.get("created_by"), "fog_id": event.entity_id, "text": text})
        elif event.kind == "proof_fog_experiment_recorded" and event.entity_id in near_fog:
            entries.append({"at": at, "kind": "experiment", "by": payload.get("run_by"), "fog_id": event.entity_id, "outcome": payload.get("outcome"), "seq": payload.get("seq")})
        elif event.kind in ("proof_map_dependency_added", "proof_map_dependency_removed", "proof_map_dependency_moved") and event.entity_id == node_id:
            entries.append({"at": at, "kind": "dependencies", "by": payload.get("edited_by") or payload.get("by"), "change": event.kind.rsplit("_", 1)[1], "dependency": payload.get("dependency_id") or payload.get("dependency")})
        elif event.kind in ("proof_map_node_claimed", "proof_map_claim_reassigned") and event.entity_id == node_id:
            entries.append({"at": at, "kind": "claimed", "by": payload.get("claimant_id") or payload.get("assignee")})
        for entry in entries[before:]:  # an automatic entry: the role of the turn it happened in, when the run's agent did it
            entry.setdefault("role", turn.get("role") if turn is not None and entry.get("by") == turn.get("by") else None)
    return entries


def _resolve_medium(kind: ProofMapNodeKind, medium: Medium | str | None) -> Medium | None:
    """The node's Medium (spec #145): `latex` unless asked otherwise; never on an imported result."""
    if kind == ProofMapNodeKind.imported_result:
        if medium is not None:
            raise ProofMapError("MEDIUM_NOT_APPLICABLE", "an imported_result has no candidate proof, so no medium; it enters the map through Reference review")
        return None
    if medium is None:
        return Medium.latex
    try:
        return Medium(medium)
    except ValueError as exc:
        valid = ", ".join(member.value for member in Medium)
        raise ProofMapError("INVALID_MEDIUM", f"'{medium}' is not a medium; expected one of: {valid}") from exc


def _write_working_files(store: ProjectStore, node: ProofMapNode) -> None:
    """The node folder its Medium asks for: a LaTeX document, or a computation's run.sh (spec #145). The LaTeX document
    opens with the definitions the statement is written in (ADR-0020), so it reads on its own."""
    if is_computation(node):
        write_working_computation(store.root, node_id=node.id, kind=node.kind.value, statement=node.statement)
    else:
        named = [get_definition(store, definition_id) for definition_id in node.definitions]
        write_working_proof(store.root, node_id=node.id, kind=node.kind.value, statement=node.statement,
                            definitions=[(d.term, d.text) for d in named if d is not None])


def set_medium(store: ProjectStore, node_id: str, medium: Medium | str, *, edited_by: str = "human") -> ProofMapNode:
    """Change what a node's candidate proof is made of (spec #145). Allowed at any time: the
    medium is not part of the Accepted mathematical interface, so an Acceptance stands; files are
    never removed, and the entry the new medium needs (run.sh or proof.tex) is scaffolded if
    missing. Setting the medium a node already has changes and records nothing."""
    node = require_node(store, node_id)
    resolved = _resolve_medium(node.kind, medium)  # refuses an imported result or an unknown medium
    if resolved == node.medium:
        return node
    changed = node.model_copy(update={"medium": resolved, "updated_by": edited_by, "updated_at": utc_now()})
    with store.transaction() as conn:
        # the scaffold first, undone if the transaction rolls back: an event is never left without its entry file
        _scaffold_on_rollback(store, node_id)
        _write_working_files(store, changed)
        update_proof_map_node(store, changed, conn=conn)
        append_event(
            store, "proof_map_node_medium_set", f"{node_id}: medium {node.medium.value} → {resolved.value}",
            entity_id=node_id, payload={"from": node.medium.value, "to": resolved.value, "by": edited_by}, conn=conn,
        )
    return changed


# -- Unfixed text (ADR-0021 point 6) -------------------------------------------------------------------------------

RESTATED_EVENT = "proof_map_node_restated"
DEFINITION_EDITED_EVENT = "definition_edited"
RESEARCHER = "human"  # the `--by` / `created_by` of the researcher's own writes; anything else is an agent


def _resting_on(store: ProjectStore, node_id: str) -> set[str]:
    """`node_id` and every node that rests on it, directly or through others."""
    dependents_of: dict[str, list[str]] = {}
    for node in list_nodes(store):
        for dependency_id in node.dependencies:
            dependents_of.setdefault(dependency_id, []).append(node.id)
    found = {node_id}
    pending = [node_id]
    while pending:
        for dependent_id in dependents_of.get(pending.pop(), []):
            if dependent_id not in found:
                found.add(dependent_id)
                pending.append(dependent_id)
    return found


def _rests_on(store: ProjectStore, node_id: str) -> set[str]:
    """`node_id` and every node it rests on, directly or through others."""
    found = {node_id}
    pending = [node_id]
    while pending:
        node = get_node(store, pending.pop())
        for dependency_id in node.dependencies if node is not None else []:
            if dependency_id not in found:
                found.add(dependency_id)
                pending.append(dependency_id)
    return found


def fixed_by(store: ProjectStore, node_id: str) -> dict | None:
    """The Review decision that fixed a node's statement, assumptions and named definitions, or None while they are
    Unfixed (ADR-0021 point 6): the first Acceptance decision of any outcome, or Reference review, on the node or on
    any node resting on it. A decision relied on the text, so no restatement may change it under that decision."""
    first: dict | None = None
    for decided_id in sorted(_resting_on(store, node_id)):
        for kind in (ReviewRecordKind.acceptance, ReviewRecordKind.reference_review):
            for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, decided_id, kind.value):
                if row["decision"] == ReviewGovernanceState.proposed_for_review.value:
                    continue
                if first is None or row["created_at"] < first["decided_at"]:
                    first = {"node_id": decided_id, "review_id": row["review_id"], "kind": kind.value, "decision": row["decision"], "decided_at": row["created_at"]}
                break  # the oldest of this kind on this node
    return first


def restated_at(store: ProjectStore, node_id: str) -> datetime | None:
    """When the text a node's proof is read against last changed, or None if it never did since its creation: the
    newest restatement of the node or of a node it rests on, or edit of a Definition any of them names."""
    nodes = _rests_on(store, node_id)
    named = {definition_id for current_id in nodes for definition_id in (getattr(get_node(store, current_id), "definitions", None) or [])}
    newest: datetime | None = None
    for event in list_events(store):
        if (event.kind == RESTATED_EVENT and event.entity_id in nodes) or (event.kind == DEFINITION_EDITED_EVENT and event.entity_id in named):
            newest = event.created_at if newest is None or event.created_at > newest else newest
    return newest


def require_restatable(store: ProjectStore, *, what: str, created_by: str, by: str, fixed: dict | None, fixed_code: str) -> None:
    """Refuse a change to fixed text (`fixed_code`, naming the decision), or an agent's change to the researcher's."""
    if fixed is not None:
        raise ProofMapError(
            fixed_code,
            f"{what} is fixed: the {fixed['kind'].replace('_', ' ')} decision {fixed['review_id']} on {fixed['node_id']} relied on it; "
            "state a corrected version as a new node or definition",
            details={"fixed_by": fixed},
        )
    if by != RESEARCHER and created_by == RESEARCHER:
        raise ProofMapError("RESEARCHER_TEXT", f"{what} was written by the researcher: only the researcher restates it")


def restate_node(
    store: ProjectStore,
    node_id: str,
    *,
    statement: str | None = None,
    assumptions: list[str] | None = None,
    definitions: list[str] | None = None,
    reason: str,
    by: str = RESEARCHER,
) -> ProofMapNode:
    """Change a node's statement, assumptions or named definitions while they are Unfixed (ADR-0021 point 6).

    The researcher may restate any unfixed text, an agent only a node an agent created (RESEARCHER_TEXT). Fixed text
    is refused (TEXT_FIXED, naming the decision that fixed it). Recorded in the work log with the reason; every
    verdict on the node and on what rests on it goes stale (`verdicts`), and the snapshots there awaiting a decision
    read Potentially stale. The working proof is the role's, and is left as it is."""
    if not (reason or "").strip():
        raise ProofMapError("RESTATE_REASON_REQUIRED", "a restatement says why: --reason \"<what was wrong or unclear>\"")
    update: dict[str, Any] = {}
    with store.transaction() as conn:
        node = require_node(store, node_id)
        if statement is not None and statement.strip() and statement.strip() != node.statement:
            update["statement"] = statement.strip()
        if assumptions is not None and [a.strip() for a in assumptions if a.strip()] != node.assumptions:
            update["assumptions"] = [a.strip() for a in assumptions if a.strip()]
        if definitions is not None:
            named = list(dict.fromkeys(definitions))
            for definition_id in named:
                if get_definition(store, definition_id, conn=conn) is None:
                    raise ProofMapError("DEFINITION_NOT_FOUND", f"definition {definition_id} does not exist; add it with `proof definition add` before a statement names it")
            if named != node.definitions:
                update["definitions"] = named
        if not update:
            raise ProofMapError("RESTATE_EMPTY", f"nothing to restate: give {node_id} a different --statement, --assumption or --definition")
        require_restatable(store, what=f"{node_id}'s statement", created_by=node.created_by, by=by, fixed=fixed_by(store, node_id), fixed_code="TEXT_FIXED")
        changed = node.model_copy(update={**update, "updated_by": by, "updated_at": utc_now()})
        update_proof_map_node(store, changed, conn=conn)
        append_event(
            store, RESTATED_EVENT, f"{node_id} restated by {by}: {reason.strip()}", entity_id=node_id,
            payload={"by": by, "reason": reason.strip(), "from": {key: getattr(node, key) for key in update}, "to": update},
            conn=conn,
        )
    return changed


def _scaffold_on_rollback(store: ProjectStore, node_id: str) -> None:
    """Inside a write transaction about to scaffold a node's working files: remove each one it
    creates (and each folder) if the transaction rolls back. What was there before stays."""
    folder = node_folder(store.root, node_id)
    candidates = [
        vault_dir(store.root), folder, preamble_path(store.root), vault_dir(store.root) / ".gitignore",
        working_proof_path(store.root, node_id), run_script_path(store.root, node_id), folder / key_ideas.KEY_IDEAS_FILE,
    ]
    absent = [path for path in candidates if not path.exists()]

    def undo() -> None:
        for path in reversed(absent):  # files first, then the folders that held them
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
            else:
                path.unlink(missing_ok=True)

    on_rollback(store, undo)


def _promoted(store: ProjectStore, node_id: str) -> bool:
    return any(
        verify_decision_row(store, row["id"]).status == "verified"
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewRecordKind.promote.value)
    )


def _effective_kind(store: ProjectStore, node: ProofMapNode) -> ProofMapNodeKind:
    """A node's kind as it counts: its stored kind, plus a recorded Promote."""
    kind = node.kind
    if kind == ProofMapNodeKind.claim and _promoted(store, node.id):
        kind = ProofMapNodeKind.lemma
    return kind


def _as_counted(store: ProjectStore, node: ProofMapNode | None) -> ProofMapNode | None:
    if node is None:
        return None
    kind = _effective_kind(store, node)
    return node if kind == node.kind else node.model_copy(update={"kind": kind})


@memoized_read
def get_node(store: ProjectStore, node_id: str) -> ProofMapNode | None:
    return _as_counted(store, get_proof_map_node(store, node_id))


def require_node(store: ProjectStore, node_id: str) -> ProofMapNode:
    node = get_node(store, node_id)
    if node is None:
        raise ProofMapError("NODE_NOT_FOUND", f"proof map node {node_id} not found")
    return node


@memoized_read
def list_nodes(store: ProjectStore) -> list[ProofMapNode]:
    return [_as_counted(store, node) for node in list_proof_map_nodes(store)]


def dependents(store: ProjectStore, node_id: str) -> list[ProofMapNode]:
    """The nodes that rest on `node_id`, in the map's order: what a briefing shares with, and what a Coordinator
    redirects when the node is Accepted (ADR-0019 points 14 and 19)."""
    require_node(store, node_id)
    return [node for node in list_nodes(store) if node_id in node.dependencies]


def siblings(store: ProjectStore, node_id: str) -> list[ProofMapNode]:
    """The other dependencies of each node that rests on `node_id` — the children beside it under the same
    parents — each once, in the map's order, never the node itself (ADR-0019 point 14). Two Claims under one
    Lemma with no edge between them are often proved by the same technique; this is how a briefing finds them."""
    require_node(store, node_id)
    wanted: set[str] = set()
    for parent in dependents(store, node_id):
        wanted.update(dependency for dependency in parent.dependencies if dependency != node_id)
    return [node for node in list_nodes(store) if node.id in wanted]


def split_node(
    store: ProjectStore,
    parent_id: str,
    child_specs: list[dict[str, Any]],
    *,
    created_by: str = "human",
    reassign: bool = False,
) -> list[ProofMapNode]:
    """Decompose `parent_id` into one or more new `claim`-kind children.

    Ungated — no researcher approval needed, so "split first, don't force a
    proof" is genuinely the path of least resistance. Each child gets
    `derived_from=parent_id` and is appended to the parent's dependencies;
    the parent's own pre-existing dependencies are untouched. This alone
    doesn't get the parent any closer to Accepted — once every child is
    Accepted the parent simply stops being `blocked`, and still needs its
    own Candidate proof and Acceptance like any other node ("how the pieces
    combine" is never assumed true without a human looking at it).

    A node someone else has claimed is theirs to split (NOT_CLAIMANT), unless
    `reassign` takes the claim over for `created_by`, recorded as `claim --reassign`
    records it — but without claim's checks: a split parent is usually Blocked
    on its earlier children, and splitting it again is still fine.
    All or nothing (#26): the checks, every child and the parent's new
    dependencies are one write transaction, and a failed split leaves no
    child, no child folder, and the parent as it was.

    Each spec in `child_specs` is `{"id": str, "statement": str,
    "assumptions": list[str] (optional), "display_label": str (optional),
    "dependencies": list[str] (optional)}`. A child's own dependencies are
    validated as any dependency is: each must exist (DEPENDENCY_NOT_FOUND)
    and none may rest on the parent (DEPENDENCY_CYCLE).
    """
    if not child_specs:
        require_node(store, parent_id)
        raise ProofMapError("SPLIT_REQUIRES_CHILDREN", "split requires at least one child claim")
    with store.transaction() as conn:
        remove_new_node_folders_on_rollback(store, [spec["id"] for spec in child_specs])
        return _split(store, conn, parent_id, child_specs, created_by=created_by, reassign=reassign)


def create_node_under_parent(
    store: ProjectStore, parent_id: str, *, created_by: str = "human", reassign: bool = False, **fields: Any
) -> ProofMapNode:
    """Create a node and make `parent_id` rest on it, in one write transaction (issue #154).

    Any kind, an imported result included: the parent gains the new node as a
    dependency, exactly as `create_node` then `add_dependency(parent_id, …)`
    would, with every refusal of either (NOT_CLAIMANT unless `reassign`,
    NODE_ACCEPTED, DEPENDENCY_CYCLE, …). Unlike a Split, the node is not
    derived from the parent. A refused parent leaves no node and no folder.
    `fields` are `create_node`'s.
    """
    with store.transaction() as conn:
        remove_new_node_folders_on_rollback(store, [fields["node_id"]])
        # a node hung under a parent is written in the parent's definitions too (ADR-0020)
        fields = {**fields, "definitions": [*require_node(store, parent_id).definitions, *(fields.get("definitions") or [])]}
        node = create_node(store, created_by=created_by, **fields)
        # add_dependency's checks, in its order; the new node is not yet visible outside this
        # transaction, so the cycle is looked for from its own dependencies down to the parent
        parent = require_node(store, parent_id)
        _structure_editable(store, parent)
        for dependency_id in node.dependencies:
            path = _dependency_path(store, dependency_id, parent_id)
            if path is not None:
                raise _cycle(parent_id, [parent_id, node.id, *path])
        claim = _held_by_another(store, conn, parent_id, created_by, reassign=reassign)
        if claim is not None:
            _take_over(store, conn, claim, created_by)
        _gain_dependency(store, conn, parent, node.id, created_by)
    return node


def remove_new_node_folders_on_rollback(store: ProjectStore, node_ids: list[str]) -> None:
    """Inside a write transaction that will create `node_ids`: take their folders with them if it rolls back.

    Under the write lock, a node with no row yet and no folder yet is ours alone: no one else
    can create it until this commits. Any other folder may be another writer's (`create_node`
    writes its proof.tex once its own transaction commits — a SAVEPOINT release, inside ours),
    so those are left be. The cleanup is an `on_rollback` callback: it runs before the lock
    goes, while nobody else can have taken the id, and a failed commit runs it too. A Split
    registers it for its children; a free-standing Crystallize for its Claim (spec #136).
    """
    ours = {node_folder(store.root, node_id) for node_id in node_ids if node_id_problem(node_id) is None and get_proof_map_node(store, node_id) is None}
    ours = {folder for folder in ours if not folder.exists()}
    on_rollback(store, lambda: _remove_folders(ours))


def _remove_folders(folders: set[Path]) -> None:
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)


def _split(
    store: ProjectStore,
    conn: sqlite3.Connection,
    parent_id: str,
    child_specs: list[dict[str, Any]],
    *,
    created_by: str,
    reassign: bool,
) -> list[ProofMapNode]:
    parent = require_node(store, parent_id)

    if parent.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError("IMMUTABLE_NODE", f"imported_result node {parent_id} cannot be split")

    acceptance = get_acceptance_state(store, parent_id)
    if acceptance == "rejected":
        raise ProofMapError(
            "NODE_REJECTED", f"node {parent_id} was Rejected and should not be pursued further; split is unavailable"
        )
    if acceptance in ("accepted", "unverifiable"):
        # new dependencies would change the interface the researcher accepted, and
        # silently void the acceptance: that's a decision, not a split (#37)
        raise ProofMapError(
            "NODE_ACCEPTED", f"node {parent_id} is {acceptance}; splitting it would void that decision, so split is unavailable"
        )

    claim = _held_by_another(store, conn, parent_id, created_by, reassign=reassign)
    if claim is not None:
        _take_over(store, conn, claim, created_by)

    children: list[ProofMapNode] = []
    for spec in child_specs:
        # a child may rest on existing nodes too (an imported result, a lemma); the parent will
        # rest on the child, so none of them may rest on the parent (PR #104)
        for dependency_id in spec.get("dependencies") or []:
            if get_proof_map_node(store, dependency_id) is not None:
                path = _dependency_path(store, dependency_id, parent_id)
                if path is not None:
                    raise _cycle(spec["id"], [spec["id"], *path, spec["id"]])
        child = create_node(
            store,
            node_id=spec["id"],
            kind=ProofMapNodeKind.claim,
            statement=spec["statement"],
            display_label=spec.get("display_label", ""),
            assumptions=spec.get("assumptions"),
            dependencies=list(spec.get("dependencies") or []),
            created_by=created_by,
            derived_from=parent_id,
            medium=spec.get("medium"),
            # a Claim of a node is about that node's objects: it is written in the parent's definitions (ADR-0020)
            definitions=[*parent.definitions, *(spec.get("definitions") or [])],
        )
        children.append(child)

    updated_parent = parent.model_copy(update={"dependencies": [*parent.dependencies, *(c.id for c in children)]})
    update_proof_map_node(store, updated_parent, conn=conn)

    append_event(
        store,
        "proof_map_node_split",
        f"split {parent_id} into {len(children)} claim(s)",
        entity_id=parent_id,
        payload={"child_ids": [c.id for c in children], "created_by": created_by},
        conn=conn,
    )
    return children


def _claim_conflict(existing: ClaimRecord) -> ProofMapError:
    return ProofMapError(
        "CLAIM_CONFLICT",
        f"node {existing.node_id} is already claimed by {existing.claimant_id}; pass --reassign to take it over",
        details={"node_id": existing.node_id, "assignee": existing.claimant_id, "claimed_at": existing.claimed_at.isoformat()},
    )


def _not_claimant(node_id: str, claim: ClaimRecord) -> ProofMapError:
    return ProofMapError(
        "NOT_CLAIMANT",
        f"{node_id} is claimed by {claim.claimant_id}",
        details={"node_id": node_id, "assignee": claim.claimant_id, "claimed_at": claim.claimed_at.isoformat()},
    )


def _not_pickable(store: ProjectStore, node: ProofMapNode) -> ProofMapError | None:
    """Why nobody may claim `node`, or None if anyone may.

    The frontier and `claim_node` share this, so nothing the frontier offers is
    refused. Accepted nodes are off it unless an open Challenge invites a
    revision (ADR-0005 Rule 4); Rejected ones for good. A Blocked node may be
    claimed and worked: Blocked holds back its Review decision, not work
    (ADR-0021 point 1), and only the frontier asks more of its dependencies.
    """
    if node.kind == ProofMapNodeKind.imported_result:
        return ProofMapError("IMMUTABLE_NODE", f"imported_result node {node.id} has no proof to work on; use Reference review instead")
    acceptance_state = get_acceptance_state(store, node.id)
    if acceptance_state == "rejected":
        return ProofMapError("NODE_REJECTED", f"node {node.id} was Rejected and should not be pursued further; create a new node instead")
    if acceptance_state == "accepted" and not has_open_challenge(store, node.id):
        return ProofMapError("NODE_ALREADY_ACCEPTED", f"node {node.id} is already Accepted; open a Challenge before reclaiming it to revise")
    if acceptance_state == "unverifiable":
        return ProofMapError(
            "NODE_UNVERIFIABLE",
            f"node {node.id}'s latest Human Review decision doesn't count; the researcher must decide it afresh before anyone picks it up",
        )
    return None


def _held_by_another(
    store: ProjectStore, conn: sqlite3.Connection, node_id: str, actor: str, *, reassign: bool
) -> ClaimRecord | None:
    """The claim `actor` must take over to change `node_id`'s structure, or None if there's none.

    A node someone else holds is theirs (NOT_CLAIMANT), unless `reassign`.
    Takes nothing over itself: the caller does, once every check has passed.
    """
    claim = get_active_claim(store, node_id, conn=conn)
    if claim is None or claim.claimant_id == actor:
        return None
    if not reassign:
        raise _not_claimant(node_id, claim)
    return claim


def _take_over(store: ProjectStore, conn: sqlite3.Connection, claim: ClaimRecord, actor: str) -> None:
    """Move `claim` to `actor`, recorded as `claim --reassign` records it."""
    mark_claim_released(store, claim.id, released_by=actor, reason=f"reassigned to {actor}", released_at=utc_now(), conn=conn)
    taken = ClaimRecord(id=str(uuid.uuid4()), node_id=claim.node_id, claimant_id=actor, session_id="")
    insert_claim(store, taken, conn=conn)
    append_event(
        store,
        "proof_map_claim_reassigned",
        f"claimed node {claim.node_id} by {actor}",
        entity_id=claim.node_id,
        payload={"claim_id": taken.id, "claimant_id": actor, "previous_claimant_id": claim.claimant_id},
        conn=conn,
    )


def _dependency_path(store: ProjectStore, start: str, goal: str) -> list[str] | None:
    """A chain of dependency edges from `start` down to `goal` (both included), or None.

    Breadth-first with an explicit worklist, like the integrity walk: a
    project's dependency chain can run deeper than Python's recursion limit.
    """
    came_from: dict[str, str | None] = {start: None}
    pending = [start]
    while pending:
        current = pending.pop(0)
        if current == goal:
            path = [current]
            while came_from[path[-1]] is not None:
                path.append(came_from[path[-1]])
            return path[::-1]
        node = get_proof_map_node(store, current)
        for dependency_id in node.dependencies if node else []:
            if dependency_id not in came_from:
                came_from[dependency_id] = current
                pending.append(dependency_id)
    return None


def _cycle(node_id: str, cycle: list[str]) -> ProofMapError:
    return ProofMapError(
        "DEPENDENCY_CYCLE",
        f"{node_id} can't rest on {cycle[1]}: " + " → ".join(cycle) + " would be a cycle",
        details={"node_id": node_id, "cycle": cycle},
    )


def _refuse_cycle(store: ProjectStore, node_id: str, dependency_id: str) -> None:
    """Refuse the edge `node_id` → `dependency_id` if `dependency_id` already rests on `node_id`."""
    path = _dependency_path(store, dependency_id, node_id)
    if path is not None:
        raise _cycle(node_id, [node_id, *path])


def _structure_editable(store: ProjectStore, node: ProofMapNode) -> None:
    """Whether `node`'s dependencies may be edited at all, apart from who holds it (issue #96).

    As `_not_pickable` rules for claiming: never an imported result (it rests
    on nothing here) or a Rejected node; an Accepted one only while an open
    Challenge invites its revision. The edit makes its Acceptance stop
    counting (`unverifiable`: its dependencies changed) until the researcher
    decides the revised node, so a node in that state stays editable only
    under the same open Challenge.
    """
    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMPORTED_RESULT_HAS_NO_DEPENDENCIES",
            f"{node.id} is an imported_result, established elsewhere: nothing in this map is a premise of it",
        )
    acceptance = get_acceptance_state(store, node.id)
    if acceptance == "rejected":
        raise ProofMapError("NODE_REJECTED", f"node {node.id} was Rejected and should not be pursued further; its dependencies stay as they were")
    if acceptance in ("accepted", "unverifiable") and not has_open_challenge(store, node.id):
        raise ProofMapError(
            "NODE_ACCEPTED",
            f"node {node.id} is {acceptance}; changing its dependencies would void that decision, so open a Challenge before revising it",
        )


@dataclass
class DependencyEdit:
    """One edit of a node's dependencies: what was done, and the node(s) as they now stand."""

    op: str  # add, remove or move
    dependency_id: str
    node: ProofMapNode
    to: ProofMapNode | None = None  # the node a moved dependency now rests under

    def as_json(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "dependency_id": self.dependency_id,
            "node": self.node.model_dump(mode="json"),
            "to": self.to.model_dump(mode="json") if self.to else None,
        }


def _with_dependencies(node: ProofMapNode, dependencies: list[str], actor: str) -> ProofMapNode:
    return node.model_copy(update={"dependencies": dependencies, "updated_by": actor, "updated_at": utc_now()})


def add_dependency(
    store: ProjectStore, node_id: str, dependency_id: str, *, edited_by: str = "human", reassign: bool = False
) -> DependencyEdit:
    """Make `node_id` rest on `dependency_id` too: a Lemma a proof came to use (story 38, #96).

    Structural, like Split: no researcher approval, agent-reachable. The
    target must exist and not already rest on the node (DEPENDENCY_CYCLE).
    A node someone else holds is theirs (NOT_CLAIMANT) unless `reassign`,
    except an edge between two unaccepted Claims `edited_by`'s own Split
    created: the Decomposer adds those itself (ADR-0021 point 7).
    No pin is taken here: the next request-review pins what the edge offers.
    """
    with store.transaction() as conn:
        node = require_node(store, node_id)
        _structure_editable(store, node)
        if get_proof_map_node(store, dependency_id) is None:
            raise ProofMapError("DEPENDENCY_NOT_FOUND", f"dependency {dependency_id} does not exist; create it before depending on it")
        if dependency_id in node.dependencies:
            raise ProofMapError("ALREADY_A_DEPENDENCY", f"{node_id} already rests on {dependency_id}")
        _refuse_cycle(store, node_id, dependency_id)
        if not _own_split_edge(store, node, dependency_id, edited_by):
            claim = _held_by_another(store, conn, node_id, edited_by, reassign=reassign)
            if claim is not None:
                _take_over(store, conn, claim, edited_by)
        _gain_dependency(store, conn, node, dependency_id, edited_by)
    return DependencyEdit("add", dependency_id, get_node(store, node_id))


def _own_split_edge(store: ProjectStore, node: ProofMapNode, dependency_id: str, edited_by: str) -> bool:
    """Whether `edited_by` is adding an edge between two Claims its own Split created, both unaccepted (ADR-0021
    point 7). An edge between unaccepted Claims decides nothing, so the Decomposer adds it without holding either
    Claim and without taking over the run that holds one."""
    dependency = get_node(store, dependency_id)
    return all(
        claim is not None
        and claim.kind == ProofMapNodeKind.claim
        and claim.derived_from is not None
        and claim.created_by == edited_by
        and get_acceptance_state(store, claim.id) not in ("accepted", "unverifiable", "rejected")
        for claim in (node, dependency)
    )


def _gain_dependency(store: ProjectStore, conn: sqlite3.Connection, node: ProofMapNode, dependency_id: str, edited_by: str) -> None:
    """Write `node` resting on `dependency_id` too, once every check has passed: the edge and its event."""
    updated = _with_dependencies(node, [*node.dependencies, dependency_id], edited_by)
    update_proof_map_node(store, updated, conn=conn)
    append_event(
        store,
        "proof_map_dependency_added",
        f"{node.id} now rests on {dependency_id}",
        entity_id=node.id,
        payload={"dependency_id": dependency_id, "edited_by": edited_by, "dependencies": {"before": node.dependencies, "after": updated.dependencies}},
        conn=conn,
    )


def remove_dependency(
    store: ProjectStore, node_id: str, dependency_id: str, *, edited_by: str = "human", reassign: bool = False
) -> DependencyEdit:
    """Stop `node_id` resting on `dependency_id` (#96). The edge's pin goes with it."""
    with store.transaction() as conn:
        node = require_node(store, node_id)
        _structure_editable(store, node)
        if dependency_id not in node.dependencies:
            raise ProofMapError("NOT_A_DEPENDENCY", f"{dependency_id} is not a dependency of {node_id}")
        claim = _held_by_another(store, conn, node_id, edited_by, reassign=reassign)
        if claim is not None:
            _take_over(store, conn, claim, edited_by)
        updated = _with_dependencies(node, [d for d in node.dependencies if d != dependency_id], edited_by)
        update_proof_map_node(store, updated, conn=conn)
        delete_dependency_pin(store, node_id, dependency_id, conn=conn)
        append_event(
            store,
            "proof_map_dependency_removed",
            f"{node_id} no longer rests on {dependency_id}",
            entity_id=node_id,
            payload={"dependency_id": dependency_id, "edited_by": edited_by, "dependencies": {"before": node.dependencies, "after": updated.dependencies}},
            conn=conn,
        )
    return DependencyEdit("remove", dependency_id, get_node(store, node_id))


def move_dependency(
    store: ProjectStore, node_id: str, dependency_id: str, *, to: str, edited_by: str = "human", reassign: bool = False
) -> DependencyEdit:
    """Move `node_id`'s dependency `dependency_id` down onto `to`, one of its own dependencies (#96).

    What CONTEXT.md's Split leaves to a person or agent: a parent's existing
    dependency deliberately handed to the child that now uses it. `node_id`
    still rests on it, through `to`. Both nodes are checked — editable, and
    held by the editor unless `reassign` — before either changes; `to`
    resting on the dependency mustn't close a cycle. The parent's pin goes
    with the edge; the child pins it at its next request-review.
    """
    with store.transaction() as conn:
        node = require_node(store, node_id)
        child = require_node(store, to)
        _structure_editable(store, node)
        if dependency_id not in node.dependencies:
            raise ProofMapError("NOT_A_DEPENDENCY", f"{dependency_id} is not a dependency of {node_id}")
        if to == dependency_id:
            raise ProofMapError("SAME_NODE", f"{dependency_id} can't be moved onto itself")
        if to not in node.dependencies:
            raise ProofMapError(
                "NOT_A_DEPENDENCY", f"{to} is not a dependency of {node_id}; a dependency moves onto one of the node's own dependencies",
                details={"node_id": node_id, "to": to},
            )
        _structure_editable(store, child)
        if dependency_id not in child.dependencies:
            _refuse_cycle(store, to, dependency_id)
        claims = [
            claim
            for claim in (
                _held_by_another(store, conn, node_id, edited_by, reassign=reassign),
                _held_by_another(store, conn, to, edited_by, reassign=reassign),
            )
            if claim is not None
        ]
        for claim in claims:
            _take_over(store, conn, claim, edited_by)
        updated = _with_dependencies(node, [d for d in node.dependencies if d != dependency_id], edited_by)
        child_after = [*child.dependencies, *([] if dependency_id in child.dependencies else [dependency_id])]
        update_proof_map_node(store, updated, conn=conn)
        update_proof_map_node(store, _with_dependencies(child, child_after, edited_by), conn=conn)
        delete_dependency_pin(store, node_id, dependency_id, conn=conn)
        append_event(
            store,
            "proof_map_dependency_moved",
            f"moved dependency {dependency_id} of {node_id} onto {to}",
            entity_id=node_id,
            payload={
                "dependency_id": dependency_id,
                "to": to,
                "edited_by": edited_by,
                "dependencies": {"before": node.dependencies, "after": updated.dependencies},
                "to_dependencies": {"before": child.dependencies, "after": child_after},
            },
            conn=conn,
        )
    return DependencyEdit("move", dependency_id, get_node(store, node_id), to=get_node(store, to))


def claim_node(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str = "",
    reassign: bool = False,
) -> ClaimRecord:
    """Assign a node to `claimant_id` before working on it: a wayfinder-style claim (ADR-0010).

    Idempotent for the same assignee. A node someone else holds is refused
    with CLAIM_CONFLICT naming the assignee, unless `reassign` takes it
    over — a claim is a planning signal, not a lock, so a stale one is simply
    reassigned. Any node that may still be worked can be claimed, a Blocked
    one included (see `_not_pickable`). The one-active-claim-per-node rule is
    the `claims` table's partial unique index, so a race between two
    claimants still resolves to one.
    """
    node = require_node(store, node_id)
    existing = get_active_claim(store, node_id)
    if existing is not None and existing.claimant_id == claimant_id:
        return existing
    problem = _not_pickable(store, node)
    if problem is not None:
        raise problem
    if existing is not None:
        if not reassign:
            raise _claim_conflict(existing)
        mark_claim_released(store, existing.id, released_by=claimant_id, reason=f"reassigned to {claimant_id}", released_at=utc_now())

    claim = ClaimRecord(id=str(uuid.uuid4()), node_id=node_id, claimant_id=claimant_id, session_id=session_id)
    try:
        insert_claim(store, claim)
    except sqlite3.IntegrityError as exc:
        existing = get_active_claim(store, node_id)
        if existing is not None and existing.claimant_id == claimant_id:
            return existing
        if existing is not None:
            raise _claim_conflict(existing) from exc
        raise ProofMapError("CLAIM_CONFLICT", f"node {node_id} is currently claimed") from exc
    except sqlite3.OperationalError as exc:
        # e.g. "database is locked" under heavy concurrent contention past
        # SQLite's busy_timeout — we don't know who, if anyone, won, so this
        # is honestly a contention error, not a confirmed conflict.
        raise ProofMapError("CLAIM_CONTENDED", f"could not claim node {node_id} due to database contention; retry") from exc

    append_event(
        store,
        "proof_map_claim_reassigned" if existing is not None else "proof_map_node_claimed",
        f"claimed node {node_id} by {claimant_id}",
        entity_id=node_id,
        payload={
            "claim_id": claim.id,
            "claimant_id": claimant_id,
            "previous_claimant_id": existing.claimant_id if existing is not None else None,
        },
    )
    return claim


def release_node(
    store: ProjectStore,
    node_id: str,
    *,
    claimant_id: str,
    session_id: str = "",
    reason: str | None = None,
) -> ClaimRecord:
    """Unassign a node: end its claim, whoever holds it (ADR-0010).

    A claim is a planning signal, so its holder, the researcher, or anyone
    by agreement may clear it; `claimant_id` is who did, recorded with the
    reason. Claims never expire on their own.
    """
    require_node(store, node_id)
    claim = get_active_claim(store, node_id)
    if claim is None:
        raise ProofMapError("NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim")
    release_reason = reason or ("released by claimant" if claim.claimant_id == claimant_id else f"unassigned by {claimant_id}")
    released_at = utc_now()
    if not mark_claim_released(store, claim.id, released_by=claimant_id, reason=release_reason, released_at=released_at):
        # someone else's concurrent release reached SQLite's write lock first
        raise ProofMapError("NO_ACTIVE_CLAIM", f"proof map node {node_id} has no active claim")
    append_event(
        store,
        "proof_map_claim_released",
        f"released claim on {node_id} by {claimant_id}",
        entity_id=node_id,
        payload={"claim_id": claim.id, "original_claimant_id": claim.claimant_id, "released_by": claimant_id, "reason": release_reason},
    )
    return claim.model_copy(update={"released_by": claimant_id, "release_reason": release_reason, "released_at": released_at})


def request_review(store: ProjectStore, node_id: str, *, requested_by: str, rationale: str, unassign: bool = False, gated_by: str | None = None) -> CandidateProofRecord:
    """Snapshot a node's working `proof.tex` for review (ADR-0010).

    The working sources are edited freely — in the node's studio, by agents —
    and never reviewed directly: this freezes every input of the proof, the
    node's working sources and the shared preamble, byte for byte, into a new
    `snapshots/v<N>/` with a manifest, never overwritten, and records the
    manifest's SHA-256 (ADR-0011 point 5). A change to any input is a new
    version; the same inputs as the snapshot under review are refused, unless
    that snapshot is missing or can't be read: then they are snapshotted afresh
    as the next version, a re-snapshot after loss (#99), which needs its own
    Human Review — decisions on the lost snapshot stay unverifiable.
    Needs the node's key-ideas summary, `key-ideas.md`, with its required fields filled in
    (KEY_IDEAS_REQUIRED): it is frozen with the proof, and a change to it alone is a new
    version (ADR-0013). Requesting review is how its author confirms a draft the agent wrote.
    Needs no claim. A node someone has claimed is theirs to hand over, and
    their claim ends here, as a wayfinder ticket's does when its work is.
    `unassign` is the researcher's request on a node someone else holds (the studio's
    Review what it has, spec #145): the holder's claim is ended in the same write, as an
    unassignment by `requested_by` — who may clear any claim (ADR-0010) — and the request
    is recorded as theirs, never as the holder's.
    """
    node = require_node(store, node_id)
    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE", f"imported_result node {node_id} has no proof to review; use Reference review instead"
        )
    if not rationale.strip():
        raise ProofMapError(
            "SCOPING_RATIONALE_REQUIRED",
            "requesting review requires stating why this node is now appropriately scoped to prove directly",
        )
    # the entry its Medium asks for (spec #145): a computation's run.sh, a LaTeX document's proof.tex
    entry = working_entry_path(store.root, node_id, node.medium)
    if not entry.is_file():
        computation = is_computation(node)
        raise ProofMapError(
            "RUN_SCRIPT_MISSING" if computation else "WORKING_PROOF_MISSING",
            f"{entry.relative_to(store.root).as_posix()} doesn't exist" + (": a computation node's review needs the program that is its candidate proof" if computation else ""),
        )
    # read once: what is hashed is exactly what is frozen, even if a file changes meanwhile.
    # The key-ideas summary is one of these inputs (ADR-0013): frozen, listed and hashed with
    # the proof, so a change to it alone is a new version, by the same unchanged-check below
    # A computation's inputs are frozen whole — its allowlisted environment files, its scripts'
    # executable bits; never a secret — and a file that can't be read, or a symbolic link, is
    # refused before anything is written
    try:
        snapshot = read_working_snapshot(store.root, node_id, node.medium)
    except (OSError, NodeFolderLinks) as exc:
        raise node_folder_error(store.root, node_id, exc, "a Review snapshot") from exc
    contents = snapshot.files
    _require_key_ideas(store, node_id, contents.get(key_ideas.KEY_IDEAS_FILE))
    sha256 = snapshot.digest()
    # The agent's gate, checked at the request itself (ADR-0019 point 3): a run's Prover names the passing verdict's
    # digest; files edited since — by anyone, in the same turn — are not what the Verifier passed, so nothing is frozen.
    # The researcher's own request names none and is never refused for this.
    if gated_by is not None and gated_by != sha256:
        raise ProofMapError(
            "VERDICT_STALE",
            f"the files of {node_id} are not the ones the Verifier passed: the verdict is about {gated_by[:12]}…, the folder now is {sha256[:12]}…; "
            "have the Verifier read them again before requesting review",
            details={"gated_by": gated_by, "working_sha256": sha256},
        )

    # The holder check and every write are one SQLite write transaction (#18): a reassignment
    # can't slip in between them, it waits for this to commit. The files written go if it rolls
    # back, before its write lock does, so no later request can have taken their version yet.
    with store.transaction() as conn:
        # The gate's second half, on the write lock (re-audit P1): the newest verdict must be a passing one on these very
        # files. Read here, a `failed` another process committed a moment ago is seen, and none can be committed before
        # this request is — BEGIN IMMEDIATE holds the lock from here to the commit.
        if gated_by is not None:
            newest = latest_verdict(store, node_id)
            if newest is None or newest.get("outcome") != "passed" or newest.get("inputs_sha256") != sha256 or newest.get("stale"):
                raise ProofMapError(
                    "VERDICT_STALE",
                    f"the newest verdict on {node_id} is not a passing one on these files"
                    + (f" (it {newest.get('outcome')} {str(newest.get('inputs_sha256') or '')[:12]}…"
                       + (", before a restatement of what it read the proof against)" if newest.get("stale") else ")") if newest else " (there is none)")
                    + "; have the Verifier read them again before requesting review",
                    details={"gated_by": gated_by, "working_sha256": sha256, "newest_verdict": newest},
                )
        claim = get_active_claim(store, node_id, conn=conn)
        unassigned = claim.claimant_id if claim is not None and claim.claimant_id != requested_by else None
        if unassigned is not None and not unassign:  # a node someone holds is theirs to hand over
            raise _not_claimant(node_id, claim)
        node = require_node(store, node_id)  # its dependencies as of the write lock, recorded with the snapshot
        current = get_current_candidate_proof(store, node_id, conn=conn)
        # refused only if nothing is new: the same files (ADR-0011), on the dependencies that
        # snapshot was made on (#96), and the snapshot itself still there to review. A missing or
        # unreadable one is taken afresh from an unchanged proof, a re-snapshot after loss, which
        # needs a Human Review of its own; its old decisions stay unverifiable (#99)
        unchanged = current is not None and current.sha256 == sha256 and _snapshot_dependencies_stand(store, node, current)
        lost = unchanged and candidate_proof_sha256(store, current.id) is None
        if unchanged and not lost:
            raise ProofMapError(
                "WORKING_PROOF_UNCHANGED",
                f"{node_id}'s working proof is unchanged since snapshot v{current.version}, which is already the one under review",
            )
        resnapshot_of = current.version if lost else None
        # who wrote the summary being frozen, from the drafts the studio recorded (not from the file)
        draft = latest_event(store, KEY_IDEAS_DRAFTED, node_id, conn=conn)
        drafted_by = key_ideas.provenance(contents[key_ideas.KEY_IDEAS_FILE], draft.payload.get("sha256") if draft else None)

        # past any snapshot already on disk too: one the index never got is an orphan, reported
        # by list_integrity_warnings, and never overwritten
        version = max([next_candidate_proof_version(store, node_id, conn=conn), *(n + 1 for n in snapshots_on_disk(store.root, node_id))])
        folder = snapshot_dir(store.root, node_id, version)
        pdf = archived_pdf_path(store.root, node_id, version)
        # listed before writing, so a write that fails partway still goes; and only if absent
        # now, under the write lock, so a rollback never removes a file this request didn't write
        ours = [p for p in (folder, pdf) if not p.exists()]
        on_rollback(store, lambda: [remove_snapshot(p) for p in ours])
        write_snapshot_folder(folder, snapshot)
        if build_is_current(store.root, node_id):
            # a PDF compiled from these very inputs (the studio's build): archived beside the snapshot
            shutil.copyfile(build_pdf_path(store.root, node_id), pdf)
        record = CandidateProofRecord(
            id=str(uuid.uuid4()),
            node_id=node_id,
            version=version,
            file_path=(folder / SNAPSHOT_MANIFEST).relative_to(store.root).as_posix(),
            submitted_by=requested_by,
            scoping_rationale=rationale,
            sha256=sha256,
            dependencies=list(node.dependencies),
            resnapshot_after_loss=resnapshot_of,
            key_ideas_drafted_by=drafted_by,
        )
        try:
            insert_candidate_proof(store, record, conn=conn)
        except sqlite3.IntegrityError as exc:
            raise ProofMapError("CANDIDATE_PROOF_VERSION_CONFLICT", f"version {version} of node {node_id} is already indexed") from exc

        pin_dependencies(store, node)
        if claim is not None:
            reason = f"unassigned by {requested_by}: review requested" if unassigned is not None else "review requested"
            mark_claim_released(store, claim.id, released_by=requested_by, reason=reason, released_at=utc_now(), conn=conn)
        append_event(
            store,
            "proof_map_review_requested",
            f"snapshot v{version} of {node_id} requested for review"
            + (f" (re-snapshot after loss of v{resnapshot_of})" if resnapshot_of is not None else ""),
            entity_id=node_id,
            payload={
                "candidate_proof_id": record.id,
                "version": version,
                "file_path": record.file_path,
                "sha256": sha256,
                "requested_by": requested_by,
                "unassigned": unassigned,  # whose claim this request ended, when it was not the requester's own
                "resnapshot_after_loss": resnapshot_of,
                # the summary's provenance: the author's, or the agent's draft confirmed or edited (ADR-0013)
                "key_ideas_drafted_by": drafted_by,
                # what the snapshot left out, by path only (ADR-0015): reported, never read
                "skipped_hidden": list(snapshot.skipped_hidden),
            },
            conn=conn,
        )
    return record


def node_folder_error(root: Path, node_id: str, exc: OSError | NodeFolderLinks, reader: str) -> ProofMapError:
    """The registered refusal for a node folder `reader` (a snapshot, an export) can't read whole:
    WORKING_FILE_UNREADABLE naming the path, or NODE_FOLDER_SYMLINK listing each link, dangling or not."""

    def shown(where: Path) -> str:
        return where.relative_to(root).as_posix() if where.is_relative_to(root) else str(where)

    if isinstance(exc, NodeFolderLinks):
        links = [{"path": shown(path), "dangling": dangling} for path, dangling in exc.links]
        listed = ", ".join(link["path"] + (" (dangling)" if link["dangling"] else "") for link in links)
        return ProofMapError(
            "NODE_FOLDER_SYMLINK",
            f"{listed}: {reader} follows no symbolic link, so nothing was written; replace each with the file "
            "it points to, or move it out of the node folder (scratch/ and build/ are never read)",
            details={"links": links},
        )
    path = shown(Path(exc.filename) if exc.filename else node_folder(root, node_id))
    return ProofMapError(
        "WORKING_FILE_UNREADABLE",
        f"{path} can't be read ({exc.strerror or exc}): {reader} reads every file it would carry, so nothing was written; "
        "make it readable, or move it out of the node folder (scratch/ and build/ are never read)",
        details={"path": path},
    )


def review_notices(store: ProjectStore, record: CandidateProofRecord) -> list[dict]:
    """What requesting review has to tell the researcher about the snapshot it froze, never a
    refusal: each a registered notice code (`errors.NOTICE_CODES`) with its message and data.
    SNAPSHOT_SKIPPED_HIDDEN when it left hidden files or folders out (by path, as the request
    recorded them; never their contents). SNAPSHOT_LARGE_OUTPUT when a computation froze more of
    `out/` than `[snapshot] large_output_mb` (default 50 MB), measured on the snapshot as stored
    (spec #145)."""
    notices: list[dict] = []
    requested = latest_event(store, "proof_map_review_requested", record.node_id)
    skipped = (requested.payload.get("skipped_hidden") or []) if requested and requested.payload.get("candidate_proof_id") == record.id else []
    if skipped:
        notices.append(notice(
            "SNAPSHOT_SKIPPED_HIDDEN",
            f"snapshot v{record.version} left out {len(skipped)} hidden path(s): {', '.join(skipped)}. Secrets (.env, .env.*, .envrc, "
            ".netrc), hidden folders and dotfiles other than the allowlisted environment files are never frozen",
            paths=list(skipped),
        ))
    node = get_proof_map_node(store, record.node_id)
    if node is None or not is_computation(node) or not record.file_path.endswith("/" + SNAPSHOT_MANIFEST):
        return notices
    size = frozen_output_bytes((store.root / record.file_path).parent)
    threshold = large_output_threshold(store.root)
    if size > threshold:
        notices.append(notice(
            "SNAPSHOT_LARGE_OUTPUT",
            f"snapshot v{record.version} froze {size / (1024 * 1024):.1f} MB of out/ (above {threshold / (1024 * 1024):g} MB): "
            "every review snapshot keeps a copy; keep in out/ what the review needs and .gitignore the rest",
            output_bytes=size,
            threshold_bytes=threshold,
        ))
    return notices


KEY_IDEAS_DRAFTED = "proof_map_key_ideas_drafted"


def record_key_ideas_draft(store: ProjectStore, node_id: str, *, agent: str, content: bytes) -> None:
    """Record that the proof agent `agent` wrote the node's working key-ideas.md as `content`
    (ADR-0013). The next review request compares what it freezes against this draft's SHA-256
    to say whether the summary is the agent's, confirmed by the author, or its draft edited."""
    require_node(store, node_id)
    append_event(
        store,
        KEY_IDEAS_DRAFTED,
        f"{agent} drafted the key ideas of {node_id}",
        entity_id=node_id,
        payload={"drafted_by": agent, "sha256": key_ideas.digest(content)},
    )


def _require_key_ideas(store: ProjectStore, node_id: str, data: bytes | None) -> key_ideas.KeyIdeas:
    """The node's working key-ideas summary, parsed; refused (KEY_IDEAS_REQUIRED) when it is
    missing or a required field is empty (ADR-0013): review starts from the key ideas."""
    path = (node_folder(store.root, node_id) / key_ideas.KEY_IDEAS_FILE).relative_to(store.root).as_posix()
    required = " and ".join(key_ideas.HEADINGS[key] for key in key_ideas.REQUIRED)
    if data is None:
        raise ProofMapError(
            "KEY_IDEAS_REQUIRED",
            f"{path} doesn't exist: requesting review needs the proof's key ideas, with {required} "
            "filled in (the studio's proof agent can draft it)",
            details={"path": path, "missing": [key_ideas.KEY_IDEAS_FILE]},
        )
    parsed = key_ideas.parse(data.decode("utf-8", errors="replace"))
    if parsed.missing:
        raise ProofMapError(
            "KEY_IDEAS_REQUIRED",
            f"{path} leaves {' and '.join(parsed.missing)} empty: {required} are both required",
            details={"path": path, "missing": parsed.missing},
        )
    return parsed


def get_candidate_proof(store: ProjectStore, candidate_proof_id: str) -> CandidateProofRecord | None:
    return _get_candidate_proof(store, candidate_proof_id)


def require_candidate_proof(store: ProjectStore, candidate_proof_id: str) -> CandidateProofRecord:
    record = get_candidate_proof(store, candidate_proof_id)
    if record is None:
        raise ProofMapError("CANDIDATE_PROOF_NOT_FOUND", f"candidate proof {candidate_proof_id} not found")
    return record


def list_candidate_proofs(store: ProjectStore, node_id: str) -> list[CandidateProofRecord]:
    require_node(store, node_id)
    return list_candidate_proofs_for_node(store, node_id)


def record_evidence_check(
    store: ProjectStore,
    candidate_proof_id: str,
    outcome: EvidenceOutcome | str,
    *,
    notes: str = "",
    run_by: str = "system",
    snapshot_sha256: str | None = None,
) -> EvidenceCheck:
    """Record an automated or semi-automated check against a specific Candidate proof.

    Purely advisory and ungated — an automated checker records its own
    outcome directly, no Human Review needed to log a result. Nothing here
    can close, block, or otherwise touch acceptance_state; the sole write
    is this check's own row (ADR-0004 point 5).

    The check is bound to a snapshot SHA-256, as a decision is. Given
    `snapshot_sha256` (the hash of the snapshot the checker ran on), it must be
    the snapshot's hash now, or the check is refused (EVIDENCE_SNAPSHOT_MISMATCH,
    naming the node's current snapshot). Omitted, the check is bound to the
    snapshot's hash at the moment of recording — which says what it was recorded
    against, not what the checker ran on.
    """
    proof = require_candidate_proof(store, candidate_proof_id)
    sha256 = candidate_proof_sha256(store, candidate_proof_id)
    if sha256 is None:  # it would bind nothing, and read as a check from before binding (PR #147)
        raise ProofMapError(
            "SNAPSHOT_UNREADABLE",
            f"snapshot v{proof.version} of {proof.node_id} is missing or can't be read, so an Evidence check on it "
            "would bind no snapshot hash: nothing was recorded",
        )
    if snapshot_sha256 is not None and snapshot_sha256 != sha256:
        current = get_current_candidate_proof(store, proof.node_id)
        now = f"hashes to {sha256[:12]}…"
        named = f"v{current.version} ({(candidate_proof_sha256(store, current.id) or 'unreadable')[:12]}…)" if current else "none"
        raise ProofMapError(
            "EVIDENCE_SNAPSHOT_MISMATCH",
            f"snapshot v{proof.version} of {proof.node_id} {now}, not {snapshot_sha256[:12]}…; "
            f"the node's current snapshot is {named}",
        )

    try:
        resolved_outcome = EvidenceOutcome(outcome)
    except ValueError as exc:
        valid = ", ".join(member.value for member in EvidenceOutcome)
        raise ProofMapError(
            "INVALID_OUTCOME", f"'{outcome}' is not a valid evidence outcome; expected one of: {valid}"
        ) from exc

    check = EvidenceCheck(
        id=str(uuid.uuid4()), candidate_proof_id=candidate_proof_id, outcome=resolved_outcome, notes=notes, run_by=run_by,
        candidate_proof_sha256=sha256,
    )
    insert_evidence_check(store, check)
    append_event(
        store,
        "proof_map_evidence_check_recorded",
        f"evidence check {resolved_outcome.value} for candidate proof {candidate_proof_id}",
        entity_id=candidate_proof_id,
        payload={"evidence_check_id": check.id, "outcome": resolved_outcome.value, "run_by": run_by, "candidate_proof_sha256": sha256},
    )
    return check


def evidence_binding(check: EvidenceCheck, snapshot_sha256_now: str | None) -> dict:
    """How an Evidence check's own bound hash reads against its snapshot as it is now: `matches`; `changed`
    (the snapshot no longer hashes to what the check was bound to); `unbound`, a check recorded before
    binding, never read as matching; or `unverifiable`, its snapshot can't be read."""
    bound = check.candidate_proof_sha256
    if bound is None:
        state, label = "unbound", "not bound (recorded before binding)"
    elif snapshot_sha256_now is None:
        state, label = "unverifiable", f"bound to {bound[:12]}…; the snapshot can't be read"
    elif bound == snapshot_sha256_now:
        state, label = "matches", f"bound to {bound[:12]}…"
    else:
        state, label = "changed", "snapshot changed since this check"
    return {"sha256": bound, "state": state, "label": label}


def get_evidence_check(store: ProjectStore, check_id: str) -> EvidenceCheck | None:
    return _get_evidence_check(store, check_id)


def require_evidence_check(store: ProjectStore, check_id: str) -> EvidenceCheck:
    check = get_evidence_check(store, check_id)
    if check is None:
        raise ProofMapError("EVIDENCE_CHECK_NOT_FOUND", f"evidence check {check_id} not found")
    return check


def list_evidence_checks(store: ProjectStore, candidate_proof_id: str) -> list[EvidenceCheck]:
    require_candidate_proof(store, candidate_proof_id)
    return list_evidence_checks_for_candidate_proof(store, candidate_proof_id)


class EvidenceTrustDecision(str, Enum):
    trusted = "trusted"
    unusable = "unusable"


_EVIDENCE_DECISION_TO_GOVERNANCE_STATE = {
    EvidenceTrustDecision.trusted: ReviewGovernanceState.trusted,
    EvidenceTrustDecision.unusable: ReviewGovernanceState.unusable,
}

_EVIDENCE_CHECK_OBJECT_TYPE = "evidence_check"


def decide_evidence_review(
    store: ProjectStore,
    evidence_check_id: str,
    decision: EvidenceTrustDecision | str,
    *,
    reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None,
) -> ReviewRecord:
    """Human Review's trust judgment on an Evidence check itself.

    Recorded in reviews.jsonl bound to the checked Candidate proof's
    snapshot (ADR-0010).

    `trusted` or `unusable` — never `approved`/`rejected`, and never
    against `object_type=proof_map_node`, so this can't be confused with,
    or feed, acceptance_state no matter what it decides (ADR-0004 point 5).
    """
    check = require_evidence_check(store, evidence_check_id)

    try:
        resolved_decision = EvidenceTrustDecision(decision)
    except ValueError as exc:
        valid = ", ".join(member.value for member in EvidenceTrustDecision)
        raise ProofMapError(
            "INVALID_DECISION", f"'{decision}' is not a valid evidence trust judgment; expected one of: {valid}"
        ) from exc

    governance_state = _EVIDENCE_DECISION_TO_GOVERNANCE_STATE[resolved_decision]
    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.evidence_review, target_id=evidence_check_id, decision=resolved_decision.value, reviewer=reviewer, rationale=rationale, viewed_binding=viewed_binding)
        record = _record(store, decided, _EVIDENCE_CHECK_OBJECT_TYPE, evidence_check_id, governance_state)
        append_event(
            store,
            "proof_map_evidence_review_decided",
            f"evidence review for {evidence_check_id}: {resolved_decision.value}",
            entity_id=check.candidate_proof_id,
            payload={"decision": resolved_decision.value, "reviewer_id": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def compute_interface_fingerprint(statement: str, assumptions: list[str], definitions: list[str] | tuple[str, ...] = ()) -> str:
    """SHA-256 hex digest over the canonical JSON pair `(statement, assumptions)`.

    That pair is the node's mathematical interface — what a dependent
    actually relies on. `kind` is deliberately left out: claim vs lemma is a
    label about reusability, and relabeling (Promote) must never read as an
    interface change to existing dependents (#22). Statement and each
    assumption are whitespace-normalized (trimmed, internal runs collapsed)
    first, so two statements differing only by whitespace produce the same
    fingerprint. "Mathematical scope" is treated as already captured within
    statement + assumptions for v1.

    A node written in Definitions (ADR-0020) has them in its interface too, by id: a decision fixes the definitions
    it relied on (ADR-0021 point 6), so under it an id stands for its text. A node that names none is spelled exactly as before.
    """
    parts: list = [_normalize_whitespace(statement), [_normalize_whitespace(a) for a in assumptions]]
    if definitions:
        parts.append(list(definitions))
    return _digest(parts)


def _digest(parts: list) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()


_FINGERPRINTED_KINDS = (ProofMapNodeKind.theorem, ProofMapNodeKind.lemma, ProofMapNodeKind.claim)


def _legacy_with_kind_fingerprint(kind: str, statement: str, assumptions: list[str]) -> str:
    """The fingerprint as it was computed before #22, with `kind` inside it."""
    return _digest([kind, _normalize_whitespace(statement), [_normalize_whitespace(a) for a in assumptions]])


def _same_interface(store: ProjectStore, node_id: str, left: str | None, right: str | None) -> bool:
    """Whether two stored fingerprints of `node_id` describe the same interface.

    Fingerprints stored before #22 included the node's `kind`, so existing
    projects hold several spellings of one interface: the current
    `(statement, assumptions)` form and a with-kind form per kind. Any two
    of those, for this node's statement and assumptions, are the same
    interface — which is also what repairs a pin broken by a pre-#22 Promote.
    """
    if left is None or right is None:
        return False
    if left == right:
        return True
    node = get_node(store, node_id)
    if node is None:
        return False
    spellings = {compute_interface_fingerprint(node.statement, node.assumptions, node.definitions)} | {
        _legacy_with_kind_fingerprint(kind.value, node.statement, node.assumptions) for kind in _FINGERPRINTED_KINDS
    }
    return left in spellings and right in spellings


def _interface_of(node: ProofMapNode) -> str:
    """What a decision about `node` binds as its mathematical interface.

    A local node: its interface fingerprint. An imported result: its
    statement and source, so a Reference review can't be carried over to a
    different citation behind the same id (#35 C), and the ReferenceRecord it
    links, by id only: editing that record's text leaves the review standing
    (issue #91). A node that links none is spelled as before the link existed."""
    if node.kind == ProofMapNodeKind.imported_result:
        fields = ["imported_result", _normalize_whitespace(node.statement), node.source_locator or "", node.source_version or ""]
        return _digest(fields + ([node.reference_id] if node.reference_id is not None else []))
    return compute_interface_fingerprint(node.statement, node.assumptions, node.definitions)


@memoized_read
def get_accepted_interface_fingerprint(store: ProjectStore, node_id: str) -> str | None:
    """The interface fingerprint of `node_id` if it is Accepted, else `None`.

    Recomputed from the node itself, never read off a stored column: an
    Acceptance only counts while the node still asserts exactly the
    interface that was accepted, so the two can't disagree (#35 C).
    """
    node = get_node(store, node_id)
    if node is None or get_acceptance_state(store, node_id) != "accepted":
        return None
    return compute_interface_fingerprint(node.statement, node.assumptions, node.definitions)


def pin_dependencies(store: ProjectStore, node: ProofMapNode) -> list[DependencyPin]:
    """Snapshot what each of `node`'s dependencies currently offers.

    Called on every Candidate proof submission, refreshing the pin to
    reflect what this particular submission was actually checked against.
    An `imported_result` target pins no version/fingerprint — it's
    immutable, so there's nothing to have moved on. A local target not yet
    Accepted pins `None` for both: nothing confirmed exists yet to check
    against. A pin whose edge is gone (a dependency removed or moved, #96)
    goes too, so the pins are exactly the node's dependencies.
    """
    for stale in list_dependency_pins_for_node(store, node.id):
        if stale.target_node_id not in node.dependencies:
            delete_dependency_pin(store, node.id, stale.target_node_id)
    pins: list[DependencyPin] = []
    for target_id in node.dependencies:
        target = get_node(store, target_id)
        if target is None:
            continue
        if target.kind == ProofMapNodeKind.imported_result:
            pinned_version, pinned_fingerprint = None, None
        else:
            pinned_fingerprint = get_accepted_interface_fingerprint(store, target_id)
            accepted = _accepted_proof(store, target_id) if pinned_fingerprint is not None else None
            pinned_version = accepted.version if accepted else None
        pin = DependencyPin(
            id=str(uuid.uuid4()),
            node_id=node.id,
            target_node_id=target_id,
            pinned_version=pinned_version,
            pinned_fingerprint=pinned_fingerprint,
        )
        pins.append(upsert_dependency_pin(store, pin))
    return pins


@memoized_read
def _signed_pins(store: ProjectStore, node_id: str) -> dict[str, PinnedDependency] | None:
    """For an Accepted node: the pins its counted Acceptance was made on,
    as later refreshed by verified Lightweight re-reviews. `None` for a node
    that isn't Accepted, whose pins are just what its submission recorded."""
    node = get_node(store, node_id)
    if node is None:
        return None
    state, latest, _ = _acceptance(store, node)
    if state != "accepted":
        return None
    pins = {pin.target_node_id: pin for pin in latest.verdict.payload.dependency_pins}
    for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewRecordKind.dependency_revalidation.value):
        if row["seq"] <= latest.row["seq"]:
            continue
        verdict = verify_decision_row(store, row["id"])
        if verdict.status == "verified":
            pins.update({pin.target_node_id: pin for pin in verdict.payload.dependency_pins})
    return pins


@memoized_read
def get_dependency_pin(store: ProjectStore, node_id: str, target_node_id: str) -> DependencyPin | None:
    """The pin as it counts. For an Accepted node that's the signed pin, not
    the `dependency_pins` row, which a direct edit could change (#35 C)."""
    stored = _get_dependency_pin(store, node_id, target_node_id)
    signed = (_signed_pins(store, node_id) or {}).get(target_node_id)
    if signed is None:
        return stored
    return DependencyPin(
        id=stored.id if stored else f"signed:{node_id}:{target_node_id}",
        node_id=node_id,
        target_node_id=target_node_id,
        pinned_version=signed.pinned_version,
        pinned_fingerprint=signed.pinned_fingerprint,
    )


def list_dependency_pins(store: ProjectStore, node_id: str) -> list[DependencyPin]:
    require_node(store, node_id)
    return [get_dependency_pin(store, node_id, pin.target_node_id) for pin in list_dependency_pins_for_node(store, node_id)]


def dependency_pin_is_current(store: ProjectStore, pin: DependencyPin) -> bool:
    """Whether a pinned dependency's interface still matches what the target now offers.

    Compared by fingerprint, never by version number: a target can move to
    a new Accepted version whose interface fingerprint is unchanged (a
    proof-only revision), and that must read as still current, not stale.
    """
    target = get_node(store, pin.target_node_id)
    if target is None or target.kind == ProofMapNodeKind.imported_result:
        return True
    current_fingerprint = get_accepted_interface_fingerprint(store, pin.target_node_id)
    return _same_interface(store, pin.target_node_id, pin.pinned_fingerprint, current_fingerprint)


def dependency_pin_lags(store: ProjectStore, pin: DependencyPin) -> bool:
    """Whether a pin is behind its target's accepted version (#23): the target has moved on to
    a new Accepted version since the dependent was checked against it, even with the same
    interface. The same rule as the page's Lightweight re-review remedy; an imported result
    has no versions, so it never lags."""
    target = get_node(store, pin.target_node_id)
    if target is None or target.kind == ProofMapNodeKind.imported_result:
        return False
    accepted = get_accepted_version(store, pin.target_node_id)
    return accepted is not None and pin.pinned_version != accepted


class AcceptanceDecision(str, Enum):
    """The only three ways a local node's acceptance_state may ever change.

    Nothing else in the system — not a claim, not a submission, not an
    Evidence check — is allowed to write acceptance_state; `decide_acceptance`
    is the sole entry point, and it always requires explicit human
    confirmation. See ADR (Human Acceptance Authority).
    """

    accept = "accept"
    revision_requested = "revision-requested"
    reject = "reject"


_ACCEPTANCE_DECISION_TO_GOVERNANCE_STATE = {
    AcceptanceDecision.accept: ReviewGovernanceState.approved,
    AcceptanceDecision.revision_requested: ReviewGovernanceState.revision_requested,
    AcceptanceDecision.reject: ReviewGovernanceState.rejected,
}

_ACCEPTANCE_OBJECT_TYPE = "proof_map_node"


def _pin_remedy(pin: DependencyPin | None, *, current: bool | None, accepted_version: int | None) -> str | None:
    """What a lagging or changed pin needs: a Lightweight re-review, or a new Candidate proof (#23, #24)."""
    if pin is None:
        return None
    if current is False:
        return "new-candidate-proof"
    if accepted_version is not None and pin.pinned_version != accepted_version:
        return "lightweight-re-review"
    return None


def dependency_details(store: ProjectStore, node_id: str) -> list[dict]:
    """Each of a node's dependencies as the node page and `node show --json` show it (#97):
    its statement and kind, the pin as it counts, the version now Accepted, whether the pin
    is still current, and the remedy a lagging or changed pin needs."""
    node = require_node(store, node_id)
    details = []
    for dependency_id in node.dependencies:
        pin = get_dependency_pin(store, node_id, dependency_id)
        dependency = get_node(store, dependency_id)
        accepted_version = get_accepted_version(store, dependency_id)
        current = dependency_pin_is_current(store, pin) if pin else None
        details.append(
            {
                "node_id": dependency_id,
                "statement": dependency.statement if dependency else None,
                # where the dependency opens: a studio, or an imported result's own page
                "kind": dependency.kind.value if dependency else None,
                "pin": pin.model_dump(mode="json") if pin else None,
                # the pin lag a Lightweight re-review is about (#23/#24)
                "accepted_version": accepted_version,
                "current": current,
                "remedy": _pin_remedy(pin, current=current, accepted_version=accepted_version),
                # an imported result depended on by rule rather than by a review (ADR-0014)
                "trust_rule": trust_rules_of(store, dependency_id) if dependency and dependency.kind == ProofMapNodeKind.imported_result else [],
            }
        )
    return details


def _require_awaiting_acceptance_review(store: ProjectStore, node_id: str) -> None:
    """A decision only ever answers a Candidate proof awaiting review.

    `rejected` is terminal (story 24), and a Blocked node's decision waits
    for its dependencies (NODE_BLOCKED, ADR-0021 point 1). Otherwise the node
    must read `review-needed`: that one state already excludes a node with no
    Candidate proof (`open`), one under an active claim (`claimed`), and a
    second decision on a submission that was already decided
    (`open`/`revision-requested`).
    """
    if get_acceptance_state(store, node_id) == "rejected":
        raise ProofMapError(
            "NODE_REJECTED", f"node {node_id} was Rejected; that decision is permanent and can't be revisited"
        )
    node = require_node(store, node_id)
    if not _already_accepted(store, node) and _has_unresolved_dependency(store, node):
        # Blocked holds back the decision, never the work: the snapshot waits for its dependencies (ADR-0021 point 1)
        unsettled = [dependency_id for dependency_id in node.dependencies if not _dependency_satisfied(store, dependency_id)]
        raise ProofMapError(
            "NODE_BLOCKED",
            f"node {node_id} is Blocked: {', '.join(unsettled)} isn't Accepted (or Reference-reviewed) yet; "
            "decide what it rests on first",
            details={"unsettled": unsettled, "awaiting_decision": _awaiting_decision(store, node) is not None},
        )
    workflow_state = get_workflow_state(store, node_id)
    if workflow_state != "review-needed":
        raise ProofMapError(
            "NOT_REVIEW_NEEDED",
            f"node {node_id} is {workflow_state}, not review-needed; "
            "a Human Review decision only applies to a submitted Candidate proof awaiting review",
            details={"workflow_state": workflow_state},
        )
    current = snapshot_with_changed_dependencies(store, node_id)
    if current is not None:
        # the snapshot was made on other dependencies: deciding it would accept a proof of a different node
        raise ProofMapError(
            "DEPENDENCIES_CHANGED",
            f"{node_id}'s dependencies changed since snapshot v{current.version} was requested for review; request review again",
        )


def snapshot_with_changed_dependencies(store: ProjectStore, node_id: str) -> CandidateProofRecord | None:
    """The node's current snapshot if its dependencies changed since it was requested for review, else None.

    The one rule by which an Acceptance decision on it is refused (DEPENDENCIES_CHANGED), and by which
    the proof map page offers none (#156).
    """
    current = get_current_candidate_proof(store, node_id)
    if current is not None and not _snapshot_dependencies_stand(store, require_node(store, node_id), current):
        return current
    return None


def _snapshot_dependencies_stand(store: ProjectStore, node: ProofMapNode, snapshot: CandidateProofRecord) -> bool:
    """Whether `node`'s dependencies are still those `snapshot` was requested for review on (#96).

    Read off the snapshot's own record, which no dependency edit touches —
    not off the pins, which removing an edge deletes along with it. A
    snapshot from before the record was kept falls back to its pins. A
    withdrawn citation the researcher moved this node off (a counted
    `dependent_migration`, #20) reads as its correction: re-Accepting the
    same snapshot against the correction is exactly what that decision asks.
    """
    recorded = snapshot.dependencies
    if recorded is None:
        recorded = [pin.target_node_id for pin in list_dependency_pins_for_node(store, node.id)]
    return {_migrated(store, node.id, dependency_id) for dependency_id in recorded} == set(node.dependencies)


def _migrated(store: ProjectStore, node_id: str, dependency_id: str) -> str:
    """Where counted Dependent migrations moved `node_id`'s edge on `dependency_id` (itself if none did)."""
    seen = {dependency_id}
    while True:
        moved_to = None
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, dependency_id, ReviewRecordKind.dependent_migration.value):
            verdict = verify_decision_row(store, row["id"])
            if verdict.status == "verified" and node_id in verdict.payload.migrated_dependents and verdict.payload.dependency_pins:
                moved_to = verdict.payload.dependency_pins[0].target_node_id
        if moved_to is None or moved_to in seen:
            return dependency_id
        seen.add(moved_to)
        dependency_id = moved_to


def decide_acceptance(
    store: ProjectStore,
    node_id: str,
    decision: AcceptanceDecision | str,
    *,
    reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None,
) -> ReviewRecord:
    """Record a Human Review acceptance decision for a local node.

    Only for a node in `review-needed`, and never once it's `rejected` (see
    `_require_awaiting_acceptance_review`). Recorded in the node's
    reviews.jsonl, bound to the current snapshot's SHA-256 and the node's
    dependency pins, and committed as the reviewer's git identity
    (ADR-0010); it counts only while it still describes the node.

    `revision_requested` keeps the node open for another claim/submit cycle
    on the same node id, never a new node. `reject` is permanent: the node
    and this decision remain in the project forever, and this function never
    touches `ProjectState.failed_routes` — once a node exists for a route,
    the node's own history is the record of it, never both.
    """
    node = require_node(store, node_id)

    if node.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE",
            f"imported_result node {node_id} is judged by Reference review, not Acceptance",
        )

    try:
        resolved_decision = AcceptanceDecision(decision)
    except ValueError as exc:
        valid = ", ".join(member.value for member in AcceptanceDecision)
        raise ProofMapError(
            "INVALID_DECISION", f"'{decision}' is not a valid acceptance decision; expected one of: {valid}"
        ) from exc

    governance_state = _ACCEPTANCE_DECISION_TO_GOVERNANCE_STATE[resolved_decision]
    # the review rows, the candidate-proof link and fingerprint, the
    # Challenges it resolves and the events all commit together or not at
    # all: a decision interrupted part-way leaves the node exactly as it was.
    with store.transaction() as conn:
        # checked on the write lock, so no concurrent decision or submission
        # can land between the check and the write
        _require_awaiting_acceptance_review(store, node_id)
        decided = _decide(store, kind=DecisionKind.acceptance, target_id=node_id, decision=resolved_decision.value, reviewer=reviewer, rationale=rationale, viewed_binding=viewed_binding)
        current_proof = get_current_candidate_proof(store, node_id)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, governance_state)
        if current_proof is not None:
            set_candidate_proof_review_record_id(store, current_proof.id, record.id, conn=conn)
            if resolved_decision == AcceptanceDecision.accept:
                fingerprint = compute_interface_fingerprint(node.statement, node.assumptions, node.definitions)
                set_candidate_proof_interface_fingerprint(store, current_proof.id, fingerprint, conn=conn)

        _resolve_open_challenges(
            store,
            node_id,
            resolved_by=decided.reviewer_id,
            review_id=record.id,
            challenge_ids=decided.payload.resolves_challenges,
            conn=conn,
        )

        append_event(
            store,
            "proof_map_acceptance_decided",
            f"acceptance decision for {node_id}: {resolved_decision.value}",
            entity_id=node_id,
            payload={"decision": resolved_decision.value, "reviewer_id": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return record


def _pins_of(store: ProjectStore, node_id: str) -> list[PinnedDependency]:
    return [
        PinnedDependency(
            target_node_id=pin.target_node_id, pinned_version=pin.pinned_version, pinned_fingerprint=pin.pinned_fingerprint
        )
        for pin in list_dependency_pins_for_node(store, node_id)
    ]


def _refreshed_pin(store: ProjectStore, target_node_id: str) -> PinnedDependency:
    """What a Lightweight re-review re-pins a dependency to: its current accepted version and interface."""
    fingerprint = get_accepted_interface_fingerprint(store, target_node_id)
    accepted = _accepted_proof(store, target_node_id) if fingerprint is not None else None
    return PinnedDependency(
        target_node_id=target_node_id,
        pinned_version=accepted.version if accepted else None,
        pinned_fingerprint=fingerprint,
    )


def _current_proof_id(store: ProjectStore, node_id: str) -> str | None:
    current = get_current_candidate_proof(store, node_id)
    return current.id if current else None


def decision_binding(
    store: ProjectStore,
    kind: DecisionKind,
    target_id: str,
    *,
    dependency_id: str | None = None,
) -> dict[str, Any]:
    """What a decision of `kind` on `target_id` is made on, as of now.

    The Candidate proof (its id; `authority` adds the SHA-256 of its
    snapshot), the node's accepted mathematical interface, the dependency
    pins the reviewer is deciding against, and the open Challenges an
    Acceptance or Reference review resolves.
    """
    none = {"candidate_proof_id": None, "interface_fingerprint": None, "dependency_pins": [], "resolves_challenges": []}
    if kind in (DecisionKind.acceptance, DecisionKind.promote):
        node = require_node(store, target_id)
        return {
            "candidate_proof_id": _current_proof_id(store, target_id),
            "interface_fingerprint": _interface_of(node),
            "dependency_pins": _pins_of(store, target_id),
            "resolves_challenges": _open_challenge_ids(store, target_id) if kind == DecisionKind.acceptance else [],
        }
    if kind == DecisionKind.reference_review:
        node = require_node(store, target_id)
        return {**none, "interface_fingerprint": _interface_of(node), "resolves_challenges": _open_challenge_ids(store, target_id)}
    if kind == DecisionKind.dependency_revalidation:
        if dependency_id is None:
            raise ProofMapError("DEPENDENCY_REQUIRED", "a Lightweight re-review names the dependency it re-pins")
        node = require_node(store, target_id)
        return {
            **none,
            "candidate_proof_id": _current_proof_id(store, target_id),
            "interface_fingerprint": _interface_of(node),
            "dependency_pins": [_refreshed_pin(store, dependency_id)],
        }
    if kind == DecisionKind.evidence_review:
        check = require_evidence_check(store, target_id)
        proof = require_candidate_proof(store, check.candidate_proof_id)
        return {**none, "candidate_proof_id": proof.id, "interface_fingerprint": _interface_of(require_node(store, proof.node_id))}
    if kind == DecisionKind.challenge_resolution:
        challenge = require_challenge(store, target_id)
        return {**none, "interface_fingerprint": _interface_of(require_node(store, challenge.target_node_id))}
    if kind == DecisionKind.dependent_migration:
        # the withdrawn citation, the exact correction its dependents move onto, and which dependents
        if dependency_id is None:
            raise ProofMapError("REPLACEMENT_REQUIRED", "moving dependents names the imported result they move onto")
        replacement = require_node(store, dependency_id)
        return {
            **none,
            "interface_fingerprint": _interface_of(require_node(store, target_id)),
            "dependency_pins": [PinnedDependency(target_node_id=replacement.id, pinned_fingerprint=_interface_of(replacement))],
            "migrated_dependents": [node.id for node in list_migratable_dependents(store, target_id)],
        }
    if kind == DecisionKind.trust_rule:
        # a rule binds nothing on the map: it is judged against the citations as they are whenever it is read (ADR-0014)
        return dict(none)
    raise ProofMapError("INVALID_DECISION_KIND", f"{kind.value} is not a proof-map decision")


def prepare_decision(
    store: ProjectStore,
    kind: DecisionKind | str,
    target_id: str,
    decision: str,
    *,
    rationale: str = "",
    dependency_id: str | None = None,
) -> DecisionPayload:
    """What a decision would be made on right now, for a page to show before the researcher decides. Decides nothing."""
    try:
        resolved_kind = DecisionKind(kind)
    except ValueError as exc:
        raise ProofMapError("INVALID_DECISION_KIND", f"'{kind}' is not a decision kind") from exc
    return build_decision_payload(
        store, resolved_kind, target_id, decision, rationale=rationale, **decision_binding(store, resolved_kind, target_id, dependency_id=dependency_id)
    )


def apply_decision(
    store: ProjectStore,
    kind: DecisionKind | str,
    target_id: str,
    decision: str,
    *,
    reviewer: str | None = None,
    rationale: str = "",
    dependency_id: str | None = None,
    viewed_binding: str | None = None,
    conditions: list | None = None,
) -> Any:
    """Make one Human Review decision by kind: the proof map page's single entry point (ADR-0010).

    `viewed_binding`: what the page showed (`binding_digest`); see `_decide`.
    `conditions`: a Trust rule's conditions, for a `trust_rule` declare or amend (ADR-0014)."""
    try:
        resolved_kind = DecisionKind(kind)
    except ValueError as exc:
        raise ProofMapError("INVALID_DECISION_KIND", f"'{kind}' is not a decision kind") from exc
    if resolved_kind == DecisionKind.trust_rule:
        # a rule binds nothing the page could have shown stale: no viewed binding (ADR-0014)
        return decide_trust_rule(store, target_id, decision, conditions=conditions, reviewer=reviewer, rationale=rationale)
    who = {"reviewer": reviewer, "rationale": rationale, "viewed_binding": viewed_binding}
    if resolved_kind == DecisionKind.acceptance:
        return decide_acceptance(store, target_id, decision, **who)
    if resolved_kind == DecisionKind.reference_review:
        return decide_reference_review(store, target_id, decision, **who)
    if resolved_kind == DecisionKind.evidence_review:
        return decide_evidence_review(store, target_id, decision, **who)
    if resolved_kind == DecisionKind.dependency_revalidation:
        return revalidate_dependency(store, target_id, dependency_id or "", **who)
    if resolved_kind == DecisionKind.challenge_resolution:
        return dismiss_challenge(store, target_id, **who)
    if resolved_kind == DecisionKind.promote:
        return promote_to_lemma(store, target_id, **who)
    if resolved_kind == DecisionKind.dependent_migration:
        return migrate_dependents(store, target_id, dependency_id or "", **who)
    raise ProofMapError("UNSUPPORTED_DECISION", f"{resolved_kind.value} decisions aren't applied here")


@dataclass
class _Counted:
    """The newest decision row on a node for one kind, and what it's worth."""

    row: dict
    verdict: RowVerdict

    @property
    def decision(self) -> ReviewGovernanceState:
        return ReviewGovernanceState(self.row["decision"])


def _latest_decision(store: ProjectStore, node_id: str, kind: ReviewRecordKind) -> _Counted | None:
    rows = [
        row
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, kind.value)
        if row["decision"] != ReviewGovernanceState.proposed_for_review.value
    ]
    if not rows:
        return None
    return _Counted(rows[-1], verify_decision_row(store, rows[-1]["id"]))


def _binding_problem(store: ProjectStore, node: ProofMapNode, payload: DecisionPayload) -> str | None:
    """Why a verified decision no longer applies to `node` as it stands, or None."""
    proof = _get_candidate_proof(store, payload.candidate_proof_id) if payload.candidate_proof_id else None
    if proof is None or proof.node_id != node.id:
        return "it was made on a Candidate proof that isn't this node's"
    current = candidate_proof_sha256(store, proof.id)
    if current is None:
        return "the snapshot it was decided on is missing or can't be read"
    if not snapshot_matches(payload.candidate_proof_sha256, current):
        return "the snapshot's text changed after it was decided on"
    if payload.interface_fingerprint != _interface_of(node):
        return "the node's statement or assumptions changed after it was decided on"
    if set(node.dependencies) != {pin.target_node_id for pin in payload.dependency_pins}:
        return "the node's dependencies changed after it was decided on"
    if payload.key_ideas_drafted_by != proof.key_ideas_drafted_by:
        return "the snapshot's key-ideas provenance changed after it was decided on"
    return None


def _acceptance(store: ProjectStore, node: ProofMapNode) -> tuple[str, _Counted | None, str | None]:
    """(acceptance_state, the newest acceptance decision, why it doesn't count).

    Only the *newest* decision is ever read (B): if it doesn't verify, the
    node reads `unverifiable` — never an older decision it superseded. A
    Reject is terminal, and bound to the node, not to the proof text: a
    later edit never reopens a Rejected node.
    """
    rows = [
        row
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node.id, ReviewRecordKind.acceptance.value)
        if row["decision"] != ReviewGovernanceState.proposed_for_review.value
    ]
    if not rows:
        return "unreviewed", None, None
    # Reject is terminal, so legitimately nothing ever follows one: any
    # Reject row keeps the node rejected, even if something (a replay, a
    # forged row) was appended after it.
    reject = next((row for row in reversed(rows) if row["decision"] == ReviewGovernanceState.rejected.value), None)
    if reject is not None:
        verdict = verify_decision_row(store, reject["id"])
        return "rejected", _Counted(reject, verdict), None if verdict.status == "verified" else verdict.reason
    latest = _Counted(rows[-1], verify_decision_row(store, rows[-1]["id"]))
    if latest.verdict.status != "verified":
        return "unverifiable", latest, latest.verdict.reason
    problem = _binding_problem(store, node, latest.verdict.payload)
    if problem is not None:
        return "unverifiable", latest, problem
    if latest.decision == ReviewGovernanceState.approved:
        return "accepted", latest, None
    return "unreviewed", latest, None


@memoized_read
def _accepted_proof(store: ProjectStore, node_id: str) -> CandidateProofRecord | None:
    """The Candidate proof an Accepted node's counted Acceptance was made on."""
    node = get_node(store, node_id)
    if node is None:
        return None
    state, latest, _ = _acceptance(store, node)
    if state != "accepted":
        return None
    return _get_candidate_proof(store, latest.verdict.payload.candidate_proof_id)


def get_accepted_version(store: ProjectStore, node_id: str) -> int | None:
    """The version of the Candidate proof a node's counted Acceptance names, or None if it isn't Accepted."""
    proof = _accepted_proof(store, node_id)
    return proof.version if proof else None


@memoized_read
@read_scoped
def get_acceptance_state(store: ProjectStore, node_id: str) -> str:
    """The node's acceptance_state, computed from its recorded Human Review decisions.

    One of `unreviewed`, `accepted`, `rejected`, `unverifiable` — never
    stored, always re-derived from the *newest* `kind=acceptance` decision
    (see `_acceptance`). An Acceptance counts only while it still describes
    this node: the Candidate proof it was made on is this node's and its
    text is unchanged, and the node still asserts the accepted interface. That accepted proof may be an
    earlier version while a newer one awaits review (the workflow axis then
    reads `review-needed`).
    """
    return _acceptance(store, require_node(store, node_id))[0]


def acceptance_overview(store: ProjectStore) -> list[tuple[ProofMapNode, str, str | None]]:
    """(node, acceptance_state, why its newest decision doesn't count) for every node, by id.

    The same computation as `get_acceptance_state`, done once per node: what a
    handoff reports as accepted is exactly what the map calls accepted (#45).
    """
    overview = []
    for node in sorted(list_nodes(store), key=lambda node: node.id):
        state, _, reason = _acceptance(store, node)
        overview.append((node, state, reason))
    return overview


def decision_node_id(store: ProjectStore, review_id: str) -> str | None:
    """The node whose reviews.jsonl records Human Review decision `review_id`, or None if there's no such decision."""
    row = next((row for row in list_decisions(store) if row["id"] == review_id), None)
    if row is None:
        return None
    try:
        return _node_folder(store, row["object_type"], row["object_id"])
    except ProofMapError:
        return None


def promote_to_lemma(
    store: ProjectStore, node_id: str, *, reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None
) -> ProofMapNode:
    """Promote an Accepted Claim to a Lemma, marking it independently reusable.

    The researcher's explicit decision, never automatic, recorded as its
    own review decision (ADR-0010). Only
    available for `kind=claim` nodes that are already Accepted and not under
    an open Challenge (a node whose soundness is in question isn't something
    to advertise as reusable); there is no demote. Every field but `kind` is
    unchanged — the Candidate-proof history and the interface fingerprint
    included, since `kind` isn't part of the interface (#22): every
    dependent's pin stays current across a promotion.
    """
    node = require_node(store, node_id)

    if node.kind != ProofMapNodeKind.claim:
        raise ProofMapError("NOT_A_CLAIM", f"node {node_id} is kind={node.kind.value}, not claim; only a claim can be promoted")

    if get_acceptance_state(store, node_id) != "accepted":
        raise ProofMapError("NOT_ACCEPTED", f"node {node_id} must be Accepted before it can be promoted to Lemma")

    if has_open_challenge(store, node_id):
        raise ProofMapError(
            "NODE_CHALLENGED", f"node {node_id} is under an open Challenge; resolve it before promoting to Lemma"
        )

    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.promote, target_id=node_id, decision="promote", reviewer=reviewer, rationale=rationale, viewed_binding=viewed_binding)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.approved)
        promoted = node.model_copy(
            update={"kind": ProofMapNodeKind.lemma, "updated_by": decided.reviewer_id, "updated_at": utc_now()}
        )
        update_proof_map_node(store, promoted, conn=conn)
        append_event(
            store,
            "proof_map_node_promoted",
            f"promoted {node_id} from claim to lemma",
            entity_id=node_id,
            payload={"promoted_by": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    return promoted


REFERENCE_REVIEW_DECISION = "reference-review"
# the citation was found wanting: terminal, like a Reject — a corrected source is a new node (#20, #38)
REFERENCE_NOT_CALLABLE_DECISION = "no-longer-callable"
REFERENCE_REVIEW_DECISIONS = (REFERENCE_REVIEW_DECISION, REFERENCE_NOT_CALLABLE_DECISION)


def decide_reference_review(
    store: ProjectStore,
    node_id: str,
    decision: str,
    *,
    reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None,
) -> ReviewRecord:
    """Grant Reference review to an imported_result node (a `reference_review` decision, ADR-0010).

    Judges the trustworthiness of a citation — never the node's
    acceptance_state, which stays `unreviewed` for every imported_result
    node forever; it is Reference-reviewed or it isn't, independently of
    Acceptance (see ADR on imported results / story 22).
    """
    node = require_node(store, node_id)

    if node.kind != ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "NOT_IMPORTED_RESULT",
            f"node {node_id} is not an imported_result; use Human Review acceptance instead",
        )

    if decision not in REFERENCE_REVIEW_DECISIONS:
        raise ProofMapError(
            "INVALID_DECISION",
            f"'{decision}' is not a valid reference review decision; expected one of: {', '.join(REFERENCE_REVIEW_DECISIONS)}",
        )
    if _no_longer_callable(store, node_id):
        raise ProofMapError(
            "REFERENCE_NOT_CALLABLE",
            f"{node_id} is no longer callable, and that is final; cite a corrected source as a new imported_result node",
        )
    not_callable = decision == REFERENCE_NOT_CALLABLE_DECISION
    if not not_callable and _citation_missing(store, node):
        raise ProofMapError(
            "REFERENCE_NOT_FOUND",
            f"{node_id} cites reference {node.reference_id}, which does not exist here; a review of it couldn't count",
        )

    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.reference_review, target_id=node_id, decision=decision, reviewer=reviewer, rationale=rationale, viewed_binding=viewed_binding)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.rejected if not_callable else ReviewGovernanceState.approved)
        _resolve_open_challenges(
            store,
            node_id,
            resolved_by=decided.reviewer_id,
            review_id=record.id,
            challenge_ids=decided.payload.resolves_challenges,
            conn=conn,
        )
        append_event(
            store,
            "proof_map_no_longer_callable" if not_callable else "proof_map_reference_review_granted",
            f"{node_id} is no longer callable" if not_callable else f"reference review granted for {node_id}",
            entity_id=node_id,
            payload={"reviewer_id": decided.reviewer_id, "review_id": record.id},
            conn=conn,
        )
    # other citations of the same source may now meet `source already reviewed` (ADR-0014)
    note_trust_rule_matches(store)
    return record


def list_migratable_dependents(store: ProjectStore, node_id: str) -> list[ProofMapNode]:
    """The nodes resting on `node_id` that moving dependents would move: all but the Rejected, the record of an abandoned route."""
    return [
        node
        for node in list_nodes(store)
        if node_id in node.dependencies and get_acceptance_state(store, node.id) != "rejected"
    ]


def migrate_dependents(
    store: ProjectStore,
    node_id: str,
    replacement_id: str,
    *,
    reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None,
) -> ReviewRecord:
    """Move the dependents of a no-longer-callable imported result onto its correction (#20, ADR-0005 Rule 1).

    A Human Review decision (`dependent_migration`, recorded as `superseded`
    in the withdrawn node's reviews.jsonl), made on the proof map page: a
    corrected source is a new imported_result node, and what rested on the
    old one moves deliberately, never by inheriting the correction. Every
    dependent but a Rejected one has the old id swapped for the new one in
    its dependencies, and its pin moved with it. An Accepted dependent's
    Acceptance was made against the withdrawn citation, so it stops counting
    (`unverifiable`, DECISION_NO_LONGER_APPLIES) and the node reads
    review-needed until the researcher re-Accepts it against the correction.
    """
    # everything — the checks, which dependents, the payload naming them, the writes — under one
    # write lock, so a concurrent split or new dependent is neither overwritten nor misrecorded
    with store.transaction() as conn:
        node = require_node(store, node_id)
        replacement = require_node(store, replacement_id)
        if node.kind != ProofMapNodeKind.imported_result:
            raise ProofMapError("NOT_IMPORTED_RESULT", f"{node_id} is not an imported_result; only a withdrawn citation's dependents move")
        if replacement.kind != ProofMapNodeKind.imported_result:
            raise ProofMapError(
                "REPLACEMENT_NOT_IMPORTED_RESULT", f"{replacement_id} is not an imported_result; a corrected source is cited as a new one"
            )
        if replacement_id == node_id:
            raise ProofMapError("SAME_NODE", f"{node_id} can't replace itself")
        if not _no_longer_callable(store, node_id):
            raise ProofMapError(
                "REFERENCE_STILL_CALLABLE", f"{node_id} is still callable; its dependents move only once it is found no longer callable"
            )
        if _no_longer_callable(store, replacement_id):
            raise ProofMapError("REPLACEMENT_NOT_CALLABLE", f"{replacement_id} is itself no longer callable")
        dependents = list_migratable_dependents(store, node_id)
        if not dependents:
            raise ProofMapError("NO_DEPENDENTS", f"nothing that can move rests on {node_id}")

        decided = _decide(
            store, kind=DecisionKind.dependent_migration, target_id=node_id, decision="superseded",
            reviewer=reviewer, rationale=rationale, dependency_id=replacement_id, viewed_binding=viewed_binding)
        decided.payload.migrated_dependents = [dependent.id for dependent in dependents]  # the very nodes moved below
        for dependent in dependents:
            moved = list(dict.fromkeys(replacement_id if dependency == node_id else dependency for dependency in dependent.dependencies))
            update_proof_map_node(
                store, dependent.model_copy(update={"dependencies": moved, "updated_by": decided.reviewer_id, "updated_at": utc_now()}), conn=conn
            )
            if get_dependency_pin(store, dependent.id, node_id) is not None:
                # an imported result pins no version: the pin just follows the edge
                delete_dependency_pin(store, dependent.id, node_id, conn=conn)
                upsert_dependency_pin(store, DependencyPin(id=str(uuid.uuid4()), node_id=dependent.id, target_node_id=replacement_id), conn=conn)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.superseded)
        append_event(
            store,
            "proof_map_dependents_migrated",
            f"moved {len(dependents)} dependent(s) of {node_id} onto {replacement_id}",
            entity_id=node_id,
            payload={"replacement_id": replacement_id, "dependents": [d.id for d in dependents], "review_id": record.id},
            conn=conn,
        )
    return record


@memoized_read
def _no_longer_callable(store: ProjectStore, node_id: str) -> bool:
    """Whether any Reference review row says `no-longer-callable`: terminal however it's recorded, like a Reject."""
    return any(
        row["decision"] == ReviewGovernanceState.rejected.value
        for row in decision_rows(store, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewRecordKind.reference_review.value)
    )


def _citation_missing(store: ProjectStore, node: ProofMapNode) -> bool:
    return node.reference_id is not None and get_reference(store, node.reference_id) is None


def node_citation(store: ProjectStore, node: ProofMapNode) -> dict[str, Any] | None:
    """The citation an imported result links, as its page, review card and `node show` show it (issue #91).

    The ReferenceRecord's title, authors, year, identifier and url, beside the
    node's own source locator and version. `missing` when the linked record
    doesn't exist here (deleted, or not carried by an exchange bundle).
    `None` for a node that links no reference."""
    if node.reference_id is None:
        return None
    reference = get_reference(store, node.reference_id)
    return {
        "reference_id": node.reference_id,
        "missing": reference is None,
        "title": reference.title if reference else None,
        "authors": list(reference.authors) if reference else [],
        "year": reference.year if reference else None,
        "identifier": reference.identifier if reference else None,
        "url": reference.url if reference else None,
        "locator": node.source_locator,
        "version": node.source_version,
    }


@memoized_read
def _explicit_reference_review(store: ProjectStore, node_id: str) -> str:
    """`unreviewed`, `reviewed`, `unverifiable` or `no-longer-callable`, from the newest `kind=reference_review`
    decision alone: the researcher's explicit decision on this node, never a Trust rule.

    Counts only while the imported result still cites what was reviewed
    (statement and source) — never acceptance_state. Once found
    wanting, an imported result stays `no-longer-callable`.
    """
    node = require_node(store, node_id)
    if _no_longer_callable(store, node_id):
        return "no-longer-callable"
    latest = _latest_decision(store, node_id, ReviewRecordKind.reference_review)
    if latest is None:
        return "unreviewed"
    if latest.verdict.status != "verified" or latest.verdict.payload.interface_fingerprint != _interface_of(node):
        return "unverifiable"
    if _citation_missing(store, node):
        # the review was made on a citation that is gone (issue #91)
        return "unverifiable"
    return "reviewed" if latest.decision == ReviewGovernanceState.approved else "unreviewed"


@memoized_read
@read_scoped
def get_reference_review_state(store: ProjectStore, node_id: str) -> str:
    """An imported result's Reference review state: `no-longer-callable`, `reviewed`, `trusted-by-rule`,
    `unverifiable` or `unreviewed`, in that order of precedence (ADR-0014 point 2).

    The explicit decision comes first: `no-longer-callable` is final, and a
    counting Reference review wins over any rule. Otherwise a citation that
    meets a Trust rule in force reads `trusted-by-rule` — derived here every
    time, never stored — ahead of an explicit decision that no longer counts,
    since a rule judges the citation as it is now.
    """
    explicit = _explicit_reference_review(store, node_id)
    if explicit in ("no-longer-callable", "reviewed"):
        return explicit
    if trust_rules_of(store, node_id):
        return "trusted-by-rule"
    return explicit


@memoized_read
@read_scoped
def trust_rules_of(store: ProjectStore, node_id: str, *, rules: list[TrustRule] | None = None) -> list[str]:
    """The names of every Trust rule an imported result meets right now (ADR-0014), in declaration order.

    A pure function of the rules in force (or `rules`, to preview a change),
    the node, its citation as it stands, and the *explicit* Reference review
    state of the other citations of the same reference. Empty for a local
    node, a node with no citation, and a node found no longer callable.
    """
    node = require_node(store, node_id)
    if node.kind != ProofMapNodeKind.imported_result or node.reference_id is None:
        return []
    in_force = list_trust_rules(store) if rules is None else [rule for rule in rules if not rule.retired]
    if not in_force or _no_longer_callable(store, node_id):
        return []
    reference = get_reference(store, node.reference_id)
    if reference is None:
        return []
    siblings = [
        SiblingCitation(node_id=other.id, source_version=other.source_version, explicit_state=_explicit_reference_review(store, other.id))
        for other in list_nodes(store)
        if other.kind == ProofMapNodeKind.imported_result and other.id != node.id and other.reference_id == node.reference_id
    ] if any(condition.kind == TrustConditionKind.source_already_reviewed for rule in in_force for condition in rule.conditions) else []
    return [rule.name for rule in in_force if rule_matches(rule, source_version=node.source_version, reference=reference, siblings=siblings)]


def decide_trust_rule(
    store: ProjectStore,
    name: str,
    decision: str,
    *,
    conditions: list | None = None,
    reviewer: str | None = None,
    rationale: str = "",
) -> TrustRuleDecision:
    """Declare, amend or retire a Trust rule: a Human Review decision on the project's trust-rules.jsonl (ADR-0014).

    Made only on the proof map page. The checks (a name that is free, or a
    rule that exists and isn't retired; at least one condition; a rationale)
    and the write happen under one write lock; the line is committed as the
    reviewer's git identity once it has landed. Nothing is written on the
    nodes the rule covers: their state follows from the rule set in force.
    """
    with store.transaction():
        try:
            resolved = check_rule_decision(store, name, decision, conditions=conditions, rationale=rationale)
            record = record_rule_decision(store, name, decision, conditions=resolved, reviewer=reviewer, rationale=rationale)
        except TrustRuleError as exc:
            raise ProofMapError(exc.code, exc.message) from exc
    note_trust_rule_matches(store)
    return record


def trust_rule_impact(store: ProjectStore, name: str, *, conditions: list | None = None) -> dict[str, list[str]]:
    """What retiring rule `name` (or amending it to `conditions`) would do, for the page to show before recording.

    `losing`: the imported results that read trusted-by-rule now and would not
    afterwards; `depended_on_by_accepted`: those of them an Accepted node rests
    on (its Acceptance keeps, ADR-0014 point 4); `gaining`: nodes that would
    newly read trusted-by-rule. A preview only: it records nothing and binds
    nothing.
    """
    with read_scope():
        rule = get_trust_rule(store, name)
        if rule is None:
            raise ProofMapError("TRUST_RULE_NOT_FOUND", f"no trust rule is named {name}")
        if conditions is None:
            changed = rule.model_copy(update={"retired": True})
        else:
            try:
                changed = rule.model_copy(update={"conditions": parse_conditions(conditions)})
            except TrustRuleError as exc:
                raise ProofMapError(exc.code, exc.message) from exc
        hypothetical = [changed if other.name == name else other for other in list_trust_rules(store)]
        nodes = list_nodes(store)
        losing: list[str] = []
        gaining: list[str] = []
        for node in nodes:
            if node.kind != ProofMapNodeKind.imported_result:
                continue
            now = get_reference_review_state(store, node.id)
            if now not in ("trusted-by-rule", "unreviewed", "unverifiable"):
                continue
            after = bool(trust_rules_of(store, node.id, rules=hypothetical))
            if now == "trusted-by-rule" and not after:
                losing.append(node.id)
            elif now != "trusted-by-rule" and after:
                gaining.append(node.id)
        depended = [
            node_id for node_id in losing
            if any(node_id in other.dependencies and get_acceptance_state(store, other.id) == "accepted" for other in nodes)
        ]
        return {"losing": losing, "depended_on_by_accepted": depended, "gaining": gaining}


def trust_rule_view(store: ProjectStore, rule: TrustRule) -> dict[str, Any]:
    """A rule as the CLI and the page's sheet show it: its record, its conditions in words, and the nodes it trusts right now."""
    trusting = [
        node.id for node in list_nodes(store)
        if node.kind == ProofMapNodeKind.imported_result
        and get_reference_review_state(store, node.id) == "trusted-by-rule"
        and rule.name in trust_rules_of(store, node.id)
    ]
    return {**rule.model_dump(mode="json"), "conditions_text": rule.describe_conditions(), "trusting": trusting}


_TRUSTED_BY_RULE_EVENT = "proof_map_trusted_by_rule"


def trust_rule_events(store: ProjectStore, node_id: str | None = None) -> list[EventRecord]:
    """When each imported result first met which rule (ADR-0014 point 2): informational events, oldest first."""
    return [
        event for event in list_events(store)
        if event.kind == _TRUSTED_BY_RULE_EVENT and (node_id is None or event.entity_id == node_id)
    ]


def note_trust_rule_matches(store: ProjectStore, node_ids: list[str] | None = None) -> list[EventRecord]:
    """Record the first time a node meets a rule, as an event and never a decision.

    Called after the writes that can make a citation start meeting a rule: a
    rule declared or amended, an imported result created, a Reference review
    decided. Reading a node's state never writes; a node that met the same rule
    before is not noted again.
    """
    with read_scope():
        wanted = set(node_ids) if node_ids is not None else None
        noted: dict[str, set[str]] = {}
        for event in trust_rule_events(store):
            noted.setdefault(event.entity_id or "", set()).add(str(event.payload.get("rule")))
        events = []
        for node in list_nodes(store):
            if node.kind != ProofMapNodeKind.imported_result or (wanted is not None and node.id not in wanted):
                continue
            for rule in trust_rules_of(store, node.id):
                if rule in noted.get(node.id, set()):
                    continue
                events.append(append_event(
                    store, _TRUSTED_BY_RULE_EVENT, f"{node.id} is trusted by rule {rule}", entity_id=node.id, payload={"rule": rule}
                ))
    return events


def revalidate_dependency(
    store: ProjectStore,
    node_id: str,
    target_node_id: str,
    *,
    reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None,
) -> ReviewRecord:
    """Lightweight re-review: confirm an existing Candidate proof still holds after a dependency advanced.

    Recorded as a `dependency_revalidation` decision whose pins are exactly
    the refreshed pin this writes (ADR-0010).

    Only available when the pin lags the target's accepted version (#23;
    otherwise `PIN_NOT_LAGGING`), and when the target's interface fingerprint hasn't changed
    since it was last pinned — if it has, the old Candidate proof no longer
    demonstrably accounts for the new premise, and a whole new Candidate
    proof is required instead (`INTERFACE_CHANGED`). Records
    `kind=dependency_revalidation, decision=reaffirmed` — deliberately
    distinct from `approved` so it can never be misread as a fresh
    Acceptance of `node_id` itself — and refreshes the dependency edge's
    pin to the target's current accepted version and fingerprint.

    The pin refresh and the review rows are written in one SQLite
    transaction: neither lands without the other.
    """
    node = require_node(store, node_id)
    target = require_node(store, target_node_id)

    if target_node_id not in node.dependencies:
        raise ProofMapError(
            "NOT_A_DEPENDENCY", f"{target_node_id} is not a dependency of {node_id}"
        )

    if target.kind == ProofMapNodeKind.imported_result:
        raise ProofMapError(
            "IMMUTABLE_NODE",
            f"{target_node_id} is an imported_result; it has no accepted-version history to revalidate against",
        )

    pin = get_dependency_pin(store, node_id, target_node_id)
    if pin is None:
        raise ProofMapError(
            "NO_DEPENDENCY_PIN",
            f"{node_id} has never pinned {target_node_id}; submit a Candidate proof first",
        )

    current_fingerprint = get_accepted_interface_fingerprint(store, target_node_id)
    if current_fingerprint is None:
        raise ProofMapError(
            "TARGET_NOT_ACCEPTED", f"{target_node_id} is not currently Accepted; nothing to revalidate against"
        )

    if not _same_interface(store, target_node_id, pin.pinned_fingerprint, current_fingerprint):
        raise ProofMapError(
            "INTERFACE_CHANGED",
            f"{target_node_id}'s accepted interface changed since {node_id} last pinned it; "
            "a new Candidate proof is required, lightweight re-review is not available",
        )
    if not dependency_pin_lags(store, pin):
        # nothing moved since the pin: a re-review would reaffirm nothing (#24)
        raise ProofMapError(
            "PIN_NOT_LAGGING",
            f"{node_id}'s pin on {target_node_id} already names its accepted version; there is nothing to re-review",
        )

    refreshed = _refreshed_pin(store, target_node_id)
    new_version = refreshed.pinned_version
    old_pin = pin

    refreshed_pin = DependencyPin(
        id=pin.id,
        node_id=node_id,
        target_node_id=target_node_id,
        pinned_version=new_version,
        pinned_fingerprint=current_fingerprint,
    )
    with store.transaction() as conn:
        decided = _decide(store, kind=DecisionKind.dependency_revalidation, target_id=node_id, decision="reaffirmed", reviewer=reviewer, rationale=rationale, dependency_id=target_node_id, viewed_binding=viewed_binding)
        upsert_dependency_pin(store, refreshed_pin, conn=conn)
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, ReviewGovernanceState.reaffirmed)
        append_event(
            store,
            "proof_map_dependency_revalidated",
            f"revalidated {node_id}'s dependency on {target_node_id}",
            entity_id=node_id,
            payload={
                "target_node_id": target_node_id,
                "old_pinned_version": old_pin.pinned_version,
                "new_pinned_version": new_version,
                "review_id": record.id,
            },
            conn=conn,
        )
    return record


def open_challenge(store: ProjectStore, target_node_id: str, *, opened_by: str = "human", rationale: str = "") -> Challenge:
    """Raise a Challenge against an already-Accepted (or Reference-reviewed) node.

    Ungated: any agent or collaborator may open one, no confirmation, no
    permission check — raising a concern is not a mathematical judgment
    ("this deserves a second look," not "this is wrong"), so it needs no
    gate the way resolving one does (ADR-0005 Rule 4).
    """
    node = require_node(store, target_node_id)

    if node.kind == ProofMapNodeKind.imported_result:
        # a node trusted by rule is depended on as a reviewed one is, so it can be Challenged as one (ADR-0014)
        if get_reference_review_state(store, target_node_id) not in ("reviewed", "trusted-by-rule"):
            raise ProofMapError(
                "TARGET_NOT_REVIEWED",
                f"{target_node_id} has not been Reference-reviewed yet; nothing to Challenge",
            )
    elif get_acceptance_state(store, target_node_id) != "accepted":
        raise ProofMapError(
            "TARGET_NOT_ACCEPTED",
            f"{target_node_id} is not Accepted; a Challenge only makes sense against a result someone might depend on",
        )

    challenge = Challenge(
        id=str(uuid.uuid4()),
        target_node_id=target_node_id,
        rationale=rationale,
        opened_by=opened_by,
    )
    with store.transaction() as conn:
        insert_challenge(store, challenge, conn=conn)
        append_event(
            store,
            "proof_map_challenge_opened",
            f"challenge opened against {target_node_id} by {opened_by}",
            entity_id=target_node_id,
            payload={"challenge_id": challenge.id, "opened_by": opened_by, "rationale": rationale},
            conn=conn,
        )
    return challenge




def _derived_challenges(store: ProjectStore) -> list[Challenge]:
    """Every Challenge, with its status as it counts.

    Resolved by a recorded decision that names it; one dismissed before
    ADR-0010 with no such decision behind it keeps its stored status.
    """
    return [_with_resolution(store, challenge) for challenge in _list_challenges(store)]


def _challenge_outcome(row: dict) -> ChallengeStatus:
    """How the decision `row` ended the Challenges it names (#25)."""
    if row["kind"] == ReviewRecordKind.challenge_resolution.value:
        return ChallengeStatus.dismissed
    approved = row["decision"] == ReviewGovernanceState.approved.value
    if row["kind"] == ReviewRecordKind.reference_review.value:
        return ChallengeStatus.dismissed if approved else ChallengeStatus.upheld
    return ChallengeStatus.resolved_by_revision if approved else ChallengeStatus.upheld


def _with_resolution(store: ProjectStore, challenge: Challenge) -> Challenge:
    row = challenge_resolution(store, challenge.id)
    if row is not None:
        return challenge.model_copy(
            update={
                "status": _challenge_outcome(row),
                "resolved_by": row["reviewer_id"],
                "resolved_at": datetime.fromisoformat(row["created_at"]),  # the row holds a string (#159)
                "resolution_review_id": row["review_id"],
                "resolution_rationale": verify_decision_row(store, row["id"]).payload.rationale,
            }
        )
    if challenge.status == ChallengeStatus.dismissed and challenge.resolution_review_id is None:
        return challenge  # dismissed before ADR-0010, with nothing recorded behind it: it stays closed
    return challenge.model_copy(update={"status": ChallengeStatus.open, "resolved_by": None, "resolved_at": None, "resolution_review_id": None})


def get_challenge(store: ProjectStore, challenge_id: str) -> Challenge | None:
    return next((challenge for challenge in _derived_challenges(store) if challenge.id == challenge_id), None)


def require_challenge(store: ProjectStore, challenge_id: str) -> Challenge:
    challenge = get_challenge(store, challenge_id)
    if challenge is None:
        raise ProofMapError("CHALLENGE_NOT_FOUND", f"challenge {challenge_id} not found")
    return challenge


def list_challenges(store: ProjectStore, *, target_node_id: str = "", status: str = "") -> list[Challenge]:
    return [
        challenge
        for challenge in _derived_challenges(store)
        if (not target_node_id or challenge.target_node_id == target_node_id)
        and (not status or challenge.status.value == status)
    ]


def _open_challenge_ids(store: ProjectStore, node_id: str) -> list[str]:
    return [challenge.id for challenge in list_challenges(store, target_node_id=node_id, status="open")]


@memoized_read
def has_open_challenge(store: ProjectStore, node_id: str) -> bool:
    return bool(list_challenges(store, target_node_id=node_id, status="open"))


def _resolve_open_challenges(
    store: ProjectStore,
    node_id: str,
    *,
    resolved_by: str,
    review_id: str,
    challenge_ids: list[str],
    conn: sqlite3.Connection,
) -> None:
    """Dismiss every open Challenge against `node_id`, as resolved by review `review_id`.

    Called from `decide_acceptance` and `decide_reference_review`: per
    ADR-0005 Rule 4, only Human Review resolves a Challenge, either by an
    explicit `challenge dismiss` or by directly addressing the concern —
    revising and re-Accepting a local node, or reaffirming trust in an
    Imported result's Reference review. Without this, a Challenge-driven
    reclaim (`claim_node`'s one sanctioned way to revise an Accepted node)
    would leave the node permanently `challenged` even after the concern was
    addressed.

    Runs on the deciding review's own transaction (`conn`). What resolves
    them is the recorded decision itself, which lists `challenge_ids` in its
    payload; marking the `challenges` rows here only keeps that advisory
    table in step.
    """
    resolved_at = utc_now()
    for challenge in [_get_challenge(store, challenge_id) for challenge_id in challenge_ids]:
        if challenge is None:
            continue
        reopened = challenge.status != ChallengeStatus.open
        if mark_challenge_dismissed(
            store,
            challenge.id,
            resolved_by=resolved_by,
            resolved_at=resolved_at,
            resolution_review_id=review_id,
            reopened=reopened,
            conn=conn,
        ):
            append_event(
                store,
                "proof_map_challenge_dismissed",
                f"challenge {challenge.id} dismissed by {resolved_by} (resolved via review decision)",
                entity_id=node_id,
                payload={"challenge_id": challenge.id, "reviewer_id": resolved_by, "review_id": review_id},
                conn=conn,
            )


def dismiss_challenge(
    store: ProjectStore,
    challenge_id: str,
    *,
    reviewer: str | None = None, rationale: str = "", viewed_binding: str | None = None,
) -> Challenge:
    """Dismiss a Challenge — Human Review only: a `challenge_resolution` decision (ADR-0010).

    Nothing un-sets `potentially-stale`/`challenged` by hand: both are
    computed fresh from the set of *open* Challenges (and stale pins) on
    every read, so dismissing one simply removes it from that set — every
    overlay it alone was causing clears itself the next time anyone asks.
    """
    challenge = require_challenge(store, challenge_id)
    if challenge.status != ChallengeStatus.open:
        raise ProofMapError("CHALLENGE_NOT_OPEN", f"challenge {challenge_id} is already {challenge.status.value}")

    resolved_at = utc_now()
    with store.transaction() as conn:
        # re-read on the write lock: a concurrent dismissal may have landed
        if require_challenge(store, challenge_id).status != ChallengeStatus.open:
            raise ProofMapError("CHALLENGE_NOT_OPEN", f"challenge {challenge_id} is already dismissed")
        decided = _decide(store, kind=DecisionKind.challenge_resolution, target_id=challenge_id, decision="dismissed", reviewer=reviewer, rationale=rationale, viewed_binding=viewed_binding)
        record = _record(store, decided, "challenge", challenge_id, ReviewGovernanceState.dismissed)
        mark_challenge_dismissed(
            store,
            challenge_id,
            resolved_by=decided.reviewer_id,
            resolved_at=resolved_at,
            resolution_review_id=record.id,
            reopened=True,
            conn=conn,
        )
        append_event(
            store,
            "proof_map_challenge_dismissed",
            f"challenge {challenge_id} dismissed by {decided.reviewer_id}",
            entity_id=challenge.target_node_id,
            payload={
                "challenge_id": challenge_id,
                "reviewer_id": decided.reviewer_id,
                "rationale": decided.payload.rationale,
                "review_id": record.id,
            },
            conn=conn,
        )
    return challenge.model_copy(
        update={
            "status": ChallengeStatus.dismissed,
            "resolved_by": decided.reviewer_id,
            "resolved_at": resolved_at,
            "resolution_review_id": record.id,
        }
    )


@dataclass
class UpstreamVisits:
    """How many nodes the integrity walk expanded (read its dependencies) while counted (#108)."""

    count: int = 0


_UPSTREAM_VISITS: ContextVar[UpstreamVisits | None] = ContextVar("proof_cli_upstream_visits", default=None)


@contextmanager
def counting_upstream_visits() -> Iterator[UpstreamVisits]:
    """Count the upstream walk's node visits for the duration: a machine-independent cost of a read."""
    counter = UpstreamVisits()
    token = _UPSTREAM_VISITS.set(counter)
    try:
        yield counter
    finally:
        _UPSTREAM_VISITS.reset(token)


def _visited_upstream() -> None:
    counter = _UPSTREAM_VISITS.get()
    if counter is not None:
        counter.count += 1


# How much each upstream cause weighs: a Challenge outranks a stale pin, which outranks nothing.
_CAUSE_RANK = {None: 0, "stale": 1, "challenged": 2}


def _worse(a: str | None, b: str | None) -> str | None:
    return a if _CAUSE_RANK[a] >= _CAUSE_RANK[b] else b


def _own_cause(store: ProjectStore, node_id: str) -> str | None:
    """What `node_id` itself starts, never looking further up: `"challenged"` for an open
    Challenge on it or an Imported result found no longer callable, `"stale"` for one of its own
    dependency edges pinned to an interface its target no longer offers, or behind its target's
    accepted version (#23), else None."""
    _visited_upstream()
    if has_open_challenge(store, node_id):
        return "challenged"
    node = get_node(store, node_id)
    if node is None:
        return None
    if node.kind == ProofMapNodeKind.imported_result and _no_longer_callable(store, node_id):
        return "challenged"  # a citation found wanting: whatever rests on it needs a second look
    for dependency_id in node.dependencies:
        pin = get_dependency_pin(store, node_id, dependency_id)
        if pin is not None and (not dependency_pin_is_current(store, pin) or dependency_pin_lags(store, pin)):
            return "stale"
    return None


_UPSTREAM_CAUSES = "upstream_cause"


def _upstream_cause(store: ProjectStore, node_id: str) -> str | None:
    """What makes `node_id` unsettled upstream: `"challenged"` if it is itself Challenged, or
    reachable (via dependency edges, transitively) from a Challenged node or a citation found
    no longer callable; `"stale"` if it is reachable only from a dependency edge whose pin no
    longer matches its target's accepted interface, or lags its accepted version (#23); else None.

    Pure graph reachability over persisted Challenge and DependencyPin records — nothing is
    stored per node. See ADR-0004 point 4.

    One topological pass per read (#108): a depth-first walk in dependency order that records
    each node's cause in the read scope's memo, so a dependent asked about later reuses its
    dependencies' causes instead of walking above them again. Over a whole map, every node is
    visited once per read. Walked with an explicit stack, not recursion: a long-running
    project's dependency chain can run hundreds of nodes deep, well past Python's default
    recursion limit.
    """
    memo: dict[str, str | None] = scoped_memo(store, _UPSTREAM_CAUSES)
    if node_id in memo:
        return memo[node_id]

    # the path being walked: each node, its dependencies still to see, and the worst cause so far
    stack: list[list] = []
    on_path: set[str] = set()

    def challenged() -> str:
        for path_id, _, _ in stack:  # nothing outranks a Challenge: everything on the path has it
            memo[path_id] = "challenged"
        return "challenged"

    def enter(current_id: str) -> bool:
        """Visit a node; whether its own cause already settles the answer (a Challenge)."""
        own = _own_cause(store, current_id)
        if own == "challenged":
            memo[current_id] = own
            return True
        node = get_node(store, current_id)
        stack.append([current_id, iter(node.dependencies if node is not None else []), own])
        on_path.add(current_id)
        return False

    if enter(node_id):
        return "challenged"
    while stack:
        top = stack[-1]
        current_id, dependencies, cause = top
        dependency_id = next(dependencies, None)
        if dependency_id is None:  # every dependency seen: its cause is settled
            stack.pop()
            on_path.discard(current_id)
            memo[current_id] = cause
            if stack:
                stack[-1][2] = _worse(stack[-1][2], cause)
            continue
        if dependency_id in memo:
            if memo[dependency_id] == "challenged":
                return challenged()
            top[2] = _worse(cause, memo[dependency_id])
            continue
        if dependency_id in on_path:
            # A dependency cycle, which no service creates: answer by plain reachability instead.
            for path_id, _, _ in stack:
                memo.pop(path_id, None)
            return _reachable_cause(store, node_id)
        if enter(dependency_id):
            return challenged()
    return memo[node_id]


def _reachable_cause(store: ProjectStore, node_id: str) -> str | None:
    """Plain reachability from `node_id`: the worst cause any node it reaches starts, remembering nothing."""
    visited: set[str] = set()
    pending = [node_id]
    worst: str | None = None
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        worst = _worse(worst, _own_cause(store, current_id))
        if worst == "challenged":
            return worst
        node = get_node(store, current_id)
        if node is not None:
            pending.extend(node.dependencies)
    return worst


def _is_downstream_of_challenge_or_stale_pin(store: ProjectStore, node_id: str) -> bool:
    """Whether anything upstream of `node_id` unsettles it: a Challenge, a withdrawn citation, a
    stale or lagging pin (see `_upstream_cause`)."""
    return _upstream_cause(store, node_id) is not None


@memoized_read
def _dependency_satisfied(store: ProjectStore, dependency_id: str) -> bool:
    """Whether a dependency has reached the standing that unblocks its dependents.

    For a local node that's Acceptance; for an imported_result that's
    Reference review. A dangling dependency id can't happen through
    `create_node` (it validates dependencies exist), so a missing node here
    is treated as satisfied rather than as a block this axis can't explain.

    Also false whenever the dependency is itself Challenged, or reachable
    from a Challenge/stale pin further upstream — an Accepted-but-Challenged
    dependency is not something a *new* dependent should treat as settled
    (ADR-0004 point 4: a not-yet-accepted node downstream of a Challenge
    reads `blocked`, same underlying cause, distinct reason).
    """
    dependency = get_node(store, dependency_id)
    if dependency is None:
        return True
    if dependency.kind == ProofMapNodeKind.imported_result:
        # a Reference review, or a Trust rule standing in for one (ADR-0014)
        reached_standing = get_reference_review_state(store, dependency_id) in ("reviewed", "trusted-by-rule")
    else:
        reached_standing = get_acceptance_state(store, dependency_id) == "accepted"
    if not reached_standing:
        return False
    return not _is_downstream_of_challenge_or_stale_pin(store, dependency_id)


def _has_unresolved_dependency(store: ProjectStore, node: ProofMapNode) -> bool:
    return any(not _dependency_satisfied(store, dependency_id) for dependency_id in node.dependencies)


def _already_accepted(store: ProjectStore, node: ProofMapNode) -> bool:
    return node.kind != ProofMapNodeKind.imported_result and get_acceptance_state(store, node.id) == "accepted"


def _awaiting_decision(store: ProjectStore, node: ProofMapNode) -> CandidateProofRecord | None:
    """The node's current snapshot if no counting Human Review decision covers it yet, else None.

    Covered means the newest decision's *recorded payload* names the current
    Candidate proof. Never the `review_record_id` column (advisory, and a
    direct edit could point it anywhere), never timestamps. A decision that
    doesn't count covers nothing, so the proof awaits the researcher afresh.
    A Rejected node awaits nothing. Read apart from Blocked, which hides it on
    the workflow axis but no longer holds the work back (ADR-0021 point 1).
    """
    if node.kind == ProofMapNodeKind.imported_result:
        return None
    current_proof = get_current_candidate_proof(store, node.id)
    if current_proof is None:
        return None
    state, latest, _ = _acceptance(store, node)
    if state == "rejected":
        return None
    covered = latest is not None and state != "unverifiable" and latest.verdict.payload.candidate_proof_id == current_proof.id
    return None if covered else current_proof


@read_scoped
def awaiting_decision(store: ProjectStore, node_id: str) -> CandidateProofRecord | None:
    """The node's snapshot awaiting a Human Review decision, Blocked or not, or None (ADR-0021 point 1): what the
    review queue and the Coordinator read where the workflow axis shows `blocked`."""
    return _awaiting_decision(store, require_node(store, node_id))


@memoized_read
@read_scoped
def get_workflow_state(store: ProjectStore, node_id: str) -> str:
    """One of `open`, `claimed`, `review-needed`, `revision-requested`, `blocked`.

    Always recomputed from the claim, candidate-proof, review, and
    dependency records — never read off a stored field, so it can never
    drift out of sync with what actually happened. `blocked` overrides every
    other workflow value but is a separate axis from acceptance/integrity,
    not a priority ladder across all three — and, per ADR-0004's note on
    ADR-0002, never overrides an already-Accepted node either: a Challenge
    or a stale dependency opened against an Accepted node's own dependency
    shows up on the integrity axis (`potentially-stale`), not by reverting
    this node's own already-settled workflow state to `blocked`.
    """
    node = require_node(store, node_id)

    if not _already_accepted(store, node) and _has_unresolved_dependency(store, node):
        return "blocked"

    if get_active_claim(store, node_id) is not None:
        return "claimed"

    if node.kind == ProofMapNodeKind.imported_result:
        # no claim/submit/Candidate-proof cycle exists for this kind; Reference
        # review governs it independently and doesn't move this axis.
        return "open"

    state, latest, _ = _acceptance(store, node)
    if state == "rejected":
        return "open"  # terminal: nothing further happens on a Rejected node
    if _awaiting_decision(store, node) is not None:
        return "review-needed"
    if latest is not None and state != "unverifiable" and latest.decision == ReviewGovernanceState.revision_requested:
        return "revision-requested"

    return "open"


@memoized_read
@read_scoped
def get_blocked_reason(store: ProjectStore, node_id: str) -> str | None:
    """Why `get_workflow_state` reads `blocked`, or `None` if it doesn't.

    `dependency-challenged` when an unresolved dependency is itself
    Challenged or downstream of a Challenge; `dependency-stale` when it is
    downstream only of a stale or lagging pin (#23) — both distinct from the
    ordinary `not-accepted` case of a dependency simply not having reached
    Acceptance/Reference-review yet.
    """
    node = require_node(store, node_id)
    if _already_accepted(store, node) or not _has_unresolved_dependency(store, node):
        return None
    for dependency_id in node.dependencies:
        dependency = get_node(store, dependency_id)
        if dependency is not None and dependency.kind == ProofMapNodeKind.imported_result and _no_longer_callable(store, dependency_id):
            return "dependency-not-callable"
    stale = False
    for dependency_id in node.dependencies:
        if _dependency_satisfied(store, dependency_id):
            continue
        cause = _upstream_cause(store, dependency_id)
        if cause == "challenged":
            return "dependency-challenged"
        stale = stale or cause == "stale"
    return "dependency-stale" if stale else "not-accepted"


# The run's Evidence check for a passing verdict is recorded as `<agent name>/verifier` (ADR-0019 point 4)
VERIFIER_CHECK_SUFFIX = "/verifier"


def _verifier_passed(store: ProjectStore, proof: CandidateProofRecord) -> bool:
    """Whether the Verifier's passing verdict was recorded on this very snapshot, and the researcher hasn't found
    that check unusable (an evidence review decision, ADR-0004 point 5)."""
    for check in list_evidence_checks_for_candidate_proof(store, proof.id):
        if check.outcome != EvidenceOutcome.passed or not check.run_by.endswith(VERIFIER_CHECK_SUFFIX):
            continue
        if check.candidate_proof_sha256 is None or check.candidate_proof_sha256 != proof.sha256:
            continue
        reviews = decision_rows(store, _EVIDENCE_CHECK_OBJECT_TYPE, check.id, ReviewRecordKind.evidence_review.value)
        if reviews and reviews[-1]["decision"] == ReviewGovernanceState.unusable.value:
            continue
        return True
    return False


@memoized_read
@read_scoped
def is_provisional(store: ProjectStore, node_id: str) -> bool:
    """Whether an unaccepted node may be rested on for work, never for trust (ADR-0021 point 2).

    A Theorem, Lemma or Claim whose current snapshot awaits a decision, on the
    dependencies it was made on, with the Verifier's pass recorded on it; or an
    imported result not yet Reference-reviewed (nor found no longer callable).
    A node under an open Challenge, or resting on a node the researcher sent
    back, is not: the support it was worked on is gone.
    """
    node = get_node(store, node_id)
    if node is None:
        return False
    if node.kind == ProofMapNodeKind.imported_result:
        return get_reference_review_state(store, node_id) in ("unreviewed", "unverifiable")
    if get_acceptance_state(store, node_id) == "accepted" or has_open_challenge(store, node_id):
        return False
    proof = _awaiting_decision(store, node)
    if proof is None or not _snapshot_dependencies_stand(store, node, proof) or not _verifier_passed(store, proof):
        return False
    # a restatement since the snapshot leaves the Verifier's pass about other text (ADR-0021 point 6)
    return not _support_withdrawn(store, node_id) and not _snapshot_restated_under(store, node_id)


_UNSETTLED_SUPPORT = "unsettled_support"


def _unsettled_support(store: ProjectStore, node_id: str) -> frozenset[str]:
    """Every node `node_id` rests on, directly or through others, that hasn't reached the standing that unblocks
    (`_dependency_satisfied`). The walk stops at a settled node: what that rests on was settled before it was.

    One pass per read, like `_upstream_cause`: each node's answer goes in the read scope's memo as the walk leaves
    it, with an explicit stack for deep chains, and a cycle (which no service creates) answered by plain reachability.
    """
    memo: dict[str, frozenset[str]] = scoped_memo(store, _UNSETTLED_SUPPORT)
    if node_id in memo:
        return memo[node_id]

    def dependencies_of(current_id: str) -> list[str]:
        node = get_node(store, current_id)
        return node.dependencies if node is not None else []

    stack: list[tuple[str, Iterator[str], set[str]]] = [(node_id, iter(dependencies_of(node_id)), set())]
    on_path = {node_id}
    while stack:
        current_id, dependencies, found = stack[-1]
        dependency_id = next(dependencies, None)
        if dependency_id is None:
            stack.pop()
            on_path.discard(current_id)
            memo[current_id] = frozenset(found)
            if stack:
                stack[-1][2].update(found)
            continue
        if _dependency_satisfied(store, dependency_id):
            continue
        found.add(dependency_id)
        if dependency_id in memo:
            found.update(memo[dependency_id])
        elif dependency_id in on_path:
            for path_id, _, _ in stack:
                memo.pop(path_id, None)
            return _reachable_unsettled(store, node_id)
        else:
            stack.append((dependency_id, iter(dependencies_of(dependency_id)), set()))
            on_path.add(dependency_id)
    return memo[node_id]


def _reachable_unsettled(store: ProjectStore, node_id: str) -> frozenset[str]:
    """`_unsettled_support` by plain reachability, remembering nothing: for a map with a cycle."""
    found: set[str] = set()
    pending = list(get_node(store, node_id).dependencies)
    while pending:
        current_id = pending.pop()
        if current_id in found or _dependency_satisfied(store, current_id):
            continue
        found.add(current_id)
        node = get_node(store, current_id)
        if node is not None:
            pending.extend(node.dependencies)
    found.discard(node_id)
    return frozenset(found)


@read_scoped
def conditional_on(store: ProjectStore, node_id: str) -> frozenset[str]:
    """The Provisional nodes `node_id` rests on, directly or through others: its proof stands only if they do
    (ADR-0021 point 2). Empty for a node that isn't Conditional, an Accepted one included; derived, and cleared
    node by node as the researcher Accepts bottom-up."""
    node = require_node(store, node_id)
    if _already_accepted(store, node):
        return frozenset()
    return frozenset(dependency_id for dependency_id in _unsettled_support(store, node_id) if is_provisional(store, dependency_id))


def _sent_back(store: ProjectStore, node_id: str) -> bool:
    """Whether the researcher's newest decision on a local node withdrew it as support: a Reject, or a Revision
    requested that no new snapshot has answered yet."""
    node = get_node(store, node_id)
    if node is None or node.kind == ProofMapNodeKind.imported_result:
        return False
    state, latest, _ = _acceptance(store, node)
    if state == "rejected":
        return True
    return (
        latest is not None
        and state != "unverifiable"
        and latest.decision == ReviewGovernanceState.revision_requested
        and _awaiting_decision(store, node) is None
    )


def _support_withdrawn(store: ProjectStore, node_id: str) -> bool:
    """Whether anything `node_id` rests on unsettled was sent back by the researcher (ADR-0021 point 4)."""
    return any(_sent_back(store, dependency_id) for dependency_id in _unsettled_support(store, node_id))


@memoized_read
@read_scoped
def get_integrity_state(store: ProjectStore, node_id: str) -> str:
    """One of `current`, `potentially-stale`, `challenged`.

    `challenged` if the node is itself the target of an open Challenge.
    `potentially-stale` if the node is Accepted and reachable (via
    dependency edges) from an open Challenge's target or a stale dependency
    pin — computed by graph reachability, nothing set directly (ADR-0004
    point 4); or if its snapshot awaits a decision and rests on a node the
    researcher has since rejected or sent back for revision (ADR-0021 point
    4); or if its current snapshot, relied on by no decision yet, was frozen
    before the text it proves was restated (ADR-0021 point 6). `current`
    otherwise.
    """
    require_node(store, node_id)
    if has_open_challenge(store, node_id):
        return "challenged"
    if get_acceptance_state(store, node_id) == "accepted" and _is_downstream_of_challenge_or_stale_pin(
        store, node_id
    ):
        return "potentially-stale"
    node = require_node(store, node_id)
    if _awaiting_decision(store, node) is not None and _support_withdrawn(store, node_id):
        return "potentially-stale"
    if _snapshot_restated_under(store, node_id):
        return "potentially-stale"
    return "current"


def _snapshot_restated_under(store: ProjectStore, node_id: str) -> bool:
    """Whether the node's current snapshot, not yet relied on by any decision, was frozen before the text it proves —
    its own or what it rests on — was restated (ADR-0021 point 6). A new snapshot answers it."""
    current = get_current_candidate_proof(store, node_id)
    if current is None:
        return False
    restated = restated_at(store, node_id)
    return restated is not None and current.created_at < restated and fixed_by(store, node_id) is None


@read_scoped
def get_frontier(store: ProjectStore) -> list[ProofMapNode]:
    """The nodes ready to be worked right now: what an agent should claim next (ADR-0010, ADR-0021).

    Every dependency Accepted (or Reference-reviewed) or Provisional, nobody
    holding it, and no snapshot of it already awaiting the researcher; among
    the nodes `claim_node` would accept from anyone (the same check,
    `_not_pickable`).
    """
    return [
        node
        for node in list_nodes(store)
        if get_active_claim(store, node.id) is None
        and _not_pickable(store, node) is None
        and _awaiting_decision(store, node) is None
        and all(_dependency_satisfied(store, d) or is_provisional(store, d) for d in node.dependencies)
    ]


@read_scoped
def list_integrity_warnings(store: ProjectStore) -> list[AuthorityWarning]:
    """What about the recorded Human Review decisions doesn't count, node by node.

    The authority layer's own findings (unreadable lines, unconfirmed
    pre-ADR-0010 decisions, decisions git doesn't have yet) plus what only
    the proof map can see: a recorded Acceptance that no longer describes
    its node, and a Review snapshot on disk the index never recorded (an orphan
    of a crashed `request_review`, #18).
    """
    warnings = list_authority_warnings(store)
    for node in list_nodes(store):
        if node.kind == ProofMapNodeKind.imported_result:
            continue
        # a folder snapshot is known by its folder, an old single-file one by its file
        indexed = {
            proof.file_path.removesuffix("/" + SNAPSHOT_MANIFEST) for proof in list_candidate_proofs_for_node(store, node.id)
        }
        for _, path in sorted(snapshots_on_disk(store.root, node.id).items()):
            file_path = path.relative_to(store.root).as_posix()
            if file_path not in indexed:
                warnings.append(
                    AuthorityWarning(
                        code="ORPHAN_SNAPSHOT",
                        message=f"{file_path} was never indexed as a Candidate proof of {node.id}; review skips past it",
                        details={"node_id": node.id, "file_path": file_path},
                    )
                )
        state, latest, problem = _acceptance(store, node)
        if state == "unverifiable" and latest is not None and latest.verdict.status == "verified":
            warnings.append(
                AuthorityWarning(
                    code="DECISION_NO_LONGER_APPLIES",
                    message=f"{node.id}'s acceptance decision no longer counts: {problem}",
                    details={"node_id": node.id, "review_id": latest.row["review_id"]},
                )
            )
    return warnings
