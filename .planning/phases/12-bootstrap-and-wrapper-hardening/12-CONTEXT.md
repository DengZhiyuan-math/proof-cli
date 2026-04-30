# Phase 12: Bootstrap and Wrapper Hardening - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Source:** Discuss-phase decisions captured inline

<domain>
## Phase Boundary

Phase 12 is about hardening the Codex-facing command layer when the local environment is incomplete or ambiguous.

This phase is not about mathematical proof logic. It is about how the `proof codex` / `proof-codex` command surface behaves when:

- the `proof` executable is missing
- the wrapper entry point is unavailable
- the environment is degraded or inconsistent
- project-local and global skill configuration could otherwise create confusion

The outcome should be deterministic, explicit, terminal-native behavior that helps the user recover without silently changing their environment.

</domain>

<decisions>
## Implementation Decisions

### Locked decisions
- Do not auto-install or auto-repair the local environment when `proof` or `proof-codex` is unavailable.
- The wrapper should report clear errors and the next command the user should run, but it should not silently modify the Python environment.
- "Bootstrap" in this phase means command-layer handling for an unready local environment, not any mathematical or proof-state bootstrapping concept.
- Treat the global `~/.codex/skills/proof/` skill as the real production entry point.
- Treat project-local `proof` / `proof-cli` skills as debugging and development helpers, not the long-term canonical user entry path.

### Clarified boundaries
- This phase should harden command availability and routing behavior, not redesign the wrapper UX from scratch.
- This phase should not add browser UI, plugin marketplace packaging, or automatic environment management.
- This phase should keep all user-facing recovery guidance terminal-native and easy to follow.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and phase scope
- `.planning/PROJECT.md` — milestone goals and active command-layer requirements
- `.planning/ROADMAP.md` — Phase 12 goal and success criteria
- `.planning/REQUIREMENTS.md` — `BST-01`, `BST-02`
- `.planning/STATE.md` — current milestone status and open questions

### Prior phase outputs
- `.planning/phases/10-command-invocation-surface/10-01-SUMMARY.md` — read-only wrapper baseline
- `.planning/phases/11-mutation-routing-and-root-resolution/11-01-SUMMARY.md` — current mutation routing and root-guard behavior

### Current implementation surface
- `src/proof_cli/codex_router.py` — current wrapper routing and root resolution
- `pyproject.toml` — current console script entry points
- `.agents/skills/proof/SKILL.md` — project-local proof skill
- `.agents/skills/proof-cli/SKILL.md` — project-local debug/helper skill
- `/Users/zhdeng/.codex/skills/proof/SKILL.md` — global proof skill
- `/Users/zhdeng/.codex/skills/proof-cli/SKILL.md` — global proof-cli skill
- `tests/test_cli.py` — current wrapper smoke tests

</canonical_refs>

<specifics>
## Specific Ideas

- Missing-binary behavior should likely centralize around one explicit diagnostic path rather than scattered command-specific errors.
- The wrapper should distinguish "command unavailable" from "workspace unavailable" and explain the difference clearly.
- If both project-local and global skills exist, the docs and behavior should make it obvious that the global skill is canonical and the local one is for repo development/debugging only.
- Recovery messages should tell the user exactly what to run next, but should stop short of running those commands automatically.

</specifics>

<deferred>
## Deferred Ideas

- Automatic package installation or environment healing
- Interactive installers or setup wizards
- Browser-based troubleshooting UI
- Full plugin packaging beyond local/global skill-based routing

</deferred>

---

*Phase: 12-bootstrap-and-wrapper-hardening*
*Context gathered: 2026-04-30 via discuss-phase decisions*
