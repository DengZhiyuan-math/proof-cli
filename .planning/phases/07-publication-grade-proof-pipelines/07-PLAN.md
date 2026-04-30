---
phase: 07-publication-grade-proof-pipelines
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/proof_cli/publication.py
  - src/proof_cli/export.py
  - src/proof_cli/exchange.py
  - src/proof_cli/collaboration.py
  - src/proof_cli/theorems.py
  - src/proof_cli/references.py
  - src/proof_cli/review.py
  - src/proof_cli/commands.py
  - src/proof_cli/cli.py
  - src/proof_cli/storage.py
  - src/proof_cli/db.py
  - src/proof_cli/snapshot.py
  - tests/test_publication.py
  - tests/test_exchange.py
autonomous: true
requirements:
  - PUB-01
  - PUB-02
  - PUB-03
  - PUB-04
  - PUB-05
  - PUB-06
  - PUB-07
  - PUB-08
  - PUB-09
  - PUB-10
must_haves:
  truths:
    - publication-facing outputs must preserve trust distinctions instead of flattening them
    - internal-only artifacts, failed routes, and disputes must stay suppressible by default
    - publication readiness must remain distinct from theorem correctness and collaboration approval
    - the first implementation should be CLI-first and selective rather than automatic prose generation
    - release approvals and versioned bundles must be auditable
  artifacts:
    - src/proof_cli/publication.py
    - src/proof_cli/export.py
    - src/proof_cli/exchange.py
    - src/proof_cli/collaboration.py
    - src/proof_cli/theorems.py
    - src/proof_cli/references.py
    - src/proof_cli/review.py
    - src/proof_cli/commands.py
    - src/proof_cli/cli.py
    - src/proof_cli/storage.py
    - src/proof_cli/db.py
    - src/proof_cli/snapshot.py
    - tests/test_publication.py
    - tests/test_exchange.py
    - tests/test_cli.py
  key_links:
    - keep publication views tied to concrete project state, review history, and provenance rather than freeform prose
    - versioned bundles should remain reproducible and selective, not just prettier exports
---

<objective>
Build Phase 7 as a publication-grade proof delivery pipeline for research mathematics.

Purpose: validate that a proof project can be converted into paper-facing, supplement-facing, and reproducible research outputs without losing provenance, release discipline, or editorial control.
Output: publication views, claim readiness states, selective export pipelines, citation provenance export, verification and review summaries, governed release bundles, editorial controls, and validation on a real mathematical section or theorem cluster.
Execution split: wave 1 establishes publication models, export surfaces, provenance summaries, and release governance; wave 2 validates the real project delivery workflow and bundle round-tripping.
</objective>

<execution_context>
@$HOME/.codex/get-shit-done/workflows/execute-plan.md
@$HOME/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/zhdeng/Proof CLI /.planning/PROJECT.md
@/Users/zhdeng/Proof CLI /.planning/ROADMAP.md
@/Users/zhdeng/Proof CLI /.planning/STATE.md
@/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md
@/Users/zhdeng/Proof CLI /.planning/phases/07-publication-grade-proof-pipelines/07-CONTEXT.md
@/Users/zhdeng/Proof CLI /.planning/phases/07-publication-grade-proof-pipelines/07-RESEARCH.md
@/Users/zhdeng/Proof CLI /src/proof_cli/export.py
@/Users/zhdeng/Proof CLI /src/proof_cli/exchange.py
@/Users/zhdeng/Proof CLI /src/proof_cli/collaboration.py
@/Users/zhdeng/Proof CLI /src/proof_cli/theorems.py
@/Users/zhdeng/Proof CLI /src/proof_cli/references.py
@/Users/zhdeng/Proof CLI /src/proof_cli/review.py
@/Users/zhdeng/Proof CLI /src/proof_cli/commands.py
@/Users/zhdeng/Proof CLI /src/proof_cli/cli.py
@/Users/zhdeng/Proof CLI /src/proof_cli/storage.py
@/Users/zhdeng/Proof CLI /src/proof_cli/db.py
</context>

<tasks>

<task type="auto">
  <name>Define publication views and readiness state</name>
  <files>src/proof_cli/publication.py, src/proof_cli/storage.py, src/proof_cli/db.py, src/proof_cli/snapshot.py, src/proof_cli/theorems.py, src/proof_cli/collaboration.py, src/proof_cli/commands.py, src/proof_cli/cli.py, tests/test_publication.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/phases/07-publication-grade-proof-pipelines/07-CONTEXT.md</read_first>
  <action>Create publication-view and publication-state models for theorem-like claims, selection rules for paper-facing versus supplement-facing versus internal-only artifacts, persistence hooks for publication state and bundle snapshots, summary rendering for readiness reasons, and CLI commands to inspect and set publication state. Keep publication readiness distinct from theorem trust state and collaboration approval.</action>
  <verify>pytest tests/test_publication.py tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - researchers can define and inspect publication views for a proof project
    - claims can carry explicit publication readiness separate from theorem trust state
    - publication summaries explain why an object is not ready or only supplement-ready
    - publication state and snapshot metadata survive persistence boundaries
  </acceptance_criteria>
  <done>Publication views and readiness states are explicit and inspectable</done>
</task>

<task type="auto">
  <name>Implement paper, supplement, and bundle export pipelines</name>
  <files>src/proof_cli/export.py, src/proof_cli/exchange.py, src/proof_cli/commands.py, src/proof_cli/cli.py, tests/test_export.py, tests/test_exchange.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/phases/07-publication-grade-proof-pipelines/07-CONTEXT.md</read_first>
  <action>Add export paths for paper drafts, technical supplements, reproducible bundles, and export manifests. Ensure each output is selective, versioned, and traceable back to project objects. Include the publication view selection, citation manifest hooks, and redaction of internal-only artifacts by default.</action>
  <verify>pytest tests/test_export.py tests/test_exchange.py -q</verify>
  <acceptance_criteria>
    - paper, supplement, and bundle exports all exist as distinct outputs
    - exported artifacts remain reproducible and traceable to project state
    - internal-only items are suppressed unless explicitly requested
  </acceptance_criteria>
  <done>Publication export pipelines are selective and reproducible</done>
</task>

<task type="auto">
  <name>Add provenance, citation, and verification summaries</name>
  <files>src/proof_cli/references.py, src/proof_cli/review.py, src/proof_cli/theorems.py, src/proof_cli/collaboration.py, src/proof_cli/export.py, src/proof_cli/commands.py, tests/test_review.py, tests/test_publication.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/phases/07-publication-grade-proof-pipelines/07-CONTEXT.md</read_first>
  <action>Normalize citation provenance for imported, adapted, project-original, and conditional claims. Add editorial notes, theorem naming, and section placement controls alongside checklist output where useful for publication preparation. Export review summaries and verification summaries without leaking internal-only debate by default, and gate publication-facing release actions behind explicit audit logging, including explicit withdrawal records for corrected or withdrawn bundles.</action>
  <verify>pytest tests/test_publication.py tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - imported and project-original claims are distinguishable in exports
    - selected verification and review summaries can be exported cleanly
    - release approvals and corrections are recorded with provenance
    - publication exports remain selective instead of dumping raw project state
    - theorem names and section placements can be set for publication-facing output
    - bundle withdrawals are recorded explicitly and remain auditable
  </acceptance_criteria>
  <done>Provenance and review summaries are publication-ready</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] publication views exist and separate paper-facing, supplement-facing, and internal-only artifacts
- [ ] publication state is distinct from theorem trust state
- [ ] paper, supplement, and bundle exports are selective, versioned, and traceable
- [ ] citation provenance and verification summaries are exportable without flattening internal history
- [ ] release approvals are auditable and bundle round-tripping preserves context
- [ ] a real project section can be validated as publication-ready without leaking internal-only material
</verification>

<success_criteria>

- A proof project can be mapped into publication-oriented views
- Theorem-like objects have explicit publication states
- The system can generate paper, supplement, and reproducible bundle outputs
- Citation provenance and selected verification summaries can be exported appropriately
- Internal-only artifacts are not leaked by default
- Release and export history are governed and auditable
- At least one real project demonstrates value in moving from proof workspace to publication package
- Researchers remain the final editors and publication decision-makers

</success_criteria>
