# Phase 5: Compounding Research Knowledge, Supervised Proof Automation, and Multi-Project Proof Intelligence - Context

**Gathered:** 2026-04-22
**Status:** Ready for planning
**Source:** User-provided Phase 5 spec in this thread

<domain>
## Phase Boundary

Phase 5 extends the earlier proof-state, retrieval, compositional reasoning, and formal-bridge layers into a compounding research environment. It must let researchers reuse structured proof knowledge across projects, package domain-specific workflows, and run bounded supervised automation loops without weakening trust boundaries.

This phase is not a fully autonomous mathematician. Its job is to prove that the system becomes more useful over time because it accumulates structured mathematical experience and can safely automate bounded, reviewable proof work.

</domain>

<decisions>
## Implementation Decisions

### Product shape
- Multi-project and compounding by default
- Reuse requires reviewable provenance and trust levels
- Bounded automation is preferred over open-ended autonomy
- Human review remains mandatory for trust-sensitive updates

### Reuse model
- Reusable assets include theorem contracts, proof patterns, repair strategies, bug archetypes, verification fragments, method cards, and checklists
- The system distinguishes project-local, domain-shared, private experimental, and approved reusable assets
- Domain packs package reusable workflows and can be installed into projects

### Automation policy
- Automation runs under explicit policy profiles
- Actions are classified by risk and reversibility
- Dry-run and approval modes must exist
- Audit traces and rollback/interrupt support are required

### Measurement model
- Reuse outcomes are tracked and evaluated
- Compounding value must be measurable
- Automation effectiveness must be benchmarked over time

### the agent's Discretion
- Exact schema for reusable assets, packs, and automation traces
- How to encode policy profiles and approval thresholds
- Whether recommendation ranking is heuristic, learned, or hybrid
- Internal module boundaries for asset registry, automation, governance, and metrics

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` - project vision, core value, and constraints
- `.planning/ROADMAP.md` - phase structure and roadmap sequencing
- `.planning/REQUIREMENTS.md` - requirement traceability and v1 scope
- `.planning/STATE.md` - current project memory and focus
- `.planning/phases/04-memory-and-retrieval/04-CONTEXT.md` - Phase 4 selective formal-bridge and verification boundaries
- `.planning/phases/04-memory-and-retrieval/04-01-SUMMARY.md` through `.planning/phases/04-memory-and-retrieval/04-08-SUMMARY.md` - Phase 4 implementation results and validation notes

### Phase 5 Specification
- This conversation's Phase 5 spec - compounding knowledge, supervised automation, and multi-project proof intelligence

</canonical_refs>

<specifics>
## Specific Ideas

- Required reusable asset types: theorem contracts, imported reference contracts, proof patterns, blocker patterns, repair strategies, bug archetypes, verification fragments, method cards, checklists
- Required automation workflow order: inspect current proof state, retrieve local and shared assets, check policy, generate plan, review when required, run bounded actions, record trace and artifacts, require review for trust-sensitive updates, publish reusable outcomes only after approval
- Required CLI surface: `proof asset list`, `proof asset show`, `proof asset publish`, `proof asset review`, `proof pack list`, `proof pack install`, `proof pack update`, `proof automate plan`, `proof automate run`, `proof automate trace`, `proof automate review`, `proof policy list`, `proof policy set`, `proof recommend`, `proof benchmark run`, `proof reuse show`
- Required validation target: two to three related proof projects, at least one reusable theorem family, at least one reusable proof pattern, at least one reusable blocker-repair pattern, at least one domain pack used in more than one project, at least one bounded automation loop that genuinely saves time, and at least one rejected automated action handled by policy

</specifics>

<deferred>
## Deferred Ideas

- Fully autonomous theorem proving without human oversight
- Global automatic trust upgrades
- Unrestricted self-modifying agent behavior
- Removing the researcher from final theorem acceptance
- Replacing proof assistants
- Replacing literature review with autonomous browsing alone

</deferred>

---

*Phase: 05-review-and-trust*
*Context gathered: 2026-04-22 via user-provided Phase 5 spec*
