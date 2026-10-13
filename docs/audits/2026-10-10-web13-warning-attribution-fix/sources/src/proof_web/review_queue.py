"""The researcher's review queue (ADR-0021 point 10): everything waiting on them, bottom-up, none of it holding the agents back.

The queue holds:
- the Provisional nodes awaiting Acceptance;
- the unreviewed imported results, an agent's with the rules it would meet and the Verifier's "unchecked against the
  source" marks on what rests on it (ADR-0022 point 3);
- the Unfixed text agents wrote (statements and Definitions), with the Reader's departures from the draft;
- the Standing questions, answered in place;
- the Parked nodes, with their attempts.

Bottom-up means by depth over the unaccepted map: a node resting on nothing unaccepted comes first, then what rests
on it, so that each Accept makes the next decision possible. The parked nodes come before everything else (point 9). Everything here is derived from project state each
read; nothing is stored for the queue.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from proof_cli import proof_map
from proof_cli.definitions import all_definitions, fixed_by_definition, nodes_naming
from proof_cli.domain import ProofMapNodeKind
from proof_cli.storage import ProjectStore, get_current_candidate_proof, list_candidate_proofs_for_node, list_evidence_checks_for_candidate_proof

# a Coordinator's note on a node it parked (ADR-0021 point 9), as `StudioHub._park` records it
PARKED_NOTE = "parked: "
# the Reader records every place it departed from the draft here (ADR-0021 point 5)
DEPARTURES = ("scratch", "reader", "departures.md")
# the work-log kinds that are work on the node itself: one after a parked note means the node is worked again
_WORK = ("plan", "step", "verdict", "attempt", "handoff", "turn")
# the Verifier's mark on an appeal to an unreviewed imported result whose source it could not read (ADR-0021 point 3)
UNCHECKED = "unchecked against the source"
# the acceptance states a Review decision left the node in: a decided node is no longer where the agents could not go
_DECIDED = ("accepted", "rejected", "no-longer-callable")


def awaiting_review(store: ProjectStore, node) -> bool:
    """Whether a snapshot of the node awaits a Review decision, even where the workflow axis reads Blocked (ADR-0021 point 1)."""
    if node.kind == ProofMapNodeKind.imported_result:
        return False
    return proof_map.awaiting_decision(store, node.id) is not None


def parked_reason(store: ProjectStore, node_id: str) -> str | None:
    """Why the node is parked, from the newest parked note on its work log, or None: never parked, worked since, or
    decided since (Accepted, Rejected, no longer callable): the researcher's decision ends what parking asked of them.
    An imported result is never parked: no run works it."""
    node = proof_map.get_node(store, node_id)
    if node is None or node.kind == ProofMapNodeKind.imported_result:
        return None
    if proof_map.get_acceptance_state(store, node_id) in _DECIDED:
        return None
    reason = None
    for entry in proof_map.work_log(store, node_id):
        kind = entry.get("kind")
        if kind == "coordinator" and str(entry.get("note") or "").startswith(PARKED_NOTE):
            reason = str(entry["note"])[len(PARKED_NOTE):]
        elif kind in _WORK:
            reason = None
    return reason


def _depths(store: ProjectStore, nodes: list) -> dict[str, int]:
    """Each node's depth over the unaccepted map: 0 when it rests on nothing unsettled, else one more than the deepest
    unsettled node it rests on. Settled nodes are 0. A cycle, which no service creates, counts its edge once."""
    by_id = {node.id: node for node in nodes}
    settled = {node.id for node in nodes if _settled(store, node)}
    depth: dict[str, int] = {}
    for start in by_id:
        stack, on_path = [(start, iter(by_id[start].dependencies))], {start}
        best = {start: 0}
        while stack:
            current, deps = stack[-1]
            dep = next(deps, None)
            if dep is None:
                stack.pop()
                on_path.discard(current)
                depth[current] = best[current]
                if stack:
                    parent = stack[-1][0]
                    best[parent] = max(best[parent], depth[current] + 1)
                continue
            if current in settled or dep not in by_id or dep in settled or dep in on_path:
                continue
            if dep in depth:
                best[current] = max(best[current], depth[dep] + 1)
                continue
            best[dep] = 0
            on_path.add(dep)
            stack.append((dep, iter(by_id[dep].dependencies)))
    return depth


def _settled(store: ProjectStore, node) -> bool:
    if node.kind == ProofMapNodeKind.imported_result:
        return proof_map.get_reference_review_state(store, node.id) in ("reviewed", "trusted-by-rule")
    return proof_map.get_acceptance_state(store, node.id) == "accepted"


def source_marks(store: ProjectStore, node_id: str) -> list[dict]:
    """Every "unchecked against the source" mark a Verifier left about this imported result (ADR-0021 point 3), as the
    Evidence check on a dependent's snapshot that recorded it: the dependent, the snapshot, whether that snapshot is
    the dependent's current one, and the note. The snapshot's own frozen dependencies say what it rested on (the
    node's current ones for a snapshot from before they were frozen). A mark is read clause by clause: a clause
    saying "unchecked against the source" is this import's when it names it, or when it names no imported result and
    the snapshot rests on no other."""
    nodes = proof_map.list_nodes(store)
    imported = [node.id for node in nodes if node.kind == ProofMapNodeKind.imported_result]
    names = {i: re.compile(rf"(?<![\w.-]){re.escape(i)}(?![\w.-])") for i in imported}
    marks = []
    for dependent in nodes:
        current = None
        for proof in list_candidate_proofs_for_node(store, dependent.id):
            rests_on = proof.dependencies if proof.dependencies is not None else dependent.dependencies
            if node_id not in rests_on:
                continue
            alone = [d for d in rests_on if d in names] == [node_id]
            for check in list_evidence_checks_for_candidate_proof(store, proof.id):
                if any(_marks(clause, node_id, names, alone) for clause in _clauses(check.notes)):
                    current = current or get_current_candidate_proof(store, dependent.id)
                    marks.append({"dependent": dependent.id, "snapshot": proof.version, "current": current is not None and current.id == proof.id,
                                  "evidence_check": check.id, "outcome": check.outcome.value, "note": check.notes})
    return marks


# Keep common abbreviations with the import named after them.
_CLAUSE_BOUNDARY = re.compile(r"\n+|;|(?<=[.!?])(?<!\be\.g\.)(?<!\bi\.e\.)\s+", re.IGNORECASE)
_CHECK_COMMA = re.compile(
    r",\s*(?=(?:\w+\s+)?[\w.-]+(?:\s*:\s*|\s+)(?:un)?checked against the source\b)",
    re.IGNORECASE,
)


def _clauses(note: str) -> Iterator[str]:
    """Split separate source checks, preserving commas in import lists and explanations."""
    for segment in _CLAUSE_BOUNDARY.split(note):
        parts = iter(_CHECK_COMMA.split(segment))
        clause = next(parts)
        for part in parts:
            if "checked against the source" in clause.lower():
                yield clause
                clause = part
            else:
                # "R, R2: unchecked ..." names both imports in one check.
                clause += ", " + part
        yield clause


def _marks(clause: str, node_id: str, names: dict, alone: bool) -> bool:
    """Whether one clause of a Verifier's note marks `node_id` unchecked against the source."""
    if UNCHECKED not in clause.lower():
        return False
    named = [i for i, name in names.items() if name.search(clause)]
    return node_id in named if named else alone


def import_review(store: ProjectStore, node_id: str) -> dict:
    """What makes an imported result's own Reference review cheap (ADR-0022 point 3): the Trust rules an agent's import
    would meet had the researcher imported it, the Verifier's marks on what rests on it, and the rationale prefilled
    from those rules. It gives the node no standing; the decision is the ordinary Reference review."""
    rules = proof_map.would_meet_trust_rules(store, node_id)
    return {"would_meet_trust_rule": rules, "unchecked": source_marks(store, node_id),
            "rationale": f"would meet trust rule {', '.join(rules)} had the researcher imported it; read against the source" if rules else ""}


def review_queue(store: ProjectStore) -> dict:
    """{"items": [...], "departures": the Reader's departures or None}: every item has `kind`, `depth`, and the node or
    Definition it is about. The order is the researcher's reading order:
    - the parked nodes first, bottom-up: the places the agents could not go;
    - then the rest bottom-up, node by node: a node's Standing questions and its unfixed statement before its
      Provisional (or Reference review) entry, so the text is read before the decision that fixes it;
    - an unfixed Definition just before the first entry on a node that names it (a parked one included), or at the
      start of the rest when no node in the queue names it."""
    nodes = proof_map.list_nodes(store)
    depth = _depths(store, nodes)
    order = sorted(range(len(nodes)), key=lambda i: (depth.get(nodes[i].id, 0), i))  # bottom-up, then the map's order
    parked: list[dict] = []
    rest: list[dict] = []
    for node in (nodes[i] for i in order):
        base = {"node_id": node.id, "node_kind": node.kind.value, "statement": node.statement, "depth": depth.get(node.id, 0)}
        imported = node.kind == ProofMapNodeKind.imported_result
        rejected = not imported and proof_map.get_acceptance_state(store, node.id) == "rejected"
        reason = parked_reason(store, node.id)
        if reason is not None:
            parked.append({**base, "kind": "parked", "reason": reason, "attempts": proof_map.attempts(store, node.id)[-5:]})
        for question in proof_map.questions(store, node.id):
            if question["state"] == "open":
                rest.append({**base, "kind": "question", "question_id": question["id"], "question": question.get("question"),
                             "by": question.get("by"), "role": question.get("role"), "at": question.get("at")})
        if not rejected and node.created_by != proof_map.RESEARCHER and proof_map.fixed_by(store, node.id) is None:
            rest.append({**base, "kind": "unfixed", "by": node.created_by, "assumptions": list(node.assumptions),
                         "definitions": list(node.definitions)})
        if proof_map.is_provisional(store, node.id):
            if imported:
                rest.append({**base, "kind": "imported", "citation": proof_map.node_citation(store, node), **import_review(store, node.id)})
            else:
                proof = get_current_candidate_proof(store, node.id)
                rest.append({**base, "kind": "provisional", "conditional_on": sorted(proof_map.conditional_on(store, node.id)),
                             "workflow_state": proof_map.get_workflow_state(store, node.id),
                             "snapshot": proof.version if proof is not None else None})
    items = parked + rest
    unnamed: list[dict] = []
    for definition in all_definitions(store):
        if definition.created_by != proof_map.RESEARCHER and fixed_by_definition(store, definition.id) is None:
            named = nodes_naming(store, definition.id)
            item = {"kind": "unfixed", "definition_id": definition.id, "term": definition.term, "text": definition.text,
                    "by": definition.created_by, "named_by": named}
            first = next((i for i, entry in enumerate(items) if entry.get("node_id") in named), None)
            if first is None:
                unnamed.append({**item, "depth": min((depth.get(n, 0) for n in named), default=0)})
            else:
                items.insert(first, {**item, "depth": items[first]["depth"]})
    at = max((i + 1 for i, entry in enumerate(items) if entry["kind"] == "parked"), default=0)  # where the rest begins
    items[at:at] = unnamed
    try:
        departures = store.root.joinpath(*DEPARTURES).read_text(encoding="utf-8")
    except OSError:
        departures = None
    return {"items": items, "departures": departures}
