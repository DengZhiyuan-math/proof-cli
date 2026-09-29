## Project

**Mathematical Proof CLI / Research Proof OS**

This is a human-machine collaborative proof operating system for research mathematics. It is not trying to replace mathematicians or fully formalize every proof step; it is trying to make proof work stateful, debuggable, and trustworthy.

The CLI should help a researcher manage a proof map of nodes (theorems, lemmas, claims and imported results), their dependencies and their proofs, so long-running proof work can survive context loss and stay auditable.

**Core Value:** Manage the trust boundary around mathematical proof work: know which proof-map nodes can be called (Accepted nodes, and imported results with a Reference review), under what assumptions, and which nodes remain open. The legacy contracts, obligations, blockers and reference records are not a trust source (ADR-0012).

### Constraints

- **Human-in-the-loop**: Final acceptance must stay with the researcher — the system can suggest and check, but not silently decide
- **Retrieval-first**: The proof map's Accepted nodes and Reference-reviewed imported results must be checked before any new proof search
- **Local-state-first**: Long tasks must survive context loss through persisted project state
- **CLI-first**: The CLI is the primary interface for researchers and agents; a local web app for visualizing proof dependencies is planned as part of the proof-map refactor
- **No full kernel in v1**: The first release should support rigorous collaboration without attempting a complete formal logic foundation

## Technology Stack

- **Python 3.11+**, packaged with setuptools (`pyproject.toml`), source under `src/proof_cli/`
- **Typer** for the CLI (the `proof` entry point, rooted by `--root` or `$PROOF_ROOT`), **Rich** for terminal output, **Pydantic v2** for domain models
- **SQLite** project state at `.proof/project.sqlite3`, collaboration state and memory included (the `side_documents` table; legacy `.proof/collaboration.json` and `.proof/memory.json` are migrated once and not read again)
- **pytest** for tests (`tests/`)

## Workflow

Development follows the Pocock engineering skills (`/wayfinder`, `/to-spec`, `/to-tickets`, `/implement`, `/tdd`, ...), with work tracked in GitHub Issues. The GSD workflow has been retired: `.planning/` is kept as a read-only archive of milestones v1.0–v1.3 and earlier research, and is not a source of current plans.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on DengZhiyuan-math/proof-cli (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.
