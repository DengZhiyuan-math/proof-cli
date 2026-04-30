# Mathematical Proof CLI / Research Proof OS

## What This Is

This is a CLI-first human-machine collaborative proof operating system for research mathematics.

It helps a researcher manage theorem contracts, proof state, dependencies, blockers, imported results, reusable proof knowledge, project memory, and explicit proof structure so long-running proof work can survive context loss and stay auditable.

## Core Value

Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

## Current State

v1.2 is shipped.

The project now has a real Codex-facing command surface on top of the Proof CLI, including deterministic command routing, safe mutation routing, readiness diagnostics, and an end-to-end theorem-cluster workflow validated through the wrapper.

## Next Milestone Goals

The next milestone is not defined yet.

Likely directions to evaluate:

- richer guided command UX for theorem and proof-state editing
- multi-workspace selection and disambiguation
- deeper plugin-level integration for Codex
- broader visual or structured inspection surfaces that still preserve the CLI-first trust model

## Requirements

### Validated

- [x] A CLI-first workspace that persists proof project state across sessions
- [x] A theorem registry that stores contracts with assumptions, exports, and dependencies
- [x] A proof state engine that tracks open goals, pending obligations, and blocker history
- [x] A DSL/elaboration layer that turns proof scripts into explicit, checkable actions
- [x] A checker stack that detects assumption mismatches, export-strength issues, circular dependencies, notation drift, and omission gaps
- [x] A retrieval-first workflow that prefers current project results before external sources
- [x] A memory system that stores working, semantic, episodic, and procedural proof context
- [x] A human review gate for imported references and trust-level changes
- [x] Codex can recognize and route `proof` command triggers deterministically
- [x] Read-only Proof CLI commands run directly from Codex with reliable repo-root resolution
- [x] Mutating Proof CLI commands ask only for the minimum missing theorem or obligation details
- [x] Proof CLI bootstrap and fallback behavior is explicit when the local executable is unavailable
- [x] The command-routing layer is validated with a small end-to-end theorem workflow inside Codex

### Active

No active milestone requirements are currently defined.

### Out of Scope

- Fully formalizing every proof step into a primitive kernel
- Replacing human judgment for final theorem acceptance
- Web console parity in v1
- "Vector database only" memory
- Cross-project shared memory as a default system layer
- Automatic graph inference from arbitrary prose
- Autonomous proof planning that silently bypasses human review

## Context

The project shipped:

- v1.0 as the local-first CLI proof workspace foundation
- v1.1 as the collaboration, publication, retrieval, snapshot, and real validation milestone
- v1.2 as the Codex command-routing and wrapper-hardening milestone

The immediate question is no longer whether the Proof CLI can model proof work, but what the next usability and integration layer should be without weakening auditability or the human-in-the-loop trust boundary.

## Constraints

- **Human-in-the-loop**: Final acceptance must stay with the researcher
- **Retrieval-first**: Project results and trusted references must be checked before any new proof search
- **Local-state-first**: Long tasks must survive context loss through persisted project state
- **CLI-first**: The initial user experience should remain terminal-native unless a later milestone justifies more
- **No full kernel in v1**: The first release should support rigorous collaboration without attempting a complete formal logic foundation
- **Explicit source of truth**: Proof CLI remains the execution and state authority

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Human-in-the-loop review remains mandatory | Research math needs trust, not silent automation | ✓ Good |
| Theorem contracts are the core data model | They encode assumptions, exports, and callability | ✓ Good |
| CLI is the primary interface | It matches the workflow and keeps the system inspectable | ✓ Good |
| Retrieval happens before proof search | Prevents re-proving known results and reduces wasted effort | ✓ Good |
| Bounded automation is preferable to open-ended autonomous proof search | It preserves auditability and trust boundaries | ✓ Good |
| Codex should drive Proof CLI through a wrapper, not replace it | The system needs a hard command surface without duplicating proof-state logic | ✓ Shipped in v1.2 |

## Recent Milestone History

<details>
<summary>v1.2 closeout snapshot</summary>

- Shipped deterministic `proof codex` / `proof-codex` command routing
- Shipped safe mutation routing for theorem, obligation, blocker, and snapshot flows
- Shipped readiness diagnostics through `proof codex doctor`
- Validated a realistic small theorem-cluster workflow through the hardened wrapper

</details>

---
*Last updated: 2026-04-30 after v1.2 milestone completion*
