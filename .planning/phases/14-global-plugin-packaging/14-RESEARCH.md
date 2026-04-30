# Phase 14 Research: Global Plugin Packaging

**Gathered:** 2026-04-30
**Status:** Complete

## Reusable Capabilities

- A repo-local plugin prototype already exists at `plugins/proof-routing/` with:
  - a non-placeholder `plugin.json`
  - an `.mcp.json` file
  - a Python MCP server script
  - a plugin-local skill
- The repository already has a repo-local marketplace entry at `.agents/plugins/marketplace.json`.
- The MCP server already routes into `proof codex`, preserving the existing wrapper and trust boundary.
- `tests/test_proof_routing_plugin.py` already verifies both tool registration and theorem-add command routing behavior.

## Missing Pieces

- There is no home-local install path yet under `~/plugins/proof-routing`.
- There is no `~/.agents/plugins/marketplace.json` entry for the global plugin path.
- There is no single install/sync path that moves the plugin from repo-local source to a reusable global footprint.
- The current MCP config uses a repo-relative script path, which is appropriate for repo-local use but not yet generalized for home-local installation.
- There is no phase-scoped documentation yet describing the packaging workflow or how the global copy should relate to the repo-local debug copy.

## Recommended Workstreams

1. **Define the canonical home-local plugin layout**
   - Choose a single target such as `~/plugins/proof-routing`.
   - Mirror the repo-local plugin structure closely to reduce drift.
   - Ensure the manifest and MCP config remain valid after relocation.

2. **Add a deterministic installation or sync path**
   - Provide a script or equivalent repeatable workflow that copies or syncs the plugin from the repo into the home-local plugin directory.
   - Ensure the process also creates or updates `~/.agents/plugins/marketplace.json`.
   - Avoid hidden side effects outside the intended plugin and marketplace locations.

3. **Normalize MCP configuration for global use**
   - Ensure `.mcp.json` points at a valid script path once the plugin lives under `~/plugins`.
   - Keep the server running against the local `proof` executable and current Proof CLI package, not a second forked implementation.
   - Confirm that the global packaging path still supports the same core tool set already validated in repo-local tests.

4. **Add packaging verification**
   - Add tests for install/sync path generation where feasible.
   - Verify the home-local plugin directory shape and marketplace entry shape.
   - Preserve existing plugin tool tests so packaging changes do not invalidate the current MCP surface.

## Risks and Ambiguities

- If repo-local and home-local copies drift, the user may debug one plugin while Codex loads another.
- If the MCP script path is hardcoded to a repo-only location, the home-local plugin may look installed but fail at runtime.
- If install/sync steps are too manual, the user may not be able to tell whether Codex is using the new global plugin or stale local skill behavior.
- If the global marketplace file is created inconsistently, plugin discovery may fail silently.

## Decision Summary

- Treat the repo-local plugin as the editable source and the home-local copy as the install target.
- Add a repeatable installation or sync workflow rather than relying on hand-copying plugin files.
- Keep plugin tools routing through `proof codex`.
- Validate packaging shape and marketplace shape in addition to existing tool-registration tests.

## Validation Architecture

- **Framework:** pytest plus deterministic filesystem checks
- **Quick run command:** `pytest tests/test_proof_routing_plugin.py -q`
- **Full run command:** `pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- **Validation focus:** confirm that the global packaging path preserves a valid plugin manifest, MCP config, marketplace entry, and tool-backed routing surface
- **Evidence sources:** generated home-local plugin files, generated marketplace file, plugin tool registration tests, and existing wrapper-backed workflow tests

---

*Phase: 14-global-plugin-packaging*
*Context gathered: 2026-04-30*
