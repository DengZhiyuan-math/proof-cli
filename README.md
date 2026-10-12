# Mathematical Proof CLI

Mathematical Proof CLI is a local-first research proof operating system for human–machine collaboration. A project is a proof map: nodes (theorems, lemmas, claims, and imported results) joined by their dependencies. Each local node has its own LaTeX proof, and the researcher accepts or rejects it on the proof map page. Agents claim nodes from the frontier, split nodes that are too large, and request review. Every decision stays explicit and auditable in git. What can be called is answered only by the proof map's nodes: an Accepted theorem, lemma or claim, or an imported result with a Reference review (ADR-0012). The `theorem`, `obligation`, `blocker`, `goal` and `verify` command groups come from the model before the proof map, and `proof --help` lists them under Legacy. Their callable, trust and review states are marked as legacy, not a trust source; a reference is only a citation.

The project is designed to support rigorous research workflows without replacing the mathematician or attempting to provide a full formal kernel. Final acceptance remains with the researcher.

## Requirements

- Python 3.11 or newer

## Install for development

proof-cli is one of four packages (ADR-0018). This repository holds **proof-cli**, the core and the `proof` CLI, and under `packages/`, **latex-agent**, the LaTeX studio taken from prism-local (editor, build, PDF, agent panel). The other two have repositories of their own in the zeqome organisation: [**proof-agents**](https://github.com/zeqome/proof-agents), the Proof agent's roles and its run, and [**proof-web**](https://github.com/zeqome/proof-web), the Home, the proof map page and each node's page, which serves the other three. `proof` works with the core alone; `proof home` and `proof map open` need proof-web, and say so until it is installed.

```bash
python -m pip install -e ".[dev]" -e packages/latex-agent                           # this repository
python -m pip install "git+https://github.com/zeqome/proof-agents.git" "git+https://github.com/zeqome/proof-web.git"
pytest                                                                               # the core's and latex-agent's tests
```

For development, check the two out beside this folder and `pip install -e` them instead.

## Command-line entry point

The researcher's entry is the web app: `proof home` opens the **Home**, the list of your proof projects, and a project opens in its **proof map page** (`proof map open` in a project's folder goes straight there; both below). `proof` is the agents' interface, with `--json` for one envelope per call:

```bash
proof --help
proof frontier
proof node show <id>
proof trust-rule list   # the Trust rules in force (read-only; declared on the page)
proof fog list          # the Proof fog: difficulties not yet precise enough to be a Claim
proof node create C3 claim "For every n ≤ 10^4 …" --medium computation   # a node established by a program: run.sh, outputs in out/
# A node's studio opens on the agent's Work log: its plan, role and step, the oversight actions (Start, Pause,
# Redirect, Resume, Stop and release, Review what it has) and what it did; the editor and PDF — or a computation's
# program and out/ — sit behind the Files tab; the Ask box only puts read-only questions to the agent.
# The Proof agent works a node on its own once started (from the map, the node page or the studio): a run of three
# roles — Prover, Typesetter, Numerics — that reports its plan and steps (`proof node progress`), stops for a review
# request, a decision, its budget or when stuck, and that you pause, redirect, resume or release. In proof.toml:
#   [studio]
#   agent_name = "claude-code"      # the name the run claims and records under (default: the provider's)
#   budget_turns = 40               # per Start; budget_minutes = 60
proof node progress N              # the node's work log: what the agent planned, did, handed over
proof node answer N <question> --keep | --answer "<the reading to follow>"
                                   # a Standing question: a choice a role made instead of stopping (`node progress --question`);
                                   # an answer that differs is a redirect for the node's next run (ADR-0021)
proof node check N                 # the mechanical checks of its working proof: builds cleanly, key-ideas.md's four headings, the statement
                                   # is the node's, \input's stay in the folder, each dependency is mentioned. Findings, not refusals: a run
                                   # sends the work back on an error before the Verifier reads; the researcher's request-review is never stopped
# In a computation node's studio, Run executes run.sh (its exit code is an Evidence check on the current snapshot:
# 0 passed, otherwise failed — recorded only when the run completes with the snapshot's frozen inputs, untouched;
# see ADR-0015; a checker recording one by hand names the snapshot it ran on with
# `proof node evidence record <proof> <outcome> --snapshot-sha256 <sha>` — refused unless it is that snapshot's
# hash now; with no flag the check binds the snapshot as it is at the moment of recording, and a snapshot that
# can't be read takes no check, SNAPSHOT_UNREADABLE). run.sh runs as you, with your full environment, and can write anywhere you can (ADR-0010's
# cooperative model, not a sandbox); the page keeps the last 8 MB of its output.
# Open in VS Code hands the folder to the editor — vscode://file/<folder>, or the command proof.toml names:
#   [studio]
#   open_command = "code {folder}"     # {folder} and {file} are filled in; run by the page's server
```

Every command acts on `--root`, else `$PROOF_ROOT`, else the current folder. An agent working inside a node's folder, like the studio's agent panel, keeps `PROOF_ROOT` set to the project root.

## Writing a proof

Each local proof map node has a standalone LaTeX document, `proofs/<id>/proof.tex`, created with the node. It `\input`s the project's shared `proofs/preamble.tex` and compiles on its own. The researcher edits it in the node's studio on the proof map page (below); agents edit it directly. The folder `proofs/<id>/` is still an ordinary LaTeX project that any editor can open.

Beside it sits the proof's key-ideas summary, `proofs/<id>/key-ideas.md` (ADR-0013). It is Markdown, with maths as `$…$`, under four headings: **核心思路** (why it holds) and **主要步骤** (3–7 steps, each naming the dependency it uses) are required; **难点** (where it is most likely wrong) and **未覆盖** (what it leaves out) may be 「无」. Review starts from it. When it is missing, the Typesetter drafts it from `proof.tex` and the dependencies (the studio's "+" → *Ask the agent to…* → *Typesetter · draft key ideas*, or a run's own turn); any agent turn that writes it is recorded as the agent's draft; you edit it, and requesting review confirms it.

When the proof and its summary are ready, request review from the studio's node panel, or:

```bash
proof node request-review <id> --rationale "why it is scoped to prove directly"
```

A request without `key-ideas.md`, or with 核心思路 or 主要步骤 empty, is refused with `KEY_IDEAS_REQUIRED`. Otherwise it freezes every input of the proof into an immutable snapshot, `proofs/<id>/snapshots/v<N>/`: the node's working sources (not `build/`, `scratch/` or older snapshots), its key-ideas summary and the shared preamble, with a `manifest.json` of each file's SHA-256. The snapshot's SHA-256, which decisions bind, is that of the manifest, so a change to any input, an `\input` file, a preamble macro or the summary alone included, is a new version to review. Review is always of a snapshot, never of the working files (ADR-0010, ADR-0011). The researcher reviews it in the node's studio: the review view shows the snapshot's key ideas and records the decisions, and links to the node's page for the frozen LaTeX and the archived PDF (ADR-0013). A snapshot from before summaries existed is reviewed as before, and says it has none.

A snapshot, and an exchange export (`proof exchange export`), never freeze or carry secrets (`.env`, `.env.*`, `.envrc`, `.netrc`), hidden folders, or dotfiles other than a computation's allowlisted environment files (`.python-version`, `.tool-versions`, `.nvmrc`, `.node-version`, `.ruby-version`). Requesting review lists what it left out, by path only (ADR-0015). **Neither follows a symbolic link. This is a deliberate change: an export used to skip links silently.** An export now fails as a whole with `NODE_FOLDER_SYMLINK` if any node folder holds a link outside `scratch/`, `build/` and hidden folders, and the error names each link, dangling ones included. Replace each link with a copy of its target (`cp --remove-destination "$(readlink <link>)" <link>`), or move it into `scratch/`, then export again.

## The Home

`proof home` opens the Home (ADR-0017), the web app's first page: your proof projects, each a card read live from its own folder — its id, its theorem, how many nodes, how many on the frontier, how many await you, how many are accepted, the open fog, whether its page is running, when you last opened it. Opening a card starts that project's proof map page (on the project's own localhost port, as before) and takes you there; the page's sidebar links back to the Home. **Add existing…** lists a folder that already holds a project, **New project…** starts one exactly as `proof init` does, and **Forget** drops a project from the list without touching its folder. The list is `projects.json` in the proof-cli config directory (`$PROOF_CLI_CONFIG_HOME`, else `$XDG_CONFIG_HOME/proof-cli`, else `~/.config/proof-cli`); `proof init` and `proof map open` keep it up to date, and nothing scans your disk. `proof home --foreground` runs it in the terminal.

## The proof map page

`proof map open` (in a project's folder, or with `--root`) opens the project's local page, bound to 127.0.0.1 on the project's own port — through the Home, started if need be, so the page links back to it:
- **The map** is a DAG of every node, with a tree view rooted at any node. Frontier nodes (every dependency Accepted or Provisional, unclaimed) are outlined as *ready to claim*. Each node shows its acceptance, workflow and integrity state, and its assignee; hovering it shows its snapshot's 核心思路.
- **Awaiting review** lists each snapshot to decide on, with its 核心思路 and 难点.
- **Nodes are created on the page or from the CLI** (`proof node create`): a theorem, lemma or claim with its assumptions, dependencies and medium, or an imported result with its source and the reference it cites. Right-click the canvas (a long press on touch) for a new node there, or a card to split it, hang a node under it (`--parent`: the card rests on the new node, in one transaction) or rest a node on it. The form opens in place, previews the maths, says what the server would refuse, and shows the equivalent command to copy; a reference that isn't in `proof reference list` yet can be added from it. That covers the first node of an empty map, and a corrected source that replaces a withdrawn one.
- **A theorem, lemma or claim opens in its studio** (ADR-0011), a LaTeX workspace built from prism-local's code: editor (with folding of sections and environments), compile, PDF with SyncTeX both ways (links with Back, text selection, search, bookmarks), and the agent panel. The agent compiles through the studio's own build (its `compile` tool), so the PDF and the Problems list the researcher sees are the ones it worked from, and the page shows it at work: the lines it reads, the file as it writes it, the lines it changed. Beside them, the **node panel** shows the node's statement, state axes, assignee and dependencies, and offers claim or unassign, split into Claims, edit its dependencies (add, remove, or move one onto a child, as `proof node depend` does), request review, open a Challenge, and record an Evidence check, as the page's git identity.
- **A node's review page** shows the exact LaTeX of the snapshot under review, with its dependencies and pins, Challenges, Evidence checks and history, and the decisions to make. It links the compiled PDF when there is one: the PDF archived with the snapshot, or the studio's current `build/proof.pdf`.
- **The agent panel is the node's proof agent** (ADR-0011): it researches, reasons and proves, and writes the result into the node.
  - **It reads** the whole project, the library folders listed in `proof.toml`, and the web.
  - **It runs** `proof` (retrieval, claim, split, request review, Evidence checks) and computation such as Python, SageMath and Lean.
  - **It writes** files only in the node's sources and its `scratch/` folder, and changes project state only through `proof`. It never makes a Human Review decision.
  - **It is rooted at the project:** it runs in `proofs/<id>/` with `PROOF_ROOT` set to the project.
  - **It runs on the Claude Code or the Codex CLI**, whichever you are logged into; there is no API-model backend.
  - **It runs with the environment of the process serving the page**, so the login it finds is the one that process sees. That process is usually the Home: `proof home` and `proof map open` start it in the background the first time, it serves every project's page, and it keeps running. A page can also be served on its own by `proof map serve`, run by you or started by `proof map open` when the Home could not serve it. If your Claude Code login lives in a profile other than `~/.claude` (`CLAUDE_CONFIG_DIR`), or your Codex one outside `~/.codex` (`CODEX_HOME`), set the variable in the shell that starts that process. A process already running keeps the environment it started with. Stop it (Ctrl-C if you ran it with `--foreground` or `proof map serve`, or `pkill -f 'proof(_web\.cli)? (home|map serve)'` for any of them), then start it again from the right shell. Otherwise every Start ends at once with `the prover turn failed: Not logged in · Please run /login`.
  - **Undo** restores the turn's files, not a claim, a split, a snapshot or a decision.

  ```toml
  # proof.toml, at the project root
  [studio]
  library = ["~/papers", "../lecture-notes"]

  [snapshot]
  large_output_mb = 50   # a computation snapshot freezing more of out/ gives the SNAPSHOT_LARGE_OUTPUT notice
  ```
- **An imported result's page** shows its source, trust level and dependents, and its Reference review.

When you request review after compiling in the studio, the fresh `build/proof.pdf` is archived as `snapshots/v<N>.pdf` next to the snapshot and committed with the decision. `proofs/.gitignore` keeps `build/` out of git. Compiling needs a TeX distribution or Tectonic; without one, the studio still edits and requests review.

## Definitions

A statement is written in **Definitions** (ADR-0020): a definition, the setting of a model or notation, written once under a name and named by the nodes whose statements use it. A node names its definitions when it is created, and its `proof.tex` opens with them. A Claim split from a node, or created under it, is written in that node's definitions too, so "in the setting of the Theorem" never has to be said. A definition no node names yet can be removed. A definition, like a node's statement, assumptions and named definitions, is Unfixed until a Review decision relies on it — the first decision on a node naming it, or on a node resting on one (an imported result: its Reference review) — and until then can be restated with a reason: `proof definition edit <id> --text … --reason … --by …`, `proof node restate <node> --statement … [--assumption …] [--definition …] --reason … --by …` (ADR-0021). The researcher may restate any unfixed text, an agent only what an agent wrote, and never a definition a node of the researcher's names. Who wrote it is `--created-by`, else the agent's `PROOF_AGENT_NAME`, else the researcher (`human`); `--by` resolves the same way. A restatement is in the work log, makes stale every verdict on the node and on what rests on it, and makes a snapshot there awaiting a decision Potentially stale. Fixed text is refused (`TEXT_FIXED`, `DEFINITION_FIXED`, naming the decision): a correction is a new definition under a new id, or a new node. What a node says is its statement, its assumptions and its definitions, and that is what Acceptance and the dependency pins bind.

```bash
proof definition add release-unit --term "Stochastic release unit" 'A unit has $M\in\mathbb N_{>0}$ release sites; $r(t)\in\{0,\dots,M\}$ of them are full at time $t$. …'
proof node create MAIN theorem 'For every $n$, $\mathbb E[K_n]=Mu_n^-x_n^-$.' --definition release-unit
proof node split MAIN --child 'MEAN=…'                         # MEAN names release-unit too
proof definition list                                            # each with the nodes that name it
```

## Proof fog

A difficulty you can't state precisely yet goes in the **Proof fog** (ADR-0008), a flat list outside the map — never a node, never a dependency. Anyone, agents included, may add one, edit it, drop it with a reason or reopen it; an item may be *near* the nodes it is about. A numerical run about an item is an **Experiment**, recorded with what it showed (supports, refutes, inconclusive, error), who ran it and where its files are; it never changes the item's status. When the idea can be stated, **crystallize** it into a Claim in one step (a single-child Split of its parent when it has one); the item then reads crystallized and the node's page says where it came from. On the proof map page the fog is a drawer opened from the toolbar's Fog badge: hovering an item lights the nodes it is near up on the map, and **Crystallize…** on an item opens the map's node form on it, preset to a Claim split from its one near node; the statement is written there, never copied from the item (#155).

```bash
proof fog add "the constant C is probably optimal" --near L1
proof fog experiment record fog-1 supports --summary "checked n ≤ 10^6" --run-by agent_a --path proofs/L1/scratch/constant.py
proof fog crystallize fog-1 C2 "For every n, C(n) ≤ 1 + 1/n"   # parent: the one near node, or --parent / --no-parent
proof fog drop fog-2 --reason "the coefficients grow too fast"  # proof fog reopen fog-2 takes it back
proof fog list --all                                           # dropped and crystallized items too
```

## Human Review

Decisions that change what the project trusts (accepting a Candidate proof, Reference review, dismissing a Challenge, promoting) are made only on the project's local proof map page:

```bash
proof home              # the Home: your projects, each opening in its page
proof map open [<id>]   # open this project's map, or a node's page (through the Home)
proof map serve         # this project's page alone, in the foreground, without a Home
```

Each decision is one line in the node's git-tracked `proofs/<id>/reviews.jsonl`, naming the SHA-256 of the snapshot it decides on. proof-cli commits that line together with the snapshot, as your own git identity (`user.name` / `user.email`); it never pushes. Once you push, the commit on GitHub is the record of who decided what (ADR-0010). Outside a git repository the decision is still recorded, just without that record. `proof review warnings` lists decisions git doesn't have yet.

A **Trust rule** (ADR-0014) is a Reference review you declare in advance for a class of citations — "textbooks and monographs", "another citation of a source I already reviewed, at the same version", "has a DOI". It is declared, amended and retired from the review page's *Trusted by rule* section (Manage rules…), recorded as one line in the project-level `proofs/trust-rules.jsonl` and committed the same way. An imported result whose citation meets a rule reads `trusted-by-rule` and unblocks its dependents; nothing is written on it, and reviewing it explicitly always wins. The review page lists those nodes apart from what awaits you; `proof trust-rule list` and `proof trust-rule show <name>` read the rules, and no command writes one.

No CLI command or agent tool can make these decisions. Those commands answer `HUMAN_REVIEW_REQUIRED` with the page's URL. That is a boundary for cooperative agents on your own machine, not a security mechanism, which suits personal use or a small team on GitHub. A project from before ADR-0010 has its decisions moved into `reviews.jsonl` the first time it's opened, and every node keeps its state.

A claim is a wayfinder-style assignment, not a lock (ADR-0010). `proof node claim <id> --assignee <name>` marks a frontier node as taken so that other agents skip it. `--reassign` takes over a stale claim, and `proof node unassign <id> --by <name>` clears one. `proof frontier` lists the nodes ready to be worked — every dependency Accepted or Provisional, nobody holding them, none awaiting review — with their three state axes. A Blocked node may still be claimed and worked; Blocked holds back only its Review decision, which waits until what it rests on is Accepted (ADR-0021). A node resting on a Provisional one, an unaccepted node whose snapshot the Verifier passed or an unreviewed imported result, is Conditional on it: `proof node show` and `--json` name them under `conditional_on`.

Proof state is persisted locally. Generated workspace state under `.proof/` is intentionally excluded from version control.

## Project principles

- Human-in-the-loop: the system suggests and checks; researchers make final trust decisions.
- Retrieval-first: the proof map's Accepted nodes and Reference-reviewed imported results are checked before new proof search.
- Local-state-first: long-running work survives context loss through persisted project state.
- CLI-first: the initial workflow is terminal-native.
- No full kernel in v1: explicit contracts, checks, and review boundaries come first.
