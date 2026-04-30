# Phase 9 Research: Radial System Validation

**Gathered:** 2026-04-29
**Status:** Complete

## Reusable Capabilities

- `src/proof_cli/retrieval.py` already prioritizes theorem state, obligations, blockers, recent memory, and explicit neighborhood before loose lexical matching.
- `src/proof_cli/analysis.py` already builds a bounded JSON diagnostic report with bottlenecks, failed routes, explicit neighborhood, and promising next steps.
- `src/proof_cli/proof_state.py` already captures the latest diagnostic report inside snapshots, so the workflow can be exercised as a recovery point plus diagnosis.
- `src/proof_cli/snapshot.py` and `src/proof_cli/exchange.py` already support handoff-style recovery and round-tripping of the snapshot payload.
- `src/proof_cli/debug_tasks.py` already turns gap-like proof issues into actionable follow-up tasks such as omission gap investigation, missing lemma isolation, boundary checks, and dependency cycle breaks.
- Existing tests already cover retrieval ordering, JSON command surfaces, snapshot restore, and exchange bundle behavior, so Phase 9 can validate on top of an existing proof OS stack instead of inventing a new one.

## Missing Pieces

- There is no dedicated validation slice for the higher-rank radial-system area yet.
- There is no phase-specific fixture that models a smaller theorem cluster partitioned by proof logic and complexity instead of article order.
- There is no explicit validation artifact that proves the workflow helps the user continue the proof, reorganize reasoning, or discover small gaps on this concrete cluster.
- The current codebase has no separate graph storage subsystem, so any neighborhood behavior must continue to come from existing theorem, obligation, blocker, memory, and route links.

## Recommended Workstreams

1. **Build a smaller theorem-cluster validation slice**
   - Use a section fragment rather than the full higher-rank radial-system section.
   - Partition by proof logic and complexity, not by prose order.
   - Include the main theorem, the Jacquet compression gap, the scalar-to-vector lifting problem, completed lemmas and propositions, failed routes, and the explicit structural gap.

2. **Exercise the workflow end to end on that slice**
   - Run retrieval, analysis, snapshot creation, and handoff-style round-tripping against the same cluster.
   - Confirm the JSON outputs still expose the relevant structure and that the recovery payload stays bounded.
   - Confirm the current workflow helps with proof continuation, reasoning cleanup, or small-gap discovery.

3. **Add a validation regression artifact**
   - Capture the cluster as a dedicated regression test or test fixture so the proof slice remains reproducible.
   - Keep the validation artifact aligned with the JSON-first CLI surfaces introduced in Phase 8.

## Risks and Ambiguities

- The phrase "real unfinished proof section" needs to be represented as a smaller theorem cluster, but the exact cluster boundary still needs to be chosen carefully so the slice is representative without being too large.
- If the validation artifact only summarizes the cluster, it may underprove the usefulness criterion; if it becomes too large, it may stop being a manageable validation target.
- The phase should not drift into inventing a new graph model or a new persistence layer just to make the section look nicer.
- The workflow needs to show practical usefulness, not only that the data can be stored and rendered.

## Decision Summary

- Validate on a smaller theorem cluster carved out by proof logic and complexity.
- Preserve the full structural picture inside that cluster, including the main theorem, gap, supporting lemmas, failed routes, and explicit missing bridge.
- Treat success as practical help: easier continuation, clearer reasoning, or discovery of small gaps.
- Reuse the existing retrieval, diagnostic, snapshot, and exchange stack rather than creating a new validation subsystem.

## Validation Architecture

- **Framework:** pytest-based regression validation over existing CLI and state helpers.
- **Quick run command:** `pytest tests/test_phase9_validation.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q`
- **Full run command:** `pytest tests/test_phase9_validation.py tests/test_retrieval.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q`
- **Validation focus:** demonstrate that a smaller theorem cluster can be retrieved, diagnosed, snapshotted, and handed off in a way that makes the proof easier to continue.
- **Evidence sources:** retrieval report ordering, project diagnostic output, snapshot restore payloads, and exchange round-tripping.
- **Manual observation:** whether the validation cluster makes the proof structure easier to navigate and exposes a small missing bridge or gap that was not obvious before.

---
*Phase: 09-radial-system-validation*
*Context gathered: 2026-04-29*
