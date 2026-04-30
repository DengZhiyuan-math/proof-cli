---
phase: 17-global-plugin-e2e-validation
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 14-global-plugin-packaging
  - phase: 15-tool-backed-proof-surface
  - phase: 16-activation-and-entry-unification
files_modified:
  - plugins/proof-routing/README.md
  - tests/test_proof_routing_plugin.py
autonomous: true
requirements:
  - ACTV-03
---

<objective>
Prove that the global plugin path works as a real end-to-end user workflow.

Execution split:
1. Validate an installed home-local plugin copy.
2. Keep the user-facing verification path short.
3. Use the plugin-backed flow itself as the main evidence.
</objective>
