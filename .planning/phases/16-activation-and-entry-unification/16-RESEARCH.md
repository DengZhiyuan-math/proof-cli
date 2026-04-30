# Phase 16 Research: Activation and Entry Unification

**Gathered:** 2026-04-30
**Status:** Complete

## Findings

- The user-facing confusion is currently about which entry actually executes versus only suggests behavior.
- The strongest concrete path is now:
  1. plugin-backed tools
  2. `proof codex ...`
  3. `$proof ...` as compatibility guidance only
- Repo-local and global skill files still over-emphasize `$proof ...` as if it were a hard trigger.
- The project needs one short install/enable/test document that explains all three surfaces together.

## Recommendation

- Add a single plugin README that explains install, enablement, and the entry hierarchy.
- Update global and repo-local skills so they explicitly describe plugin tools as primary.
- Keep `proof codex ...` documented as the reliable CLI fallback.

---

*Phase: 16-activation-and-entry-unification*
*Context gathered: 2026-04-30*
