# Phase 8: Retrieval and Snapshots - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase makes retrieval and session recovery project-aware.

The phase is not about adding a new proof kernel, replacing human judgment, or turning retrieval into a remote search service. It is about making `proof retrieve` and `proof project analyze` understand the current proof workspace first, then fall back to looser matching only after the local structural context has been considered.

The phase should also make snapshots behave like durable work recovery points for long-running proof sessions, while preserving the recent diagnostic context that led to the current state.

</domain>

<decisions>
## Implementation Decisions

### Retrieval priority
- **D-01:** Retrieval should treat the current theorem, open obligations, blockers, recent memory, and explicit graph neighborhood as a stronger front-end filter than loose text matching.
- **D-02:** The retrieval stack should continue to prefer project-local context before imported references and external bibliographic sources, but the structural context of the active proof work should be considered even earlier in the ranking pipeline.
- **D-03:** The relevant "graph neighborhood" for this phase should come from explicit project links that already exist in the workspace model, not from inferred prose relationships.
- **D-03a:** When external literature is needed, a thin web-assisted lookup layer is acceptable as long as the result can be grounded to a specific theorem, proposition, lemma, or book result with exact source metadata.
- **D-03b:** External lookup should be treated as a reference-finding aid, not as an authoritative proof source unless the exact cited result is identified and recorded.

### Output shape
- **D-04:** `proof retrieve` and `proof project analyze` should default to machine-readable JSON output.
- **D-05:** Human-readable terminal rendering can be layered on top of the JSON shape, but JSON is the canonical output for downstream tooling in this phase.

### Snapshot semantics
- **D-06:** A snapshot should be treated as a work recovery point plus the latest diagnostic report, not as a full database dump.
- **D-07:** The snapshot payload should center on the active theorem, open obligations, blockers, memory, and the most recent retrieval or analysis conclusions needed to resume work.
- **D-08:** The snapshot should be useful for both resuming a session and handing work off to another person or another run of the CLI.

### the agent's Discretion
- Exact ranking weights for structural context versus lexical matching.
- Whether the JSON shape is emitted directly by the command or via a shared serializer plus a terminal-facing formatter.
- Whether snapshot refresh happens only on explicit command invocation or also after selected state-changing actions.

</decisions>

<specifics>
## Specific Ideas

- "Current theorem / obligations / blockers / memory / graph neighborhood" should be pulled into retrieval before any loose text match.
- The user wants snapshots to feel like "work recovery point + recent diagnosis report."
- JSON should be the primary output form for these phase 8 commands.
- External web lookup is acceptable as a helper when it finds a specific cited result, but the workspace must record exact citation details so the result remains auditable.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` - current project framing, milestone context, and non-negotiables
- `.planning/REQUIREMENTS.md` - current requirement vocabulary, out-of-scope boundaries, and Phase 8 traceability
- `.planning/ROADMAP.md` - roadmap structure, phase dependencies, and Phase 8 success criteria
- `.planning/STATE.md` - current phase status and project progress snapshot

### Existing phase context
- `.planning/phases/07-publication-grade-proof-pipelines/07-CONTEXT.md` - latest phase boundary and discussion style reference

### Existing code paths
- `src/proof_cli/retrieval.py` - retrieval ranking, project-local ordering, and candidate serialization
- `src/proof_cli/snapshot.py` - snapshot creation and handoff bundle capture
- `src/proof_cli/proof_state.py` - snapshot assembly, latest snapshot tracking, and project state persistence
- `src/proof_cli/services.py` - workspace-facing helpers that expose retrieval and snapshot behavior
- `src/proof_cli/commands.py` - CLI command surface, including `proof search`, snapshot, and export orchestration
- `src/proof_cli/cli.py` - Typer entrypoint wiring for CLI subcommands

### Relevant tests
- `tests/test_retrieval.py` - retrieval ordering, context usage, and serialization expectations
- `tests/test_proof_state.py` - state summary and snapshot behavior
- `tests/test_snapshot.py` - recovery and handoff snapshot preservation
- `tests/test_exchange.py` - bundle import/export behavior that touches latest and handoff snapshots

### No external specs
- No separate spec or ADR files were present for this phase; the required boundaries are already captured in the project docs and roadmap.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RetrievalReport`, `RetrievalCandidate`, and `RetrievalContext` already provide a structured basis for a JSON-first retrieval API.
- `ProjectSnapshot`, `HandoffSnapshot`, and the handoff helpers already provide a durable recovery-point model that can be extended with diagnostic metadata.
- `cmd_snapshot`, `workspace_snapshot`, and `create_snapshot` already separate the snapshot workflow from the rest of the CLI.

### Established Patterns
- Retrieval already prefers project-local data before imported and external candidates.
- Snapshot creation already records both a project snapshot and a handoff snapshot, so Phase 8 can build on an existing recovery concept instead of inventing a new one.
- CLI commands are already routed through `commands.py`, with `services.py` acting as a thin workspace-facing wrapper where appropriate.

### Integration Points
- Retrieval output connects to `proof retrieve` / `proof search` behavior in `commands.py` and `cli.py`.
- Snapshot content connects to `proof_state.py`, `snapshot.py`, `storage.py`, and exchange bundle import/export.
- Any Phase 8 graph-neighborhood work must integrate with the existing theorem, obligation, blocker, and memory link fields rather than introducing a parallel trust model.

</code_context>

<deferred>
## Deferred Ideas

- Adding a new explicit graph storage subsystem would be a separate capability if the existing explicit links turn out not to be enough.
- Automatic graph inference from prose stays out of scope; the graph source of truth must remain explicit and auditable.

</deferred>

---

*Phase: 08-retrieval-and-snapshots*
*Context gathered: 2026-04-28*
