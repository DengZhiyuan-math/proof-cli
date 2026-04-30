---
phase: 15-tool-backed-proof-surface
plan: 01
subsystem: codex-plugin
tags: [plugin, tools, proof-surface, mcp, wrapper]

# Dependency graph
requires:
  - phase: 14-global-plugin-packaging
    provides: a relocatable home-local plugin with valid MCP wiring
provides:
  - a broader plugin-backed proof workspace tool surface
  - alignment between plugin tool inventory and the existing Proof Codex wrapper
  - tests that lock the expanded tool inventory to real wrapper routing
affects:
  - phase 15 completion status
  - phase 16 readiness for activation and entry unification

# Tech tracking
tech-stack:
  verified: [FastMCP tool expansion, wrapper-backed command routing, pytest tool-surface coverage]
  patterns: [tool-surface-parity, wrapper-backed-tools, explicit-proof-actions]

key-files:
  verified:
    [
      plugins/proof-routing/scripts/proof_mcp_server.py,
      plugins/proof-routing/skills/proof-routing/SKILL.md,
      tests/test_proof_routing_plugin.py,
      .planning/phases/15-tool-backed-proof-surface/15-01-SUMMARY.md,
    ]
  no_source_changes: false

key-decisions:
  - "Expanded the plugin tool inventory to match more of the existing `proof codex` wrapper surface."
  - "Kept tool naming flat and explicit so Codex can call proof operations without extra routing ambiguity."
  - "Preserved the wrapper as the execution boundary instead of bypassing it from MCP tools."

patterns-established:
  - "Pattern 1: plugin tools should achieve parity with existing wrapper commands where those commands are already stable."
  - "Pattern 2: explicit tool names are preferable to hidden grouped subcommand magic at the MCP boundary."
  - "Pattern 3: plugin expansion should be validated through representative routed commands, not just tool registration counts."

requirements-completed: [TOOL-01, TOOL-02, TOOL-03]

# Metrics
duration: implementation-plus-tool-surface-tests
completed: 2026-04-30
---

# Phase 15: Tool-Backed Proof Surface Summary

## Performance

- **Completed:** 2026-04-30
- **Tasks:** 3 tool-surface and verification tasks
- **Files modified:** plugin MCP server, plugin-local skill guidance, plugin tests, milestone state docs

## Accomplishments

- Expanded the plugin tool surface with:
  - `theorem_show`
  - `obligation_list`
  - `blocker_list`
  - `search`
  - `project_analyze`
- Kept all new tools routing through `proof codex`, so the plugin still does not own proof-state semantics.
- Brought the plugin tool inventory much closer to the real wrapper surface needed for everyday proof inspection and core mutation workflows.
- Extended tests to verify both:
  - the full tool inventory
  - representative command routing for project analysis

## Verification

- `python -m pytest tests/test_proof_routing_plugin.py -q`
- Result: `5 passed`
- `python -m pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- Result: `27 passed`

## Notes

- This phase made the plugin practically useful as a proof-work tool surface, but it did not yet settle user-facing activation guidance or the exact relationship between `$proof ...` and plugin tools.
- The next natural step is Phase 16: unify entry semantics and document the shortest reliable activation path.

---
*Phase: 15-tool-backed-proof-surface*
*Completed: 2026-04-30*
