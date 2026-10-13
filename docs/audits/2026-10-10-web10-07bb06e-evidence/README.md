# proof-web #10: 07bb06e, a project Pursue's history

Date: 2026-10-10 (Europe/Zurich). Commit `07bb06e67dbd767a8390593b464fee4dba2d07a4` on branch `fix/10-pursuit-history`, in a Claude Code scratchpad clone of proof-web (not pushed). Parent: PR #15 head `f0ea4a7` (`fix/12-pursuit-release-retry`). The full patch is `07bb06e.patch`.

Stacked on unmerged work:

| Package | Source | State |
| --- | --- | --- |
| proof-web | PR #15 `f0ea4a7` (web #12, live retry controls) | OPEN |
| proof-cli | PR #206 `09e64a3` (core #201, pursuit events) | OPEN |
| proof-agents | PR #23 `e2d6f9e` (agents #17, release-failed) | OPEN |

latex-agent is taken from the same proof-cli checkout. Python 3.11 at `/opt/anaconda3/bin/python3`.

## The researcher's decision on recovery (2026-10-10)

The live #10 body asks a new hub to restore `release_failed` with a retry Stop. That conflicts with the audit's recovery contract, core #201 and #12's scope. The researcher decided that #10 does no release retry after a restart:

| Case | Shown, and the controls |
| --- | --- |
| This hub's live pursuit: release failed | `release-failed`, Stop retries (#12) |
| After a restart, the old pursuit has no `end` | `interrupted`, keeping the last release failure in its reason; a new Start rechecks claims |
| An end was recorded | That end and its reason |

A release that fails writes only `release_failed`. The end is written once a retry succeeds. The #10 body needs correcting to match; it was not edited.

## What changed (`src/proof_web/studios.py`, `static/app.js`)

- Start: `record_pursuit(start)` comes first. A failure answers 500 `PURSUIT_RECORD_FAILED`, and the Reader and the provider never start. A pursuit refused after its start was recorded gets `end refused`.
- The Reader's end is recorded when the hub's `read` hook returns (`ok` or `failed` with its error), and a Theorem when the pursuit first asks for its Coordinator. The budget is that Coordinator's `turns`/`turns_max` if the hub holds it; none is made to ask.
- The pursuit's `record` hook no longer takes a note string: it reads the pursuit's view. `release-failed` becomes `release_failed`; `done` or `stuck` becomes `end`. proof-agents' `_note` swallows exceptions, so recording errors are caught in the hub instead.
- Stop, from the page or from the hub closing: `stop` is recorded first, then `end released` once the release returns `released`.
- No step is recorded after the end, so a Reader turn that returns after its Stop's end adds no false error.
- A recording failure is kept as `record_error` in the pursuit view. The page shows it after the status: "History not saved: …".
- A hub with no live pursuit (`idle`) reads `project_progress`'s last pursuit: its end, or `interrupted` with its last phase and that step's reason. Stop there answers as for an ended pursuit (`NO_PURSUIT` → 200, the view), and no release is asked.

## Verification

| Check | Result |
| --- | --- |
| `tests/test_pursuit_history.py` (8, including the audit probe `test_project_pursuit_ending_survives_a_new_hub`) | 8 passed |
| The same file against f0ea4a7 source | 8 failed (`control10.log`) |
| Two new page tests in `test_review_queue_page.py` | passed. Against f0ea4a7 `app.js`: the `record_error` one fails; the `interrupted` one passes there too, as the old generic branch already says "status — reason", so it is a guard (`control-page-f0ea4a7.log`) |
| `test_review_queue_page.py`, `test_pursuit_history.py`, `test_pursue_review_queue.py` | 56 passed |
| Full web suite at 07bb06e, clean tree | 744 passed, 5 failed, 14 errors, 1 skipped (`full-suite-10-07bb06e.log`) |

All 19 failures and errors in the full suite are `PermissionError: [Errno 1] Operation not permitted` binding a local port in the sandbox (`test_home.py`, `test_review_app.py`). They are unverified, not passed. The log holds no other assertion error.

Not done: the browser check that #10 asks for (Pursue, refresh, restart the server). There was no live browser or provider here.
