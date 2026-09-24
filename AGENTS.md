## Project

**Mathematical Proof CLI / Research Proof OS**

This is a human-machine collaborative proof operating system for research mathematics. It is not trying to replace mathematicians or fully formalize every proof step; it is trying to make proof work stateful, debuggable, and trustworthy.

The CLI should help a researcher manage theorem contracts, proof state, dependencies, blockers, and imported results so long-running proof work can survive context loss and stay auditable.

**Core Value:** Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

### Constraints

- **Human-in-the-loop**: Final acceptance must stay with the researcher — the system can suggest and check, but not silently decide
- **Retrieval-first**: Project results and trusted references must be checked before any new proof search
- **Local-state-first**: Long tasks must survive context loss through persisted project state
- **CLI-first**: The CLI is the primary interface for researchers and agents; a local web app for visualizing proof dependencies is planned as part of the proof-map refactor
- **No full kernel in v1**: The first release should support rigorous collaboration without attempting a complete formal logic foundation

## Technology Stack

- **Python 3.11+**, packaged with setuptools (`pyproject.toml`), source under `src/proof_cli/`
- **Typer** for the CLI (`proof`, `proof-codex` entry points), **Rich** for terminal output, **Pydantic v2** for domain models
- **SQLite** project state at `.proof/project.sqlite3` (plus JSON side files under `.proof/`)
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
