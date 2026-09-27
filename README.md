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
