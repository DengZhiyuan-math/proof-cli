from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import typer

from .commands import (
    bug_scan_data,
    explain_apply_data,
    export_data,
    provenance_show_data,
    memory_list_data,
    reference_list_data,
    search_data,
    theorem_apply_data,
    theorem_extract_data,
    theorem_list_data,
    cmd_blocker_add,
    cmd_blocker_list,
    cmd_branch_compare,
    cmd_branch_create,
    cmd_branch_list,
    cmd_branch_merge,
    cmd_export,
    cmd_comment_add,
    cmd_comment_list,
    cmd_contributor_list,
    cmd_exchange_export,
    cmd_exchange_import,
    cmd_proof_asset_list,
    cmd_proof_asset_publish,
    cmd_proof_asset_review,
    cmd_proof_asset_show,
    cmd_proof_automate_plan,
    cmd_proof_automate_review,
    cmd_proof_automate_run,
    cmd_proof_automate_trace,
    cmd_proof_benchmark_run,
    cmd_proof_bug_list,
    cmd_proof_bug_scan,
    cmd_proof_bug_show,
    cmd_proof_debug_generate,
    cmd_proof_debug_list,
    cmd_proof_evidence_show,
    cmd_proof_explain_apply,
    cmd_proof_obligation_derive,
    cmd_proof_reason,
    cmd_proof_revalidate,
    cmd_proof_repair_mark,
    cmd_proof_retrieve,
    cmd_proof_review_suspicion,
    cmd_proof_formalize_edit,
    cmd_proof_formalize_recommend,
    cmd_proof_formalize_show,
    cmd_proof_trace_dependency,
    cmd_proof_trace_machine_check,
    cmd_proof_verify_queue,
    cmd_proof_verify_result,
    cmd_proof_verify_run,
    cmd_proof_verify_stale,
    cmd_proof_verify_status,
    cmd_proof_pack_install,
    cmd_proof_pack_list,
    cmd_proof_pack_show,
    cmd_proof_pack_update,
    cmd_proof_policy_list,
    cmd_proof_policy_set,
    cmd_proof_recommend,
    cmd_project_analyze,
    cmd_review_decide,
    cmd_review_list,
    cmd_review_request,
    cmd_role_show,
    cmd_handoff_create,
    cmd_handoff_inspect,
    cmd_proof_reuse_show,
    cmd_goal_list,
    cmd_goal_open,
    cmd_goal_set,
    cmd_history,
    cmd_init,
    cmd_obligation_add,
    cmd_obligation_list,
    cmd_memory_add,
    cmd_memory_list,
    cmd_memory_show,
    cmd_publication_export,
    cmd_publication_list,
    cmd_publication_release,
    cmd_publication_set,
    cmd_publication_show,
    cmd_publication_view,
    cmd_publication_withdraw,
    publication_export_json,
    publication_list_data,
    publication_release_data,
    publication_set_data,
    publication_show_data,
    publication_view_data,
    publication_withdraw_data,
    cmd_proof_provenance_show,
    cmd_reference_import,
    cmd_reference_list,
    cmd_reference_show,
    cmd_search,
    cmd_snapshot,
    cmd_status,
    cmd_theorem_add,
    cmd_theorem_apply,
    cmd_theorem_extract,
    cmd_theorem_ground,
    cmd_theorem_list,
    cmd_theorem_show,
    get_store,
)
from .envelope import dump_envelope, error_envelope, success_envelope
from .contract import ProofGroup
from .collaboration import summarize_review_record
from .storage import read_scoped
from .proof_map import (
    ProofMapError,
    add_dependency,
    claim_node,
    create_node,
    dependency_details,
    move_dependency,
    remove_dependency,
    get_acceptance_state,
    get_blocked_reason,
    get_frontier,
    get_integrity_state,
    get_workflow_state,
    list_candidate_proofs,
    list_challenges,
    list_integrity_warnings,
    list_nodes,
    node_citation,
    open_challenge,
    record_evidence_check,
    release_node,
    require_challenge,
    request_review,
    require_node,
    split_node,
)
from .vault import working_proof_path
from .rendering import (
    render_candidate_proof,
    render_challenge,
    render_challenge_list,
    render_claim,
    render_frontier,
    render_proof_map_node,
    render_proof_map_node_list,
)
from .review import render_verification_output

app = typer.Typer(
    add_completion=False,
    help="Mathematical Proof CLI: a proof map of nodes (theorems, lemmas, claims, imported results), each with its own LaTeX proof, "
    "reviewed by the researcher on the proof map page. Start with `proof node --help` and `proof frontier`.",
    cls=ProofGroup,  # the agent-facing contract: see contract.py
)
# Every command's project: --root, else $PROOF_ROOT, else the current folder. The one root
# convention (ADR-0011 point 8): a studio's agent runs in its node's folder with PROOF_ROOT
# set to the project, so a `proof` call from there never starts a nested project.
ROOT_OPTION = typer.Option(".", "--root", envvar="PROOF_ROOT", help="The proof project (default: $PROOF_ROOT, then the current folder)")
PROOF_MAP_PANEL = "Proof map"
LEGACY_PANEL = "Legacy (before the proof map; kept for old projects)"
asset_app = typer.Typer(help="Reusable asset workflows")
pack_app = typer.Typer(help="Domain pack workflows")
policy_app = typer.Typer(help="Automation policy workflows")
recommend_app = typer.Typer(help="Cross-project recommendation workflows")
reuse_app = typer.Typer(help="Reuse outcome workflows")
automate_app = typer.Typer(help="Supervised automation workflows")
benchmark_app = typer.Typer(help="Automation evaluation workflows")
project_app = typer.Typer(help="Project diagnostics workflows")
goal_app = typer.Typer(help="(legacy) Goal operations; a goal becomes a Claim node")
theorem_app = typer.Typer(help="(legacy) Theorem-contract registry; the proof map's nodes replace it")
node_app = typer.Typer(help="Proof map node operations")
node_evidence_app = typer.Typer(help="Evidence check workflows")
challenge_app = typer.Typer(help="Challenge workflows")
obligation_app = typer.Typer(help="(legacy) Proof-obligation queue; an obligation is a Claim node now")
blocker_app = typer.Typer(help="(legacy) Blocker tracking")
reference_app = typer.Typer(help="Reference workflows")
memory_app = typer.Typer(help="Memory workflows")
publication_app = typer.Typer(help="Publication workflows")
provenance_app = typer.Typer(help="Provenance workflows")
bug_app = typer.Typer(help="Proof bug workflows")
debug_app = typer.Typer(help="Proof debug workflows")
review_app = typer.Typer(help="Proof review workflows")
map_app = typer.Typer(help="The proof map page: the map, each node, and where Human Review decisions are made (ADR-0008, ADR-0010)")
contributor_app = typer.Typer(help="Contributor workflows")
role_app = typer.Typer(help="Role workflows")
comment_app = typer.Typer(help="Comment workflows")
branch_app = typer.Typer(help="Branch workflows")
exchange_app = typer.Typer(help="Exchange workflows")
handoff_app = typer.Typer(help="Handoff workflows")
repair_app = typer.Typer(help="Proof repair workflows")
trace_app = typer.Typer(help="Dependency tracing workflows")
evidence_app = typer.Typer(help="Evidence inspection workflows")
explain_app = typer.Typer(help="Theorem explanation workflows")
formalize_app = typer.Typer(help="Formal bridge workflows")
verify_app = typer.Typer(help="(legacy) Machine-check log; advisory, and no backend runs (#27)")


def _root(path: str | None) -> Path:
    return Path(path or ".")


@app.command(rich_help_panel=PROOF_MAP_PANEL)
def init(root: str = ROOT_OPTION) -> None:
    """Start a proof project in ROOT."""
    typer.echo(cmd_init(_root(root)))


@app.command()
def status(root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_status(_root(root)))


@app.command()
def snapshot(root: str = ROOT_OPTION, note: str = "", json_output: bool = typer.Option(False, "--json")) -> None:
    """A snapshot of the project state. Its trust-sensitive calls are legacy (ADR-0012)."""
    _emit_legacy_json("snapshot", json_output, lambda: cmd_snapshot(_root(root), handoff_note=note))


@app.command()
def history(root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_history(_root(root)))


@app.command()
def export(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Export the project's state as text. Its callable, trust and review states are legacy (ADR-0012)."""
    _emit_legacy("export", json_output, lambda: cmd_export(_root(root)), lambda: export_data(_root(root)))


@app.command()
def search(query: str, root: str = ROOT_OPTION, limit: int = 10, json_output: bool = typer.Option(False, "--json")) -> None:
    """Search what the project holds for QUERY. Under --json, a candidate's trust level is legacy (ADR-0012)."""
    if json_output:
        typer.echo(dump_envelope(success_envelope("search", search_data(query, _root(root), limit=limit))))
        return
    typer.echo(cmd_search(query, _root(root), limit=limit))


@app.command()
def retrieve(query: str, root: str = ROOT_OPTION, limit: int = 10, json_output: bool = typer.Option(False, "--json")) -> None:
    """Rank what the project holds for QUERY. A candidate's trust level is legacy (ADR-0012)."""
    _emit_legacy_json("retrieve", json_output, lambda: cmd_proof_retrieve(query, _root(root), limit=limit))


@app.command()
def reason(theorem_id: str, root: str = ROOT_OPTION, notes: str = "") -> None:
    typer.echo(cmd_proof_reason(theorem_id, _root(root), notes=notes))


def _with_state_axes(store, node) -> dict:
    """A node under --json, with its three state axes (ADR-0002)."""
    return {
        **node.model_dump(mode="json"),
        "workflow_state": get_workflow_state(store, node.id),
        "acceptance_state": get_acceptance_state(store, node.id),
        "integrity_state": get_integrity_state(store, node.id),
    }


@app.command(rich_help_panel=PROOF_MAP_PANEL)
@read_scoped
def frontier(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """The open, unblocked, unclaimed nodes: what an agent could claim right now."""
    store = get_store(_root(root))
    nodes = get_frontier(store)
    if json_output:
        typer.echo(dump_envelope(success_envelope("frontier", [_with_state_axes(store, node) for node in nodes])))
        return
    typer.echo(render_frontier(nodes))


@app.command(rich_help_panel=LEGACY_PANEL)
def revalidate(source_id: str, root: str = ROOT_OPTION, backend_target: str = "", notes: str = "") -> None:
    """(legacy) Re-queue a stale verification fragment. A node's dependency is re-reviewed on the proof map page instead."""
    typer.echo(
        render_verification_output(
            f"revalidate {source_id}",
            cmd_proof_revalidate(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


def _emit_legacy(command: str, json_output: bool, text, data) -> None:
    """A frozen legacy command's output (ADR-0012): its text, or under --json its data in one
    envelope. Either way it carries the legacy notice; a missing target is NOT_FOUND."""
    if not json_output:
        typer.echo(text())
        return
    payload = data()
    if payload is None:
        typer.echo(dump_envelope(error_envelope(command, "NOT_FOUND", text())))
        raise typer.Exit(code=1)
    typer.echo(dump_envelope(success_envelope(command, payload)))


def _legacy_input_error(command: str, exc: ValueError, json_output: bool) -> None:
    if json_output:
        typer.echo(dump_envelope(error_envelope(command, "INVALID_INPUT", str(exc))))
    else:
        typer.echo(f"Error: {exc}")
    raise typer.Exit(code=1)


def _emit_legacy_json(command: str, json_output: bool, text) -> None:
    """`_emit_legacy` for a command whose text is already its JSON: under --json, that JSON is the data."""
    output = text()
    try:
        data = json.loads(output) if json_output else None
    except ValueError:
        data = None
    _emit_legacy(command, json_output, lambda: output, lambda: data)


def _emit_node(node, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, node.model_dump(mode="json"))))
    else:
        typer.echo(render_proof_map_node(node))


def human_review_required(root: str, *, command: str, kind: str, target_id: str, node_id: str | None, json_output: bool) -> None:
    """Every Human Review decision is made on the proof map page, never here (ADR-0010): say where, and fail."""
    from .webapp.server import project_url

    # not a project yet: nothing to decide, and a refusal shouldn't create one
    url = project_url(get_store(_root(root)), node_id) if (_root(root) / ".proof").exists() else None
    _emit_node_error(
        ProofMapError(
            "HUMAN_REVIEW_REQUIRED",
            f"{kind} on {target_id} is a Human Review decision: the researcher makes it on the proof map page"
            f"{f', at {url}' if url else ''} (run `{('proof map open ' + node_id) if node_id else 'proof map open'}`)",
            details={"kind": kind, "target_id": target_id, "url": url},
        ),
        json_output,
        command=command,
    )
    raise typer.Exit(code=1)


def _emit_node_error(exc: ProofMapError, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(error_envelope(command, exc.code, exc.message, details=exc.details or None)))
    else:
        detail_suffix = ""
        if exc.details:
            detail_suffix = " (" + ", ".join(f"{key}={value}" for key, value in exc.details.items()) + ")"
        typer.echo(f"Error: {exc.message}{detail_suffix}")


def _emit_claim(claim, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, claim.model_dump(mode="json"))))
    else:
        typer.echo(render_claim(claim))


@node_app.command("create")
def node_create(
    node_id: str,
    kind: str,
    statement: str,
    root: str = ROOT_OPTION,
    display_label: str = "",
    assumption: list[str] = typer.Option(None, "--assumption"),
    dependency: list[str] = typer.Option(None, "--dependency"),
    created_by: str = "human",
    source_locator: str = typer.Option("", "--source-locator", help="Required for imported_result nodes"),
    source_version: str = typer.Option("", "--source-version", help="Required for imported_result nodes"),
    trust_level: str = typer.Option("", "--trust-level"),
    reference_id: str = typer.Option(
        "", "--reference-id", help="imported_result only: the `reference list` entry it cites; fixed once the node exists"
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_store(_root(root))
    try:
        node = create_node(
            store,
            node_id=node_id,
            kind=kind,
            statement=statement,
            display_label=display_label,
            assumptions=assumption,
            dependencies=dependency,
            source_locator=source_locator or None,
            source_version=source_version or None,
            trust_level=trust_level or None,
            reference_id=reference_id or None,
            created_by=created_by,
        )
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.create")
        raise typer.Exit(code=1)
    _emit_node(node, json_output, command="node.create")


@node_app.command("show")
@read_scoped
def node_show(
    node_id: str,
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_store(_root(root))
    try:
        node = require_node(store, node_id)
        workflow_state = get_workflow_state(store, node_id)
        acceptance_state = get_acceptance_state(store, node_id)
        integrity_state = get_integrity_state(store, node_id)
        blocked_reason = get_blocked_reason(store, node_id) if workflow_state == "blocked" else None
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.show")
        raise typer.Exit(code=1)
    working = working_proof_path(store.root, node_id)
    working_proof = working.relative_to(store.root).as_posix() if working.is_file() else None
    snapshots = [
        {"version": proof.version, "file_path": proof.file_path, "sha256": proof.sha256, "is_current": proof.is_current}
        for proof in list_candidate_proofs(store, node_id)
    ]
    citation = node_citation(store, node)

    if json_output:
        payload = node.model_dump(mode="json")
        payload["citation"] = citation
        payload["workflow_state"] = workflow_state
        payload["acceptance_state"] = acceptance_state
        payload["integrity_state"] = integrity_state
        payload["blocked_reason"] = blocked_reason
        payload["working_proof"] = working_proof
        payload["snapshots"] = snapshots
        # what the node page shows of each dependency: its pin, whether current, the remedy (#97)
        payload["dependency_details"] = dependency_details(store, node_id)
        typer.echo(dump_envelope(success_envelope("node.show", payload)))
    else:
        typer.echo(
            render_proof_map_node(
                node,
                workflow_state=workflow_state,
                acceptance_state=acceptance_state,
                integrity_state=integrity_state,
                blocked_reason=blocked_reason,
                working_proof=working_proof,
                snapshots=snapshots,
                citation=citation,
            )
        )


@node_app.command("list")
@read_scoped
def node_list(
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_store(_root(root))
    nodes = list_nodes(store)
    if json_output:
        typer.echo(dump_envelope(success_envelope("node.list", [_with_state_axes(store, node) for node in nodes])))
        return
    typer.echo(render_proof_map_node_list(nodes))


@node_app.command("claim")
def node_claim(
    node_id: str,
    assignee: str = typer.Option(..., "--assignee", "--claimant", help="Who is taking the node on (an agent or person name)"),
    reassign: bool = typer.Option(False, "--reassign", help="Take the node over from its current assignee"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Assign a frontier node to yourself before working on it: a planning signal, not a lock (ADR-0010)."""
    store = get_store(_root(root))
    try:
        claim = claim_node(store, node_id, claimant_id=assignee, reassign=reassign)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.claim")
        raise typer.Exit(code=1)
    _emit_claim(claim, json_output, command="node.claim")


@node_app.command("unassign")
def node_unassign(
    node_id: str,
    by: str = typer.Option(..., "--by", "--claimant", help="Who is clearing the claim (its holder, the researcher, or by agreement)"),
    reason: str = typer.Option("", "--reason"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """End a node's claim, whoever holds it (ADR-0010)."""
    store = get_store(_root(root))
    try:
        claim = release_node(store, node_id, claimant_id=by, reason=reason or None)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.unassign")
        raise typer.Exit(code=1)
    _emit_claim(claim, json_output, command="node.unassign")


node_app.command("release", hidden=True)(node_unassign)


def _emit_candidate_proof(record, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, record.model_dump(mode="json"))))
    else:
        typer.echo(render_candidate_proof(record))


@node_app.command("request-review")
def node_request_review(
    node_id: str,
    rationale: str = typer.Option(..., "--rationale", help="Why this node is now appropriately scoped to prove directly"),
    requested_by: str = typer.Option("human", "--requested-by"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Snapshot the node's working proof.tex for review (ADR-0010). Needs no claim."""
    store = get_store(_root(root))
    try:
        record = request_review(store, node_id, requested_by=requested_by, rationale=rationale)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.request_review")
        raise typer.Exit(code=1)
    _emit_candidate_proof(record, json_output, command="node.request_review")


def _emit_review_record(record, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, record.model_dump(mode="json"))))
    else:
        typer.echo(summarize_review_record(record))


@node_app.command("review")
def node_review(node_id: str, decision: str = typer.Argument(""), root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Accept / revision-requested / reject a node, or Reference-review an imported result — on the proof map page.

    A Human Review decision is the researcher's, made on the proof map page
    (ADR-0010): this command never makes one, whatever flags it's given. It
    prints where to.
    """
    human_review_required(root, command="node.review", kind="acceptance", target_id=node_id, node_id=node_id, json_output=json_output)


@node_app.command("revalidate")
def node_revalidate(node_id: str, target_node_id: str = typer.Argument(""), root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Lightweight re-review of node_id's dependency on target_node_id — on the proof map page (ADR-0010)."""
    human_review_required(
        root, command="node.revalidate", kind="dependency_revalidation", target_id=node_id, node_id=node_id, json_output=json_output
    )


@node_app.command("migrate-dependents")
def node_migrate_dependents(
    node_id: str,
    replacement_id: str = typer.Argument(""),
    root: str = typer.Option(".", "--root", envvar="PROOF_ROOT"),  # the root convention of ADR-0011 (#67)
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a no-longer-callable imported result's dependents onto its correction — on the proof map page (#20)."""
    human_review_required(
        root, command="node.migrate_dependents", kind="dependent_migration", target_id=node_id, node_id=node_id, json_output=json_output
    )


@node_app.command("promote")
def node_promote(node_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Promote an Accepted Claim to a Lemma — on the proof map page (ADR-0010)."""
    human_review_required(root, command="node.promote", kind="promote", target_id=node_id, node_id=node_id, json_output=json_output)


@node_app.command("split")
def node_split(
    parent_id: str,
    child: list[str] = typer.Option(
        ..., "--child", help="Repeatable, one per child: <child-id>=<statement>"
    ),
    root: str = ROOT_OPTION,
    created_by: str = "human",
    reassign: bool = typer.Option(False, "--reassign", help="Take the claim over from whoever holds it (recorded as `claim --reassign` records it); the node need not be on the frontier"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Decompose parent_id into new claim-kind children. Ungated — no researcher approval needed.
    All or nothing; a node someone else holds is theirs to split unless --reassign."""
    store = get_store(_root(root))
    try:
        specs = []
        for entry in child:
            if "=" not in entry:
                raise ProofMapError(
                    "INVALID_CHILD_SPEC", f"'{entry}' is not in the form <child-id>=<statement>"
                )
            child_id, statement = entry.split("=", 1)
            specs.append({"id": child_id, "statement": statement})
        children = split_node(store, parent_id, specs, created_by=created_by, reassign=reassign)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.split")
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(
            dump_envelope(success_envelope("node.split", [node.model_dump(mode="json") for node in children]))
        )
    else:
        typer.echo(render_proof_map_node_list(children))


@node_app.command("depend")
def node_depend(
    node_id: str,
    add: str = typer.Option("", "--add", help="Make the node rest on this node too"),
    remove: str = typer.Option("", "--remove", help="Stop the node resting on this dependency"),
    move: str = typer.Option("", "--move", help="Move this dependency down onto the node given by --to"),
    to: str = typer.Option("", "--to", help="With --move: one of the node's own dependencies, e.g. a split child"),
    by: str = typer.Option("human", "--by", help="Who is editing (an agent or person name)"),
    reassign: bool = typer.Option(False, "--reassign", help="Take the claim over from whoever holds it (recorded as `claim --reassign` records it)"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add, remove or move one of node_id's dependencies. Ungated, like split (#96).

    A node someone else holds is theirs to edit unless --reassign; an Accepted
    node only under an open Challenge. Pins are taken at the next request-review."""
    named = [flag for flag, value in (("--add", add), ("--remove", remove), ("--move", move)) if value]
    if len(named) != 1:
        raise click.UsageError("name exactly one of --add, --remove or --move")
    if bool(to) != bool(move):
        raise click.UsageError("--move and --to go together: --move <dependency> --to <child>")
    store = get_store(_root(root))
    try:
        if add:
            edit = add_dependency(store, node_id, add, edited_by=by, reassign=reassign)
        elif remove:
            edit = remove_dependency(store, node_id, remove, edited_by=by, reassign=reassign)
        else:
            edit = move_dependency(store, node_id, move, to=to, edited_by=by, reassign=reassign)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.depend")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("node.depend", edit.as_json())))
        return
    summary = {
        "add": f"{node_id} now rests on {edit.dependency_id}",
        "remove": f"{node_id} no longer rests on {edit.dependency_id}",
        "move": f"moved dependency {edit.dependency_id} of {node_id} onto {to}",
    }[edit.op]
    typer.echo(summary + "; pins are taken at the next request-review")
    typer.echo(render_proof_map_node(edit.node))
    if edit.to is not None:
        typer.echo(render_proof_map_node(edit.to))


def _emit_challenge(challenge, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, challenge.model_dump(mode="json"))))
    else:
        typer.echo(render_challenge(challenge))


@challenge_app.command("open")
def challenge_open(
    target_id: str,
    root: str = ROOT_OPTION,
    opened_by: str = "human",
    rationale: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Raise a Challenge against an already-Accepted (or Reference-reviewed) node. Ungated."""
    store = get_store(_root(root))
    try:
        challenge = open_challenge(store, target_id, opened_by=opened_by, rationale=rationale)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="challenge.open")
        raise typer.Exit(code=1)
    _emit_challenge(challenge, json_output, command="challenge.open")


@challenge_app.command("list")
def challenge_list(
    root: str = ROOT_OPTION,
    target_id: str = "",
    status: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_store(_root(root))
    challenges = list_challenges(store, target_node_id=target_id, status=status)
    if json_output:
        typer.echo(
            dump_envelope(success_envelope("challenge.list", [c.model_dump(mode="json") for c in challenges]))
        )
        return
    typer.echo(render_challenge_list(challenges))


@challenge_app.command("show")
def challenge_show(
    challenge_id: str,
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_store(_root(root))
    try:
        challenge = require_challenge(store, challenge_id)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="challenge.show")
        raise typer.Exit(code=1)
    _emit_challenge(challenge, json_output, command="challenge.show")


@challenge_app.command("dismiss")
def challenge_dismiss(challenge_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Resolve a Challenge — on the proof map page (ADR-0010)."""
    store = get_store(_root(root))
    try:
        target = require_challenge(store, challenge_id).target_node_id
    except ProofMapError:
        target = None
    human_review_required(
        root, command="challenge.dismiss", kind="challenge_resolution", target_id=challenge_id, node_id=target, json_output=json_output
    )


def _emit_evidence_check(check, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, check.model_dump(mode="json"))))
    else:
        typer.echo(
            f"Evidence check {check.id}: {check.outcome.value} on candidate proof {check.candidate_proof_id} "
            f"(run_by={check.run_by})"
        )


@node_evidence_app.command("record")
def evidence_record(
    candidate_proof_id: str,
    outcome: str,
    root: str = ROOT_OPTION,
    notes: str = "",
    run_by: str = typer.Option("system", "--run-by", help="The checker or backend that ran the check; the node page shows it"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Record an Evidence check against a specific Candidate proof. Advisory, ungated."""
    store = get_store(_root(root))
    try:
        check = record_evidence_check(store, candidate_proof_id, outcome, notes=notes, run_by=run_by)
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="node.evidence.record")
        raise typer.Exit(code=1)
    _emit_evidence_check(check, json_output, command="node.evidence.record")


@node_evidence_app.command("review")
def evidence_review(check_id: str, decision: str = typer.Argument(""), root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Judge an Evidence check trusted/unusable — on the proof map page (ADR-0010)."""
    human_review_required(root, command="node.evidence.review", kind="evidence_review", target_id=check_id, node_id=None, json_output=json_output)


node_app.add_typer(node_evidence_app, name="evidence")


def _running_review_app(store) -> bool:
    """Whether this project's proof map page already answers on its origin."""
    import urllib.request

    from .storage import read_project_instance_id
    from .webapp.server import project_url

    try:
        with urllib.request.urlopen(f"{project_url(store)}/api/health", timeout=2) as response:
            return json.loads(response.read())["data"]["instance"] == read_project_instance_id(store)
    except (OSError, ValueError, KeyError):
        return False


@map_app.command("serve")
def review_serve(root: str = ROOT_OPTION) -> None:
    """Run this project's proof map page on its own localhost origin — the only place Human Review decisions are made (ADR-0010).

    Runs in the foreground until interrupted. Bound to 127.0.0.1. Decisions
    are recorded as this process's git identity and committed with their
    snapshots.
    """
    from .webapp.server import ReviewServer

    store = get_store(_root(root))
    try:
        server = ReviewServer(store)
    except OSError as exc:
        typer.echo(f"Error: can't bind this project's review port ({exc}); is it already running? Try `proof map open`.")
        raise typer.Exit(code=1)
    typer.echo(f"Proof map page for this project: {server.url}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@map_app.command("open")
def review_open(
    node_id: str = typer.Argument("", help="Open this node's decision page"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Open this project's proof map page (starting it in the background if needed), optionally at a node."""
    import subprocess
    import time
    import webbrowser

    from .webapp.server import project_url

    store = get_store(_root(root))
    if not _running_review_app(store):
        subprocess.Popen(
            [sys.executable, "-m", "proof_cli.cli", "map", "serve", "--root", str(_root(root))],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            if _running_review_app(store):
                break
            time.sleep(0.1)
    url = project_url(store, node_id or None)
    typer.echo(dump_envelope(success_envelope("map.open", {"url": url, "node_id": node_id or None})) if json_output else url)
    webbrowser.open(url)


@review_app.command("warnings")
def review_warnings(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Everything about Human Review authority that doesn't verify, and Review snapshots the index never recorded."""
    warnings = list_integrity_warnings(get_store(_root(root)))
    if json_output:
        typer.echo(dump_envelope(success_envelope("review.warnings", [warning.model_dump(mode="json") for warning in warnings])))
    elif not warnings:
        typer.echo("No authority warnings")
    else:
        typer.echo("\n".join(f"{warning.code}: {warning.message}" for warning in warnings))


app.add_typer(goal_app, name="goal", rich_help_panel=LEGACY_PANEL)
# Frozen peripheral modules (issue #28): reachable, but no longer advertised
# in default `proof --help` discoverability — the new proof-map node model
# is the primary surface now.
app.add_typer(asset_app, name="asset", hidden=True)
app.add_typer(pack_app, name="pack", hidden=True)
app.add_typer(policy_app, name="policy", hidden=True)
app.add_typer(recommend_app, name="recommend", hidden=True)
app.add_typer(reuse_app, name="reuse", hidden=True)
app.add_typer(automate_app, name="automate", hidden=True)
app.add_typer(benchmark_app, name="benchmark", hidden=True)
app.add_typer(project_app, name="project")
app.add_typer(theorem_app, name="theorem", rich_help_panel=LEGACY_PANEL)
app.add_typer(node_app, name="node", rich_help_panel=PROOF_MAP_PANEL)
app.add_typer(challenge_app, name="challenge", rich_help_panel=PROOF_MAP_PANEL)
app.add_typer(obligation_app, name="obligation", rich_help_panel=LEGACY_PANEL)
app.add_typer(blocker_app, name="blocker", rich_help_panel=LEGACY_PANEL)
app.add_typer(reference_app, name="reference")
app.add_typer(memory_app, name="memory")
app.add_typer(publication_app, name="publication")
app.add_typer(provenance_app, name="provenance")
app.add_typer(bug_app, name="bug")
app.add_typer(debug_app, name="debug")
app.add_typer(review_app, name="review")
app.add_typer(map_app, name="map", rich_help_panel=PROOF_MAP_PANEL)
# the page's commands before it was the map's home (ADR-0010): kept, out of sight
review_app.command("serve", hidden=True)(review_serve)
review_app.command("open", hidden=True)(review_open)
app.add_typer(contributor_app, name="contributor")
app.add_typer(role_app, name="role")
app.add_typer(comment_app, name="comment")
app.add_typer(branch_app, name="branch")
app.add_typer(exchange_app, name="exchange")
app.add_typer(handoff_app, name="handoff")
app.add_typer(repair_app, name="repair")
app.add_typer(trace_app, name="trace")
app.add_typer(evidence_app, name="evidence")
app.add_typer(explain_app, name="explain")
app.add_typer(formalize_app, name="formalize")
app.add_typer(verify_app, name="verify", rich_help_panel=LEGACY_PANEL)


@asset_app.command("list")
def asset_list(root: str = ROOT_OPTION, project_id: str = "", kind: str = "", status: str = "") -> None:
    typer.echo(cmd_proof_asset_list(_root(root), project_id=project_id, kind=kind, status=status))


@asset_app.command("show")
def asset_show(asset_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_proof_asset_show(asset_id, _root(root)))


@asset_app.command("publish")
def asset_publish(
    asset_json: str,
    root: str = ROOT_OPTION,
    review_action: str = "publish",
    reviewer: str = "human",
    notes: str = "",
) -> None:
    typer.echo(cmd_proof_asset_publish(asset_json, _root(root), review_action=review_action, reviewer=reviewer, notes=notes))


@asset_app.command("review")
def asset_review(
    asset_id: str,
    action: str,
    root: str = ROOT_OPTION,
    reviewer: str = "human",
    notes: str = "",
) -> None:
    typer.echo(cmd_proof_asset_review(asset_id, action, _root(root), reviewer=reviewer, notes=notes))


@pack_app.command("list")
def pack_list(root: str = ROOT_OPTION, project_id: str = "") -> None:
    typer.echo(cmd_proof_pack_list(_root(root), project_id=project_id))


@pack_app.command("show")
def pack_show(pack_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_proof_pack_show(pack_id, _root(root)))


@pack_app.command("install")
def pack_install(
    pack_json: str,
    root: str = ROOT_OPTION,
    installed_by: str = "human",
    notation_profile: str = "",
    notes: str = "",
    project_tag: list[str] = typer.Option(None, "--project-tag"),
    available_asset_id: list[str] = typer.Option(None, "--available-asset-id"),
    available_asset_kind: list[str] = typer.Option(None, "--available-asset-kind"),
) -> None:
    typer.echo(
        cmd_proof_pack_install(
            pack_json,
            _root(root),
            installed_by=installed_by,
            project_tags=project_tag,
            available_asset_ids=available_asset_id,
            available_asset_kinds=available_asset_kind,
            notation_profile=notation_profile,
            notes=notes,
        )
    )


@pack_app.command("update")
def pack_update(pack_json: str, root: str = ROOT_OPTION, reviewer: str = "human", notes: str = "") -> None:
    typer.echo(cmd_proof_pack_update(pack_json, _root(root), reviewer=reviewer, notes=notes))


@policy_app.command("list")
def policy_list(root: str = ROOT_OPTION, project_id: str = "") -> None:
    typer.echo(cmd_proof_policy_list(_root(root), project_id=project_id))


@policy_app.command("set")
def policy_set(profile_json: str, root: str = ROOT_OPTION, reviewer: str = "human", notes: str = "") -> None:
    typer.echo(cmd_proof_policy_set(profile_json, _root(root), reviewer=reviewer, notes=notes))


@recommend_app.callback(invoke_without_command=True)
def recommend(
    ctx: typer.Context,
    root: str = ROOT_OPTION,
    query: str = "",
    current_project_id: str = "",
    prior_usefulness_json: str = "",
    limit: int = 10,
    current_asset_json: list[str] = typer.Option(None, "--current-asset-json"),
    shared_asset_json: list[str] = typer.Option(None, "--shared-asset-json"),
    prior_asset_json: list[str] = typer.Option(None, "--prior-asset-json"),
    domain_pack_json: list[str] = typer.Option(None, "--domain-pack-json"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(
        cmd_proof_recommend(
            _root(root),
            query=query,
            current_project_id=current_project_id,
            current_project_assets_json=current_asset_json,
            shared_assets_json=shared_asset_json,
            prior_project_assets_json=prior_asset_json,
            domain_packs_json=domain_pack_json,
            prior_usefulness_json=prior_usefulness_json,
            limit=limit,
        )
    )


@reuse_app.command("show")
def reuse_show(root: str = ROOT_OPTION, asset_id: str = "", project_id: str = "") -> None:
    typer.echo(cmd_proof_reuse_show(_root(root), asset_id=asset_id, project_id=project_id))


@automate_app.command("plan")
def automate_plan(
    scope: str,
    task_type: str,
    root: str = ROOT_OPTION,
    execution_mode: str = "supervised",
    notes: str = "",
    dry_run: bool = False,
    approval_required: bool = False,
    policy_json: str = "",
    action_json: list[str] = typer.Option(None, "--action-json"),
) -> None:
    typer.echo(
        cmd_proof_automate_plan(
            _root(root),
            scope=scope,
            task_type=task_type,
            action_json=action_json,
            policy_json=policy_json,
            execution_mode=execution_mode,
            notes=notes,
            dry_run=dry_run,
            approval_required=approval_required,
        )
    )


@automate_app.command("run")
def automate_run(run_id: str, root: str = ROOT_OPTION, approvals_json: str = "", interrupt_after: int | None = None, notes: str = "") -> None:
    typer.echo(cmd_proof_automate_run(run_id, _root(root), approvals_json=approvals_json, interrupt_after=interrupt_after, notes=notes))


@automate_app.command("trace")
def automate_trace(run_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_proof_automate_trace(run_id, _root(root)))


@automate_app.command("review")
def automate_review(
    run_id: str,
    action_id: str,
    root: str = ROOT_OPTION,
    decision: str = "approve",
    reviewer: str = "human",
    rationale: str = "",
) -> None:
    typer.echo(cmd_proof_automate_review(run_id, action_id, _root(root), decision=decision, reviewer=reviewer, rationale=rationale))


@benchmark_app.command("run")
def benchmark_run(
    root: str = ROOT_OPTION,
    benchmark_name: str = "",
    scenario_id: str = "",
    notes: str = "",
    record_json: list[str] = typer.Option(None, "--record-json"),
    ) -> None:
    typer.echo(cmd_proof_benchmark_run(_root(root), record_json=record_json, benchmark_name=benchmark_name, scenario_id=scenario_id, notes=notes))


@project_app.command("analyze")
def project_analyze(root: str = ROOT_OPTION, query: str = "", limit: int = 5) -> None:
    typer.echo(cmd_project_analyze(_root(root), query=query, limit=limit))


@goal_app.command("set")
def goal_set(goal: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_goal_set(goal, root=_root(root)))


@goal_app.command("list")
def goal_list(root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_goal_list(_root(root)))


@theorem_app.command("add")
def theorem_add(
    theorem_id: str,
    name: str,
    statement: str,
    root: str = ROOT_OPTION,
    kind: str = "theorem",
    assumption: list[str] = typer.Option(None, "--assumption"),
    export: list[str] = typer.Option(None, "--export"),
    source_ref: str = "internal/project",
    created_by: str = "human",
    updated_by: str = "human",
    contributor: list[str] = typer.Option(None, "--contributor"),
    notes: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """(legacy) Add a contract. Its trust and review fields are legacy (ADR-0012)."""
    try:
        output = (
            cmd_theorem_add(
                theorem_id=theorem_id,
                name=name,
                statement=statement,
                root=_root(root),
                kind=kind,
                assumption=assumption,
                export=export,
                source_ref=source_ref,
                created_by=created_by,
                updated_by=updated_by,
                contributor=contributor,
                notes=notes,
            )
        )
    except ValueError as exc:
        _legacy_input_error("theorem.add", exc, json_output)
    _emit_legacy_json("theorem.add", json_output, lambda: output)


@theorem_app.command("show")
def theorem_show(theorem_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """(legacy) A contract, with its legacy trust and review fields: not a trust source (ADR-0012)."""
    _emit_legacy_json("theorem.show", json_output, lambda: cmd_theorem_show(theorem_id, root=_root(root)))


@theorem_app.command("extract")
def theorem_extract(theorem_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """(legacy) A contract with its legacy callability: not a trust source (ADR-0012)."""
    _emit_legacy(
        "theorem.extract",
        json_output,
        lambda: cmd_theorem_extract(theorem_id, root=_root(root)),
        lambda: theorem_extract_data(theorem_id, root=_root(root)),
    )


@theorem_app.command("list")
def theorem_list(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """(legacy) The contracts, with their legacy status: not a trust source (ADR-0012)."""
    _emit_legacy("theorem.list", json_output, lambda: cmd_theorem_list(_root(root)), lambda: theorem_list_data(_root(root)))


@theorem_app.command("apply")
def theorem_apply(theorem_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """(legacy) Record a use of a contract, if its legacy callability allows: not a trust source (ADR-0012)."""
    if json_output:
        typer.echo(dump_envelope(success_envelope("theorem.apply", theorem_apply_data(theorem_id, root=_root(root)))))
    else:
        typer.echo(cmd_theorem_apply(theorem_id, root=_root(root)))


@theorem_app.command("ground")
def theorem_ground(theorem_id: str, reference_id: list[str] = typer.Option(..., "--reference-id"), root: str = ROOT_OPTION, notes: str = "") -> None:
    typer.echo(cmd_theorem_ground(theorem_id, reference_id, root=_root(root), notes=notes))


@obligation_app.command("add")
def obligation_add(goal_statement: str, root: str = ROOT_OPTION, source_step_id: str = "", required_for: str = "") -> None:
    typer.echo(
        cmd_obligation_add(
            goal_statement=goal_statement,
            root=_root(root),
            source_step_id=source_step_id or None,
            required_for=required_for or None,
        )
    )


@obligation_app.command("list")
def obligation_list(root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_obligation_list(_root(root)))


@obligation_app.command("derive")
def obligation_derive(theorem_id: str, root: str = ROOT_OPTION, notes: str = "") -> None:
    typer.echo(cmd_proof_obligation_derive(theorem_id, _root(root), notes=notes))


@blocker_app.command("add")
def blocker_add(description: str, root: str = ROOT_OPTION, scope: str = "global", failure_type: str = "unknown") -> None:
    typer.echo(cmd_blocker_add(description, root=_root(root), scope=scope, failure_type=failure_type))


@blocker_app.command("list")
def blocker_list(root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_blocker_list(_root(root)))


@reference_app.command("list")
def reference_list(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """The project's references: citations. Their review status and callable flag are legacy (ADR-0012)."""
    _emit_legacy("reference.list", json_output, lambda: cmd_reference_list(_root(root)), lambda: reference_list_data(_root(root)))


@reference_app.command("show")
def reference_show(reference_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """A reference: a citation. Its review status, trust level and callable flag are legacy (ADR-0012)."""
    _emit_legacy_json("reference.show", json_output, lambda: cmd_reference_show(reference_id, root=_root(root)))


@reference_app.command("import")
def reference_import(
    reference_id: str,
    title: str,
    year: int,
    root: str = ROOT_OPTION,
    author: list[str] = typer.Option(None, "--author"),
    source_type: str = "other",
    origin: str = "",
    bibliographic_source: str = "",
    identifier: str = "",
    url: str = "",
    notes: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Import a reference as a citation. Its legacy trust fields are not a trust source (ADR-0012)."""
    try:
        output = (
            cmd_reference_import(
                reference_id,
                title,
                year,
                _root(root),
                author=author,
                source_type=source_type,  # type: ignore[arg-type]
                origin=origin,
                bibliographic_source=bibliographic_source,
                identifier=identifier,
                url=url,
                notes=notes,
            )
        )
    except ValueError as exc:
        _legacy_input_error("reference.import", exc, json_output)
    _emit_legacy_json("reference.import", json_output, lambda: output)




@memory_app.command("list")
def memory_list(
    root: str = ROOT_OPTION,
    layer: str = "",
    node_id: str = "",
    candidate_proof_id: str = "",
    review_id: str = "",
    theorem_id: str = typer.Option("", help="Legacy scope (read-only, ADR-0012)"),
    goal_id: str = typer.Option("", help="Legacy scope (read-only, ADR-0012)"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    filters = dict(
        layer=layer,
        node_id=node_id,
        candidate_proof_id=candidate_proof_id,
        review_id=review_id,
        theorem_id=theorem_id,
        goal_id=goal_id,
    )
    if not json_output:
        typer.echo(cmd_memory_list(_root(root), **filters))
        return
    try:
        data = memory_list_data(_root(root), **filters)
    except ValueError as exc:
        typer.echo(dump_envelope(error_envelope("memory.list", "INVALID_INPUT", str(exc))))
        raise typer.Exit(code=1)
    typer.echo(dump_envelope(success_envelope("memory.list", data)))


@memory_app.command("show")
def memory_show(artifact_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_memory_show(artifact_id, root=_root(root)))


@memory_app.command("add")
def memory_add(
    content: str,
    root: str = ROOT_OPTION,
    layer: str = "working",
    node_id: str = "",
    candidate_proof_id: str = "",
    review_id: str = "",
    route_id: str = "",
    importance: str = "medium",
    status: str = "",
    source: str = "manual",
    tag: list[str] = typer.Option(None, "--tag"),
    notes: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Record a memory entry, scoped to a proof-map node (and one of its Candidate proofs or reviews).

    The scope is checked against the map, and a bad one writes nothing. The
    legacy theorem/goal/obligation/blocker scope is read-only (ADR-0012).
    """
    try:
        output = cmd_memory_add(
            content,
            _root(root),
            layer=layer,
            node_id=node_id,
            candidate_proof_id=candidate_proof_id,
            review_id=review_id,
            route_id=route_id,
            importance=importance,
            status=status,
            source=source,
            tag=tag,
            notes=notes,
        )
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="memory.add")
        raise typer.Exit(code=1)
    typer.echo(dump_envelope(success_envelope("memory.add", json.loads(output))) if json_output else output)


def _publication(command: str, json_output: bool, data, human) -> None:
    """Run one publication command: an ADR-0006 envelope under --json, text otherwise.

    Publication is editorial (issue #30): agents may run these, and none is a
    Human Review decision. A refused write is a stable error code, exit 1.
    """
    try:
        if json_output:
            typer.echo(dump_envelope(success_envelope(command, data())))
        else:
            typer.echo(human())
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command=command)
        raise typer.Exit(code=1)


@publication_app.command("list")
def publication_list(root: str = ROOT_OPTION, object_type: str = "", json_output: bool = typer.Option(False, "--json")) -> None:
    """List publication claims: editorial readiness beside each node's live acceptance and integrity."""
    _publication(
        "publication.list",
        json_output,
        lambda: publication_list_data(_root(root), object_type=object_type),
        lambda: cmd_publication_list(_root(root), object_type=object_type),
    )


@publication_app.command("show")
def publication_show(
    object_id: str, root: str = ROOT_OPTION, object_type: str = "", json_output: bool = typer.Option(False, "--json")
) -> None:
    """Show a claim's editorial record and its node's live acceptance and integrity."""
    _publication(
        "publication.show",
        json_output,
        lambda: publication_show_data(object_id, _root(root), object_type=object_type),
        lambda: cmd_publication_show(object_id, _root(root), object_type=object_type),
    )


@publication_app.command("set")
def publication_set(
    object_id: str,
    readiness: str,
    root: str = ROOT_OPTION,
    object_type: str = "proof_map_node",
    display_name: str = "",
    title: str = "",
    section_placement: str = "",
    reason: str = "",
    citation_kind: str = "",
    internal_only: bool = False,
    editorial_note: list[str] = typer.Option(None, "--editorial-note"),
    supporting_reference_id: list[str] = typer.Option(None, "--supporting-reference-id"),
    supporting_theorem_id: list[str] = typer.Option(None, "--supporting-theorem-id"),
    release_status: str = typer.Option("", help="approved, corrected or withdrawn; left unset, no release is recorded"),
    release_notes: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Set a claim's editorial readiness (editorial, not a Human Review decision).

    internal_draft -> collaborator_ready -> supplement_ready -> paper_ready, one
    step at a time, and withdrawn from anywhere; supplement_ready and paper_ready
    need a node that is accepted · current.
    """
    options = dict(
        object_type=object_type,
        display_name=display_name,
        title=title,
        section_placement=section_placement,
        reason=reason,
        citation_kind=citation_kind,
        internal_only=internal_only,
        editorial_note=editorial_note,
        supporting_reference_id=supporting_reference_id,
        supporting_theorem_id=supporting_theorem_id,
        release_status=release_status,
        release_notes=release_notes,
    )
    _publication(
        "publication.set",
        json_output,
        lambda: publication_set_data(object_id, readiness, _root(root), **options),
        lambda: cmd_publication_set(object_id, readiness, _root(root), **options),
    )


@publication_app.command("view")
def publication_view(root: str = ROOT_OPTION, audience: str = "paper", json_output: bool = typer.Option(False, "--json")) -> None:
    _publication(
        "publication.view",
        json_output,
        lambda: publication_view_data(_root(root), audience=audience),
        lambda: cmd_publication_view(_root(root), audience=audience),
    )


@publication_app.command("export")
def publication_export(
    root: str = ROOT_OPTION, audience: str = "paper", format: str = "paper", json_output: bool = typer.Option(False, "--json")
) -> None:
    """Export for an audience. A ready claim whose node is no longer accepted · current is withheld and flagged."""
    _publication(
        "publication.export",
        json_output,
        lambda: publication_export_json(_root(root), audience=audience, format=format),
        lambda: cmd_publication_export(_root(root), audience=audience, format=format),
    )


@publication_app.command("release")
def publication_release(
    root: str = ROOT_OPTION,
    audience: str = "paper",
    status: str = "approved",
    approved_by: list[str] = typer.Option(None, "--approved-by"),
    rationale: str = "",
    note: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Record a release (editorial; the sign-off on record is the release commit's git author)."""
    options = dict(audience=audience, status=status, approved_by=approved_by, rationale=rationale, note=note)
    _publication(
        "publication.release",
        json_output,
        lambda: publication_release_data(_root(root), **options),
        lambda: cmd_publication_release(_root(root), **options),
    )


@publication_app.command("withdraw")
def publication_withdraw(
    release_id: str,
    root: str = ROOT_OPTION,
    approved_by: list[str] = typer.Option(None, "--approved-by"),
    rationale: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Withdraw a release, named by its release id or bundle id (editorial)."""
    options = dict(rationale=rationale, approved_by=approved_by)
    _publication(
        "publication.withdraw",
        json_output,
        lambda: publication_withdraw_data(release_id, _root(root), **options),
        lambda: cmd_publication_withdraw(release_id, _root(root), **options),
    )


@provenance_app.command("show")
def provenance_show(target_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """A contract's or reference's provenance, with its legacy trust fields: not a trust source (ADR-0012)."""
    _emit_legacy(
        "provenance.show",
        json_output,
        lambda: cmd_proof_provenance_show(target_id, root=_root(root)),
        lambda: provenance_show_data(target_id, root=_root(root)),
    )


@bug_app.command("scan")
def bug_scan(theorem_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Scan a contract for proof bugs. Its callability checks are legacy (ADR-0012)."""
    if json_output:
        typer.echo(dump_envelope(success_envelope("bug.scan", bug_scan_data(theorem_id, _root(root)))))
    else:
        typer.echo(cmd_proof_bug_scan(theorem_id, _root(root)))


@bug_app.command("list")
def bug_list(root: str = ROOT_OPTION, theorem_id: str = typer.Option("", "--theorem-id")) -> None:
    typer.echo(cmd_proof_bug_list(_root(root), theorem_id=theorem_id))


@bug_app.command("show")
def bug_show(bug_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_proof_bug_show(bug_id, _root(root)))


@evidence_app.command("show")
def evidence_show(bug_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_proof_evidence_show(bug_id, _root(root)))


@debug_app.command("generate")
def debug_generate(theorem_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_proof_debug_generate(theorem_id, _root(root)))


@debug_app.command("list")
def debug_list(root: str = ROOT_OPTION, theorem_id: str = typer.Option("", "--theorem-id")) -> None:
    typer.echo(cmd_proof_debug_list(_root(root), theorem_id=theorem_id))


@repair_app.command("mark")
def repair_mark(
    bug_id: str,
    status: str = typer.Argument("repaired"),
    status_override: str | None = typer.Option(None, "--status"),
    root: str = ROOT_OPTION,
    note: str = "",
) -> None:
    typer.echo(cmd_proof_repair_mark(bug_id, status_override or status, _root(root), note=note))


@review_app.command("suspicion")
def review_suspicion(
    bug_id: str,
    status: str = typer.Argument("under_review"),
    status_override: str | None = typer.Option(None, "--status"),
    root: str = ROOT_OPTION,
    rationale: str = "",
) -> None:
    typer.echo(cmd_proof_review_suspicion(bug_id, status_override or status, _root(root), rationale=rationale))


@review_app.command("request")
def review_request(
    object_type: str,
    object_id: str,
    root: str = ROOT_OPTION,
    reviewer_id: str = "human",
    rationale: str = "",
) -> None:
    try:
        typer.echo(cmd_review_request(object_type, object_id, _root(root), reviewer_id=reviewer_id, rationale=rationale))
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)


@review_app.command("list")
def review_list(root: str = ROOT_OPTION, object_type: str = "", object_id: str = "") -> None:
    typer.echo(cmd_review_list(_root(root), object_type=object_type, object_id=object_id))


@review_app.command("decide")
def review_decide(
    review_id: str,
    decision: str,
    root: str = ROOT_OPTION,
    reviewer_id: str = "human",
    rationale: str = "",
) -> None:
    try:
        typer.echo(cmd_review_decide(review_id, decision, _root(root), reviewer_id=reviewer_id, rationale=rationale))
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)


@contributor_app.command("list")
def contributor_list(root: str = ROOT_OPTION, team_id: str = "", status: str = "") -> None:
    typer.echo(cmd_contributor_list(_root(root), team_id=team_id, status=status))


@role_app.command("show")
def role_show(contributor_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_role_show(contributor_id, _root(root)))


@comment_app.command("add")
def comment_add(
    object_type: str,
    object_id: str,
    content: str,
    root: str = ROOT_OPTION,
    author_id: str = "human",
    thread_id: str = "",
    status: str = "open",
) -> None:
    typer.echo(cmd_comment_add(object_type, object_id, content, _root(root), author_id=author_id, thread_id=thread_id, status=status))


@comment_app.command("list")
def comment_list(root: str = ROOT_OPTION, thread_id: str = "", object_type: str = "", object_id: str = "") -> None:
    typer.echo(cmd_comment_list(_root(root), thread_id=thread_id, object_type=object_type, object_id=object_id))


@branch_app.command("create")
def branch_create(
    scope: str,
    name: str,
    root: str = ROOT_OPTION,
    created_by: str = "human",
    derived_from: str = "",
    notes: str = "",
    downstream_asset_id: list[str] = typer.Option(None, "--downstream-asset-id"),
) -> None:
    typer.echo(
        cmd_branch_create(
            scope,
            name,
            _root(root),
            created_by=created_by,
            derived_from=derived_from,
            notes=notes,
            downstream_asset_id=downstream_asset_id,
        )
    )


@branch_app.command("list")
def branch_list(root: str = ROOT_OPTION, scope: str = "", status: str = "") -> None:
    typer.echo(cmd_branch_list(_root(root), scope=scope, status=status))


@branch_app.command("compare")
def branch_compare(left_branch_id: str, right_branch_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_branch_compare(left_branch_id, right_branch_id, _root(root)))


@branch_app.command("merge")
def branch_merge(
    branch_id: str,
    root: str = ROOT_OPTION,
    into_branch_id: str = "",
    reviewer_id: str = "human",
    rationale: str = "",
) -> None:
    typer.echo(cmd_branch_merge(branch_id, _root(root), into_branch_id=into_branch_id, reviewer_id=reviewer_id, rationale=rationale))


@exchange_app.command("export")
def exchange_export(root: str = ROOT_OPTION, note: str = "", json_output: bool = typer.Option(False, "--json")) -> None:
    """Export an exchange bundle. Its contracts' and references' trust fields are legacy (ADR-0012)."""
    _emit_legacy_json("exchange.export", json_output, lambda: cmd_exchange_export(_root(root), note=note))


@exchange_app.command("import")
def exchange_import(bundle_json: str, root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_exchange_import(bundle_json, _root(root)))


@handoff_app.command("create")
def handoff_create(
    root: str = ROOT_OPTION,
    note: str = "",
    node_id: str = typer.Option("", help="Scope the handoff's memory to this node, its Candidate proofs, reviews and derived_from parent"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Snapshot the project and export a handoff bundle. Its trust fields are legacy (ADR-0012)."""
    try:
        _emit_legacy_json("handoff.create", json_output, lambda: cmd_handoff_create(_root(root), note=note, node_id=node_id))
    except ProofMapError as exc:
        _emit_node_error(exc, json_output, command="handoff.create")
        raise typer.Exit(code=1)


@handoff_app.command("inspect")
def handoff_inspect(bundle_json: str = "", root: str = ROOT_OPTION) -> None:
    typer.echo(cmd_handoff_inspect(bundle_json, _root(root)))


@trace_app.command("dependency")
def trace_dependency(target_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """(legacy) A contract's dependencies, obligations and blockers. Its trust fields are legacy (ADR-0012)."""
    _emit_legacy_json("trace.dependency", json_output, lambda: cmd_proof_trace_dependency(target_id, _root(root)))


@trace_app.command("machine-check")
def trace_machine_check(source_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(render_verification_output(f"trace machine-check {source_id}", cmd_proof_trace_machine_check(source_id, _root(root))))


@explain_app.command("apply")
def explain_apply(theorem_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """(legacy) Why a contract is or isn't callable under the legacy rules: not a trust source (ADR-0012)."""
    _emit_legacy(
        "explain.apply",
        json_output,
        lambda: cmd_proof_explain_apply(theorem_id, _root(root)),
        lambda: explain_apply_data(theorem_id, _root(root)),
    )


@formalize_app.command("recommend")
def formalize_recommend(source_id: str, root: str = ROOT_OPTION, backend_target: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"formalize recommend {source_id}",
            cmd_proof_formalize_recommend(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


@formalize_app.command("show")
def formalize_show(source_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(render_verification_output(f"formalize show {source_id}", cmd_proof_formalize_show(source_id, _root(root))))


@formalize_app.command("edit")
def formalize_edit(source_id: str, root: str = ROOT_OPTION, backend_target: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"formalize edit {source_id}",
            cmd_proof_formalize_edit(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


@verify_app.command("queue")
def verify_queue(source_id: str, root: str = ROOT_OPTION, backend_target: str = "", route_id: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"verify queue {source_id}",
            cmd_proof_verify_queue(source_id, _root(root), backend_target=backend_target, route_id=route_id, notes=notes),
        )
    )


@verify_app.command("run")
def verify_run(
    source_id: str,
    root: str = ROOT_OPTION,
    backend_target: str = "",
    notes: str = "",
) -> None:
    """Log a placeholder machine check: no backend runs yet. Advisory: it never closes, blocks or
    resolves anything. A real checker records its outcome on a Candidate proof with
    `proof node evidence record`."""
    try:
        output = cmd_proof_verify_run(source_id, _root(root), backend_target=backend_target, notes=notes)
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)
    typer.echo(render_verification_output(f"verify run {source_id}", output))


@verify_app.command("status")
def verify_status(source_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(render_verification_output(f"verify status {source_id}", cmd_proof_verify_status(source_id, _root(root))))


@verify_app.command("result")
def verify_result(source_id: str, root: str = ROOT_OPTION) -> None:
    typer.echo(render_verification_output(f"verify result {source_id}", cmd_proof_verify_result(source_id, _root(root))))


@verify_app.command("stale")
def verify_stale(
    source_id: str,
    root: str = ROOT_OPTION,
    reason: str = "",
    dependency: list[str] = typer.Option(None, "--dependency"),
) -> None:
    typer.echo(
        render_verification_output(
            f"verify stale {source_id}",
            cmd_proof_verify_stale(source_id, _root(root), reason=reason, changed_dependency_ids=dependency),
        )
    )


if __name__ == "__main__":
    app()
