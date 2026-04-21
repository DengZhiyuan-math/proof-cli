from __future__ import annotations

from pathlib import Path

import typer

from .commands import (
    cmd_blocker_add,
    cmd_blocker_list,
    cmd_export,
    cmd_goal_list,
    cmd_goal_open,
    cmd_goal_set,
    cmd_history,
    cmd_init,
    cmd_obligation_add,
    cmd_obligation_list,
    cmd_snapshot,
    cmd_status,
    cmd_theorem_add,
    cmd_theorem_apply,
    cmd_theorem_list,
    cmd_theorem_show,
)

app = typer.Typer(add_completion=False, help="Mathematical Proof CLI")
goal_app = typer.Typer(help="Goal operations")
theorem_app = typer.Typer(help="Theorem registry")
obligation_app = typer.Typer(help="Obligation queue")
blocker_app = typer.Typer(help="Blocker tracking")


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


app.add_typer(goal_app, name="goal")
app.add_typer(theorem_app, name="theorem")
app.add_typer(obligation_app, name="obligation")
app.add_typer(blocker_app, name="blocker")


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


@theorem_app.command("list")
def theorem_list(root: str = ".") -> None:
    typer.echo(cmd_theorem_list(_root(root)))


@theorem_app.command("apply")
def theorem_apply(theorem_id: str, root: str = ".") -> None:
    typer.echo(cmd_theorem_apply(theorem_id, root=_root(root)))


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


@blocker_app.command("add")
def blocker_add(description: str, root: str = ".", scope: str = "global", failure_type: str = "unknown") -> None:
    typer.echo(cmd_blocker_add(description, root=_root(root), scope=scope, failure_type=failure_type))


@blocker_app.command("list")
def blocker_list(root: str = ".") -> None:
    typer.echo(cmd_blocker_list(_root(root)))

