"""The agent-facing CLI contract (story 42, ADR-0006, issue #34).

Under `--json` every invocation writes exactly one envelope to stdout, a
failure included: a usage error, a missing project, or an unexpected
exception. A read never creates a project. Human-readable output prints once.
"""

import ast
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import errors
from proof_cli.cli import READ_ONLY_COMMANDS, app

runner = CliRunner()
SRC = Path(__file__).resolve().parents[1] / "src" / "proof_cli"


def _envelope(result) -> dict:
    """The one JSON document on stdout, nothing else."""
    return json.loads(result.stdout)


def _project(tmp_path: Path) -> Path:
    runner.invoke(app, ["node", "create", "C1", "claim", "stmt", "--root", str(tmp_path)])
    return tmp_path


# -- one envelope, whatever goes wrong -----------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["node", "show", "--json"],  # missing argument
        ["node", "show", "C1", "--bogus", "--json"],  # unknown option
        ["node", "nope", "--json"],  # unknown command
        ["init", "--json"],  # a command with no --json of its own
    ],
    ids=["missing-argument", "unknown-option", "unknown-command", "no-json-option"],
)
def test_a_usage_error_under_json_is_one_envelope(tmp_path: Path, args):
    result = runner.invoke(app, [*args, "--root", str(_project(tmp_path))])

    assert result.exit_code == 2
    envelope = _envelope(result)
    assert envelope["ok"] is False and envelope["error"]["code"] == "USAGE_ERROR"
    assert envelope["error"]["message"]


def test_an_unexpected_exception_under_json_is_one_envelope_not_a_traceback(tmp_path: Path, monkeypatch):
    root = _project(tmp_path)

    def broken(*_args, **_kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("proof_cli.cli.get_workflow_state", broken)
    result = runner.invoke(app, ["node", "show", "C1", "--root", str(root), "--json"])

    assert result.exit_code == 1
    envelope = _envelope(result)
    assert (envelope["command"], envelope["error"]["code"]) == ("node.show", "INTERNAL_ERROR")
    assert "disk on fire" in envelope["error"]["message"]
    assert "Traceback" not in result.output


def test_without_json_a_usage_error_keeps_clicks_usage_message(tmp_path: Path):
    result = runner.invoke(app, ["node", "show", "--root", str(tmp_path)])
    assert result.exit_code == 2
    assert "Missing argument" in result.output


# -- a read never creates a project ---------------------------------------------------


@pytest.mark.parametrize("json_output", [True, False])
def test_a_read_on_a_mistyped_root_fails_and_creates_nothing(tmp_path: Path, json_output: bool):
    typo = tmp_path / "typo"
    result = runner.invoke(app, ["node", "show", "C1", "--root", str(typo), *(["--json"] if json_output else [])])

    assert result.exit_code == 1
    assert not typo.exists()
    if json_output:
        assert _envelope(result)["error"]["code"] == "PROJECT_NOT_FOUND"
    else:
        assert "no proof project" in result.output and "proof init" in result.output


def test_no_read_only_command_creates_a_project(tmp_path: Path):
    """Every command listed read-only, run against a folder with no project, leaves it without one."""
    import click
    import typer

    tree = typer.main.get_command(app)
    for path in sorted(READ_ONLY_COMMANDS):
        command = tree
        for name in path.split():
            command = command.commands[name]
        root = tmp_path / path.replace(" ", "_")
        args = [*path.split(), *("X" for p in command.params if isinstance(p, click.Argument) and p.required)]
        if any("--root" in p.opts for p in command.params if isinstance(p, click.Option)):
            args += ["--root", str(root)]
        else:
            continue  # a read that takes no root (codex catalog, …) touches no project
        runner.invoke(app, args)
        assert not (root / ".proof").exists(), path


def test_the_read_only_list_names_real_commands():
    import click
    import typer

    tree = typer.main.get_command(app)
    for path in READ_ONLY_COMMANDS:
        command = tree
        for name in path.split():
            assert isinstance(command, click.Group) and name in command.commands, path
            command = command.commands[name]


def test_a_write_still_starts_a_project(tmp_path: Path):
    result = runner.invoke(app, ["node", "create", "C1", "claim", "stmt", "--root", str(tmp_path / "fresh"), "--json"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "fresh" / ".proof").is_dir()


# -- human-readable output prints once ------------------------------------------------


@pytest.mark.parametrize(
    "args, marker",
    [(["node", "show", "C1"], "Proof Map Node"), (["node", "list"], "C1"), (["frontier"], "C1"), (["challenge", "list"], "No challenges")],
)
def test_human_readable_output_prints_once(tmp_path: Path, args, marker):
    root = _project(tmp_path)
    result = runner.invoke(app, [*args, "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert result.stdout.count(marker) == 1, result.stdout


# -- error codes are written down in one place ----------------------------------------


def _raised_codes() -> dict[str, str]:
    """Every literal error code the source passes to ProofMapError, RequestError or error_envelope."""
    found: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ("ProofMapError", "RequestError", "error_envelope"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", arg.value):
                    found[arg.value] = f"{path.name}:{node.lineno}"
                    break
    return found


def test_every_error_code_the_code_raises_is_registered():
    unregistered = {code: where for code, where in _raised_codes().items() if code not in errors.ERROR_CODES}
    assert not unregistered, unregistered


def test_the_adr_points_at_the_registry():
    adr = (SRC.parents[1] / "docs" / "adr" / "0006-agent-execution-protocol.md").read_text()
    assert "proof_cli/errors.py" in adr


def test_no_module_defines_a_function_twice():
    """A second top-level definition silently replaces the first, which then invites fixes in the wrong place (#34)."""
    import collections

    for path in SRC.rglob("*.py"):
        names = collections.Counter(
            node.name for node in ast.parse(path.read_text()).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        assert not [name for name, count in names.items() if count > 1], path.name
