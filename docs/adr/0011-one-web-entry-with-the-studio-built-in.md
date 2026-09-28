# One web entry, with the LaTeX studio built in

**Status**: proposed.
- **Supersedes** ADR-0010 point 5 ("prism-local is coupled only through files") and its note that proof-cli needs no TeX.
- **Supersedes** ADR-0007's "Start agent is not the web app spawning or supervising an agent process": the node page now runs an agent.
- **Amends** ADR-0006 (the command surface), ADR-0008 (the node page) and ADR-0010's snapshot (point 5 below).

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

   Splitting creates each child's folder, and the page moves straight on to the child.

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
   - The TeX distribution itself is out of scope: a snapshot freezes the project's own files, not the installed packages.

6. **What the editor and the agent may write directly.** Direct file edits, from the editor or from an agent's file tools, reach only the node's working sources. Review snapshots, `reviews.jsonl` and `build/` are never directly writable, and neither is another node's folder. The shared `preamble.tex` is edited from its own entry on the map page.

   Domain operations are a different path. Claim, split, request review, open a Challenge and compile have their documented wider effects: the project database, a child's new folder, a snapshot, build output. They go through the service layer, as every caller's do (ADR-0007). This boundary is about correctness for cooperative local agents. It isn't a security boundary against a hostile one (ADR-0010).

7. **A node's snapshot PDF follows ADR-0010's freshness rule.** The PDF archived beside a snapshot is `build/proof.pdf`, and only when it is at least as new as every input the snapshot freezes (`vault.build_is_current`). A PDF left over from an earlier successful build, when the latest build failed, is shown as stale and never archived. The working build and the snapshot's archived PDF are shown as two different things.

8. **Agents keep the `proof` CLI, bound to the project, not the node.**
   - The `proof` CLI stays the agent interface of ADR-0006, and its JSON contract (#34) is unchanged.
   - The CLI's `--root` defaults to the `PROOF_ROOT` environment variable, then to the current folder. That is the one root convention, taken over from the retired `proof codex` group.
   - The studio starts its agent in the node's folder with `PROOF_ROOT` set to the project root, so a `proof` call from inside `proofs/<id>/` acts on the project and never starts a nested one.
   - **What each backend can do in v1:**
     - Claude Code and Codex, which run commands, may call `proof` for the agent-reachable actions. Their command permissions are node-scoped and explicit, not inherited from the repository's own CLAUDE.md, settings or Bash allowlist, which Claude Code would otherwise load from the parent folders.
     - API models have only file tools, so in v1 they edit sources and nothing more. A small `proof` tool for them is future work.
   - Human Review decisions stay unreachable from the agent panel exactly as from the CLI.
   - The panel's **per-turn Undo restores working source files only.** It doesn't undo a claim, a split, a snapshot, anything in the project database, or any decision, and its label says so.

9. **Removed:** the `proof-codex` entry point, the `proof codex …` group, and the proof-routing MCP plugin, which only wrapped that group. Agents use `proof` directly, guided by `.agents/skills/proof-cli/SKILL.md`.

10. **TeX becomes optional equipment, not a requirement.** Compiling needs a TeX distribution (or Tectonic). Without one, the node page still edits, snapshots and reviews, and shows the build as unavailable.

## Consequences

- One server, one origin, one place to look. A node folder stays an ordinary LaTeX project that any editor, prism-local itself included, can open. It just isn't needed.
- proof-cli takes on prism-local's code, about 300 KB of Python and JavaScript plus vendored libraries, and with it prism-local's tests and packaging. The wheel must carry the nested static and vendor files and the three licences. Fixes made in one project don't reach the other. That is accepted.
- The snapshot changes shape, from one file to a frozen folder with a manifest, and its SHA-256 now covers every input. Decisions, bindings and the archived PDF follow it. Old single-file snapshots and the decisions made on them stay valid.
- The page's security model extends to the studio's routes: the pinned origin and host checks, a same-origin requirement for writes, and a CSP. prism-local's `X-Prism-Local` header and `X-Frame-Options: DENY` are folded into it.
- The agent panel becomes a second way for an agent to act on the project, next to a terminal. It goes through the same `proof` CLI and the same service layer, so there is still one write path, and Human Acceptance Authority (ADR-0004) is unchanged.
- Users of `proof codex …` or the MCP plugin move to `proof node …`.
