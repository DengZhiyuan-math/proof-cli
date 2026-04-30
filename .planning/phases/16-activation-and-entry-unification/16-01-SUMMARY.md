---
phase: 16-activation-and-entry-unification
plan: 01
subsystem: codex-plugin
tags: [plugin, activation, docs, entrypoints, codex]

# Dependency graph
requires:
  - phase: 14-global-plugin-packaging
    provides: a globally installable plugin path
  - phase: 15-tool-backed-proof-surface
    provides: a practical plugin-backed proof tool surface
provides:
  - a single documented install and enablement path
  - a unified entry hierarchy across plugin tools, `proof codex`, and `$proof`
  - clearer separation between global usage and repo-local debugging
affects:
  - phase 16 completion status
  - phase 17 readiness for end-to-end user validation

# Tech tracking
tech-stack:
  verified: [plugin README, aligned skill wording, pytest documentation-presence coverage]
  patterns: [plugin-first-entry, codex-wrapper-fallback, repo-local-debug-boundary]

key-files:
  verified:
    [
      plugins/proof-routing/README.md,
      plugins/proof-routing/skills/proof-routing/SKILL.md,
      .agents/skills/proof/SKILL.md,
      .agents/skills/proof-cli/SKILL.md,
      /Users/zhdeng/.codex/skills/proof/SKILL.md,
      tests/test_proof_routing_plugin.py,
      .planning/phases/16-activation-and-entry-unification/16-01-SUMMARY.md,
    ]
  no_source_changes: false

key-decisions:
  - "Declared plugin-backed MCP tools the canonical Codex path once installed."
  - "Kept `proof codex ...` as the explicit CLI fallback and debugging surface."
  - "Reframed `$proof ...` as a compatibility trigger instead of the strongest execution guarantee."
  - "Made repo-local skills explicitly development-scoped."

patterns-established:
  - "Pattern 1: entry hierarchies should be documented explicitly once multiple surfaces coexist."
  - "Pattern 2: plugin tools can be canonical without removing the CLI fallback."
  - "Pattern 3: skill files should explain their relative role, not pretend every surface is primary."

requirements-completed: [TOOL-04, ACTV-01, ACTV-02]

# Metrics
duration: documentation-plus-entry-alignment
completed: 2026-04-30
---

# Phase 16: Activation and Entry Unification Summary

## Performance

- **Completed:** 2026-04-30
- **Tasks:** 3 documentation and entry-unification tasks
- **Files modified:** plugin README, plugin/local/global skill guidance, plugin tests, milestone state docs

## Accomplishments

- Added a single plugin README that explains:
  - install
  - enablement
  - verification
  - the relationship between plugin tools, `proof codex ...`, and `$proof ...`
- Established one entry hierarchy:
  - plugin-backed MCP tools first
  - `proof codex ...` second
  - `$proof ...` as compatibility only
- Clarified that repo-local `.agents/skills/` entries are for debugging and development, not the canonical everyday interface.
- Added a small automated check that the README keeps the entry hierarchy explicit.

## Verification

- `python -m pytest tests/test_proof_routing_plugin.py -q`
- Result: `6 passed`
- `python -m pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- Result: `28 passed`

## Notes

- This phase did not yet prove that a real user can follow the path successfully from start to finish; it only made that path explicit and internally consistent.
- The next natural step is Phase 17: run the plugin-backed global workflow as an end-to-end validation story.

---
*Phase: 16-activation-and-entry-unification*
*Completed: 2026-04-30*
