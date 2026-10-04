"""Where the other packages of the family plug into the `proof` CLI (ADR-0018).

proof-cli is the base: the project state, the proof map and the agents' command surface. The web
app (proof-web) adds its own commands, `proof home`, `proof map open` and `proof map serve`, by
publishing a `register(app, map_app, review_app)` function under the entry-point group
`proof_cli.commands`; it also tells the CLI where a project's page is (`provide_project_url`), so
a refused Human Review decision can say where to make it. Without proof-web installed, those
commands exist as fallbacks that say which package to install, and no URL is known.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Callable

import typer

from .envelope import dump_envelope, error_envelope

ENTRY_POINT_GROUP = "proof_cli.commands"
WEB_PACKAGE = "proof-web"

_project_url: Callable[..., str] | None = None


def provide_project_url(fn: Callable[..., str]) -> None:
    """Set the function that answers `project_url(store, node_id)` — proof-web's, when it is installed."""
    global _project_url
    _project_url = fn


def project_url(store, node_id: str | None = None) -> str | None:
    """The project's proof map page (at a node, if given), or None when no web app is installed."""
    return _project_url(store, node_id) if _project_url is not None else None


def load_commands(app: typer.Typer, map_app: typer.Typer, review_app: typer.Typer) -> None:
    """Give every installed plugin the CLI's groups to add its commands to."""
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        entry.load()(app, map_app, review_app)


def command_names(typer_app: typer.Typer) -> set[str]:
    return {command.name or command.callback.__name__ for command in typer_app.registered_commands}


def drop_fallbacks(*typer_apps: typer.Typer) -> None:
    """Remove the fallback commands below, so a plugin registering late (a test, `python -m proof_web.cli`) replaces them."""
    for typer_app in typer_apps:
        typer_app.registered_commands[:] = [c for c in typer_app.registered_commands if not getattr(c.callback, "proof_cli_fallback", False)]


def install_web_fallbacks(app: typer.Typer, map_app: typer.Typer, *, panel: str) -> None:
    """`proof home`, `proof map open` and `proof map serve` when proof-web isn't installed: say so, and fail."""

    def fallback(words: str, help_text: str):
        def command(
            ctx: typer.Context,
            json_output: bool = typer.Option(False, "--json"),
        ) -> None:
            command_name = words.replace(" ", ".")
            message = f"`proof {words}` is the proof map web app, which is the {WEB_PACKAGE} package: pip install {WEB_PACKAGE}"
            typer.echo(dump_envelope(error_envelope(command_name, "WEB_APP_NOT_INSTALLED", message)) if json_output else f"Error: {message}")
            raise typer.Exit(code=1)

        command.proof_cli_fallback = True  # type: ignore[attr-defined]
        command.__doc__ = help_text
        return command

    settings = {"allow_extra_args": True, "ignore_unknown_options": True}
    app.command("home", rich_help_panel=panel, context_settings=settings)(
        fallback("home", f"Open the Home: your proof projects (needs the {WEB_PACKAGE} package)."))
    map_app.command("open", context_settings=settings)(
        fallback("map open", f"Open this project's proof map page (needs the {WEB_PACKAGE} package)."))
    map_app.command("serve", context_settings=settings)(
        fallback("map serve", f"Run this project's proof map page in the foreground (needs the {WEB_PACKAGE} package)."))
