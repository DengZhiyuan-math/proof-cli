---
name: "proof-cli-repo-dev"
description: "Working on the Mathematical Proof CLI repository, or on a proof project through its `proof` CLI"
metadata:
  short-description: "Proof CLI repo and proof-project helper"
---

# Proof CLI

`proof` is the one agent interface to a proof project (ADR-0006, ADR-0011). The researcher works on the proof map page (`proof map open`); agents use `proof`, with `--json` for one envelope per call.

## Rooting every call

Every command acts on `--root`, else `$PROOF_ROOT`, else the current folder. Inside a node's folder (`proofs/<id>/`), including a studio's agent panel, keep `PROOF_ROOT` set to the project root so each call reaches the project. A read on a folder with no project answers `PROJECT_NOT_FOUND` and creates nothing.

## Working a node

1. **Retrieval first.** Before any new proof search, read what the project already holds: `proof search`, `proof retrieve`, `proof node show <id>` (its `dependency_details` give each dependency's pin and the remedy a lagging pin needs), `proof reference list`, `proof memory list`.
2. **Pick up work.** `proof frontier` lists the open, unblocked, unclaimed nodes; `proof node claim <id> --assignee <name>` takes one. Use that same `<name>` in every later call on the node: a claimed node is its assignee's (`NOT_CLAIMANT` otherwise).
3. **Prove or split.** Write the proof in `proofs/<id>/proof.tex`. A node too large to prove directly is split into Claims instead: `proof node split <id> --child <child-id>=<statement> … --created-by <name>`.
4. **Hand over.** First write the proof's key ideas in `proofs/<id>/key-ideas.md`, under the headings `## 核心思路` (why it holds) and `## 主要步骤` (3–7 steps, each naming the dependency it uses), both required, then `## 难点` and `## 未覆盖` (「无」 if none); maths as `$…$` (ADR-0013). Then `proof node request-review <id> --rationale "<why this node is scoped to prove directly>" --requested-by <name>` snapshots the proof and its summary for the researcher; without the summary it answers `KEY_IDEAS_REQUIRED`. An Evidence check records only what a real checker reported: `proof node evidence record <candidate-proof-id> <outcome> --run-by <checker>`.
5. **Fog.** A difficulty not yet precise enough to be a Claim goes in the Proof fog, outside the map: `proof fog add "<text>" --near <id> --created-by <name>`, `proof fog list`, `proof fog show <fog-id>`. A computation about a fog item is an Experiment, recorded with its files in your node's `scratch/`: `proof fog experiment record <fog-id> <supports|refutes|inconclusive|error> --summary "<what it showed>" --run-by <name> --path proofs/<id>/scratch/<file>`; it never changes the item's status. When the idea can be stated: `proof fog crystallize <fog-id> <node-id> "<statement>" --created-by <name>` makes it a Claim (a single-child Split of its parent when it has one).

Human Review decisions (accept, reject, Reference review, dismissing a Challenge, …) belong to the researcher on the page; their commands answer `HUMAN_REVIEW_REQUIRED` with the page's URL.

## As a node's proof agent

A node's studio starts its agent in `proofs/<id>/` with `PROOF_ROOT` set to the project and its own brief (ADR-0011). The steps above are that brief. Files change only in the node's sources and `scratch/`; everything else goes through `proof`. Requesting review freezes the working inputs and shared preamble in `snapshots/v<N>/`, with a manifest; review is of that frozen snapshot.

## Working conventions

- Change project state through `proof`; the files under `.proof/` and `reviews.jsonl` are its record, not a place to edit.
- When a command is unavailable or fails, report the error and the next command to run.

## Developing the CLI

- Install with `python -m pip install -e ".[dev]"`; run `python -m pytest -q` after a change.
- Domain terms are in `CONTEXT.md`, decisions in `docs/adr/`, the error codes in `src/proof_cli/errors.py`.
