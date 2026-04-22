---
phase: 02-registry
plan: 03
subsystem: theorem-registry
tags: [theorems, provenance, review-state, versioning, pytest]
requires:
  - phase: 02-registry
    provides: provenance-aware theorem contracts with explicit review state and preserved version history
provides:
  - theorem provenance fields
  - theorem review state
  - explicit supersession/version history
affects: [02-04, 02-05, 02-06, 02-07, 02-08]
key-files:
  modified:
    - src/proof_cli/domain.py
    - src/proof_cli/theorems.py
    - tests/test_theorems.py
requirements-completed: [THM-01, THM-02]
completed: 2026-04-21
---

# Phase 2 Registry Plan 03 Summary

Extended the theorem registry so imported and local contracts share one provenance-aware model with explicit review state, grounded source links, usage notes, and versioned supersession.

## Accomplishments

- Added theorem provenance and review enums to the core domain model
- Extended `TheoremContract` with provenance kind, review state, grounded references, grounded theorem links, per-origin usage notes, and explicit supersession tracking
- Updated theorem writes so each revision records which earlier version it supersedes
- Added usage-note support that preserves prior versions instead of mutating history in place
- Tightened callability checks so imported theorems stay blocked until they are explicitly approved
- Added tests that prove provenance/review round-tripping, separate usage-note storage, and historical version preservation

## Verification

- `python -m pytest tests/test_theorems.py -q`
- `python -m pytest tests/test_theorems.py tests/test_storage.py -q`

## Files Changed

- `src/proof_cli/domain.py`
- `src/proof_cli/theorems.py`
- `tests/test_theorems.py`

## Deviations from Plan

None.

## Issues Encountered

None.

## Next Step Readiness

- The registry now retains provenance and review state on theorem records.
- Contract replacements preserve prior versions in the SQLite history table.
- Imported results remain non-callable until review approval.

