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

from _proofs import ensure_key_ideas
from typer.testing import CliRunner

from proof_cli import errors
from proof_cli.cli import app
from proof_cli.contract import STARTS_A_PROJECT

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


def _leaves(command, path=()):
    import click

    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            yield from _leaves(sub, (*path, name))
    else:
        yield path, command


def _placeholder_args(command) -> list[str]:
    """Something for every required argument and option: enough to reach the command's body."""
    import click

    args = ["X" for p in command.params if isinstance(p, click.Argument) and p.required]
    for option in command.params:
        if isinstance(option, click.Option) and option.required:
            args += [option.opts[0], "X"]
    return args


def test_only_the_commands_that_start_a_project_create_one(tmp_path: Path):
    """The whole command tree, not a list checked against itself: every command but the few that
    create content, pointed at a folder with no project, leaves it without one (#34)."""
    import click
    import typer

    walked = 0
    crashed = []
    for path, command in _leaves(typer.main.get_command(app)):
        full = " ".join(path)
        if full in STARTS_A_PROJECT:
            continue
        if not any("--root" in p.opts for p in command.params if isinstance(p, click.Option)):
            continue  # takes no root: touches no project
        root = tmp_path / full.replace(" ", "_") / "missing"
        result = runner.invoke(app, [*path, *_placeholder_args(command), "--root", str(root)])
        walked += 1
        assert not root.exists(), full
        if not isinstance(result.exception, (type(None), *EXPECTED_WALK_FAILURES)):
            crashed.append((full, repr(result.exception)))
    assert walked > 80
    assert not crashed, crashed  # e.g. a command function cli.py never imported (#44)


# What the walk may end in: a usage error or a missing project (both exit through
# SystemExit), or the placeholder "X" rejected as input (a ValueError, pydantic's
# ValidationError included). Anything else -- a NameError above all -- is a bug.
EXPECTED_WALK_FAILURES = (SystemExit, ValueError)


def test_the_starting_list_names_real_commands():
    import typer

    known = {" ".join(path) for path, _ in _leaves(typer.main.get_command(app))}
    assert STARTS_A_PROJECT <= known, STARTS_A_PROJECT - known


@pytest.mark.parametrize(
    "args",
    [["--", "node", "list"], ["node", "--", "list"], ["node", "list", "--"]],
    ids=["before-group", "inside-group", "after-command"],
)
def test_a_double_dash_cannot_slip_a_read_past_the_check(tmp_path: Path, args):
    """PR #64 audit: `proof -- node list` is a valid click invocation of `node list`."""
    missing = tmp_path / "missing"
    result = runner.invoke(app, [*args, "--root", str(missing), "--json"])
    assert not missing.exists()
    assert result.exit_code != 0


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


_CODE = re.compile(r"[A-Z][A-Z0-9_]+")
# the calls whose first code-shaped argument is a refusal's code: the service's and the page's errors, the studio's
# refusals and its `_err(status, CODE, message)`, the hub's `_error(status, CODE, message)` and NoStudio
_REFUSALS = ("ProofMapError", "RequestError", "error_envelope", "_Refused", "_err", "_error", "NoStudio")
# the calls whose first code-shaped argument is a notice's code: errors.notice(CODE, message, …)
_NOTICES = ("notice",)


def _code_of(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) and _CODE.fullmatch(node.value) else None


def _scan_codes(source: str, where: str) -> tuple[dict[str, str], dict[str, str]]:
    """(refusals, notices) in one module's source: every literal code it refuses with — passed to ProofMapError,
    RequestError, error_envelope or the studio's _Refused, or answered as `{"error": CODE}`, `{"error": …, "code": CODE}`
    or `{"error": {"code": CODE}}` — and every literal code it tells as a notice: a `{"code": CODE, …}` with no `error`."""
    refusals: dict[str, str] = {}
    notices: dict[str, str] = {}
    tree = ast.parse(source)
    inside_error = set()  # dicts that are an `error` value: {"error": {"code": CODE, …}} is a refusal
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "error" and isinstance(value, ast.Dict):
                    inside_error.add(id(value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            fields = {key.value: value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant)}
            refusal = "error" in fields or id(node) in inside_error
            for name in ("error", "code"):
                code = _code_of(fields.get(name))
                if code:
                    (refusals if refusal else notices)[code] = f"{where}:{node.lineno}"
            continue
        name = (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) if isinstance(node, ast.Call) else None
        if name in _REFUSALS or name in _NOTICES:
            code = next((code for code in map(_code_of, node.args) if code), None)
            if code:
                (refusals if name in _REFUSALS else notices)[code] = f"{where}:{node.lineno}"
    return refusals, notices


def _family_sources() -> list[Path]:
    """The code the registry covers (ADR-0018): this repository's core and latex-agent, and the other two packages
    of the family when they are installed beside it (proof-agents, proof-web); each raises codes of this registry."""
    import importlib.util

    folders = [SRC, SRC.parents[1] / "packages" / "latex-agent" / "src" / "latex_agent"]
    for name in ("proof_agents", "proof_web"):
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.origin:
            folders.append(Path(spec.origin).parent)
    return [folder for folder in folders if folder.is_dir()]


def _codes() -> tuple[dict[str, str], dict[str, str]]:
    refusals: dict[str, str] = {}
    notices: dict[str, str] = {}
    for path in (path for folder in _family_sources() for path in folder.rglob("*.py")):
        found_refusals, found_notices = _scan_codes(path.read_text(), path.name)
        refusals.update(found_refusals)
        notices.update(found_notices)
    return refusals, notices


def _raised_codes() -> dict[str, str]:
    return _codes()[0]


def test_every_error_code_the_code_raises_is_registered():
    """A refusal's code is an error code (ERROR_CODES) — being a notice's is not enough — and a notice's is a notice code."""
    refusals, notices = _codes()
    unregistered = {code: where for code, where in refusals.items() if code not in errors.ERROR_CODES}
    assert not unregistered, unregistered
    not_notices = {code: where for code, where in notices.items() if code not in errors.NOTICE_CODES}
    assert not not_notices, not_notices


def test_error_codes_and_notice_codes_do_not_overlap():
    assert errors.ERROR_CODES.keys().isdisjoint(errors.NOTICE_CODES)


def test_the_scanner_sees_each_kind_of_refusal_and_notice():
    """The scan bites: each way of refusing or noticing is found, and a notice code is not a refusal's."""
    refusals, notices = _scan_codes("""
raise ProofMapError("PLANTED_A", "x")
raise _Refused("PLANTED_B", "x")
answer = {"error": "a message", "code": "PLANTED_C"}
old = {"error": "PLANTED_D", "message": "x"}
envelope = {"ok": False, "error": {"code": "PLANTED_E", "message": "x"}}
notice = [{"code": "PLANTED_F", "message": "x"}]
answer = _err(404, "PLANTED_G", "x")
hub = _error(HTTPStatus.NOT_FOUND, "PLANTED_H", "x")
told = errors.notice("PLANTED_I", "x", output_bytes=1)
""", "planted")
    assert set(refusals) == {"PLANTED_A", "PLANTED_B", "PLANTED_C", "PLANTED_D", "PLANTED_E", "PLANTED_G", "PLANTED_H"}
    assert set(notices) == {"PLANTED_F", "PLANTED_I"}
    # the studio's own refusals are seen, and a notice code used as a refusal is not let through
    studio = _scan_codes((SRC.parents[1] / "packages" / "latex-agent" / "src" / "latex_agent" / "server.py").read_text(), "server.py")[0]
    assert {"NOT_A_COMPUTATION", "INVALID_LINE", "OPEN_FAILED", "NOT_A_NODE_FILE", "STUDIO_CLOSED", "NO_SUCH_JOB"} <= set(studio)
    # the agent manager's answers carry registered codes too (PR #148)
    agent = _scan_codes((SRC.parents[1] / "packages" / "latex-agent" / "src" / "latex_agent" / "agent.py").read_text(), "agent.py")[0]
    assert {"STUDIO_CLOSED", "AGENT_UNKNOWN_PROVIDER", "AGENT_UNAVAILABLE", "AGENT_INVALID_OPTION", "AGENT_BUSY", "TURN_CALLED_OFF"} <= set(agent)
    misused, _ = _scan_codes('{"error": "big", "code": "SNAPSHOT_LARGE_OUTPUT"}', "planted")
    assert "SNAPSHOT_LARGE_OUTPUT" in misused and "SNAPSHOT_LARGE_OUTPUT" not in errors.ERROR_CODES


def test_the_agent_runs_refusals_are_registered_codes():
    """PR #148 seventh review: the run's answers are codes an agent or the page may branch on (ADR-0006)."""
    raised = _raised_codes()
    pytest.importorskip("proof_agents")  # the run is proof-agents' (ADR-0018): its codes are seen when it is installed beside this checkout
    for code in ("RUN_ACTIVE", "RUN_SETTLING", "NO_RUN", "REDIRECT_EMPTY", "RUN_REFUSED", "RELEASE_FAILED", "AGENT_BUSY", "TURN_CALLED_OFF"):
        assert code in errors.ERROR_CODES, code
        assert code in raised or code == "RUN_REFUSED", code  # RUN_REFUSED is the fallback the map's route passes on


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


def test_no_module_uses_an_undefined_name():
    """An unimported name is a NameError waiting for its first call: `proof pack` sat broken for months (#44)."""
    import shutil
    import subprocess
    import sys

    ruff = shutil.which("ruff")
    command = [ruff] if ruff else [sys.executable, "-m", "ruff"]
    try:
        result = subprocess.run([*command, "check", "--select", "F821", "--no-cache", str(SRC)], capture_output=True, text=True)
    except FileNotFoundError:
        pytest.skip("ruff is not installed (pip install -e '.[dev]')")
    if result.returncode != 0 and "No module named ruff" in result.stderr:
        pytest.skip("ruff is not installed (pip install -e '.[dev]')")
    assert result.returncode == 0, result.stdout + result.stderr


# -- one agent entry: `proof`, rooted by PROOF_ROOT (ADR-0011, #67) ---------------------

REPO = SRC.parents[1]


def test_proof_codex_and_the_mcp_plugin_are_gone():
    assert "proof-codex" not in (REPO / "pyproject.toml").read_text()
    assert not (SRC / "codex_router.py").exists()
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "plugins/proof-routing"], cwd=REPO, capture_output=True, text=True)
    if tracked.returncode == 0:  # a stale local __pycache__ may linger; what matters is that nothing is shipped
        assert tracked.stdout.strip() == ""
    result = runner.invoke(app, ["codex", "status", "--json"])
    assert result.exit_code == 2 and _envelope(result)["error"]["code"] == "USAGE_ERROR"


def test_nothing_still_points_at_the_retired_entries():
    """Outside the archived plans and the ADRs' history, no tracked file names them: the
    repository's implementation and docs, not regression-test literals or local caches."""
    import subprocess

    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True)
    if listed.returncode != 0:
        pytest.skip("not a git checkout")
    retired = ("proof codex", "proof-codex", "codex_router", "proof-routing", "proof routing", "proof_mcp_server")
    this = Path(__file__).resolve()
    for rel in filter(None, listed.stdout.split("\0")):
        path = REPO / rel
        if rel.startswith((".planning/", "docs/adr/", "tests/")) or path == this or not path.is_file():
            continue
        text = path.read_text(errors="ignore").lower()
        assert not [name for name in retired if name in text], rel


def test_every_command_with_a_root_reads_proof_root():
    """The one root convention holds for every command, including ones added on other branches (PR #77 review)."""
    import click
    import typer

    for path, command in _leaves(typer.main.get_command(app)):
        for option in command.params:
            if isinstance(option, click.Option) and "--root" in option.opts:
                assert option.envvar == "PROOF_ROOT", " ".join(path)


def test_proof_root_roots_every_call_made_inside_a_node_folder(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    runner.invoke(app, ["node", "create", "C1", "claim", "stmt", "--root", str(project)])
    node_folder = project / "proofs" / "C1"
    monkeypatch.chdir(node_folder)
    monkeypatch.setenv("PROOF_ROOT", str(project))

    result = runner.invoke(app, ["node", "claim", "C1", "--assignee", "agent_a", "--json"])

    assert result.exit_code == 0, result.output
    assert _envelope(result)["data"]["claimant_id"] == "agent_a"
    assert not (node_folder / ".proof").exists()  # never a nested project


def test_an_explicit_root_wins_over_proof_root(tmp_path: Path, monkeypatch):
    other = tmp_path / "other"
    runner.invoke(app, ["node", "create", "X", "claim", "x", "--root", str(other)])
    monkeypatch.setenv("PROOF_ROOT", str(tmp_path / "elsewhere"))
    result = runner.invoke(app, ["node", "show", "X", "--root", str(other), "--json"])
    assert result.exit_code == 0 and _envelope(result)["data"]["id"] == "X"


def test_without_proof_root_the_current_folder_is_the_root(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PROOF_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["node", "create", "Y", "claim", "y"])
    assert (tmp_path / ".proof").is_dir()


def test_the_skills_node_workflow_runs_as_written(tmp_path: Path):
    """The agent skill's steps, with its identity flags, work in order (PR #77 review): an agent
    that claims a node must name itself the same way when it splits it or requests review."""
    skill = (REPO / ".agents" / "skills" / "proof-cli" / "SKILL.md").read_text()
    for flag in ("--assignee <name>", "--created-by <name>", "--requested-by <name>"):
        assert flag in skill, flag
    root = str(tmp_path)
    steps = [
        ["node", "create", "P", "claim", "a claim too large", "--root", root],
        ["node", "claim", "P", "--assignee", "agent_a", "--root", root],
        ["node", "split", "P", "--child", "P1=first half", "--created-by", "agent_a", "--root", root],
        ["node", "claim", "P1", "--assignee", "agent_a", "--root", root],
        ["node", "request-review", "P1", "--rationale", "one computation", "--requested-by", "agent_a", "--root", root],
    ]
    for args in steps:
        if args[:2] == ["node", "request-review"]:
            ensure_key_ideas(tmp_path, args[2])  # what the agent writes beside proof.tex before it asks (ADR-0013)
        result = runner.invoke(app, [*args, "--json"])
        assert result.exit_code == 0 and _envelope(result)["ok"], (args, result.output)


def test_an_unknown_reference_source_type_names_the_valid_ones_with_a_code(tmp_path: Path):
    """As --trust-level and a node's kind do: the refused value, every valid one, and an error code."""
    root = str(_project(tmp_path))
    args = ["reference", "import", "R1", "A title", "2020", "--source-type", "paper", "--root", root]

    envelope = _envelope(runner.invoke(app, [*args, "--json"]))
    assert envelope["error"]["code"] == "INVALID_SOURCE_TYPE"
    assert envelope["error"]["message"] == ("'paper' is not a valid source type; expected one of: standard_reference, research_paper, "
                                            "textbook, survey, monograph, website, other")
    text = runner.invoke(app, args)
    assert text.exit_code == 1 and "expected one of: standard_reference" in text.stdout and "[INVALID_SOURCE_TYPE]" in text.stdout
    assert "research_paper" in " ".join(runner.invoke(app, ["reference", "import", "--help"]).stdout.split())
