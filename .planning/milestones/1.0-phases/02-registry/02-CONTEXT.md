# Phase 2: Retrieval, Reference Grounding, and Assisted Proof Orchestration - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning
**Source:** User-provided Phase 2 spec in this thread and `/Users/zhdeng/Downloads/mathematical_proof_cli_project_plan.md`

<domain>
## Phase Boundary

Phase 2 extends the Phase 1 local-state model into a retrieval-first proof workflow. It must let researchers search internal project results, inspect imported and external references, ground theorem use in callable contracts, preserve richer proof memory, and keep trust-sensitive literature use auditable.

This phase is still CLI-first and human-reviewed. It is not a full proof assistant and it is not a browser product. Its job is to prove that retrieval, reference grounding, and proof orchestration materially improve long-running mathematical research work.

</domain>

<decisions>
## Implementation Decisions

### Product shape
- CLI-first and local-state-first
- Retrieval before proof search
- Imported references stay candidate until reviewed
- Human approval is mandatory for trust-sensitive changes

### Workflow
- Search project-local theorem contracts first
- Search imported local references second
- Search approved external sources third
- Distinguish bibliographic relevance from callable mathematical use
- Treat proof memory as structured artifacts, not flat notes

### Data model
- ReferenceRecord is a first-class object
- ImportedContractReview records approval and rationale
- MemoryArtifact is typed by working, semantic, episodic, or procedural use
- ProofStepProvenance records which contracts and references were used

### Checker policy
- Imported contracts must satisfy assumption matching before reuse
- Export-strength mismatches and unresolved external-use cases are warnings or obligations, not silent acceptances
- Dependency and provenance tracing must remain visible

### the agent's Discretion
- Exact external adapter selection and ranking heuristics
- Whether retrieval uses SQLite FTS, metadata APIs, embeddings, or a combination
- Exact memory retention and summarization strategy
- Command naming details for retrieval and grounding flows
- Internal module boundaries for retrieval, import, and memory services

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` - project vision, core value, and constraints
- `.planning/ROADMAP.md` - phase structure and current roadmap sequencing
- `.planning/REQUIREMENTS.md` - requirement traceability and v1 scope
- `.planning/STATE.md` - current project memory and focus
- `.planning/phases/01-foundation/01-CONTEXT.md` - Phase 1 decisions and implementation boundaries

### Phase 2 Specification
- `/Users/zhdeng/Downloads/mathematical_proof_cli_project_plan.md` - project proposal and technical rationale
- This conversation's Phase 2 spec - retrieval-first phase boundary, deliverables, workstreams, and acceptance criteria

</canonical_refs>

<specifics>
## Specific Ideas

- Required retrieval order: project-verified results, imported callable contracts, imported candidate references, approved local references, external bibliographic sources, then new proof search
- Required CLI surface: `proof search`, `proof reference list`, `proof reference show`, `proof reference import`, `proof reference review`, `proof theorem extract`, `proof theorem ground`, `proof memory list`, `proof memory show`, `proof memory add`, `proof provenance show`
- Required memory layers: working, semantic, episodic, procedural, and handoff snapshots
- Required reference fields: title, authors, year, source type, origin, bibliographic source, identifier, url, notes, review status, trust level
- Required provenance fields: used contracts, used references, grounding status, notes
- Validation target: one real theorem project with multiple lemmas, at least two imported standard results, at least one imported research-paper result, at least one blocker, and at least one rejected or narrowed literature candidate

</specifics>

<deferred>
## Deferred Ideas

- Full formal logic kernel
- Automatic theorem proving at scale
- Browser-first UI
- Large-scale autonomous literature crawling
- Complete semantic parsing of arbitrary research papers
- Fully automatic trust upgrades without human review

</deferred>

---

*Phase: 02-registry*
*Context gathered: 2026-04-21 via user-provided Phase 2 spec*
