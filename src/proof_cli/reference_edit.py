"""Fixing a citation's bibliography in place (ADR-0021 audit section 2, issue #202).

`edit_reference` corrects a ReferenceRecord's bibliographic fields under the same id: what isn't
given keeps its value, `id`, `created_by` and `created_at` never change, and each edit is one
`reference_edited` event naming the editor, the reason, and every changed field's old and new value.

An Imported result's statement, `source_locator`, `source_version` and `reference_id` are its
mathematical interface (ADR-0005), not bibliography: they are refused here
(REFERENCE_FIELD_NOT_EDITABLE). Citing another work or another version is a new Imported result.

A Trust rule reads the citation as it is now (ADR-0014), so a researcher's import may meet or stop
meeting a rule after an edit; under ADR-0022 an edit gives an agent's import no trust.
"""

from __future__ import annotations

from typing import Any

from .proof_map import ProofMapError
from .references import ReferenceRecord, ReferenceSourceType, utc_now
from .storage import ProjectStore, append_event, get_reference, store_reference

REFERENCE_EDITED_EVENT = "reference_edited"

# the bibliography: what a correction may change
EDITABLE_FIELDS = ("title", "authors", "year", "source_type", "origin", "bibliographic_source", "identifier", "url", "notes")
# the Imported result's mathematical interface (ADR-0005): a new Imported result, never an edit
INTERFACE_FIELDS = ("statement", "source_locator", "source_version", "reference_id")


def _value(field: str, value: Any) -> Any:
    if field == "source_type":
        try:
            return ReferenceSourceType(value)
        except ValueError as exc:
            valid = ", ".join(member.value for member in ReferenceSourceType)
            raise ProofMapError("INVALID_SOURCE_TYPE", f"'{value}' is not a valid source type; expected one of: {valid}") from exc
    if field == "authors":
        return [author.strip() for author in value if author.strip()]
    if field == "title" and not str(value).strip():
        raise ProofMapError("REFERENCE_TITLE_REQUIRED", "a citation keeps a title")
    return value.strip() if isinstance(value, str) else value


def _json(value: Any) -> Any:
    return value.value if isinstance(value, ReferenceSourceType) else value


def edit_reference(store: ProjectStore, reference_id: str, changes: dict[str, Any], *, edited_by: str = "human", reason: str = "") -> ReferenceRecord:
    """Apply `changes` (field → new value; a field left out keeps its value) to the citation. Changing
    nothing changes and records nothing; any change needs a reason."""
    for field in changes:
        if field in INTERFACE_FIELDS:
            raise ProofMapError(
                "REFERENCE_FIELD_NOT_EDITABLE",
                f"{field} is an imported result's mathematical interface, not bibliography: cite another work or version as a new imported result",
                details={"field": field},
            )
        if field not in EDITABLE_FIELDS:
            raise ProofMapError(
                "REFERENCE_FIELD_NOT_EDITABLE",
                f"{field} is not a citation's bibliography; editable: {', '.join(EDITABLE_FIELDS)}",
                details={"field": field},
            )
    with store.transaction() as conn:
        current = get_reference(store, reference_id, conn=conn)
        if current is None:
            raise ProofMapError("REFERENCE_NOT_FOUND", f"no reference has the id {reference_id}")
        update = {}
        for field, value in changes.items():
            new = _value(field, value)
            if new != getattr(current, field):
                update[field] = new
        if not update:
            return current
        if not (reason or "").strip():
            raise ProofMapError("REFERENCE_EDIT_REASON_REQUIRED", f"say why reference {reference_id} is corrected, with --reason")
        changed = current.model_copy(update={**update, "updated_at": utc_now()})
        store_reference(store, changed)  # joins this transaction
        fields = {field: {"old": _json(getattr(current, field)), "new": _json(new)} for field, new in update.items()}
        append_event(
            store,
            REFERENCE_EDITED_EVENT,
            f"reference {reference_id} edited by {edited_by}: {', '.join(fields)}",
            entity_id=reference_id,
            payload={"reference_id": reference_id, "by": edited_by, "reason": reason.strip(), "fields": fields},
            conn=conn,
        )
    return changed
