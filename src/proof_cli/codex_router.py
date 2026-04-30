from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import typer

from .commands import (
    cmd_init,
    cmd_blocker_add,
    cmd_blocker_list,
    cmd_obligation_add,
    cmd_obligation_list,
    cmd_project_analyze,
    cmd_proof_retrieve,
    cmd_search,
    cmd_snapshot,
    cmd_status,
    cmd_theorem_add,
    cmd_theorem_list,
    cmd_theorem_show,
)

ROOT_ENV_VAR = "PROOF_ROOT"
FALLBACK_ROOT = Path("/Users/zhdeng/Proof CLI ")


@dataclass(frozen=True)
class ResolvedRoot:
    path: Path
    source: str


@dataclass(frozen=True)
class MutationContext:
    root: ResolvedRoot
    mutation_name: str


@dataclass(frozen=True)
class CommandReadiness:
    proof_path: str | None
    proof_codex_path: str | None
    running_entrypoint: str


app = typer.Typer(
    add_completion=False,
    help="Guided Codex-facing Proof CLI wrapper",
    invoke_without_command=True,
    no_args_is_help=False,
)
theorem_app = typer.Typer(help="Theorem discovery and guided theorem actions")
obligation_app = typer.Typer(help="Obligation discovery")
blocker_app = typer.Typer(help="Blocker discovery")
project_app = typer.Typer(help="Project diagnostics")
new_app = typer.Typer(help="Guided creation entry points")

app.add_typer(theorem_app, name="theorem")
app.add_typer(obligation_app, name="obligation")
app.add_typer(blocker_app, name="blocker")
app.add_typer(project_app, name="project")
app.add_typer(new_app, name="new")


def resolve_root(raw_root: str | None = None) -> ResolvedRoot:
    if raw_root:
        return ResolvedRoot(Path(raw_root).expanduser().resolve(), "explicit --root")

    env_root = os.getenv(ROOT_ENV_VAR)
    if env_root:
        return ResolvedRoot(Path(env_root).expanduser().resolve(), f"${ROOT_ENV_VAR}")

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".proof").exists():
            return ResolvedRoot(candidate, "workspace discovery")

    for candidate in (cwd, *cwd.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "proof_cli").exists():
            return ResolvedRoot(candidate, "repo discovery")

    if FALLBACK_ROOT.exists():
        return ResolvedRoot(FALLBACK_ROOT.resolve(), "global Proof CLI fallback")

    return ResolvedRoot(cwd, "current working directory")


def _root(path: str | None = None) -> Path:
    return resolve_root(path).path


def _looks_like_workspace(path: Path) -> bool:
    return (path / ".proof").exists()


def _mutation_context(path: str | None, mutation_name: str) -> MutationContext | str:
    root = resolve_root(path)
    if root.source == "global Proof CLI fallback" or (root.source == "current working directory" and not _looks_like_workspace(root.path)):
        return "\n".join(
            [
                f"Mutation: {mutation_name}",
                f"Selected root: {root.path}",
                f"Root source: {root.source}",
                "",
                "This command would mutate persisted proof state, but the selected root does not look like a Proof workspace.",
                "Provide --root explicitly, set PROOF_ROOT, or run proof init first.",
            ]
        )
    return MutationContext(root=root, mutation_name=mutation_name)


def _render_missing_details(context: MutationContext, missing: list[str], usage: str) -> str:
    return "\n".join(
        [
            f"Mutation: {context.mutation_name}",
            f"Selected root: {context.root.path}",
            f"Root source: {context.root.source}",
            "Persisted proof state: not changed yet",
            "",
            f"Missing details: {', '.join(missing)}",
            f"Next step: {usage}",
        ]
    )


def _render_mutation_result(context: MutationContext, payload: str) -> str:
    return "\n".join(
        [
            f"Mutation: {context.mutation_name}",
            f"Selected root: {context.root.path}",
            f"Root source: {context.root.source}",
            "Persisted proof state: changed",
            "",
            "Result:",
            payload,
        ]
    )


def detect_command_readiness() -> CommandReadiness:
    return CommandReadiness(
        proof_path=shutil.which("proof"),
        proof_codex_path=shutil.which("proof-codex"),
        running_entrypoint=Path(sys.argv[0]).name or "python",
    )


def _readiness_problems(readiness: CommandReadiness) -> list[str]:
    problems: list[str] = []
    if readiness.proof_path is None:
        problems.append("`proof` is not available on PATH.")
    if readiness.proof_codex_path is None:
        problems.append("`proof-codex` is not available on PATH.")
    return problems


def _render_readiness_report() -> str:
    readiness = detect_command_readiness()
    problems = _readiness_problems(readiness)
    lines = [
        "Proof Codex Diagnostics",
        f"Running entrypoint: {readiness.running_entrypoint}",
        f"proof: {readiness.proof_path or 'missing'}",
        f"proof-codex: {readiness.proof_codex_path or 'missing'}",
        "Canonical skill: ~/.codex/skills/proof/SKILL.md",
        "Project-local skills: debugging and development helpers only",
    ]
    if not problems:
        lines.extend(["", "Status: ready", "Command entrypoints are available."])
        return "\n".join(lines)

    lines.extend(
        [
            "",
            "Status: degraded",
            *problems,
            "",
            "Next steps:",
            '  1. From the repo root, run: python -m pip install -e ".[dev]"',
            "  2. Re-check with: proof codex doctor",
            "  3. Prefer the global ~/.codex/skills/proof/ skill as the normal entry path.",
        ]
    )
    return "\n".join(lines)


def _catalog(root: ResolvedRoot) -> str:
    readiness = detect_command_readiness()
    readiness_status = "ready" if not _readiness_problems(readiness) else "degraded"
    return "\n".join(
        [
            "Proof Codex Surface",
            f"Selected root: {root.path}",
            f"Root source: {root.source}",
            f"Readiness: {readiness_status}",
            "",
            "Read-only commands:",
            "  proof codex status",
            "  proof codex theorem list",
            "  proof codex theorem show <theorem_id>",
            "  proof codex obligation list",
            "  proof codex blocker list",
            '  proof codex search "<query>"',
            '  proof codex retrieve "<query>"',
            '  proof codex project analyze --query "<query>"',
            "  proof codex doctor",
            "",
            "Mutation commands:",
            "  proof codex new theorem <theorem_id> <name> <statement>",
            "  proof codex theorem add <theorem_id> <name> <statement>",
            '  proof codex obligation add "<goal_statement>"',
            '  proof codex blocker add "<description>"',
            "  proof codex snapshot",
            "",
            "Notes:",
            "  - This wrapper keeps Proof CLI as the source of truth.",
            "  - Retrieval-first and local-state-first still apply.",
            "  - Mutation commands always show the selected root before or after state changes.",
            "  - The global ~/.codex/skills/proof/ skill is the canonical entry path.",
            "  - Project-local proof skills are for repository debugging and development work.",
        ]
    )


@app.callback()
def codex_callback(ctx: typer.Context, root: str = typer.Option("", "--root", help="Proof workspace root")) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(_catalog(resolve_root(root or None)))


@app.command("catalog")
def catalog(root: str = "") -> None:
    typer.echo(_catalog(resolve_root(root or None)))


@app.command("where")
def where(root: str = "") -> None:
    resolved = resolve_root(root or None)
    typer.echo(f"{resolved.path} ({resolved.source})")


@app.command("doctor")
def doctor() -> None:
    typer.echo(_render_readiness_report())


@app.command("init")
def init(root: str = "") -> None:
    selected_root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()
    payload = cmd_init(selected_root)
    typer.echo("\n".join([f"Initialization root: {selected_root}", "Persisted proof state: changed", "", payload]))


@app.command("status")
def status(root: str = "") -> None:
    typer.echo(cmd_status(_root(root or None)))


@app.command("search")
def search(query: str, root: str = "", limit: int = 10) -> None:
    typer.echo(cmd_search(query, _root(root or None), limit=limit))


@app.command("retrieve")
def retrieve(query: str, root: str = "", limit: int = 10) -> None:
    typer.echo(cmd_proof_retrieve(query, _root(root or None), limit=limit))


@app.command("analyze")
def analyze(root: str = "", query: str = "", limit: int = 5) -> None:
    typer.echo(cmd_project_analyze(_root(root or None), query=query, limit=limit))


@project_app.command("analyze")
def project_analyze(root: str = "", query: str = "", limit: int = 5) -> None:
    typer.echo(cmd_project_analyze(_root(root or None), query=query, limit=limit))


@theorem_app.command("list")
def theorem_list(root: str = "") -> None:
    typer.echo(cmd_theorem_list(_root(root or None)))


@theorem_app.command("show")
def theorem_show(theorem_id: str, root: str = "") -> None:
    typer.echo(cmd_theorem_show(theorem_id, root=_root(root or None)))


@theorem_app.command("add")
def theorem_add(
    theorem_id: str | None = typer.Argument(None),
    name: str | None = typer.Argument(None),
    statement: str | None = typer.Argument(None),
    root: str = "",
    kind: str = "theorem",
    assumption: list[str] = typer.Option(None, "--assumption"),
    export: list[str] = typer.Option(None, "--export"),
    notes: str = "",
) -> None:
    context = _mutation_context(root or None, "theorem add")
    if isinstance(context, str):
        typer.echo(context)
        return
    missing = [label for label, value in [("theorem_id", theorem_id), ("name", name), ("statement", statement)] if not value]
    if missing:
        typer.echo(
            _render_missing_details(
                context,
                missing,
                'proof codex theorem add <theorem_id> "<name>" "<statement>" [--assumption ...] [--export ...] [--notes "..."]',
            )
        )
        return
    payload = cmd_theorem_add(
        theorem_id=theorem_id or "",
        name=name or "",
        statement=statement or "",
        root=context.root.path,
        kind=kind,
        assumption=assumption or None,
        export=export or None,
        notes=notes,
    )
    typer.echo(_render_mutation_result(context, payload))


@new_app.command("theorem")
def new_theorem(
    theorem_id: str | None = typer.Argument(None),
    name: str | None = typer.Argument(None),
    statement: str | None = typer.Argument(None),
    root: str = "",
    kind: str = "theorem",
    assumption: list[str] = typer.Option(None, "--assumption"),
    export: list[str] = typer.Option(None, "--export"),
    notes: str = "",
) -> None:
    context = _mutation_context(root or None, "new theorem")
    if isinstance(context, str):
        typer.echo(context)
        return
    missing = [label for label, value in [("theorem_id", theorem_id), ("name", name), ("statement", statement)] if not value]
    if missing:
        typer.echo(
            _render_missing_details(
                context,
                missing,
                'proof codex new theorem <theorem_id> "<name>" "<statement>" [--assumption ...] [--export ...] [--notes "..."]',
            )
        )
        return
    payload = cmd_theorem_add(
        theorem_id=theorem_id or "",
        name=name or "",
        statement=statement or "",
        root=context.root.path,
        kind=kind,
        assumption=assumption or None,
        export=export or None,
        notes=notes,
    )
    typer.echo(_render_mutation_result(context, payload))


@obligation_app.command("list")
def obligation_list(root: str = "") -> None:
    typer.echo(cmd_obligation_list(_root(root or None)))


@obligation_app.command("add")
def obligation_add(
    goal_statement: str | None = typer.Argument(None),
    root: str = "",
    source_step_id: str = "",
    required_for: str = "",
) -> None:
    context = _mutation_context(root or None, "obligation add")
    if isinstance(context, str):
        typer.echo(context)
        return
    if not goal_statement:
        typer.echo(
            _render_missing_details(
                context,
                ["goal_statement"],
                'proof codex obligation add "<goal_statement>" [--required-for <theorem_id>] [--source-step-id <step_id>]',
            )
        )
        return
    payload = cmd_obligation_add(
        goal_statement=goal_statement,
        root=context.root.path,
        source_step_id=source_step_id or None,
        required_for=required_for or None,
    )
    typer.echo(_render_mutation_result(context, payload))


@blocker_app.command("list")
def blocker_list(root: str = "") -> None:
    typer.echo(cmd_blocker_list(_root(root or None)))


@blocker_app.command("add")
def blocker_add(
    description: str | None = typer.Argument(None),
    root: str = "",
    scope: str = "global",
    failure_type: str = "unknown",
) -> None:
    context = _mutation_context(root or None, "blocker add")
    if isinstance(context, str):
        typer.echo(context)
        return
    if not description:
        typer.echo(
            _render_missing_details(
                context,
                ["description"],
                'proof codex blocker add "<description>" [--scope <scope>] [--failure-type <type>]',
            )
        )
        return
    payload = cmd_blocker_add(
        description=description,
        root=context.root.path,
        scope=scope,
        failure_type=failure_type,
    )
    typer.echo(_render_mutation_result(context, payload))


@app.command("snapshot")
def snapshot(root: str = "", note: str = "") -> None:
    context = _mutation_context(root or None, "snapshot")
    if isinstance(context, str):
        typer.echo(context)
        return
    payload = cmd_snapshot(context.root.path, handoff_note=note)
    typer.echo(_render_mutation_result(context, payload))
