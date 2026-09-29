# proof_cli.studio

The LaTeX studio of a node's page: editor, compile, PDF with SyncTeX, and the agent panel (ADR-0011).

It began as a copy of [prism-local](https://github.com/DengZhiyuan-math/Local-Ai-agent-for-latex) at commit `6512eb8f7d65d152dfb45fba64e3606fa1dc4755`, taken on 2026-09-28 (#68), and belongs to proof-cli from then on. The two projects are independent. Nothing is synced either way, and proof-cli owes prism-local no compatibility.

## Kept from prism-local

- The editor server: `server.py`, `httpbase.py`, `fsutil.py`, `texutil.py`.
- Build: `build.py` and `proc.py`.
- The agent panel: `agent.py` and the backends `backends.py`, `backend_claude.py` and `backend_codex.py`. prism-local's API-model backend (`backend_openai.py`, DeepSeek and other OpenAI-compatible APIs) was removed in #72: the proof agent runs on the Claude Code or Codex CLI.
- The page: `static/`, with vendored CodeMirror 5 and PDF.js.

## Left out

- The multi-project Home page and its server: `hub.py`, `static/home.*`.
- The port registry (`registry.py`), page presence and idle exit (`presence.py`), the launcher and `bin/`. proof-cli's own server and proof map do those jobs.

## Changed on import

- Imports are package-relative.
- The allowed Claude account comes from `$PROOF_CLAUDE_ACCOUNT`, not from the Home page's settings.
- A build on a machine with no TeX engine and no Tectonic reports `"unavailable": true` rather than looking like a failed build.

## Still to change

This package still serves one folder per process, through module globals. #69 makes it serve nodes inside proof-cli's server.

## Licences

prism-local is MIT, © 2026 Zhiyuan Deng (`LICENSE`). The vendored libraries keep their own licences: CodeMirror (MIT, `static/vendor/LICENSE-codemirror`), PDF.js (Apache-2.0, `static/vendor/LICENSE-pdfjs`) and KaTeX (MIT, `static/vendor/LICENSE-katex`).

## KaTeX

The key-ideas summaries (ADR-0013) typeset their `$…$` and `$$…$$` with [KaTeX](https://katex.org) **0.18.9**, vendored from the npm tarball `katex-0.18.9.tgz` (integrity `sha512-8ad9RyoKsb/g8/yLFE+KAlP+DhbCTRUNi/V9XGsxn0R+trJJltNwzcDNo0q/DEkOy5fQUQTAQyCXCYSE+OakTQ==`):
`dist/katex.min.js` and `dist/katex.min.css` as `static/vendor/katex.min.*`, and the twenty `dist/fonts/*.woff2` as `static/vendor/fonts/`. The `.woff` and `.ttf` fallbacks the stylesheet also names are left out; every browser the studio supports loads `.woff2`. `static/mathtext.js` calls it; the map page loads the same files from `/static/shared/`. Nothing is fetched from the network. To update, replace those files from a newer tarball and change the version here.
