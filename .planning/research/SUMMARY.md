# Project Research Summary

**Project:** Mathematical Proof CLI / Research Proof OS
**Domain:** Research mathematics CLI / proof workflow OS
**Researched:** 2026-04-21
**Confidence:** MEDIUM

## Executive Summary

This project should be built as a local-first CLI for research mathematics, not as a fully automatic theorem prover. The research direction is consistent: store explicit theorem contracts, keep proof state persistent, and force omitted reasoning into checkable obligations so trust is visible instead of implicit.

The main risk is scope drift toward either a generic notes app or a browser-heavy UI. The roadmap should therefore prioritize a structured state model, contract-based reuse, and the checker/elaboration pipeline before any console polish or automation extras.

- What type of product this is and how experts build it
- The recommended approach based on research
- Key risks and how to mitigate them

## Key Findings

### Recommended Stack

The project fits a Node.js + TypeScript + SQLite stack well. That combination keeps the CLI fast to iterate on while preserving durable local state for contracts, obligations, and blocker history.

**Core technologies:**
- Node.js: CLI runtime and orchestration - good fit for cross-platform command handling
- TypeScript: implementation language - keeps the proof-state logic explicit and refactorable
- SQLite: persistent project state - matches the local-first, structured memory model

### Expected Features

The table stakes are persistent state, theorem contracts, goal tracking, dependency tracking, and import metadata. Differentiators are contract-based reuse, omission elaboration, retrieval-first workflows, and a human review gate for imports.

**Must have (table stakes):**
- Persistent project state - users need to resume long proof work
- Theorem/lemma registry - users need reusable results with assumptions
- Proof goal tracking - users need to know what remains open

**Should have (competitive):**
- Contract-based theorem calls - reuse results without reopening proof bodies
- Omission elaboration - make compressed reasoning checkable
- Human review gate - keep trust changes explicit

**Defer (v2+):**
- Browser console - useful, but not necessary for the first release
- Automatic proof suggestion modes - defer until the trust model is stable

### Architecture Approach

The recommended architecture separates CLI commands, proof state, theorem registry, elaboration, checking, retrieval, memory, and review into distinct layers. That separation reflects the actual trust boundaries in research mathematics and prevents summaries from being mistaken for proof objects.

**Major components:**
1. CLI layer - user commands and status display
2. State engine - open goals, obligations, blockers, snapshots
3. Registry - theorem contracts, dependencies, trust metadata

### Critical Pitfalls

1. **Treating summaries as proof objects** - require explicit contracts
2. **Hiding obligations behind "standard" steps** - force elaboration into checkable obligations
3. **Importing external results without trust workflow** - require approval and metadata

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Foundation
**Rationale:** The project needs persistent state and a usable CLI shell before anything else can be trusted.
**Delivers:** workspace initialization, project state, snapshots, blocker visibility
**Addresses:** persistent project state, proof goal tracking
**Avoids:** summary-only memory

### Phase 2: Registry
**Rationale:** Proof reuse depends on explicit theorem contracts and dependency metadata.
**Delivers:** theorem registry, dependency graph, callable contracts
**Uses:** SQLite, TypeScript schemas, command handlers
**Implements:** registry component

### Phase 3: DSL and Checks
**Rationale:** Users need compressed proof syntax only after the system can expand and validate it.
**Delivers:** proof script parsing, elaboration, checker stack
**Uses:** obligation pipeline, contract metadata
**Implements:** elaborator and validation pipeline

### Phase 4: Retrieval and Memory
**Rationale:** Research workflows need reuse and recovery once the core proof model exists.
**Delivers:** layered memory, internal search, external import metadata
**Implements:** retrieval and memory components

### Phase 5: Review and Trust
**Rationale:** Imported results must be gated before they can become part of the proof base.
**Delivers:** human approval flow, trust-level changes, auditability
**Avoids:** blind imports

### Phase Ordering Rationale

- Persistent state must come before contracts because the CLI needs a reliable project backbone.
- Contracts must come before DSL shortcuts because the shortcuts need something formal to point at.
- Retrieval and review should follow validation because imported results are only useful once they can be checked.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3:** elaboration rules and checker semantics may need implementation detail
- **Phase 4:** retrieval and memory design may need iteration based on actual use

Phases with standard patterns (skip research-phase):
- **Phase 1:** local project state and CLI scaffolding are well understood
- **Phase 2:** structured registry modeling is straightforward once the data model is defined

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Node + TypeScript + SQLite is a strong fit, but exact libraries can still shift |
| Features | HIGH | The proposal is explicit about the product shape |
| Architecture | MEDIUM | The major components are clear, but implementation details remain open |
| Pitfalls | HIGH | The trust-boundary issues are strongly implied by the proposal |

**Overall confidence:** MEDIUM

### Gaps to Address

- Exact proof script syntax: define during planning and phase execution
- Retrieval source ranking: verify with real project usage before hardening

## Sources

### Primary (HIGH confidence)
- Project proposal in `mathematical_proof_cli_project_plan.md`

### Secondary (MEDIUM confidence)
- Local-first CLI and proof-state architecture patterns

### Tertiary (LOW confidence)
- Specific library choices in the stack are inferred and should be validated during implementation

---
*Research completed: 2026-04-21*
*Ready for roadmap: yes*
