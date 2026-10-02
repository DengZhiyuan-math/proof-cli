# Mathematical Proof CLI

Mathematical Proof CLI is a local-first research proof operating system for human–machine collaboration. A project is a proof map: nodes (theorems, lemmas, claims, and imported results) joined by their dependencies. Each local node has its own LaTeX proof, and the researcher accepts or rejects it on the proof map page. Agents claim nodes from the frontier, split nodes that are too large, and request review. Every decision stays explicit and auditable in git. What can be called is answered only by the proof map's nodes: an Accepted theorem, lemma or claim, or an imported result with a Reference review (ADR-0012). The `theorem`, `obligation`, `blocker`, `goal` and `verify` command groups come from the model before the proof map, and `proof --help` lists them under Legacy. Their callable, trust and review states are marked as legacy, not a trust source; a reference is only a citation.

The project is designed to support rigorous research workflows without replacing the mathematician or attempting to provide a full formal kernel. Final acceptance remains with the researcher.

## Requirements

- Python 3.11 or newer

## Install for development

```bash
python -m pip install -e ".[dev]"
```

## Command-line entry point

The researcher's entry is the proof map page (`proof map open`, below). `proof` is the agents' interface, with `--json` for one envelope per call:

```bash
proof --help
proof frontier
proof node show <id>
proof trust-rule list   # the Trust rules in force (read-only; declared on the page)
proof fog list          # the Proof fog: difficulties not yet precise enough to be a Claim
proof node create C3 claim "For every n ≤ 10^4 …" --medium computation   # a node established by a program: run.sh, outputs in out/
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

Beside it sits the proof's key-ideas summary, `proofs/<id>/key-ideas.md` (ADR-0013). It is Markdown, with maths as `$…$`, under four headings: **核心思路** (why it holds) and **主要步骤** (3–7 steps, each naming the dependency it uses) are required; **难点** (where it is most likely wrong) and **未覆盖** (what it leaves out) may be 「无」. Review starts from it. When it is missing, the node panel's *Draft key ideas with the proof agent* has the agent draft it from `proof.tex` and the dependencies; you edit the draft, and requesting review confirms it.

When the proof and its summary are ready, request review from the studio's node panel, or:

```bash
proof node request-review <id> --rationale "why it is scoped to prove directly"
```

A request without `key-ideas.md`, or with 核心思路 or 主要步骤 empty, is refused with `KEY_IDEAS_REQUIRED`. Otherwise it freezes every input of the proof into an immutable snapshot, `proofs/<id>/snapshots/v<N>/`: the node's working sources (not `build/`, `scratch/` or older snapshots), its key-ideas summary and the shared preamble, with a `manifest.json` of each file's SHA-256. The snapshot's SHA-256, which decisions bind, is that of the manifest, so a change to any input, an `\input` file, a preamble macro or the summary alone included, is a new version to review. Review is always of a snapshot, never of the working files (ADR-0010, ADR-0011). The researcher reviews it in the node's studio: the review view shows the snapshot's key ideas and records the decisions, and links to the node's page for the frozen LaTeX and the archived PDF (ADR-0013). A snapshot from before summaries existed is reviewed as before, and says it has none.

## The proof map page

`proof map open` starts the project's local page, bound to 127.0.0.1, and opens it:
- **The map** is a DAG of every node, with a tree view rooted at any node. Frontier nodes (open, unblocked, unclaimed) are outlined as *ready to claim*. Each node shows its acceptance, workflow and integrity state, and its assignee; hovering it shows its snapshot's 核心思路.
- **Awaiting review** lists each snapshot to decide on, with its 核心思路 and 难点.
- **Nodes are created from the CLI** (`proof node create`): a theorem, lemma or claim with its assumptions and dependencies, or an imported result with its source. That covers the first node of an empty map, and a corrected source that replaces a withdrawn one.
- **A theorem, lemma or claim opens in its studio** (ADR-0011), a LaTeX workspace built from prism-local's code: editor, compile, PDF with SyncTeX both ways, and the agent panel. Beside them, the **node panel** shows the node's statement, state axes, assignee and dependencies, and offers claim or unassign, split into Claims, edit its dependencies (add, remove, or move one onto a child, as `proof node depend` does), request review, open a Challenge, and record an Evidence check, as the page's git identity.
- **A node's review page** shows the exact LaTeX of the snapshot under review, with its dependencies and pins, Challenges, Evidence checks and history, and the decisions to make. It links the compiled PDF when there is one: the PDF archived with the snapshot, or the studio's current `build/proof.pdf`.
- **The agent panel is the node's proof agent** (ADR-0011): it researches, reasons and proves, and writes the result into the node.
  - **It reads** the whole project, the library folders listed in `proof.toml`, and the web.
  - **It runs** `proof` (retrieval, claim, split, request review, Evidence checks) and computation such as Python, SageMath and Lean.
  - **It writes** files only in the node's sources and its `scratch/` folder, and changes project state only through `proof`. It never makes a Human Review decision.
  - **It is rooted at the project:** it runs in `proofs/<id>/` with `PROOF_ROOT` set to the project.
  - **It runs on the Claude Code or the Codex CLI**, whichever you are logged into; there is no API-model backend.
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

## Proof fog

A difficulty you can't state precisely yet goes in the **Proof fog** (ADR-0008), a flat list outside the map — never a node, never a dependency. Anyone, agents included, may add one, edit it, drop it with a reason or reopen it; an item may be *near* the nodes it is about. A numerical run about an item is an **Experiment**, recorded with what it showed (supports, refutes, inconclusive, error), who ran it and where its files are; it never changes the item's status. When the idea can be stated, **crystallize** it into a Claim in one step (a single-child Split of its parent when it has one); the item then reads crystallized and the node's page says where it came from. On the proof map page the fog is a drawer opened from the toolbar's Fog badge: hovering an item lights the nodes it is near up on the map.

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
proof map serve         # start the proof map page for this project
proof map open [<id>]   # open the map, or a node's page
```

Each decision is one line in the node's git-tracked `proofs/<id>/reviews.jsonl`, naming the SHA-256 of the snapshot it decides on. proof-cli commits that line together with the snapshot, as your own git identity (`user.name` / `user.email`); it never pushes. Once you push, the commit on GitHub is the record of who decided what (ADR-0010). Outside a git repository the decision is still recorded, just without that record. `proof review warnings` lists decisions git doesn't have yet.

A **Trust rule** (ADR-0014) is a Reference review you declare in advance for a class of citations — "textbooks and monographs", "another citation of a source I already reviewed, at the same version", "has a DOI". It is declared, amended and retired from the review page's *Trusted by rule* section (Manage rules…), recorded as one line in the project-level `proofs/trust-rules.jsonl` and committed the same way. An imported result whose citation meets a rule reads `trusted-by-rule` and unblocks its dependents; nothing is written on it, and reviewing it explicitly always wins. The review page lists those nodes apart from what awaits you; `proof trust-rule list` and `proof trust-rule show <name>` read the rules, and no command writes one.

No CLI command or agent tool can make these decisions. Those commands answer `HUMAN_REVIEW_REQUIRED` with the page's URL. That is a boundary for cooperative agents on your own machine, not a security mechanism, which suits personal use or a small team on GitHub. A project from before ADR-0010 has its decisions moved into `reviews.jsonl` the first time it's opened, and every node keeps its state.

A claim is a wayfinder-style assignment, not a lock (ADR-0010). `proof node claim <id> --assignee <name>` marks a frontier node as taken so that other agents skip it. `--reassign` takes over a stale claim, and `proof node unassign <id> --by <name>` clears one. `proof frontier` lists the open, unblocked, unclaimed nodes with their three state axes.

Proof state is persisted locally. Generated workspace state under `.proof/` is intentionally excluded from version control.

## Project principles

- Human-in-the-loop: the system suggests and checks; researchers make final trust decisions.
- Retrieval-first: the proof map's Accepted nodes and Reference-reviewed imported results are checked before new proof search.
- Local-state-first: long-running work survives context loss through persisted project state.
- CLI-first: the initial workflow is terminal-native.
- No full kernel in v1: explicit contracts, checks, and review boundaries come first.
