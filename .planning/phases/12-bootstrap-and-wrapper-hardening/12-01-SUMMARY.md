---
phase: 12-bootstrap-and-wrapper-hardening
plan: 01
subsystem: codex-routing
tags: [codex, wrapper, diagnostics, bootstrap, skills]

# Dependency graph
requires:
  - phase: 10-command-invocation-surface
    provides: the hard wrapper surface and read-only command catalog
  - phase: 11-mutation-routing-and-root-resolution
    provides: mutation-capable wrapper routing and explicit root messaging
provides:
  - explicit command-readiness diagnostics for `proof` and `proof-codex`
  - non-automatic recovery guidance for degraded command-entry states
  - clearer separation between canonical global skills and project-local debug skills
affects:
  - phase 12 completion status
  - phase 13 readiness for end-to-end validation

# Tech tracking
tech-stack:
  verified: [Typer diagnostics command, CLI smoke coverage, installed console entrypoints]
  patterns: [diagnose-dont-install, canonical-global-skill, degraded-state-smoke-tests]

key-files:
  verified:
    [
      src/proof_cli/codex_router.py,
      tests/test_cli.py,
      .agents/skills/proof/SKILL.md,
      .agents/skills/proof-cli/SKILL.md,
      /Users/zhdeng/.codex/skills/proof/SKILL.md,
      /Users/zhdeng/.codex/skills/proof-cli/SKILL.md,
    ]
  no_source_changes: false

key-decisions:
  - "Implemented a `proof codex doctor` surface rather than automatic installation or repair."
  - "Kept recovery advisory-only: the system explains the next command but does not mutate the environment."
  - "Marked the global `~/.codex/skills/proof/` skill as canonical and reframed project-local skills as debugging/development helpers."
  - "Extended the wrapper catalog with readiness status so degraded command-layer states become visible early."

patterns-established:
  - "Pattern 1: degraded command-layer states should be categorized and explained, not silently repaired."
  - "Pattern 2: global skill routing should be treated as the production entry path, while repo-local skills stay development-scoped."
  - "Pattern 3: hardening work should preserve the existing happy path and prove degraded behavior with smoke tests."

requirements-completed: [BST-01, BST-02]

# Metrics
duration: implementation-plus-smoke-tests
completed: 2026-04-30
---

# Phase 12: Bootstrap and Wrapper Hardening Summary

## Performance

- **Completed:** 2026-04-30
- **Tasks:** 3 implementation and verification tasks
- **Files modified:** wrapper diagnostics, skills, and CLI smoke tests

## Accomplishments

- Added `proof codex doctor` as a command-readiness diagnostic surface.
- Added readiness visibility to the wrapper catalog.
- Standardized degraded-state messaging for missing `proof` and `proof-codex` availability.
- Kept recovery advisory-only: the wrapper now suggests next commands but does not auto-install or auto-repair.
- Clarified that the global `~/.codex/skills/proof/` skill is canonical, while project-local skills are for repository debugging and development.
- Added degraded-state smoke tests without regressing the normal wrapper behavior.

## Verification

- `python -m pytest tests/test_cli.py -q`
- Result: `16 passed`
- `python -m pytest tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- Result: `21 passed`
- `proof codex doctor`
- `proof-codex --help`

## Notes

- This phase intentionally does not auto-install dependencies, even when diagnostics detect missing entrypoints.
- The next phase can now validate the full theorem workflow against a hardened command surface rather than a best-effort wrapper.

---
*Phase: 12-bootstrap-and-wrapper-hardening*
*Completed: 2026-04-30*
