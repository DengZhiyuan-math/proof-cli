---
phase: 15-tool-backed-proof-surface
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 14-global-plugin-packaging
    provides: a relocatable home-local plugin with valid marketplace and MCP wiring
files_modified:
  - plugins/proof-routing/scripts/proof_mcp_server.py
  - plugins/proof-routing/skills/proof-routing/SKILL.md
  - tests/test_proof_routing_plugin.py
autonomous: true
requirements:
  - TOOL-01
  - TOOL-02
  - TOOL-03
must_haves:
  truths:
    - the plugin tool surface should feel like a real proof workspace interface, not a partial demo
    - plugin tools must keep routing through `proof codex`
    - the expanded tool inventory should stay explicit and testable
  artifacts:
    - plugins/proof-routing/scripts/proof_mcp_server.py
    - plugins/proof-routing/skills/proof-routing/SKILL.md
    - tests/test_proof_routing_plugin.py
---

<objective>
Expand the plugin-backed proof surface so it covers the routine inspection and mutation workflows a user actually needs.

Execution split:
1. Add the missing proof inspection tools.
2. Keep the mutation tools anchored to the existing wrapper semantics.
3. Lock the broader tool surface down with tests.
</objective>
