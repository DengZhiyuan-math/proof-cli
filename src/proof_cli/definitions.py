"""Definitions: the named text a project's node statements are written in (ADR-0020).

A statement alone could not say what its symbols are: a model's setting, a definition, notation all had to be crammed
into it, or were left out and every reader — the researcher and each agent — had to guess. A **Definition** is that text,
once, under a name: an id, a term to show, and Markdown with `$…$` maths, as a statement is.

A node names the definitions its statement is written in, when it is created (`proof node create --definition <id>`),
and the names never change afterwards, as the statement never does. A Split's children, and a node created under a
parent, name their parent's definitions too: a Claim of a Theorem is about the Theorem's objects. What a node says is
its statement, its assumptions and the definitions it names — its Accepted mathematical interface, so they are in its
interface fingerprint (ids only: a definition a node names can no longer change).

A definition is editable and removable only while no node names it (DEFINITION_IN_USE); once one does, it is as fixed
as that node's statement, and a corrected definition is a new one, named by new nodes. That is the whole trust story:
no edit anywhere can change what an existing node, Accepted or not, says. Snapshots freeze the proof, not the
statement, so they don't copy definitions; the review page shows them from the record, where they cannot move.

This module is the seam the CLI, the proof map page and `proof_map` call.
"""

from __future__ import annotations

import re

from .domain import Definition, ProofMapNode, utc_now
from .proof_map import ProofMapError
from .storage import (
    ProjectStore,
    append_event,
    delete_definition,
    get_definition,
    insert_definition,
    list_definitions,
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
    definition = get_definition(store, definition_id, conn=conn)
    if definition is None:
        raise ProofMapError("DEFINITION_NOT_FOUND", f"no definition is named {definition_id}; add it with `proof definition add`")
    return definition


def nodes_naming(store: ProjectStore, definition_id: str, *, conn=None) -> list[str]:
    """The ids of the nodes whose statement is written in this definition (read on `conn` when a writer passes its own)."""
    def scan(c) -> list[str]:
        rows = c.execute("SELECT data FROM proof_map_nodes ORDER BY id").fetchall()
        return [node.id for node in (ProofMapNode.model_validate_json(row["data"]) for row in rows) if definition_id in node.definitions]

    if conn is not None:
        return scan(conn)
    with store.connect() as own:
        return scan(own)


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


def add_definition(store: ProjectStore, definition_id: str, *, term: str, text: str, created_by: str = "human") -> Definition:
    if not DEFINITION_ID.fullmatch(definition_id or ""):
        raise ProofMapError("INVALID_DEFINITION_ID", f"definition id {definition_id!r} must be letters, digits, '.', '_' or '-' (at most 64), starting with a letter or digit")
    definition = Definition(id=definition_id, term=_clean(term, "term"), text=_clean(text, "text"), created_by=created_by)
    with store.transaction() as conn:
        if get_definition(store, definition_id, conn=conn) is not None:
            raise ProofMapError("DEFINITION_ALREADY_EXISTS", f"definition {definition_id} already exists")
        insert_definition(store, definition, conn=conn)
        append_event(store, "definition_added", f"definition {definition_id}: {definition.term}", entity_id=definition_id,
                     payload=definition.model_dump(mode="json"), conn=conn)
    return definition


def _unused(store: ProjectStore, definition_id: str, conn, doing: str) -> None:
    using = nodes_naming(store, definition_id, conn=conn)
    if using:
        raise ProofMapError(
            "DEFINITION_IN_USE",
            f"definition {definition_id} is named by {', '.join(using)}: it is as fixed as their statements, and cannot be {doing}; "
            "add a corrected definition under a new id and name it from new nodes",
            details={"nodes": using},
        )


def edit_definition(store: ProjectStore, definition_id: str, *, term: str | None = None, text: str | None = None, edited_by: str = "human") -> Definition:
    """Change a definition no node names yet. Changing nothing changes and records nothing."""
    with store.transaction() as conn:
        current = require_definition(store, definition_id, conn=conn)
        update = {}
        if term is not None and _clean(term, "term") != current.term:
            update["term"] = _clean(term, "term")
        if text is not None and _clean(text, "text") != current.text:
            update["text"] = _clean(text, "text")
        if not update:
            return current
        _unused(store, definition_id, conn, "edited")
        changed = current.model_copy(update={**update, "updated_at": utc_now()})
        update_definition(store, changed, conn=conn)
        append_event(store, "definition_edited", f"definition {definition_id} edited by {edited_by}", entity_id=definition_id,
                     payload={"by": edited_by, **update}, conn=conn)
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
