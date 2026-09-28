# Mathematical Proof CLI

Mathematical Proof CLI is a local-first research proof operating system for human–machine collaboration. It keeps theorem contracts, proof state, dependencies, blockers, imported results, and outstanding proof obligations explicit and auditable.

The project is designed to support rigorous research workflows without replacing the mathematician or attempting to provide a full formal kernel. Final acceptance remains with the researcher.

## Requirements

- Python 3.11 or newer

## Install for development

```bash
python -m pip install -e ".[dev]"
```

## Command-line entry points

```bash
proof --help
proof codex
proof-codex status
proof codex doctor
```

## Writing a proof

Each local proof map node has a standalone LaTeX document, `proofs/<id>/proof.tex`, created with the node. It `\input`s the project's shared `proofs/preamble.tex` and compiles on its own. Agents and the researcher edit it directly. The folder `proofs/<id>/` is an ordinary LaTeX project, which [prism-local](https://github.com/DengZhiyuan-math/Local-Ai-agent-for-latex) or any editor can open. When the proof is ready:

```bash
proof node request-review <id> --rationale "why it is scoped to prove directly"
```

This copies the working file to an immutable snapshot, `proofs/<id>/snapshots/v<N>.tex`, and records its SHA-256. Review is always of a snapshot, never of the working file (ADR-0010).

## Human Review

Decisions that change what the project trusts (accepting a Candidate proof, Reference review, dismissing a Challenge, promoting) are made only on the project's local proof map page:

```bash
proof review serve      # start the page for this project
proof review open <id>  # open a node's decision page
```

Each decision is one line in the node's git-tracked `proofs/<id>/reviews.jsonl`, naming the SHA-256 of the snapshot it decides on. proof-cli commits that line together with the snapshot, as your own git identity (`user.name` / `user.email`); it never pushes. Once you push, the commit on GitHub is the record of who decided what (ADR-0010). Outside a git repository the decision is still recorded, just without that record. `proof review warnings` lists decisions git doesn't have yet.

No CLI command or agent tool can make these decisions. Those commands answer `HUMAN_REVIEW_REQUIRED` with the page's URL. That is a boundary for cooperative agents on your own machine, not a security mechanism, which suits personal use or a small team on GitHub. A project from before ADR-0010 has its decisions moved into `reviews.jsonl` the first time it's opened, and every node keeps its state.

A claim is a wayfinder-style assignment, not a lock (ADR-0010). `proof node claim <id> --assignee <name>` marks a frontier node as taken so that other agents skip it. `--reassign` takes over a stale claim, and `proof node unassign <id> --by <name>` clears one. `proof frontier` lists the open, unblocked, unclaimed nodes with their three state axes.

Proof state is persisted locally. Generated workspace state under `.proof/` is intentionally excluded from version control.

## Project principles

- Human-in-the-loop: the system suggests and checks; researchers make final trust decisions.
- Retrieval-first: existing project results and trusted references are checked before new proof search.
- Local-state-first: long-running work survives context loss through persisted project state.
- CLI-first: the initial workflow is terminal-native.
- No full kernel in v1: explicit contracts, checks, and review boundaries come first.
