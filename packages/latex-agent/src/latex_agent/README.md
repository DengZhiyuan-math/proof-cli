# latex-agent (`latex_agent`)

The LaTeX studio of a node's page: editor, compile, PDF with SyncTeX, and the agent panel (ADR-0011). Its own package since ADR-0018, `packages/latex-agent/` (before that `src/proof_cli/studio/`): the standard library only, a TeX distribution or Tectonic to compile, and nothing of proof-cli. proof-web serves one `Studio` per proof map node and hands it the node's agent context (proof-agents' `ProofAgentContext`), its run (`AgentRun`) and the names of the node's summary and program files.

It began as a copy of [prism-local](https://github.com/DengZhiyuan-math/Local-Ai-agent-for-latex) at commit `6512eb8f7d65d152dfb45fba64e3606fa1dc4755`, taken on 2026-09-28 (#68), and belongs to proof-cli from then on. The two projects are independent and proof-cli owes prism-local no compatibility; when prism-local gains something the node page wants, it is taken over by hand (a three-way merge of the files that still match, the rest ported), never merged as a branch. See "Taken from upstream since".

## Kept from prism-local

- The editor server: `server.py`, `httpbase.py`, `fsutil.py`, `texutil.py`.
- Build: `build.py` and `proc.py`.
- The agent panel: `agent.py` and the backends `backends.py`, `backend_claude.py` and `backend_codex.py`. prism-local's API-model backend (`backend_openai.py`, DeepSeek and other OpenAI-compatible APIs) was removed in #72: the proof agent runs on the Claude Code or Codex CLI.
- The page: `static/`, with vendored CodeMirror 5 and PDF.js.

## Left out

- The multi-project Home page and its server: `hub.py`, `static/home.*`. proof-cli has its own Home since ADR-0017 (proof-web's `home.py` and `static/home.*`), written for its project model, not taken from here.
- The port registry (`registry.py`), page presence and idle exit (`presence.py`), the launcher and `bin/`. proof-cli's own server, proof map and project list (`projects.py`) do those jobs.

## Taken from upstream since

- **2938c05 (2026-10-01), "Watch the agent work, let it compile, and a fuller PDF reader".** Taken: the Claude backend streams thinking, each tool step with the file and lines it works on, and the text of a file as it is written (`tool_start`, `tool_live`, `thinking*` events); the page marks where the agent reads, rewrites and changed, and shows the file it is writing over the editor (`AH`, `AV` in `app.js`) — in proof-cli a file it changed is offered as a marked tab behind the one the researcher is on, never switched to; refused steps are named; with the claude.ai login tokens are shown, not a price. The compile tool (`mcp_compile.py`, an MCP server Claude Code or Codex starts per turn: `--mcp-config` for the one, `-c mcp_servers.studio.*` for the other) builds through the node's own studio — in proof-cli a LaTeX node's typesetting edit turns get it (the Typesetter's, and the solo agent's edit turns); Ask turns, the Prover, Numerics and a computation node's turns don't; the Typesetter no longer runs latexmk itself. Both CLIs' names for the tool are shown as `Compile` (`backends.tool_name`), and a compile through it counts as a run for the stuck rule, as a shell compile did; a `kpsewhich` lookup does not. A limit carried over with that rule: a turn that only compiles resets the run's idle count, so an agent can go on compiling, turn after turn, until the run's turn or minute budget ends — as it could with latexmk before. Whether Codex's sandbox lets the tool reach the studio on localhost is not yet verified (#152). The PDF reader's links with Back (http(s) URLs and places in the document only), text selection, search and bookmarks; glyphs drawn as paths; inverse SyncTeX from the contents and the bibliography to the source or the `.bib` entry; the fold addon for sections, environments and `\[ \]` (`texfold.js`, vendored `foldcode.js`/`foldgutter.*`). proof-cli adds what upstream has no need of: the run pane follows the running turn's events live into the Files view and shows each step in the turn's transcript. Left out: the "Update: restart" button and `/api/restart` (proof-cli's server is its own program), the shell-allowlist logic (a role's Bash rules come from `proof_agent.py`), the API-model backend's share, and `home.js`.

## Changed on import

- Imports are package-relative.
- The allowed Claude account comes from `$PROOF_CLAUDE_ACCOUNT`, not from the Home page's settings.
- A build on a machine with no TeX engine and no Tectonic reports `"unavailable": true` rather than looking like a failed build.

## What proof-cli added here

Nothing is outstanding from the import. Since #69 there are no module globals: a `Studio` (`server.py`) holds one folder's state, and proof-cli's server runs one per node inside its own process (proof-web's `studios.py`, `StudioHub`). `python -m latex_agent.server` still serves a single folder on its own port, for developing the studio itself.

The page is the studio's alone: editor, PDF, build and the agent panel. It carries **host slots** — `<!-- host:brand -->`, `host:sidebar`, `host:centre-top`, `host:centre-pane`, `host:chat-foot`, `host:chat-actions` and `host:head` — where a host serving it for a proof map node puts its own markup; proof-web fills them with its node section, the centre's Work log · Files tab bar and run pane, the review card and the "+" menu by the message box, and the link back to its map, adds its stylesheet (`node.css`) and appends its scripts (`node.js`, `run.js`, `menu.js`, `status.js`, `mathtext.js`) when it serves the page (ADR-0018). Served on its own, every slot is empty, the editor and the PDF are the centre, and `showCentre` is a no-op. What remains from proof-cli's use here is only wording: the agent panel asks about "this node", a computation's Run is recorded as an Evidence check by the host's hooks.

## Licences

prism-local is MIT, © 2026 Zhiyuan Deng (`LICENSE`). The vendored libraries keep their own licences: CodeMirror (MIT, `static/vendor/LICENSE-codemirror`), PDF.js (Apache-2.0, `static/vendor/LICENSE-pdfjs`) and KaTeX (MIT, `static/vendor/LICENSE-katex`).

## KaTeX

The key-ideas summaries (ADR-0013) typeset their `$…$` and `$$…$$` with [KaTeX](https://katex.org) **0.18.9**, vendored from the npm tarball `katex-0.18.9.tgz` (integrity `sha512-8ad9RyoKsb/g8/yLFE+KAlP+DhbCTRUNi/V9XGsxn0R+trJJltNwzcDNo0q/DEkOy5fQUQTAQyCXCYSE+OakTQ==`):
`dist/katex.min.js` and `dist/katex.min.css` as `static/vendor/katex.min.*`, and the twenty `dist/fonts/*.woff2` as `static/vendor/fonts/`. The `.woff` and `.ttf` fallbacks the stylesheet also names are left out; every browser the studio supports loads `.woff2`. `static/mathtext.js` calls it; the map page loads the same files from `/static/shared/`. Nothing is fetched from the network. To update, replace those files from a newer tarball and change the version here.
