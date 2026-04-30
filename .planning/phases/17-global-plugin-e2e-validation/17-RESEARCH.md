# Phase 17 Research: Global Plugin E2E Validation

**Gathered:** 2026-04-30
**Status:** Complete

## Findings

- The installer already supports a synthetic home path, which makes end-to-end validation easy to automate with a temporary directory.
- The installed plugin copy can be loaded directly from its installed script path.
- The strongest realistic validation path is:
  1. install plugin to a temp home
  2. load the installed MCP server
  3. call `doctor`
  4. call `status`
  5. call one core mutation or workflow step if needed

## Recommendation

- Automate the installed-copy validation in `tests/test_proof_routing_plugin.py`.
- Keep the README verification path short and aligned with the same story.

---

*Phase: 17-global-plugin-e2e-validation*
*Context gathered: 2026-04-30*
