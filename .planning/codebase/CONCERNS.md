# Codebase Concerns

**Analysis Date:** 2026-04-28

## Tech Debt

**Unstable durable IDs**
- Issue: Several persisted IDs are derived from Python `hash()`, including obligation, blocker, and bug IDs.
- Files: `src/proof_cli/commands.py`
- Impact: `hash()` is process-randomized, so the same input can produce different IDs across runs. That weakens deduplication, restart behavior, and cross-session references.
- Fix approach: Replace `hash()`-based IDs with a stable digest or UUID derived from canonicalized inputs.

**Split persistence model**
- Issue: Core project state lives in SQLite, but collaboration state is stored separately in `.proof/collaboration.json`.
- Files: `src/proof_cli/storage.py`, `src/proof_cli/collaboration.py`
- Impact: There are two persistence paths and two serialization strategies to keep consistent.
- Fix approach: Move collaboration records into SQLite or wrap both stores behind a single persistence boundary with explicit migration rules.

**Large orchestration module**
- Issue: `src/proof_cli/commands.py` is 2,566 lines and combines CLI dispatch, formatting, state mutation, verification flow, and publication workflows.
- Files: `src/proof_cli/commands.py`
- Impact: The file has a wide blast radius and makes targeted changes harder to isolate and review.
- Fix approach: Split commands by domain and keep the top-level CLI module thin.

## Known Bugs

**Collaboration version never advances**
- Symptoms: `save_collaboration()` always resets `CollaborationState.version` to `1` before writing.
- Files: `src/proof_cli/collaboration.py`
- Trigger: Any collaboration write path that calls `save_collaboration()`.
- Workaround: None in code.

## Security Considerations

**Not detected**
- No external auth, secret handling, or network-facing security boundary was detected in the inspected code paths.

## Performance Bottlenecks

**Heuristic matching stays in memory**
- Problem: Retrieval and verification routing use token overlap, regex cues, and fixed weights rather than indexed search or configurable scoring.
- Files: `src/proof_cli/retrieval.py`, `src/proof_cli/verification_broker.py`
- Cause: Candidate selection is computed from full-text heuristics at call time.
- Improvement path: Add a configurable ranking layer and an indexed search path for larger workspaces.

## Fragile Areas

**Persistence schema has no migration layer**
- Files: `src/proof_cli/db.py`, `src/proof_cli/storage.py`
- Why fragile: Schema bootstrap is `CREATE TABLE IF NOT EXISTS` only. No version gate or migration routine is present for evolving persisted state.
- Safe modification: Add schema version tracking and explicit upgrade steps before changing table layouts.

**Hard-coded routing rules**
- Files: `src/proof_cli/retrieval.py`, `src/proof_cli/verification_broker.py`
- Why fragile: Scoring and route selection are embedded in code, so behavior changes require source edits.
- Safe modification: Centralize route criteria and add regression tests around representative proof fragments.

## Scaling Limits

**Not detected**
- The current workspace model appears optimized for a single local project and small-to-moderate artifact counts.

## Dependencies at Risk

**Not detected**
- No high-risk external dependency or vendored integration stood out in the inspected files.

## Missing Critical Features

**Not detected**
- The codebase already has the core local-state and proof-tracking primitives needed for the current scope.

## Test Coverage Gaps

**Persistence evolution and recovery**
- What’s not tested: Schema migration, partial-write recovery, and restart behavior after store shape changes.
- Files: `src/proof_cli/db.py`, `src/proof_cli/storage.py`, `src/proof_cli/collaboration.py`
- Risk: Local state bugs can surface only after data has already been written.
- Priority: High

**Deterministic identifier behavior**
- What’s not tested: Cross-process stability for hash-derived obligation, blocker, and bug IDs.
- Files: `src/proof_cli/commands.py`
- Risk: Repeated commands can produce different IDs for the same logical input.
- Priority: High

---

*Concerns audit: 2026-04-28*
