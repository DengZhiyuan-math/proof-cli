# Phase 07: Publication-Grade Proof Pipelines, Ecosystem Integration, and Reproducible Research Delivery - Context

**Gathered:** 2026-04-23
**Status:** Ready for planning
**Source:** user-provided phase specification in the gsd-plan-phase request

<domain>
## Phase Boundary

This phase validates whether Mathematical Proof CLI can turn an internal proof project into a publication-grade research delivery pipeline without collapsing trust distinctions.

The phase is not about automatic paper authorship, automatic journal submission, or publishing all internal artifacts by default. It is about publication-facing views, claim readiness states, selective export pipelines, provenance-aware citation output, verification/review summaries, and governed release bundles.

The phase should demonstrate that the proof OS can move from proof development and collaboration into a controlled publication and delivery workflow while preserving human editorial judgment and project traceability.

## Phase Outcome

The phase should answer one concrete product question:

Can a research proof OS turn internal proof-state, review, and verification artifacts into publication-grade, reproducible mathematical outputs without collapsing trust distinctions?

</domain>

<decisions>
## Implementation Decisions

### Publication model
- Add publication-facing views that select which proof objects appear in a paper draft, supplement, or reproducible bundle.
- Keep publication-state separate from theorem trust-state so a claim can be internally credible without being externally ready.

### Export model
- Support paper, supplement, and reproducible bundle outputs with manifests and versioning.
- Preserve traceability from publication artifacts back to internal project objects.

### Editorial model
- Support editorial notes, theorem naming and section placement, and unresolved-writing checklists.
- Keep human authors as final editors for publication-facing content.

### Provenance and citation model
- Export citation provenance that distinguishes imported, adapted, project-original, and conditional claims.
- Make citation-relevant output explicit enough for external readers and internal reviewers.

### Review and verification model
- Export review summaries and verification summaries selectively, not as a dump of all internal reasoning.
- Suppress internal-only debate unless explicitly chosen for a supplement or bundle.

### Release governance model
- Require explicit approval for publication-facing bundles and versioned exports.
- Track approvals, corrections, and withdrawals as auditable release history.

### Validation model
- Validate the workflow on a real substantial section or theorem cluster, including at least one project-original claim, one imported result, one verification artifact, and one artifact that must remain internal-only.

### the agent's Discretion
- Exact publication-state storage backend and whether it lives with theorem records or in a dedicated publication module.
- Bundle serialization format choices across Markdown, JSON, and archive packaging.
- Whether citation manifests are embedded in export bundles or emitted as separate artifacts.
- How dense the CLI should be for editorial and release workflows in the first pass.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `/Users/zhdeng/Proof CLI /.planning/PROJECT.md` — current project framing, constraints, and active milestone context
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md` — current requirement vocabulary and out-of-scope boundaries
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md` — roadmap structure and dependency ordering
- `/Users/zhdeng/Proof CLI /.planning/STATE.md` — current planning state

### Existing phase patterns
- `/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/06-collaborative-proof-infrastructure/06-CONTEXT.md` — latest collaboration phase context and style reference
- `/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/05-review-and-trust/05-CONTEXT.md` — review and trust phase patterns this work extends

### Relevant codebase entry points
- `/Users/zhdeng/Proof CLI /src/proof_cli/export.py` — current export surface and bundled summaries
- `/Users/zhdeng/Proof CLI /src/proof_cli/exchange.py` — bundle export/import and handoff mechanics
- `/Users/zhdeng/Proof CLI /src/proof_cli/collaboration.py` — contributors, governance, comments, and publication state for shared assets
- `/Users/zhdeng/Proof CLI /src/proof_cli/theorems.py` — theorem trust and provenance handling
- `/Users/zhdeng/Proof CLI /src/proof_cli/review.py` — review and verification rendering
- `/Users/zhdeng/Proof CLI /src/proof_cli/references.py` — reference metadata and review state
- `/Users/zhdeng/Proof CLI /src/proof_cli/storage.py` — persistence entry points and SQLite schema access
- `/Users/zhdeng/Proof CLI /src/proof_cli/db.py` — schema definitions for persisted project state
- `/Users/zhdeng/Proof CLI /src/proof_cli/commands.py` — CLI command surface for current workflows
- `/Users/zhdeng/Proof CLI /src/proof_cli/cli.py` — Typer app wiring for CLI subcommands

</canonical_refs>

<specifics>
## Specific Ideas

- Publication views should separate paper-facing, supplement-facing, and internal-only artifacts.
- Claim readiness should be explicit and separate from theorem correctness or trust state.
- Export pipelines should include paper draft, technical supplement, reproducible bundle, and manifest outputs.
- Citation export should preserve origin and attribution for imported, adapted, and project-original claims.
- Verification and review summaries should be selectively externalized, not flattened into generic notes.
- Release governance should require explicit approval, versioning, and correction/withdrawal history.
- Validation should use a real project section close enough to publication form to expose editorial tradeoffs.

</specifics>

<deferred>
## Deferred Ideas

- Automatic paper authorship without researcher control.
- Automatic journal submission.
- Fully automatic conversion of arbitrary proof state into polished prose.
- Public open repository distribution as the default mode.
- Replacing human mathematical writing style and exposition decisions.

</deferred>

---

*Phase: 07-publication-grade-proof-pipelines*
*Context gathered: 2026-04-23 via user-provided phase specification*
