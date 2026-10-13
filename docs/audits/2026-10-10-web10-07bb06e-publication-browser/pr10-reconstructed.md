Refs #10. Depends on DengZhiyuan-math/proof-cli#206 (`09e64a3`) and zeqome/proof-agents#23 (`e2d6f9e`).

This PR is stacked on #15 (`f0ea4a7`), with base `fix/12-pursuit-release-retry`. After #15 merges, change this PR's base to `feat/0021-pursue-review-queue`.

The hub records a project Pursue's start, the Reader's end, each Theorem with its Coordinator's spent turns, Stop, release failure, and end through core's pursuit events. If the start cannot be recorded, it returns 500 `PURSUIT_RECORD_FAILED` before any Reader or provider starts. Later recording failures are kept as `record_error` and shown as `History not saved: …`.

The recovery contract differs from the original #10 body, as the researcher decided. A live hub keeps `release-failed` and Stop retries its release (#15). A release failure records only `release_failed`; a successful retry records `end released`. A new hub reads the last recorded end and its reason. Without an end, it shows `interrupted` and retains the last step's reason, including a release failure. It offers no Stop and performs no release retry after restart. A new Start rechecks claims, snapshots and node states.

Validation reported by the implementer for exact commit `07bb06e67dbd767a8390593b464fee4dba2d07a4`: 8 new pursuit-history tests pass, including `test_project_pursuit_ending_survives_a_new_hub`; all 8 fail against #15's source. Two new page tests pass; the record-error test fails against the old page, and the interrupted display test is a regression guard. The full suite reports 744 passed and 1 skipped; 19 other cases were blocked by sandbox port-binding errors.

Independent verification on the same exact sources: 56 related tests pass, and a separate rerun of those 19 previously port-blocked cases passes. This is not a fresh full-suite run. Chrome acceptance passes with the actual HTTP server and deterministic Reader/Coordinator fixtures: Pursue, refresh, and server-process restart retain the recorded ending and reason; release failure becomes interrupted with its reason after restart and offers no Stop; a successful same-hub Stop retry records released; recording failures are visible. No real model/provider acceptance was performed.

Evidence: `docs/audits/2026-10-10-web10-07bb06e-evidence/` in proof-cli.
Independent browser and rerun evidence: `docs/audits/2026-10-10-web10-07bb06e-publication-browser/` in proof-cli.
