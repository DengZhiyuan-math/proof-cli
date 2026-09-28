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

Decisions that change what the project trusts (accepting a Candidate proof, Reference review, dismissing a Challenge, promoting, force-releasing a claim) are made only in the local review app, signed with the researcher's passkey (ADR-0009):

```bash
proof review serve      # start the review app for this project
proof review open <id>  # open a node's decision page
```

No CLI command or agent tool can make them. Those commands answer `HUMAN_REVIEW_REQUIRED` with the page's URL. An agent that claims a node gets a claim token back, and needs it to submit or release.

Proof state is persisted locally. Generated workspace state under `.proof/` is intentionally excluded from version control.

## Project principles

- Human-in-the-loop: the system suggests and checks; researchers make final trust decisions.
- Retrieval-first: existing project results and trusted references are checked before new proof search.
- Local-state-first: long-running work survives context loss through persisted project state.
- CLI-first: the initial workflow is terminal-native.
- No full kernel in v1: explicit contracts, checks, and review boundaries come first.
