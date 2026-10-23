"""A project from before ADR-0025 switches to the five states once, the first time this version opens it (point 26; #259).

There is no migration flow and no confirmation step: the researcher's stated focus is the system's stability, not real
proofs. Most of the switch is a reading the five states already make of the old records (`node_states`): an
Acceptance of the current version, a Reference review or a Trust rule reads verified, nothing sealed; an import found
no longer callable reads sealed false; a Verdict from before Verdicts had ids is no check; an open Challenge from
before kinds stays its raiser's, its words kept and its kind left for the Coordinator, whose branch waits meanwhile;
a Pursue with no end reads interrupted. `reviews.jsonl` is not rewritten. What the switch writes:

- for each Rejected node something still rests on, a Challenge by the researcher carrying the reason of the
  rejection, with no kind: the branch using it waits until the Coordinator has settled it with the researcher. A
  Rejected node is history, and nothing is written for it, when nothing rests on it but history, or when a seal holds
  it: the seal is the researcher's word after the rejection, and a sealed node is never challenged;
- the release of every claim an agent holds: the runs from before the switch are interrupted, their drafts and work
  logs kept, and the researcher starts a Pursue to go on;
- the Uses of dependencies' environments in the shared preamble, when it lacks them (#281).

Before it, one copy of the database is kept (`BACKUP_FILE`, written whole under another name first); after it, one
project entry (`SWITCH_EVENT`, listed by `proof history`: the switch is no node's) says what changed and how many.
What it counts is read before the write lock is taken; the writes, the preamble's among them, are made under it, and
the flag is set in the same transaction, so two processes opening at once switch once, a second open changes nothing,
and a switch that fails leaves the preamble as it was. A project this version makes is switched as it is made.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .domain import ProofMapNode, ProofMapNodeKind
from .node_states import NodeStates, node_states
from .proof_map import (RESEARCHER, _raise_challenge, direct_seal, latest_verdict, list_challenges, list_nodes, rejected_because, release_node,
                        researcher_verification_time)
from .pursuit import INTERRUPTED, project_progress
from .storage import FIVE_STATES_SWITCHED_KEY, ProjectStore, append_event, get_active_claim, read_scope
from .vault import USES_PREAMBLE, preamble_path

SWITCHED_KEY = FIVE_STATES_SWITCHED_KEY
SWITCH_EVENT = "five_states_switch"
BACKUP_FILE = Path(".proof") / "project-before-five-states.sqlite3"   # from the project root
SWITCHED_BY = "five-states-switch"   # who released the claims of the runs from before
_RELEASED = "the switch to the five states (ADR-0025): runs from before it are interrupted; start a Pursue to go on"


def switch_to_five_states(store: ProjectStore) -> dict[str, int] | None:
    """Switch the project once, as the module says; the counts of what changed, or None when it was switched already."""
    if _switched(store):
        return None
    with read_scope():   # one reading of the project, before the write lock: none of it depends on what the switch writes
        nodes = list_nodes(store)
        states = {node.id: node_states(store, node.id) for node in nodes}
        rejected = {node.id: reason for node in nodes if (reason := rejected_because(store, node.id)) is not None}
        challenged = _rejected_rested_on(nodes, rejected, states)
        counts = {
            "verified": sum(states[node.id].proof_layer == "expert-verified" and researcher_verification_time(store, node.id) is None
                            for node in nodes),   # by an Acceptance, a Reference review or a Trust rule
            "sealed_false": sum(states[node.id].seal == "sealed-false" and direct_seal(store, node.id) == "unsealed"
                                for node in nodes),   # by a Reference review that found an import no longer callable
            "rejected_history": len(rejected) - len(challenged),
            "rejected_challenged": len(challenged),
            "challenges_to_classify": sum(challenge.kind is None for challenge in list_challenges(store, status="open")) + len(challenged),
            "verdicts_not_counted": sum(_passed_before(store, node.id) and states[node.id].proof_layer != "expert-verified"
                                        for node in nodes if node.kind != ProofMapNodeKind.imported_result),
            "pursuits_interrupted": sum(pursuit["status"] == INTERRUPTED for pursuit in project_progress(store)),
        }
    _back_up(store)
    preamble, before = preamble_path(store.root), None
    try:
        with store.transaction() as conn:
            if _switched(store, conn):   # another process switched it meanwhile
                return None
            for node_id in challenged:
                _raise_challenge(store, node_id, kind=None, opened_by=RESEARCHER, rationale=rejected[node_id], conn=conn)
            counts["claims_released"] = 0
            for node in nodes:
                claim = get_active_claim(store, node.id, conn=conn)
                if claim is not None and claim.claimant_id != RESEARCHER:
                    release_node(store, node.id, claimant_id=SWITCHED_BY, reason=_RELEASED)
                    counts["claims_released"] += 1
            before = _complete_preamble(preamble)   # under the write lock: one process completes it
            counts["preamble_completed"] = int(before is not None)
            said = ", ".join(f"{count} {what.replace('_', ' ')}" for what, count in counts.items() if count)
            append_event(store, SWITCH_EVENT, f"switched to the five states (ADR-0025): {said or 'nothing to convert'}; "
                         f"the database as it was before is kept at {BACKUP_FILE.as_posix()}",
                         payload={"counts": counts, "backup": BACKUP_FILE.as_posix()}, conn=conn)
            conn.execute("INSERT OR IGNORE INTO project_meta(key, value) VALUES (?, ?)", (SWITCHED_KEY, "1"))
    except BaseException:
        if before is not None:   # the switch did not happen: neither did this
            preamble.write_text(before, encoding="utf-8")
        raise
    return counts


def _rejected_rested_on(nodes: list[ProofMapNode], rejected: dict[str, str], states: dict[str, NodeStates]) -> list[str]:
    """The Rejected nodes that become the researcher's Challenge: unsealed, and rested on by something that is not
    history. History is a Rejected node nothing rests on but history, or one a seal holds; what rests on history only
    is history too, so the reading is repeated until it settles."""
    users: dict[str, set[str]] = {}
    for node in nodes:
        for dependency in node.dependencies:
            users.setdefault(dependency, set()).add(node.id)
    history = {node_id for node_id in rejected if states[node_id].seal != "unsealed"}
    while True:
        more = {node_id for node_id in rejected if node_id not in history and users.get(node_id, set()) <= history}
        if not more:
            return sorted(set(rejected) - history)
        history |= more


def _switched(store: ProjectStore, conn: sqlite3.Connection | None = None) -> bool:
    if conn is not None:
        return conn.execute("SELECT 1 FROM project_meta WHERE key = ?", (SWITCHED_KEY,)).fetchone() is not None
    with closing(store.connect()) as own:
        return _switched(store, own)


def _back_up(store: ProjectStore) -> None:
    """One copy of the database as it stood before the switch's first try, written whole under another name, then
    named: a copy cut short is never kept for good."""
    backup = store.root / BACKUP_FILE
    if backup.exists():
        return
    partial = backup.with_name(backup.name + ".partial")
    partial.unlink(missing_ok=True)
    with closing(sqlite3.connect(store.db_path)) as source, closing(sqlite3.connect(partial)) as copy:
        source.backup(copy)
    partial.replace(backup)


def _passed_before(store: ProjectStore, node_id: str) -> bool:
    """Whether the node's newest Verdict passed under the old rules: from before Verdicts had ids, so it is no check."""
    verdict = latest_verdict(store, node_id)
    return verdict is not None and verdict.get("outcome") == "passed" and not verdict.get("id")


def _complete_preamble(path: Path) -> str | None:
    """Add the Uses of dependencies' environments to a shared preamble that lacks them, leaving the rest as the
    researcher wrote it; its text before, or None when nothing was added. A missing preamble is the scaffold's to write."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    if "\\newenvironment{depuse}" in text:
        return None
    path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + USES_PREAMBLE, encoding="utf-8")
    return text


__all__ = ["BACKUP_FILE", "SWITCH_EVENT", "SWITCHED_KEY", "switch_to_five_states"]
