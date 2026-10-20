"""A node's states and its conclusion (ADR-0025): one reading, computed from the records that hold them, never kept.

A node keeps four states of its own — Seal, Statement layer, Proof layer and Assignee — each read off its own record;
the fifth, Run state, is the agents'. Its **conclusion** (verified true, true, uncertain or false) follows from them by
ADR-0025's table and is never above the node's weakest dependency. Every reader that needs to know what a node's
states say about it reads it here, so two readings of one node's conclusion cannot disagree.

Until the records later tickets add exist, today's records are read as ADR-0025 point 26 maps them, read-only: nothing
is written, and no Challenge kind is guessed or stored (#276).

- **Seal**: unsealed (#279 adds seal lines), except an imported result found no longer callable, which reads sealed false.
- **Statement layer**: an open Challenge, which has no kind yet (#277), reads challenged as false; so does a Rejected node.
- **Proof layer**: a counting Acceptance, a Reference review or a Trust rule the citation meets reads expert-verified, and
  an imported result without one checks passed. A legacy passed Verdict alone is not a check under the new rules: a
  local node with only that is incomplete, until #281 records the check those rules make.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from .domain import ProofMapNodeKind
from .proof_map import get_acceptance_state, get_reference_review_state, has_open_challenge, require_node
from .storage import ProjectStore, get_active_claim, memoized_read, read_scoped

SEALS = ("unsealed", "sealed-true", "sealed-false")
STATEMENT_LAYERS = ("unchallenged", "challenged-as-false", "false")
PROOF_LAYERS = ("incomplete", "checks-passed", "expert-verified")
CONCLUSIONS = ("uncertain", "true", "verified-true", "false")

_RANK = {"uncertain": 0, "true": 1, "verified-true": 2}  # the order a dependency caps in; false is not on it


def conclusion(seal: str, statement_layer: str, proof_layer: str, *, dependencies: Iterable[str] = ()) -> str:
    """ADR-0025 point 2's table, capped by point 3: never above the weakest of `dependencies`' conclusions.

    A seal decides alone: sealing true seals what the node rests on with it, and sealing false seals only the node.
    A false dependency makes the node uncertain, not false: it needs a proof that does not use it."""
    if seal == "sealed-true":
        return "verified-true"
    if seal == "sealed-false" or statement_layer == "false":
        return "false"
    if statement_layer == "challenged-as-false" or proof_layer == "incomplete":
        own = "uncertain"
    else:
        own = "verified-true" if proof_layer == "expert-verified" else "true"
    capped = ["uncertain" if dependency == "false" else dependency for dependency in dependencies]
    return min([own, *capped], key=_RANK.__getitem__)


class NodeStates(BaseModel):
    """What one reading says of a node: its four states and its conclusion."""

    seal: str
    statement_layer: str
    proof_layer: str
    assignee: str | None
    conclusion: str


@memoized_read
@read_scoped
def node_states(store: ProjectStore, node_id: str) -> NodeStates:
    """The node's states, read off today's records, and its conclusion, capped by each dependency's (ADR-0025)."""
    node = require_node(store, node_id)
    seal, statement_layer, proof_layer = "unsealed", "unchallenged", "incomplete"
    if node.kind == ProofMapNodeKind.imported_result:
        review = get_reference_review_state(store, node.id)
        if review == "no-longer-callable":
            seal = "sealed-false"
        proof_layer = "expert-verified" if review in ("reviewed", "trusted-by-rule") else "checks-passed"
    else:
        acceptance = get_acceptance_state(store, node.id)
        if acceptance == "rejected":
            statement_layer = "challenged-as-false"
        elif acceptance == "accepted":
            proof_layer = "expert-verified"
    if has_open_challenge(store, node.id):
        statement_layer = "challenged-as-false"
    claim = get_active_claim(store, node.id)
    dependencies = [node_states(store, dependency).conclusion for dependency in node.dependencies]
    return NodeStates(seal=seal, statement_layer=statement_layer, proof_layer=proof_layer,
                      assignee=claim.claimant_id if claim else None,
                      conclusion=conclusion(seal, statement_layer, proof_layer, dependencies=dependencies))
