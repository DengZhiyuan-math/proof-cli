# Phase 11: Mutation Routing and Root Resolution - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Source:** Inline planning context after Phase 10 execution

<domain>
## Phase Boundary

Phase 11 hardens the new `proof codex` wrapper from a read-only inspection surface into a safe mutation-routing surface.

This phase should make Codex capable of driving real Proof CLI mutations for:

- theorem creation
- obligation creation
- blocker creation
- snapshot creation

while keeping workspace targeting deterministic and keeping the human review boundary explicit.

This is not a browser UI phase and not a plugin-packaging phase. It is a CLI/Codex workflow phase that should feel guided, visible, and general enough for ordinary Codex use.

</domain>

<decisions>
## Implementation Decisions

### Locked decisions
- Keep Proof CLI as the source of truth and mutation engine.
- Build on top of the `proof codex` wrapper introduced in Phase 10 rather than creating a second parallel mutation path.
- Make root resolution deterministic for project-local and global Codex entry points.
- Prefer the smallest missing-detail question for underspecified mutation commands.
- Keep read-only and mutating flows visibly distinct so the trust boundary stays clear.
- Preserve the broader milestone direction that the system should feel visualized, guided, general, and easy to use inside Codex.

### Planning assumptions
- No dedicated `11-discuss-phase` artifact exists yet, so this context is being synthesized from roadmap requirements, milestone goals, and the completed Phase 10 wrapper.
- The common mutation flows to harden first are `theorem add`, `obligation add`, `blocker add`, and `snapshot`.
- The current `proof codex` root resolver is a good starting point, but it likely needs clearer precedence and mutation-safe behavior before Phase 11 is complete.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and routing scope
- `.planning/PROJECT.md` — current milestone goals and active requirements
- `.planning/ROADMAP.md` — Phase 11 goal, scope, and success criteria
- `.planning/REQUIREMENTS.md` — `CMD-04`, `MUT-01`, `MUT-02`, `MUT-03`
- `.planning/STATE.md` — current milestone execution status

### Prior phase outputs
- `.planning/phases/10-command-invocation-surface/10-01-SUMMARY.md` — what Phase 10 already established and intentionally deferred

### Current implementation surface
- `src/proof_cli/codex_router.py` — current wrapper surface and root resolution
- `src/proof_cli/cli.py` — underlying Typer command surface
- `src/proof_cli/commands.py` — mutation command handlers
- `tests/test_cli.py` — current smoke tests and mutation-related CLI coverage

</canonical_refs>

<specifics>
## Specific Ideas

- The wrapper should accept the same mutation intent users naturally type in Codex, not force them to memorize low-level CLI flags before the wrapper becomes useful.
- Theorem creation likely needs a guided bridge from loose intent to the existing `proof theorem add <id> <name> <statement>` contract.
- Root selection should be explainable, not magical, especially when a global skill is used outside the repo root.
- Snapshot should be the easiest mutation path because it naturally follows the existing local-state-first workflow.

</specifics>

<deferred>
## Deferred Ideas

- Full interactive forms or richer multi-step modal workflows
- Plugin-marketplace packaging
- Multi-workspace chooser UX beyond deterministic defaults and explicit `--root`
- Automatic proof generation from natural language

</deferred>

---

*Phase: 11-mutation-routing-and-root-resolution*
*Context gathered: 2026-04-30 via inline planning path*
