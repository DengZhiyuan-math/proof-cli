# Phase 6: Collaborative Proof Infrastructure, Shared Review Governance, and Institutional-Scale Research Workflow - Context

**Gathered:** 2026-04-23
**Status:** Ready for planning
**Source:** user-provided phase specification in the gsd-plan-phase request

<domain>
## Phase Boundary

This phase validates whether Mathematical Proof CLI can support real collaborative proof development across multiple researchers without weakening trust discipline.

The phase is not about public theorem marketplaces, anonymous crowd consensus, or automated merger of conflicting mathematical claims. It is about governed collaboration: authorship, provenance, review, comments, branch management, shared reusable knowledge, reproducible handoff, and collaboration-aware policy.

The phase should demonstrate that the proof OS can move from a single-researcher workflow into a team- and lab-scale operating environment while keeping mathematical acceptance explicit and human-responsible.

## Phase Outcome

The phase should answer one concrete product question:

Can a research proof OS support real collaborative proof development across multiple users without losing auditability, trust discipline, or mathematical clarity?

</domain>

<decisions>
## Implementation Decisions

### Collaboration model
- Support multiple contributors on a proof project with explicit contributor identity, roles, provenance, and authorship for proof objects.
- Preserve final human responsibility for trust-sensitive mathematical acceptance.

### Governance model
- Shared proof objects must have explicit governance states: `draft`, `proposed_for_review`, `under_review`, `approved`, `rejected`, `superseded`, and `disputed`.
- Governance must apply to theorem contracts, imported reference contracts, blocker resolutions, proof-bug reports, repair strategies, reusable assets, domain-pack updates, and machine-check acceptance decisions.

### Review model
- Comments and review threads must remain separate from theorem truth state.
- Review history, rationale, and unresolved discussion must be explicit and exportable.

### Branching model
- Alternative proof routes and conflicting interpretations must be represented explicitly.
- Branches may only merge through explicit review; unresolved alternatives must remain preserved when useful.

### Shared knowledge model
- Team-scoped reusable knowledge should support shared theorem/asset libraries, team-owned domain packs, reviewed reusable patterns, shared blocker and repair archetypes, and provenance across reuse boundaries.

### Exchange model
- Proof projects must be exportable/importable with provenance, review history, shared asset dependencies, snapshots, and verification history.
- Handoff from one researcher to another should preserve context instead of collapsing into flat notes.

### Policy model
- Collaboration policies must govern who can propose, approve, publish, mark callable, accept machine-check results, and resolve disputes.
- Policy must be explicit at project, team, and shared-library level.

### Evaluation model
- The phase must include a collaboration evaluation loop so the team can measure whether governance improves the workflow rather than adding unbounded overhead.

### the agent's Discretion
- Exact persistence backend, sync model, and concurrency strategy.
- Whether the first implementation is local-first with replicated bundles or introduces a service boundary.
- UI density for review threads, comments, and branch comparison in the CLI.
- How much of the collaboration policy is driven by reusable defaults versus project-specific configuration.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `/Users/zhdeng/Proof CLI /.planning/PROJECT.md` — current project framing, constraints, and active milestone context
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md` — current milestone requirement vocabulary and out-of-scope boundaries
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md` — roadmap structure and dependency ordering
- `/Users/zhdeng/Proof CLI /.planning/STATE.md` — current planning state

### Existing phase patterns
- `/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/05-review-and-trust/05-CONTEXT.md` — latest completed phase context and style reference
- `/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/04-memory-and-retrieval/04-CONTEXT.md` — memory/retrieval phase patterns that this work builds on

### Relevant codebase entry points
- `/Users/zhdeng/Proof CLI /src/proof_cli/memory.py` — existing layered memory and snapshot primitives
- `/Users/zhdeng/Proof CLI /src/proof_cli/retrieval.py` — retrieval-first project query layer
- `/Users/zhdeng/Proof CLI /src/proof_cli/snapshot.py` — snapshot creation and recovery integration
- `/Users/zhdeng/Proof CLI /src/proof_cli/commands.py` — CLI surface for current commands
- `/Users/zhdeng/Proof CLI /src/proof_cli/cli.py` — Typer app wiring for CLI subcommands

</canonical_refs>

<specifics>
## Specific Ideas

- Multi-user project model with contributor identity, roles, authorship, and reviewer identity.
- Shared proof-object governance with review states and explicit transitions.
- Review and discussion threads that do not mutate object truth state directly.
- Branching and divergence management for conflicting interpretations or alternative proof routes.
- Team-scoped reusable knowledge with library publication and provenance-aware reuse.
- Reproducible export/import of project state and review history for handoff.
- Collaboration-aware policy layer for proposals, approvals, publication, callable state, machine-check acceptance, and dispute resolution.
- Validation on a real collaborative proof workflow with at least two users, one disputed step, one shared imported theorem family, one reusable team asset, one branch comparison or resolution, and one successful handoff.

</specifics>

<deferred>
## Deferred Ideas

- Open public anonymous collaboration by default.
- Replacing journal peer review.
- Majority-vote truth resolution.
- Fully automatic merge of conflicting mathematical claims.
- Social reputation systems as the basis of mathematical trust.
- Unrestricted autonomous multi-agent collaboration without supervision.

</deferred>

---

*Phase: 06-collaborative-proof-infrastructure*
*Context gathered: 2026-04-23 via user-provided phase specification*
