# web #9 P3: publication verified

Date: 2026-10-11 (Europe/Zurich).

Applied the saved format patch with `git am --committer-date-is-author-date` in a new temporary clone at `83dbc43f33e0dfdb5c9fb27bca0b39422283aac4`. This reproduced the exact commit `90c0377ed083fe3dc11a3f825a4716ea75a0e494`. The original commit message, authorship, parent, and tree were preserved.

Pushed that commit with an ordinary fast-forward to `zeqome/proof-web`, branch `fix/9-reference-review-marks`. The remote branch and [PR #13](https://github.com/zeqome/proof-web/pull/13) both read back as `90c0377ed083fe3dc11a3f825a4716ea75a0e494`. The PR remains OPEN with base `feat/0021-pursue-review-queue` at `864a2c29bd4f41a5344ae7be960b842a1d4aed62`. Its title and body match the pre-push values exactly.

The published commit changes only `src/proof_web/review_queue.py` and `tests/test_import_review.py`. Its source SHA-256 matches the implementation evidence: `7a030b68b4083264b55955d5cbb77effb6f6057472bbd2b1d00356816b920739`.

Independent pre-push checks used Python 3.11.14 and fresh Git archives of core `ad479f6d69186105a934d9765a553c48f859ceca` and agents `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`.

| Check | Result |
| --- | --- |
| Import-review tests | 27 passed |
| Saved reviewer probes, with only checkout paths repointed | 11 passed |
| Wheel build | Passed |
| Python compilation | Passed |
| JavaScript syntax | All 9 files passed |
| [Package CI](https://github.com/zeqome/proof-web/actions/runs/38132652608) | COMPLETED / SUCCESS; head SHA verified as `90c0377` |

The full suite was not rerun for this publication. The implementation report's 748 passed, 1 skipped, 19 sandbox port failures/errors, and separate Coordinator timeout remain distinct from these independent checks. No browser or provider check was added.

The temporary publication checkout is clean. The sibling checkout's unrelated edits and all existing local evidence were preserved. No PR comment, merge, base change, or branch deletion was made.

Readback, pre-push metadata, push output, and local check logs are in [publication/](publication/remote-verified.json).
