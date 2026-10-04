"""The web app's commands on the `proof` CLI: `proof home`, `proof map open`, `proof map serve`.

proof-cli finds `register` through the entry-point group `proof_cli.commands` (proof_cli.plugins)
when this package is installed, and the commands replace the CLI's fallbacks. `main` below is
the same CLI with these commands whether or not the entry point is installed; the Home and
`map open` start their background processes through it. From a checkout nothing is installed
from, the four packages' source folders must be on `PYTHONPATH` first:

    export PYTHONPATH=src:packages/proof-agents/src:packages/latex-agent/src:packages/proof-web/src
    python -m proof_web.cli home [--foreground]
    python -m proof_web.cli map open [<node-id>] --root <project>
"""

from __future__ import annotations

import subprocess
import sys
import time
import webbrowser

import typer


def _wait_until(ready, *, seconds: float = 6.0) -> bool:
    for _ in range(int(seconds / 0.1)):
        if ready():
            return True
        time.sleep(0.1)
    return ready()


def _running_review_app(store) -> bool:
    """Whether this project's proof map page already answers on its origin."""
    from .home import project_answering

    return project_answering(store)


def _ensure_home() -> bool:
    """A Home answering on its port: the one already running, or one started in the background."""
    from .home import home_answering

    if home_answering():
        return True
    subprocess.Popen(
        [sys.executable, "-m", "proof_web.cli", "home", "--foreground"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return _wait_until(home_answering)


def register(app: typer.Typer, map_app: typer.Typer, review_app: typer.Typer) -> None:
    """Add the web app's commands to the `proof` CLI's groups (once), and tell it where a project's page is."""
    from proof_cli import plugins
    from proof_cli.cli import PROOF_MAP_PANEL, ROOT_OPTION, _root, get_store
    from proof_cli.envelope import dump_envelope, success_envelope
    from proof_cli.projects import register_project

    from .home import HomeServer, ask_home_to_open, home_origin
    from .server import ReviewServer, project_url

    plugins.drop_fallbacks(app, map_app)
    if "home" in plugins.command_names(app):
        return
    plugins.provide_project_url(project_url)

    @app.command(rich_help_panel=PROOF_MAP_PANEL)
    def home(
        foreground: bool = typer.Option(False, "--foreground", help="Run the Home in this terminal (Ctrl-C stops it) instead of opening it"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Open the Home: your proof projects, each opening in its own proof map page (ADR-0017)."""
        if foreground:
            try:
                server = HomeServer()
            except OSError as exc:
                typer.echo(f"Error: can't bind the Home's port ({exc}); is it already running? Try `proof home`.")
                raise typer.Exit(code=1)
            typer.echo(f"Home: {server.url}  (Ctrl-C to stop)")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return
        if not _ensure_home():
            typer.echo("Error: the Home didn't start; run `proof home --foreground` to see why.")
            raise typer.Exit(code=1)
        url = home_origin()
        typer.echo(dump_envelope(success_envelope("home", {"url": url})) if json_output else url)
        webbrowser.open(url)

    @map_app.command("serve")
    def review_serve(root: str = ROOT_OPTION) -> None:
        """Run this project's proof map page on its own localhost origin — the only place Human Review decisions are made (ADR-0010).

        Runs in the foreground until interrupted. Bound to 127.0.0.1. Decisions
        are recorded as this process's git identity and committed with their
        snapshots.
        """
        store = get_store(_root(root))
        register_project(store.root)
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
        """Open this project's proof map page (starting it in the background if needed), optionally at a node.

        The page is served by the Home (`proof home`), started if need be, so it lists this
        project and the page links back to it. Without a Home, the page runs on its own.
        """
        store = get_store(_root(root))
        register_project(store.root, opened=True)
        if not _running_review_app(store):
            if _ensure_home():
                try:
                    ask_home_to_open(store.root)
                except (OSError, ValueError, KeyError):
                    pass  # the Home couldn't serve it: the page runs on its own, below
            if not _running_review_app(store):
                subprocess.Popen(
                    [sys.executable, "-m", "proof_web.cli", "map", "serve", "--root", str(_root(root))],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                _wait_until(lambda: _running_review_app(store), seconds=5)
        url = project_url(store, node_id or None)
        typer.echo(dump_envelope(success_envelope("map.open", {"url": url, "node_id": node_id or None})) if json_output else url)
        webbrowser.open(url)

    # the page's commands before it was the map's home (ADR-0010): kept, out of sight
    review_app.command("serve", hidden=True)(review_serve)
    review_app.command("open", hidden=True)(review_open)


def main() -> None:
    """The whole `proof` CLI with the web app's commands, whether or not this package is installed."""
    from proof_cli.cli import app, map_app, review_app

    register(app, map_app, review_app)
    app()


if __name__ == "__main__":
    main()
