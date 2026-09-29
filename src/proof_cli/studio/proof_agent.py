"""The node's proof agent: what the studio's agent panel runs on a proof map node (ADR-0011 point 8, #72).

This is an automated proof system: the agent on a node researches, reasons and proves, and
editing the LaTeX is only how it writes the result down. Only a Human Review decision is beyond
it. It is started in the node's folder with `PROOF_ROOT` set to the project, so every `proof`
call acts on the project.

- It reads the whole project, the library folders the project lists, and the web.
- It runs `proof` (everything agent-reachable) and computation: Python, SageMath, Lean.
- It writes files only in the node's working sources and its scratch folder; project state
  changes only through `proof`.

Its permissions are explicit, never the repository's own CLAUDE.md settings or Bash allowlist.
They are a contract for cooperative local agents, enforced where a backend can (ADR-0010's
threat model), not a sandbox against a hostile one. It runs on the Claude Code or Codex CLI,
which search the web and run commands; the studio has no API-model backend.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_CONFIG = "proof.toml"
# the commands the agent may run besides `proof`: computation in support of its reasoning
COMPUTATION = ("python", "python3", "sage", "lean", "lake", "gp", "maxima", "M2", "magma", "gap")
# a node folder's files no agent writes directly: frozen snapshots, build output, the decisions
PROTECTED = ("snapshots/**", "build/**", "reviews.jsonl")


def library_folders(project_root: Path) -> list[Path]:
    """The read-only library folders `proof.toml` lists (`[studio] library = [...]`): the
    researcher's papers and notes, for the agent to read. Relative paths are the project's."""
    config = project_root / PROJECT_CONFIG
    try:
        listed = tomllib.loads(config.read_text(encoding="utf-8")).get("studio", {}).get("library", [])
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        return []
    folders = []
    for entry in listed if isinstance(listed, list) else []:
        if isinstance(entry, str):
            path = Path(entry).expanduser()
            path = (project_root / path if not path.is_absolute() else path).resolve()
            if path.is_dir():
                folders.append(path)
    return folders


BRIEF = """\
You are the proof agent on node {node} of a proof map: an automated proof system. You research,
reason and prove; the LaTeX in this folder is where the proof is written down. The researcher
decides every Human Review question (accept, reject, …) on the proof map page; you never do.

Work this way:
1. Retrieval first. Before a new proof search, read what the project holds: `proof search`,
   `proof retrieve`, `proof node show {node} --json`, this node's dependencies (their folders are
   ../<id>/), `proof reference list`, `proof memory list`{library}. Search the literature on the
   web when the project has nothing.
2. Reason independently, and check what you can by computation (Python, SageMath, Lean, …),
   keeping scripts and their output in scratch/.
3. Write the proof in proof.tex (and any file it \\input's). If the node is too large to prove
   directly, split it into Claims instead: `proof node split {node} --child <id>=<statement>
   --created-by {name}`. If the proof comes to use another node of the map, add the edge:
   `proof node depend {node} --add <id> --by {name}` (`--remove <id>`, `--move <id> --to <child>`).
4. When the proof is ready, write its key ideas in key-ideas.md (核心思路, 主要步骤, 难点, 未覆盖;
   the review starts from them), then: `proof node request-review {node} --rationale "<why this
   node is scoped to prove directly>" --requested-by {name}`.
5. Record an Evidence check only for a checker you actually ran, with what it reported:
   `proof node evidence record <candidate-proof-id> <outcome> --run-by <checker>`.

`proof` acts on the project through $PROOF_ROOT. Change project state only through `proof`, and
change files only in this node's folder: its sources and scratch/, never snapshots/, build/ or
reviews.jsonl.
"""


KEY_IDEAS_BRIEF = """\
Draft this node's key-ideas summary: create key-ideas.md in this folder ({node}). It is what the
researcher reads first when reviewing the proof, so it must say what the proof in proof.tex
actually does, not what it should do. Read proof.tex (and any file it \\input's) and the
dependencies it rests on: {dependencies}. Don't change the proof, and write no other file.

Write Markdown, with mathematics as $…$, under exactly these four headings:

## 核心思路
One or two sentences: why the result holds. (Required.)

## 主要步骤
3–7 numbered steps, each naming the dependency node it uses, by id. (Required.)

## 难点
Where the proof is most likely to be wrong: what the reviewer should check hardest. Write 「无」 if nothing stands out.

## 未覆盖
Boundary cases, extra assumptions, or parts not yet handled. Write 「无」 if there are none.

If proof.tex has no proof yet, say so under 核心思路 instead of inventing one. The author edits
your draft; requesting review is how they confirm it, and the studio records that you drafted it.
"""


@dataclass
class ProofAgentContext:
    """One node's proof agent: where it runs, what it reads, how it is briefed and permitted."""

    node_id: str
    project_root: Path
    library: list[Path] = field(default_factory=list)
    name: str = "studio-agent"   # the name it claims, splits and requests review under
    dependencies: list[str] = field(default_factory=list)   # the node's, for drafting its key ideas
    # records a key-ideas draft in project state: (agent name, the bytes it wrote); see record_draft
    on_drafted: Callable[[str, bytes], None] | None = None

    def key_ideas_prompt(self) -> str:
        """The turn that drafts a missing key-ideas.md from proof.tex and the dependencies (ADR-0013)."""
        deps = ", ".join(f"{dep} (../{dep}/)" for dep in self.dependencies) or "none (it has no dependencies)"
        return KEY_IDEAS_BRIEF.format(node=self.node_id, dependencies=deps)

    def record_draft(self, path: Path) -> None:
        """After the drafting turn: record in project state that this agent wrote the summary, and
        the SHA-256 of what it wrote, so a review request can tell the agent's draft, as confirmed
        or as edited by the author, from the author's own (ADR-0013). The file itself is untouched."""
        try:
            data = path.read_bytes()
        except OSError:
            return  # nothing was drafted
        if self.on_drafted is not None:
            self.on_drafted(self.name, data)

    def env(self) -> dict[str, str]:
        """The agent's environment: PROOF_ROOT set to the project, and `proof` reachable."""
        env = {**os.environ, "PROOF_ROOT": str(self.project_root)}
        if shutil.which("proof", path=env.get("PATH")) is None:  # the interpreter running proof-cli has it
            env["PATH"] = os.pathsep.join(filter(None, [env.get("PATH"), str(Path(sys.executable).parent)]))
        return env

    def brief(self) -> str:
        library = "".join(f", {folder}" for folder in self.library)
        return BRIEF.format(node=self.node_id, name=self.name, library=f", and the library ({library[2:]})" if library else "")

    def claude_args(self, edit: bool, scope_rules: list[str] | None = None) -> list[str]:
        """Claude Code's permissions: read the project and library, the web, `proof` and computation;
        edit only this folder, never its protected files. `--setting-sources user` keeps the
        repository's own settings and Bash allowlist out."""
        args = [
            "--setting-sources", "user",
            "--permission-prompts", "none",   # nobody can approve here: a call no rule allows is refused
            "--settings", json.dumps({"claudeMdExcludes": self.claude_md_excludes()}),
            "--add-dir", str(self.project_root), *(str(folder) for folder in self.library),
        ]
        allowed = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash(proof *)", *(f"Bash({command} *)" for command in COMPUTATION)]
        if scope_rules:  # the author @-mentioned files: only those may change this turn
            allowed += scope_rules
        elif edit:
            allowed += ["Edit(./**)", "Write(./**)", "MultiEdit(./**)"]
        denied = [f"{tool}(./{path})" for tool in ("Edit", "Write", "MultiEdit") for path in PROTECTED]
        return [*args, "--allowedTools", *allowed, "--disallowedTools", *denied]

    def claude_md_excludes(self) -> list[str]:
        """The memory files Claude Code would otherwise load from the repository: CLAUDE.md,
        CLAUDE.local.md and AGENTS.md in the project, at its root and in every folder above it
        (`--setting-sources` doesn't cover them). The researcher's own ~/.claude/CLAUDE.md stays."""
        names = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")
        root = self.project_root
        inside = [f"{root}/**/{name}" for name in (*names, ".claude/CLAUDE.md")]
        return [f"{folder}/{name}" for folder in (root, *root.parents) for name in names] + inside

    def codex_args(self, sandbox: str) -> tuple[list[str], list[str]]:
        """Codex's (before `exec`, after it): no project AGENTS.md, live web search, the project writable because
        `proof` writes its database and new nodes' folders, and the network for computation.
        Codex can't confine its file writes to this folder: the brief is the contract there."""
        # project_doc_max_bytes=0: none of the repository's AGENTS.md, which Codex would load from
        # the project on its own (PR #79 review); the researcher's ~/.codex/AGENTS.md is separate
        exec_args = ["--sandbox", sandbox, "-c", "project_doc_max_bytes=0"]
        if sandbox == "workspace-write":
            exec_args += ["--add-dir", str(self.project_root), "-c", "sandbox_workspace_write.network_access=true"]
        return ["--search"], exec_args
