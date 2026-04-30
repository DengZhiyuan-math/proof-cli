---
phase: 06-collaborative-proof-infrastructure
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/proof_cli/collaboration.py
  - src/proof_cli/commands.py
  - src/proof_cli/cli.py
  - src/proof_cli/export.py
  - src/proof_cli/governance.py
  - src/proof_cli/reusable_assets.py
  - src/proof_cli/domain_packs.py
  - src/proof_cli/storage.py
  - src/proof_cli/theorems.py
  - src/proof_cli/review.py
  - tests/test_collaboration.py
  - tests/test_cli.py
  - tests/test_export.py
  - tests/test_governance.py
  - tests/test_reusable_assets.py
autonomous: true
requirements:
  - COL-01
  - COL-02
  - COL-03
  - COL-04
  - COL-05
  - COL-06
  - COL-07
  - COL-08
  - COL-09
must_haves:
  truths:
    - collaborative proof work must preserve provenance, review history, and explicit trust boundaries
    - comments, review decisions, and governance state must remain distinct from theorem truth state
    - shared assets and branches must be representable and reproducible without silent merges
    - the first implementation should stay CLI-first and bundle-based rather than introducing live anonymous collaboration
  artifacts:
    - src/proof_cli/collaboration.py
    - src/proof_cli/governance.py
    - src/proof_cli/export.py
    - src/proof_cli/commands.py
    - src/proof_cli/cli.py
    - src/proof_cli/reusable_assets.py
    - src/proof_cli/domain_packs.py
    - src/proof_cli/storage.py
    - src/proof_cli/theorems.py
    - src/proof_cli/review.py
    - tests/test_collaboration.py
    - tests/test_cli.py
    - tests/test_export.py
    - tests/test_governance.py
    - tests/test_reusable_assets.py
  key_links:
    - keep the collaboration model explicit enough to support later service-mode evolution without requiring it now
    - policy and review state must be auditable in exports and summaries
---

<objective>
Build Phase 6 as a governed collaborative proof infrastructure for research mathematics.

Purpose: validate that multiple researchers can collaborate on related proof projects without losing authorship, provenance, review discipline, or mathematical clarity.
Output: contributor and role model, explicit governance for shared proof objects, review/comment workflows, branch/divergence handling, team-scoped reusable knowledge, reproducible exchange/handoff, collaboration-aware policy, and validation on a real multi-user proof workflow.
Execution split: wave 1 establishes collaboration models, governance, and CLI reachability; wave 2 handles bundle import/reconstitution and the end-to-end collaboration validation harness.
</objective>

<execution_context>
@$HOME/.codex/get-shit-done/workflows/execute-plan.md
@$HOME/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/zhdeng/Proof CLI /.planning/PROJECT.md
@/Users/zhdeng/Proof CLI /.planning/ROADMAP.md
@/Users/zhdeng/Proof CLI /.planning/STATE.md
@/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/06-collaborative-proof-infrastructure/06-CONTEXT.md
@/Users/zhdeng/Proof CLI /src/proof_cli/memory.py
@/Users/zhdeng/Proof CLI /src/proof_cli/retrieval.py
@/Users/zhdeng/Proof CLI /src/proof_cli/snapshot.py
@/Users/zhdeng/Proof CLI /src/proof_cli/reusable_assets.py
@/Users/zhdeng/Proof CLI /src/proof_cli/domain_packs.py
@/Users/zhdeng/Proof CLI /src/proof_cli/governance.py
@/Users/zhdeng/Proof CLI /src/proof_cli/export.py
@/Users/zhdeng/Proof CLI /src/proof_cli/commands.py
@/Users/zhdeng/Proof CLI /src/proof_cli/cli.py
</context>

<tasks>

<task type="auto">
  <name>Define collaboration domain models and persistence</name>
  <files>src/proof_cli/collaboration.py, src/proof_cli/storage.py, src/proof_cli/theorems.py, src/proof_cli/review.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/06-collaborative-proof-infrastructure/06-CONTEXT.md</read_first>
  <action>Create explicit contributor, role, authorship, review record, comment thread, comment, branch, publication, and collaboration policy models; wire authorship and provenance into theorem contracts and review records; add persistence and loading hooks that preserve provenance and review history across sessions.</action>
  <verify>pytest tests/test_collaboration.py -q</verify>
  <acceptance_criteria>
    - proof objects can carry contributor identity and authorship
    - review state is explicit and auditable
    - project state can persist collaboration metadata across sessions
  </acceptance_criteria>
  <done>Collaboration schema and persistence are in place</done>
</task>

<task type="auto">
  <name>Expose review, comment, and branch workflows in the CLI</name>
  <files>src/proof_cli/commands.py, src/proof_cli/cli.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/06-collaborative-proof-infrastructure/06-CONTEXT.md</read_first>
  <action>Add terminal commands for contributor listing, role display, review request/decision, comment add/list, branch create/list/compare/merge, and project status summaries that surface unreviewed, disputed, and branch-dependent objects.</action>
  <verify>pytest tests/test_cli.py tests/test_collaboration.py -q</verify>
  <acceptance_criteria>
    - collaborators can inspect and act on review state from the CLI
    - discussion remains separate from theorem truth state
    - branch divergence is visible and queryable
  </acceptance_criteria>
  <done>Core collaboration workflows are reachable from the CLI</done>
</task>

<task type="auto">
  <name>Implement shared asset governance and reproducible exchange</name>
  <files>src/proof_cli/reusable_assets.py, src/proof_cli/domain_packs.py, src/proof_cli/governance.py, src/proof_cli/export.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/06-collaborative-proof-infrastructure/06-CONTEXT.md</read_first>
  <action>Extend reusable assets and domain packs with team-scoped publication, provenance propagation, review states, and policy checks; add export bundles that include state, review history, shared dependencies, and export metadata.</action>
  <verify>pytest tests/test_reusable_assets.py tests/test_export.py tests/test_governance.py -q</verify>
  <acceptance_criteria>
    - shared assets require explicit governance before publication
    - exports preserve provenance, review history, and dependencies
  </acceptance_criteria>
  <done>Shared governance and exchange are reproducible</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] contributor identity, provenance, and review states survive persistence and export
- [ ] comments and approvals remain separate from theorem truth state
- [ ] branch divergence and disputed interpretations are explicit
- [ ] shared assets and team packs require governance before reuse
</verification>

<success_criteria>

- Multiple contributors can work on a proof project without losing provenance
- Theorem contracts, obligations, blockers, and reusable assets can be reviewed collaboratively
- Comments and discussion remain separate from object truth state
- Conflicting proof paths can be represented explicitly
- Shared assets can be published and reused with governance
- Proof projects can be handed off reproducibly across users
- Collaboration improves workflow on at least one real proof project
- The researcher or team still retains explicit final authority over trust-sensitive mathematical acceptance

</success_criteria>

<output>
After completion, create `/Users/zhdeng/Proof CLI /.planning/milestones/1.0-phases/06-collaborative-proof-infrastructure/06-SUMMARY.md`
</output>
