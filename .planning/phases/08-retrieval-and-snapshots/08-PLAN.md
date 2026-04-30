---
phase: 08-retrieval-and-snapshots
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 06-collaborative-proof-infrastructure
    provides: collaboration history, shared handoff bundles, and explicit provenance links
  - phase: 07-publication-grade-proof-pipelines
    provides: publication metadata, bundle snapshots, and selective release history
files_modified:
  - src/proof_cli/analysis.py
  - src/proof_cli/retrieval.py
  - src/proof_cli/proof_state.py
  - src/proof_cli/snapshot.py
  - src/proof_cli/services.py
  - src/proof_cli/commands.py
  - src/proof_cli/cli.py
  - src/proof_cli/domain.py
  - tests/test_retrieval.py
  - tests/test_proof_state.py
  - tests/test_snapshot.py
  - tests/test_exchange.py
  - tests/test_cli.py
autonomous: true
requirements:
  - PRET-01
  - PRET-02
  - PRET-03
  - PSNP-01
must_haves:
  truths:
    - retrieval must prioritize explicit proof-work context before loose lexical matching
    - retrieval and project analysis must be JSON-first for downstream tooling
    - snapshots must function as work recovery points plus the latest diagnostic report
    - graph neighborhood behavior must be derived from explicit workspace links, not inferred prose
    - external web-assisted literature lookup is allowed as a thin helper when it resolves to a specific cited result with exact source metadata
    - existing CLI behavior should remain understandable through compatibility wrappers where needed
  artifacts:
    - src/proof_cli/analysis.py
    - src/proof_cli/retrieval.py
    - src/proof_cli/proof_state.py
    - src/proof_cli/snapshot.py
    - src/proof_cli/services.py
    - src/proof_cli/commands.py
    - src/proof_cli/cli.py
    - src/proof_cli/domain.py
    - tests/test_retrieval.py
    - tests/test_proof_state.py
    - tests/test_snapshot.py
    - tests/test_exchange.py
    - tests/test_cli.py
  key_links:
    - keep retrieval/report composition close to the existing structured data models already used by the workspace
    - keep snapshots bounded so they remain useful for recovery and handoff without becoming a full database dump
---

<objective>
Implement project-aware retrieval and recovery for the proof workspace.

Purpose: make `proof retrieve` and `proof project analyze` understand the current theorem state first, then emit JSON reports that downstream tooling can consume directly. Snapshots should become recovery points that also carry the latest diagnostic context needed to resume work.

Execution split:
1. Build JSON-first retrieval and project-analysis reports with structural prefiltering.
2. Enrich snapshots so they carry the latest diagnostic report in bounded form.
3. Keep CLI compatibility and round-trip tests stable while the new canonical JSON commands land.
</objective>

<threat_model>
## Threat Model

### High severity
- Internal-only diagnostic details leak into retrieval or snapshot JSON.
  - Mitigation: keep diagnostic payloads bounded, avoid dumping raw internal histories by default, and redact any sensitive publication/review data from recovery summaries.

- External literature lookup returns a vague or uncited answer.
  - Mitigation: require exact source identification for any external result that gets recorded, and keep the web-assisted layer as a reference-finding aid rather than a freeform answer generator.

### Medium severity
- Structural prefiltering over-prioritizes an unsafe local route or stale result.
  - Mitigation: keep the ranking deterministic, preserve source ordering, and add regression tests for representative theorem / obligation / blocker / memory mixes.

- Snapshot payloads grow into a pseudo-database dump.
  - Mitigation: store a concise recovery report instead of unbounded candidate histories or full trace logs.

### Low severity
- New canonical JSON commands break familiar terminal output.
  - Mitigation: keep `proof search` as a compatibility wrapper and preserve a readable summary path where needed.
</threat_model>

<tasks>

<task type="auto">
  <name>Build JSON-first retrieval and project analysis reports</name>
  <files>src/proof_cli/analysis.py, src/proof_cli/retrieval.py, src/proof_cli/services.py, src/proof_cli/commands.py, src/proof_cli/cli.py, tests/test_retrieval.py, tests/test_cli.py</files>
  <action>Create a canonical JSON retrieval path that elevates current theorem context, open obligations, blockers, recent memory, and explicit local neighborhood before loose text matching. Add `proof retrieve` as the canonical command and keep `proof search` as a compatibility wrapper over the same structured report. Add `proof project analyze` as a JSON-first diagnostic command that summarizes bottlenecks, promising next steps, and the local structural neighborhood of the current proof work.</action>
  <verify>pytest tests/test_retrieval.py tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - retrieval reports expose structured JSON for downstream tooling
    - current theorem / obligations / blockers / memory / neighborhood are evaluated before loose lexical matching
    - `proof retrieve` is the canonical structured command
    - `proof search` still works as a readable compatibility wrapper
    - `proof project analyze` returns JSON that identifies the current bottleneck and promising next steps
  </acceptance_criteria>
  <done>Retrieval and project analysis are JSON-first and structurally aware</done>
</task>

<task type="auto">
  <name>Enrich snapshots with the latest diagnostic report</name>
  <files>src/proof_cli/analysis.py, src/proof_cli/proof_state.py, src/proof_cli/snapshot.py, src/proof_cli/domain.py, src/proof_cli/services.py, src/proof_cli/commands.py, tests/test_proof_state.py, tests/test_snapshot.py, tests/test_exchange.py</files>
  <action>Extend the snapshot model so a snapshot can carry a bounded diagnostic report alongside the normal recovery state. Preserve the existing recovery contents, but add the most recent analysis / retrieval conclusions needed to resume work after context loss or handoff. Keep the diagnostic payload compact and readable in JSON.</action>
  <verify>pytest tests/test_proof_state.py tests/test_snapshot.py tests/test_exchange.py -q</verify>
  <acceptance_criteria>
    - snapshots remain valid recovery points for active theorem, obligations, blockers, and memory
    - the latest diagnostic report is present in snapshot JSON
    - the diagnostic payload is bounded rather than a full dump
    - snapshot restore and exchange round-tripping preserve the new recovery context
  </acceptance_criteria>
  <done>Snapshots carry recovery context plus the latest diagnostic report</done>
</task>

<task type="auto">
  <name>Stabilize CLI and regression coverage</name>
  <files>src/proof_cli/commands.py, src/proof_cli/cli.py, src/proof_cli/services.py, tests/test_cli.py, tests/test_retrieval.py, tests/test_snapshot.py</files>
  <action>Wire the new JSON-first commands cleanly into the CLI, keep compatibility behavior understandable, and add regression coverage for the new output shapes, ordering rules, and snapshot handoff behavior. Make sure the phase still behaves well when users come from the existing `proof search` and `proof snapshot` paths.</action>
  <verify>pytest tests/test_retrieval.py tests/test_snapshot.py tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - CLI subcommands expose `proof retrieve`, `proof project analyze`, and a stable `proof search` wrapper
    - output remains deterministic enough for tests and downstream tooling
    - snapshot and retrieval behavior still round-trips cleanly through the workspace
  </acceptance_criteria>
  <done>CLI behavior is stable and regression-covered</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] retrieval is structural-first and JSON-first
- [ ] project analysis returns a useful diagnostic report
- [ ] snapshots store bounded diagnostic context in addition to recovery state
- [ ] graph neighborhood behavior uses explicit links, not inferred prose
- [ ] compatibility wrappers and tests remain stable

</verification>

<success_criteria>

- `proof retrieve` prioritizes theorem state, obligations, blockers, memory, and explicit neighborhood before loose text matching
- `proof project analyze` produces a machine-readable diagnosis of the current proof bottleneck and promising next steps
- snapshots preserve enough context to resume or hand off work cleanly
- diagnostic context stays bounded and auditable
- the existing CLI remains familiar while the new canonical JSON commands land
- any external literature lookup that enters the workspace is tied to a specific cited result and remains auditable

</success_criteria>
