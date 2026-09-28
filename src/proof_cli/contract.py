"""The agent-facing CLI contract every entry point shares (ADR-0006, issue #34).

`proof` and `proof-codex` both build their root command from `ProofGroup`:

- Under `--json`, exactly one envelope on stdout whatever happens: a usage
  error (USAGE_ERROR, exit 2), a missing project (PROJECT_NOT_FOUND) or an
  unexpected exception (INTERNAL_ERROR, never a traceback), exit 1. `--help`
  is the one exception: it prints help.
- Only a command in STARTS_A_PROJECT may create a project. Any other one,
  pointed at a folder with no project, fails with PROJECT_NOT_FOUND and
  creates nothing. A command left off the list fails safe: it refuses a
  missing project rather than silently making one of a mistyped --root.
"""

from __future__ import annotations

import sys
from contextlib import nullcontext

import click
import typer
from typer.core import TyperGroup

from .envelope import dump_envelope, error_envelope
from .storage import ProjectNotFoundError, read_only

# Commands that may start a project in an empty folder, by their path from `proof`:
# the ones that create content. Everything else needs an existing project.
STARTS_A_PROJECT = frozenset(
    {
        "init",
        "codex init",
        "node create",
        "theorem add",
        "codex theorem add",
        "codex new theorem",
        "obligation add",
        "codex obligation add",
        "blocker add",
        "codex blocker add",
        "goal set",
        "reference import",
        "memory add",
        "exchange import",
        "comment add",
        "branch create",
        "handoff create",
        "asset publish",
        "pack install",
        "policy set",
    }
)


def command_path(group: click.Group, args: list[str], prog_name: str) -> list[str] | None:
    """The subcommand names `args` invoke, resolved the way click itself parses them
    (so `proof -- node list` and `proof node -- list` resolve too), or None if they don't parse."""
    path: list[str] = []
    try:
        ctx = group.make_context(prog_name, list(args), resilient_parsing=True)
        command: click.Command = group
        while isinstance(command, click.Group):
            remaining = [*ctx._protected_args, *ctx.args]
            if not remaining:
                break
            name, sub, rest = command.resolve_command(ctx, remaining)
            if sub is None:
                return None
            path.append(name)
            ctx = sub.make_context(name, rest, parent=ctx, resilient_parsing=True)
            command = sub
    except click.ClickException:
        return None
    return path


class ProofGroup(TyperGroup):
    """A root command bound to the contract; `prefix` is its path from `proof` ("codex" for `proof-codex`)."""

    prefix: tuple[str, ...] = ()

    def main(self, args=None, prog_name=None, complete_var=None, standalone_mode=True, **extra):
        argv = list(args) if args is not None else sys.argv[1:]
        path = command_path(self, argv, prog_name or "proof")
        full_path = [*self.prefix, *(path or [])]
        json_output = "--json" in argv
        command = ".".join(full_path) or "proof"
        # an invocation that doesn't parse gets its usage error below, and creates nothing either way
        may_start = path is not None and " ".join(full_path) in STARTS_A_PROJECT
        try:
            with nullcontext() if may_start else read_only():
                outcome = super().main(argv, prog_name, complete_var, standalone_mode=False, **extra)
            code = outcome if isinstance(outcome, int) else 0
        except click.exceptions.Exit as exc:
            code = exc.exit_code
        except click.ClickException as exc:
            if not json_output:
                if not standalone_mode:
                    raise
                from typer import rich_utils

                rich_utils.rich_format_error(exc)
                sys.exit(exc.exit_code)
            typer.echo(dump_envelope(error_envelope(command, "USAGE_ERROR", exc.format_message())))
            code = exc.exit_code
        except click.Abort:
            if json_output:
                typer.echo(dump_envelope(error_envelope(command, "INTERNAL_ERROR", "aborted")))
            else:
                typer.echo("Aborted!", err=True)
            code = 1
        except ProjectNotFoundError as exc:
            if json_output:
                typer.echo(dump_envelope(error_envelope(command, exc.code, str(exc), details={"root": str(exc.root)})))
            else:
                typer.echo(f"Error: {exc}")
            code = 1
        except Exception as exc:  # noqa: BLE001 — the contract: an envelope, not a traceback
            if not json_output:
                raise
            typer.echo(dump_envelope(error_envelope(command, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")))
            code = 1
        if standalone_mode:
            sys.exit(code)
        return code


class CodexGroup(ProofGroup):
    """`proof-codex`: the same contract, its commands named by their path under `proof codex`."""

    prefix = ("codex",)
