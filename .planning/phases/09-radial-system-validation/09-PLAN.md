---
phase: 09-radial-system-validation
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 06-collaborative-proof-infrastructure
    provides: collaboration history, handoff bundles, provenance, and explicit review state
  - phase: 07-publication-grade-proof-pipelines
    provides: publication views, selective exports, and round-trippable bundle state
  - phase: 08-retrieval-and-snapshots
    provides: JSON-first retrieval, project diagnostics, and bounded recovery snapshots
files_modified:
  - tests/test_phase9_validation.py
  - .planning/phases/09-radial-system-validation/09-SUMMARY.md
autonomous: true
requirements:
  - PVAL-01
  - PVAL-02
must_haves:
  truths:
    - the validation slice must be a smaller theorem cluster, not the full section
    - the cluster must be partitioned by proof logic and complexity, not by article writing order
    - the validation must preserve the full structural picture: main theorem, Jacquet compression gap, scalar-to-vector lifting problem, completed lemmas and propositions, failed routes, and the explicit structural gap
    - the workflow must demonstrate practical value by making it easier to continue the proof, reorganize the reasoning, or discover a small gap
    - validation artifacts must stay compatible with the existing JSON-first retrieval, analysis, snapshot, and exchange surfaces
  artifacts:
    - tests/test_phase9_validation.py
    - .planning/phases/09-radial-system-validation/09-SUMMARY.md
  key_links:
    - keep the validation fixture close to the existing retrieval, diagnostic, snapshot, and exchange helpers
    - keep the summary bounded so it records the proof-work benefit without turning into a new proof repository
---

<objective>
Validate the radial-system workflow on a smaller theorem cluster that represents the proof logic of the unfinished section more faithfully than article order would.

Purpose: prove that the current retrieval, diagnostic, snapshot, and exchange stack can help organize a real proof cluster, expose a small missing bridge or gap, and make continued proof work easier.

Execution split:
1. Build a reproducible regression fixture for the smaller theorem cluster and assert that retrieval and diagnostics stay structure-first.
2. Run the end-to-end workflow on the same cluster, verify snapshot and exchange preservation, and record the observed proof-work benefit in a bounded summary.
</objective>

<threat_model>
## Threat Model

### High severity
- The validation slice becomes too synthetic and no longer reflects the real proof structure.
  - Mitigation: seed a real theorem cluster with the exact proof-logic roles required by the phase and keep the explicit gap visible in the fixture.

- Snapshot or exchange round-tripping loses the structural gap or the diagnostic context that makes the validation useful.
  - Mitigation: assert that `latest_diagnostic_report`, the active theorem, and the explicit neighborhood survive the recovery path.

- The summary leaks too much internal proof reasoning and becomes a second proof repository.
  - Mitigation: keep the summary bounded to the observed workflow benefit, the cluster boundary, and the specific small gap that was uncovered.

### Medium severity
- The validation fixture overfits to one set of ids and becomes brittle.
  - Mitigation: keep assertions tied to role and structure names as well as the chosen ids, and verify the diagnostic shape rather than only one exact string.

- The phase proves the data can be stored, but not that it helps the user reason better.
  - Mitigation: require a manual observation note in the summary that states whether the workflow clarified the next proof step or gap.

### Low severity
- The regression output becomes noisy because too many existing tests are pulled into the validation command.
  - Mitigation: keep the new validation test focused and use the existing retrieval/snapshot/exchange/CLI tests only where they directly exercise the same cluster.
</threat_model>

<tasks>

<task type="auto">
  <name>Build the smaller theorem-cluster validation fixture</name>
  <files>tests/test_phase9_validation.py, tests/test_retrieval.py, tests/test_snapshot.py, tests/test_exchange.py, tests/test_cli.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/phases/09-radial-system-validation/09-CONTEXT.md</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/retrieval.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/analysis.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/proof_state.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/snapshot.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/exchange.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/commands.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/cli.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_retrieval.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_snapshot.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_exchange.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_cli.py</read_first>
  <action>Create a dedicated regression test file that seeds a smaller theorem cluster with the exact roles `thm_radial_main`, `thm_jacquet_gap`, `thm_scalar_lift`, `lem_radial_bridge`, `lem_vector_support`, `obl_jacquet_gap`, `blk_scalar_lift`, a failed route note, and a few memory artifacts. Assert that `retrieve_candidates` ranks `thm_radial_main` first, `cmd_proof_retrieve` JSON exposes the explicit neighborhood entries, `cmd_project_analyze` reports a blocker or obligation bottleneck with cluster-aware next steps, and `create_snapshot` / `restore_snapshot` preserve `latest_diagnostic_report` and the handoff context.</action>
  <verify>pytest tests/test_phase9_validation.py tests/test_retrieval.py tests/test_snapshot.py tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - `tests/test_phase9_validation.py` exists
    - the file contains the ids `thm_radial_main`, `thm_jacquet_gap`, `thm_scalar_lift`, `lem_radial_bridge`, `lem_vector_support`, `obl_jacquet_gap`, and `blk_scalar_lift`
    - `retrieve_candidates` asserts `thm_radial_main` is first for the validation slice
    - `cmd_proof_retrieve` JSON checks the explicit neighborhood and the current theorem
    - `cmd_project_analyze` JSON checks the bottleneck and next-step output
    - snapshot restore checks preserve `latest_diagnostic_report`
  </acceptance_criteria>
  <done>Radial-system validation fixture and regression coverage are in place</done>
</task>

<task type="auto">
  <name>Run the end-to-end workflow and record the validation result</name>
  <files>.planning/phases/09-radial-system-validation/09-SUMMARY.md, tests/test_phase9_validation.py</files>
  <read_first>/Users/zhdeng/Proof CLI /.planning/phases/09-radial-system-validation/09-VALIDATION.md</read_first>
  <read_first>/Users/zhdeng/Proof CLI /.planning/phases/09-radial-system-validation/09-CONTEXT.md</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/retrieval.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/analysis.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/proof_state.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/snapshot.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/exchange.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/commands.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /src/proof_cli/cli.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_phase9_validation.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_exchange.py</read_first>
  <read_first>/Users/zhdeng/Proof CLI /tests/test_cli.py</read_first>
  <action>Exercise the same validation cluster through `cmd_proof_retrieve`, `cmd_project_analyze`, snapshot creation, snapshot restore, and exchange bundle round-tripping, then write `.planning/phases/09-radial-system-validation/09-SUMMARY.md` with the smaller theorem-cluster boundary, the proof-logic partitioning, the observed workflow benefit, and any small gap discovered. Keep the summary bounded and explicit about whether the workflow made the proof easier to continue, clarified reasoning, or exposed a small missing bridge.</action>
  <verify>pytest tests/test_phase9_validation.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - `09-SUMMARY.md` exists
    - the summary contains the phrase `smaller theorem cluster`
    - the summary mentions proof-logic or complexity-based partitioning
    - the summary states whether the workflow made the proof easier to continue, clarified reasoning, or exposed a small gap
    - the exchange/snapshot validation command exits successfully
  </acceptance_criteria>
  <done>Validation results are captured in a bounded phase summary</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] the validation slice is smaller than the full section
- [ ] the slice is partitioned by proof logic and complexity
- [ ] retrieval stays structure-first on the validation cluster
- [ ] snapshots and exchange preserve the latest diagnostic context
- [ ] the workflow demonstrates practical proof-work benefit

</verification>

<success_criteria>

- The unfinished higher-rank radial-system work can be represented with the main theorem, the Jacquet compression gap, the scalar-to-vector lifting problem, completed lemmas and propositions, failed routes, and an explicit structural gap.
- The validation slice is smaller than the full section and is organized by proof logic and complexity rather than article order.
- The workflow makes it easier to continue the proof, reorganize the reasoning, or discover a small gap.
- Retrieval, diagnostics, snapshots, and exchange all preserve the validation cluster’s structure.
- Validation artifacts remain bounded, auditable, and reusable for ongoing section-level work.

</success_criteria>
