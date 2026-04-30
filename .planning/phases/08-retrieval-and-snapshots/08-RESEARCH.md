# Phase 8 Research: Retrieval and Snapshots

**Gathered:** 2026-04-29
**Status:** Complete

## Reusable Capabilities

- `src/proof_cli/retrieval.py` already builds a structured `RetrievalReport` with `RetrievalContext`, source ordering, candidate traces, and rankable candidates.
- `src/proof_cli/proof_state.py` already assembles a project snapshot from the active theorem, current goals, open obligations, blockers, recent theorem usage, unresolved trust-sensitive calls, and recent failed routes.
- `src/proof_cli/snapshot.py` already separates snapshot creation from the rest of the CLI and records a handoff snapshot plus publication bundle snapshot metadata.
- `src/proof_cli/services.py` already exposes workspace-facing retrieval and snapshot helpers that can become the thin entrypoints for richer CLI commands.
- Existing tests already cover retrieval ordering, context-driven scoring, snapshot restore, handoff preservation, and exchange bundle behavior that touches latest and handoff snapshots.

## Missing Pieces

- There is no dedicated `proof retrieve` command that returns JSON as the canonical output.
- There is no `proof project analyze` command yet.
- Retrieval currently ranks candidates by lexical overlap plus source priority; it does not yet elevate structural proof context as an explicit front-end filter before text matching.
- Snapshot payloads currently capture proof-state and handoff state, but they do not yet carry the latest retrieval/analyze diagnostic report as a first-class artifact.
- There is no separate explicit graph storage subsystem; any "graph neighborhood" behavior must be derived from existing theorem, obligation, blocker, memory, and literature-route links.

## Recommended Workstreams

1. **Structured retrieval API first**
   - Add a JSON-first retrieval command/API that exposes the structured report already produced by `retrieve_candidates`.
   - Keep human-readable terminal rendering as a thin wrapper so downstream tooling can consume the same data shape.

2. **Project analysis command second**
   - Add `proof project analyze` as a JSON-first diagnostic view over the current proof workspace.
   - Use the active theorem, open obligations, blockers, recent memory, and local route history as the input basis.

3. **Snapshot enrichment third**
   - Extend snapshot data with the latest retrieval or analysis conclusions so snapshots become recovery points plus diagnostic context.
   - Keep the snapshot format bounded so it remains useful for handoff and restore without becoming a full database dump.

4. **Explicit neighborhood abstraction last**
   - Represent "graph neighborhood" with a deterministic, explicit neighborhood view built from existing links rather than a new inferred graph engine.
   - If the explicit links are insufficient later, treat a dedicated graph store as a separate capability.

## Risks and Ambiguities

- The existing `proof search` text output may overlap with the desired `proof retrieve` command name and behavior, so the CLI surface needs a clear naming decision.
- Moving retrieval to JSON by default may require a compatibility layer for human-friendly output and existing tests.
- Snapshot enrichment can easily become too large if it stores raw diagnostic payloads instead of a bounded summary or the latest report reference.
- Structural filtering needs a deterministic tie-break strategy so retrieval remains explainable and stable across sessions.
- Because the graph source of truth must stay explicit, Phase 8 should not infer relationships from prose even if that would be convenient for ranking.

## Decision Summary

- Treat the current theorem, obligations, blockers, memory, and explicit local neighborhood as a stronger pre-filter than loose lexical matching.
- Make JSON the canonical output for retrieval and project analysis.
- Define snapshots as work recovery points plus the latest diagnostic report.
- Build neighborhood behavior from existing explicit proof-state links instead of introducing inferred graph logic.

---
*Phase: 08-retrieval-and-snapshots*
*Context gathered: 2026-04-29*
