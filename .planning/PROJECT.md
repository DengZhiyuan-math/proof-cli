# Mathematical Proof CLI / Research Proof OS

## What This Is

This is a human-machine collaborative proof operating system for research mathematics. It is not trying to replace mathematicians or fully formalize every proof step; it is trying to make proof work stateful, debuggable, and trustworthy.

The CLI should help a researcher manage theorem contracts, proof state, dependencies, blockers, and imported results so long-running proof work can survive context loss and stay auditable.

## Core Value

Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] A CLI-first workspace that persists proof project state across sessions
- [ ] A theorem registry that stores contracts with assumptions, exports, and dependencies
- [ ] A proof state engine that tracks open goals, pending obligations, and blocker history
- [ ] A DSL/elaboration layer that turns proof scripts into explicit, checkable actions
- [ ] A checker stack that detects assumption mismatches, export-strength issues, circular dependencies, notation drift, and omission gaps
- [ ] A retrieval-first workflow that prefers current project results before external sources
- [ ] A memory system that stores working, semantic, episodic, and procedural proof context
- [ ] A human review gate for imported references and trust-level changes

### Out of Scope

- Fully formalizing every proof step into a primitive kernel — v1 is about trustworthy collaboration, not a complete proof assistant
- Replacing human judgment for final theorem acceptance — the user remains the reviewer and decision-maker
- Web console parity in v1 — the first release is CLI-first, with browser tooling deferred
- "Vector database only" memory — the project needs explicit proof state, not just embeddings and summaries

## Context

This is a greenfield project with no existing codebase yet. The source material already defines the product philosophy: theorem contracts instead of raw text, proof obligations instead of vague prose, and retrieval before local proof search.

The project is being initialized from a proposal that frames the product as a research workflow tool, not an automated theorem prover. That framing should stay stable unless the core product vision changes.

## Constraints

- **Human-in-the-loop**: Final acceptance must stay with the researcher — the system can suggest and check, but not silently decide
- **Retrieval-first**: Project results and trusted references must be checked before any new proof search
- **Local-state-first**: Long tasks must survive context loss through persisted project state
- **CLI-first**: The initial user experience should be terminal-native, with browser views deferred
- **No full kernel in v1**: The first release should support rigorous collaboration without attempting a complete formal logic foundation

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Human-in-the-loop review remains mandatory | Research math needs trust, not just automation | — Pending |
| Theorem contracts are the core data model | They encode assumptions, exports, and callability | — Pending |
| CLI is the primary interface | It matches the workflow and keeps the first release focused | — Pending |
| Retrieval happens before proof search | Prevents re-proving known results and reduces wasted effort | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check -> still the right priority?
3. Audit Out of Scope -> reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-21 after initialization*
