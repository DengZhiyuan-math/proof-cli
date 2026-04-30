---
phase: 10-command-invocation-surface
plan: 01
subsystem: codex-routing
tags: [codex, wrapper, command-routing, skills, usability]

# Dependency graph
requires:
  - phase: 08-retrieval-and-snapshots
    provides: JSON-first retrieval and analysis outputs that a wrapper can expose directly
  - phase: 09-radial-system-validation
    provides: a realistic proof-work inspection slice for wrapper smoke tests
provides:
  - a hard `proof codex` wrapper surface for guided read-only command routing
  - deterministic common-case root resolution for project-local and global Codex use
  - aligned global and project-local skill vocabulary that points at the same wrapper semantics
affects:
  - phase 10 completion status
  - phase 11 readiness for mutation routing

# Tech tracking
tech-stack:
  verified: [Typer subcommand wrapper, editable console entry point, pytest smoke coverage]
  patterns: [wrapper-not-rewrite, guided catalog output, JSON-preserving read-only routing]

key-files:
  verified:
    [
      src/proof_cli/codex_router.py,
      src/proof_cli/cli.py,
      pyproject.toml,
      tests/test_cli.py,
      .agents/skills/proof/SKILL.md,
      .agents/skills/proof-cli/SKILL.md,
      /Users/zhdeng/.codex/skills/proof/SKILL.md,
      /Users/zhdeng/.codex/skills/proof-cli/SKILL.md,
    ]
  no_source_changes: false

key-decisions:
  - "Introduced `proof codex` as the hard Codex-facing wrapper instead of trying to make skill prose carry execution semantics alone."
  - "Kept Proof CLI as the execution engine and source of truth by routing the wrapper into existing command handlers."
  - "Made the default discovery path human-readable while preserving raw JSON for retrieval and project analysis."
  - "Kept mutation entry points visible in the wrapper, but intentionally left full mutation hardening to Phase 11."

patterns-established:
  - "Pattern 1: Codex-facing command UX should wrap existing proof-state logic, not duplicate it."
  - "Pattern 2: Read-only wrapper commands may add guidance, but JSON-oriented commands must preserve machine-readable payloads."
  - "Pattern 3: Root resolution should be explicit enough to explain itself in the catalog and stable enough for ordinary workspace use."

requirements-completed: [CMD-01, CMD-02, CMD-03]

# Metrics
duration: implementation-plus-smoke-tests
completed: 2026-04-30
---

# Phase 10: Command Invocation Surface Summary

## Performance

- **Completed:** 2026-04-30
- **Tasks:** 3 implementation and verification tasks
- **Files modified:** Codex wrapper, CLI wiring, console script registration, skills, and smoke tests

## Accomplishments

- Added a new `proof codex` wrapper surface and a matching `proof-codex` console entry point.
- Added a guided catalog that shows the selected root, command groups, and likely next actions inside Codex or the terminal.
- Added deterministic common-case root resolution through explicit `--root`, `PROOF_ROOT`, workspace discovery, repo discovery, and fallback behavior.
- Kept `retrieve` and `project analyze` machine-readable while exposing status/list/search commands through a more human-friendly surface.
- Aligned project-local and global Codex skills so `$proof ...` points at the same wrapper semantics.
- Added smoke tests proving the wrapper reaches real proof-work commands rather than only parsing text.

## Verification

- `python -m pytest tests/test_cli.py -q`
- Result: `11 passed`
- `python -m pytest tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- Result: `16 passed`
- `proof codex --help`
- `proof-codex where`

## Notes

- Phase 10 intentionally leaves full mutation routing for the next phase; the wrapper exposes guided mutation entry points now so the user-facing command vocabulary can stabilize first.
- The wrapper is terminal-native and Codex-native, not a browser UI, which keeps the milestone aligned with the CLI-first constraint.

---
*Phase: 10-command-invocation-surface*
*Completed: 2026-04-30*
