# Phase 3: Compositional Proof Reasoning, Evidence Chains, and Proof-Debug Automation - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning
**Source:** User-provided Phase 3 spec in this thread

<domain>
## Phase Boundary

Phase 3 extends the Phase 2 retrieval and grounding workflow into structured proof reasoning assistance. It must let researchers decompose large proof projects compositionally, derive local obligations from downstream theorem intent, detect hidden proof bugs, and generate explicit evidence chains plus proof-debug tasks for suspected issues.

This phase is still not a full formal proof assistant and does not replace human theorem judgment. Its job is to validate that the system can reason about proof structure well enough to uncover meaningful defects and produce auditable debug artifacts.

</domain>

<decisions>
## Implementation Decisions

### Product shape
- CLI-first and audit-first
- Reasoning remains explicit, typed, and reviewable
- Proof-debug output must attach to proof state as first-class artifacts
- Human confirmation remains mandatory for trust-sensitive outcomes

### Reasoning model
- Proof projects are handled compositionally rather than monolithically
- Theorem intent drives downstream obligation synthesis
- Local contract adequacy is checked against downstream use
- Suspicion reports must include reasoning paths and missing conditions

### Bug policy
- Bug reports use typed categories, severity, and confidence
- Suspicion states are distinct from confirmed defects
- Evidence chains are required for meaningful bug reports
- Debug tasks are generated from bug type and proof context

### Data model
- ProofBugReport is a first-class artifact
- EvidenceChain records reasoning paths and missing conditions
- DebugTask records actionable next steps
- Suspicion outcomes are persisted and linked back to proof artifacts

### the agent's Discretion
- Exact detector heuristics and thresholding
- Whether bug scanning is rule-based, heuristic, or hybrid
- The granularity of reasoning units and obligation synthesis
- Command naming and CLI presentation details
- Internal module boundaries for reasoning, evidence, and debug-task services

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` - project vision, core value, and constraints
- `.planning/ROADMAP.md` - phase structure and roadmap sequencing
- `.planning/REQUIREMENTS.md` - requirement traceability and v1 scope
- `.planning/STATE.md` - current project memory and focus
- `.planning/phases/02-registry/02-CONTEXT.md` - Phase 2 decisions and retrieval/reference grounding boundaries
- `.planning/phases/02-registry/02-01-SUMMARY.md` through `.planning/phases/02-registry/02-08-SUMMARY.md` - Phase 2 implementation results and validation notes

### Phase 3 Specification
- This conversation's Phase 3 spec - compositional reasoning, evidence chains, bug detection, and repair workflow
- [FM-Agent paper](https://arxiv.org/html/2604.11556v1) - inspiration for top-down compositional reasoning and evidence-backed bug confirmation

</canonical_refs>

<specifics>
## Specific Ideas

- Required reasoning workflow order: inspect current proof state, retrieve relevant project and imported results, check applicability, derive missing obligations, scan for proof-bug patterns, generate evidence chains, propose debug tasks, then wait for human review
- Required CLI surface: `proof reason`, `proof obligation derive`, `proof bug scan`, `proof bug list`, `proof bug show`, `proof evidence show`, `proof debug generate`, `proof debug list`, `proof repair mark`, `proof review suspicion`, `proof trace dependency`, `proof explain apply`
- Required bug statuses: suspected, under_review, confirmed, dismissed, repaired, superseded
- Required bug metadata: bug type, description, severity, confidence, linked contracts, linked obligations, linked blockers
- Required evidence-chain metadata: reasoning path, missing conditions, review recommendation
- Validation target: one theorem with multiple lemma layers, at least one imported theorem used as a black box, one omitted standard step, one fragile blocker, one downstream usage that surfaces a hidden condition, and at least one genuine near-bug or bug confirmed by the human reviewer

</specifics>

<deferred>
## Deferred Ideas

- Full formal verification kernel
- Autonomous theorem acceptance
- Complete automatic proof generation
- Exhaustive counterexample generation across all mathematical domains
- Replacement of external literature review
- Removal of human theorem judgment

</deferred>

---

*Phase: 03-dsl-and-checks*
*Context gathered: 2026-04-21 via user-provided Phase 3 spec*
