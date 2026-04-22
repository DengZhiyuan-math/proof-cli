---
phase: 03-dsl-and-checks
plan: 02
subsystem: proof-reasoning
tags: [obligations, reasoning, downstream-use, auditability, pytest]
requires:
  - phase: 02-registry
    provides: theorem contracts, grounding, and obligation-aware proof state
provides:
  - downstream theorem use now synthesizes explicit open obligations
  - synthesized obligations carry provenance through ids, dependencies, and events
  - reviewable obligation persistence for reasoning-driven proof debts
affects: [phase-03-dsl-and-checks, proof-debug, checker-output]
tech-stack:
  added: []
  patterns: [top-down obligation synthesis, explicit audit trail for derived proof debt]
key-files:
  created:
    - tests/test_obligations.py
  modified:
    - src/proof_cli/reasoning.py
    - src/proof_cli/obligations.py
    - tests/test_obligations.py
key-decisions:
  - "Derived obligations stay open and reviewable instead of auto-binding into proof state."
  - "Downstream use, theorem intent, and intermediate claims are linked through deterministic obligation ids and dependency tokens."
patterns-established:
  - "Pattern 1: theorem intent expands into downstream obligations before acceptance"
  - "Pattern 2: synthesized obligations are persisted with explicit audit events"
requirements-completed: [DSL-02]
duration: 35min
completed: 2026-04-21
---

# Phase 3 Plan 02 Summary

Downstream theorem usage now expands into explicit, reviewable proof obligations instead of disappearing into prose.

## Performance

- **Duration:** 35 min
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments

- Added downstream obligation synthesis to the reasoning model for missing assumptions, missing exports, and intermediate claims.
- Added persistence helpers that convert synthesized reasoning obligations into open `ProofObligation` records with audit events.
- Added focused tests proving that derived obligations are visible, linked to downstream use, and stored as reviewable state.

## Files Created/Modified

- `src/proof_cli/reasoning.py` - derived obligation synthesis helpers on reasoning artifacts
- `src/proof_cli/obligations.py` - conversion and persistence helpers for synthesized obligations
- `tests/test_obligations.py` - downstream-use obligation synthesis and persistence coverage

## Decisions Made

- Kept synthesized obligations open rather than closing or auto-accepting them.
- Used deterministic obligation ids and dependency tokens so downstream links remain auditable.

## Deviations from Plan

- None

## Issues Encountered

- None

## Next Phase Readiness

Phase 3 can build on explicit downstream obligation synthesis for checker, bug, and debug workflows.

