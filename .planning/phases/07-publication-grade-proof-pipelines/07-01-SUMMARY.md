---
phase: 07-publication-grade-proof-pipelines
plan: 01
subsystem: publication
tags: [publication, export, exchange, review, typer, pydantic, sqlite, testing]

# Dependency graph
requires:
  - phase: 06-collaborative-proof-infrastructure
    provides: collaboration review state, release history, shared publication governance, and exchange bundles
provides:
  - publication workspace state separate from theorem trust state
  - paper-facing, supplement-facing, and internal publication views
  - selective paper/supplement/bundle export surfaces with redaction by default
  - auditable publication bundle snapshots and release history
affects:
  - phase 07 wave 2 publication validation
  - later publication/export and snapshot workflows

# Tech tracking
tech-stack:
  added: [pydantic models for publication workspace state, Typer publication commands, selective JSON/markdown exports]
  patterns: [readiness separated from theorem trust, visibility-based view selection, redacted public exports, bundle snapshot persistence]

key-files:
  created: [src/proof_cli/publication.py, tests/test_publication.py, tests/test_exchange.py]
  modified: [src/proof_cli/commands.py, src/proof_cli/cli.py, src/proof_cli/export.py, src/proof_cli/exchange.py, src/proof_cli/proof_state.py, src/proof_cli/snapshot.py, src/proof_cli/storage.py, src/proof_cli/db.py, src/proof_cli/domain.py, src/proof_cli/references.py, src/proof_cli/review.py, src/proof_cli/theorems.py, tests/test_cli.py, tests/test_export.py, tests/test_review.py]

key-decisions:
  - "Kept publication readiness in a dedicated workspace record so theorem trust and editorial readiness remain distinct."
  - "Used view audiences plus visibility filtering to separate paper, supplement, and internal exports."
  - "Recorded bundle snapshots when exports or snapshots are created so release history survives exchange boundaries."
  - "Redacted internal-only claims, editorial notes, and snapshot payloads from paper-facing exports."

patterns-established:
  - "Pattern 1: publication state lives alongside the project, not inside theorem trust fields."
  - "Pattern 2: public exports derive from filtered views, not raw workspace dumps."
  - "Pattern 3: bundle exports write auditable snapshot records."
  - "Pattern 4: CLI publication commands expose inspect/set/export/release actions explicitly."

requirements-completed: [PUB-01, PUB-02, PUB-03, PUB-04, PUB-05, PUB-06, PUB-07]

# Metrics
duration: 21m
completed: 2026-04-23
---

# Phase 07: Publication-Grade Proof Pipelines, Wave 1 Summary

**Publication workspace models, selective paper/supplement exports, and auditable snapshot/release plumbing without collapsing theorem trust into editorial readiness**

## Performance

- **Duration:** 21m
- **Started:** 2026-04-23T12:10:47Z
- **Completed:** 2026-04-23T12:31:49Z
- **Tasks:** 3
- **Files modified:** 17

## Accomplishments
- Added a dedicated publication workspace with explicit readiness states, publication views, and release history separate from theorem trust state.
- Wired CLI commands for inspecting and setting publication state, plus export commands for paper, supplement, bundle, and manifest outputs.
- Added publication bundle snapshots to snapshot/export flows and made paper-facing output redact internal-only claims and notes by default.
- Added tests covering publication state persistence, CLI surface exposure, export selection, exchange round-tripping, and selective review summaries.

## Task Commits

1. **Task 1: Define publication views and readiness state** - `0344cc4` (`feat`)
2. **Task 2: Implement paper, supplement, and bundle export pipelines** - `b86dcb8` (`feat`, marker commit after verification)
3. **Task 3: Add provenance, citation, and verification summaries** - `c9ff72e` (`feat`, marker commit after verification)

## Files Created/Modified
- [`src/proof_cli/publication.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/publication.py) - publication workspace, views, release history, export builders, and bundle snapshots
- [`src/proof_cli/commands.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/commands.py) - CLI command surface for publication inspect/set/export/release workflows
- [`src/proof_cli/cli.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/cli.py) - Typer publication subcommand wiring
- [`src/proof_cli/export.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/export.py) - publication-aware project export section
- [`src/proof_cli/exchange.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/exchange.py) - publication workspace round-tripping in exchange bundles
- [`src/proof_cli/proof_state.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/proof_state.py) - snapshot metadata for publication views and releases
- [`src/proof_cli/snapshot.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/snapshot.py) - publication bundle snapshot recording during snapshot creation
- [`src/proof_cli/storage.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/storage.py) - publication snapshot/state persistence hooks
- [`src/proof_cli/db.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/db.py) - publication tables in the SQLite schema
- [`src/proof_cli/domain.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/domain.py) - publication snapshot metadata on project snapshots
- [`src/proof_cli/references.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/references.py) - citation provenance normalization helper
- [`src/proof_cli/review.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/review.py) - publication review and verification summary helpers
- [`src/proof_cli/theorems.py`](/Users/zhdeng/Proof%20CLI%20/src/proof_cli/theorems.py) - theorem citation provenance helper
- [`tests/test_publication.py`](/Users/zhdeng/Proof%20CLI%20/tests/test_publication.py) - publication state/view/export persistence tests
- [`tests/test_export.py`](/Users/zhdeng/Proof%20CLI%20/tests/test_export.py) - public export selection assertions
- [`tests/test_exchange.py`](/Users/zhdeng/Proof%20CLI%20/tests/test_exchange.py) - publication workspace round-trip assertions
- [`tests/test_review.py`](/Users/zhdeng/Proof%20CLI%20/tests/test_review.py) - review/verification summary and release audit assertions
- [`tests/test_cli.py`](/Users/zhdeng/Proof%20CLI%20/tests/test_cli.py) - publication CLI help exposure

## Decisions Made
- Kept publication readiness in a separate workspace model rather than extending theorem trust fields.
- Selected publication views by audience and visibility so paper, supplement, and internal exports stay distinct.
- Recorded bundle snapshots at export time so the public-facing release trail is auditable.
- Redacted hidden claims and snapshot payloads from paper-facing export output by default.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Publication workspace enum collision broke readiness setting**
- **Found during:** Task 1
- **Issue:** The publication module reused the same symbol for the readiness enum and the persisted workspace model, causing the setter path to fail.
- **Fix:** Split the enum and workspace model into distinct names and updated the CLI command to use the readiness enum correctly.
- **Files modified:** `src/proof_cli/publication.py`, `src/proof_cli/commands.py`
- **Verification:** `pytest tests/test_publication.py tests/test_cli.py -q`
- **Committed in:** `0344cc4`

**2. [Rule 1 - Bug] Paper export leaked hidden claim details through editorial notes and snapshots**
- **Found during:** Task 2
- **Issue:** Paper-facing bundle output still serialized internal-only claim metadata.
- **Fix:** Redacted hidden claims, review records, editorial notes, and bundle snapshot payloads from paper-facing export payloads.
- **Files modified:** `src/proof_cli/publication.py`
- **Verification:** `pytest tests/test_publication.py tests/test_export.py tests/test_exchange.py -q`
- **Committed in:** `b86dcb8`

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes were necessary for correctness and trust-boundary integrity. No scope creep.

## Issues Encountered
- The publication module already contained a workspace API, but it also had a symbol-name collision that needed correction before the CLI could use it reliably.
- The paper export initially surfaced hidden claim content through nested snapshot payloads, which required redaction logic to keep the public-facing export selective.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 1 is complete and the publication workspace/export surface is ready for the real-project validation work in wave 2.
- Wave 2 should now focus on the mixed-provenance validation slice and confirm round-tripping on a real theorem cluster.

---
*Phase: 07-publication-grade-proof-pipelines*
*Completed: 2026-04-23*
