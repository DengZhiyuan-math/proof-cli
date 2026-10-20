"""A node's states and its conclusion (ADR-0025): one reading, computed from the records that hold them, never kept.

A node keeps four states of its own — Seal, Statement layer, Proof layer and Assignee — each read off its own record;
the fifth, Run state, is the agents'. Its **conclusion** (verified true, true, uncertain or false) follows from them by
ADR-0025's table and is never above the node's weakest dependency. Every reader that needs to know what a node's
states say about it reads it here, so two readings of one node's conclusion cannot disagree.

Until the records later tickets add exist, today's records are read as ADR-0025 point 26 maps them, read-only: nothing
is written, and no Challenge kind is guessed or stored (#276).

- **Seal**: the node's own newest seal line (#279), else sealed true where a true seal above covers it, else unsealed; an
  imported result found no longer callable, sealed by no line of its own, reads sealed false.
- **Statement layer**: an open Challenge against the statement reads challenged as false, and so does one raised before
  Challenges had a kind (#277), whose kind is never guessed; so does a Rejected node. An open Challenge against the
  proof sends the Proof layer back to incomplete instead.
- **A verification lapses** when an agent challenges the node after it, either kind, and stays lapsed when the Challenge
  is withdrawn or ends (ADR-0025 point 13): only a new verification, or the researcher's click restoring it (the page's
  dismissal today, #279's later), brings it back. The researcher's own doubt lapses nothing.
- **Proof layer**: the researcher's verification of the version as it stands (#279), a counting Acceptance of the
  current version, a Reference review or a Trust rule the citation meets
  reads expert-verified (a verification counts for its own version only: a newer snapshot nobody verified is not), and
  an imported result without one checks passed. A local node's checks passed is its newest Verdict, structured (#278),
  passing and on the inputs as they stand; a Verdict from before Verdicts had ids is no check under the new rules.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from .domain import ChallengeStatus, ProofMapNode, ProofMapNodeKind
from .proof_map import (
    RESEARCHER,
    ProofMapError,
    direct_seal,
    get_acceptance_state,
    get_accepted_version,
    get_reference_review_state,
    has_passing_check,
    list_challenges,
    list_nodes,
    require_node,
    restored_challenges,
    seal_line,
    researcher_verification_time,
    verification_time,
)
from .storage import ProjectStore, get_active_claim, get_current_candidate_proof, read_scoped, scoped_memo

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


@read_scoped
def node_states(store: ProjectStore, node_id: str) -> NodeStates:
    """The node's states, read off today's records, and its conclusion, capped by each dependency's (ADR-0025).

    The dependencies are walked with a stack, not by recursion: a chain may run deeper than Python's recursion limit.
    What the walk works out is kept for the rest of the read scope, so reading every node of the map reads each once.
    No service makes a cycle, but a hand-edited map may hold one: the walk refuses it (DEPENDENCY_CYCLE, naming it)
    rather than going round it forever."""
    read = scoped_memo(store, "node_states")
    path: list[ProofMapNode] = []  # the chain being worked out, from node_id down
    on_path: set[str] = set()
    todo: list[list[str]] = []  # for each node on the path, its dependencies not yet read, the first last

    def enter(entered: str) -> None:
        if entered in on_path:
            ids = [node.id for node in path]
            cycle = [*ids[ids.index(entered):], entered]
            raise ProofMapError("DEPENDENCY_CYCLE", "the map holds a cycle of dependencies, which no service writes: "
                                + " → ".join(cycle) + "; remove one of its edges", details={"node_id": node_id, "cycle": cycle})
        node = require_node(store, entered)
        path.append(node)
        on_path.add(entered)
        todo.append(list(reversed(node.dependencies)))

    if node_id not in read:
        enter(node_id)
    while path:
        while todo[-1] and todo[-1][-1] in read:
            todo[-1].pop()
        if todo[-1]:
            enter(todo[-1].pop())
            continue
        node = path.pop()
        on_path.discard(node.id)
        todo.pop()
        seal, statement_layer, proof_layer, assignee = own_states(store, node)
        read[node.id] = NodeStates(seal=seal, statement_layer=statement_layer, proof_layer=proof_layer, assignee=assignee,
                                   conclusion=conclusion(seal, statement_layer, proof_layer,
                                                         dependencies=[read[dependency].conclusion for dependency in node.dependencies]))
    return read[node_id]


def own_states(store: ProjectStore, node: ProofMapNode) -> tuple[str, str, str, str | None]:
    """The node's own (Seal, Statement layer, Proof layer, Assignee), as the module note maps today's records: no walk
    over what it rests on, so a hand-edited cycle elsewhere never reaches it. Its conclusion is `node_states`'."""
    seal, statement_layer, proof_layer = direct_seal(store, node.id), "unchallenged", "incomplete"
    if node.kind == ProofMapNodeKind.imported_result:
        review = get_reference_review_state(store, node.id)
        if review == "no-longer-callable" and seal == "unsealed":
            seal = "sealed-false"
        proof_layer = "expert-verified" if review in ("reviewed", "trusted-by-rule") else "checks-passed"
    else:
        acceptance = get_acceptance_state(store, node.id)
        if acceptance == "rejected":
            statement_layer = "challenged-as-false"
        elif acceptance == "accepted":
            current = get_current_candidate_proof(store, node.id)
            if current is not None and current.version == get_accepted_version(store, node.id):
                proof_layer = "expert-verified"
    if seal == "unsealed" and sealed_by(store, node.id) is not None:
        seal = "sealed-true"  # a true seal above covers what it rests on (ADR-0025 point 14)
    if proof_layer != "expert-verified" and researcher_verification_time(store, node.id) is not None:
        proof_layer = "expert-verified"  # the researcher's verification of the version as it stands (ADR-0025 point 13)
    challenges = list_challenges(store, target_node_id=node.id)
    if proof_layer == "expert-verified":
        since = verification_time(store, node.id)
        restored = restored_challenges(store)  # the researcher's "not a problem" (point 10), or a dismissal on the page
        if any(challenge.opened_by != RESEARCHER and challenge.status != ChallengeStatus.dismissed and challenge.id not in restored
               and (since is None or challenge.created_at > since) for challenge in challenges):
            proof_layer = "checks-passed" if node.kind == ProofMapNodeKind.imported_result else "incomplete"
    if proof_layer == "incomplete" and node.kind != ProofMapNodeKind.imported_result and has_passing_check(store, node.id):
        proof_layer = "checks-passed"
    for challenge in challenges:
        if challenge.status != ChallengeStatus.open:
            continue
        if challenge.kind == "proof":
            proof_layer = "incomplete"
        else:
            statement_layer = "challenged-as-false"
    claim = get_active_claim(store, node.id)
    return seal, statement_layer, proof_layer, claim.claimant_id if claim else None


def stopped_by(store: ProjectStore, node_id: str) -> list[str]:
    """The nodes challenged as false whose Challenge stops work on this one (ADR-0025 point 6), by id; empty when none.

    A statement Challenge stops everything under each node that uses the challenged one directly, the challenged node
    included, on that branch only: what uses it elsewhere, and what sits beside it, goes on. A Challenge against a
    proof stops nothing: only that node is reworked."""
    return _stopped(store).get(node_id, [])


@read_scoped
def _stopped(store: ProjectStore) -> dict[str, list[str]]:
    memo = scoped_memo(store, "stopped")
    if "stopped" in memo:
        return memo["stopped"]
    nodes = {node.id: node for node in list_nodes(store)}
    users: dict[str, list[str]] = {}
    for node in nodes.values():
        for dependency in node.dependencies:
            users.setdefault(dependency, []).append(node.id)
    stopped: dict[str, set[str]] = {}
    for challenged in nodes:
        if own_states(store, nodes[challenged])[1] != "challenged-as-false":  # its own states: no walk, so no unrelated cycle
            continue
        branch = list(users.get(challenged, []))
        seen: set[str] = set()
        while branch:  # each direct user and everything under it; `seen` ends a hand-edited cycle
            current = branch.pop()
            if current in seen:
                continue
            seen.add(current)
            stopped.setdefault(current, set()).add(challenged)
            branch.extend(nodes[current].dependencies if current in nodes else [])
    memo["stopped"] = {node_id: sorted(by) for node_id, by in stopped.items()}
    return memo["stopped"]


def sealed_by(store: ProjectStore, node_id: str) -> str | None:
    """The node whose true seal covers this one (ADR-0025 point 14): one sealed true that rests on it, at any depth, or
    None. Only the directly sealed node is recorded; what it covers is computed, and unsealing it releases them."""
    return _covered(store).get(node_id)


@read_scoped
def _covered(store: ProjectStore) -> dict[str, str]:
    memo = scoped_memo(store, "covered")
    if "covered" in memo:
        return memo["covered"]
    nodes = {node.id: node for node in list_nodes(store)}
    covered: dict[str, str] = {}
    for sealed in sorted(node_id for node_id in nodes if direct_seal(store, node_id) == "sealed-true"):
        below = list(nodes[sealed].dependencies)
        seen: set[str] = set()
        while below:  # everything it rests on; `seen` ends a hand-edited cycle
            current = below.pop()
            if current in seen or current == sealed:
                continue
            seen.add(current)
            covered.setdefault(current, sealed)
            below.extend(nodes[current].dependencies if current in nodes else [])
    memo["covered"] = covered
    return covered


def seal_record(store: ProjectStore, node_id: str) -> dict | None:
    """What seals the node, for every later briefing (ADR-0025 point 14): {"seal", "sealed_node", "by", "at", "note"} —
    its own seal, or the true seal above that covers it — or None while no seal line holds it."""
    sealed_node = node_id if direct_seal(store, node_id) != "unsealed" else sealed_by(store, node_id)
    line = seal_line(store, sealed_node) if sealed_node is not None else None
    if line is None:
        return None
    return {"seal": node_states(store, node_id).seal, "sealed_node": sealed_node, "by": line["by"], "at": line["at"], "note": line["note"]}


def seal_preview(store: ProjectStore, node_id: str, action: str) -> dict[str, list[str]]:
    """What a seal or an unseal would do, listed before the researcher's click (ADR-0025 point 15); it never blocks.

    `seal-true`: the nodes it would seal (itself and all it rests on), those of them not verified, and those with a
    Challenge not ended. `seal-false`: the nodes that use it directly, which become uncertain and need another route,
    and those of them verified, whose verification is void. `unseal`: the nodes released with it."""
    nodes = {node.id: node for node in list_nodes(store)}
    require_node(store, node_id)
    if action == "seal-true":
        covers, below = [], [node_id]
        while below:
            current = below.pop()
            if current in covers:
                continue
            covers.append(current)
            below.extend(nodes[current].dependencies if current in nodes else [])
        covers.sort()
        return {"covers": covers,
                "unverified": [n for n in covers if node_states(store, n).proof_layer != "expert-verified"],
                "challenged": [n for n in covers if list_challenges(store, target_node_id=n, status="open")]}
    if action == "seal-false":
        users = sorted(n for n, node in nodes.items() if node_id in node.dependencies)
        return {"direct_users": users, "verified": [n for n in users if node_states(store, n).proof_layer == "expert-verified"]}
    if action == "unseal":
        return {"releases": sorted([node_id, *(n for n, by in _covered(store).items() if by == node_id)])}
    raise ProofMapError("INVALID_SEAL", f"'{action}' is not seal-true, seal-false or unseal")
