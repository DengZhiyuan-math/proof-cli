Closes #201.

## What

A project Pursue now leaves a history in the project's own SQLite events (audit section 1). This adds no new log and uses no node.

- `proof_cli.pursuit.record_pursuit(store, phase, ...)` is the one service function that writes. It appends a `pursuit` event with `entity_id=None`. Phases: `start`, `reader_end`, `theorem`, `stop`, `release_failed`, `end`. Payload: `pursuit_id`, `phase`, `outcome`, `reason`, `provider`, `theorem`, `budget`.
- A `start` makes the pursuit's id. Any other phase must name a started pursuit that has not ended (`PURSUIT_NOT_FOUND`, `PURSUIT_ENDED`). An `end` must name its outcome (`PURSUIT_OUTCOME_REQUIRED`).
- A write that fails raises `PURSUIT_RECORD_FAILED`. On a failed `start` nothing is recorded, and the host must not start a provider.
- `project_progress(store, live=None)` and `proof project progress [--json]` read the pursuits back, oldest first, with their events. A pursuit with no end reads `interrupted`. The host can name its own live pursuit to have it read `running`. Nothing is resumed and no provider budget is spent.
- The five new codes are registered in `ERROR_CODES`. `CONTEXT.md`'s Pursue entry names the history.

## Acceptance

- [x] Each event kind round-trips through the service and `proof project progress --json` (`test_each_phase_round_trips_through_the_service_and_the_cli`)
- [x] A pursuit with no end event reads `interrupted` (`test_a_pursuit_with_no_end_reads_interrupted_and_the_live_one_running`)
- [x] A failing write at start refuses the start with an error code (`test_a_failing_write_at_start_is_refused_with_a_code_and_records_nothing`)
- [x] No fake node holds a Reader failure (`test_a_reader_failure_is_a_pursuit_event_not_a_node`)

## Tests

Core suite on this branch: 1037 passed, 2 skipped, 2 failed. The two failures are `tests/test_latex_snapshots.py` real `tectonic` builds, which panic fetching network resources inside the local sandbox. They don't touch this change.

Wiring the page (replacing the no-op `record` hook, restart reads) is proof-web #10.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
