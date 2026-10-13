# ADR-0021 integration Head: local candidate and full suites

Date: 2026-10-11 (Europe/Zurich). This is step 12 of [the fix order](../../plans/0021-audit-fix-order.md). By the researcher's choice, every open ADR-0021 fix PR was merged **locally** onto the integration branches. Nothing was merged, pushed or retargeted upstream.

`manifest.json` records heads, bases, merge-bases, the merged refs with SHAs, and the first-parent log. The candidate branches are in `bundles/`, as `<base>..candidate/0021-head`; to reproduce, run `git fetch <bundle> candidate/0021-head` in a clone that has the base.

## What was merged

| Repo | Base | Merged, in order | Candidate head |
| --- | --- | --- | --- |
| proof-cli | `integ/0021` `b7f3943` | #204 `ad479f6`, #206 `09e64a3`, #207 `2f7c246`, #208 `d17b484`, #205 `1337080`, new `fix/0021-pursue-budget-codes` `a7a3857` | `e50f8cd` |
| proof-agents | `integ/0021` `36c291f` | `fix/19` `ead54fe` (#26; contains #15 `9558fd0` and #18 `7e742b5`), `fix/17` `e2d6f9e` (#23), `fix/16` `8340de9` (#22), `fix/20` `7543134` (#25) | `f06f5b8` |
| proof-web | `feat/0021-pursue-review-queue` `864a2c2` | `fix/18` `355837c` (#19; contains #12 `f0ea4a7` and #10 `07bb06e`), `fix/9` `90c0377` (#13), `fix/11` `d5df6e9` (#14), `fix/discussion-empty-reply` `bb9ac29` (#21) | `3b88b4b` |

### Conflicts

- **core, merging #205 (`fix/200`) after #201.** Both add error codes at the end of `ERROR_CODES`; both were kept (`core-merge-200-resolution.diff`). Merging `fix/0021-pursue-budget-codes` hit the same spot and was resolved the same way.
- **agents, merging `fix/17` after `fix/19`.** `coordinator.py` was resolved with the saved resolution, carried through #19's two later commits, together with the two #17 test changes (explicit 1-turn limits; T2 reads `not-started`). The files came from the combined test build; the candidate then differed from it in no file (`agents-merge-17-files.txt`).
- **web:** no conflicts.

## Finding, fixed on a new core branch (not pushed)

Running the three repos together exposed two gaps in core's error-code contract test. Neither shows up in any single repo's suite.

1. **Unregistered codes.** proof-agents #19 refuses with `INVALID_LIMITS`, `BUDGET_SPENT` and `NO_BUDGET`, and proof-web #18 answers `INVALID_LIMITS`. None of them was in `ERROR_CODES`.
   - Fix: `b8bc20f` registers them.
2. **A refusal read as a notice.** With the codes registered, the scan then flagged `RELEASE_FAILED` (agents #17, `ProjectPursuit`) as a notice. The code writes `{**answer, "code": "RELEASE_FAILED"}`, where the spread `answer` carries the `error`, but the scanner saw no literal `error` key.
   - Fix: `a7a3857` makes the scanner read a dict that spreads another dict as a refusal, and adds a planted case.

The branch is `fix/0021-pursue-budget-codes`, from `integ/0021` (`b7f3943`, head `a7a3857`). The patches are in `core-branch/`.
- Contract tests on the branch alone: 32 passed, 1 skipped (the sibling-package scan skips without proof-agents and proof-web).
- Contract tests on the candidate: 33 passed.

## Suites

Sandbox, `/opt/anaconda3/bin/python`. Only the candidate sources are on `PYTHONPATH` (`import-paths.txt`).

| Suite | Result |
| --- | --- |
| core, before the codes branch (`core-suite-before-codes.txt`) | 1149 passed, 15 skipped, 4 failed: the error-code contract test above, and 3 tectonic tests (no network in the sandbox, as at #198) |
| core, final candidate `e50f8cd` (`core-suite-final.txt`) | 1150 passed, 15 skipped; 3 failed, all tectonic (sandbox network). The contract test passes |
| agents `f06f5b8` | 199 passed |
| web `3b88b4b` | 797 passed, 1 skipped; 5 failed and 14 errors, all sandbox port binding (PermissionError). `test_coordinator_hub` passed |

## The audit's probes (`probes/`)

These are the probes from `docs/audits/2026-10-08-adr0021-evidence/`. At #198, 8 of the 9 failed as expected, one for each issue the fix PRs address.

- **Unadapted:** 7 of 9 pass (5 of 6 audit probes, 2 of 3 spec probes). The other 2 fail only on test scaffolding that #19's interface changed. A fake Coordinator's `start(self, provider)` doesn't accept `budget=`. The probe also calls the private `ProjectPursuit._loop` directly, skipping the `start()` that fixes the budget. The spec probe for the budget boundary waits for the Coordinator to finish; under #19 the total isn't spent at that point, so T's re-split runs on (ADR-0021 point 9).
- **Adapted (`*.diff`):** widen the fake's signature, go through `start()` with explicit limits, and wait for A's Parked mark instead of the Coordinator's end. With that, **all 9 pass**: trust ×2 (#199), release ×2 (#17), new hub (#10), Definitions read (#198), needs-human (#15), unchecked-source warning (#9), Parked at budget (#18). In the budget probe, A is Parked in both the view and the park hook, as the probe asserts.

## Not covered

- The 19 web port tests and the 3 tectonic tests were not run outside the sandbox.
- No browser or real-provider check. Those belong to T8 (core #197), which should cite the real merged heads, not this candidate.
- The researcher decides the merges. After merging, record the real heads in a new manifest.
