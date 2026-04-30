# Phase 15: Tool-Backed Proof Surface - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase expands the Proof Routing plugin from a minimally packaged prototype into a practical proof workspace tool surface.

The focus is not on plugin installation anymore; Phase 14 already established that path. The focus here is whether the plugin exposes enough first-class tools for real proof work inspection and core state mutation without forcing the user back to raw `proof codex ...` commands for common tasks.

</domain>

<decisions>
## Implementation Decisions

### Tool surface scope
- **D-01:** Read-only tools should cover the same common inspection surface already available through the wrapper: doctor, status, theorem list/show, obligation list, blocker list, search, retrieve, and project analysis.
- **D-02:** Core mutation tools should cover theorem add, obligation add, blocker add, and snapshot.
- **D-03:** This phase should expand the current plugin tool set rather than invent a second abstraction layer.

### Trust boundary
- **D-04:** Plugin tools must continue to route through `proof codex ...` so the existing wrapper remains the execution boundary.
- **D-05:** Root handling should remain explicit and optional; plugin tools should work with the current wrapper's root resolution rather than silently choosing a different policy.
- **D-06:** The plugin should still feel like a tool surface, not a hidden shell alias.

### Coexistence
- **D-07:** The repo-local debug path and the global plugin path should continue to share the same tool semantics.
- **D-08:** Phase 15 can improve plugin-local skill guidance only where it helps the tool surface stay accurate and discoverable.

### the agent's Discretion
- Whether the plugin should expose flat tool names (`theorem_show`) or more grouped naming.
- Whether to add a lightweight metadata or manifest view for tools in this phase, or defer that to activation guidance.

</decisions>

<specifics>
## Specific Ideas

- The current plugin already exposes:
  - `doctor`
  - `status`
  - `init`
  - `theorem_list`
  - `theorem_add`
  - `obligation_add`
  - `blocker_add`
  - `retrieve`
  - `snapshot`
- The obvious missing proof-work inspection tools are:
  - `theorem_show`
  - `obligation_list`
  - `blocker_list`
  - `search`
  - `project_analyze`
- The user wants real Codex tool integration, so the plugin tool surface should feel complete enough for routine theorem work, not like a packaging demo.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `/Users/zhdeng/Proof CLI /.planning/PROJECT.md`
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md`
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md`
- `/Users/zhdeng/Proof CLI /.planning/STATE.md`

### Existing plugin layer
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/.mcp.json`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/scripts/proof_mcp_server.py`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/skills/proof-routing/SKILL.md`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/scripts/install_home_plugin.py`

### Existing wrapper layer
- `/Users/zhdeng/Proof CLI /src/proof_cli/codex_router.py`
- `/Users/zhdeng/Proof CLI /src/proof_cli/commands.py`

### Relevant tests
- `/Users/zhdeng/Proof CLI /tests/test_proof_routing_plugin.py`
- `/Users/zhdeng/Proof CLI /tests/test_cli.py`
- `/Users/zhdeng/Proof CLI /tests/test_retrieval.py`
- `/Users/zhdeng/Proof CLI /tests/test_phase9_validation.py`

</canonical_refs>

<deferred>
## Deferred Ideas

- User-facing install/enable documentation belongs to Phase 16.
- Final end-to-end user validation belongs to Phase 17.

</deferred>

---

*Phase: 15-tool-backed-proof-surface*
*Context gathered: 2026-04-30*
