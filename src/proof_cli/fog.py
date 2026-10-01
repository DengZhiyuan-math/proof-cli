"""Proof fog: the flat list of difficulties not yet precise enough to be a Claim (ADR-0008, spec #136).

A fog item lives outside the proof map. It may be *near* one or more nodes — an informal
"about this" pointer that is never a dependency and never touches a node's three state axes,
the frontier or Acceptance. Anyone, agents included, adds, edits, drops (with a reason) and
reopens items: fog is not a mathematical judgment, so nothing here is gated. Its record is
SQLite; its vault folder `proofs/fog/<fog-id>/` is implied by the id and created only when
something is put there.

An **Experiment** is a numerical run recorded against an open item — what was computed, what it
showed (supports / refutes / inconclusive / error), who ran it, where its files are. It never
changes the item's status: dropping or crystallizing is always an explicit call, the same
principle as an Evidence check never changing Acceptance.

**Crystallize** turns an open item into a Claim in one transaction: with a parent, it is
exactly a single-child Split of that parent (the same code path, every Split rule kept); without
one, an ordinary node creation. The item then reads `crystallized` with the node's id — it
leaves the fog list, nothing is deleted — and the node's page says "crystallized from fog-N".

This module is the seam the CLI and the proof map page call; `proof_map` knows nothing of fog.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .domain import ExperimentOutcome, FogExperiment, FogItem, FogStatus, ProofMapNode, fog_id, utc_now
from .proof_map import ProofMapError, create_node, remove_new_node_folders_on_rollback, require_node, split_node
from .storage import (
    ProjectStore,
    append_event,
    get_fog_item,
    insert_fog_experiment,
    insert_fog_item,
    list_fog_experiments,
    list_fog_items,
    next_fog_number,
    update_fog_item,
)
from .vault import vault_dir

FOG_DIR = "fog"


def fog_folder(root: Path, fog_id: str) -> Path:
    """Where a fog item's own files go (`proofs/fog/<fog-id>/`): implied by the id, created on demand."""
    return vault_dir(root) / FOG_DIR / fog_id


# -- reading -------------------------------------------------------------------------------------


def require_fog(store: ProjectStore, fog_id: str, *, conn=None) -> FogItem:
    """The item, or FOG_NOT_FOUND. A writer passes its transaction's `conn`, so the check and the write are one."""
    item = get_fog_item(store, fog_id, conn=conn)
    if item is None:
        raise ProofMapError("FOG_NOT_FOUND", f"no fog item is named {fog_id}")
    return item


def list_fog(store: ProjectStore, *, include_all: bool = False) -> list[FogItem]:
    """Open items by id, or with `include_all` every item, dropped and crystallized ones too."""
    return list_fog_items(store) if include_all else list_fog_items(store, status=FogStatus.open.value)


def list_experiments(store: ProjectStore, fog_id: str) -> list[FogExperiment]:
    """An item's Experiments, oldest first, each marked `missing` when its file is gone."""
    return [
        experiment.model_copy(update={"missing": experiment.path is not None and not (store.root / experiment.path).exists()})
        for experiment in list_fog_experiments(store, fog_id)
    ]


def fog_near(store: ProjectStore, node_id: str) -> list[FogItem]:
    """The open items near a node: its fog context, as its page and `node show` list it."""
    return [item for item in list_fog(store) if node_id in item.near]


def crystallized_from(store: ProjectStore, node_id: str) -> FogItem | None:
    """The fog item a node came out of, looked up in the fog table: the node itself carries no field."""
    items = list_fog_items(store, node_id=node_id)
    return items[0] if items else None


def last_dropped(store: ProjectStore) -> FogItem | None:
    """The most recently dropped item: what `project analyze` reads as the abandoned route."""
    dropped = [item for item in list_fog_items(store, status=FogStatus.dropped.value) if item.dropped_at is not None]
    return max(dropped, key=lambda item: item.dropped_at) if dropped else None


def fog_view(store: ProjectStore, item: FogItem) -> dict:
    """An item as `fog show` and the page report it: its record, its Experiments (newest first), the folder."""
    experiments = list_experiments(store, item.id)
    folder = fog_folder(store.root, item.id)
    return {
        **item.model_dump(mode="json"),
        "experiments": [experiment.model_dump(mode="json") for experiment in reversed(experiments)],
        "experiment_count": len(experiments),
        "latest_experiment": experiments[-1].model_dump(mode="json") if experiments else None,
        "folder": folder.relative_to(store.root).as_posix(),
        "folder_exists": folder.is_dir(),
    }


# -- adding, editing, dropping, reopening ------------------------------------------------------------


def _not_open(item: FogItem, doing: str) -> ProofMapError:
    if item.status == FogStatus.crystallized:
        return ProofMapError(
            "FOG_NOT_OPEN", f"{item.id} is crystallized as node {item.node_id}; {doing} belongs to that node now", details={"status": item.status.value, "node_id": item.node_id}
        )
    return ProofMapError("FOG_NOT_OPEN", f"{item.id} is dropped ({item.reason}); `proof fog reopen {item.id}` first, then {doing}", details={"status": item.status.value})


def _require_open(item: FogItem, doing: str) -> None:
    if item.status != FogStatus.open:
        raise _not_open(item, doing)


def _checked_near(store: ProjectStore, near) -> list[str]:
    """Distinct, existing node ids of any kind and any state: `near` says "about", never "depends on"."""
    ids = list(dict.fromkeys(str(node_id).strip() for node_id in (near or ()) if str(node_id).strip()))
    for node_id in ids:
        require_node(store, node_id)
    return ids


def add_fog(store: ProjectStore, text: str, *, near=(), notes: str = "", created_by: str = "human") -> FogItem:
    """Add an open item. Ungated; `created_by` records who (a person, or an agent's name)."""
    if not text.strip():
        raise ProofMapError("FOG_TEXT_REQUIRED", "a fog item needs its text: the difficulty, in words")
    near_ids = _checked_near(store, near)
    with store.transaction() as conn:
        item = FogItem(id=fog_id(next_fog_number(store, conn=conn)), text=text.strip(), notes=notes or "", near=near_ids, created_by=created_by or "human")
        insert_fog_item(store, item, conn=conn)
        append_event(store, "proof_fog_added", f"added {item.id}: {item.text}", entity_id=item.id, payload={"near": near_ids, "created_by": item.created_by}, conn=conn)
    return item


def edit_fog(store: ProjectStore, fog_id: str, *, text: str | None = None, near=None, notes: str | None = None, edited_by: str = "human") -> FogItem:
    """Change an open item's text, notes or near nodes; whatever isn't given stays. The id never changes."""
    if text is not None and not text.strip():
        raise ProofMapError("FOG_TEXT_REQUIRED", "a fog item needs its text: the difficulty, in words")
    with store.transaction() as conn:
        item = require_fog(store, fog_id, conn=conn)
        _require_open(item, "edit it")
        changes: dict = {"updated_at": utc_now()}
        if text is not None:
            changes["text"] = text.strip()
        if notes is not None:
            changes["notes"] = notes
        if near is not None:
            changes["near"] = _checked_near(store, near)
        edited = item.model_copy(update=changes)
        update_fog_item(store, edited, conn=conn)
        append_event(store, "proof_fog_edited", f"edited {item.id}", entity_id=item.id, payload={"edited_by": edited_by, "fields": sorted(k for k in changes if k != "updated_at")}, conn=conn)
    return edited


def drop_fog(store: ProjectStore, fog_id: str, *, reason: str, dropped_by: str = "human") -> FogItem:
    """Give an item up, saying why. Reversible with `reopen_fog`."""
    if not (reason or "").strip():
        raise ProofMapError("FOG_REASON_REQUIRED", f"dropping {fog_id} needs a reason: why this direction is given up")
    with store.transaction() as conn:
        item = require_fog(store, fog_id, conn=conn)
        _require_open(item, "drop it")
        now = utc_now()
        dropped = item.model_copy(update={"status": FogStatus.dropped, "dropped_by": dropped_by or "human", "dropped_at": now, "reason": reason.strip(), "updated_at": now})
        update_fog_item(store, dropped, conn=conn)
        append_event(store, "proof_fog_dropped", f"dropped {item.id}: {reason.strip()}", entity_id=item.id, payload={"dropped_by": dropped.dropped_by, "reason": dropped.reason}, conn=conn)
    return dropped


def reopen_fog(store: ProjectStore, fog_id: str, *, by: str = "human") -> FogItem:
    """Take a dropped item back, clearing its drop record. An open item is left as it is; a crystallized one never reopens."""
    with store.transaction() as conn:
        item = require_fog(store, fog_id, conn=conn)
        if item.status == FogStatus.open:
            return item
        if item.status == FogStatus.crystallized:
            raise _not_open(item, "reopening")
        reopened = item.model_copy(update={"status": FogStatus.open, "dropped_by": None, "dropped_at": None, "reason": None, "updated_at": utc_now()})
        update_fog_item(store, reopened, conn=conn)
        append_event(store, "proof_fog_reopened", f"reopened {item.id}", entity_id=item.id, payload={"by": by}, conn=conn)
    return reopened


# -- Experiments -----------------------------------------------------------------------------------------


def _checked_path(store: ProjectStore, path: str | None) -> str | None:
    """A path under proofs/, relative to the project, that exists right now; None when none was given.

    A symlink under proofs/ pointing elsewhere passes: the check keeps a cooperative agent's
    records tidy, it is not a boundary against a hostile one (ADR-0011)."""
    if path is None or not str(path).strip():
        return None
    given = Path(str(path).strip())
    if given.is_absolute() or ".." in given.parts:
        raise ProofMapError("FOG_EXPERIMENT_PATH_INVALID", f"an Experiment's path is relative to the project and under proofs/, not {path!r}")
    if len(given.parts) < 2 or given.parts[0] != vault_dir(store.root).name:
        raise ProofMapError("FOG_EXPERIMENT_PATH_INVALID", f"an Experiment's files live under proofs/ (the vault), not at {path!r}")
    if not (store.root / given).exists():
        raise ProofMapError("FOG_EXPERIMENT_PATH_INVALID", f"nothing is at {path!r}: an Experiment names files that exist")
    return given.as_posix()


def record_experiment(store: ProjectStore, fog_id: str, outcome: str, *, summary: str, run_by: str, path: str | None = None) -> FogExperiment:
    """Record a run against an open item: only what was really run, by whoever ran it. Changes the item's status not at all."""
    try:
        resolved = ExperimentOutcome(outcome)
    except ValueError as exc:
        raise ProofMapError("INVALID_OUTCOME", f"'{outcome}' is not an Experiment outcome; expected one of: {', '.join(o.value for o in ExperimentOutcome)}") from exc
    if not (summary or "").strip():
        raise ProofMapError("FOG_SUMMARY_REQUIRED", "an Experiment says what was computed and what it showed (--summary)")
    if not (run_by or "").strip():
        raise ProofMapError("FOG_RUN_BY_REQUIRED", "an Experiment records who ran it (--run-by)")
    checked_path = _checked_path(store, path)
    with store.transaction() as conn:
        item = require_fog(store, fog_id, conn=conn)
        _require_open(item, "recording an experiment")
        experiment = insert_fog_experiment(
            store, FogExperiment(fog_id=item.id, seq=0, outcome=resolved, summary=(summary or "").strip(), run_by=run_by.strip(), path=checked_path), conn=conn
        )
        append_event(
            store, "proof_fog_experiment_recorded", f"{item.id} experiment {experiment.seq}: {resolved.value}",
            entity_id=item.id, payload={"seq": experiment.seq, "outcome": resolved.value, "run_by": experiment.run_by, "path": checked_path}, conn=conn,
        )
    return experiment


# -- Crystallize -------------------------------------------------------------------------------------------


class CrystallizeResult(BaseModel):
    node: ProofMapNode
    fog: FogItem
    # a reminder when Experiment files sit in an agent's scratch/ folder: they stay there, commit them to keep them
    reminder: str = ""


def _scratch_owner(path: str | None) -> str | None:
    """The node whose scratch/ folder holds an Experiment's file (`proofs/<node>/scratch/…`), or None."""
    parts = Path(path).parts if path else ()
    return parts[1] if len(parts) > 3 and parts[0] == "proofs" and parts[2] == "scratch" else None


def _resolve_parent(item: FogItem, *, parent: str | None, no_parent: bool) -> str | None:
    if parent is not None and no_parent:
        raise ProofMapError("FOG_FLAG_CONFLICT", "crystallize takes either --parent or --no-parent, not both")
    if parent is not None:
        return parent
    if no_parent or not item.near:
        return None
    if len(item.near) == 1:
        return item.near[0]
    raise ProofMapError(
        "FOG_PARENT_AMBIGUOUS",
        f"{item.id} is near {len(item.near)} nodes ({', '.join(item.near)}); say which is the parent with --parent, or --no-parent for none",
        details={"candidates": list(item.near)},
    )


def crystallize_fog(
    store: ProjectStore,
    fog_id: str,
    node_id: str,
    statement: str,
    *,
    parent: str | None = None,
    no_parent: bool = False,
    reassign: bool = False,
    assumptions: list[str] | None = None,
    display_label: str = "",
    created_by: str = "human",
) -> CrystallizeResult:
    """State an open fog item as a Claim, in one transaction (ADR-0008, #126).

    With a parent (given, or the item's single near node) the new Claim is a
    single-child Split of it — the same path, so every Split rule holds:
    `derived_from`, the child appended to the parent's dependencies, the
    claimant check and `reassign`, an imported result or Rejected or Accepted
    parent refused. With none it is an ordinary Claim. The statement is
    written here, never taken from the item's text. The item keeps its text,
    notes, near nodes and Experiments and reads `crystallized`; a refusal
    anywhere leaves it open and creates no node.
    """
    with store.transaction() as conn:
        # the checks and the item's change on the write lock: two crystallizes of one item can't both pass
        item = require_fog(store, fog_id, conn=conn)
        _require_open(item, "crystallizing it")
        parent_id = _resolve_parent(item, parent=parent, no_parent=no_parent)
        # the item first: if the node can't be made, the whole transaction rolls back, item included
        update_fog_item(store, item.model_copy(update={"status": FogStatus.crystallized, "node_id": node_id, "updated_at": utc_now()}), conn=conn)
        spec = {"id": node_id, "statement": statement, "assumptions": list(assumptions or []), "display_label": display_label}
        if parent_id is not None:
            (node,) = split_node(store, parent_id, [spec], created_by=created_by, reassign=reassign)  # cleans its child folder up on rollback
        else:
            # a free-standing Claim writes its proof.tex before this transaction commits: the same cleanup a Split registers
            remove_new_node_folders_on_rollback(store, [node_id])
            node = create_node(store, node_id=node_id, kind="claim", statement=statement, display_label=display_label, assumptions=list(assumptions or []), created_by=created_by)
        append_event(
            store, "proof_fog_crystallized", f"crystallized {item.id} as {node_id}",
            entity_id=item.id, payload={"node_id": node_id, "parent": parent_id, "created_by": created_by}, conn=conn,
        )
    crystallized = require_fog(store, fog_id)
    owners = sorted({owner for owner in (_scratch_owner(e.path) for e in list_fog_experiments(store, fog_id)) if owner})
    reminder = ""
    if owners:
        reminder = "Experiment files stay where they are, in " + ", ".join(f"proofs/{owner}/scratch/" for owner in owners) + "; commit them to git if they should be kept."
    return CrystallizeResult(node=node, fog=crystallized, reminder=reminder)
