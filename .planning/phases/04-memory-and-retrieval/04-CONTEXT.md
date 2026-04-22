# Phase 4: Formal Bridge, Machine-Checkable Proof Fragments, and Verified Closure Loops - Context

**Gathered:** 2026-04-22
**Status:** Ready for planning
**Source:** User-provided Phase 4 spec in this thread

<domain>
## Phase Boundary

Phase 4 extends the earlier proof-state, retrieval, compositional reasoning, and proof-debug layers into a selective formal bridge. It must let researchers escalate high-risk or high-value proof obligations into machine-checkable fragments, route those fragments to appropriate backends, and integrate machine-check results back into proof state in a reviewable way.

This phase is still not a full theorem prover. It is a selective closure workflow for fragile proof components, designed to increase trust without requiring end-to-end formalization.

</domain>

<decisions>
## Implementation Decisions

### Product shape
- CLI-first and review-first
- Selective formalization is preferred over blanket formalization
- Machine-check success never silently upgrades a broader theorem claim
- Human acceptance is required for strong trust upgrades

### Verification model
- Verification artifacts must be typed, serializable, and auditable
- Verification results attach to theorem contracts, obligations, blockers, and proof-step provenance
- Stale fragments must be detected when dependencies change
- Backend choice is brokered by obligation type and capability match

### Data model
- VerificationFragment is a first-class artifact
- VerificationResult records machine-check outcomes
- FormalizationRecommendation ranks escalation candidates
- StalenessRecord tracks invalidation after dependency changes
- MachineCheckProvenance links verification back to proof state

### the agent's Discretion
- Exact IR schema shape and status vocabulary
- Which backend adapters are implemented first
- How translation and backend selection are represented internally
- The exact heuristic for selecting formalization candidates
- Internal module boundaries for bridge, broker, adapters, and revalidation services

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` - project vision, core value, and constraints
- `.planning/ROADMAP.md` - phase structure and roadmap sequencing
- `.planning/REQUIREMENTS.md` - requirement traceability and v1 scope
- `.planning/STATE.md` - current project memory and focus
- `.planning/phases/03-dsl-and-checks/03-CONTEXT.md` - Phase 3 decisions and proof-debug boundaries
- `.planning/phases/03-dsl-and-checks/03-01-SUMMARY.md` through `.planning/phases/03-dsl-and-checks/03-08-SUMMARY.md` - Phase 3 implementation results and validation notes

### Phase 4 Specification
- This conversation's Phase 4 spec - formal bridge, verification IR, backend broker, and staleness lifecycle
- [FM-Agent paper](https://arxiv.org/html/2604.11556v1) - inspiration for compositional reasoning and evidence-backed bug confirmation

</canonical_refs>

<specifics>
## Specific Ideas

- Required verification workflow order: inspect state, identify high-risk obligations, choose escalation, translate to IR, inspect translation, run machine-check path, review result, integrate accepted result, then track staleness
- Required CLI surface: `proof formalize recommend`, `proof formalize show`, `proof formalize edit`, `proof verify queue`, `proof verify run`, `proof verify status`, `proof verify result`, `proof verify accept`, `proof verify reject`, `proof verify stale`, `proof trace machine-check`, `proof revalidate`
- Required verification states: queued_for_verification, machine_checked, backend_failed, translation_failed, stale_after_change, rejected_by_human, accepted_after_review
- Required fragment metadata: source type, source id, scope, ir version, translation status, backend target, dependency versions, status
- Required result metadata: backend, summary, artifacts, review status
- Validation target: one nontrivial theorem with several intermediate lemmas, at least one fragile theorem application, one standard step converted into explicit side conditions, one blocker narrowed or resolved by stronger checking, at least one fragment successfully escalated, and at least one failure or stale result handled explicitly

</specifics>

<deferred>
## Deferred Ideas

- Full end-to-end formalization of arbitrary research papers
- Replacing mature proof assistants with a new foundational kernel
- Autonomous theorem acceptance without human review
- Proving all imported literature results inside the system
- Fully automatic translation of arbitrary mathematical prose into proof code
- Mandatory formalization of all proof work

</deferred>

---

*Phase: 04-memory-and-retrieval*
*Context gathered: 2026-04-22 via user-provided Phase 4 spec*
