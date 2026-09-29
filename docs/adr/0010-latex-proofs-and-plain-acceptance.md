# LaTeX proof files, a plain Acceptance, and prism-local as a loosely coupled editor

**Status**: accepted. Supersedes ADR-0003 and ADR-0009, and amends ADR-0006 and ADR-0007. Point 5 and the note that proof-cli needs no TeX are superseded by ADR-0011, which also amends the snapshot of point 2 (every input frozen as `snapshots/v<N>/`). ADR-0013 amends point 2 again: a snapshot also freezes the node's key-ideas summary, `key-ideas.md`, and requesting review needs one.

proof-cli's intended use is **personal and local, or a small team working through a GitHub repository**. The Markdown proof vault (ADR-0003) and the passkey-signed Human Review (ADR-0009) were built for a stronger threat model than that. They cost a lot: WebAuthn ceremonies, hash chains, a legacy cutoff, a trust pin, and a long tail of audit tickets. Meanwhile the Markdown view kept mangling mathematics. For example, `(f * g) * h` lost its asterisks, and a line starting `- x^2` turned into a bullet. Researchers already read and write mathematics in LaTeX and PDF. The author's own [prism-local](https://github.com/DengZhiyuan-math/Local-Ai-agent-for-latex) is a local LaTeX studio (editor, compile, PDF with SyncTeX, an AI agent panel with per-turn undo) built for exactly that.

The two tools have different centres of gravity:
- **proof-cli** is an **agent-led** proof system: the map, the node states, the frontier, and what agents may pick up next.
- **prism-local** is a **human-led**, AI-assisted LaTeX editor.

They should work together without depending on each other.

## Decided

1. **A node's proof is a standalone LaTeX document.**
   - Each local node has one working file, `proofs/<node-id>/proof.tex`. It is a complete document: `\documentclass`, then `\input{../preamble}` for the project's shared `proofs/preamble.tex` (macros and theorem environments), then the proof.
   - It compiles on its own to its own PDF, so the researcher reviews one node as one PDF.
   - A combined document that `\input`s nodes in dependency order may come later. It is not part of this decision.
2. **Agents write proofs directly.**
   - Agents edit the working file freely, as does the researcher. The claim, submit and immutable-version ceremony (ADR-0003, ADR-0006 §submit) no longer gates writing.
   - **A claim is a wayfinder-style assignment, not a lock.** It works like a wayfinder ticket's assignee. Before starting work on a node, an agent assigns the node to itself, and that assignee *is* the claim. The **frontier** is the open, unblocked, unclaimed nodes. A claim is transitional, a planning signal that tells concurrent agents to skip the node. It ends when its holder requests review or unassigns.
   - Therefore: no claim token, no signed force-release, and no exclusivity enforced beyond the one-assignee-per-node record. A stale claim is simply reassigned or cleared, by the researcher or by agreement. A claim never gates editing the working file.
   - When the author thinks a proof is ready, they **request review**. That records a **snapshot**: `proofs/<node-id>/snapshots/v<N>.tex`, a copy of the working file, never overwritten, with its SHA-256 recorded in SQLite. Snapshots sit in a subfolder because prism-local takes a folder's first `.tex` with a `\documentclass` as its main file when there's no `main.tex`. Review is always of a snapshot, never of the moving working file.
     - *Amended by ADR-0011:* a snapshot now freezes every input of the proof, the node's working sources and the shared preamble, as `snapshots/v<N>/` with a manifest whose SHA-256 decisions bind. Single-file snapshots stay readable.
     - *Amended by ADR-0013:* among those inputs is the node's key-ideas summary, `key-ideas.md` (核心思路, 主要步骤, 难点, 未覆盖), which review starts from. Requesting review needs it (`KEY_IDEAS_REQUIRED`), and a change to it alone is a new snapshot. Older snapshots without one stay reviewable.
3. **Acceptance is a plain, recorded action by the researcher, and git is its record.**
   - Accept, revision requested and reject are recorded with who decided, when, the rationale, and the snapshot's SHA-256.
   - **The reviewer is a GitHub identity.** Each decision is written to a git-tracked text record, `proofs/<node-id>/reviews.jsonl` (one line per decision), and committed together with the snapshot it decides on. The commit's author is the reviewer. Once pushed, the commit on GitHub is the evidence of who accepted or changed what, and when. SQLite keeps only an index of these records, rebuilt from them.
   - **Verification is the snapshot's `.tex` hash plus git history.** A decision counts for the snapshot whose SHA-256 it names, and git shows the snapshot never changed. A compiled PDF may be archived next to the snapshot (`snapshots/v<N>.pdf`) for convenience, but it isn't required.
   - The researcher decides on the proof map page (point 4). The CLI, the Codex routes and MCP expose no command that makes a Human Review decision. That boundary is a convention for cooperative agents on the researcher's own machine, not a security mechanism.
   - The passkey, WebAuthn, hash-chain, trust-pin and legacy re-sign machinery of ADR-0009 is retired.
   - ADR-0004 still holds: only Human Review changes acceptance state, and an Evidence check never does.
4. **proof-cli owns its own entry point: the proof map page.** proof-cli's local web app becomes the map's home: the DAG and tree, the frontier, each node's three state axes, and the review actions (ADR-0008). A node's page shows the snapshot under review, with its PDF if one was built.
5. **prism-local is coupled only through files.**
   - *Superseded by ADR-0011:* prism-local's code is built into proof-cli as each local node's studio, served by the map's own server; there is no separate program to launch.
   - A node's folder `proofs/<node-id>/` is an ordinary LaTeX project that prism-local opens like any other, with `proof.tex` as its only top-level `.tex`, and so its main file. prism-local needs no knowledge of proof-cli, and proof-cli imports nothing from prism-local.
   - The map page offers **Open in prism-local**, which runs a configured `prism-local` executable on the node folder. If none is configured, the page shows the path.
   - prism-local's own agent panel and undo remain its own business. proof-cli sees only the resulting file changes.

## Consequences

- ADR-0003 (Markdown vault, one immutable file per attempt) is superseded. Existing `proofs/<node-id>/v<N>.md` files are kept as read-only history and never converted automatically.
- ADR-0009 is superseded, along with the parts of #35, #36, #38 and #42 that exist only to harden signatures. A project's existing decisions move from the SQLite `review_history` table into `reviews.jsonl` the first time it is opened, as plain decisions that keep their reviewer, time and rationale. A signed one keeps what it was signed over. An older unsigned one is bound to what it was made on as the project stands at migration: the Candidate proof its review was linked to, and the node's current interface and pins. Signatures no longer matter, so every node keeps the state its decisions give it, and nothing needs re-signing. A pre-#35 project reads exactly as that code read it. `review_history` keeps only generic, editorial reviews.
- A decision's `reviews.jsonl` line is written as its operation's SQLite transaction commits, while that transaction still holds the write lock, so concurrent decisions are ordered and a failed write rolls the operation back. The git commit follows. If it fails (for example on another process's `index.lock`), the decision stands, and `REVIEWS_NOT_COMMITTED` reports the file.
- ADR-0006 is amended: submit becomes "request review" on a snapshot, and a claim becomes a plain assignee. The claim token (#37) and the signed force-release (ADR-0009) go, and #17's remaining items shrink to the assignment record and the frontier's "unclaimed" filter.
- ADR-0007 is amended: the web app remains the one place Human Review decisions are made, now without a passkey.
- proof-cli doesn't need TeX installed. Compiling is prism-local's job, or the researcher's. The map page shows a PDF only when one exists next to the snapshot.
  - *Superseded by ADR-0011:* the studio compiles when a TeX distribution or Tectonic is installed; without one it still edits, snapshots and reviews.
- A cooperative agent can't make a decision through proof-cli, but an uncooperative one with the researcher's file permissions can edit anything, including `.proof/`. That is accepted for the personal and small-team scope. A decision that isn't in a commit by the reviewer's GitHub identity doesn't have the record behind it, and git history is where tampering would show.
- Review decisions leave the append-only SQLite `review_history` table (#33) for git-tracked `reviews.jsonl` files. Committing needs a git repository with a GitHub remote. Without one, decisions are still recorded locally, marked as not yet committed.
