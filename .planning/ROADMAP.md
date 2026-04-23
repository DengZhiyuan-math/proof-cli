# Roadmap: Mathematical Proof CLI

**Created:** 2026-04-23
**Core Value:** Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

## Phase Overview

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Foundation | 7/7 | Complete | 2026-04-21 |
| 2 | Registry | 8/8 | Complete | 2026-04-21 |
| 3 | DSL and Checks | 8/8 | Complete | 2026-04-22 |
| 4 | Memory and Retrieval | 8/8 | Complete | 2026-04-22 |
| 5 | Review and Trust | 8/8 | Complete | 2026-04-22 |
| 6 | Collaborative Proof Infrastructure | 3/3 | Pending | 2026-04-23 |
| 7 | Knowledge Graph | 4/4 | Pending | 2026-04-23 |
| 8 | Retrieval and Snapshots | 4/4 | Pending | 2026-04-23 |
| 9 | Radial System Validation | 2/2 | Pending | 2026-04-23 |

## Phase Details

## Phase 1: Foundation
**Goal:** Create the persistent project backbone and CLI status surface.
**Requirements:** WS-01, WS-02
**Success Criteria:**
1. A new workspace can be initialized and reopened without losing project state.
2. The CLI can display current open goals and blockers.
3. Project snapshots survive a fresh session.
4. The state model is explicit enough for later phases to build on.

## Phase 2: Registry
**Goal:** Make theorem contracts first-class and callable.
**Requirements:** THM-01, THM-02, THM-03
**Success Criteria:**
1. The user can register reusable theorem contracts.
2. Each contract stores assumptions, exports, and dependencies.
3. The system can explain whether a contract is callable in context.
4. Dependency metadata is available for later checks.

## Phase 3: DSL and Checks
**Goal:** Parse proof scripts and validate omissions, assumptions, and dependency safety.
**Requirements:** DSL-01, DSL-02, DSL-03, CHK-01, CHK-02, CHK-03, CHK-04
**Success Criteria:**
1. A proof script can be parsed into explicit steps.
2. Compressed reasoning expands into visible obligations.
3. The system can catch assumption mismatches before reuse.
4. Circular dependency and export-strength errors are reported clearly.
5. Notation and omission issues are surfaced as actionable checker output.

## Phase 4: Memory and Retrieval
**Goal:** Add layered memory and project-first retrieval.
**Requirements:** MEM-01, RET-01, RET-02
**Success Criteria:**
1. The system can persist multiple memory layers, not just plain notes.
2. Current-project results are searched before external sources.
3. External imports store source metadata and trust levels.
4. Session recovery preserves enough context to resume work accurately.

## Phase 5: Review and Trust
**Goal:** Gate imported results and make blockers explicit.
**Requirements:** REV-01, REV-02
**Success Criteria:**
1. Imported results require approval, downgrade, or rejection before reuse.
2. Blockers are visible and tied to concrete proof failures.
3. Trust changes are auditable.
4. The proof workflow makes stalled paths easy to inspect and continue.

## Phase 6: Collaborative Proof Infrastructure
**Goal:** Validate multi-user collaborative proof development with explicit governance, provenance, review, branching, team libraries, reproducible handoff, and collaboration-aware policy.
**Requirements:** PMEM-01, PMEM-02, PMEM-03
**Plans:**
- [ ] 06-PLAN.md — collaboration-aware project memory, governance, and handoff
**Success Criteria:**
1. Contributors, roles, and provenance are explicit for shared proof objects and reusable assets.
2. Review comments remain separate from theorem truth state while staying exportable and auditable.
3. Governance states and collaboration policies gate proposals, approvals, publication, callable state, and dispute resolution.
4. Handoff bundles preserve review history, branch state, shared-library dependencies, snapshots, and verification history.
5. The CLI stays terminal-native for collaboration inspection, review, and exchange.

## Phase 7: Knowledge Graph
**Goal:** Represent explicit structural relationships between proof objects.
**Requirements:** PGR-01, PGR-02, PGR-03, PGR-04
**Success Criteria:**
1. The project can store explicit graph nodes for theorem-local and memory objects.
2. The project can store explicit graph edges with the milestone's relation vocabulary.
3. Users can inspect neighbors and local dependency structure around a node.
4. Memory artifacts can be linked into the graph and back to theorem state.

## Phase 8: Retrieval and Snapshots
**Goal:** Make retrieval and session recovery project-aware.
**Requirements:** PRET-01, PRET-02, PRET-03, PSNP-01
**Success Criteria:**
1. `proof retrieve` prioritizes theorem state, linked obligations, blockers, memory, and graph adjacency before loose text matching.
2. `proof retrieve` reports known context, nearby attempts or insights, and adjacent blockers in a useful order.
3. `proof project analyze` identifies bottlenecks, central obligations, failed routes, and promising next steps.
4. Snapshots capture the current theorem, nearby memory, nearby graph structure, and suggested next focus areas.

## Phase 9: Radial System Validation
**Goal:** Prove the new memory and graph layer is useful on a real unfinished proof section.
**Requirements:** PVAL-01, PVAL-02
**Success Criteria:**
1. The unfinished higher-rank radial system section can be represented with the main theorem, the Jacquet compression gap, the scalar-to-vector lifting problem, completed lemmas and propositions, failed routes, and an explicit structural gap.
2. The workflow helps with section-level or project-level work, not just isolated theorem-local work.

## Phase-to-Requirement Mapping

| Requirement | Phase | Status |
|-------------|-------|--------|
| WS-01 | Phase 1 | Complete |
| WS-02 | Phase 1 | Complete |
| THM-01 | Phase 2 | Complete |
| THM-02 | Phase 2 | Complete |
| THM-03 | Phase 2 | Complete |
| DSL-01 | Phase 3 | Complete |
| DSL-02 | Phase 3 | Complete |
| DSL-03 | Phase 3 | Complete |
| CHK-01 | Phase 3 | Complete |
| CHK-02 | Phase 3 | Complete |
| CHK-03 | Phase 3 | Complete |
| CHK-04 | Phase 3 | Complete |
| MEM-01 | Phase 4 | Complete |
| RET-01 | Phase 4 | Complete |
| RET-02 | Phase 4 | Complete |
| REV-01 | Phase 5 | Complete |
| REV-02 | Phase 5 | Complete |
| PMEM-01 | Phase 6 | Pending |
| PMEM-02 | Phase 6 | Pending |
| PMEM-03 | Phase 6 | Pending |
| PGR-01 | Phase 7 | Pending |
| PGR-02 | Phase 7 | Pending |
| PGR-03 | Phase 7 | Pending |
| PGR-04 | Phase 7 | Pending |
| PRET-01 | Phase 8 | Pending |
| PRET-02 | Phase 8 | Pending |
| PRET-03 | Phase 8 | Pending |
| PSNP-01 | Phase 8 | Pending |
| PVAL-01 | Phase 9 | Pending |
| PVAL-02 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 29 total
- Mapped to phases: 29
- Unmapped: 0 ✓

## Phase Dependencies

- Phase 1 must come first because later work depends on persisted state.
- Phase 2 depends on Phase 1 because contracts need a stable workspace and snapshot model.
- Phase 3 depends on Phase 2 because the DSL and checker stack need contract metadata.
- Phase 4 depends on Phase 3 because memory and retrieval need structured proof objects to store.
- Phase 5 depends on Phase 4 because imported results and blocker recovery need the full state model.
- Phase 6 depends on Phase 5 because typed memory should build on the existing state, review, and snapshot plumbing.
- Phase 7 depends on Phase 6 because the graph needs memory artifacts and theorem state to link into.
- Phase 8 depends on Phases 6 and 7 because retrieval and snapshotting need both memory records and graph adjacency.
- Phase 9 depends on Phase 8 because the radial-system validation should exercise the finished memory, graph, retrieval, and snapshot layers together.

## Success Definition

The roadmap is successful if the user can:
- initialize a proof workspace,
- register and reuse theorem contracts safely,
- parse and elaborate compressed proof steps,
- recover project context across sessions,
- represent project memory and graph structure explicitly,
- retrieve useful section-level context before new proof work,
- and validate the workflow on a real unfinished proof section.

---
*Last updated: 2026-04-23 after v1.1 milestone kickoff*
