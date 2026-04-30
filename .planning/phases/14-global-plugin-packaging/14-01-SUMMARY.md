---
phase: 14-global-plugin-packaging
plan: 01
subsystem: codex-plugin
tags: [plugin, packaging, marketplace, mcp, codex]

# Dependency graph
requires:
  - phase: 13-codex-e2e-validation
    provides: a working repo-local wrapper and plugin prototype to globalize
provides:
  - a deterministic home-local install path for the Proof Routing plugin
  - plugin-relative MCP wiring suitable for relocation outside the repo
  - packaging tests that prove the plugin shape and marketplace entry are valid
affects:
  - phase 14 completion status
  - phase 15 readiness for expanding the plugin-backed tool surface

# Tech tracking
tech-stack:
  verified: [FastMCP plugin server, home-local installer script, pytest packaging coverage]
  patterns: [repo-source-to-home-install, plugin-relative-mcp, wrapper-not-rewrite]

key-files:
  verified:
    [
      plugins/proof-routing/.mcp.json,
      plugins/proof-routing/scripts/proof_mcp_server.py,
      plugins/proof-routing/scripts/install_home_plugin.py,
      tests/test_proof_routing_plugin.py,
      .planning/phases/14-global-plugin-packaging/14-01-SUMMARY.md,
    ]
  no_source_changes: false

key-decisions:
  - "Made the repo-local plugin the editable source and the home-local plugin the installation target."
  - "Changed MCP script paths to be plugin-relative so the plugin remains valid after relocation."
  - "Added a deterministic installer that writes both `~/plugins/proof-routing` and `~/.agents/plugins/marketplace.json`."
  - "Kept plugin tools routing through `proof codex` rather than moving proof-state semantics into the plugin."

patterns-established:
  - "Pattern 1: plugin packaging should sync from the repo source rather than hand-maintaining a second copy."
  - "Pattern 2: MCP config must be valid relative to the installed plugin root, not the repo root."
  - "Pattern 3: packaging validation should cover both manifest shape and continued command routing."

requirements-completed: [GPLG-01, GPLG-02, GPLG-03]

# Metrics
duration: implementation-plus-packaging-tests
completed: 2026-04-30
---

# Phase 14: Global Plugin Packaging Summary

## Performance

- **Completed:** 2026-04-30
- **Tasks:** 3 packaging and verification tasks
- **Files modified:** plugin MCP config, plugin server defaults, home-local installer, packaging tests, milestone state docs

## Accomplishments

- Added a real home-local installer at `plugins/proof-routing/scripts/install_home_plugin.py`.
- Made `.mcp.json` plugin-relative so the MCP server path works after copying the plugin outside the repo.
- Relaxed plugin server root defaults so the global plugin no longer depends on a hardcoded repo root.
- Verified that the installer creates:
  - `~/plugins/proof-routing`
  - `~/.agents/plugins/marketplace.json`
- Extended plugin tests to cover:
  - tool registration
  - theorem routing
  - MCP config shape
  - home-local installation and marketplace generation

## Verification

- `python -m pytest tests/test_proof_routing_plugin.py -q`
- Result: `4 passed`
- `python plugins/proof-routing/scripts/install_home_plugin.py --home /tmp/proof-plugin-home-test`
- Result: home-local plugin and marketplace files created successfully
- `python -m pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- Result: `26 passed`

## Notes

- This phase deliberately stopped at packaging and relocation correctness; it did not yet expand the tool catalog or write end-user install guidance.
- The next natural step is Phase 15: make the plugin-backed proof surface broader and more explicitly first-class.

---
*Phase: 14-global-plugin-packaging*
*Completed: 2026-04-30*
