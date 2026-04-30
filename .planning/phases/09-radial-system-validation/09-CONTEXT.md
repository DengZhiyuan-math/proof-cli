# Phase 9: Radial System Validation - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase validates the new memory, retrieval, snapshot, and publication workflow on a real unfinished proof cluster from the higher-rank radial-system area.

The validation slice should be smaller than the full section: it should be organized around a theorem cluster that reflects proof logic and complexity, not necessarily the article's writing order. The goal is to prove that the workflow helps organize the proof, expose small gaps, and make continued progress easier.

This phase is not about completing the entire radial-system section, inventing a new graph model, or replacing mathematical judgment. It is about proving that the existing local-first proof OS can meaningfully support a hard section-level proof task.

</domain>

<decisions>
## Implementation Decisions

### Validation slice selection
- **D-01:** Use a smaller theorem cluster rather than the full section as the primary validation slice.
- **D-02:** Partition the slice by proof logic and complexity, not by article exposition order.
- **D-03:** The slice should still be representative of the real section, so it can expose genuine proof-work behavior rather than a toy example.

### Structural depth
- **D-04:** Represent the slice with full structure: the main theorem, the Jacquet compression gap, the scalar-to-vector lifting problem, completed lemmas and propositions, failed routes, and the explicit structural gap.
- **D-05:** Include intermediate methods, insights, dependencies, and any other explicit links needed to make the cluster navigable and auditable.
- **D-06:** Do not collapse the cluster into a minimal summary-only view; the point is to preserve enough structure to reason about the proof.

### Success criterion
- **D-07:** Success means the workflow makes it easier to continue the proof, reorganize the reasoning, or discover small gaps that were easy to miss before.
- **D-08:** The phase should demonstrate practical benefit, not just that the section can be recorded or rendered.
- **D-09:** The validation should support both project-level understanding and section-level progress, so it can be reused for ongoing proof work after the phase ends.

### the agent's Discretion
- Exact choice of theorem cluster inside the radial-system section.
- Exact granularity of explicit nodes and links beyond the required core structure.
- Whether the phase validation artifacts are captured as a reusable section bundle, a working snapshot, or both.

</decisions>

<specifics>
## Specific Ideas

- The user wants the validation slice to be smaller than the full section, but still structurally faithful.
- The user prefers proof partitions that follow logical order and complexity rather than article order.
- The workflow should help the user continue proofs, clarify the reasoning, or uncover small gaps.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `/Users/zhdeng/Proof CLI /.planning/PROJECT.md` - current project framing, constraints, and active milestone context
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md` - requirement vocabulary and Phase 9 traceability
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md` - roadmap structure, dependency ordering, and Phase 9 success criteria
- `/Users/zhdeng/Proof CLI /.planning/STATE.md` - current planning state and milestone progress

### Prior phase context
- `/Users/zhdeng/Proof CLI /.planning/phases/08-retrieval-and-snapshots/08-CONTEXT.md` - retrieval, snapshot, and diagnosis decisions that Phase 9 will exercise
- `/Users/zhdeng/Proof CLI /.planning/phases/07-publication-grade-proof-pipelines/07-CONTEXT.md` - publication and release validation patterns for the same validation family

### Relevant codebase entry points
- `/Users/zhdeng/Proof CLI /src/proof_cli/analysis.py` - JSON diagnostic reporting for proof work
- `/Users/zhdeng/Proof CLI /src/proof_cli/retrieval.py` - retrieval ranking, context prioritization, and explicit neighborhood handling
- `/Users/zhdeng/Proof CLI /src/proof_cli/proof_state.py` - snapshot assembly, latest diagnostic report capture, and state persistence
- `/Users/zhdeng/Proof CLI /src/proof_cli/snapshot.py` - snapshot creation and handoff mechanics
- `/Users/zhdeng/Proof CLI /src/proof_cli/exchange.py` - bundle export/import and handoff preservation
- `/Users/zhdeng/Proof CLI /src/proof_cli/commands.py` - CLI command surface for retrieval, project analysis, snapshots, and export workflows
- `/Users/zhdeng/Proof CLI /src/proof_cli/cli.py` - Typer app wiring for CLI subcommands

### Relevant tests
- `/Users/zhdeng/Proof CLI /tests/test_retrieval.py` - retrieval ordering, context usage, and JSON serialization expectations
- `/Users/zhdeng/Proof CLI /tests/test_proof_state.py` - state summary and snapshot behavior
- `/Users/zhdeng/Proof CLI /tests/test_snapshot.py` - recovery and handoff snapshot preservation
- `/Users/zhdeng/Proof CLI /tests/test_exchange.py` - bundle import/export behavior that touches latest and handoff snapshots
- `/Users/zhdeng/Proof CLI /tests/test_cli.py` - CLI wiring and JSON command surfaces

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ProjectDiagnosticReport` already gives a bounded JSON diagnosis that can be exercised on a real theorem cluster.
- `RetrievalReport`, `RetrievalCandidate`, and `RetrievalContext` already capture the local structural context needed to orient the slice.
- `ProjectSnapshot` and handoff bundle preservation already provide a recovery-point model that can carry the latest diagnostic report.
- CLI wrappers for `proof retrieve`, `proof project analyze`, and snapshot/export workflows already exist, so Phase 9 can focus on validation rather than new surfaces.

### Established Patterns
- Retrieval already prefers theorem-local and explicitly linked context before loose matching.
- Snapshot creation already records both project and handoff snapshots, so the phase can validate recovery rather than inventing a new persistence path.
- The current project has a pattern of validating real, non-toy slices with bounded summaries and explicit provenance.

### Integration Points
- Phase 9 should exercise retrieval, analysis, snapshots, and exchange together on the same proof cluster.
- The workflow should show how a section-level proof task becomes easier to navigate when the proof structure is split by logic and difficulty rather than by prose order.
- Any reusable validation output should stay compatible with the current JSON-first CLI commands and snapshot payloads.

</code_context>

<deferred>
## Deferred Ideas

- Building a new graph storage subsystem would be a separate capability if the current explicit links are not enough.
- Automatic graph inference from prose remains out of scope; the graph source of truth must stay explicit and auditable.
- Replacing the higher-rank radial-system validation with a fully different mathematical section would be a scope change for a later phase.

</deferred>

---

*Phase: 09-radial-system-validation*
*Context gathered: 2026-04-29*
