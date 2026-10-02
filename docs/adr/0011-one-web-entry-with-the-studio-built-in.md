# One web entry, with the LaTeX studio built in

**Status**: accepted (implemented in #67–#72). Amended by ADR-0015: a node whose Medium is `computation` has a program as its candidate proof — its scripts, data and environment files, frozen by the snapshot as inputs, and `out/` as outputs — unlike a LaTeX node's `scratch/`, which stays unfrozen. The studio's Run and the display of frozen outputs follow in #147. Amended by ADR-0016: the studio is the Proof agent's workbench — a run of three roles the researcher watches and steps in on — and the editor is its Files view.
- **Supersedes** ADR-0010 point 5 ("prism-local is coupled only through files") and its note that proof-cli needs no TeX.
- **Supersedes** ADR-0007's "Start agent is not the web app spawning or supervising an agent process": the node page now runs an agent.
- **Amends** ADR-0006 (the command surface), ADR-0008 (the node page) and ADR-0010's snapshot (point 5 below).
- **Amended by** ADR-0013: the snapshot of point 5 also freezes the node's key-ideas summary, and the review of point 2 shows that summary and the decisions, not the frozen LaTeX or PDF.

## Context

ADR-0010 made a node's proof a standalone LaTeX document. It left writing and compiling that document to prism-local, the author's separate local LaTeX studio (editor, compile, PDF with SyncTeX, an AI agent panel with per-turn undo), which the map page launched as a second program on the node's folder. In use this splits one job across two apps. The researcher reads the map in one page, edits and compiles in another, and comes back to the first to request review or decide. Splitting a node, the most common response to a proof that won't close, can't be done at all where the proof is being written.

The researcher also had two command-line entry points that humans never needed: `proof-codex`, and the `proof codex …` wrapper group behind the proof-routing MCP plugin.

## Decision

1. **Humans have one entry: the proof map web app.**
   - `proof map open` starts it, one local server process.
   - Its home is the proof map: the DAG and tree, the frontier, what awaits review, and creating nodes. That covers the first node of an empty map, an imported result, and the corrected source that replaces a withdrawn one.
   - Every human action happens in the web app: reading, writing and compiling a proof, claiming, splitting, requesting review, opening a Challenge, and every Human Review decision.

2. **A local node's page is a LaTeX studio scoped to the node's folder.** A theorem, lemma or claim opens `proofs/<node-id>/` in an editor with its compiled PDF (SyncTeX both ways), compile, the problems list and the agent panel. Beside them sits a node panel:
   - the node's statement and three state axes, its assignee, and its dependencies with their pins;
   - the agent-reachable actions of ADR-0006: claim or unassign, split into Claims, request review, open a Challenge, record an Evidence check;
   - review: the Review snapshot under review, read-only, with its archived PDF, and the Human Review decisions this node offers, with the bindings of PR #63 (a decision is refused if what the page showed changed).
     - *Amended by ADR-0013:* the review shows the snapshot's key-ideas summary and the decisions only. The frozen LaTeX sources and the archived PDF are a link away, on the node's page. A snapshot without a summary says so and links there too.

   Splitting creates each child's folder, and the page moves straight on to the child.

   The agent panel is not a LaTeX assistant. It is the node's **proof agent** (point 8), which researches, reasons and proves, and writes its result into the node.

   **An imported result's page is not a studio.** It has no proof to write. Its page shows its source (locator, version, trust level), its dependents, Reference review, and, once it is no longer callable, moving its dependents onto a corrected source (#20).

3. **The studio is prism-local's code, taken into proof-cli and then changed freely.** The code is copied, not merged: prism-local at commit `6512eb8` goes into `src/proof_cli/studio/`, with its MIT licence and the licences of the vendored CodeMirror (MIT) and PDF.js (Apache-2.0). The two projects stay independent. Nothing is synced either way, and proof-cli owes prism-local no compatibility.

   Only what the node page needs is kept: the editor, build, SyncTeX, file I/O and the agent panel with its backends. prism-local's multi-project Home, port registry, launcher and idle watchdog are left out, because proof-cli's own server and map do those jobs.

4. **The studio serves nodes, not an origin.**
   - prism-local keeps one project per process in module globals, and its page assumes the origin is the project. In proof-cli, each node's studio is an object bound to the node's folder, its routes live under the node's path, and the page takes its base path from the node.
   - Browser storage, BroadcastChannel and lock names are keyed by node.
   - Builds and agent turns are limited per node, not per process.
   - A node's build is fixed, not configurable per node: main file `proof.tex`, output `build/proof.pdf`.

5. **A Review snapshot freezes every input of the proof.** Once the editor allows more than one source file, a snapshot of `proof.tex` alone would review a document it can't reproduce. Changing an `\input` file, or a macro in the shared preamble, would then leave the node reading "unchanged".
   - A snapshot is therefore the node's whole working source set, frozen together: every `.tex`, `.bib`, `.sty`, `.cls` and similar input in the node folder, plus the shared `preamble.tex`.
   - It is stored as `snapshots/v<N>/`, with a manifest of each file's SHA-256. The snapshot's SHA-256, which decisions bind, is the SHA-256 of that manifest.
   - A change to any input is a new version to review.
   - Older single-file snapshots (`snapshots/v<N>.tex`) stay readable as they are.
   - *Amended by ADR-0013:* the node's working sources include its key-ideas summary, `key-ideas.md`, so it is frozen, listed and hashed with the rest, and requesting review needs one.
   - The TeX distribution itself is out of scope: a snapshot freezes the project's own files, not the installed packages.

6. **What the editor and the agent may write directly.**
   - Direct file edits, from the editor or from an agent's file tools, reach only the node's working sources, plus, for the agent, the node's scratch folder.
   - **The scratch folder** is `proofs/<id>/scratch/`, where the agent keeps its computation scripts and their output. Snapshots don't include it, builds ignore it, and it stays out of git by default, like `build/`.
   - Review snapshots, `reviews.jsonl`, `build/` and other nodes' folders are never directly writable.
   - The shared `preamble.tex` is edited from its own entry on the map page.
   - **Reading is not confined** (point 8).

   Domain operations are a different path. Claim, split, request review, open a Challenge and compile have their documented wider effects: the project database, a child's new folder, a snapshot, build output. They go through the service layer, as every caller's do (ADR-0007). This boundary is about correctness for cooperative local agents. It isn't a security boundary against a hostile one (ADR-0010).

7. **A node's snapshot PDF follows ADR-0010's freshness rule.** The PDF archived beside a snapshot is `build/proof.pdf`, and only when it is at least as new as every input the snapshot freezes (`vault.build_is_current`). A PDF left over from an earlier successful build, when the latest build failed, is shown as stale and never archived. The working build and the snapshot's archived PDF are shown as two different things.

8. **The agent panel is an autonomous proof agent, rooted at the project.** This is an automated proof system: the agent on a node researches, reasons and proves, and editing the LaTeX is only how it writes the result down. Only a Human Review decision is beyond it.
   - **What it may read:**
     - the whole project: every node's proof, snapshots, reviews, references, memory and handoffs;
     - the read-only library folders listed in the project's configuration, such as the researcher's papers and notes;
     - the web: search and fetch, to find and read the literature.
   - **What it may run:** `proof`, for everything agent-reachable (ADR-0006): retrieving project results and references, claiming, splitting, creating nodes, requesting review, opening a Challenge and recording an Evidence check. It may also run computation to support its reasoning: Python, SageMath, a proof assistant such as Lean, numerical checks and counterexample searches.
   - **What it may change:** files only as point 6 says (the node's working sources and scratch folder), and project state only through `proof`.
   - **How it is asked to work.** Its standing brief follows the project's constraints:
     - retrieval first: check project results and trusted references before a new proof search;
     - reason independently and write the proof in `proof.tex`;
     - split a node too large to prove directly rather than force a proof;
     - request review with a scoping rationale;
     - record what a real checker it ran said as an Evidence check, and never claim a check nobody ran (#27).
   - **Rooted at the project.**
     - The `proof` CLI stays the agent interface of ADR-0006, and its JSON contract (#34) is unchanged.
     - The CLI's `--root` defaults to the `PROOF_ROOT` environment variable, then to the current folder. That is the one root convention, taken over from the retired `proof codex` group.
     - The studio starts the agent in the node's folder with `PROOF_ROOT` set to the project root, so every `proof` call acts on the project and never starts a nested one.
   - **Its permissions are explicit, not inherited.** They are the set above: reads over the project and the library folders, web search and fetch, `proof` and computation commands, and writes confined to the node's sources and scratch folder. They aren't the repository's own CLAUDE.md, settings or Bash allowlist, which Claude Code would otherwise load from the parent folders. This is a contract for cooperative local agents, enforced where the backend supports it (ADR-0010's threat model), not a sandbox against a hostile one.
   - **Backends.** The proof agent runs on the Claude Code CLI or the Codex CLI, which the researcher logs into and which search the web and run commands. prism-local's API-model backend (an OpenAI-compatible API with a key) is not carried over: the researcher doesn't use API keys, and a model with only file tools couldn't be the proof agent.
   - Human Review decisions stay unreachable from the agent panel exactly as from the CLI.
   - The panel's **per-turn Undo restores working source and scratch files only.** It doesn't undo a claim, a split, a new node, a snapshot, anything in the project database, or any decision, and its label says so.

9. **Removed:** the `proof-codex` entry point, the `proof codex …` group, and the proof-routing MCP plugin, which only wrapped that group. Agents use `proof` directly, guided by `.agents/skills/proof-cli/SKILL.md`.

10. **TeX becomes optional equipment, not a requirement.** Compiling needs a TeX distribution (or Tectonic). Without one, the node page still edits, snapshots and reviews, and shows the build as unavailable.

## Consequences

- One server, one origin, one place to look. A node folder stays an ordinary LaTeX project that any editor, prism-local itself included, can open. It just isn't needed.
- proof-cli takes on prism-local's code, about 300 KB of Python and JavaScript plus vendored libraries, and with it prism-local's tests and packaging. The wheel must carry the nested static and vendor files and the three licences. Fixes made in one project don't reach the other. That is accepted.
- The snapshot changes shape, from one file to a frozen folder with a manifest, and its SHA-256 now covers every input. Decisions, bindings and the archived PDF follow it. Old single-file snapshots and the decisions made on them stay valid.
- The page's security model extends to the studio's routes: the pinned origin and host checks, a same-origin requirement for writes, and a CSP. prism-local's `X-Prism-Local` header and `X-Frame-Options: DENY` are folded into it.
- The agent panel becomes a second way for an agent to act on the project, next to a terminal, and a capable one: it reads the whole project and the web and runs computation. It still changes project state only through the same `proof` CLI and service layer, so there is still one write path, and Human Acceptance Authority (ADR-0004) is unchanged. Everything it proves reaches the map as a Review snapshot for the researcher to decide on.
- Users of `proof codex …` or the MCP plugin move to `proof node …`.
