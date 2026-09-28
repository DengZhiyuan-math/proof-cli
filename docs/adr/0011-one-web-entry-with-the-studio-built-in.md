# One web entry, with the LaTeX studio built in

**Status**: proposed. Supersedes ADR-0010 point 5 ("prism-local is coupled only through files") and its note that proof-cli needs no TeX. Amends ADR-0006 (the command surface) and ADR-0008 (the node page).

## Context

ADR-0010 made a node's proof a standalone LaTeX document. It left writing and compiling that document to prism-local, the author's separate local LaTeX studio (editor, compile, PDF with SyncTeX, an AI agent panel with per-turn undo), which the map page launched as a second program on the node's folder. In use this splits one job across two apps. The researcher reads the map in one page, edits and compiles in another, and comes back to the first to request review or decide. Splitting a node, the most common response to a proof that won't close, can't be done at all where the proof is being written.

The researcher also had two command-line entry points that humans never needed: `proof-codex`, and the `proof codex …` wrapper group behind the proof-routing MCP plugin.

## Decision

1. **Humans have one entry: the proof map web app.** `proof map open` starts it, one local server process. Its home is the proof map: the DAG and tree, the frontier, and what awaits review. Every human action happens in it: reading, writing and compiling a proof, claiming, splitting, requesting review, opening a Challenge, and every Human Review decision.

2. **A node's page is a LaTeX studio scoped to the node's folder.** `proofs/<node-id>/` opens in an editor with its compiled PDF (SyncTeX both ways), compile, the problems list, and the agent panel. Beside them sits a node panel:
   - the node's statement and three state axes, its assignee, and its dependencies with their pins;
   - the agent-reachable actions of ADR-0006: claim or unassign, split into Claims, request review, open a Challenge, record an Evidence check;
   - review: the Review snapshot under review, read-only, with its archived PDF, and the Human Review decisions this node offers, with the bindings of PR #63 (a decision is refused if what the page showed changed).

   Splitting creates each child's folder, and the page moves straight on to the child.

3. **The studio is prism-local's code, taken into proof-cli and then changed freely.** The code is copied, not merged: prism-local at commit `6512eb8` goes into `src/proof_cli/studio/`, with its MIT licence and the licences of the vendored CodeMirror (MIT) and PDF.js (Apache-2.0). The two projects stay independent. Nothing is synced either way, and proof-cli owes prism-local no compatibility. Only what the node page needs is kept: the editor, build, SyncTeX, file I/O and the agent panel with its backends. prism-local's multi-project Home, port registry, launcher and idle watchdog are left out, because proof-cli's own server and map already do those jobs.

4. **The studio serves nodes, not an origin.** prism-local keeps one project per process in module globals, and its page assumes the origin is the project. In proof-cli:
   - each node's studio is an object bound to the node's folder;
   - its routes live under the node's path;
   - the page takes its base path from the node;
   - browser storage, BroadcastChannel and lock names are keyed by node.

   Builds and agent turns are limited per node, not per process.

5. **What a node's studio may write.** The editable set is the node's working sources: `proof.tex` and any other `.tex`/`.bib`/`.sty` files the author adds. Review snapshots (`snapshots/`), `reviews.jsonl` and `build/` are never editable from the editor or by the agent. A snapshot is what the researcher reviews, and only `request review` writes one. The shared `preamble.tex` is editable from its own entry on the map page, not from a node.

6. **Agents keep the `proof` CLI.** It stays the agent interface of ADR-0006, and its JSON contract of #34 is unchanged. The studio's agent panel runs its agent (Claude Code, Codex, or an API model) in the node's folder with `proof` on its path, so an agent at work on a node can claim, split and request review the same way an agent in a terminal can. Human Review decisions stay unreachable from the agent panel exactly as from the CLI: a decision is made only by the researcher on the page. The agent's writes are confined as in point 5. Claude Code, started in `proofs/<id>/`, would otherwise inherit the repository's own CLAUDE.md, settings and Bash allowlist, so the studio starts it with an explicit, node-scoped permission set.

7. **Removed:** the `proof-codex` entry point, the `proof codex …` group, and the proof-routing MCP plugin, which only wrapped that group. Agents use `proof` directly, guided by `.agents/skills/proof-cli/SKILL.md`.

8. **TeX becomes optional equipment, not a requirement.** Compiling needs a TeX distribution (or Tectonic). Without one, the node page still edits, snapshots and reviews, and shows the build as unavailable. A snapshot's archived PDF is still whatever the last build produced (ADR-0010).

## Consequences

- One server, one origin, one place to look. ADR-0010's promise that a node folder is an ordinary LaTeX project still holds, so any other editor, or prism-local itself, can still open it. It just isn't needed.
- proof-cli takes on prism-local's code, about 300 KB of Python and JavaScript plus vendored libraries, and with it prism-local's tests. Fixes made in one project don't reach the other. That is accepted.
- The page's security model extends to the studio's routes: the pinned origin and host checks, a same-origin requirement for writes, and a CSP. prism-local's `X-Prism-Local` header and `X-Frame-Options: DENY` are folded into it.
- The agent panel becomes a second way for an agent to act on the project, next to a terminal. It goes through the same `proof` CLI and the same service layer (ADR-0007), so there is still one write path, and Human Acceptance Authority (ADR-0004) is unchanged.
- Users of `proof codex …` or the MCP plugin move to `proof node …`.
