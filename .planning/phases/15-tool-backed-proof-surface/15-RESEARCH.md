# Phase 15 Research: Tool-Backed Proof Surface

**Gathered:** 2026-04-30
**Status:** Complete

## Reusable Capabilities

- `src/proof_cli/codex_router.py` already exposes all the wrapper commands the plugin needs to reach.
- The plugin server already has the `_run_proof_codex(...)` helper and an established FastMCP tool pattern.
- Packaging work from Phase 14 already made the plugin relocatable and test-backed.
- Existing tests already cover plugin tool registration and theorem-add routing, making extension straightforward.

## Missing Pieces

- The plugin does not yet expose theorem show, obligation list, blocker list, search, or project analysis.
- The current plugin tool inventory is therefore narrower than the wrapper command surface.
- The plugin-local skill text does not yet present the fuller tool surface that a real everyday proof workflow would need.

## Recommended Workstreams

1. Extend the plugin server with the missing read-only inspection tools.
2. Keep all new tools routing through `proof codex` rather than bypassing the wrapper.
3. Expand plugin tests to assert the complete expected tool inventory and representative command routing.
4. Keep naming stable and explicit so the tool surface is easy to understand from Codex.

## Risks and Ambiguities

- Tool naming may become inconsistent if the plugin drifts from wrapper command vocabulary.
- A plugin that exposes only some inspection tools may still force users back into raw CLI for normal work.
- Over-expanding into advanced workflows too early could blur the line between Phase 15 and later usability/documentation work.

## Decision Summary

- Match the plugin tool surface more closely to the wrapper surface.
- Prefer flat, explicit tool names that map predictably to wrapper commands.
- Validate the expanded tool inventory with tests immediately.

## Validation Architecture

- **Framework:** pytest
- **Quick run command:** `pytest tests/test_proof_routing_plugin.py -q`
- **Full run command:** `pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- **Validation focus:** expanded tool inventory and stable routing through `proof codex`

---

*Phase: 15-tool-backed-proof-surface*
*Context gathered: 2026-04-30*
