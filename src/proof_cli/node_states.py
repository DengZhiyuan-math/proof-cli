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
  Challenges had a kind (#277), whose kind is never guessed; so does a Rejected node. It reads false once the
  Challenge's counterexample reads true (`counterexample_decides`, zeqome/proof-agents#49). An open Challenge against
  the proof sends the Proof layer back to incomplete instead, and so does an agent's statement Challenge until its
  counterexample decides: no Verdict has yet said where the counterexample fails.
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
from datetime import datetime

from pydantic import BaseModel

from .domain import Challenge, ChallengeStatus, ProofMapNode, ProofMapNodeKind
from .proof_map import (
    RESEARCHER,
    ProofMapError,
    direct_seal,
    false_since,
    get_acceptance_state,
    get_accepted_version,
    get_node,
    get_reference_review_state,
    has_passing_check,
    list_challenges,
    list_nodes,
    no_longer_callable_review,
    require_node,
    restored_challenges,
    rests_on,
    seal_line,
    two_sided,
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
    over what it rests on, so a hand-edited cycle elsewhere never reaches it; only a counterexample's conclusion is read
    with it (`counterexample_decides`). Its conclusion is `node_states`'."""
    seal, statement_layer = own_seal(store, node), "unchallenged"
    imported = node.kind == ProofMapNodeKind.imported_result
    if not imported and get_acceptance_state(store, node.id) == "rejected":
        statement_layer = "challenged-as-false"
    if seal == "unsealed" and sealed_by(store, node.id) is not None:
        seal = "sealed-true"  # a true seal above covers what it rests on (ADR-0025 point 14)
    challenges = list_challenges(store, target_node_id=node.id)
    holds, since = verification_holds(store, node)
    if holds and any(lapses(store, challenge, since) for challenge in challenges):
        holds = False
    proof_layer = "expert-verified" if holds else "checks-passed" if imported else "incomplete"
    if proof_layer == "incomplete" and node.kind != ProofMapNodeKind.imported_result and has_passing_check(store, node.id):
        proof_layer = "checks-passed"
    for challenge in challenges:
        if challenge.status != ChallengeStatus.open:
            continue
        if challenge.kind == "proof":
            proof_layer = "incomplete"
            continue
        decided = counterexample_decides(store, challenge)   # a counterexample that decided makes it false (ADR-0025 point 7)
        if statement_layer != "false":
            statement_layer = "false" if decided else "challenged-as-false"
        if two_sided(challenge) and not decided:   # no Verdict has said where its counterexample fails yet
            proof_layer = "incomplete"
    claim = get_active_claim(store, node.id)
    return seal, statement_layer, proof_layer, claim.claimant_id if claim else None


@read_scoped
def counterexample_decides(store: ProjectStore, challenge: Challenge) -> bool:
    """Whether an open statement Challenge's counterexample decides it (ADR-0025 point 7; zeqome/proof-agents#49): the
    counterexample's conclusion is true — its proof has passed its check, its own statement is unchallenged, and what it
    rests on holds — so the challenged statement is false; it reads challenged again when that stops being so, and when
    the counterexample comes to rest on its target, which it could then contradict only by assuming it. Counterexamples
    that contradict each other in a cycle are each challenged, none decides, and all read uncertain; a cycle that runs
    through what they rest on is cut where it comes back to a Challenge being decided, which reads undecided there."""
    if challenge.kind != "statement" or not challenge.counterexample_id or challenge.status != ChallengeStatus.open:
        return False
    node = get_node(store, challenge.counterexample_id)
    if node is None or any(other.status == ChallengeStatus.open and other.kind != "proof" for other in list_challenges(store, target_node_id=node.id)):
        return False   # gone, or its own statement in question
    if challenge.target_node_id in rests_on(store, node.id):
        return False
    deciding = scoped_memo(store, "deciding")
    if challenge.id in deciding:
        return False
    deciding[challenge.id] = True
    try:
        return node_states(store, node.id).conclusion in ("true", "verified-true")
    except ProofMapError as error:
        if error.code != "DEPENDENCY_CYCLE":
            raise
        return False   # a hand-edited cycle under it: undecided here, and named where the counterexample is read
    finally:
        deciding.pop(challenge.id, None)


def own_seal(store: ProjectStore, node: ProofMapNode) -> str:
    """The node's Seal by itself, never by a seal above: its newest seal line, else sealed false for an imported result a
    Reference review found no longer callable, from before seal lines (ADR-0025 point 26), else unsealed."""
    seal = direct_seal(store, node.id)
    if (seal == "unsealed" and node.kind == ProofMapNodeKind.imported_result
            and get_reference_review_state(store, node.id) == "no-longer-callable"):
        return "sealed-false"
    return seal


def _seal_after_unseal(store: ProjectStore, node: ProofMapNode, unsealed: str) -> str:
    """The node's Seal once `unsealed` is unsealed: its own seal line (the root's is the one removed), else the older
    review's sealed false, else a true seal other than `unsealed`'s that covers it, else unsealed."""
    own = "unsealed" if node.id == unsealed else direct_seal(store, node.id)
    if (own == "unsealed" and node.kind == ProofMapNodeKind.imported_result
            and get_reference_review_state(store, node.id) == "no-longer-callable"):
        own = "sealed-false"
    if own != "unsealed":
        return own
    return "sealed-true" if [by for by in _covered(store).get(node.id, []) if by != unsealed] else "unsealed"


def verification_holds(store: ProjectStore, node: ProofMapNode) -> tuple[bool, datetime | None]:
    """Whether a verification of the node as it stands holds, before any Challenge lapses it, and when it was made
    (None for a Trust rule, which holds from no one decision): the researcher's verification of the version as it
    stands, a counting Acceptance of the current version, a Reference review or a Trust rule. It is void when a
    dependency was found false after it (ADR-0025 point 3), sealed false or no longer callable, however that ends."""
    if node.kind == ProofMapNodeKind.imported_result:
        holds = get_reference_review_state(store, node.id) in ("reviewed", "trusted-by-rule")
    else:
        current = get_current_candidate_proof(store, node.id)
        holds = (get_acceptance_state(store, node.id) == "accepted" and current is not None
                 and current.version == get_accepted_version(store, node.id))
    holds = holds or researcher_verification_time(store, node.id) is not None
    if not holds:
        return False, None
    since = verification_time(store, node.id)
    if since is not None and any(found > since for dependency in node.dependencies for found in false_since(store, dependency)):
        return False, None
    return True, since


def lapses(store: ProjectStore, challenge: Challenge, since: datetime | None) -> bool:
    """Whether a Challenge lapses a verification made at `since` (ADR-0025 point 13): an agent's, raised after it (any,
    under a Trust rule), and not ended by the researcher's click — "not a problem", or a dismissal on the page."""
    return (challenge.opened_by != RESEARCHER and challenge.status != ChallengeStatus.dismissed
            and challenge.id not in restored_challenges(store) and (since is None or challenge.created_at > since))


def stopped_by(store: ProjectStore, node_id: str) -> list[str]:
    """The nodes challenged as false whose Challenge stops work on this one (ADR-0025 point 6), by id; empty when none.

    A statement Challenge stops everything under each node that uses the challenged one directly, on that branch only:
    what uses it elsewhere, and what sits beside it, goes on. The challenged node is stopped with it, unless an agent's
    Challenge links a counterexample: then it and its counterexample are the two sides worked while the branch waits
    (point 7; zeqome/proof-agents#49). A Challenge against a proof stops nothing: only that node is reworked."""
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
        examples = counterexamples(store, challenged)   # with them, the two sides and what they rest on are worked
        seen: set[str] = set().union(*(rests_on(store, side) for side in (challenged, *examples))) if examples else set()
        while branch:  # each direct user and everything under it; `seen` ends a hand-edited cycle
            current = branch.pop()
            if current in seen:
                continue
            seen.add(current)
            stopped.setdefault(current, set()).add(challenged)
            branch.extend(nodes[current].dependencies if current in nodes else [])
    memo["stopped"] = {node_id: sorted(by) for node_id, by in stopped.items()}
    return memo["stopped"]


def counterexamples(store: ProjectStore, node_id: str) -> list[str]:
    """The counterexamples of the agents' statement Challenges open on the node: with the node itself, the two sides of
    each, worked while its branch waits (ADR-0025 point 7; zeqome/proof-agents#49). None while the researcher's Challenge,
    one from before kinds or a Rejection is also on it: the node stays stopped for the researcher to conclude."""
    statement = [challenge for challenge in list_challenges(store, target_node_id=node_id, status="open") if challenge.kind != "proof"]
    if not all(two_sided(challenge) for challenge in statement):
        return []
    node = require_node(store, node_id)
    if node.kind != ProofMapNodeKind.imported_result and get_acceptance_state(store, node_id) == "rejected":
        return []
    return [challenge.counterexample_id for challenge in statement]


def sealed_by(store: ProjectStore, node_id: str) -> str | None:
    """The node whose true seal covers this one (ADR-0025 point 14), the first by id when several do, or None. Only the
    directly sealed node is recorded, with the set it covered as the page showed it; unsealing it removes that
    coverage, never another seal's, and a node it came to rest on later is not sealed by it."""
    coverers = _covered(store).get(node_id)
    return coverers[0] if coverers else None


@read_scoped
def _covered(store: ProjectStore) -> dict[str, list[str]]:
    """Every covered node's sealing nodes, by id: one read of the map's true seals per read scope."""
    memo = scoped_memo(store, "covered")
    if "covered" in memo:
        return memo["covered"]
    covered: dict[str, list[str]] = {}
    for sealed in sorted(node.id for node in list_nodes(store)):
        line = seal_line(store, sealed)
        for node_id in (line or {}).get("covered") or []:
            covered.setdefault(node_id, []).append(sealed)
    memo["covered"] = covered
    return covered


def seal_record(store: ProjectStore, node_id: str) -> dict | None:
    """What seals the node, for every later briefing (ADR-0025 point 14): {"seal", "sealed_node", "by", "at", "note"} —
    its own seal, or the true seal above that covers it, or for an imported result the older Reference review that
    found it no longer callable — or None while nothing seals it."""
    if direct_seal(store, node_id) != "unsealed":
        sealed_node = node_id
    elif own_seal(store, require_node(store, node_id)) == "sealed-false":  # its own, before any seal above (`own_states`)
        older = no_longer_callable_review(store, node_id)
        return {"seal": "sealed-false", "sealed_node": node_id, **older} if older else None
    else:
        sealed_node = sealed_by(store, node_id)
    line = seal_line(store, sealed_node) if sealed_node is not None else None
    if line is None:
        return None
    return {"seal": node_states(store, node_id).seal, "sealed_node": sealed_node, "by": line["by"], "at": line["at"], "note": line["note"]}


def seal_preview(store: ProjectStore, node_id: str, action: str) -> dict[str, list[str]]:
    """What a seal or an unseal would do, listed before the researcher's click (ADR-0025 point 15); it never blocks.

    `seal-true`: the nodes it would seal (itself and all it rests on), those of them not verified, and those with a
    Challenge not ended. `seal-false`: the nodes that use it directly, which become uncertain and need another route,
    and those of them verified, whose verification is void. `unseal`: the nodes no seal holds once its seal and that
    seal's coverage are removed; one sealed itself, by an older review, or by another true seal stays sealed."""
    nodes = {node.id: node for node in list_nodes(store)}
    require_node(store, node_id)
    if action == "seal-true":
        covers = sorted(rests_on(store, node_id))
        return {"covers": covers,
                "unverified": [n for n in covers if node_states(store, n).proof_layer != "expert-verified"],
                "challenged": [n for n in covers if list_challenges(store, target_node_id=n, status="open")]}
    if action == "seal-false":
        users = sorted(n for n, node in nodes.items() if node_id in node.dependencies)
        return {"direct_users": users, "verified": [n for n in users if node_states(store, n).proof_layer == "expert-verified"]}
    if action == "unseal":
        # unsealing removes this seal and its coverage; what goes unsealed is what is sealed by nothing else after it —
        # by no seal line of its own (but the root's, which goes), no older review's fallback, no other true seal
        mine = [node_id, *((seal_line(store, node_id) or {}).get("covered") or [])]
        return {"releases": sorted(n for n in set(mine) if n in nodes and _seal_after_unseal(store, nodes[n], node_id) == "unsealed")}
    raise ProofMapError("INVALID_SEAL", f"'{action}' is not seal-true, seal-false or unseal")
