---
phase: 14-global-plugin-packaging
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 13-codex-e2e-validation
    provides: a working repo-local Codex wrapper and plugin prototype worth globalizing
files_modified:
  - plugins/proof-routing/.codex-plugin/plugin.json
  - plugins/proof-routing/.mcp.json
  - plugins/proof-routing/scripts/proof_mcp_server.py
  - plugins/proof-routing/skills/proof-routing/SKILL.md
  - .agents/plugins/marketplace.json
  - pyproject.toml
  - tests/test_proof_routing_plugin.py
autonomous: true
requirements:
  - GPLG-01
  - GPLG-02
  - GPLG-03
must_haves:
  truths:
    - the global plugin path must be real packaging, not another repo-local skill workaround
    - Proof CLI must remain the source of truth behind the plugin tool surface
    - repo-local and home-local plugin paths must be able to coexist without silent divergence
    - packaging work should make Codex discovery more deterministic, not more magical
  artifacts:
    - plugins/proof-routing/.codex-plugin/plugin.json
    - plugins/proof-routing/.mcp.json
    - plugins/proof-routing/scripts/proof_mcp_server.py
    - .agents/plugins/marketplace.json
    - tests/test_proof_routing_plugin.py
  key_links:
    - keep the plugin aligned with the existing `proof codex` wrapper
    - keep the repo-local plugin as the editable source template
    - keep the home-local plugin path explicit and repeatable
---

<objective>
Package the Proof Routing plugin for global home-local Codex use.

Purpose: take the repo-local plugin prototype and make it installable and discoverable under `~/plugins/...` and `~/.agents/plugins/marketplace.json` without weakening the current Proof CLI trust boundary.

Execution split:
1. Define and implement the home-local plugin install or sync path.
2. Normalize manifest, marketplace, and MCP wiring for global discovery.
3. Validate that the resulting packaging still exposes the existing tool-backed proof surface.
</objective>

<threat_model>
## Threat Model

### High severity
- The "global plugin" still depends on repo-local paths and silently fails once copied outside the repo.
  - Mitigation: validate home-local path assumptions explicitly and ensure generated MCP config is correct for the installed location.

- The packaging path forks behavior from the repo-local prototype.
  - Mitigation: treat the repo-local plugin as the source template and add a deterministic install or sync path instead of hand-maintained duplication.

- The plugin starts owning proof-state behavior rather than routing through Proof CLI.
  - Mitigation: preserve `proof codex ...` as the execution boundary in both repo-local and home-local forms.

### Medium severity
- Repo-local and home-local entries become ambiguous inside Codex.
  - Mitigation: make marketplace ownership and plugin role explicit; Phase 14 should set a canonical installation target.

- Packaging succeeds but discovery fails because the marketplace or plugin manifest remains incomplete.
  - Mitigation: include manifest and marketplace validation in tests and implementation checks.

### Low severity
- Packaging scripts are slightly verbose or manual.
  - Mitigation: prefer explicit, understandable installation over premature automation magic.
</threat_model>

<tasks>

<task type="auto">
  <name>Implement the home-local plugin install or sync path</name>
  <files>plugins/proof-routing/.codex-plugin/plugin.json, plugins/proof-routing/.mcp.json, plugins/proof-routing/scripts/proof_mcp_server.py, .agents/plugins/marketplace.json, pyproject.toml</files>
  <action>Define the canonical home-local install target for `proof-routing`, then add the minimal implementation needed to copy or sync the repo-local plugin into `~/plugins/proof-routing` and create or update `~/.agents/plugins/marketplace.json`. Ensure the plugin manifest and MCP server configuration remain valid after relocation and that the installed plugin still routes through the existing `proof` executable and `proof codex` wrapper.</action>
  <verify>pytest tests/test_proof_routing_plugin.py -q</verify>
  <acceptance_criteria>
    - a deterministic home-local install target is defined
    - the plugin can be packaged outside the repo under `~/plugins/...`
    - a home-local marketplace entry can point Codex at the installed plugin
    - the global packaging path does not require repo-local skill-only behavior to make sense
  </acceptance_criteria>
  <done>The Proof Routing plugin has a real home-local installation path</done>
</task>

<task type="auto">
  <name>Normalize global discovery metadata and MCP wiring</name>
  <files>plugins/proof-routing/.codex-plugin/plugin.json, plugins/proof-routing/.mcp.json, plugins/proof-routing/skills/proof-routing/SKILL.md, tests/test_proof_routing_plugin.py</files>
  <action>Review and tighten plugin metadata so the global plugin is discoverable as a coherent Codex surface rather than a placeholder scaffold. Ensure manifest fields, MCP config, and plugin-local skill all describe the plugin in ways that stay accurate after global installation. Keep the current tool inventory stable unless a small naming or metadata correction is required for discovery.</action>
  <verify>pytest tests/test_proof_routing_plugin.py -q</verify>
  <acceptance_criteria>
    - plugin manifest fields are complete enough for discovery
    - MCP configuration is valid for the intended global installation shape
    - plugin-local guidance matches the tool-backed surface rather than contradicting it
    - the tool-backed plugin remains anchored to the existing wrapper behavior
  </acceptance_criteria>
  <done>Global plugin discovery metadata is coherent and install-ready</done>
</task>

<task type="auto">
  <name>Prove packaging preserves the tool-backed proof surface</name>
  <files>tests/test_proof_routing_plugin.py, tests/test_cli.py, tests/test_retrieval.py, tests/test_phase9_validation.py</files>
  <action>Add or adjust tests so the plugin packaging work is validated together with the existing wrapper-backed proof surface. Keep the focus on proving that home-local packaging still exposes the same MCP tool inventory and continues to route through `proof codex` for realistic proof-work commands.</action>
  <verify>pytest tests/test_proof_routing_plugin.py tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q</verify>
  <acceptance_criteria>
    - packaging changes do not break plugin tool registration
    - packaging changes do not break the underlying wrapper-backed proof workflow
    - the combined validation covers both plugin shape and proof command routing
    - Phase 14 closes the global plugin packaging requirements without overreaching into later documentation phases
  </acceptance_criteria>
  <done>Global plugin packaging is tested against the real proof surface</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] there is a real home-local `proof-routing` plugin target
- [ ] a home-local marketplace entry can point Codex to the plugin
- [ ] manifest and MCP wiring are valid for global installation
- [ ] plugin behavior still routes through the existing Proof CLI wrapper
- [ ] tests prove packaging changes preserve the current tool-backed proof surface

</verification>

<success_criteria>

- The Proof Routing plugin can be installed under `~/plugins/...`.
- A home-local `~/.agents/plugins/marketplace.json` entry can reference the installed plugin.
- Plugin metadata and MCP config are complete enough for Codex discovery.
- The plugin still routes into `proof codex` rather than owning proof-state semantics itself.
- Packaging work is validated with tests that cover both plugin shape and proof command routing.

</success_criteria>
