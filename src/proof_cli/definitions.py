"""Definitions: the named text a project's node statements are written in (ADR-0020).

A statement alone could not say what its symbols are: a model's setting, a definition, notation all had to be crammed
into it, or were left out and every reader — the researcher and each agent — had to guess. A **Definition** is that text,
once, under a name: an id, a term to show, and Markdown with `$…$` maths, as a statement is.

A node names the definitions its statement is written in, when it is created (`proof node create --definition <id>`),
and the names change afterwards only by a restatement while Unfixed, as the statement does. A Split's children, a node created under a
parent and a Claim crystallized under one name only the definitions their creator gives, the parent's included only where
the statement uses them (#286): each definition a node names is one of its conditions. What a node says is
its statement, its assumptions and the definitions it names — its Accepted mathematical interface, so they are in its
interface fingerprint (ids only: a decision fixes the definitions it relied on, so under it an id stands for its text).

A definition is Unfixed until a Review decision relies on it (ADR-0021 point 6): until the first decision on a node
naming it, or on a node resting on one. Until then it may be edited, with a reason — by the researcher, or by an agent
if an agent wrote it — and the edit is a restatement of every node naming it: the verdicts there go stale. Once fixed
it is as fixed as those nodes' statements (DEFINITION_FIXED, naming the decision), and a corrected definition is a new
one, named by new nodes. It is removable only while no node names it (DEFINITION_IN_USE). That is the whole trust
story: no edit anywhere can change what a node says under a decision that relied on it. Snapshots freeze the proof,
not the statement, so they don't copy definitions; the review page shows them from the record.

This module is the seam the CLI, the proof map page and `proof_map` call.
"""

from __future__ import annotations

import re

from .domain import Definition, ProofMapNode, utc_now
from .proof_map import DEFINITION_EDITED_EVENT, RESEARCHER, ProofMapError, fixed_by, require_restatable
from .storage import (
    ProjectStore,
    append_event,
    delete_definition,
    get_definition,
    insert_definition,
    list_definitions,
    list_proof_map_nodes,
    update_definition,
)

DEFINITION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _clean(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ProofMapError("DEFINITION_EMPTY", f"a definition's {field} cannot be empty")
    return text


# -- reading -------------------------------------------------------------------------------------


def require_definition(store: ProjectStore, definition_id: str, *, conn=None) -> Definition:
    """The definition under this id, for a caller looking it up (show, edit, remove). Under an id there is none of
    (DEFINITION_NOT_FOUND) it names the ids there are, oldest first, and where to read them, so a guessed id is not
    answered with "add a definition". A statement naming a missing definition is told to add it first
    (`proof_map.create_node`, `restate_node`)."""
    definition = get_definition(store, definition_id, conn=conn)
    if definition is None:
        ids = [known.id for known in list_definitions(store, conn=conn)]
        raise ProofMapError(
            "DEFINITION_NOT_FOUND",
            f"no definition is named {definition_id}; the project's definitions are {', '.join(ids)}"
            " (`proof definition list --json` gives each with its term and text)" if ids
            else f"no definition is named {definition_id}: the project has no definitions",
        )
    return definition


def nodes_naming(store: ProjectStore, definition_id: str, *, conn=None) -> list[str]:
    """The ids of the nodes whose statement is written in this definition (read on `conn` when a writer passes its own)."""
    return [node.id for node in _nodes_naming(store, definition_id, conn=conn)]


def _nodes_naming(store: ProjectStore, definition_id: str, *, conn=None) -> list[ProofMapNode]:
    def scan(c) -> list[ProofMapNode]:
        rows = c.execute("SELECT data FROM proof_map_nodes ORDER BY id").fetchall()
        return [node for node in (ProofMapNode.model_validate_json(row["data"]) for row in rows) if definition_id in node.definitions]

    if conn is not None:
        return scan(conn)
    return [node for node in list_proof_map_nodes(store) if definition_id in node.definitions]  # a read scope's one connection (#43)


def definitions_of(store: ProjectStore, node: ProofMapNode, *, conn=None) -> list[Definition]:
    """The definitions a node names, in its order. Every one exists: none named can be removed."""
    found = [get_definition(store, definition_id, conn=conn) for definition_id in node.definitions]
    return [definition for definition in found if definition is not None]


def all_definitions(store: ProjectStore) -> list[Definition]:
    return list_definitions(store)


def check_named(store: ProjectStore, definition_ids: list[str], *, conn=None) -> list[str]:
    """The ids, each once and in order, after checking that each names a definition (DEFINITION_NOT_FOUND)."""
    seen: list[str] = []
    for definition_id in definition_ids:
        if definition_id in seen:
            continue
        require_definition(store, definition_id, conn=conn)
        seen.append(definition_id)
    return seen


# -- writing -------------------------------------------------------------------------------------


def _wording(text: str) -> str:
    """A definition's text as `add` compares it (#255): its whitespace runs made one space. Nothing mathematical is
    normalized, so `$f$` and `f` are two wordings; a near one is the researcher's to read, never merged."""
    return " ".join(text.split())


def _refuse_a_repeat(store: ProjectStore, text: str, *, conn, apart_from: str | None = None) -> None:
    """Refuse a text another definition already has, whitespace aside, naming that one (DEFINITION_DUPLICATE): one
    condition, written once (#255), whether it is added or edited in (#307). `apart_from`: the definition being edited."""
    same = next((known for known in list_definitions(store, conn=conn) if known.id != apart_from and _wording(known.text) == _wording(text)), None)
    if same is not None:
        raise ProofMapError("DEFINITION_DUPLICATE", f"definition {same.id} ({same.term}) already says this: name it instead",
                            details={"definition_id": same.id})


def add_definition(store: ProjectStore, definition_id: str, *, term: str, text: str, created_by: str = "human") -> Definition:
    """Add a definition under a new id. One whose text another already has, whitespace aside, is refused, naming that one
    (DEFINITION_DUPLICATE): an agent adds definitions too, and one condition written twice would read as two (#255)."""
    if not DEFINITION_ID.fullmatch(definition_id or ""):
        raise ProofMapError("INVALID_DEFINITION_ID", f"definition id {definition_id!r} must be letters, digits, '.', '_' or '-' (at most 64), starting with a letter or digit")
    definition = Definition(id=definition_id, term=_clean(term, "term"), text=_clean(text, "text"), created_by=created_by)
    with store.transaction() as conn:
        if get_definition(store, definition_id, conn=conn) is not None:
            raise ProofMapError("DEFINITION_ALREADY_EXISTS", f"definition {definition_id} already exists")
        _refuse_a_repeat(store, definition.text, conn=conn)
        insert_definition(store, definition, conn=conn)
        append_event(store, "definition_added", f"definition {definition_id}: {definition.term}", entity_id=definition_id,
                     payload=definition.model_dump(mode="json"), conn=conn)
    return definition


def _unused(store: ProjectStore, definition_id: str, conn, doing: str) -> None:
    using = nodes_naming(store, definition_id, conn=conn)
    if using:
        raise ProofMapError(
            "DEFINITION_IN_USE",
            f"definition {definition_id} is named by {', '.join(using)}, and cannot be {doing}; "
            "edit it while it is unfixed, or add a corrected definition under a new id and name it from new nodes",
            details={"nodes": using},
        )


def fixed_by_definition(store: ProjectStore, definition_id: str) -> dict | None:
    """The Review decision that fixed a definition — the first that fixed a node naming it — or None while Unfixed."""
    found = [decided for node_id in nodes_naming(store, definition_id) if (decided := fixed_by(store, node_id)) is not None]
    return min(found, key=lambda decided: decided["decided_at"]) if found else None


def edit_definition(
    store: ProjectStore, definition_id: str, *, term: str | None = None, text: str | None = None, edited_by: str = "human", reason: str = ""
) -> Definition:
    """Change an Unfixed definition (ADR-0021 point 6): the researcher any, an agent one an agent wrote and no node
    of the researcher's names (RESEARCHER_TEXT: the edit would restate the researcher's statement); a fixed one is
    refused (DEFINITION_FIXED). Once a node names it, the edit restates that node and needs a reason. Any change is
    an edit; changing nothing changes and records nothing. Text another definition already has is refused, as on an add
    (DEFINITION_DUPLICATE)."""
    with store.transaction() as conn:
        current = require_definition(store, definition_id, conn=conn)
        update = {}
        if term is not None and _clean(term, "term") != current.term:
            update["term"] = _clean(term, "term")
        if text is not None and _clean(text, "text") != current.text:
            update["text"] = _clean(text, "text")
        if not update:
            return current
        require_restatable(store, what=f"definition {definition_id}", created_by=current.created_by, by=edited_by,
                           fixed=fixed_by_definition(store, definition_id), fixed_code="DEFINITION_FIXED")
        if "text" in update:
            _refuse_a_repeat(store, update["text"], conn=conn, apart_from=definition_id)
        naming = _nodes_naming(store, definition_id, conn=conn)
        theirs = [node.id for node in naming if node.created_by == RESEARCHER]
        if edited_by != RESEARCHER and theirs:
            raise ProofMapError(
                "RESEARCHER_TEXT",
                f"definition {definition_id} is named by the researcher's {', '.join(theirs)}: editing it would restate their text, so only the researcher edits it",
                details={"nodes": theirs},
            )
        if naming and not (reason or "").strip():
            raise ProofMapError("RESTATE_REASON_REQUIRED", f"definition {definition_id} is named by a node: editing it restates that node, so say why with --reason")
        changed = current.model_copy(update={**update, "updated_at": utc_now()})
        update_definition(store, changed, conn=conn)
        append_event(store, DEFINITION_EDITED_EVENT, f"definition {definition_id} edited by {edited_by}", entity_id=definition_id,
                     payload={"by": edited_by, **update, "from": {key: getattr(current, key) for key in update}, "to": update,
                              **({"reason": reason.strip()} if (reason or "").strip() else {})}, conn=conn)
    return changed


def remove_definition(store: ProjectStore, definition_id: str, *, removed_by: str = "human") -> Definition:
    """Remove a definition no node names."""
    with store.transaction() as conn:
        current = require_definition(store, definition_id, conn=conn)
        _unused(store, definition_id, conn, "removed")
        delete_definition(store, definition_id, conn=conn)
        append_event(store, "definition_removed", f"definition {definition_id} removed by {removed_by}", entity_id=definition_id,
                     payload={"by": removed_by, **current.model_dump(mode="json")}, conn=conn)
    return current
