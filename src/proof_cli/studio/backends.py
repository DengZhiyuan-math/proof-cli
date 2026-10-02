"""AI backends for the agent panel, and the registry that lists them.

A backend runs one chat turn in the project directory and reports what happens as
events. The agent manager (agent.py) does everything that does not depend on the
backend: it checks the request, snapshots the editable files, computes the per-file
diffs afterwards and undoes turns.

Two kinds ship with the studio, both local CLIs the researcher logs into:

- ``claude`` (backend_claude.py): the local Claude Code CLI.
- ``codex`` (backend_codex.py): the local OpenAI Codex CLI (``codex exec --json``).

prism-local's API-model backend (an OpenAI-compatible API with an API key) is not part of
proof-cli: the proof agent runs on the CLIs, which search the web and run commands (#72).

To add another backend, subclass `Backend` (or `CliBackend` for a CLI that prints
JSON lines), implement `run` (or `command` and `handle`), and add its type to
`kinds` in `load_backends`, which also applies the user's settings.

Events a backend emits through ``job.emit`` (the panel understands exactly these):

    {"t": "init", "session_id": str, "model": str|None}
    {"t": "message_start"}                      a new assistant message begins
    {"t": "delta", "text": str}                 streamed text of that message
    {"t": "text", "text": str}                  a whole message (when not streamed)
    {"t": "thinking_start"}                     the model starts thinking
    {"t": "thinking", "text": str}              streamed thinking (where the model shows it)
    {"t": "tool_start", "id": str, "name": str} a tool call begins (its input still streams)
    {"t": "tool_live", "id": str, "path"?: str, "text"?: str, "old"?: str, "old_done"?: true}
                                                the file a Write/Edit is writing, as it streams
    {"t": "tool", "id": str, "name": str, "summary": str, "path"?: str, "lines"?: [first, last]}
                                                a tool call, with the file (and lines) a file tool works on
    {"t": "tool_result", "id": str, "error": bool, "preview": str}
    {"t": "build", "result": dict}              a build the agent ran (agent.py, not backends)
    {"t": "rate", "rate": dict}                 Claude usage limits
    {"t": "error", "message": str}

`run` returns a dict with any of: session_id, exit (0 = success), is_error, subtype,
cost (USD, only when billed per token), billing ("subscription" or "api"), duration
(ms), usage ({"in": tokens, "out": tokens}), denials (tool
names refused), stderr.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from .proc import NO_WINDOW, TREE, kill_tree  # noqa: F401 — re-exported


SYSTEM_APPEND = """\
You are being driven from prism-local, a local LaTeX web editor, not the
terminal. The author sees your text in a chat panel next to the LaTeX source
and the compiled PDF.
- The message may include a [Referenced] block listing files and line ranges
  (with their text) that the author @-mentioned. Treat it as the author's
  pointer to what they mean by "this", "here", "the selection".
- In edit mode each message ends with a [Scope for this turn] line saying which
  files you may change. It replaces the scope of every earlier message.
- The author reviews every turn's file changes as a diff with an undo button,
  so make focused, minimal edits and say which files you changed.
- In .tex files, write display math with named LaTeX environments:
  \\begin{equation} ... \\end{equation} (or equation*, align, align*, gather,
  multline), never the shortcuts \\[ ... \\] or $$ ... $$. Use \\begin{...}
  environments rather than shortcuts elsewhere in them too.
- key-ideas.md is Markdown, not LaTeX: write its math as $...$ inline and
  $$...$$ for display math, the only delimiters its review page typesets.
- Read, search and change files with your file tools (Read, Grep, Glob, Edit,
  Write), not shell commands such as cat, sed, python or rm.
- To compile, use the compile tool when you have it: it runs the editor's own
  build (the author's Compile button) and returns the errors with file:line.
  Compile after substantial edits and fix the errors your changes caused.
  Never run pdflatex or latexmk yourself. Without the tool, do not compile:
  the author compiles in the editor.
- Never commit, push, or run git commands that modify the repository.
- Keep replies concise. If the project has a CLAUDE.md or AGENTS.md, follow it exactly.
- Do not claim an argument is correct, or a step proved, unless you checked it.
"""


def system_append(context=None) -> str:
    """The instructions a turn starts with. A node's proof agent (proof_agent.py) gets its own
    brief instead of the rule to follow the project's CLAUDE.md/AGENTS.md: its instructions and
    permissions are explicit, never inherited from the repository (ADR-0011 point 8)."""
    if context is None:
        return SYSTEM_APPEND
    general = SYSTEM_APPEND.replace(
        "- Keep replies concise. If the project has a CLAUDE.md or AGENTS.md, follow it exactly.\n", "- Keep replies concise.\n"
    ).replace(  # a role's brief says what it runs (the Numerics role runs programs); only the plain editor's agent has no shell
        "- Read, search and change files with your file tools (Read, Grep, Glob, Edit,\n"
        "  Write), not shell commands such as cat, sed, python or rm.\n", ""
    )
    return f"{general}\n{context.brief()}"


# The agent's compile tool (mcp_compile.py, taken from upstream 2938c05): an MCP server either CLI starts
# for the turn, named "studio", with one tool, "compile", that builds through the node's own studio.
MCP_SERVER = "studio"
# The compile tool as each CLI names it in its events: Claude Code's `mcp__<server>__<tool>`, Codex's `<server>.<tool>`.
COMPILE_TOOL_NAMES = frozenset((f"mcp__{MCP_SERVER}__compile", f"{MCP_SERVER}.compile"))


def tool_name(name: str | None) -> str | None:
    """A tool's name as the turn's events carry it, for either CLI: the compile tool is "Compile" (what the stuck
    rule, the transcript and the live view look for), every other tool its own name."""
    return "Compile" if name in COMPILE_TOOL_NAMES else name


def has_compile_tool(job: "Job") -> bool:
    """Whether this turn gets the compile tool: the node's studio has a build (a URL), the turn edits (plan
    mode admits no tool that builds), and its role typesets (the Prover and Numerics don't)."""
    return bool(job.compile_url) and job.mode == "edit" and (job.context is None or job.context.compiles)


def compile_tool_server(url: str) -> dict:
    """The MCP server's command and arguments, as either CLI's configuration wants them."""
    return {"command": sys.executable, "args": [str(Path(__file__).with_name("mcp_compile.py")), "--url", url]}


def find_bin(env: str, name: str, extra: tuple[str, ...] = ()) -> str | None:
    """A CLI from the environment variable `env`, else PATH, else a few usual places."""
    return os.environ.get(env) or shutil.which(name) \
        or next((p for p in extra if Path(p).exists()), None)


class Job:
    """One chat turn: the request, its event log and the file snapshots around it."""

    def __init__(self, jid: int):
        self.id = jid
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.done = False
        self.cancel = threading.Event()
        self.proc: subprocess.Popen | None = None   # a CLI backend's process
        self.http = None                            # an API backend's open response
        # The request, filled in by AgentManager.start.
        self.provider = ""
        self.prompt = ""
        self.session_id: str | None = None
        self.mode = "ask"
        self.model: str | None = None
        self.effort: str | None = None
        self.scope: list[str] | None = None     # files this turn may change (None: any)
        self.compile_url: str | None = None     # the node studio this turn's compile tool builds through (None: no tool)
        self.root = Path(".")
        self.files: Callable[[], list[str]] = lambda: []    # editable files
        self.writable: Callable[[str], bool] = lambda rel: False
        self.context = None     # a node's ProofAgentContext (proof_agent.py), or None outside a proof map
        self.turn: dict | None = None   # a run's turn (agent_run.py): role, name, redirect; None for the researcher's own
        self.before: dict[str, bytes | None] = {}     # file contents around the turn
        self.after: dict[str, bytes | None] = {}
        # run once the backend is done, before the turn's changes are read (a draft's marker, ADR-0013)
        self.finish: Callable[[], None] | None = None

    def emit(self, ev: dict) -> None:
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    def wait_events(self, after: int, timeout: float) -> tuple[list[dict], bool]:
        with self.cond:
            if len(self.events) <= after and not self.done:
                self.cond.wait(timeout)
            return self.events[after:], self.done


class Backend:
    """Base class. Subclasses set the class attributes and implement `run`."""

    kind = ""
    id = ""
    label = ""
    models: list[str] = []            # suggestions for /model; any valid name is accepted
    default_model: str | None = None
    efforts: tuple[str, ...] = ()     # accepted effort levels; empty: no effort setting
    # False: the backend cannot stop writes outside the @-mentioned files, so the
    # manager reverts such writes after the turn.
    enforces_scope = True
    skills = False                    # offers skills / slash commands (/api/agent/commands)
    usage_limits = False              # reports subscription usage limits (/api/agent/usage)

    def __init__(self, pid: str, spec: dict | None = None):
        spec = spec or {}
        self.id = pid
        self.label = spec.get("label") or self.label or pid
        if spec.get("models") is not None:
            self.models = [str(m) for m in spec["models"]]
        self.default_model = spec.get("default_model", self.default_model)
        if spec.get("efforts") is not None:
            self.efforts = tuple(str(e) for e in spec["efforts"])

    def unavailable(self) -> str | None:
        """None when the backend can run, else why not (shown to the author)."""
        return None

    def check(self, model: str | None, effort: str | None) -> str | None:
        if effort and effort not in self.efforts:
            return (f"{self.label} has no effort setting." if not self.efforts else
                    f"Effort for {self.label} must be one of: {', '.join(self.efforts)}")
        return None

    def preflight(self, root: Path) -> str | None:
        """Checked right before each turn; a message here stops the turn (nothing is sent)."""
        return None

    def run(self, job: Job) -> dict:
        raise NotImplementedError

    def stop(self, job: Job) -> None:
        job.cancel.set()
        if job.proc and job.proc.poll() is None:
            kill_tree(job.proc)
        if job.http is not None:
            try:
                job.http.close()
            except Exception:  # noqa: BLE001 — closing from another thread may race
                pass

    def commands(self, root: Path, refresh: bool = False) -> dict:
        return {"skills": [], "commands": [], "terminal_only": []}

    def info(self) -> dict:
        why = self.unavailable()
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "available": why is None, "reason": why,
                "models": list(self.models), "default_model": self.default_model,
                "efforts": list(self.efforts), "skills": self.skills,
                "usage_limits": self.usage_limits, "enforces_scope": self.enforces_scope}


class CliBackend(Backend):
    """A local CLI that takes the prompt on stdin and prints one JSON object per line."""

    def command(self, job: Job) -> tuple[list[str], str]:
        """The argv to start and the text to write to its stdin."""
        raise NotImplementedError

    def handle(self, d: dict, job: Job, st: dict) -> None:
        """Turn one JSON line into events; keep what `run` returns in `st`."""
        raise NotImplementedError

    def run(self, job: Job) -> dict:
        if job.cancel.is_set():         # stopped (or the studio closed) before it started
            return {"is_error": True, "subtype": "stopped"}
        cmd, stdin = self.command(job)
        st: dict = {}
        stderr_lines: list[str] = []
        # The prompt goes through stdin so it can never be parsed as a flag. TREE: Stop
        # also ends the commands the CLI started.
        job.proc = subprocess.Popen(cmd, cwd=job.root, stdin=subprocess.PIPE,
                                    env=job.context.env() if job.context else None,   # PROOF_ROOT, `proof` on PATH
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    **TREE)
        if job.cancel.is_set():         # stop() came between the check above and the start:
            kill_tree(job.proc)         # it couldn't see this process, so end it here
        job.proc.stdin.write(stdin)
        job.proc.stdin.close()
        threading.Thread(target=lambda: stderr_lines.extend(job.proc.stderr), daemon=True).start()
        for line in job.proc.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                self.handle(d, job, st)
        job.proc.wait()
        st["exit"] = job.proc.returncode
        if st["exit"] != 0 or st.get("is_error"):
            st["stderr"] = "".join(stderr_lines)[-2000:]
        return st


# ---------------------------------------------------------------- registry

def config_path() -> Path:
    """User-level agent settings: $PRISM_AGENTS, else ~/.prism-local/agents.json."""
    return Path(os.environ.get("PRISM_AGENTS") or Path.home() / ".prism-local" / "agents.json")


def read_config(path: Path | None = None) -> tuple[dict, str | None]:
    """The settings file as a dict, and an error message if it could not be read."""
    p = path or config_path()
    if not p.exists():
        return {}, None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("the file must hold a JSON object")
        return data, None
    except (OSError, ValueError) as e:
        return {}, f"{p}: {e}"


def load_backends(path: Path | None = None) -> tuple[dict[str, Backend], str, str | None]:
    """All backends (the built-in Claude Code and Codex CLIs, then the user's settings), the
    default id, and an error message if the settings file was bad.

    Settings file (JSON)::

        {
          "default": "codex",
          "providers": {
            "codex": {"bin": "C:/tools/codex.cmd"},
            "claude": {"default_model": "opus"}
          }
        }

    An entry with the id of a built-in changes only the fields it gives; another entry names
    its `type` (claude or codex). ``"enabled": false`` hides a provider.
    """
    from .backend_claude import ClaudeCode
    from .backend_codex import Codex
    kinds = {"claude": ClaudeCode, "codex": Codex}

    data, err = read_config(path)
    specs: dict[str, dict] = {"claude": {"type": "claude"}, "codex": {"type": "codex"}}
    user = data.get("providers") or {}
    if not isinstance(user, dict):
        user, err = {}, err or "'providers' must be an object"
    for pid, spec in user.items():
        if isinstance(spec, dict):
            specs[pid] = {**specs.get(pid, {}), **spec}
    out: dict[str, Backend] = {}
    for pid, spec in specs.items():
        if spec.get("enabled") is False:
            continue
        cls = kinds.get(spec.get("type") or pid)
        if cls is None:
            err = err or f"provider {pid}: type {spec.get('type')!r} isn't supported (the studio runs the Claude Code or Codex CLI)"
            continue
        try:
            out[pid] = cls(pid, spec)
        except (TypeError, ValueError) as e:
            err = err or f"provider {pid}: {e}"
    default = os.environ.get("PRISM_AGENT") or data.get("default") or "claude"
    if default not in out:
        default = next(iter(out), "claude")
    return out, default, err
