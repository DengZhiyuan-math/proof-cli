from __future__ import annotations

from pathlib import Path

import typer

from .commands import (
    cmd_blocker_add,
    cmd_blocker_list,
    cmd_export,
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
    cmd_proof_review_suspicion,
    cmd_proof_formalize_edit,
    cmd_proof_formalize_recommend,
    cmd_proof_formalize_show,
    cmd_proof_trace_dependency,
    cmd_proof_trace_machine_check,
    cmd_proof_verify_accept,
    cmd_proof_verify_queue,
    cmd_proof_verify_reject,
    cmd_proof_verify_result,
    cmd_proof_verify_run,
    cmd_proof_verify_stale,
    cmd_proof_verify_status,
    cmd_proof_policy_list,
    cmd_proof_policy_set,
    cmd_proof_recommend,
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
    cmd_proof_provenance_show,
    cmd_reference_import,
    cmd_reference_list,
    cmd_reference_review,
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
)
from .review import render_verification_output

app = typer.Typer(add_completion=False, help="Mathematical Proof CLI")
asset_app = typer.Typer(help="Reusable asset workflows")
pack_app = typer.Typer(help="Domain pack workflows")
policy_app = typer.Typer(help="Automation policy workflows")
recommend_app = typer.Typer(help="Cross-project recommendation workflows")
reuse_app = typer.Typer(help="Reuse outcome workflows")
automate_app = typer.Typer(help="Supervised automation workflows")
benchmark_app = typer.Typer(help="Automation evaluation workflows")
goal_app = typer.Typer(help="Goal operations")
theorem_app = typer.Typer(help="Theorem registry")
obligation_app = typer.Typer(help="Obligation queue")
blocker_app = typer.Typer(help="Blocker tracking")
reference_app = typer.Typer(help="Reference workflows")
memory_app = typer.Typer(help="Memory workflows")
provenance_app = typer.Typer(help="Provenance workflows")
bug_app = typer.Typer(help="Proof bug workflows")
debug_app = typer.Typer(help="Proof debug workflows")
review_app = typer.Typer(help="Proof review workflows")
repair_app = typer.Typer(help="Proof repair workflows")
trace_app = typer.Typer(help="Dependency tracing workflows")
evidence_app = typer.Typer(help="Evidence inspection workflows")
explain_app = typer.Typer(help="Theorem explanation workflows")
formalize_app = typer.Typer(help="Formal bridge workflows")
verify_app = typer.Typer(help="Verification workflows")


def _root(path: str | None) -> Path:
    return Path(path or ".")


@app.command()
def init(root: str = ".") -> None:
    typer.echo(cmd_init(_root(root)))


@app.command()
def status(root: str = ".") -> None:
    typer.echo(cmd_status(_root(root)))


@app.command()
def snapshot(root: str = ".", note: str = "") -> None:
    typer.echo(cmd_snapshot(_root(root), handoff_note=note))


@app.command()
def history(root: str = ".") -> None:
    typer.echo(cmd_history(_root(root)))


@app.command()
def export(root: str = ".") -> None:
    typer.echo(cmd_export(_root(root)))


@app.command()
def search(query: str, root: str = ".", limit: int = 10) -> None:
    typer.echo(cmd_search(query, _root(root), limit=limit))


@app.command()
def reason(theorem_id: str, root: str = ".", notes: str = "") -> None:
    typer.echo(cmd_proof_reason(theorem_id, _root(root), notes=notes))


@app.command()
def revalidate(source_id: str, root: str = ".", backend_target: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"revalidate {source_id}",
            cmd_proof_revalidate(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


app.add_typer(goal_app, name="goal")
app.add_typer(asset_app, name="asset")
app.add_typer(pack_app, name="pack")
app.add_typer(policy_app, name="policy")
app.add_typer(recommend_app, name="recommend")
app.add_typer(reuse_app, name="reuse")
app.add_typer(automate_app, name="automate")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(theorem_app, name="theorem")
app.add_typer(obligation_app, name="obligation")
app.add_typer(blocker_app, name="blocker")
app.add_typer(reference_app, name="reference")
app.add_typer(memory_app, name="memory")
app.add_typer(provenance_app, name="provenance")
app.add_typer(bug_app, name="bug")
app.add_typer(debug_app, name="debug")
app.add_typer(review_app, name="review")
app.add_typer(repair_app, name="repair")
app.add_typer(trace_app, name="trace")
app.add_typer(evidence_app, name="evidence")
app.add_typer(explain_app, name="explain")
app.add_typer(formalize_app, name="formalize")
app.add_typer(verify_app, name="verify")


@asset_app.command("list")
def asset_list(root: str = ".", project_id: str = "", kind: str = "", status: str = "") -> None:
    typer.echo(cmd_proof_asset_list(_root(root), project_id=project_id, kind=kind, status=status))


@asset_app.command("show")
def asset_show(asset_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_asset_show(asset_id, _root(root)))


@asset_app.command("publish")
def asset_publish(
    asset_json: str,
    root: str = ".",
    review_action: str = "publish",
    reviewer: str = "human",
    notes: str = "",
) -> None:
    typer.echo(cmd_proof_asset_publish(asset_json, _root(root), review_action=review_action, reviewer=reviewer, notes=notes))


@asset_app.command("review")
def asset_review(
    asset_id: str,
    action: str,
    root: str = ".",
    reviewer: str = "human",
    notes: str = "",
) -> None:
    typer.echo(cmd_proof_asset_review(asset_id, action, _root(root), reviewer=reviewer, notes=notes))


@pack_app.command("list")
def pack_list(root: str = ".", project_id: str = "") -> None:
    typer.echo(cmd_proof_pack_list(_root(root), project_id=project_id))


@pack_app.command("show")
def pack_show(pack_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_pack_show(pack_id, _root(root)))


@pack_app.command("install")
def pack_install(
    pack_json: str,
    root: str = ".",
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
def pack_update(pack_json: str, root: str = ".", reviewer: str = "human", notes: str = "") -> None:
    typer.echo(cmd_proof_pack_update(pack_json, _root(root), reviewer=reviewer, notes=notes))


@policy_app.command("list")
def policy_list(root: str = ".", project_id: str = "") -> None:
    typer.echo(cmd_proof_policy_list(_root(root), project_id=project_id))


@policy_app.command("set")
def policy_set(profile_json: str, root: str = ".", reviewer: str = "human", notes: str = "") -> None:
    typer.echo(cmd_proof_policy_set(profile_json, _root(root), reviewer=reviewer, notes=notes))


@recommend_app.callback(invoke_without_command=True)
def recommend(
    ctx: typer.Context,
    root: str = ".",
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
def reuse_show(root: str = ".", asset_id: str = "", project_id: str = "") -> None:
    typer.echo(cmd_proof_reuse_show(_root(root), asset_id=asset_id, project_id=project_id))


@automate_app.command("plan")
def automate_plan(
    scope: str,
    task_type: str,
    root: str = ".",
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
def automate_run(run_id: str, root: str = ".", approvals_json: str = "", interrupt_after: int | None = None, notes: str = "") -> None:
    typer.echo(cmd_proof_automate_run(run_id, _root(root), approvals_json=approvals_json, interrupt_after=interrupt_after, notes=notes))


@automate_app.command("trace")
def automate_trace(run_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_automate_trace(run_id, _root(root)))


@automate_app.command("review")
def automate_review(
    run_id: str,
    action_id: str,
    root: str = ".",
    decision: str = "approve",
    reviewer: str = "human",
    rationale: str = "",
) -> None:
    typer.echo(cmd_proof_automate_review(run_id, action_id, _root(root), decision=decision, reviewer=reviewer, rationale=rationale))


@benchmark_app.command("run")
def benchmark_run(
    root: str = ".",
    benchmark_name: str = "",
    scenario_id: str = "",
    notes: str = "",
    record_json: list[str] = typer.Option(None, "--record-json"),
) -> None:
    typer.echo(cmd_proof_benchmark_run(_root(root), record_json=record_json, benchmark_name=benchmark_name, scenario_id=scenario_id, notes=notes))


@goal_app.command("set")
def goal_set(goal: str, root: str = ".") -> None:
    typer.echo(cmd_goal_set(goal, root=_root(root)))


@goal_app.command("list")
def goal_list(root: str = ".") -> None:
    typer.echo(cmd_goal_list(_root(root)))


@theorem_app.command("add")
def theorem_add(
    theorem_id: str,
    name: str,
    statement: str,
    root: str = ".",
    kind: str = "theorem",
    assumption: list[str] = typer.Option(None, "--assumption"),
    export: list[str] = typer.Option(None, "--export"),
    source_ref: str = "internal/project",
    notes: str = "",
) -> None:
    typer.echo(
        cmd_theorem_add(
            theorem_id=theorem_id,
            name=name,
            statement=statement,
            root=_root(root),
            kind=kind,
            assumption=assumption,
            export=export,
            source_ref=source_ref,
            notes=notes,
        )
    )


@theorem_app.command("show")
def theorem_show(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_theorem_show(theorem_id, root=_root(root)))


@theorem_app.command("extract")
def theorem_extract(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_theorem_extract(theorem_id, root=_root(root)))


@theorem_app.command("list")
def theorem_list(root: str = ".") -> None:
    typer.echo(cmd_theorem_list(_root(root)))


@theorem_app.command("apply")
def theorem_apply(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_theorem_apply(theorem_id, root=_root(root)))


@theorem_app.command("ground")
def theorem_ground(theorem_id: str, reference_id: list[str] = typer.Option(..., "--reference-id"), root: str = ".", notes: str = "") -> None:
    typer.echo(cmd_theorem_ground(theorem_id, reference_id, root=_root(root), notes=notes))


@obligation_app.command("add")
def obligation_add(goal_statement: str, root: str = ".", source_step_id: str = "", required_for: str = "") -> None:
    typer.echo(
        cmd_obligation_add(
            goal_statement=goal_statement,
            root=_root(root),
            source_step_id=source_step_id or None,
            required_for=required_for or None,
        )
    )


@obligation_app.command("list")
def obligation_list(root: str = ".") -> None:
    typer.echo(cmd_obligation_list(_root(root)))


@obligation_app.command("derive")
def obligation_derive(theorem_id: str, root: str = ".", notes: str = "") -> None:
    typer.echo(cmd_proof_obligation_derive(theorem_id, _root(root), notes=notes))


@blocker_app.command("add")
def blocker_add(description: str, root: str = ".", scope: str = "global", failure_type: str = "unknown") -> None:
    typer.echo(cmd_blocker_add(description, root=_root(root), scope=scope, failure_type=failure_type))


@blocker_app.command("list")
def blocker_list(root: str = ".") -> None:
    typer.echo(cmd_blocker_list(_root(root)))


@reference_app.command("list")
def reference_list(root: str = ".") -> None:
    typer.echo(cmd_reference_list(_root(root)))


@reference_app.command("show")
def reference_show(reference_id: str, root: str = ".") -> None:
    typer.echo(cmd_reference_show(reference_id, root=_root(root)))


@reference_app.command("import")
def reference_import(
    reference_id: str,
    title: str,
    year: int,
    root: str = ".",
    author: list[str] = typer.Option(None, "--author"),
    source_type: str = "other",
    origin: str = "",
    bibliographic_source: str = "",
    identifier: str = "",
    url: str = "",
    notes: str = "",
) -> None:
    typer.echo(
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


@reference_app.command("review")
def reference_review(reference_id: str, action: str, root: str = ".", rationale: str = "") -> None:
    typer.echo(cmd_reference_review(reference_id, action, root=_root(root), rationale=rationale))


@memory_app.command("list")
def memory_list(root: str = ".", layer: str = "", theorem_id: str = "", goal_id: str = "") -> None:
    typer.echo(cmd_memory_list(_root(root), layer=layer, theorem_id=theorem_id, goal_id=goal_id))


@memory_app.command("show")
def memory_show(artifact_id: str, root: str = ".") -> None:
    typer.echo(cmd_memory_show(artifact_id, root=_root(root)))


@memory_app.command("add")
def memory_add(
    content: str,
    root: str = ".",
    layer: str = "working",
    theorem_id: str = "",
    goal_id: str = "",
    obligation_id: str = "",
    blocker_id: str = "",
    route_id: str = "",
    importance: str = "medium",
    status: str = "",
    source: str = "manual",
    tag: list[str] = typer.Option(None, "--tag"),
    notes: str = "",
) -> None:
    typer.echo(
        cmd_memory_add(
            content,
            _root(root),
            layer=layer,
            theorem_id=theorem_id,
            goal_id=goal_id,
            obligation_id=obligation_id,
            blocker_id=blocker_id,
            route_id=route_id,
            importance=importance,
            status=status,
            source=source,
            tag=tag,
            notes=notes,
        )
    )


@provenance_app.command("show")
def provenance_show(target_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_provenance_show(target_id, root=_root(root)))


@bug_app.command("scan")
def bug_scan(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_bug_scan(theorem_id, _root(root)))


@bug_app.command("list")
def bug_list(root: str = ".", theorem_id: str = typer.Option("", "--theorem-id")) -> None:
    typer.echo(cmd_proof_bug_list(_root(root), theorem_id=theorem_id))


@bug_app.command("show")
def bug_show(bug_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_bug_show(bug_id, _root(root)))


@evidence_app.command("show")
def evidence_show(bug_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_evidence_show(bug_id, _root(root)))


@debug_app.command("generate")
def debug_generate(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_debug_generate(theorem_id, _root(root)))


@debug_app.command("list")
def debug_list(root: str = ".", theorem_id: str = typer.Option("", "--theorem-id")) -> None:
    typer.echo(cmd_proof_debug_list(_root(root), theorem_id=theorem_id))


@repair_app.command("mark")
def repair_mark(
    bug_id: str,
    status: str = typer.Argument("repaired"),
    status_override: str | None = typer.Option(None, "--status"),
    root: str = ".",
    note: str = "",
) -> None:
    typer.echo(cmd_proof_repair_mark(bug_id, status_override or status, _root(root), note=note))


@review_app.command("suspicion")
def review_suspicion(
    bug_id: str,
    status: str = typer.Argument("under_review"),
    status_override: str | None = typer.Option(None, "--status"),
    root: str = ".",
    rationale: str = "",
) -> None:
    typer.echo(cmd_proof_review_suspicion(bug_id, status_override or status, _root(root), rationale=rationale))


@trace_app.command("dependency")
def trace_dependency(target_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_trace_dependency(target_id, _root(root)))


@trace_app.command("machine-check")
def trace_machine_check(source_id: str, root: str = ".") -> None:
    typer.echo(render_verification_output(f"trace machine-check {source_id}", cmd_proof_trace_machine_check(source_id, _root(root))))


@explain_app.command("apply")
def explain_apply(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_proof_explain_apply(theorem_id, _root(root)))


@formalize_app.command("recommend")
def formalize_recommend(source_id: str, root: str = ".", backend_target: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"formalize recommend {source_id}",
            cmd_proof_formalize_recommend(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


@formalize_app.command("show")
def formalize_show(source_id: str, root: str = ".") -> None:
    typer.echo(render_verification_output(f"formalize show {source_id}", cmd_proof_formalize_show(source_id, _root(root))))


@formalize_app.command("edit")
def formalize_edit(source_id: str, root: str = ".", backend_target: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"formalize edit {source_id}",
            cmd_proof_formalize_edit(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


@verify_app.command("queue")
def verify_queue(source_id: str, root: str = ".", backend_target: str = "", route_id: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"verify queue {source_id}",
            cmd_proof_verify_queue(source_id, _root(root), backend_target=backend_target, route_id=route_id, notes=notes),
        )
    )


@verify_app.command("run")
def verify_run(source_id: str, root: str = ".", backend_target: str = "", notes: str = "") -> None:
    typer.echo(
        render_verification_output(
            f"verify run {source_id}",
            cmd_proof_verify_run(source_id, _root(root), backend_target=backend_target, notes=notes),
        )
    )


@verify_app.command("status")
def verify_status(source_id: str, root: str = ".") -> None:
    typer.echo(render_verification_output(f"verify status {source_id}", cmd_proof_verify_status(source_id, _root(root))))


@verify_app.command("result")
def verify_result(source_id: str, root: str = ".") -> None:
    typer.echo(render_verification_output(f"verify result {source_id}", cmd_proof_verify_result(source_id, _root(root))))


@verify_app.command("accept")
def verify_accept(source_id: str, root: str = ".", notes: str = "") -> None:
    typer.echo(render_verification_output(f"verify accept {source_id}", cmd_proof_verify_accept(source_id, _root(root), notes=notes)))


@verify_app.command("reject")
def verify_reject(source_id: str, root: str = ".", notes: str = "") -> None:
    typer.echo(render_verification_output(f"verify reject {source_id}", cmd_proof_verify_reject(source_id, _root(root), notes=notes)))


@verify_app.command("stale")
def verify_stale(
    source_id: str,
    root: str = ".",
    reason: str = "",
    dependency: list[str] = typer.Option(None, "--dependency"),
) -> None:
    typer.echo(
        render_verification_output(
            f"verify stale {source_id}",
            cmd_proof_verify_stale(source_id, _root(root), reason=reason, changed_dependency_ids=dependency),
        )
    )
