# proof-web #18: local commit `c0232ef`

- Commit `c0232effb7f130368a4053d5491fabdfc7cd6c73` (`c0232ef.patch`). Branch `fix/18-pursue-limits` in the scratchpad clone of zeqome/proof-web. Its parent is `07bb06e` (PR #16, web #10), which sits on `f0ea4a7` (PR #15). **Not pushed.**
- It is stacked on #16 because both Pursue panels (`pursuit_action`/`showPursuit` and the subtree card) were changed by #12 and #10.

## Test build

| Part | Build |
| --- | --- |
| proof-cli | worktree `0021-201` at `09e64a3` (PR #206, the pursuit events web #10 needs) |
| proof-agents | local merge of `fix/19-structure-budget` `d9f98fa` (PR #26) with `fix/17-pursuit-release-failed` `e2d6f9e` (PR #23). Merge `36d295f`, then test commit `bffebde` (`agents-test-build.txt`). |

The two agents stacks conflict in `ProjectPursuit.start` and in its loop's release handling.

- **Resolution** (`agents-merge-resolution.diff`): keep both. #17's release-failed refusal and its `_release`/`_release_failed` handling, plus #19's limits and unstarted Theorems.
- **Two #17 tests no longer hold under the shared total** (`agents-merge-test-adaptation.diff`):
  - `…whose_release_fails_holds_the_next_theorem…` assumed each Coordinator's own budget. It now passes an explicit total of 1 turn.
  - `…already_being_released_by_another_stop…` expected T2 to start after T1's release. Under one total, a Coordinator that ends `budget` has spent the Pursue's total, so T2 reads `not-started`. The test still checks that nothing moves on until T1's release ends.
- With both changes, the agents build passes: 181, twice.
- **Whoever merges #23 and #26 needs the same resolution and test changes.**

## Change

- **`studios.py`:**
  - `PursuitHooks(budget=…)` gets the node budget, when proof-agents has the field.
  - `_limits(body)` checks `{"turns", "minutes"}` with `PursueBudget.from_limits` before anything is recorded or started. A bad value gets 400 `INVALID_LIMITS`.
  - Both Starts pass `limits=` only when the researcher gave them.
  - `pursuit_view` adds `limits` (the default) while `can_pursue`, and `spend`: turns of the parts that ended plus the live Theorem's `pursue_turns`, structure turns, failed launches, minutes left.
  - `coordinator_view` adds `limits` while idle.
  - `_pursued_coordinator` records a Theorem step only when the pursuit is on that Theorem, so a `default_limits()` read records nothing.
- **Page** (`index.html`, `app.js`, `studio/run.js`, CSS):
  - Before Start, editable total-turns and minutes fields, with how the default was computed and that a node's budget is a ceiling, not a share. A typed value is kept across refreshes. Start sends it.
  - While running and after, `Turns n/total (k structure) · failed launches m · x of y min left`.
  - The subtree card also lists Interrupted nodes and launch-failed nodes with their reasons.
- **With proof-agents from before #19:** no limits are shown and none are sent (`PursueBudget` import guard).

## Results (clean tree at `c0232ef`)

| Run | Result |
| --- | --- |
| full suite, combined build, run 1 | 5 failed, 759 passed, 1 skipped, 14 errors |
| full suite, combined build, run 2 | 5 failed, 759 passed, 1 skipped, 14 errors |
| full suite, agents `e2d6f9e` (no #19) | 5 failed, 750 passed, 2 skipped (`test_pursue_limits.py`: "needs proof-agents#19"), 14 errors |
| baseline `07bb06e` with the combined build | 12 failed (`web18-baseline.txt`). The 7 that are not port failures come from old-budget expectations and fakes; this commit fixes them. |

All 5 failures and 14 errors in each run are in `test_home.py`/`test_review_app.py`: the sandbox's local-port PermissionErrors, unverified.

New tests:
- `tests/test_pursue_limits.py`, 9 tests:
  - the default before Start, for the project and the subtree;
  - the researcher's total fixed and enforced;
  - spend shown;
  - invalid limits refused before any record or Reader turn;
  - no limits sent: proof-agents' default.
- `test_review_queue_page.py`, 3 tests: the banner's default and why, a typed total kept across a refresh and posted, spend apart.
- `test_run_pane.py`, 3 tests: the subtree's default and why, the posted limits, spend and the Interrupted / launch-failed lines.

Changed tests:
- `test_coordinator_hub.py`: the total is 122 with #19, 120 without, and the start/run/budget notes are checked per version.
- Fakes in `test_pursuit_history.py` and `test_pursue_review_queue.py`: `open_nodes()`, and `start(provider, **limits)`.

## Not verified

- **Shown before Start** (the issue's first acceptance item) is checked only in the page harnesses. There was no browser check: the sandbox can't bind a port.
- **One intermittent hub-test failure.** `test_coordinator_hub::test_the_coordinator_works_the_children…` failed twice in about 13 runs before this commit, both times inside larger runs, never alone. One failure was a 60-second wait for T's review request; the other's message wasn't captured. It passed in both full runs above and in 9 runs alone or in its group. Its cause is not established.
