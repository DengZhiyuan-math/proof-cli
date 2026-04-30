# Phase 07 Research: Publication-Grade Proof Pipelines

**Gathered:** 2026-04-23
**Status:** Complete

## Reusable Capabilities

- Theorem contracts already carry assumptions, exports, dependencies, provenance kind, review state, grounded reference/theorem IDs, contributors, and usage notes.
- Collaboration state already models contributors, review records, comment threads, branches, shared asset publications, and collaboration policy.
- Export already emits reasoning, imported references, grounded theorems, collaboration, verification support, bug/evidence/debug state, repair state, memory counts, reusable assets, domain packs, policy profiles, automation runs, recommendations, reuse outcomes, and benchmarks.
- Exchange bundles already preserve project state, latest snapshot, handoff snapshot, memory, collaboration, theorem contracts, obligations, blockers, references, reference reviews, reusable assets, domain packs, and policies.
- Retrieval already ranks project-local theorem state and cross-project assets/packs using text match, trust, provenance, and prior usefulness.

## Missing Pieces

- There is no publication-state schema or publication-view model for theorem-like claims.
- There is no graph-free publication release record, manifest, or versioned paper/supplement bundle structure.
- Citation provenance is shallow and is not yet normalized into structured export artifacts.
- Release governance is recorded in collaboration state but not enforced at the publication boundary.
- Review support is record-level, not release-level; there are no publication/release review summaries.
- Export bundles are not yet publication-grade because they do not include publication views, citation manifests, or release metadata.
- There is no dedicated CLI surface for paper export, supplement export, publication state management, editorial notes, or release approvals.

## Recommended Workstreams

1. Publication views and readiness states first, because exports need a stable inclusion/exclusion model.
2. Export pipelines second, because paper, supplement, and bundle outputs are the user-facing payoff.
3. Provenance, citation, and verification summaries third, because external readers need traceable support artifacts.
4. Release governance and validation last, because publication approvals and the real-project workflow depend on the earlier layers.

## Risks and Ambiguities

- Publication-state storage may duplicate lifecycle concepts already used for reusable assets unless the model is normalized.
- Citation granularity is unresolved: theorem-level, step-level, or manifest-level provenance all imply different schemas.
- Bundle format needs a decision between preserving the current human-readable export style or introducing a new machine-readable manifest-first artifact.
- There are no graph-specific concerns in this phase, but publication exports must still stay selective and reproducible.
- New tests will be required for publication views, export/selective inclusion, release approvals, and bundle round-tripping.

