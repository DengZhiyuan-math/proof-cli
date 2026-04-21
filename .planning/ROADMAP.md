# Roadmap: Mathematical Proof CLI

**Created:** 2026-04-21
**Core Value:** Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

## Phase Overview

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Foundation | 7/7 | Complete    | 2026-04-21 |
| 2 | Registry | Make theorem contracts first-class and callable | THM-01, THM-02, THM-03 | 4 |
| 3 | DSL and Checks | Parse proof scripts and validate omissions, assumptions, and dependency safety | DSL-01, DSL-02, DSL-03, CHK-01, CHK-02, CHK-03, CHK-04 | 5 |
| 4 | Memory and Retrieval | Add layered memory and project-first retrieval | MEM-01, RET-01, RET-02 | 4 |
| 5 | Review and Trust | Gate imported results and make blockers explicit | REV-01, REV-02 | 4 |

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

## Phase-to-Requirement Mapping

| Requirement | Phase | Status |
|-------------|-------|--------|
| WS-01 | Phase 1 | Pending |
| WS-02 | Phase 1 | Pending |
| THM-01 | Phase 2 | Pending |
| THM-02 | Phase 2 | Pending |
| THM-03 | Phase 2 | Pending |
| DSL-01 | Phase 3 | Pending |
| DSL-02 | Phase 3 | Pending |
| DSL-03 | Phase 3 | Pending |
| CHK-01 | Phase 3 | Pending |
| CHK-02 | Phase 3 | Pending |
| CHK-03 | Phase 3 | Pending |
| CHK-04 | Phase 3 | Pending |
| MEM-01 | Phase 4 | Pending |
| RET-01 | Phase 4 | Pending |
| RET-02 | Phase 4 | Pending |
| REV-01 | Phase 5 | Pending |
| REV-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0 ✓

## Phase Dependencies

- Phase 1 must come first because later work depends on persisted state.
- Phase 2 depends on Phase 1 because contracts need a stable workspace and snapshot model.
- Phase 3 depends on Phase 2 because the DSL and checker stack need contract metadata.
- Phase 4 depends on Phase 3 because memory and retrieval need structured proof objects to store.
- Phase 5 depends on Phase 4 because imported results and blocker recovery need the full state model.

## Success Definition

The roadmap is successful if the user can:
- initialize a proof workspace,
- register and reuse theorem contracts safely,
- parse and elaborate compressed proof steps,
- recover project context across sessions,
- and control trust changes for imported results.

---
*Last updated: 2026-04-21 after roadmap creation*
