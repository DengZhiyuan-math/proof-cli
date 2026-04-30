# Phase 14: Global Plugin Packaging - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase turns the current repo-local Proof Routing plugin prototype into a home-local plugin that can live under `~/plugins/...` and be referenced from `~/.agents/plugins/marketplace.json`.

The phase is about packaging, installation shape, marketplace registration, and MCP wiring completeness. It is not yet about broadening the proof tool surface or polishing the final user guidance. The main question for this phase is: can a user move from repository-local experimentation to a reusable global plugin footprint that Codex can discover consistently?

</domain>

<decisions>
## Implementation Decisions

### Packaging target
- **D-01:** The canonical install target for this phase is home-local, not repo-local: `~/plugins/proof-routing` plus `~/.agents/plugins/marketplace.json`.
- **D-02:** The repo-local plugin under `plugins/proof-routing` remains valuable as the source template and debug copy, but it should no longer be treated as the final everyday install location.
- **D-03:** The plugin name should remain `proof-routing` so repo-local and home-local copies share one identity.

### Discovery and manifest shape
- **D-04:** Codex discovery should depend on real plugin manifests and MCP config, not just `SKILL.md` prose.
- **D-05:** `.codex-plugin/plugin.json`, `.mcp.json`, and the marketplace entry must be complete enough to describe the plugin without placeholder fields.
- **D-06:** The plugin should expose its MCP server through a local script path and preserve the current `proof codex ...` wrapper as the execution engine behind that MCP layer.

### Trust boundary and ownership
- **D-07:** The Proof CLI remains the state authority. The plugin is a packaging and invocation layer, not a new proof-state owner.
- **D-08:** Home-local plugin installation should not silently replace repo-local debug behavior; both paths should be able to coexist during development.
- **D-09:** This phase should stop short of expanding the tool catalog unless packaging work requires a small manifest or MCP correction.

### the agent's Discretion
- Whether home-local installation is best implemented via a copy script, a sync script, or a documented manual command path.
- Whether the global marketplace file should be generated from the repo copy or written directly in home-local form.
- Whether the MCP server path should run against the repo checkout, an installed package, or a hybrid bootstrapping path.

</decisions>

<specifics>
## Specific Ideas

- The user explicitly wants a real Codex plugin/tool integration, not more skill-only routing.
- The immediate follow-up request was to:
  - copy the repo-local plugin into a home-local global plugin
  - document the minimal install/enable path
  - connect `$proof ...` semantics to the plugin tool surface
- A repo-local `plugins/proof-routing` prototype already exists, including:
  - plugin manifest
  - `.mcp.json`
  - MCP server script
  - plugin-local skill
- The current prototype already proves technical direction; Phase 14 is about packaging it into a reusable installation path.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `/Users/zhdeng/Proof CLI /.planning/PROJECT.md` - v1.3 milestone framing and plugin-integration intent
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md` - GPLG requirements and milestone scope
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md` - phase 14 goal, dependencies, and success criteria
- `/Users/zhdeng/Proof CLI /.planning/STATE.md` - current milestone status

### Existing plugin prototype
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/.codex-plugin/plugin.json` - current plugin manifest
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/.mcp.json` - current MCP server configuration
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/scripts/proof_mcp_server.py` - local MCP tool server
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/skills/proof-routing/SKILL.md` - plugin-local skill behavior
- `/Users/zhdeng/Proof CLI /.agents/plugins/marketplace.json` - repo-local marketplace entry

### Existing command and wrapper layer
- `/Users/zhdeng/Proof CLI /src/proof_cli/codex_router.py` - wrapper semantics that the plugin tools route through
- `/Users/zhdeng/Proof CLI /src/proof_cli/cli.py` - primary CLI registration and `proof` entrypoint
- `/Users/zhdeng/Proof CLI /pyproject.toml` - dependency and script registration

### Relevant tests
- `/Users/zhdeng/Proof CLI /tests/test_proof_routing_plugin.py` - plugin tool registration and command-routing coverage
- `/Users/zhdeng/Proof CLI /tests/test_cli.py` - current Codex wrapper behavior
- `/Users/zhdeng/Proof CLI /tests/test_retrieval.py` - retrieval command behavior
- `/Users/zhdeng/Proof CLI /tests/test_phase9_validation.py` - realistic theorem workflow coverage that later global-plugin validation should reuse

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The repo-local plugin prototype already provides the essential files for a Codex plugin footprint.
- The MCP server script already routes to `proof codex` rather than duplicating proof-state behavior.
- `tests/test_proof_routing_plugin.py` already proves that the current prototype registers a concrete tool set.

### Established Patterns
- The project has already established "wrapper, not rewrite" as a command-layer rule.
- The current plugin prototype uses the same rule at the MCP layer by shelling into `proof codex`.
- Repo-local `.agents/plugins/marketplace.json` is already present, so Phase 14 can mirror rather than invent marketplace structure.

### Integration Points
- The global plugin copy should stay aligned with the repo-local prototype to avoid divergence.
- Packaging work likely needs a sync or install script so the home-local plugin can be refreshed from the repo source.
- The final packaging path should keep the repo checkout useful for development while making the global plugin the canonical install target.

</code_context>

<deferred>
## Deferred Ideas

- Expanding the tool list beyond the current proof inspection and mutation core belongs to Phase 15.
- Final end-user guidance and entry unification belong to Phase 16.
- Full end-to-end install validation belongs to Phase 17.

</deferred>

---

*Phase: 14-global-plugin-packaging*
*Context gathered: 2026-04-30*
