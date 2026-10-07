from __future__ import annotations

import json
import re
import os
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
    cmd_exchange_export,
    cmd_comment_add,
    cmd_comment_list,
    cmd_contributor_list,
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
    cmd_proof_reuse_show,
    cmd_goal_list,
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
from .domain import AGENT_ROLES, ProofMapNodeKind, is_computation
from .envelope import dump_envelope, error_envelope, success_envelope
from .contract import ProofGroup
from .theorems import LEGACY_TRUST_NOTICE
from .collaboration import summarize_review_record
from .storage import read_project_instance_id, read_scoped
from .fog import (
    add_fog,
    crystallize_fog,
    crystallized_from,
    drop_fog,
    edit_fog,
    fog_near,
    fog_view,
    list_experiments,
    list_fog,
    record_experiment,
    reopen_fog,
    require_fog,
)
from .exchange import (
    export_exchange_bundle,
    import_exchange_bundle,
    inspect_exchange_bundle,
    parse_bundle,
    summarize_import_report,
    summarize_inspect_report,
)
from .proof_map import (
    ProofMapError,
    add_dependency,
    claim_node,
    create_node,
    create_node_under_parent,
    dependency_details,
    move_dependency,
    remove_dependency,
    get_acceptance_state,
    conditional_on,
    get_blocked_reason,
    get_frontier,
    is_provisional,
    fixed_by,
    restate_node,
    get_integrity_state,
    get_reference_review_state,
    get_workflow_state,
    evidence_binding,
    list_candidate_proofs,
    list_evidence_checks,
    list_challenges,
    list_integrity_warnings,
    list_nodes,
    node_citation,
    open_challenge,
    record_evidence_check,
    questions,
    record_progress,
    release_node,
    require_challenge,
    request_review,
    require_node,
    review_notices,
    set_medium,
    split_node,
    trust_rule_events,
    trust_rule_view,
    trust_rules_of,
    work_log,
    answer_question,
)
from .trust_rules import get_trust_rule, list_trust_rules, trust_rule_history
from .authority import candidate_proof_sha256
from .vault import working_entry_path
from .definitions import add_definition, all_definitions, definitions_of, edit_definition, fixed_by_definition, nodes_naming, remove_definition, require_definition
from .rendering import (
    render_definition,
    render_definition_list,
    render_node_check,
    render_candidate_proof,
    render_challenge,
    render_challenge_list,
    render_claim,
    render_fog_experiments,
    render_fog_item,
    render_fog_list,
    render_frontier,
    render_proof_map_node,
    render_proof_map_node_list,
    render_trust_rule,
    render_trust_rule_list,
    render_work_log,
    render_work_log_entry,
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
trust_rule_app = typer.Typer(help="Trust rules: the researcher's standing Reference reviews, read-only here (declared on the proof map page; ADR-0014)")
definition_app = typer.Typer(help="Definitions: the named text node statements are written in — a model's setting, a definition, notation (ADR-0020). A node names its definitions when it is created; a definition is fixed, like the statements naming it, once a Review decision relies on it (ADR-0021)")
fog_app = typer.Typer(help="Proof fog: difficulties not yet precise enough to be a Claim, kept outside the map (ADR-0008). Ungated: anyone, agents included, may add, edit, drop or crystallize one")
fog_experiment_app = typer.Typer(help="Experiments: numerical runs recorded against a fog item; they never change its status")
node_evidence_app = typer.Typer(help="Evidence check workflows")
node_medium_app = typer.Typer(help="What a node's candidate proof is made of: latex, or computation (spec #145)")
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
    """Start a proof project in ROOT (and list it on the Home, `proof home`)."""
    from .projects import register_project

    typer.echo(cmd_init(_root(root)))
    register_project(_root(root))


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


def _acceptance_axis(store, node) -> str:
    """The acceptance axis as the proof map page reads it: an imported result's Reference review state
    (`reviewed`, `trusted-by-rule`, …; ADR-0014), a local node's acceptance state."""
    if node.kind == ProofMapNodeKind.imported_result:
        return get_reference_review_state(store, node.id)
    return get_acceptance_state(store, node.id)


def _with_state_axes(store, node) -> dict:
    """A node under --json, with its three state axes (ADR-0002), whether it is Provisional and the Provisional nodes
    it is Conditional on (ADR-0021), and, for an imported result, the Trust rules it meets."""
    return {
        **node.model_dump(mode="json"),
        "workflow_state": get_workflow_state(store, node.id),
        "acceptance_state": _acceptance_axis(store, node),
        "integrity_state": get_integrity_state(store, node.id),
        "provisional": is_provisional(store, node.id),
        "conditional_on": sorted(conditional_on(store, node.id)),
        "trust_rule": trust_rules_of(store, node.id),
    }


@app.command(rich_help_panel=PROOF_MAP_PANEL)
@read_scoped
def frontier(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """The nodes ready to be worked: every dependency Accepted or Provisional, nobody holding them, none awaiting review."""
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
    from .origins import project_url

    # not a project yet: nothing to decide, and a refusal shouldn't create one
    url = project_url(get_store(_root(root)), node_id) if (_root(root) / ".proof").exists() else None
    _emit_error(
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


def _emit_error(exc: ProofMapError, json_output: bool, *, command: str) -> None:
    """A ProofMapError as the command's error envelope under --json, or one line otherwise (nodes, fog, rules alike)."""
    if json_output:
        typer.echo(dump_envelope(error_envelope(command, exc.code, exc.message, details=exc.details or None)))
    else:
        detail_suffix = ""
        if exc.details:
            detail_suffix = " (" + ", ".join(f"{key}={value}" for key, value in exc.details.items()) + ")"
        typer.echo(f"Error: {exc.message}{detail_suffix} [{exc.code}]")


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
    definition: list[str] = typer.Option(None, "--definition", help="Repeatable: a definition the statement is written in (`proof definition list`); restated with `proof node restate` until a Review decision fixes it"),
    created_by: str = "human",
    source_locator: str = typer.Option("", "--source-locator", help="Required for imported_result nodes"),
    source_version: str = typer.Option("", "--source-version", help="Required for imported_result nodes"),
    trust_level: str = typer.Option("", "--trust-level"),
    reference_id: str = typer.Option(
        "", "--reference-id", help="imported_result only: the `reference list` entry it cites; fixed once the node exists"
    ),
    medium: str = typer.Option("", "--medium", help="What the candidate proof is made of: latex (default) or computation (run.sh, outputs in out/)"),
    parent: str = typer.Option(
        "", "--parent", help="A node that rests on the new one: it gains it as a dependency, in the same transaction (any kind; not a Split)"
    ),
    reassign: bool = typer.Option(False, "--reassign", help="With --parent: take the parent's claim over from whoever holds it"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a proof map node. With --parent, the parent rests on it too: one transaction, and a refused
    parent leaves no node and no folder (issue #154)."""
    if reassign and not parent:
        raise click.UsageError("--reassign goes with --parent: it takes the parent's claim over")
    store = get_store(_root(root))
    try:
        fields = dict(
            node_id=node_id,
            kind=kind,
            statement=statement,
            display_label=display_label,
            assumptions=assumption,
            dependencies=dependency,
            definitions=list(definition or []),
            source_locator=source_locator or None,
            source_version=source_version or None,
            trust_level=trust_level or None,
            reference_id=reference_id or None,
            medium=medium or None,
            created_by=created_by,
        )
        node = create_node_under_parent(store, parent, reassign=reassign, **fields) if parent else create_node(store, **fields)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.create")
        raise typer.Exit(code=1)
    _emit_node(node, json_output, command="node.create")


@node_app.command("restate")
def node_restate(
    node_id: str,
    statement: str = typer.Option(None, "--statement"),
    assumption: list[str] = typer.Option(None, "--assumption", help="Repeatable: the assumptions as they now read (all of them)"),
    definition: list[str] = typer.Option(None, "--definition", help="Repeatable: the definitions the statement is now written in (all of them)"),
    reason: str = typer.Option("", "--reason", help="Why: what was wrong or unclear in the text as it stood"),
    by: str = typer.Option("human", "--by", help="Who restates: the researcher (human) any unfixed text, an agent only what an agent wrote"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Restate a node's statement, assumptions or definitions while no Review decision relies on them (ADR-0021).
    Every verdict on the node and on what rests on it goes stale; fixed text is refused (TEXT_FIXED)."""
    store = get_store(_root(root))
    try:
        node = restate_node(store, node_id, statement=statement, assumptions=assumption, definitions=definition, reason=reason, by=by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.restate")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("node.restate", {**node.model_dump(mode="json"), "fixed_by": None})))
        return
    _emit_node(node, json_output, command="node.restate")


@node_app.command("check")
@read_scoped
def node_check(
    node_id: str,
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """The mechanical checks of the node's working proof (issue #180): does it build cleanly, is key-ideas.md there with its four
    headings, does proof.tex state the node's statement, do its \\input's stay in the folder, is each dependency mentioned.
    Findings, never refusals: a run sends the work back on an error before the Verifier reads; the researcher's own
    request-review is never stopped by one. Exit 1 when there is an error-level finding."""
    from .node_check import check_node, errors_of

    store = get_store(_root(root))
    try:
        findings = check_node(store, node_id)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.check")
        raise typer.Exit(code=1)
    failed = bool(errors_of(findings))
    if json_output:
        typer.echo(dump_envelope(success_envelope("node.check", {"node_id": node_id, "ok": not failed, "findings": findings})))
    else:
        typer.echo(render_node_check(node_id, findings))
    if failed:
        raise typer.Exit(code=1)


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
        acceptance_state = _acceptance_axis(store, node)
        integrity_state = get_integrity_state(store, node_id)
        trust_rule = trust_rules_of(store, node_id)
        # the fog item the node came out of, and the open fog near it (ADR-0008, spec #136)
        origin = crystallized_from(store, node_id)
        near = [item.id for item in fog_near(store, node_id)]
        blocked_reason = get_blocked_reason(store, node_id) if workflow_state == "blocked" else None
        # what it may be rested on for, and what its own proof rests on unaccepted (ADR-0021)
        provisional = is_provisional(store, node_id)
        conditional = sorted(conditional_on(store, node_id))
        # the text of the definitions the statement is written in (ADR-0020)
        definition_details = [{"id": d.id, "term": d.term, "text": d.text} for d in definitions_of(store, node)]
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.show")
        raise typer.Exit(code=1)
    working = working_entry_path(store.root, node_id, node.medium)
    working_proof = working.relative_to(store.root).as_posix() if working.is_file() else None
    snapshots = [
        {"version": proof.version, "file_path": proof.file_path, "sha256": proof.sha256, "is_current": proof.is_current}
        for proof in list_candidate_proofs(store, node_id)
    ]
    citation = node_citation(store, node)

    if json_output:
        payload = node.model_dump(mode="json")
        payload["citation"] = citation
        if is_computation(node):  # the entry is run.sh, under its own key: `working_proof` means proof.tex
            payload["run_script"], working_proof = working_proof, None
        payload["workflow_state"] = workflow_state
        payload["acceptance_state"] = acceptance_state
        payload["integrity_state"] = integrity_state
        # the Trust rules an imported result meets, and when it first met each (ADR-0014)
        payload["trust_rule"] = trust_rule
        payload["trust_rule_events"] = [{"rule": event.payload.get("rule"), "at": event.created_at.isoformat()} for event in trust_rule_events(store, node_id)]
        payload["crystallized_from"] = origin.id if origin else None
        payload["fog_near"] = near
        payload["blocked_reason"] = blocked_reason
        payload["provisional"] = provisional
        payload["conditional_on"] = conditional
        # the Review decision that fixed its text, or None while it may still be restated (ADR-0021)
        payload["fixed_by"] = fixed_by(store, node_id)
        # the choices its runs made instead of stopping, and the researcher's answers (ADR-0021)
        payload["questions"] = questions(store, node_id)
        payload["working_proof"] = working_proof
        payload["snapshots"] = snapshots
        # each Evidence check with its own bound hash, read against its snapshot as it is now (PR #147)
        payload["evidence_checks"] = [
            {**check.model_dump(mode="json"), "snapshot_version": proof.version, "binding": evidence_binding(check, now)}
            for proof in list_candidate_proofs(store, node_id) for now in [candidate_proof_sha256(store, proof.id)]
            for check in list_evidence_checks(store, proof.id)
        ]
        # what the node page shows of each dependency: its pin, whether current, the remedy (#97)
        payload["dependency_details"] = dependency_details(store, node_id)
        payload["definition_details"] = definition_details
        typer.echo(dump_envelope(success_envelope("node.show", payload)))
    else:
        typer.echo(
            render_proof_map_node(
                node,
                workflow_state=workflow_state,
                acceptance_state=acceptance_state,
                integrity_state=integrity_state,
                blocked_reason=blocked_reason,
                provisional=provisional,
                conditional_on=conditional,
                working_proof=working_proof,
                snapshots=snapshots,
                citation=citation,
                trust_rule=trust_rule,
                crystallized_from=origin.id if origin else None,
                fog_near=near,
                definitions=definition_details,
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


# -- Trust rules (ADR-0014): read-only; declared, amended and retired only on the proof map page


@trust_rule_app.command("list")
@read_scoped
def trust_rule_list(
    root: str = ROOT_OPTION,
    all_rules: bool = typer.Option(False, "--all", help="Retired rules too"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """The Trust rules in force: which citations are trusted without a review of their own, and why."""
    store = get_store(_root(root))
    views = [trust_rule_view(store, rule) for rule in list_trust_rules(store, include_retired=all_rules)]
    if json_output:
        typer.echo(dump_envelope(success_envelope("trust-rule.list", views)))
        return
    typer.echo(render_trust_rule_list(views))


@trust_rule_app.command("show")
@read_scoped
def trust_rule_show(name: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """One Trust rule, with every decision recorded under its name."""
    store = get_store(_root(root))
    rule = get_trust_rule(store, name)
    if rule is None:
        _emit_error(ProofMapError("TRUST_RULE_NOT_FOUND", f"no trust rule is named {name}"), json_output, command="trust-rule.show")
        raise typer.Exit(code=1)
    view = {**trust_rule_view(store, rule), "history": trust_rule_history(store, name)}
    if json_output:
        typer.echo(dump_envelope(success_envelope("trust-rule.show", view)))
        return
    typer.echo(render_trust_rule(view))


# -- Proof fog (ADR-0008, spec #136): ungated, outside the map ---------------------------------------


def _emit_fog(store, item, json_output: bool, *, command: str) -> None:
    view = fog_view(store, item)
    if json_output:
        typer.echo(dump_envelope(success_envelope(command, view)))
    else:
        typer.echo(render_fog_item(view))


def _definition_view(store, definition) -> dict:
    return {**definition.model_dump(mode="json"), "used_by": nodes_naming(store, definition.id), "fixed_by": fixed_by_definition(store, definition.id)}


def _emit_definition(store, definition, json_output: bool, *, command: str) -> None:
    view = _definition_view(store, definition)
    typer.echo(dump_envelope(success_envelope(command, view)) if json_output else render_definition(view))


@definition_app.command("add")
def definition_add(
    definition_id: str,
    text: str,
    term: str = typer.Option(..., "--term", help="The name the page and the node show it under, e.g. \"Stochastic release unit\""),
    root: str = ROOT_OPTION,
    created_by: str = typer.Option("human", "--created-by"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add a definition: TEXT is Markdown with $…$ maths, as a statement is. Name it from a node with `--definition`."""
    store = get_store(_root(root))
    try:
        definition = add_definition(store, definition_id, term=term, text=text, created_by=created_by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="definition.add")
        raise typer.Exit(code=1)
    _emit_definition(store, definition, json_output, command="definition.add")


@definition_app.command("edit")
def definition_edit(
    definition_id: str,
    text: str = typer.Option(None, "--text"),
    term: str = typer.Option(None, "--term"),
    root: str = ROOT_OPTION,
    edited_by: str = typer.Option("human", "--by", help="The researcher (human) may edit any unfixed definition, an agent only one an agent wrote"),
    reason: str = typer.Option("", "--reason", help="Why; required once a node names it, since the edit restates that node"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Change a definition while no Review decision relies on it (ADR-0021; DEFINITION_FIXED otherwise: add a corrected one under a new id)."""
    store = get_store(_root(root))
    try:
        definition = edit_definition(store, definition_id, term=term, text=text, edited_by=edited_by, reason=reason)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="definition.edit")
        raise typer.Exit(code=1)
    _emit_definition(store, definition, json_output, command="definition.edit")


@definition_app.command("remove")
def definition_remove(
    definition_id: str,
    root: str = ROOT_OPTION,
    removed_by: str = typer.Option("human", "--by"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a definition no node names."""
    store = get_store(_root(root))
    try:
        removed = remove_definition(store, definition_id, removed_by=removed_by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="definition.remove")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("definition.remove", removed.model_dump(mode="json"))))
    else:
        typer.echo(f"removed definition {removed.id}")


@definition_app.command("list")
@read_scoped
def definition_list(root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """The project's definitions, oldest first, with the nodes that name each."""
    store = get_store(_root(root))
    views = [_definition_view(store, d) for d in all_definitions(store)]
    typer.echo(dump_envelope(success_envelope("definition.list", views)) if json_output else render_definition_list(views))


@definition_app.command("show")
@read_scoped
def definition_show(definition_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """One definition in full, with the nodes that name it."""
    store = get_store(_root(root))
    try:
        definition = require_definition(store, definition_id)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="definition.show")
        raise typer.Exit(code=1)
    _emit_definition(store, definition, json_output, command="definition.show")


@fog_app.command("add")
def fog_add(
    text: str,
    root: str = ROOT_OPTION,
    near: list[str] = typer.Option([], "--near", help="A node this is about (repeatable); never a dependency"),
    notes: str = typer.Option("", "--notes"),
    created_by: str = typer.Option("human", "--created-by"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add a fog item: a difficulty you can't state precisely yet."""
    store = get_store(_root(root))
    try:
        item = add_fog(store, text, near=near, notes=notes, created_by=created_by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.add")
        raise typer.Exit(code=1)
    _emit_fog(store, item, json_output, command="fog.add")


@fog_app.command("list")
@read_scoped
def fog_list(root: str = ROOT_OPTION, all_items: bool = typer.Option(False, "--all", help="Dropped and crystallized items too"), json_output: bool = typer.Option(False, "--json")) -> None:
    """The open fog items, by id."""
    store = get_store(_root(root))
    views = [fog_view(store, item) for item in list_fog(store, include_all=all_items)]
    if json_output:
        typer.echo(dump_envelope(success_envelope("fog.list", views)))
        return
    typer.echo(render_fog_list(views))


@fog_app.command("show")
@read_scoped
def fog_show(fog_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """One fog item in full: its fields, its Experiments (newest first), its folder, its drop or crystallize record."""
    store = get_store(_root(root))
    try:
        item = require_fog(store, fog_id)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.show")
        raise typer.Exit(code=1)
    _emit_fog(store, item, json_output, command="fog.show")


@fog_app.command("edit")
def fog_edit(
    fog_id: str,
    root: str = ROOT_OPTION,
    text: str | None = typer.Option(None, "--text"),
    near: list[str] = typer.Option(None, "--near", help="Replace the near nodes (repeatable)"),
    clear_near: bool = typer.Option(False, "--clear-near", help="Near no node"),
    notes: str | None = typer.Option(None, "--notes"),
    edited_by: str = typer.Option("human", "--by"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Change an open item's text, notes or near nodes; what isn't given stays."""
    store = get_store(_root(root))
    try:
        if clear_near and near:
            raise ProofMapError("FOG_FLAG_CONFLICT", "fog edit takes either --near or --clear-near, not both")
        item = edit_fog(store, fog_id, text=text, near=[] if clear_near else (near or None), notes=notes, edited_by=edited_by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.edit")
        raise typer.Exit(code=1)
    _emit_fog(store, item, json_output, command="fog.edit")


@fog_app.command("drop")
def fog_drop(
    fog_id: str,
    root: str = ROOT_OPTION,
    reason: str = typer.Option(..., "--reason", help="Why this direction is given up"),
    dropped_by: str = typer.Option("human", "--by"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Give an item up, saying why. Reversible with `fog reopen`."""
    store = get_store(_root(root))
    try:
        item = drop_fog(store, fog_id, reason=reason, dropped_by=dropped_by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.drop")
        raise typer.Exit(code=1)
    _emit_fog(store, item, json_output, command="fog.drop")


@fog_app.command("reopen")
def fog_reopen(fog_id: str, root: str = ROOT_OPTION, by: str = typer.Option("human", "--by"), json_output: bool = typer.Option(False, "--json")) -> None:
    """Take a dropped item back."""
    store = get_store(_root(root))
    try:
        item = reopen_fog(store, fog_id, by=by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.reopen")
        raise typer.Exit(code=1)
    _emit_fog(store, item, json_output, command="fog.reopen")


@fog_app.command("crystallize")
def fog_crystallize(
    fog_id: str,
    node_id: str,
    statement: str,
    root: str = ROOT_OPTION,
    parent: str | None = typer.Option(None, "--parent", help="The node the new Claim is a single-child Split of (default: the item's one near node)"),
    no_parent: bool = typer.Option(False, "--no-parent", help="A free-standing Claim, even when the item is near a node"),
    reassign: bool = typer.Option(False, "--reassign", help="Take the parent's claim over from whoever holds it"),
    assumption: list[str] = typer.Option([], "--assumption"),
    display_label: str = typer.Option("", "--display-label"),
    created_by: str = typer.Option("human", "--created-by"),
    medium: str = typer.Option("", "--medium", help="The new Claim's medium: latex (default) or computation"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """State an open fog item as a Claim (written here, never taken from the item's text); the item leaves the fog list."""
    store = get_store(_root(root))
    try:
        made = crystallize_fog(
            store, fog_id, node_id, statement, parent=parent, no_parent=no_parent, reassign=reassign,
            assumptions=assumption, display_label=display_label, created_by=created_by,
            medium=medium or None,
        )
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.crystallize")
        raise typer.Exit(code=1)
    if json_output:
        # a stable shape (ADR-0006): `reminder` is always there, empty when there is nothing to say
        payload = {**made.node.model_dump(mode="json"), "fog": {"id": made.fog.id, "status": made.fog.status.value, "node_id": made.fog.node_id}, "reminder": made.reminder}
        typer.echo(dump_envelope(success_envelope("fog.crystallize", payload)))
        return
    typer.echo(render_proof_map_node(made.node, crystallized_from=made.fog.id))
    if made.reminder:
        typer.echo(made.reminder)


@fog_experiment_app.command("record")
def fog_experiment_record(
    fog_id: str,
    outcome: str,
    root: str = ROOT_OPTION,
    summary: str = typer.Option(..., "--summary", help="What was computed and what it showed, in a sentence or two"),
    run_by: str = typer.Option(..., "--run-by", help="Who ran it"),
    path: str | None = typer.Option(None, "--path", help="Its script or output, under proofs/ (an agent's own scratch/, or proofs/fog/<fog-id>/)"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Record a numerical run against an open fog item: supports, refutes, inconclusive or error. Never changes the item's status."""
    store = get_store(_root(root))
    try:
        experiment = record_experiment(store, fog_id, outcome, summary=summary, run_by=run_by, path=path)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.experiment.record")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("fog.experiment.record", experiment.model_dump(mode="json"))))
        return
    typer.echo(render_fog_experiments(fog_id, [experiment.model_dump(mode="json")]))


@fog_experiment_app.command("list")
@read_scoped
def fog_experiment_list(fog_id: str, root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """An item's Experiments, oldest first."""
    store = get_store(_root(root))
    try:
        require_fog(store, fog_id)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="fog.experiment.list")
        raise typer.Exit(code=1)
    experiments = [experiment.model_dump(mode="json") for experiment in list_experiments(store, fog_id)]
    if json_output:
        typer.echo(dump_envelope(success_envelope("fog.experiment.list", experiments)))
        return
    typer.echo(render_fog_experiments(fog_id, experiments))


@node_app.command("claim")
def node_claim(
    node_id: str,
    assignee: str = typer.Option(..., "--assignee", "--claimant", help="Who is taking the node on (an agent or person name)"),
    reassign: bool = typer.Option(False, "--reassign", help="Take the node over from its current assignee"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Assign a node to yourself before working on it, usually one on the frontier: a planning signal, not a lock (ADR-0010)."""
    store = get_store(_root(root))
    try:
        claim = claim_node(store, node_id, claimant_id=assignee, reassign=reassign)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.claim")
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
        _emit_error(exc, json_output, command="node.unassign")
        raise typer.Exit(code=1)
    _emit_claim(claim, json_output, command="node.unassign")


node_app.command("release", hidden=True)(node_unassign)


def _emit_candidate_proof(record, json_output: bool, *, command: str, notices: list[dict] | None = None) -> None:
    """The Candidate proof as an envelope or a table; with `notices` (errors.NOTICE_CODES), what
    the command has to tell beside it: `data.notices` under --json, a `Note` line each otherwise."""
    if json_output:
        data = record.model_dump(mode="json")
        if notices is not None:
            data["notices"] = notices
        typer.echo(dump_envelope(success_envelope(command, data)))
        return
    typer.echo(render_candidate_proof(record))
    for notice in notices or []:
        typer.echo(f"Note ({notice['code']}): {notice['message']}")


@node_app.command("request-review")
def node_request_review(
    node_id: str,
    rationale: str = typer.Option(..., "--rationale", help="Why this node is now appropriately scoped to prove directly"),
    requested_by: str = typer.Option("human", "--requested-by"),
    gated_by: list[str] = typer.Option(None, "--gated-by", help="A run's Prover: the SHA-256 of the Verifier's passing verdict, once; refused (VERDICT_STALE) if the files changed since, or the newest verdict is not that passing one (ADR-0019)"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Snapshot the node's working proof.tex (or a computation's run.sh and out/) for review (ADR-0010). Needs no claim."""
    store = get_store(_root(root))
    try:
        # the gate is one digest, given once: a second --gated-by, or an empty one, is not a way out of it (ADR-0019 point 3)
        gates = list(gated_by or [])
        if gates and (len(gates) != 1 or not re.fullmatch(r"[0-9a-f]{64}", gates[0])):  # given once: a repeat, equal or not, is refused
            raise ProofMapError("GATE_MALFORMED", "--gated-by is the passing verdict's SHA-256 (64 hex digits), given once; repeated, empty or malformed, the request is refused")
        record = request_review(store, node_id, requested_by=requested_by, rationale=rationale, gated_by=gates[0] if gates else None)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.request_review")
        raise typer.Exit(code=1)
    # a large out/ is a notice, never a refusal (spec #145): the researcher's .gitignore decides what stays
    _emit_candidate_proof(record, json_output, command="node.request_review", notices=review_notices(store, record))


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
    assumption: list[str] = typer.Option(None, "--assumption", help="Repeatable: an assumption of the one --child (as the page's split gives it)"),
    display_label: str = typer.Option("", "--display-label", help="The one --child's display label"),
    definition: list[str] = typer.Option(None, "--definition", help="Repeatable: a definition the one --child is written in, beside the parent's, which every child names"),
    root: str = ROOT_OPTION,
    created_by: str = "human",
    reassign: bool = typer.Option(False, "--reassign", help="Take the claim over from whoever holds it (recorded as `claim --reassign` records it); the node need not be on the frontier"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Decompose parent_id into new claim-kind children. Ungated — no researcher approval needed.
    All or nothing; a node someone else holds is theirs to split unless --reassign.
    With a single --child, --assumption and --display-label give it those, as the page's split does (issue #154)."""
    if (assumption or display_label or definition) and len(child) != 1:
        raise click.UsageError("--assumption, --display-label and --definition go with a single --child")
    store = get_store(_root(root))
    try:
        specs = []
        for entry in child:
            if "=" not in entry:
                raise ProofMapError(
                    "INVALID_CHILD_SPEC", f"'{entry}' is not in the form <child-id>=<statement>"
                )
            child_id, statement = entry.split("=", 1)
            specs.append({"id": child_id, "statement": statement, "assumptions": list(assumption or []), "display_label": display_label,
                          "definitions": list(definition or [])})
        children = split_node(store, parent_id, specs, created_by=created_by, reassign=reassign)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.split")
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(
            dump_envelope(success_envelope("node.split", [node.model_dump(mode="json") for node in children]))
        )
    else:
        typer.echo(render_proof_map_node_list(children))


_ROLES_HELP = ", ".join(AGENT_ROLES[:-1]) + f" or {AGENT_ROLES[-1]}"  # the roles, as the help spells them (ADR-0019: never by hand)


@node_app.command("progress")
def node_progress(
    node_id: str,
    plan: list[str] = typer.Option(None, "--plan", help="A step of the plan; repeat for each step, in order"),
    step: int = typer.Option(None, "--step", help="The step being reported, counting from 1"),
    status: str = typer.Option("", "--status", help="With --step: started, done, stuck, or needs-human (a decision only the researcher can make, named in --note)"),
    note: str = typer.Option("", "--note", help="A line about the step: what it found, why it is stuck, what the next role should do"),
    handoff: str = typer.Option("", "--handoff", help=f"Hand the work to this role ({_ROLES_HELP}) and end the turn"),
    verdict: str = typer.Option("", "--verdict", help="The Verifier's verdict on the working proof as it stands: passed or failed, with the objections in --note (ADR-0019)"),
    attempt: str = typer.Option("", "--attempt", help="Close an abandoned line: what it tried to establish; goes with --failed-on (ADR-0019)"),
    method: str = typer.Option("", "--method", help="With --attempt: the approach"),
    failed_on: str = typer.Option("", "--failed-on", help="With --attempt: the objection or obstruction it failed on"),
    coordinator: str = typer.Option("", "--coordinator", help="What a Coordinator did on this Theorem or Lemma's subtree: a run it started, a redirect, a stop (ADR-0019 point 18); no role"),
    question: str = typer.Option("", "--question", help="A judgement call made instead of stopping: \"<the choice made; the alternative>\", a Standing question the researcher answers later (ADR-0021)"),
    role: str = typer.Option("", "--role", help=f"{_ROLES_HELP} (default: PROOF_AGENT_ROLE, set in the agent's runtime)"),
    by: str = typer.Option("", "--by", help="Who reports; empty means PROOF_AGENT_NAME from the agent's runtime, else human"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """A Proof agent's report on this node — the studio's work log (spec #145): its plan, a step, a handoff,
    the Verifier's verdict, an abandoned attempt (ADR-0019) or a choice made (ADR-0021). Without any of them: the node's
    work log so far."""
    store = get_store(_root(root))
    try:
        if not plan and step is None and not handoff and not verdict and not attempt and not failed_on and not coordinator and not question:
            log = work_log(store, node_id)
            if json_output:
                typer.echo(dump_envelope(success_envelope("node.progress", log)))
            else:
                typer.echo(render_work_log(node_id, log))
            return
        entry = record_progress(
            store, node_id, role=role or os.environ.get("PROOF_AGENT_ROLE") or None, by=by or os.environ.get("PROOF_AGENT_NAME") or "human",
            plan=plan or None, step=step, status=status or None, note=note, handoff=handoff or None,
            verdict=verdict or None, attempt=attempt or None, method=method or None, failed_on=failed_on or None, coordinator=coordinator or None,
            question=question or None,
        )
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.progress")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("node.progress", entry)))
    else:
        typer.echo(render_work_log_entry(node_id, entry))


@node_app.command("answer")
def node_answer(
    node_id: str,
    question_id: str,
    keep: bool = typer.Option(False, "--keep", help="The choice the role made stands"),
    answer: str = typer.Option("", "--answer", help="The reading to follow instead: recorded as a redirect for the node's next run"),
    by: str = typer.Option("human", "--by", help="Who answers: the researcher"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Answer a Standing question on the node: keep the choice the role made, or redirect it (ADR-0021)."""
    store = get_store(_root(root))
    try:
        if os.environ.get("PROOF_AGENT_ROLE"):  # an agent's runtime: the answer is the researcher's
            raise ProofMapError("ANSWER_IS_THE_RESEARCHERS", "a Standing question is answered by the researcher, not by a Proof agent")
        entry = answer_question(store, node_id, question_id, keep=keep, answer=answer or None, by=by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.answer")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("node.answer", entry)))
    else:
        typer.echo(f"{question_id} on {node_id}: " + ("the choice stands" if entry["keep"] else f"redirect — {entry['redirect']}"))


@node_medium_app.command("set")
def node_medium_set(
    node_id: str,
    medium: str = typer.Argument(..., help="latex or computation"),
    by: str = typer.Option("human", "--by", help="Who is switching (an agent or person name)"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Switch a node's medium. Allowed at any time: files stay, the missing entry (run.sh or proof.tex) is scaffolded, an Acceptance stands."""
    store = get_store(_root(root))
    try:
        node = set_medium(store, node_id, medium, edited_by=by)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.medium.set")
        raise typer.Exit(code=1)
    _emit_node(node, json_output, command="node.medium.set")


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
        _emit_error(exc, json_output, command="node.depend")
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
        _emit_error(exc, json_output, command="challenge.open")
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
        _emit_error(exc, json_output, command="challenge.show")
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
    snapshot_sha256: str | None = typer.Option(
        None, "--snapshot-sha256",
        help="The SHA-256 of the snapshot the check ran on; refused unless it is the snapshot's hash now. "
             "Omitted, the check is bound to the snapshot's hash at the moment of recording.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Record an Evidence check against a specific Candidate proof. Advisory, ungated."""
    store = get_store(_root(root))
    try:
        check = record_evidence_check(store, candidate_proof_id, outcome, notes=notes, run_by=run_by, snapshot_sha256=snapshot_sha256)
    except ProofMapError as exc:
        _emit_error(exc, json_output, command="node.evidence.record")
        raise typer.Exit(code=1)
    _emit_evidence_check(check, json_output, command="node.evidence.record")


@node_evidence_app.command("review")
def evidence_review(check_id: str, decision: str = typer.Argument(""), root: str = ROOT_OPTION, json_output: bool = typer.Option(False, "--json")) -> None:
    """Judge an Evidence check trusted/unusable — on the proof map page (ADR-0010)."""
    human_review_required(root, command="node.evidence.review", kind="evidence_review", target_id=check_id, node_id=None, json_output=json_output)


node_app.add_typer(node_evidence_app, name="evidence")
node_app.add_typer(node_medium_app, name="medium")


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
app.add_typer(trust_rule_app, name="trust-rule", rich_help_panel=PROOF_MAP_PANEL)
fog_app.add_typer(fog_experiment_app, name="experiment")
app.add_typer(fog_app, name="fog", rich_help_panel=PROOF_MAP_PANEL)
app.add_typer(definition_app, name="definition", rich_help_panel=PROOF_MAP_PANEL)
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
    node_id: list[str] = typer.Option(None, "--node-id", help="The node this is about; once. A run's role may name only its own node (ADR-0019 point 12)"),
    project: list[str] = typer.Option(None, "--project", help="The project's instance id this entry is for; once. Refused when the project opened is another: a run's role writes its own project's memory and no other's"),
    candidate_proof_id: str = "",
    review_id: str = "",
    route_id: str = "",
    importance: str = "medium",
    status: str = typer.Option("", help="stable | tentative | failed | tactic: what was learned, as against what was tried (ADR-0019 point 8)"),
    source: str = typer.Option("manual", help="Who learned it: manual, or a run's agent and role as <agent>/<role>"),
    tag: list[str] = typer.Option(None, "--tag"),
    notes: str = "",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Record a memory entry, scoped to a proof-map node (and one of its Candidate proofs or reviews).

    The scope is checked against the map, and a bad one writes nothing. The
    legacy theorem/goal/obligation/blocker scope is read-only (ADR-0012). A
    run's role records what it learned here — a dead end (--status failed), a
    technique that worked (--status tactic), an observation not yet trusted
    (--status tentative) — scoped to its own node and tagged with --source
    <agent>/<role>; other nodes' briefings read it (ADR-0019 part C). The
    node is named once: a second --node-id, or an empty one, is refused, so
    a permission that admits `proof memory add --node-id <node>` admits that
    node's memory and no other's.
    """
    given = list(node_id or [])
    projects = list(project or [])
    refused = None
    if len(given) > 1 or any(not value.strip() for value in given):
        refused = "--node-id names one node, once" if len(given) > 1 else "--node-id needs a node id"
    elif len(projects) > 1 or any(not value.strip() for value in projects):
        refused = "--project names one project, once" if len(projects) > 1 else "--project needs a project instance id"
    elif projects:
        try:
            opened = read_project_instance_id(get_store(_root(root)))
        except Exception:  # noqa: BLE001 — no project there: not the one named either
            opened = None
        if opened != projects[0].strip():
            refused = f"the project at {_root(root)} is not project {projects[0].strip()}: this entry is for another project"
    if refused is not None:
        _emit_error(ProofMapError("INVALID_INPUT", refused), json_output, command="memory.add")
        raise typer.Exit(code=1)
    try:
        output = cmd_memory_add(
            content,
            _root(root),
            layer=layer,
            node_id=given[0].strip() if given else "",
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
        _emit_error(exc, json_output, command="memory.add")
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
        _emit_error(exc, json_output, command=command)
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


def _read_bundle(source: str) -> str:
    """A bundle's text: from the file `source`, or stdin for "-" (a bundle is too big for an argument)."""
    if source == "-":
        return sys.stdin.read()
    try:
        return Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProofMapError("BUNDLE_UNREADABLE", f"can't read the bundle {source}: {exc}", details={"path": source}) from None


def _emit_exchange_error(exc: ProofMapError, json_output: bool, *, command: str) -> None:
    if json_output:
        typer.echo(dump_envelope(error_envelope(command, exc.code, exc.message, details=exc.details or None)))
        return
    typer.echo(f"Error: {exc.message}")
    for problem in exc.details.get("problems", [])[1:]:
        typer.echo(f"  - {problem.get('code')}: {problem.get('message') or problem.get('at')}")


@exchange_app.command("export")
def exchange_export(
    root: str = ROOT_OPTION,
    note: str = "",
    output: str = typer.Option("", "--output", "-o", help="Write the bundle to this file instead of stdout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """The project as one bundle: the proof map, its Proof vault files and its side state (#31).
    Its contracts' and references' trust fields are legacy (ADR-0012); an importer resets them."""
    try:
        bundle_json = cmd_exchange_export(_root(root), note=note)  # led by the legacy notice
    except ProofMapError as exc:  # a node folder it can't read whole: an unreadable file, a symbolic link
        _emit_error(exc, json_output, command="exchange.export")
        raise typer.Exit(code=1)
    if output:
        Path(output).write_text(bundle_json + "\n", encoding="utf-8")
        bundle = parse_bundle(bundle_json)
        counts = inspect_exchange_bundle(bundle).section_counts
        summary = {
            "legacy_notice": LEGACY_TRUST_NOTICE, "path": output, "bundle_id": bundle.id, "section_counts": counts,
            "notices": bundle.notices,  # SNAPSHOT_EXPORTED_UNVERIFIABLE per snapshot it had to leave files out of
        }
        if json_output:
            typer.echo(dump_envelope(success_envelope("exchange.export", summary)))
        else:
            typer.echo(f"Wrote bundle {bundle.id} to {output}: {counts['proof_map_nodes']} node(s), {counts['vault_files']} vault file(s)")
            for item in bundle.notices:
                typer.echo(f"Note ({item['code']}): {item['message']}")
        return
    _emit_legacy_json("exchange.export", json_output, lambda: bundle_json)


@exchange_app.command("import")
def exchange_import(
    bundle_file: str = typer.Argument("-", help="The bundle file (`exchange export`'s output, with or without --json); - reads stdin"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Merge a bundle into this project: validated whole first, then written in one transaction (#31)."""
    try:
        bundle = parse_bundle(_read_bundle(bundle_file))
        report = import_exchange_bundle(get_store(_root(root)), bundle)
    except ProofMapError as exc:
        _emit_exchange_error(exc, json_output, command="exchange.import")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(dump_envelope(success_envelope("exchange.import", report.model_dump(mode="json"))))
    else:
        typer.echo(summarize_import_report(report))


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
        _emit_error(exc, json_output, command="handoff.create")
        raise typer.Exit(code=1)


@handoff_app.command("inspect")
def handoff_inspect(
    bundle_file: str = typer.Argument("", help="A bundle file, or - for stdin; omitted, this project's own"),
    root: str = ROOT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """What importing a bundle would carry over."""
    try:
        bundle = parse_bundle(_read_bundle(bundle_file)) if bundle_file else export_exchange_bundle(get_store(_root(root)))
    except ProofMapError as exc:
        _emit_exchange_error(exc, json_output, command="handoff.inspect")
        raise typer.Exit(code=1)
    report = inspect_exchange_bundle(bundle)
    if json_output:
        typer.echo(dump_envelope(success_envelope("handoff.inspect", report.model_dump(mode="json"))))
    else:
        typer.echo(summarize_inspect_report(report))


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


# The other packages' commands (ADR-0018): proof-web adds `home`, `map open` and `map serve` through
# the `proof_cli.commands` entry point. Without it, those commands say which package to install.
from . import plugins as _plugins  # noqa: E402

_plugins.load_commands(app, map_app, review_app)
if "home" not in _plugins.command_names(app):
    _plugins.install_web_fallbacks(app, map_app, panel=PROOF_MAP_PANEL)


if __name__ == "__main__":
    app()
