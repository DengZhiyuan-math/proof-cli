#!/usr/bin/env python3
"""The studio: editor + PDF preview with SyncTeX + an AI agent panel, for one folder
(taken from prism-local, ADR-0011). A `Studio` serves one folder; proof-cli's server runs
one per node, and `main` below runs a single one for developing the studio itself:

    python -m proof_cli.studio.server [PROJECT_DIR] [--port 8765] [--no-browser]

Besides the builds (build.py) it runs only read-only `git status` / `git diff`
and, for the agent panel, the chosen AI backend (agent.py, backends.py): the
Claude Code or Codex CLI.
Optional per-project settings live in PROJECT_DIR/prism.json (see README).
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable

from . import build, httpbase
from .agent_run import AgentRun, RunHooks
from ..key_ideas import KEY_IDEAS_FILE
from ..vault import RUN_SCRIPT
from .agent import NO_WINDOW, AgentManager
from .fsutil import EDITABLE_SUFFIXES, SKIP_DIRS, with_line_ends_of, write_bytes
from .texutil import group, plain_text

# what a computation node's studio edits besides the LaTeX suffixes (spec #145): its program, its data, its logs
COMPUTATION_SUFFIXES = {".sh", ".py", ".sage", ".lean", ".jl", ".r", ".R", ".m", ".gp", ".mac", ".csv", ".json", ".log", ".toml", ".yml", ".yaml", ".cfg", ".ini"}

MAX_FILES = 3000

STANDARD_THEOREMS = ["theorem", "proposition", "lemma", "corollary", "definition",
                     "remark", "example"]


class Config:
    """Project settings: defaults, overridden by PROJECT_DIR/prism.json. A prism.json
    that cannot be used is reported (`error`) and the defaults apply instead."""

    def __init__(self, root: Path, *, fixed_build: tuple[str, str] | None = None):
        self.root = root.resolve()
        problems: list[str] = []
        cfg = self.root / "prism.json"
        self.stamp = cfg.stat().st_mtime_ns if cfg.is_file() else None
        data: dict = {}
        if self.stamp is not None:
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("it must hold a JSON object")
            except (OSError, ValueError) as e:
                data = {}
                problems.append(f"prism.json cannot be used ({e}); the defaults apply.")
        if fixed_build is not None:
            # a node's build is fixed (ADR-0011): its PDF is what review archives
            if data.get("main") or data.get("outdir"):
                problems.append(f"a node's main file and output are fixed ({fixed_build[0]} → "
                                f"{fixed_build[1]}/); main and outdir are ignored.")
            self.main, self.outdir = fixed_build
        else:
            self.main = str(data.get("main") or self._guess_main())
            outdir = str(data.get("outdir") or "build").replace("\\", "/").strip("/") or "build"
            if Path(outdir).is_absolute() or ".." in Path(outdir).parts:
                problems.append("outdir must be a folder inside the project; build is used.")
                outdir = "build"
            self.outdir = outdir
        lists = {k: data.get(k) for k in ("files", "exclude")}
        for k, v in lists.items():
            if v is not None and not (isinstance(v, list) and all(isinstance(g, str) for g in v)):
                problems.append(f"{k} must be a list of patterns; it is ignored.")
                lists[k] = None
        self.files = lists["files"]                    # optional list of globs
        self.exclude = lists["exclude"] or []
        self.builder = str(data.get("builder") or "auto")       # auto (built-in), latexmk, tectonic
        self.engine = data.get("engine") or None                 # pdflatex, xelatex, lualatex
        if self.engine is not None and str(self.engine).lower() not in build.ENGINES:
            problems.append(f"unknown engine {self.engine!r} (use pdflatex, xelatex or "
                            "lualatex); it is chosen from the document instead.")
            self.engine = None
        self.shell_escape = data.get("shell_escape") is True
        # Commands of your own per mode: an argv list, or a shell string (see build.py).
        cmds = data.get("build") or {}
        if not isinstance(cmds, dict):
            problems.append("build must map modes to commands; it is ignored.")
            cmds = {}
        self.custom = {k: v for k, v in cmds.items() if isinstance(v, (str, list)) and v}
        self.modes = [m for m in ("draft", "strict", "check") if m != "check" or m in self.custom]
        self.error = " ".join(p if p.startswith("prism.json") else "prism.json: " + p
                              for p in problems) or None
        stem = Path(self.main).stem
        out = self.root / self.outdir
        self.pdf = out / f"{stem}.pdf"
        self.log = out / f"{stem}.log"
        self.synctex = out / f"{stem}.synctex.gz"

    def _guess_main(self) -> str:
        if (self.root / "main.tex").is_file():
            return "main.tex"
        cands = [p for p in sorted(self.root.glob("*.tex")) if not p.name.startswith("._")
                 and "\\documentclass" in p.read_text(encoding="utf-8", errors="replace")[:5000]]
        return cands[0].name if cands else "main.tex"

    def expand(self, cmd: list[str] | str) -> list[str] | str:
        sub = lambda a: str(a).replace("{main}", self.main).replace("{outdir}", self.outdir)  # noqa: E731
        return sub(cmd) if isinstance(cmd, str) else [sub(a) for a in cmd]

    def describe(self, mode: str) -> str:
        """What a build in `mode` runs, for the Compile menu."""
        cmd = self.custom.get(mode)
        if cmd:
            return cmd if isinstance(cmd, str) else " ".join(self.expand(cmd))
        how = "stops at the first error" if mode == "strict" else "continues after errors"
        engine = self.engine or "chosen from the document"
        if self.builder in ("latexmk", "tectonic"):
            return f"{self.builder}; engine {engine}; {how}"
        return (f"built-in: engine {engine}, then bibtex/biber and makeindex as needed, "
                f"rerun until stable; {how}")


def mtime(p: Path) -> float:
    return p.stat().st_mtime_ns / 1e9


# ---------------------------------------------------------------- symbols

LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
BEGIN_RE = re.compile(r"\\begin\{([A-Za-z*]+)\}(?:\[([^\]]*)\])?")
# \section{…}, \section*{…}, \section[short]{long}; the title is read with its braces paired.
SECTION_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection)\*?\s*(?:\[[^\]]*\])?\s*\{")
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
MACRO_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareMathOperator|DeclarePairedDelimiter)\*?"
    r"\s*\{?\\([A-Za-z]+)\}?")
BIBKEY_RE = re.compile(r"^\s*@(\w+)\s*\{\s*([^,\s]+)\s*,", re.M)
# \newtheorem{thm}{Theorem}[section], \newtheorem{lem}[thm]{Lemma}, llncs, mdframed, tcolorbox …
NEWTHEOREM_RE = re.compile(r"\\(?:newtheorem|spnewtheorem|newmdtheoremenv|newtcbtheorem)\*?\s*"
                           r"\{([^}]+)\}\s*(?:\[[^\]]*\]\s*)?(?:\{([^}]*)\})?")
# thmtools: \declaretheorem[name=Theorem, numberwithin=section]{thm}
DECLARETHEOREM_RE = re.compile(r"\\declaretheorem\*?\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}")


def strip_comment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


# ---------------------------------------------------------------- synctex

SP_TO_BP = 72.0 / 72.27 / 65536.0     # scaled points -> PDF points
REC_RE = re.compile(r"^([\[(hvxkg$])(\d+),(\d+):(-?\d+),(-?\d+)(?::(-?\d+),(-?\d+),(-?\d+))?")


class SyncTex:
    """Minimal reader for .synctex.gz files (pdfTeX, XeTeX, LuaTeX, Tectonic)."""

    def __init__(self, studio: "Studio") -> None:
        self.studio = studio
        self.stamp = None
        self.inputs: dict[int, str] = {}
        self.recs: list[tuple] = []   # (page, kind, file, line, x, y, w, h, d) in bp

    def load(self) -> bool:
        if not self.studio.cfg.synctex.exists():
            return False
        st = self.studio.cfg.synctex.stat().st_mtime_ns
        if st == self.stamp:
            return True
        inputs, recs, page, unit, mag = {}, [], 0, 1.0, 1.0
        with gzip.open(self.studio.cfg.synctex, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                c = line[:1]
                if c == "I" and line.startswith("Input:"):
                    tag, _, path = line[6:].rstrip("\n").partition(":")
                    if path:
                        try:
                            # pdfTeX writes paths relative to the working directory.
                            pp = Path(path) if os.path.isabs(path) else self.studio.root / path
                            rel = pp.resolve().relative_to(self.studio.root).as_posix()
                            inputs[int(tag)] = rel
                        except ValueError:
                            pass
                elif c == "{":
                    page = int(line[1:])
                elif line.startswith("Unit:"):
                    unit = float(line[5:])
                elif line.startswith("Magnification:"):
                    mag = float(line[14:]) / 1000.0
                elif c in "[(hvxkg$":
                    m = REC_RE.match(line)
                    if not m:
                        continue
                    f = int(m.group(2))
                    if f not in inputs:
                        continue
                    s = unit * mag * SP_TO_BP
                    w, h, d = (int(m.group(i)) * s if m.group(i) else 0.0
                               for i in (6, 7, 8))
                    recs.append((page, m.group(1), inputs[f], int(m.group(3)),
                                 int(m.group(4)) * s, int(m.group(5)) * s, w, h, d))
        self.inputs, self.recs, self.stamp = inputs, recs, st
        return True

    # Paragraph line boxes ('(') carry the line where the paragraph *ended*;
    # the fine records (glyph runs x, kerns k, glue g, math $, ...) carry the
    # line they were typeset from. So boxes locate the visual line, and fine
    # records supply the source line.
    FINE = "xkg$h"

    def _line_box(self, page, x, y):
        """Smallest wide hbox on `page` whose vertical extent contains y."""
        best = None
        for r in self.recs:
            if r[0] == page and r[1] == "(" and r[6] > 0 \
                    and r[5] - r[7] - 1 <= y <= r[5] + r[8] + 1 \
                    and r[4] - 1 <= x <= r[4] + r[6] + 1:
                if best is None or r[6] > best[6]:   # widest = the text line
                    best = r
        return best

    def forward(self, rel: str, line: int) -> dict | None:
        cands = [r for r in self.recs if r[2] == rel and r[3] > 0
                 and r[1] in self.FINE]
        if not cands:
            cands = [r for r in self.recs if r[2] == rel and r[3] > 0]
        if not cands:
            return None
        after = [r for r in cands if r[3] >= line]
        target = min(r[3] for r in after) if after else max(r[3] for r in cands)
        first = min((r for r in cands if r[3] == target),
                    key=lambda r: (r[0], r[5], r[4]))
        box = self._line_box(first[0], first[4], first[5])
        if box:
            return {"page": first[0], "x": box[4], "y": box[5] - box[7],
                    "w": box[6], "h": max(box[7] + box[8], 8.0), "line": target}
        return {"page": first[0], "x": first[4], "y": first[5] - 9,
                "w": 60.0, "h": 12.0, "line": target}

    def inverse(self, page: int, x: float, y: float) -> dict | None:
        box = self._line_box(page, x, y)
        on_page = [r for r in self.recs if r[0] == page and r[3] > 0]
        if box:
            base = box[5]
            row = [r for r in on_page if r[1] in self.FINE
                   and box[4] - 1 <= r[4] <= box[4] + box[6] + 1
                   and base - box[7] - 1 <= r[5] <= base + box[8] + 1]
            if row:
                left = [r for r in row if r[4] <= x + 0.5]
                r = max(left, key=lambda r: r[4]) if left else min(row, key=lambda r: r[4])
                return {"file": r[2], "line": r[3]}
        if not on_page:
            return None
        r = min(on_page, key=lambda r: (r[4] - x) ** 2 + 4 * (r[5] - y) ** 2)
        return {"file": r[2], "line": r[3]}


class Response:
    """A studio answer, whichever HTTP server sends it (the standalone one below, or proof-cli's)."""

    def __init__(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.status, self.body, self.ctype = status, body, ctype


RUN_TIMEOUT = 600.0  # seconds for one run of a computation node's run.sh, as for a build


def _json(obj, code=200) -> Response:
    return Response(code, json.dumps(obj).encode("utf-8"))


def _err(code, msg) -> Response:
    return _json({"error": msg}, code)


def program_argv(script: Path) -> list[str]:
    """How to start the node's program: the script as itself when it is executable; otherwise (an exchanged copy,
    a fresh checkout) by the interpreter its own `#!` line names, so a zsh or Python entry runs as written —
    and through `sh` only when it names none (audit R-S2)."""
    if os.access(script, os.X_OK):
        return [str(script)]
    with script.open("rb") as handle:
        first = handle.readline(512)
    if first.startswith(b"#!"):
        interpreter = shlex.split(first[2:].decode("utf-8", "replace").strip())
        if interpreter:
            return [*interpreter, str(script)]
    return ["/bin/sh", str(script)]


class Studio:
    """One folder's studio: its settings, files, build, SyncTeX and agent, with its own locks.

    prism-local kept all of this in module globals, one project per process. proof-cli runs
    one Studio per node folder in its own server (ADR-0011): a build or an agent turn is
    limited per folder, never per process. `fixed_build` pins the main file and output
    (proof.tex → build/proof.pdf) whatever a prism.json says, and `hidden` names top-level
    folders the editor neither lists nor writes (a node's snapshots and scratch).
    `agent_scratch` is the one hidden folder the agent may write anything in (ADR-0011).

    Once closed, a studio starts no build and no agent turn, even for a request that got
    hold of it before: admitting work and closing take the same lock."""

    def __init__(self, root: Path, *, fixed_build: tuple[str, str] | None = None,
                 hidden: tuple[str, ...] = (), agent_scratch: str | None = None,
                 agent_context: Callable[[], object] | None = None,
                 node_medium: Callable[[], str | None] | None = None,
                 on_run: Callable[[str, str, object, object], dict] | None = None,
                 working_digest: Callable[[], object] | None = None,
                 open_command: Callable[[], str | None] | None = None,
                 run_hooks: RunHooks | None = None) -> None:
        # a node's Medium (spec #145): Run exists for a computation; on_run records a run as an
        # Evidence check when the folder it ran in is the current snapshot — working_digest is the
        # folder's manifest digest, read before and after the run — and says what it did or why not;
        # open_command is the project's optional way to hand the folder to an editor
        self.node_medium = node_medium
        self.on_run = on_run
        self.working_digest = working_digest
        self.open_command = open_command
        self.running_runs: list[build.Runner] = []  # runs may be concurrent, each its own Evidence check
        self.fixed_build = fixed_build
        self.hidden = hidden
        self.agent_scratch = agent_scratch
        self.closed = False
        self._admit = threading.Lock()
        self.root = root.resolve()
        self.cfg = Config(self.root, fixed_build=fixed_build)
        self.save_lock = threading.Lock()
        self.build_lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.running_build = None           # the build in progress, for /api/build/stop
        self._git_prefix: str | None = None
        self.sync = SyncTex(self)
        # agent_context: a node's proof agent (proof_agent.py), made fresh for each turn
        self.agent = AgentManager(lambda: self.root, self.agent_files, self.agent_writable, context_fn=agent_context)
        # the agent's run on this node (agent_run.py, spec #145): Start once, then autonomous, under the researcher's eye
        self.run = AgentRun(self.agent, run_hooks) if run_hooks is not None else None

    def refresh_config(self) -> None:
        """Load prism.json again when it changed, so a new engine or outdir applies at once."""
        try:
            stamp = (self.root / "prism.json").stat().st_mtime_ns
        except OSError:
            stamp = None
        if stamp != self.cfg.stamp:
            self.cfg = Config(self.root, fixed_build=self.fixed_build)

    def close(self) -> None:
        with self._admit:
            self.closed = True
            running = self.running_build
        if running is not None:
            running.stop()      # registered before it runs anything, so nothing starts
        self.stop_runs()        # a computation's runs too (ADR-0011: programs are limited per folder)
        if self.run is not None and self.run.active():
            self.run.release("the studio is closing")
        self.agent.shutdown()

    # ------------------------------------------------------------ the agent's files
    def agent_writable(self, rel: str) -> Path:
        """What the agent may write: the editor's sources, plus anything in its scratch folder
        (a script, its output). Raises ValueError otherwise."""
        try:
            return self.resolve(rel)
        except ValueError:
            if not self.agent_scratch or not rel or rel.startswith("/") or "\\" in rel:
                raise
        scratch = (self.root / self.agent_scratch).resolve()
        p = (self.root / rel).resolve()
        if scratch not in p.parents or any(part.startswith(".") for part in p.relative_to(scratch).parts):
            raise ValueError("not a file the agent may write")
        return p

    def agent_files(self) -> list[str]:
        """The files an agent turn snapshots, diffs and can undo: the sources and its scratch."""
        files = self.list_files()
        scratch = self.root / self.agent_scratch if self.agent_scratch else None
        if scratch is not None and scratch.is_dir():
            for dirpath, dirnames, filenames in os.walk(scratch):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                files += [(Path(dirpath) / f).relative_to(self.root).as_posix() for f in sorted(filenames) if not f.startswith(".")]
                if len(files) > MAX_FILES:
                    break
        return files

    def _excluded(self, rel: str) -> bool:
        parts = rel.split("/")
        if any(p.startswith(".") or p in SKIP_DIRS for p in parts[:-1]):
            return True
        if len(parts) > 1 and parts[0] in self.hidden:    # a node's snapshots/, scratch/
            return True
        if parts[-1].startswith("._") or rel.startswith(self.cfg.outdir + "/"):
            return True
        return any(fnmatch.fnmatch(rel, g) for g in self.cfg.exclude)

    def resolve(self, rel: str) -> Path:
        """Map a project-relative path to an editable file, or raise ValueError."""
        if not rel or rel.startswith("/") or "\\" in rel:
            raise ValueError("bad path")
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            raise ValueError("outside project")
        r = p.relative_to(self.root).as_posix()
        if p.suffix not in self.editable_suffixes() or self._excluded(r):
            raise ValueError("not an editable file")
        return p

    def list_files(self) -> list[str]:
        seen: set[str] = set()
        if self.cfg.files:
            for g in self.cfg.files:
                for p in self.root.glob(g):
                    rel = p.relative_to(self.root).as_posix()
                    if p.is_file() and p.suffix in self.editable_suffixes() and not self._excluded(rel):
                        seen.add(rel)
        else:
            for dirpath, dirnames, filenames in os.walk(self.root):
                reld = Path(dirpath).relative_to(self.root).as_posix()
                reld = "" if reld == "." else reld + "/"
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                                     and d not in SKIP_DIRS and reld + d != self.cfg.outdir
                                     and not (reld == "" and d in self.hidden))
                for f in filenames:
                    rel = reld + f
                    if Path(f).suffix in self.editable_suffixes() and not self._excluded(rel):
                        seen.add(rel)
                if len(seen) > MAX_FILES:
                    break
        return sorted(seen, key=lambda s: (s != self.cfg.main, s.count("/") == 0, s))

    def git(self, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
        """Read-only git in the project. --no-optional-locks: the editor asks every two
        seconds, and must never hold .git/index.lock when a git command of yours starts."""
        return subprocess.run(["git", "--no-optional-locks", *args], cwd=self.root, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              **NO_WINDOW)

    def git_prefix(self) -> str:
        """Where the project sits in its repository: "" at the top, "examples/minimal/" …"""
        if self._git_prefix is None:
            try:
                self._git_prefix = self.git("rev-parse", "--show-prefix").stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return ""
        return self._git_prefix

    def git_status(self) -> dict[str, str]:
        """{project-relative path: status} of the files git reports as changed."""
        try:
            out = self.git("status", "--porcelain", "-z", "-uall", "--", ".").stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        # -z: unquoted paths (any characters), relative to the repository's top, "XY path";
        # a rename or copy is followed by its old path.
        prefix, st, entries, i = self.git_prefix(), {}, out.split("\0"), 0
        while i < len(entries):
            e = entries[i]
            i += 1
            if len(e) < 4:
                continue
            if "R" in e[:2] or "C" in e[:2]:
                i += 1
            if e[3:].startswith(prefix):
                st[e[3:][len(prefix):]] = e[:2].strip() or "M"
        return st

    def save_file(self, rel: str, content: str, base_mtime: float | None, force: bool) -> tuple[dict, int]:
        """Write an editor buffer to disk, unless the file changed on disk since the editor
        loaded it (a conflict). The file keeps its line ends (the editor sends \\n)."""
        p = self.resolve(rel)
        with self.save_lock:     # check-then-write must not interleave with another save
            if p.exists() and base_mtime is not None and abs(mtime(p) - base_mtime) > 1e-6 \
                    and not force:
                return {"conflict": True, "mtime": mtime(p)}, 409
            write_bytes(p, with_line_ends_of(content, p).encode("utf-8"))
            return {"ok": True, "mtime": mtime(p)}, 200

    def document_order(self) -> list[str]:
        """Project .tex files in the order the main file \\input's them (depth first)."""
        order: list[str] = []

        def visit(rel: str) -> None:
            if rel in order:
                return
            order.append(rel)
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
            for line in text.splitlines():
                for m in INPUT_RE.finditer(strip_comment(line)):
                    child = self.resolve_tex_name(m.group(1).strip())
                    if child:
                        visit(child)

        visit(self.cfg.main)
        rest = [f for f in self.list_files() if f.endswith(".tex") and f not in order]
        return order + rest

    def theorem_envs(self, files: list[str]) -> dict[str, str]:
        """Theorem-like environments and the names they print: {"thm": "Theorem", …}."""
        envs: dict[str, str] = {}
        for rel in files:
            if Path(rel).suffix not in (".tex", ".sty", ".cls"):
                continue
            for raw in (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines():
                line = strip_comment(raw)
                for m in NEWTHEOREM_RE.finditer(line):
                    envs.setdefault(m.group(1).strip(), (m.group(2) or m.group(1)).strip())
                for m in DECLARETHEOREM_RE.finditer(line):
                    name = m.group(2).strip()
                    opt = re.search(r"(?:^|,)\s*(?:name|title)\s*=\s*\{?([^,}]+)", m.group(1) or "")
                    envs.setdefault(name, opt.group(1).strip() if opt else name.capitalize())
        return envs or {e: e.capitalize() for e in STANDARD_THEOREMS}

    def symbols(self) -> dict:
        labels, outline, macros = [], [], []
        files = self.list_files()
        envs = self.theorem_envs(files)
        outline_envs = set(envs)
        for rel in self.document_order():
            if not (self.root / rel).is_file():
                continue
            env = None
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            for n, raw in enumerate(text.splitlines(), 1):
                line = strip_comment(raw)
                m = SECTION_RE.search(line)
                if m:
                    g = group(line, m.end() - 1)          # a title that runs on: this line's part
                    outline.append({"file": rel, "line": n, "kind": m.group(1),
                                    "title": plain_text(g[0] if g else line[m.end():])})
                    env = m.group(1)
                for m in BEGIN_RE.finditer(line):
                    if m.group(1) in outline_envs:
                        outline.append({"file": rel, "line": n, "kind": m.group(1),
                                        "title": plain_text(m.group(2) or "")})
                    env = m.group(1)
                for m in MACRO_RE.finditer(line):
                    macros.append({"name": m.group(1), "file": rel, "line": n})
                for m in LABEL_RE.finditer(line):
                    labels.append({"label": m.group(1), "file": rel, "line": n,
                                   "kind": env or ""})
        keys = []
        for rel in (f for f in files if f.endswith(".bib")):
            bib = self.root / rel
            text = bib.read_text(encoding="utf-8", errors="replace")
            for m in BIBKEY_RE.finditer(text):
                if m.group(1).lower() not in ("string", "preamble", "comment"):
                    keys.append({"key": m.group(2), "type": m.group(1).lower(),
                                 "file": bib.relative_to(self.root).as_posix(),
                                 "line": text.count("\n", 0, m.start()) + 1})
        return {"labels": labels, "bibkeys": keys, "outline": outline, "macros": macros,
                "environments": list(envs), "env_titles": envs}


    def resolve_tex_name(self, name: str) -> str | None:
        return build.project_file(self.root, name)

    def run_build(self, mode: str, clean: bool = False) -> dict:
        """One build (see build.py). Only one runs at a time."""
        if mode not in self.cfg.modes:
            return {"busy": False, "exit": 127, "mode": mode, "seconds": 0, "diagnostics": [],
                    "output": f"There is no '{mode}' build.", "pdf_mtime": None}
        if not self.build_lock.acquire(blocking=False):
            return {"busy": True}
        try:
            t0 = time.time()
            before = mtime(self.cfg.pdf) if self.cfg.pdf.exists() else None
            cmd = self.cfg.custom.get(mode)
            with self._admit:   # registered before it runs, so close() can always stop it
                if self.closed:
                    return {"busy": False, "closed": True, "exit": 1, "mode": mode, "seconds": 0,
                            "diagnostics": [], "output": "The studio is closed.", "pdf_mtime": None}
                b = build.Build(self.root, self.cfg.main, self.cfg.outdir, mode, builder=self.cfg.builder, engine=self.cfg.engine,
                                command=self.cfg.expand(cmd) if cmd else None, clean=clean,
                                shell_escape=self.cfg.shell_escape)
                self.running_build = b
            r = b.run()
            if self.cfg.error:
                r["output"] = f"prism-local: {self.cfg.error}\n" + r["output"]
            pdf = mtime(self.cfg.pdf) if self.cfg.pdf.exists() else None
            return {**r, "busy": False, "mode": mode, "seconds": round(time.time() - t0, 1),
                    "pdf_mtime": pdf, "pdf_updated": pdf is not None and pdf != before}
        finally:
            self.running_build = None
            self.build_lock.release()

    def stop_build(self) -> bool:
        b = self.running_build
        if b is not None:
            b.stop()
        return b is not None

    # ------------------------------------------------------------ a computation's run (spec #145)
    def medium(self) -> str | None:
        return self.node_medium() if self.node_medium else None

    def editable_suffixes(self) -> set[str]:
        """The files the editor lists and writes: the LaTeX set, plus a computation's program and data (spec #145)."""
        return EDITABLE_SUFFIXES | COMPUTATION_SUFFIXES if self.medium() == "computation" else EDITABLE_SUFFIXES

    def run_program(self) -> dict:
        """Run the node's run.sh in its folder: the computation that is its candidate proof. Its exit
        code is recorded as an Evidence check on the current snapshot (0 passed, otherwise failed, a
        run that could not start or was stopped error) — never a decision. Runs may be concurrent."""
        t0 = time.time()
        script = self.root / RUN_SCRIPT
        runner = build.Runner(RUN_TIMEOUT)
        with self._admit:
            if self.closed:
                return {"closed": True, "exit": None, "output": "The studio is closed.", "seconds": 0, "cancelled": False, "timed_out": False,
                        "outcome": "error", "evidence": None, "note": ""}
            self.running_runs.append(runner)
        rc: int | None = None
        digest_before = self.working_digest() if self.working_digest else None
        try:
            if not script.is_file():
                out = f"{RUN_SCRIPT} is missing in {self.root}: nothing ran"
            else:
                try:
                    rc, out = runner.run(program_argv(script), self.root, env=build.build_env())
                except build.Stopped:  # stopped from another request, or by the time limit (the Runner raises for both)
                    out = f"the run took longer than {int(RUN_TIMEOUT)} seconds and was stopped" if runner.timed_out else "stopped"
        except OSError as exc:
            out = f"{RUN_SCRIPT} could not start: {exc}"
        finally:
            with self._admit:
                if runner in self.running_runs:
                    self.running_runs.remove(runner)
        seconds = round(time.time() - t0, 1)
        cancelled = runner.stopped.is_set() and not runner.timed_out  # as Build.run reads it
        outcome = "passed" if rc == 0 else "failed" if rc is not None else "error"
        what = "stopped" if cancelled else "timed out" if runner.timed_out else f"exit {rc}" if rc is not None else "could not start"
        notes = f"./{RUN_SCRIPT}: {what} after {seconds}s"
        digest_after = self.working_digest() if self.working_digest else None
        recorded = self.on_run(outcome, notes, digest_before, digest_after) if self.on_run else {"evidence": None, "note": ""}
        return {"exit": rc, "output": out, "seconds": seconds, "cancelled": cancelled, "timed_out": runner.timed_out,
                "outcome": outcome, "evidence": recorded.get("evidence"), "note": recorded.get("note") or ""}

    def run_action(self, action: str, body: dict) -> tuple[int, dict]:
        """The researcher's oversight of the agent's run (spec #145): start, pause, resume, redirect or release — (status, answer)."""
        if self.run is None:
            return 404, {"error": "NO_RUN", "message": "this folder has no proof map node, so no agent run"}
        if action == "start":
            provider = str(body.get("provider") or (self.agent.backend(None).id if self.agent.backend(None) else ""))
            roles = body.get("roles") if isinstance(body.get("roles"), list) else None
            r = self.run.start(provider, roles=roles, redirect=str(body.get("redirect") or "") or None,
                               model=body.get("model") or None, effort=body.get("effort") or None)
            return (409 if r.get("error") == "RUN_ACTIVE" else 400 if "error" in r else 200), r
        if action == "pause":
            return 200, self.run.pause()
        if action == "resume":
            return 200, self.run.resume()
        if action == "redirect":
            text = str(body.get("text") or "").strip()
            if not text:
                return 400, {"error": "REDIRECT_EMPTY", "message": "say what the agent should do differently"}
            return 200, self.run.redirect(text, body.get("role") or None)
        if action == "release":
            return 200, self.run.release()
        return 404, {"error": "NOT_FOUND", "message": f"no run action {action!r}"}

    def stop_runs(self) -> bool:
        with self._admit:
            runs = list(self.running_runs)
        for runner in runs:
            runner.stop()
        return bool(runs)

    def how_to_open(self) -> dict:
        """How the page hands this folder to an editor: the project's command, or the vscode:// scheme."""
        command = self.open_command() if self.open_command else None
        if command:
            return {"kind": "command", "command": command}
        return {"kind": "scheme", "url": f"vscode://file/{self.root}"}

    def open_folder(self, file: str | None = None, line: int | None = None) -> dict:
        """Hand the folder — or one of its files, at a line — to the editor: run the project's open
        command with {folder} and {file} filled in, or tell the page the scheme URL to use itself
        (`vscode://file/<folder>`, `vscode://file/<file>:<line>`)."""
        target = self.root
        if file:
            try:
                target = self.resolve(file)  # a file of this folder, never outside it
            except ValueError:
                return {"ok": False, "error": f"not a file of this node: {file}"}
        how = self.how_to_open()
        if how["kind"] != "command":
            url = f"vscode://file/{target}" + (f":{int(line)}" if file and line else "")
            return {"ok": True, "kind": "scheme", "url": url}
        entry = target if file else self.root / (RUN_SCRIPT if self.medium() == "computation" else self.cfg.main)
        argv = [part.replace("{folder}", str(self.root)).replace("{file}", str(entry)) for part in shlex.split(how["command"])]
        try:
            done = subprocess.run(argv, cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "kind": "command", "error": f"{how['command']}: {exc}"}
        return {"ok": done.returncode == 0, "kind": "command", "exit": done.returncode, "output": (done.stdout + done.stderr)[-2000:]}


    # ------------------------------------------------------------ requests
    def get(self, path: str, q: dict) -> Response:
        self.refresh_config()
        try:
            return self._get(path, q)
        except UnicodeDecodeError:
            return _err(415, "This file is not UTF-8 text; the studio edits UTF-8 files only.")
        except (ValueError, KeyError) as e:
            return _err(400, str(e))
        except FileNotFoundError:
            return _err(404, "file not found")
        except OSError as e:                 # e.g. the file is locked by another program
            return _err(500, f"{type(e).__name__}: {e}")

    def _get(self, path, q):
        if path == "/api/ping":
            return _json({"app": "proof-cli studio", "root": str(self.root), "pid": os.getpid()})
        if path == "/api/pdfstat":
            return _json({"mtime": mtime(self.cfg.pdf) if self.cfg.pdf.exists() else None})
        if path == "/pdf":
            if not self.cfg.pdf.exists():
                return _err(404, "no PDF yet")
            return Response(200, self.cfg.pdf.read_bytes(), "application/pdf")
        if path == "/api/tree":
            st = self.git_status()
            files = [{"path": f, "git": st.get(f, ""), "mtime": mtime(self.root / f)}
                     for f in self.list_files()]
            return _json({"root": self.root.name, "files": files, "order": self.document_order(),
                               "pdf_mtime": mtime(self.cfg.pdf) if self.cfg.pdf.exists() else None})
        if path == "/api/config":
            return _json({"main": self.cfg.main, "outdir": self.cfg.outdir, "modes": self.cfg.modes,
                               "builder": self.cfg.builder, "engine": self.cfg.engine, "error": self.cfg.error,
                               "build": {m: self.cfg.describe(m) for m in self.cfg.modes},
                               # the node's Medium, its folder and how to hand it to an editor (spec #145)
                               "folder": str(self.root), "medium": self.medium(), "open": self.how_to_open()})
        if path == "/api/agent/run":
            return _json(self.run.view() if self.run is not None else {"status": "idle", "reason": "no run on this folder"})
        if path == "/api/agent/events":
            job = self.agent.jobs.get(int(q["job"]))
            if not job:
                return _err(404, "unknown job")
            evs, done = job.wait_events(int(q.get("after", 0)), 20.0)
            return _json({"events": evs, "done": done})
        if path == "/api/agent/commands":
            r = self.agent.commands(q.get("provider") or None, refresh=q.get("refresh") == "1")
            return _json(r, 502 if "error" in r else 200)
        if path == "/api/agent/account":
            b = self.agent.backend(q.get("provider") or None)
            if b is None or not hasattr(b, "account"):
                return _json({"account": None})
            return _json(b.account(self.root, fresh=q.get("fresh") == "1"))
        if path == "/api/agent/info":
            return _json(self.agent.info())
        if path == "/api/symbols":
            return _json(self.symbols())
        if path == "/api/file":
            p = self.resolve(q.get("path", ""))
            return _json({"path": q["path"], "content": p.read_text(encoding="utf-8"),
                               "mtime": mtime(p)})
        if path == "/api/diff":
            if q.get("path"):
                self.resolve(q["path"])
            # --relative: paths as the project sees them, and nothing from outside it
            return _json({"diff": self.git("diff", "--no-color", "--relative", "--",
                                           q.get("path") or ".", timeout=20).stdout})
        if path == "/api/synctex/forward":
            with self.sync_lock:
                if not self.sync.load():
                    return _err(404, "no synctex data; build first")
                r = self.sync.forward(q["file"], int(q["line"]))
            return _json(r or {"error": "no match"}, 200 if r else 404)
        if path == "/api/synctex/inverse":
            with self.sync_lock:
                if not self.sync.load():
                    return _err(404, "no synctex data; build first")
                r = self.sync.inverse(int(q["page"]), float(q["x"]), float(q["y"]))
            return _json(r or {"error": "no match"}, 200 if r else 404)
        return _err(404, "not found")

    def post(self, path: str, body: dict) -> Response:
        self.refresh_config()
        try:
            return self._post(path, body)
        except (ValueError, KeyError) as e:
            return _err(400, str(e))
        except OSError as e:                 # e.g. the file is locked by another program
            return _err(500, f"{type(e).__name__}: {e}")

    def draft_key_ideas(self, body: dict) -> Response:
        """The node's proof agent drafts its missing key-ideas.md (ADR-0013): one edit turn that may
        write only that file, briefed to summarise proof.tex and the dependencies. The draft is then
        recorded in project state; the author edits it, and requesting review confirms it."""
        context = self.agent.context_fn() if self.agent.context_fn else None
        if context is None:
            return _err(404, "only a proof map node's studio drafts key ideas")
        target = self.root / KEY_IDEAS_FILE
        if target.exists():
            return _json({"error": f"{KEY_IDEAS_FILE} already exists: edit it, or remove it to have the agent draft it afresh"}, 409)
        r = self.agent.start(context.key_ideas_prompt(), body.get("session_id") or None, "edit",
                             body.get("model") or None, body.get("effort") or None, [KEY_IDEAS_FILE],
                             body.get("provider") or None, finish=lambda: context.record_draft(target))
        return _json(r, 409 if "error" in r else 200)

    def _post(self, path, body):
        if path == "/api/file":
            r, code = self.save_file(body["path"], str(body["content"]), body.get("base_mtime"),
                                bool(body.get("force")))
            return _json(r, code)
        if path == "/api/agent":
            scope = body.get("scope") or None
            if scope is not None:
                if not isinstance(scope, list) or not all(isinstance(f, str) for f in scope):
                    raise ValueError("scope must be a list of files")
                for f in scope:
                    self.resolve(f)          # an editable project file, or ValueError
            r = self.agent.start(body["prompt"], body.get("session_id") or None,
                            body.get("mode", "ask"), body.get("model") or None,
                            body.get("effort") or None, scope, body.get("provider") or None)
            return _json(r, 409 if "error" in r else 200)
        if path == "/api/key-ideas/draft":
            return self.draft_key_ideas(body)
        if path == "/api/agent/usage":
            return _json(self.agent.probe_rate(body.get("provider") or None))
        if path == "/api/agent/stop":
            return _json(self.agent.stop(int(body["job"])))
        if path == "/api/agent/undo":
            return _json(self.agent.undo(int(body["turn"])))
        if path == "/api/build":
            r = self.run_build(str(body.get("mode", "draft")), bool(body.get("clean")))
            return _json(r, 409 if r.get("busy") else 200)
        if path == "/api/build/stop":
            return _json({"ok": self.stop_build()})
        if path.startswith("/api/agent/") and path.split("/")[3] in ("start", "pause", "resume", "redirect", "release"):
            status, data = self.run_action(path.split("/")[3], body)
            return _json(data, status)
        if path == "/api/run":
            if self.medium() != "computation":
                return _json({"error": "NOT_A_COMPUTATION", "message": "Run is for a node whose medium is computation; this one compiles"}, 409)
            return _json(self.run_program())
        if path == "/api/run/stop":
            return _json({"stopped": self.stop_runs()})
        if path == "/api/open":
            line = body.get("line")
            return _json(self.open_folder(str(body.get("file") or "") or None, int(line) if line else None))
        return _err(404, "not found")




# ---------------------------------------------------------------- http

class Handler(httpbase.Handler):
    """The standalone studio's requests (see main): every one goes to its single Studio.
    The checks every request passes are in httpbase.py."""

    studio: Studio
    pages = {"/": "index.html", "/index.html": "index.html", "/viewer": "viewer.html"}

    def _answer(self, r: Response):
        return self._send(r.status, r.body, r.ctype)

    def get(self, path, q):
        return self._answer(self.studio.get(path, q))

    def post(self, path, body):
        return self._answer(self.studio.post(path, body))


def main():
    """A standalone studio on one folder, for developing the studio itself. proof-cli's own
    server mounts it per node (ADR-0011); this entry has no Home page and no idle exit."""
    httpbase.quiet_stdio()
    ap = argparse.ArgumentParser(description="proof-cli studio: editor, PDF + SyncTeX, agent panel, on one folder")
    ap.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                    help="LaTeX project directory (default: current directory)")
    ap.add_argument("--port", type=int, default=8765, help="port (0: any free port)")
    ap.add_argument("--port-tries", type=int, default=1,
                    help="if the port is taken, try this many ports upwards")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    studio = Studio(a.project)
    cfg, root = studio.cfg, studio.root
    if not (root / cfg.main).is_file():
        print(f"studio: warning: main file {cfg.main} not found in {root}", file=sys.stderr)
    try:
        srv = httpbase.listen(type("StudioHandler", (Handler,), {"studio": studio}), a.port, a.port_tries)
    except OSError as e:
        sys.exit(f"studio: {e}")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"studio: {url}\n  project: {root}\n  main:    {cfg.main}\n"
          f"  builds:  {', '.join(cfg.modes)}\n  Ctrl-C to stop", flush=True)
    if cfg.error:
        print(f"  warning: {cfg.error}", flush=True)
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    httpbase.stop_on_signals(srv)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        studio.close()
        httpbase.log("stopped")


if __name__ == "__main__":
    sys.exit(main())


