"""Decision lines as versions before ADR-0025 wrote them: an Acceptance, a Reference review and a Challenge's dismissal.

ADR-0025 point 24 retired the three decisions: the researcher verifies and seals, and a Challenge is withdrawn or
answered "not a problem". Projects keep their old lines, and core reads them as point 26 says: an approving Acceptance
or Reference review as a verification, a rejection as the researcher's Challenge against the statement, a
no-longer-callable import as sealed false, a dismissal as the Challenge's ending. Nothing in the CLI, the page or the
agents makes one any more (`apply_decision` refuses them).

This module writes such lines, in the old format and with no gate, for tests and fixtures that build a project as an
older version left it. It refuses nothing an old version refused: a line it writes is a record of what happened then.
"""

from __future__ import annotations

from .authority import build_decision_payload
from .collaboration import ReviewGovernanceState, ReviewRecord
from .domain import Challenge
from .proof_map import (
    _ACCEPTANCE_OBJECT_TYPE,
    ProofMapError,
    _current_proof_id,
    _Decision,
    _interface_of,
    _pins_of,
    _record,
    note_trust_rule_matches,
    require_challenge,
    require_node,
)
from .reviews import DecisionKind, git_identity
from .storage import ProjectStore, append_event, list_challenges

ACCEPTANCE_DECISIONS = {
    "accept": ReviewGovernanceState.approved,
    "revision-requested": ReviewGovernanceState.revision_requested,
    "reject": ReviewGovernanceState.rejected,
}
REFERENCE_REVIEW_DECISIONS = {"reference-review": ReviewGovernanceState.approved, "no-longer-callable": ReviewGovernanceState.rejected}


def _open_challenge_ids(store: ProjectStore, node_id: str) -> list[str]:
    return [challenge.id for challenge in list_challenges(store, target_node_id=node_id, status="open")]


def write_acceptance(store: ProjectStore, node_id: str, decision: str, *, reviewer: str | None = None, rationale: str = "") -> ReviewRecord:
    """An Acceptance line on the node's current snapshot: accept, revision-requested or reject, bound to the snapshot,
    the interface and the pins as they stand, and resolving the node's open Challenges, as an old version bound it."""
    state = ACCEPTANCE_DECISIONS.get(decision)
    if state is None:
        raise ProofMapError("INVALID_DECISION", f"'{decision}' is not an old acceptance decision: {', '.join(ACCEPTANCE_DECISIONS)}")
    node = require_node(store, node_id)
    with store.transaction() as conn:
        payload = build_decision_payload(
            store, DecisionKind.acceptance, node_id, decision, rationale=rationale, candidate_proof_id=_current_proof_id(store, node_id),
            interface_fingerprint=_interface_of(node), dependency_pins=_pins_of(store, node_id), resolves_challenges=_open_challenge_ids(store, node_id))
        decided = _Decision(payload=payload, reviewer_id=reviewer or git_identity(store.root))
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, state)
        append_event(store, "proof_map_acceptance_decided", f"acceptance decision for {node_id}: {decision}", entity_id=node_id,
                     payload={"decision": decision, "reviewer_id": decided.reviewer_id, "review_id": record.id}, conn=conn)
    return record


def write_reference_review(store: ProjectStore, node_id: str, decision: str = "reference-review", *, reviewer: str | None = None,
                           rationale: str = "") -> ReviewRecord:
    """A Reference review line on an imported result: reference-review or no-longer-callable, bound to its interface and
    resolving its open Challenges, as an old version bound it."""
    state = REFERENCE_REVIEW_DECISIONS.get(decision)
    if state is None:
        raise ProofMapError("INVALID_DECISION", f"'{decision}' is not an old reference review decision: {', '.join(REFERENCE_REVIEW_DECISIONS)}")
    node = require_node(store, node_id)
    not_callable = state == ReviewGovernanceState.rejected
    with store.transaction() as conn:
        payload = build_decision_payload(store, DecisionKind.reference_review, node_id, decision, rationale=rationale,
                                         interface_fingerprint=_interface_of(node), resolves_challenges=_open_challenge_ids(store, node_id))
        decided = _Decision(payload=payload, reviewer_id=reviewer or git_identity(store.root))
        record = _record(store, decided, _ACCEPTANCE_OBJECT_TYPE, node_id, state)
        append_event(store, "proof_map_no_longer_callable" if not_callable else "proof_map_reference_review_granted",
                     f"{node_id} is no longer callable" if not_callable else f"reference review granted for {node_id}", entity_id=node_id,
                     payload={"reviewer_id": decided.reviewer_id, "review_id": record.id}, conn=conn)
    note_trust_rule_matches(store)   # other citations of the same source may now meet `source already reviewed` (ADR-0014)
    return record


def write_dismissal(store: ProjectStore, challenge_id: str, *, reviewer: str | None = None, rationale: str = "") -> Challenge:
    """A Challenge's dismissal line, bound to its target's interface: the Challenge's ending, read from the line."""
    challenge = require_challenge(store, challenge_id)
    with store.transaction() as conn:
        payload = build_decision_payload(store, DecisionKind.challenge_resolution, challenge_id, "dismissed", rationale=rationale,
                                         interface_fingerprint=_interface_of(require_node(store, challenge.target_node_id)))
        decided = _Decision(payload=payload, reviewer_id=reviewer or git_identity(store.root))
        record = _record(store, decided, "challenge", challenge_id, ReviewGovernanceState.dismissed)
        append_event(store, "proof_map_challenge_dismissed", f"challenge {challenge_id} dismissed by {decided.reviewer_id}",
                     entity_id=challenge.target_node_id,
                     payload={"challenge_id": challenge_id, "reviewer_id": decided.reviewer_id, "review_id": record.id}, conn=conn)
    return require_challenge(store, challenge_id)
