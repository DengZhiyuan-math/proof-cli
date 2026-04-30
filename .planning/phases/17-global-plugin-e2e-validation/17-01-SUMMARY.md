---
phase: 17-global-plugin-e2e-validation
plan: 01
subsystem: codex-plugin
tags: [plugin, e2e, validation, install, workflow]

# Dependency graph
requires:
  - phase: 14-global-plugin-packaging
    provides: an installable home-local plugin
  - phase: 15-tool-backed-proof-surface
    provides: a practical proof tool inventory
  - phase: 16-activation-and-entry-unification
    provides: a clear entry hierarchy and verification path
provides:
  - installed-copy validation for the global plugin workflow
  - a short documented user verification path
  - closure of the final activation requirement for v1.3
affects:
  - phase 17 completion status
  - milestone audit and completion readiness

# Tech tracking
tech-stack:
  verified: [installed-copy MCP server loading, wrapper-backed doctor/status flow, pytest e2e coverage]
  patterns: [installed-copy-validation, plugin-first-evidence, short-user-verification-path]

key-files:
  verified:
    [
      plugins/proof-routing/README.md,
      tests/test_proof_routing_plugin.py,
      .planning/phases/17-global-plugin-e2e-validation/17-01-SUMMARY.md,
    ]
  no_source_changes: false

key-decisions:
  - "Used the installed home-local plugin copy as the main validation target rather than the repo-local source tree."
  - "Kept the E2E story intentionally short: install, doctor, status."
  - "Treated plugin-backed workflow evidence as primary and raw CLI behavior as supporting context."

patterns-established:
  - "Pattern 1: final plugin validation should run against the installed copy, not only the source copy."
  - "Pattern 2: short verification paths are more useful than large synthetic scripts when proving operational usability."
  - "Pattern 3: plugin-backed proof work should be validated through the same wrapper-backed flows the user is expected to trust."

requirements-completed: [ACTV-03]

# Metrics
duration: installed-copy-e2e-validation
completed: 2026-04-30
---

# Phase 17: Global Plugin E2E Validation Summary

## Performance

- **Completed:** 2026-04-30
- **Tasks:** 3 validation tasks
- **Files modified:** plugin README, plugin tests, milestone state docs

## Accomplishments

- Added an installed-copy E2E test that:
  - installs the plugin into a temporary home
  - loads the installed MCP server script
  - runs `doctor`
  - runs `status`
- Shortened and clarified the README verification story so a user can follow the same path manually.
- Proved that the global plugin workflow now works as more than a manifest/package artifact; it behaves like a usable installed Codex integration.

## Verification

- `python -m pytest tests/test_proof_routing_plugin.py -q`
- Result: `7 passed`
- `python -m pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- Result: `29 passed`

## Notes

- This phase closes the v1.3 milestone's final requirement by validating the installed plugin copy directly.
- The next natural step is milestone audit and completion, not more plugin-surface work inside v1.3.

---
*Phase: 17-global-plugin-e2e-validation*
*Completed: 2026-04-30*
