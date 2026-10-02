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

from ..domain import AgentRole

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


def studio_settings(project_root: Path) -> dict:
    """The `[studio]` table of proof.toml, or {} when there is none or it can't be read."""
    config = project_root / PROJECT_CONFIG
    try:
        table = tomllib.loads(config.read_text(encoding="utf-8")).get("studio", {})
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        return {}
    return table if isinstance(table, dict) else {}


DEFAULT_AGENT_NAMES = {"claude": "claude-code", "codex": "codex"}  # a backend's id, as a run names itself by default


def agent_name(project_root: Path, provider: str) -> str:
    """The name a run claims, splits, requests review and records under (spec #145): `[studio] agent_name`, else the provider's."""
    name = studio_settings(project_root).get("agent_name")
    return name.strip() if isinstance(name, str) and name.strip() else DEFAULT_AGENT_NAMES.get(provider, provider)


def budget(project_root: Path) -> tuple[int, float]:
    """(turns, minutes) one Start may spend (spec #145): `[studio] budget_turns` / `budget_minutes`, else 40 and 60."""
    settings = studio_settings(project_root)
    table = settings.get("budget") if isinstance(settings.get("budget"), dict) else {}
    turns = table.get("turns", settings.get("budget_turns", 40))
    minutes = table.get("minutes", settings.get("budget_minutes", 60))
    return (int(turns) if isinstance(turns, (int, float)) and turns > 0 else 40,
            float(minutes) if isinstance(minutes, (int, float)) and minutes > 0 else 60.0)


def open_command(project_root: Path) -> str | None:
    """The optional `[studio] open_command` of proof.toml (spec #145, decided in #143): how to hand a
    node folder to an editor other than VS Code, with `{folder}` and `{file}` filled in. None means
    the page uses `vscode://file/<folder>`."""
    command = studio_settings(project_root).get("open_command")
    return command.strip() if isinstance(command, str) and command.strip() else None


BRIEF = """\
You are the proof agent on node {node} of a proof map: an automated proof system. You research,
reason and prove; the LaTeX in this folder is where the proof is written down. The researcher
decides every Human Review question (accept, reject, …) on the proof map page; you never do.

Work this way:
1. Retrieval first. Before a new proof search, read what the project holds: `proof search`,
   `proof retrieve`, `proof node show {node} --json`, this node's dependencies (their folders are
   ../<id>/), `proof reference list`, `proof memory list`{library}. Search the literature on the
   web when the project has nothing.
{work}
`proof` acts on the project through $PROOF_ROOT. Change project state only through `proof`, and
change files only in this node's folder: its sources and scratch/, never snapshots/, build/ or
reviews.jsonl.
"""

# the solo agent's own steps (a chat turn outside a run); a run's turn gets a role's section instead
SOLO_BRIEF = """\
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
6. A difficulty you can't state yet goes in the Proof fog, not in the proof: `proof fog add "<text>"
   --near {node} --created-by {name}` (`proof fog list` shows what is there). When you have run a
   computation about a fog item near this node, record it, with its files in scratch/:
   `proof fog experiment record <fog-id> <supports|refutes|inconclusive|error> --summary "<what it
   showed>" --run-by {name} --path proofs/{node}/scratch/<file>`. An Experiment never decides anything.
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


# The three roles of a run (spec #145, decided in #144): each the same CLI with its own brief, write scope and
# `proof` commands. The common brief above still says how the project is read and what `proof` is for; a
# role's section says what this turn is for and what it never does.
_PROOF_READS = ("Bash(proof search *)", "Bash(proof retrieve *)", "Bash(proof node show *)", "Bash(proof node list *)", "Bash(proof reference list *)",
                "Bash(proof memory list *)", "Bash(proof fog list *)", "Bash(proof fog show *)", "Bash(proof node progress *)")
_TEX_PROGRAMS = ("latexmk", "pdflatex", "xelatex", "lualatex", "tectonic", "bibtex", "biber", "kpsewhich")


@dataclass(frozen=True)
class Role:
    """What one role of a run is for, may write, may ask `proof` for, and may run."""

    name: str
    brief: str                      # appended to the common brief, with {node} and {name} filled in
    writes: tuple[str, ...]          # Claude Code's Edit/Write/MultiEdit rules, relative to the node folder
    proof: tuple[str, ...]           # the `proof` commands it may run
    programs: tuple[str, ...]        # the programs it may run besides `proof`
    commands: tuple[str, ...] = ()   # other Bash rules, as Claude Code spells them

    def write_rules(self) -> list[str]:
        return [f"{tool}({pattern})" for pattern in self.writes for tool in ("Edit", "Write", "MultiEdit")]


# Every role's obligations when it stops (spec #145: 停下时写 progress … 说不清的方向 fog add --near), and how it
# says that only the researcher can decide what comes next.
_STOPPING = """\
When you stop — done, stuck, or waiting for the researcher — report it: `--step N --status done|stuck --note "<what
now stands>"`. When a decision only the researcher can make is in the way (a choice of definition, of norm, of which
case to drop), name it and stop: `proof node progress {node} --step N --status needs-human --note "<the decision>"`.
A direction you can't state yet goes in the fog before you stop: `proof fog add "<text>" --near {node} --created-by {name}`.
"""

_ROLE_BRIEFS = {
    "prover": """\
This turn you are the **Prover** of node {node}. You find the proof: retrieval first, then your own
reasoning. Write the proof's structure — its key ideas, its steps and which dependency each uses, the
subclaims it needs — as a Markdown draft in scratch/ (scratch/proof-draft.md); never write proof.tex
yourself, the Typesetter does. You decide when to split the node (`proof node split`) and when its
proof is ready to request review. Report your plan first (`proof node progress {node} --plan "…" --plan "…"`),
then each step as you start and finish it (`--step N --status started|done`). When a step needs
another role, hand it over and end your turn: `proof node progress {node} --handoff typesetter --note
"<what to write>"` or `--handoff numerics --note "<what to compute>"`; the run brings you back after.
""" + _STOPPING,
    "typesetter": """\
This turn you are the **Typesetter** of node {node}. You write the Prover's draft (scratch/proof-draft.md)
as the node's LaTeX — proof.tex and the files it \\input's — compile it and fix what fails, keep the
preamble's conventions, and write the text of key-ideas.md from the draft. You do no mathematics:
never supply a missing step or a missing case yourself; when the draft lacks one, report it and end your turn
(`proof node progress {node} --step N --status done --note "missing: …"`), and the Prover takes it from there.
You never split the node and never request review. Compile without --shell-escape.
""" + _STOPPING,
    "numerics": """\
This turn you are the **Numerics** role of node {node}. You write and run the computations: run.sh is the
entry, scripts beside it, everything they produce in out/. On a computation node that program and its
outputs are the candidate proof itself; on a LaTeX node they are evidence for the Prover. Record every run
you make as an Evidence check once a snapshot exists (`proof node evidence record <candidate-proof-id>
<passed|failed|inconclusive|error> --run-by {name}`), and a computation about a fog item as an Experiment.
Run the program yourself (`./run.sh`, or the interpreter on a script file: `python3 check.py`, never `python3 -c`).
Before a snapshot exists, what a run showed goes in your step's note; once one does, it is an Evidence check.
You never edit the LaTeX. Report your steps with `proof node progress {node}`, and hand back with
`--handoff prover --note "<what the numbers showed>"` when you are done.
""" + _STOPPING,
}
# every role may put an unclear direction in the fog near the node (the stopping duty above)
_EVERY_ROLE = ("Bash(proof fog add *)",)
ROLES: dict[str, Role] = {
    AgentRole.prover.value: Role(
        AgentRole.prover.value, _ROLE_BRIEFS["prover"], ("./scratch/**",),
        (*_PROOF_READS, *_EVERY_ROLE, "Bash(proof node split *)", "Bash(proof node depend *)", "Bash(proof node request-review *)",
         "Bash(proof fog edit *)", "Bash(proof fog drop *)", "Bash(proof fog reopen *)", "Bash(proof fog crystallize *)"),
        COMPUTATION,
    ),
    AgentRole.typesetter.value: Role(
        AgentRole.typesetter.value, _ROLE_BRIEFS["typesetter"], ("./*.tex", "./**/*.tex", "./key-ideas.md"), (*_PROOF_READS, *_EVERY_ROLE), _TEX_PROGRAMS,
    ),
    AgentRole.numerics.value: Role(
        AgentRole.numerics.value, _ROLE_BRIEFS["numerics"],
        ("./run.sh", "./*.py", "./*.sage", "./*.lean", "./*.jl", "./*.r", "./*.txt", "./out/**", "./scratch/**"),
        (*_PROOF_READS, *_EVERY_ROLE, "Bash(proof node evidence record *)", "Bash(proof fog experiment record *)"),
        COMPUTATION, ("Bash(./run.sh)", "Bash(./run.sh *)"),  # its own program; no general shell (ADR-0011)
    ),
}

# The named ways a role's allowed programs give a general shell back, denied (ADR-0011): an interpreter's inline code,
# module or stdin (`python3 -c "…"`, `python3 -m proof_cli …`, `python3 -`, `python3 /dev/stdin`), sage's shells,
# `lake env <cmd>` / `lake exe|run|script`, TeX's shell escape, and latexmk's Perl (`-e`, `-r <rc>`) and engine
# commands (`-pdflatex=<cmd>`). This closes these named escapes only, not every prefix trick: ADR-0010 makes the roles'
# scope a contract for a cooperative agent, not a sandbox, and a role can still run a script it wrote itself.
# A flag ending in "=" takes its value glued on; latexmk's flags are denied wherever they stand in the command line.
_TEX_ENGINES = ("-pdflatex", "-lualatex", "-xelatex", "-latex")
_INLINE = {"python": ("-c", "-m", "-", "/dev/stdin"), "python3": ("-c", "-m", "-", "/dev/stdin"),
           "sage": ("-c", "-m", "-sh", "-python", "-ipython", "-", "/dev/stdin"), "lake": ("env", "exe", "run", "script"),
           "latexmk": ("-e", "-r", *(f"{engine}=" for engine in _TEX_ENGINES), *_TEX_ENGINES, "-shell-escape", "--shell-escape"),
           **{tex: ("-shell-escape", "--shell-escape") for tex in ("pdflatex", "xelatex", "lualatex")}}
_ANYWHERE = ("latexmk",)
# the commands that make a turn a run, for the stuck rule: a computation, a compile, the node's own program
_RUNS = frozenset((*COMPUTATION, *_TEX_PROGRAMS))


def inline_code_rules(programs: tuple[str, ...]) -> list[str]:
    """The Bash rules that deny `programs` their ways back to a general shell (see _INLINE)."""
    rules: list[str] = []
    for program in programs:
        for flag in _INLINE.get(program, ()):
            forms = [f"{flag}*"] if flag.endswith("=") else [flag, f"{flag} *"]
            if program in _ANYWHERE:
                forms += [f"* {form}" for form in forms]
            rules += [f"Bash({program} {form})" for form in forms]
    return rules


def is_a_run(command: str) -> bool:
    """Whether a shell command an agent ran is a run — a computation, a compile, `./run.sh` — rather than a look around."""
    for part in command.replace("&&", ";").replace("||", ";").replace("|", ";").split(";"):
        words = part.split()
        if words and (words[0] in ("./run.sh", "run.sh") or Path(words[0]).name in _RUNS):
            return True
    return False


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
    # a run's turn (spec #145): which role this turn is; None for the researcher's own turn (an Ask)
    role: str | None = None

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
        """The agent's environment: PROOF_ROOT set to the project, `proof` reachable, and in a run the role
        and name `proof node progress` reports under (spec #145)."""
        env = {**os.environ, "PROOF_ROOT": str(self.project_root), "PROOF_AGENT_NAME": self.name}
        if self.role:
            env["PROOF_AGENT_ROLE"] = self.role
        else:
            env.pop("PROOF_AGENT_ROLE", None)
        if shutil.which("proof", path=env.get("PATH")) is None:  # the interpreter running proof-cli has it
            env["PATH"] = os.pathsep.join(filter(None, [env.get("PATH"), str(Path(sys.executable).parent)]))
        return env

    def brief(self) -> str:
        library = "".join(f", {folder}" for folder in self.library)
        work = ROLES[self.role].brief if self.role in ROLES else SOLO_BRIEF
        return BRIEF.format(node=self.node_id, name=self.name, library=f", and the library ({library[2:]})" if library else "",
                            work=work.format(node=self.node_id, name=self.name))

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
        inline: list[str] = []
        if self.role in ROLES:  # a run's turn: the role's `proof` commands, programs and write scope (spec #145)
            role = ROLES[self.role]
            allowed = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", *role.proof, *(f"Bash({command} *)" for command in role.programs), *role.commands]
            inline = inline_code_rules(role.programs)  # a named program, never a shell by another name
            if edit:
                allowed += role.write_rules()
        else:
            allowed = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash(proof *)", *(f"Bash({command} *)" for command in COMPUTATION)]
            if scope_rules:  # the author @-mentioned files: only those may change this turn
                allowed += scope_rules
            elif edit:
                allowed += ["Edit(./**)", "Write(./**)", "MultiEdit(./**)"]
        denied = [f"{tool}(./{path})" for tool in ("Edit", "Write", "MultiEdit") for path in PROTECTED] + inline
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
