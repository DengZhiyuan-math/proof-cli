# Requirements: Mathematical Proof CLI

**Defined:** 2026-04-21
**Core Value:** Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Workspace and State

- [x] **WS-01**: User can initialize a proof project workspace and resume it across sessions
- [x] **WS-02**: User can view the current project state, including open goals and blockers, from the CLI

### Theorem Registry

- [x] **THM-01**: User can register a theorem, lemma, proposition, or corollary as a reusable contract
- [x] **THM-02**: User can record assumptions, exports, and dependencies for each contract
- [x] **THM-03**: User can tell whether a contract is callable in the current proof context

### Proof Scripts and Elaboration

- [ ] **DSL-01**: User can write a proof script in a CLI-friendly DSL and have it parsed into explicit steps
- [ ] **DSL-02**: User can expand omitted or compressed proof steps into checkable obligations
- [ ] **DSL-03**: User can attach DSL steps to either a local proof action or an existing contract

### Checks and Validation

- [ ] **CHK-01**: User can verify that current assumptions satisfy a contract before reuse
- [ ] **CHK-02**: User can detect when an imported conclusion is stronger than the contract actually exports
- [ ] **CHK-03**: User can detect circular dependencies in proof paths
- [ ] **CHK-04**: User can flag notation mismatches and unresolved omissions that require elaboration

### Retrieval and Memory

- [ ] **MEM-01**: User can store and retrieve structured proof memory across working, semantic, episodic, and procedural layers
- [ ] **RET-01**: User can search current project results before looking outside the project
- [ ] **RET-02**: User can import an external result with source metadata and a trust level

### Review and Trust

- [ ] **REV-01**: User can approve, downgrade, or reject imported results before they are callable
- [ ] **REV-02**: User can inspect a blocker log that records why a proof path stalled

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Browser Console

- **WEB-01**: User can view a browser-based dependency graph
- **WEB-02**: User can inspect project snapshots in a browser console

### Automation Enhancements

- **AUTO-01**: System can suggest likely next proof steps without requiring an explicit script
- **AUTO-02**: System can rank candidate external results automatically

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Fully formal kernel for all proof steps | The v1 goal is trustworthy collaboration, not complete formalization |
| Replacing final human judgment | The product is a collaborator, not an autonomous mathematician |
| Browser-first experience | The initial interface must stay CLI-first to preserve the workflow |
| Summary-only memory | It cannot represent obligations, dependencies, or trust accurately |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| WS-01 | Phase 1 | Complete |
| WS-02 | Phase 1 | Complete |
| THM-01 | Phase 2 | Complete |
| THM-02 | Phase 2 | Complete |
| THM-03 | Phase 2 | Complete |
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

---
*Requirements defined: 2026-04-21*
*Last updated: 2026-04-21 after initial definition*
