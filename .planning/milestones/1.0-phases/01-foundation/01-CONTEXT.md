# Phase 1: CLI Foundation and Proof-State Validation - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning
**Source:** User-provided Phase 1 spec in this thread

<domain>
## Phase Boundary

Phase 1 builds the first usable CLI-first version of Mathematical Proof CLI / Research Proof OS. It must validate that a researcher can persist proof work across sessions, register theorem contracts, track goals and obligations, record blockers, apply known results safely, and recover after interruption.

This phase is intentionally not a full proof assistant. It is a workflow validation phase for explicit proof state, explicit trust boundaries, explicit obligations, and continuity across sessions.

</domain>

<decisions>
## Implementation Decisions

### Product shape
- CLI-first, terminal-native workflow
- Persistence-first architecture with local SQLite storage
- Human review remains mandatory for trust-sensitive changes

### Stack
- Python implementation
- Typer or Click for CLI
- Pydantic for schema validation
- SQLite for local persistence
- Rich for terminal rendering
- JSON or YAML for export and snapshots

### Data model
- TheoremContract is a structured object with id, kind, name, statement, assumptions, exports, status, trust_level, dependencies, source_ref, notes, version, and timestamps
- ProofObligation and BlockerRecord are first-class records
- ProjectSnapshot is persisted and used for handoff

### the agent's Discretion
- Exact package layout
- CLI command grouping and module boundaries
- Whether to use Typer or Click
- Exact snapshot file format and internal migration strategy
- Minor naming choices for internal services and tests

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` - project vision, core value, constraints
- `.planning/ROADMAP.md` - phase structure and phase 1 positioning
- `.planning/REQUIREMENTS.md` - existing roadmap-level requirement set
- `.planning/STATE.md` - current project memory and focus

### Phase 1 Specification
- This conversation’s Phase 1 spec - detailed phase deliverables, milestone structure, validation target, risks, and acceptance criteria

</canonical_refs>

<specifics>
## Specific Ideas

- Required commands: `proof init`, `proof status`, `proof goal set`, `proof goal list`, `proof theorem add`, `proof theorem show`, `proof theorem list`, `proof theorem apply`, `proof obligation add`, `proof obligation list`, `proof blocker add`, `proof blocker list`, `proof snapshot`, `proof history`, `proof export`
- Theorem contract statuses: imported, verified, assumed, draft, blocked, failed
- Trust levels: foundational, project_verified, external_reference, temporary_admit
- Proof-state fields: current target, local context, open goals, open obligations, dependencies, blockers, failed attempts, session history, latest snapshot
- DSL commands: import T, use T, apply T, goal G, assume H, assert C, defer C, split, suffices Q, close
- Checker checks: assumption presence, theorem-call legality, dependency existence, circularity, export-strength mismatch, unresolved omission marker, notation drift
- Snapshot contents: current theorem, active goals, open obligations, blockers, recent results, unresolved trust-sensitive calls, suggested next steps, handoff note
- Validation target: one real theorem project with multiple lemmas, one imported standard result, one project-local verified result, one blocker, and one obligation that survives multiple sessions

</specifics>

<deferred>
## Deferred Ideas

- Full formal logic kernel
- Automatic theorem proving at scale
- Browser UI / web console
- Large-scale literature federation APIs as a hard dependency
- Fully automatic extraction of theorem contracts from papers
- Advanced vector-memory-only workflows
- Autonomous trust upgrades without human approval

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-04-21 via user-provided Phase 1 spec*
