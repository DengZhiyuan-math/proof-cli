---
phase: 13-codex-e2e-validation
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 10-command-invocation-surface
    provides: deterministic read-only wrapper routing
  - phase: 11-mutation-routing-and-root-resolution
    provides: real theorem / obligation / blocker / snapshot mutation routing
  - phase: 12-bootstrap-and-wrapper-hardening
    provides: readiness diagnostics and canonical global-skill clarification
files_modified:
  - tests/test_cli.py
  - tests/test_phase9_validation.py
  - src/proof_cli/codex_router.py
  - .planning/phases/13-codex-e2e-validation/13-01-SUMMARY.md
  - .planning/STATE.md
  - .planning/ROADMAP.md
  - .planning/REQUIREMENTS.md
autonomous: true
requirements:
  - VAL-01
  - VAL-02
  - VAL-03
must_haves:
  truths:
    - the main validation evidence should be a realistic Codex-driven proof workflow, not only smoke tests
    - the validation slice should resemble the user's real research workflow through a small theorem cluster
    - the final success standard must argue improved usability, not just technical correctness
    - the wrapper surface built in phases 10 through 12 remains the only command path under validation
  artifacts:
    - tests/test_cli.py
    - tests/test_phase9_validation.py
    - .planning/phases/13-codex-e2e-validation/13-01-SUMMARY.md
  key_links:
    - reuse the theorem-cluster validation pattern proven in Phase 9
    - preserve the hardened wrapper and diagnostics behavior from Phases 10 to 12
---

<objective>
Prove that the hardened Codex-facing command layer works as a realistic ongoing proof-work interface.

Purpose: validate that a user can actually use `$proof ...` / `proof codex ...` to manage a small theorem cluster end to end, and show that the resulting workflow is more direct, less ambiguous, and more sustainable than the earlier skill-only experience.
</objective>

<threat_model>
## Threat Model

### High severity
- The phase only re-runs technical smoke tests and never proves real workflow usefulness.
  - Mitigation: require a realistic theorem-cluster workflow as the primary validation artifact.

- The final validation slice is so toy-like that it says nothing about real research use.
  - Mitigation: reuse the Phase 9 pattern of a bounded but structurally meaningful theorem cluster.

- The summary claims usability improvements without evidence.
  - Mitigation: tie the summary to explicit workflow observations such as reduced ambiguity, direct mutation routing, clear diagnostics, and easier continuation via snapshots.

### Medium severity
- The validation bypasses the wrapper and accidentally validates lower-level commands instead.
  - Mitigation: keep the wrapper surface as the command path under test and narrative validation.

- The final phase regresses prior routing behavior while adding new validation coverage.
  - Mitigation: preserve and extend current smoke tests rather than replacing them.

### Low severity
- The difference between `$proof ...` and `proof codex ...` becomes confusing in the final write-up.
  - Mitigation: explain that the validation centers on the Codex-facing command surface and keep both phrasings aligned in the narrative.
</threat_model>

<tasks>

<task type="auto">
  <name>Build a realistic small theorem-cluster validation workflow</name>
  <files>tests/test_cli.py, tests/test_phase9_validation.py</files>
  <action>Create or adapt a bounded theorem-cluster validation slice that feels closer to the user's actual research workflow than a toy theorem. The workflow should include state inspection, theorem creation, obligation tracking, blocker tracking, and snapshotting through the Codex-facing command layer.</action>
  <verify>python -m pytest tests/test_cli.py tests/test_phase9_validation.py -q</verify>
  <acceptance_criteria>
    - the validation slice is a small theorem cluster rather than a purely abstract toy command demo
    - theorem, obligation, blocker, and snapshot behavior are all exercised
    - the validation reflects realistic proof-state progression
  </acceptance_criteria>
  <done>A realistic theorem-cluster workflow exists for final validation</done>
</task>

<task type="auto">
  <name>Validate the full Codex-facing command layer end to end</name>
  <files>tests/test_cli.py, src/proof_cli/codex_router.py</files>
  <action>Extend smoke or workflow tests so the hardened wrapper path is exercised end to end, including readiness, state inspection, mutation routing, and continuation behavior. Keep the command layer under test as the primary surface, not the lower-level handlers in isolation.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - the wrapper path is exercised as an end-to-end surface
    - the validation covers open/init, inspect, mutate, and snapshot behavior
    - existing hardened behaviors from Phases 10 to 12 continue to pass
  </acceptance_criteria>
  <done>The hardened command layer is validated as a single coherent workflow</done>
</task>

<task type="auto">
  <name>Write a strong usability-focused final validation summary</name>
  <files>.planning/phases/13-codex-e2e-validation/13-01-SUMMARY.md, .planning/STATE.md, .planning/ROADMAP.md, .planning/REQUIREMENTS.md</files>
  <action>Summarize the validation in a way that explicitly argues why the new command surface is more usable than before: more direct, less ambiguous, and better suited for ongoing proof work. Tie that conclusion to the theorem-cluster workflow and the command-layer behavior that the user actually experienced.</action>
  <verify>summary includes workflow evidence and requirement closure</verify>
  <acceptance_criteria>
    - the final summary argues usability improvement, not just test passage
    - requirement closure for `VAL-01`, `VAL-02`, and `VAL-03` is explicit
    - milestone state can move cleanly toward audit/completion after this phase
  </acceptance_criteria>
  <done>The milestone has a persuasive end-to-end validation record</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] a realistic small theorem-cluster workflow is under validation
- [ ] the wrapper surface is the thing being validated end to end
- [ ] theorem, obligation, blocker, and snapshot behavior are all covered
- [ ] the final summary argues improved usability, not just technical passage
- [ ] Phase 13 closes `VAL-01`, `VAL-02`, and `VAL-03`

</verification>

<success_criteria>

- A realistic Codex-facing proof workflow runs end to end through the hardened command layer.
- The validation shows the system is more direct, less ambiguous, and more sustainable for ongoing use than before.
- Supporting tests preserve regression confidence while the main evidence remains workflow-centered.

</success_criteria>
