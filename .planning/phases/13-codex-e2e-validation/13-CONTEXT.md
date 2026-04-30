# Phase 13: Codex E2E Validation - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate the full Codex-facing Proof CLI command layer end to end.

This phase should prove that a user can drive a realistic miniature proof workflow through the hardened `proof codex` / `$proof ...` surface, not just through isolated CLI smoke checks. The scope is validation and proof-of-usability for the command-routing layer that Phases 10, 11, and 12 built.

</domain>

<decisions>
## Implementation Decisions

### Validation slice
- **D-01:** The final validation should use a small theorem cluster that is closer to the user's real research style, not a purely abstract toy theorem.
- **D-02:** The cluster should still stay small enough to be repeatable and auditable, but it should feel like genuine theorem / obligation / blocker / snapshot work rather than a fake demo.

### Validation evidence
- **D-03:** The primary evidence should be a real Codex-driven `$proof ...` workflow walkthrough, not only automated smoke tests.
- **D-04:** Automated tests still matter, but they are secondary support for the main claim that the command layer works in real interactive use.

### Success standard
- **D-05:** Success should be stronger than “the commands technically run.”
- **D-06:** The phase must show that this command surface is more usable than before: more direct, less ambiguous, and more suitable for ongoing use.
- **D-07:** The validation should explicitly check that the new entry surface reduces confusion compared with the earlier skill-only / weaker-routing behavior.

### the agent's Discretion
- Choice of exact small theorem cluster, as long as it stays close to the user's real research workflow
- Exact split between scripted validation artifact and supporting smoke tests
- Exact wording and structure of the final validation summary

</decisions>

<specifics>
## Specific Ideas

- The validation should feel like “I can actually use this in Codex for proof work now,” not just “the repository has tests.”
- The proof slice should resemble theorem-cluster work with obligations, blockers, and snapshots, because that is closer to the system’s intended research-math use.
- The result should make it easy to compare the old experience and the hardened command-surface experience.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and validation scope
- `.planning/PROJECT.md` — current milestone goals and active end-to-end validation requirement
- `.planning/ROADMAP.md` — Phase 13 goal and success criteria
- `.planning/REQUIREMENTS.md` — `VAL-01`, `VAL-02`, `VAL-03`
- `.planning/STATE.md` — current project state and open validation questions

### Prior routing phases
- `.planning/phases/10-command-invocation-surface/10-01-SUMMARY.md` — read-only wrapper baseline
- `.planning/phases/11-mutation-routing-and-root-resolution/11-01-SUMMARY.md` — mutation routing and root guard behavior
- `.planning/phases/12-bootstrap-and-wrapper-hardening/12-01-SUMMARY.md` — diagnostics and canonical global-skill hardening

### Validation precedent
- `.planning/phases/09-radial-system-validation/09-SUMMARY.md` — small theorem-cluster validation pattern closer to the user's research style

### Current implementation surface
- `src/proof_cli/codex_router.py` — hardened wrapper surface
- `tests/test_cli.py` — current wrapper smoke coverage

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/proof_cli/codex_router.py`: already exposes read-only, mutation, and diagnostic wrapper commands that can serve as the validation surface
- `tests/test_cli.py`: already contains smoke coverage for routing, mutations, root precedence, unsafe roots, and `doctor`

### Established Patterns
- Phase 9 already validated a small theorem-cluster workflow rather than a toy example
- Phases 10 to 12 established the pattern that wrapper behavior should be tested both through human-readable behavior and targeted regression coverage

### Integration Points
- Phase 13 should validate the user-facing wrapper surface without bypassing it
- The final validation should connect theorem creation, obligation/blocker management, snapshotting, and readiness checks into one coherent workflow

</code_context>

<deferred>
## Deferred Ideas

- Full browser-based usability validation
- Multi-workspace chooser UX validation beyond the current deterministic root rules
- Plugin-marketplace or non-skill packaging validation

</deferred>

---

*Phase: 13-codex-e2e-validation*
*Context gathered: 2026-04-30*
