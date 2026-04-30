---
phase: 16-activation-and-entry-unification
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 14-global-plugin-packaging
  - phase: 15-tool-backed-proof-surface
files_modified:
  - plugins/proof-routing/README.md
  - plugins/proof-routing/skills/proof-routing/SKILL.md
  - .agents/skills/proof/SKILL.md
  - .agents/skills/proof-cli/SKILL.md
  - /Users/zhdeng/.codex/skills/proof/SKILL.md
  - tests/test_proof_routing_plugin.py
autonomous: true
requirements:
  - TOOL-04
  - ACTV-01
  - ACTV-02
---

<objective>
Clarify how users should activate and use the global plugin-backed proof surface.

Execution split:
1. Write one short install/enable/use document.
2. Align skill wording with the plugin-first entry hierarchy.
3. Add lightweight verification that the documentation and entry semantics stay present.
</objective>
