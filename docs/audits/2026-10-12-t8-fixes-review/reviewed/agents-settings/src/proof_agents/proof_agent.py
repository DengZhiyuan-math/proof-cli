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
from pathlib import Path, PurePath
from typing import Callable

from proof_cli.domain import AgentRole
from proof_cli.key_ideas import KEY_IDEAS_FILE
from proof_cli.vault import node_folder

PROJECT_CONFIG = "proof.toml"
# the commands the agent may run besides `proof`: computation in support of its reasoning
COMPUTATION = ("python", "python3", "sage", "lean", "lake", "gp", "maxima", "M2", "magma", "gap")
# a node folder's files no agent writes directly: frozen snapshots, build output, the decisions
PROTECTED = ("snapshots/**", "build/**", "reviews.jsonl")


def anchored(rule: str, folder: PurePath) -> str:
    """A file rule `Tool(./pattern)`, written relative to the node folder, tied to that folder by its absolute path
    (`Tool(//abs/folder/pattern)`, Claude Code's form for a path from the filesystem root). Claude Code reads `./`
    against its current directory, which a `cd` in a Bash call moves: a Prover that had `cd`'d to the project root
    was refused its own scratch/ (#132 tier 3), and a Typesetter there would have had `./**/*.tex` over every node."""
    tool, _, rest = rule.partition("(")
    pattern = rest[:-1] if rest.endswith(")") else rest
    if not pattern.startswith("./"):
        return rule
    path = folder.as_posix()
    if len(path) > 1 and path[1] == ":":  # Claude Code normalizes Windows drive paths to /c/...
        path = f"/{path[0].lower()}{path[2:]}"
    return f"{tool}(/{path}/{pattern[2:]})"


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


STUDIO_KEYS = {"library", "agent_name", "budget", "budget_turns", "budget_minutes", "parallel", "open_command"}  # what `[studio]` is read for
STUDIO_HINTS = {  # a key someone might expect to exist, and where that setting really lives
    "claude_config_dir": "the Claude profile is CLAUDE_CONFIG_DIR in the environment of the process serving the page",
}


def unknown_studio_keys(project_root: Path) -> list[dict]:
    """The `[studio]` keys of proof.toml that nothing reads, each {key, message}: a misspelt or
    invented setting is otherwise silently ignored (proof-cli#197, T8 set `claude_config_dir`)."""
    settings = studio_settings(project_root)
    keys = [key for key in settings if key not in STUDIO_KEYS]
    budget_table = settings.get("budget")
    if isinstance(budget_table, dict):
        keys += [f"budget.{key}" for key in budget_table if key not in ("turns", "minutes")]
    return [{"key": key, "message": f"proof.toml [studio] {key} is not a setting and is ignored"
             + (f"; {STUDIO_HINTS[key]}" if key in STUDIO_HINTS else "")
             + f". Settings: {', '.join(sorted(STUDIO_KEYS))}."} for key in keys]


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


def parallel(project_root: Path) -> int:
    """How many node runs a Coordinator keeps going at once (ADR-0019 point 18): `[studio] parallel`, else 2."""
    value = studio_settings(project_root).get("parallel", 2)
    return int(value) if isinstance(value, (int, float)) and value >= 1 else 2


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


# How the Typesetter writes the key-ideas summary (ADR-0013): what the researcher reads first when reviewing.
# Whatever turn writes key-ideas.md, the studio records it as that agent's draft (ProofAgentContext.turn_ended).
KEY_IDEAS_GUIDE = """\
The key-ideas summary, key-ideas.md, is what the researcher reads first when reviewing the proof, so it
must say what the proof in proof.tex actually does, not what it should do: read proof.tex (and any file it
\\input's) and the dependencies it rests on ({dependencies}). Write Markdown, with mathematics as $…$
(display: $$…$$, never a LaTeX environment), under exactly these four headings: `## 核心思路` (one or two sentences: why the result holds; required),
`## 主要步骤` (3–7 numbered steps, each naming the dependency node it uses, by id; required), `## 难点`
(where the proof is most likely to be wrong; 「无」 if nothing stands out) and `## 未覆盖` (boundary cases,
extra assumptions, parts not yet handled; 「无」 if none). If proof.tex has no proof yet, say so under
核心思路 instead of inventing one. The author edits your draft; requesting review is how they confirm
it, and the studio records that you drafted it.
"""


# The roles of a run: Prover, Typesetter and Numerics (spec #145, decided in #144) and the Verifier (ADR-0019 part A),
# each the same CLI with its own brief, write scope and `proof` commands. The common brief above still says how the
# project is read and what `proof` is for; a role's section says what this turn is for and what it never does.
_PROOF_READS = ("Bash(proof search *)", "Bash(proof retrieve *)", "Bash(proof node show *)", "Bash(proof node list *)", "Bash(proof reference list *)",
                "Bash(proof memory list *)", "Bash(proof fog list *)", "Bash(proof fog show *)", "Bash(proof node progress {node} *)",
                "Bash(proof definition list *)", "Bash(proof definition show *)")   # what statements are written in (ADR-0020)
# a rule that names {node} is filled in per turn (ProofAgentContext.claude_args): a role reports, splits and edits the edges of
# its own node and no other (audit P1: an unbound `proof node split *` let a Decomposer take another node over with --reassign)
# the Prover's request-review: given only when the newest verdict passed this version of the inputs (ADR-0019 point 3)
REQUEST_REVIEW = "Bash(proof node request-review *)"  # the general rule no role gets; the gate admits one exact command (ProofAgentContext.request_review_command)
_TEX_LOOKUPS = ("kpsewhich",)   # the Typesetter compiles through the studio's build (its compile tool), not a shell
# TeX's programs that build, for the stuck rule: a compile in a shell is a run (the Typesetter's goes through the
# compile tool). Not kpsewhich: a lookup is not a run, or a turn of lookups would hold off the stuck rule.
_TEX_PROGRAMS = ("latexmk", "pdflatex", "xelatex", "lualatex", "tectonic", "bibtex", "biber")


@dataclass(frozen=True)
class Role:
    """What one role of a run is for, may write, may ask `proof` for, and may run."""

    name: str
    brief: str                      # appended to the common brief, with {node}, {name} and {key_ideas} filled in
    writes: tuple[str, ...]          # Claude Code's Edit/Write/MultiEdit rules, relative to the node folder
    proof: tuple[str, ...]           # the `proof` commands it may run
    programs: tuple[str, ...]        # the programs it may run besides `proof`
    commands: tuple[str, ...] = ()   # other Bash rules, as Claude Code spells them
    alone: bool = False              # started on its own, for one turn, never part of the cycle (the Decomposer, ADR-0019 point 20)

    def write_rules(self) -> list[str]:
        return [f"{tool}({pattern})" for pattern in self.writes for tool in ("Edit", "Write", "MultiEdit")]


# A judgement call is made and recorded, not asked (ADR-0021 point 8): the researcher answers it later, from the review
# queue, and nothing waits for them meanwhile.
_CHOICES = """\
A judgement call is not a reason to stop. Where the statement admits two readings, a constant is left unspecified or a
case split is a matter of judgement, pick the reading the draft most likely means, record it as a Standing question —
`proof node progress {node} --question "<the choice made; the alternative>"` — and go on. The researcher answers it later;
an answer that differs comes back to this node as a redirect. Do not record the same choice twice.
"""
# Every role's obligations when it stops (spec #145: 停下时写 progress … 说不清的方向 fog add --near), and the one thing
# that still stops a node for the researcher (ADR-0021 point 8).
_STOPPING = """\
When you stop — done or stuck — report it: `--step N --status done|stuck --note "<what now stands>"`.
""" + _CHOICES + """\
`needs-human` is only for what no reading settles: a contradiction in this node's own statement, or a fact only the
researcher can know. Then name it and stop: `proof node progress {node} --step N --status needs-human --note "<it>"`.
It stops this node, not the rest of the map.
A direction you can't state yet goes in the fog before you stop: `proof fog add "<text>" --near {node} --created-by {name}`.
"""

# The Decomposer's brief: what it is for and how it splits, then how its turn ends — started alone, for the researcher
# (ADR-0019 point 20); under Pursue, PURSUE_DECOMPOSER instead (ADR-0021 point 7), never both.
_DECOMPOSER = """\
This turn you are the **Decomposer** of node {node} (ADR-0019 point 20): a Theorem not yet split, whose proof is
a research effort rather than one argument. You do not prove it. Read the library and the literature first —
`proof search`, `proof retrieve`, `proof reference list`, `proof memory list`, the library folders, the web —
then write the key theorems the course of the proof needs as a split into Claims, each a statement a run could
prove on its own, in one call (a split is all or nothing):
`proof node split {node} --child <id>=<statement> --child <id>=<statement> … --created-by {name}`.
Every Claim is written in the Theorem's definitions (your briefing gives them; ADR-0020) and names them without being
told: state each in their terms so it reads on its own, and never as "in the setting of {node}". A Claim that needs
notation the definitions lack says what it means in its own statement; a definition worth adding is the researcher's
to add — name it, with its text, in your closing note.
Keep your reading notes and the reasons for the structure in scratch/decomposer/. A split makes {node} rest
on every Claim, and each Claim on nothing. What you cannot yet state as a Claim goes in the fog near the Theorem:
`proof fog add "<text>" --near {node} --created-by {name}`. Report your plan first (`proof node progress {node} --plan "…"`).
If you find the Theorem is one argument after all, say so instead (`--step 1 --status done --note "no split: …"`) and
split nothing.
"""
_DECOMPOSER_ALONE = """\
When one Claim uses another, say so for the researcher, who adds the edge — in scratch/decomposer/ and in your closing
note, as the command to copy: `proof node depend <claim> --add <claim it uses> --by human`. You never write proof.tex,
never request review, never add or remove a dependency edge, and never start anything. The shape of a whole research
effort is a decision only the researcher can make: end your turn with
`proof node progress {node} --step 1 --status needs-human --note "structure proposed; the researcher decides; edges: proof node depend <claim> --add <claim it uses> --by human; …"`
(with no edge to name, the note ends after decides, unless a definition is proposed; a definition to add comes last, after the edges or after decides, as `definition <name>: <text>`) — they read the Claims on the map, edit them, and start a Coordinator if they agree.
"""

_ROLE_BRIEFS = {
    "prover": """\
This turn you are the **Prover** of node {node}. You find the proof: retrieval first, then your own
reasoning. Write the proof's structure — its key ideas, its steps and which dependency each uses, the
subclaims it needs — as a Markdown draft in scratch/ (scratch/proof-draft.md); never write proof.tex
or key-ideas.md yourself, the Typesetter writes both from your draft. You decide when to split the node (`proof node split`). Report your plan
first (`proof node progress {node} --plan "…" --plan "…"`), then each step as you start and finish it
(`--step N --status started|done`). When a step needs another role, hand it over and end your turn:
`proof node progress {node} --handoff typesetter --note "<what to write>"` or `--handoff numerics --note
"<what to compute>"`; the run brings you back after. When you abandon a line, close it so no later turn
walks it again: `proof node progress {node} --attempt "<what it was to establish>" --method "<how>"
--failed-on "<the objection or obstruction>"`. When you believe the draft is complete and written down,
hand it to the Verifier: `--handoff verifier --note "<what to read it against>"`; it reads the proof
against you and records a verdict. Only after the Verifier passed this very version of the files may
you request review (`proof node request-review {node} --rationale "<why this node is scoped to prove
directly>" --requested-by {name}`); a failed verdict's objections come back to you, each to be settled
or refuted. {gate}
What you learn, as against what you try, goes to memory, scoped to this node and under your name
(ADR-0019 point 8): a dead end that would mislead another node, `{memory} --layer episodic --status failed
--source {name}/prover "<it>"` (this project and node first, once: that is the form you are allowed); a
technique that worked, `--layer procedural --status tactic`; an observation not yet trusted, `--layer
semantic --status tentative`. Other nodes'
runs are briefed from these, and you from theirs (the briefing's shared notes; `proof memory list
--node-id <id>` reads more), each unverified: a result you need from another node is a Claim both
depend on (`proof node depend`), never a sentence copied from its proof, and you write no other
node's memory. When you split out a Claim a sibling could use, leave a memory entry saying so; its
Prover adds the edge, or does not.
A dependency the briefing marks Provisional (ADR-0021 point 3) may be used by its statement, as an Accepted one's is; its
proof never — read none of it as a fact. For an imported result not yet Reference-reviewed, use what the cited source
actually gives, and say in your draft where you rely on it.
When a dependency this proof rests on may no longer hold, open a Challenge on it (ADR-0005):
`proof challenge open <dependency-id> --rationale "<why>" --opened-by {name}`. Dismissing or resolving a
Challenge is the researcher's alone: you never do either.
""" + _STOPPING,
    "typesetter": """\
This turn you are the **Typesetter** of node {node}. You write the Prover's draft (scratch/proof-draft.md)
as the node's LaTeX — proof.tex and the files it \\input's — compile it with the `compile` tool (the
studio's own build, whose PDF and problems the researcher sees; never pdflatex or latexmk yourself) and fix
what fails, keep the preamble's conventions, and write the text of key-ideas.md from the draft. You do no mathematics:
never supply a missing step or a missing case yourself; when the draft lacks one, report it and end your turn
(`proof node progress {node} --step N --status done --note "missing: …"`), and the Prover takes it from there.
You never split the node and never request review. In the .tex files display math is a named environment;
in key-ideas.md it is $$…$$ and inline math $…$. The Verifier reads what you write — the .tex files, not the
draft — so write every step the draft has, and nothing it hasn't.
{key_ideas}""" + _STOPPING,
    "verifier": """\
This turn you are the **Verifier** of node {node} (ADR-0019). The mechanical checks — the proof builds cleanly, key-ideas.md
has its four headings, the statement is the node's — are done by the run before your turn and reported in your briefing,
with the files themselves: do not redo them, and do not spend the turn on `ls`, `cat` or the build log. Your work is
the mathematics. You read the node's working proof as it stands —
proof.tex and the files it \\input's, or on a computation node run.sh, its scripts and out/ — against the
node's statement and its dependencies' statements, adversarially: every step is unjustified until the text
or a dependency it names justifies it; every appeal to a dependency is wrong until that dependency's
statement actually gives it (its proof is not yours to rely on); every appeal to the literature is unchecked
until you have read it. You do no mathematics of your own beyond what checking requires; you may run a
computation to check a claim, keeping its files under scratch/verifier/. You write no other file. Then record
your verdict, which is about this exact state of the files: `proof node progress {node} --verdict passed --note
"<what you checked and why it holds>"` when every step holds — the note is the reviewer's evidence, so name what you
read and checked, and any fact the proof takes as background — or `--verdict failed --note "1. <the step or citation
it attacks: why> 2. …"`, the objections numbered, each naming the step or the citation it attacks. A failed verdict goes back to the Prover
with your objections; a passing one is the Prover's gate to request review. An objection you cannot settle
because it concerns an Accepted dependency's own proof is a Challenge: `proof challenge open <dependency-id>
--rationale "<why>" --opened-by {name}`. A sibling's or a dependency's unaccepted proof justifies nothing: an
appeal to it is an appeal to nothing (ADR-0019 point 11). A dependency the briefing marks Provisional may be
appealed to by its statement, as an Accepted one's (ADR-0021 point 3); its proof never. For an imported result not yet
Reference-reviewed, read the cited source and check the appeal against it; if you cannot read it, say so in your verdict's
note — the appeal is "unchecked against the source" — which the researcher sees at its Reference review. An obstruction you find that would mislead another
node — a step the proof keeps failing on, a cited result that does not give what is claimed — goes to memory
under this node and your name: `{memory} --layer episodic --status failed --source {name}/verifier "<it>"`
(this project and node first, once: that is the form you are allowed); you write no other node's memory. You never split the node, never request review, and never make a
Review decision. When a step of yours is done, report it (`--step N --status done`); the verdict ends your turn.
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
    "decomposer": _DECOMPOSER + _DECOMPOSER_ALONE + _CHOICES,
}
# every role may put an unclear direction in the fog near the node (the stopping duty above)
_EVERY_ROLE = ("Bash(proof fog add *)",)
# each role's `proof` commands, as a sheet to copy (issue #180); {node}, {name} and {memory} are filled in per turn
_COMMON_COMMANDS = (
    'proof node progress {node} --plan "<step 1>" --plan "<step 2>" …',
    'proof node progress {node} --step <N> --status started|done|stuck|needs-human --note "<what now stands>"',
    'proof node progress {node} --question "<the choice made; the alternative>"   (a judgement call: record it and go on)',
    'proof fog add "<the difficulty>" --near {node} --created-by {name}',
)
COMMANDS: dict[str, tuple[str, ...]] = {
    "prover": (*_COMMON_COMMANDS,
               'proof node progress {node} --handoff typesetter|numerics|verifier --note "<what to do / to read against>"',
               'proof node progress {node} --attempt "<what it was to establish>" --method "<how>" --failed-on "<the obstruction>"',
               'proof node split {node} --child <id>=<statement> --child <id>=<statement> --created-by {name}',
               'proof node depend {node} --add <id> --by {name}   (or --remove <id> | --move <id> --to <child>)',
               '{memory} --layer episodic|procedural|semantic --status failed|tactic|tentative --source {name}/prover "<what was learned>"',
               'proof challenge open <dependency-id> --rationale "<why>" --opened-by {name}',
               'proof node request-review {node} --gated-by <the passing verdict\'s digest> --rationale "<why it is scoped>" --requested-by {name}   (only when the briefing says the gate is open)'),
    "typesetter": (*_COMMON_COMMANDS,
                   'proof node progress {node} --step <N> --status done --note "missing: <the step the draft lacks>"   (and end the turn: the Prover takes it)'),
    "verifier": (*_COMMON_COMMANDS,
                 'proof node progress {node} --verdict passed --note "<what you checked and why it holds>"',
                 'proof node progress {node} --verdict failed --note "1. <step or citation>: <why it fails> 2. …"',
                 '{memory} --layer episodic --status failed --source {name}/verifier "<the obstruction>"',
                 'proof challenge open <dependency-id> --rationale "<why>" --opened-by {name}'),
    "numerics": (*_COMMON_COMMANDS,
                 'proof node progress {node} --handoff prover --note "<what the numbers showed>"',
                 'proof node evidence record <candidate-proof-id> passed|failed|inconclusive|error --run-by {name}',
                 'proof fog experiment record <fog-id> supports|refutes|inconclusive|error --summary "<what it showed>" --run-by {name} --path proofs/{node}/scratch/<file>'),
    "decomposer": (*_COMMON_COMMANDS,
                   'proof node split {node} --child <id>=<statement> --child <id>=<statement> --created-by {name}',
                   'proof node progress {node} --step 1 --status needs-human --note "structure proposed; the researcher decides; edges: proof node depend <claim> --add <claim it uses> --by human; …"'),
}
# what a role learned goes to its own node's memory and no other's (ADR-0019 point 12): the rule names the project (by
# instance id) and the node, filled in per turn (ProofAgentContext.memory_command); Typer takes the options before the
# entry, so the prefix is the rule, and `proof memory add` refuses a second --project or --node-id, and a --project that
# is not the project --root opens, so the rest of the command can name no other project or node (audits P1, re-audit P1)
MEMORY_WRITE = "Bash({memory} *)"
# denied to every role: `--root` on any `proof` command, wherever it stands — the project is $PROOF_ROOT and no other
NO_OTHER_PROJECT = ("Bash(proof * --root *)", "Bash(proof * --root=*)")
ROLES: dict[str, Role] = {
    AgentRole.prover.value: Role(  # request-review is not here: the gate adds it when the newest verdict passed this version (ADR-0019 point 3)
        AgentRole.prover.value, _ROLE_BRIEFS["prover"], ("./scratch/**",),
        (*_PROOF_READS, *_EVERY_ROLE, MEMORY_WRITE, "Bash(proof node split {node} *)", "Bash(proof node depend {node} *)", "Bash(proof challenge open *)",
         "Bash(proof fog edit *)", "Bash(proof fog drop *)", "Bash(proof fog reopen *)", "Bash(proof fog crystallize *)"),
        COMPUTATION,
    ),
    AgentRole.verifier.value: Role(  # ADR-0019 point 1: reads, checks, records a verdict; writes only under scratch/verifier/
        AgentRole.verifier.value, _ROLE_BRIEFS["verifier"], ("./scratch/verifier/**",),
        (*_PROOF_READS, *_EVERY_ROLE, MEMORY_WRITE, "Bash(proof challenge open *)"),
        COMPUTATION,
    ),
    AgentRole.typesetter.value: Role(
        AgentRole.typesetter.value, _ROLE_BRIEFS["typesetter"], ("./*.tex", "./**/*.tex", "./key-ideas.md"), (*_PROOF_READS, *_EVERY_ROLE), _TEX_LOOKUPS,
    ),
    AgentRole.numerics.value: Role(
        AgentRole.numerics.value, _ROLE_BRIEFS["numerics"],
        ("./run.sh", "./*.py", "./*.sage", "./*.lean", "./*.jl", "./*.r", "./*.txt", "./out/**", "./scratch/**"),
        (*_PROOF_READS, *_EVERY_ROLE, "Bash(proof node evidence record *)", "Bash(proof fog experiment record *)"),
        COMPUTATION, ("Bash(./run.sh)", "Bash(./run.sh *)"),  # its own program; no general shell (ADR-0011)
    ),
    AgentRole.decomposer.value: Role(  # ADR-0019 point 20: reads, splits, puts the rest in the fog, stops for the researcher; no program, no cycle
        AgentRole.decomposer.value, _ROLE_BRIEFS["decomposer"], ("./scratch/decomposer/**",),
        (*_PROOF_READS, *_EVERY_ROLE, "Bash(proof node split {node} *)"),
        (), alone=True,
    ),
}
# A Decomposer started by a Coordinator's Pursue (ADR-0021 point 7): its split is the structure worked next, so it adds the
# edges between its own Claims itself and does not stop for the researcher. Appended to its brief; it overrides the ending.
PURSUE_DECOMPOSER = """\
**Under Pursue** (this turn was started by a Coordinator): the researcher reads the structure later, so you do not
stop for them. You never write proof.tex, never request review and never start anything, and the only dependency edges
you change are these, each one call:
- when one of your Claims uses another, add the edge yourself: `proof node depend <claim> --add <claim it uses> --by {name}`
  (between Claims your own split of {node} created, while both are unaccepted);
- when this turn was started because a Claim of {node} is parked (the redirect names it), split {node} again with the
  Claims that replace it, then drop {node}'s edge to the parked Claim: `proof node depend {node} --remove <the parked Claim> --by {name}`
  (only a Claim your own split created, still unaccepted). The parked Claim stays on the map, with its attempts, for
  the researcher; nothing is deleted.
Where the structure is a judgement call, pick the likeliest and record it as a standing question:
`proof node progress {node} --question "<the structure chosen; the alternative>"`. End your turn with
`proof node progress {node} --step 1 --status done --note "split into <the Claims>; edges: <the edges you added or dropped>"`.
`needs-human` is only for a contradiction in {node}'s own statement or a fact only the researcher knows.
"""
PURSUE_DECOMPOSER_COMMANDS = (
    'proof node depend <claim> --add <claim it uses> --by {name}',
    'proof node depend {node} --remove <the parked Claim> --by {name}   (a further turn, for a parked Claim of your own split)',
    'proof node progress {node} --question "<the structure chosen; the alternative>"',
    'proof node progress {node} --step 1 --status done --note "split into <the Claims>; edges: <the edges you added or dropped>"',
)
_DECOMPOSER_ENDING = 'proof node progress {node} --step 1 --status needs-human'   # the sheet's line for the ending only the alone Decomposer has

# the roles a whole run cycles through, in the spec's order: every role with a brief but one started alone (the Decomposer)
CYCLE_ROLES = tuple(role.value for role in AgentRole if role.value in ROLES and not ROLES[role.value].alone)

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


def claude_md_excludes(project_root: Path) -> list[str]:
    """The memory files Claude Code would otherwise load from the repository: CLAUDE.md, CLAUDE.local.md and AGENTS.md
    in the project, at its root and in every folder above it (`--setting-sources` doesn't cover them). The researcher's
    own ~/.claude/CLAUDE.md stays."""
    names = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")
    inside = [f"{project_root}/**/{name}" for name in (*names, ".claude/CLAUDE.md")]
    return [f"{folder}/{name}" for folder in (project_root, *project_root.parents) for name in names] + inside


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
    # the Prover's gate (ADR-0019 point 3): set by the run when the newest verdict passed and its hash is the working
    # inputs' now; only then does the turn get `proof node request-review` (Claude Code), and the brief says so (Codex)
    review_gate: str | None = None   # the passing verdict's digest this Prover turn may request review against (ADR-0019 point 3); None: it may not
    # the project's instance id (proof_cli.storage.read_project_instance_id), from the host: what binds a role's memory
    # writes to this project, so `--root <another project>` after the allowed prefix is refused by `proof` itself
    project_id: str | None = None
    # a Coordinator's Pursue started this turn (ADR-0021 point 7): a Decomposer adds its own Claims' edges and does not stop
    pursue: bool = False

    @property
    def compiles(self) -> bool:
        """Whether this turn may compile through the studio's build: the Typesetter's, and the solo agent's (an edit
        turn of the researcher's own); the Prover writes its draft and Numerics its program, neither typesets."""
        return self.role in (None, AgentRole.typesetter.value)

    def key_ideas_guide(self) -> str:
        """How key-ideas.md is written (ADR-0013), naming this node's dependencies as of this turn."""
        deps = ", ".join(f"{dep} (../{dep}/)" for dep in self.dependencies) or "none: it has no dependencies"
        return KEY_IDEAS_GUIDE.format(dependencies=deps)

    def turn_ended(self, root: Path, changed: list[str]) -> None:
        """After an agent turn (agent.py): when it wrote key-ideas.md, record it as this agent's draft — a run's
        role or a one-off task alike (ADR-0013). Without that record, an agent's summary would read as the author's."""
        if KEY_IDEAS_FILE in changed:
            self.record_draft(Path(root) / KEY_IDEAS_FILE)

    def record_draft(self, path: Path) -> None:
        """Record in project state that this agent wrote the summary, and the SHA-256 of what it left, so a
        review request can tell the agent's draft, as confirmed or as edited by the author, from the author's
        own (ADR-0013). The file itself is untouched."""
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
        # a `cd` in one Bash call does not carry to the next (Claude Code): the folder the brief's relative paths
        # name stays the folder the turn works in (#132 tier 3)
        env["CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"] = "1"
        if self.role:
            env["PROOF_AGENT_ROLE"] = self.role
        else:
            env.pop("PROOF_AGENT_ROLE", None)
        if shutil.which("proof", path=env.get("PATH")) is None:  # the interpreter running proof-cli has it
            env["PATH"] = os.pathsep.join(filter(None, [env.get("PATH"), str(Path(sys.executable).parent)]))
        return env

    @property
    def may_request_review(self) -> bool:
        return bool(self.review_gate)

    def __post_init__(self) -> None:
        if self.role is not None and self.role not in ROLES:  # a role with no brief takes no turn
            raise ValueError(f"no brief for the {self.role} role: it cannot take a turn")

    def request_review_command(self) -> str:
        """The one request-review the gate admits: this node, this verdict's digest, so an edit since is refused by `proof` itself."""
        return f"proof node request-review {self.node_id} --gated-by {self.review_gate}"

    def memory_command(self) -> str:
        """The one form of `proof memory add` a role is allowed: this project (when the host named it) and this node, first and once."""
        project = f" --project {self.project_id}" if self.project_id else ""
        return f"proof memory add{project} --node-id {self.node_id}"

    def gate_text(self) -> str:
        """What the Prover is told about requesting review this turn (ADR-0019 point 3), the same on every backend."""
        if self.may_request_review:
            return (f"The Verifier passed the files as they stand now: you may request review this turn, with exactly "
                    f"`{self.request_review_command()} --rationale \"<why it is scoped>\" --requested-by {self.name}` — "
                    "and only if nothing changed since; `proof` refuses the request (VERDICT_STALE) otherwise.")
        return ("The Verifier has not passed the files as they stand now (no verdict, a failed one, or one of an earlier version): "
                "you may not request review this turn; hand to the Verifier when the draft is complete.")

    def brief(self) -> str:
        library = "".join(f", {folder}" for folder in self.library)
        work = ROLES[self.role].brief if self.role in ROLES else SOLO_BRIEF
        if self._pursued_decomposer:  # its own ending, in place of the one that stops for the researcher (ADR-0021 point 7)
            work = _DECOMPOSER + PURSUE_DECOMPOSER + _CHOICES
        text = BRIEF.format(node=self.node_id, name=self.name, library=f", and the library ({library[2:]})" if library else "",
                            work=work.format(node=self.node_id, name=self.name, key_ideas=self.key_ideas_guide(), gate=self.gate_text(), memory=self.memory_command()))
        return text + self.commands_sheet()

    @property
    def _pursued_decomposer(self) -> bool:
        return self.pursue and self.role == AgentRole.decomposer.value

    def commands_sheet(self) -> str:
        """The exact `proof` commands this role uses, filled in for this node and name, to copy rather than to look up with
        `--help` (issue #180: a turn spent on `proof node progress --help` is a turn not spent on the proof)."""
        if self.role not in COMMANDS:
            return ""
        own = COMMANDS[self.role]
        if self._pursued_decomposer:
            own = (*(line for line in own if not line.startswith(_DECOMPOSER_ENDING)), *PURSUE_DECOMPOSER_COMMANDS)
        lines = [line.format(node=self.node_id, name=self.name, memory=self.memory_command()) for line in own]
        return ("\nCommands you will use, exactly (no need for --help). Run each as its own Bash call: one joined with &&, ;, | or a "
                "loop is refused, whatever its parts (#132 tier 3):\n" + "\n".join(f"  {line}" for line in lines) + "\n")

    def claude_args(self, edit: bool, scope_rules: list[str] | None = None, tools: list[str] | tuple[str, ...] = ()) -> list[str]:
        """Claude Code's permissions: read the project and library, the web, `proof` and computation;
        edit only this folder, never its protected files; `tools`, the studio's own tools for this turn
        (its compile tool). `--setting-sources user` keeps the repository's own settings and Bash allowlist out."""
        args = [
            "--setting-sources", "user",
            "--permission-prompts", "none",   # nobody can approve here: a call no rule allows is refused
            "--settings", json.dumps({"claudeMdExcludes": self.claude_md_excludes()}),
            "--add-dir", str(self.project_root), *(str(folder) for folder in self.library),
        ]
        folder = node_folder(self.project_root, self.node_id).resolve()
        inline: list[str] = []
        if self.role in ROLES:  # a run's turn: the role's `proof` commands, programs and write scope (spec #145)
            role = ROLES[self.role]
            proof_rules = [rule.replace("{memory}", self.memory_command()).replace("{node}", self.node_id) for rule in role.proof]  # this project, this node
            allowed = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", *proof_rules, *(f"Bash({command} *)" for command in role.programs), *role.commands]
            if self.role == AgentRole.prover.value and self.may_request_review:  # the gate (ADR-0019 point 3): this node, this verdict, nothing else
                allowed.append(f"Bash({self.request_review_command()} *)")
            if self._pursued_decomposer:  # its own Claims' edges, under its own name (ADR-0021 point 7), and on a further turn the
                # parent's edge to its own parked Claim (point 9); `proof` refuses any other pair. Its --question is `progress {node} *`'s
                allowed += [f"Bash(proof node depend * --add * --by {self.name})", f"Bash(proof node depend {self.node_id} --remove * --by {self.name})"]
            inline = inline_code_rules(role.programs)  # a named program, never a shell by another name
            if edit:
                allowed += [anchored(rule, folder) for rule in role.write_rules()]
        else:
            allowed = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash(proof *)", *(f"Bash({command} *)" for command in COMPUTATION)]
            if scope_rules:  # the author @-mentioned files: only those may change this turn
                allowed += [anchored(rule, folder) for rule in scope_rules]
            elif edit:
                allowed += [anchored(rule, folder) for rule in ("Edit(./**)", "Write(./**)", "MultiEdit(./**)")]
        allowed += list(tools)
        denied = [anchored(f"{tool}(./{path})", folder) for tool in ("Edit", "Write", "MultiEdit") for path in PROTECTED] + inline
        if self.role in ROLES:  # PROOF_ROOT names the project: no role sends a `proof` command to another one (audit P1)
            denied += list(NO_OTHER_PROJECT)
        if self._pursued_decomposer:  # an edge is added as itself, never by taking a node over
            denied.append("Bash(proof node depend * --reassign*)")
        return [*args, "--allowedTools", *allowed, "--disallowedTools", *denied]

    def claude_md_excludes(self) -> list[str]:
        return claude_md_excludes(self.project_root)

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
