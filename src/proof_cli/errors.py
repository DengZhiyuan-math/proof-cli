"""Every error code the agent-facing contract can return, in one place (ADR-0006, issue #34).

A code is what an agent branches on, so it is stable: the message beside it
may be reworded, the code may not. `tests/test_cli_contract.py` fails if the
source raises a code that isn't listed here.
"""

from __future__ import annotations

ERROR_CODES: dict[str, str] = {
    # -- the CLI itself ----------------------------------------------------------------
    "USAGE_ERROR": "the command line didn't parse: a missing argument, an unknown option or command (exit 2)",
    "INTERNAL_ERROR": "an unexpected failure inside proof-cli; the message names it",
    "INVALID_INPUT": "a legacy command (`theorem add`, `reference import`) refused its input under --json; the message says why",
    "PROJECT_NOT_FOUND": "a read was pointed at a folder with no proof project; nothing was created",
    "HUMAN_REVIEW_REQUIRED": "a Human Review decision, made only by the researcher on the proof map page; the error carries its URL",
    # -- nodes -------------------------------------------------------------------------
    "NODE_NOT_FOUND": "no proof map node has this id",
    "NODE_ALREADY_EXISTS": "a proof map node with this id already exists",
    "INVALID_NODE_ID": "a node id must be a plain folder name: letters, digits, '.', '_' or '-'",
    "INVALID_KIND": "not a proof map node kind",
    "INVALID_TRUST_LEVEL": "not a trust level",
    "DUPLICATE_THEOREM": "the project already has its one theorem-kind node",
    "DEPENDENCY_NOT_FOUND": "a named dependency doesn't exist yet",
    "DERIVED_FROM_NOT_FOUND": "the node a split child derives from doesn't exist",
    "IMMUTABLE_NODE": "an imported result has no proof, claim or split; it enters the map through Reference review",
    "IMPORTED_RESULT_REQUIRES_SOURCE": "an imported result needs a source locator and a source version",
    "IMPORTED_RESULT_HAS_NO_DEPENDENCIES": "an imported result is established elsewhere and takes no dependencies",
    "NOT_IMPORTED_RESULT": "the operation applies only to an imported result",
    "NOT_A_CLAIM": "only a Claim can be promoted",
    # -- claims (a planning signal, ADR-0010) --------------------------------------------
    "CLAIM_CONFLICT": "someone else holds the claim; the error names them (pass --reassign to take it over)",
    "CLAIM_CONTENDED": "the claim couldn't be taken under database contention; retry",
    "NO_ACTIVE_CLAIM": "the node has no active claim",
    "NOT_CLAIMANT": "someone else holds this node, so the operation is theirs (ADR-0006 §8's CLAIM_OWNERSHIP_MISMATCH)",
    "NODE_BLOCKED": "a dependency hasn't reached the standing this needs",
    "NODE_CHALLENGED": "the node is the target of an open Challenge",
    "NODE_ACCEPTED": "the node is Accepted; the operation would void that decision",
    "NODE_ALREADY_ACCEPTED": "the node is already Accepted",
    "NODE_REJECTED": "the node was Rejected, which is final",
    "NODE_UNVERIFIABLE": "the node's recorded decision no longer counts; it needs the researcher first",
    # -- proofs, snapshots and splits ----------------------------------------------------
    "SCOPING_RATIONALE_REQUIRED": "requesting review needs a statement of why the node is scoped to prove directly",
    "WORKING_PROOF_MISSING": "the node has no working proof.tex",
    "WORKING_PROOF_UNCHANGED": "the working proof is the snapshot already under review",
    "CANDIDATE_PROOF_NOT_FOUND": "no Candidate proof has this id",
    "CANDIDATE_PROOF_VERSION_CONFLICT": "that snapshot version is already indexed",
    "SPLIT_REQUIRES_CHILDREN": "a split needs at least one child",
    "INVALID_CHILD_SPEC": "a split child is written <child-id>=<statement>",
    # -- evidence, challenges, dependencies ----------------------------------------------
    "EVIDENCE_CHECK_NOT_FOUND": "no Evidence check has this id",
    "INVALID_OUTCOME": "not an Evidence check outcome",
    "CHALLENGE_NOT_FOUND": "no Challenge has this id",
    "CHALLENGE_NOT_OPEN": "the Challenge is already resolved",
    "TARGET_NOT_ACCEPTED": "the target isn't Accepted",
    "TARGET_NOT_REVIEWED": "the imported result hasn't been Reference-reviewed",
    "NOT_A_DEPENDENCY": "the target isn't one of the node's dependencies",
    "NO_DEPENDENCY_PIN": "the node never pinned that dependency; request review first",
    "DEPENDENCY_REQUIRED": "a Lightweight re-review names the dependency it re-pins",
    "INTERFACE_CHANGED": "the dependency's accepted interface changed: a new Candidate proof is needed, not a re-review",
    # -- Human Review decisions (made on the page) ---------------------------------------
    "INVALID_DECISION": "not a decision of this kind",
    "INVALID_DECISION_KIND": "not a decision kind",
    "UNSUPPORTED_DECISION": "the page doesn't apply decisions of this kind",
    "NOT_REVIEW_NEEDED": "no snapshot awaits a decision",
    "NOT_ACCEPTED": "the node isn't Accepted",
    "REFERENCE_NOT_CALLABLE": "the imported result is no longer callable, which is final",
    "REFERENCE_STILL_CALLABLE": "the imported result is still callable, so its dependents don't move",
    "REPLACEMENT_REQUIRED": "moving dependents names the imported result they move onto",
    "REPLACEMENT_NOT_IMPORTED_RESULT": "a corrected source is cited as a new imported result",
    "REPLACEMENT_NOT_CALLABLE": "the replacement is itself no longer callable",
    "SAME_NODE": "a node can't replace itself",
    "NO_DEPENDENTS": "nothing that can move rests on the node",
    "STALE_VIEW": "what the decision is made on changed since the page showed it; reload",
    # -- the proof map page's own requests -----------------------------------------------
    "NO_DECISIONS": "the request decided nothing",
    "MALFORMED_DECISION": "a decision in the request isn't a well-formed object",
    "NO_PDF": "that PDF doesn't exist",
    "NO_PROOF_FOLDER": "the node has no proof folder",
    "INVALID_REQUEST": "the page's request is missing what the action needs (a node id, which snapshot, …)",
    "NOT_FOUND": "no such page route or node action, or (a legacy command under --json) no such contract, reference or target",
    "NOT_THIS_NODE": "the snapshot named belongs to another node",
}
