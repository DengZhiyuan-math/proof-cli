# Phase 17: Global Plugin E2E Validation - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase validates the global plugin workflow end to end.

The question is no longer whether the plugin exists or whether its tools are individually wired. The question is whether a user can install the plugin, activate the expected path, and then use the installed tool surface to inspect or mutate proof state without confusion.

</domain>

<decisions>
## Implementation Decisions

- **D-01:** Validation should use the installed home-local plugin copy, not only the repo-local source tree.
- **D-02:** Validation should stay close to a real user story: install, inspect readiness/state, and run a small proof-state action.
- **D-03:** The plugin-backed path should be the main evidence; raw CLI checks are supporting evidence only.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/zhdeng/Proof CLI /plugins/proof-routing/scripts/install_home_plugin.py`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/scripts/proof_mcp_server.py`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/README.md`
- `/Users/zhdeng/Proof CLI /tests/test_proof_routing_plugin.py`
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md`
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md`

</canonical_refs>

---

*Phase: 17-global-plugin-e2e-validation*
*Context gathered: 2026-04-30*
