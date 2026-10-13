# Discussion empty-reply fix: publication verified

Date: 2026-10-11 (Europe/Zurich).

Created [issue #20](https://github.com/zeqome/proof-web/issues/20) with the supplied title and the exact contents of `issue.md`. Replaced only `#<issue>` with `#20` in `pr.md`.

Applied the saved patch with `git am --committer-date-is-author-date` on `fix/discussion-empty-reply`, created from `864a2c29bd4f41a5344ae7be960b842a1d4aed62`. This reproduced the exact commit `bb9ac2960e2e9d6f2607bffd5affa96f0151d1d1`, including its original authorship, message, parent, and tree.

Pushed the new branch with an ordinary push. Created [PR #21](https://github.com/zeqome/proof-web/pull/21) with the supplied title and exact amended `pr.md` body. Attached the PR to this chat.

Read back and verified:

- The remote branch and PR head are `bb9ac2960e2e9d6f2607bffd5affa96f0151d1d1`.
- The base is `feat/0021-pursue-review-queue` at `864a2c29bd4f41a5344ae7be960b842a1d4aed62`, also the commit's only parent.
- The PR contains one commit and changes only `src/proof_web/studios.py` and `tests/test_discussion_web.py`.
- The issue title/body and PR title/body match the saved drafts. The PR body says `Closes #20`.
- Both the issue and PR remain OPEN. The PR is not a draft.
- [Package CI](https://github.com/zeqome/proof-web/actions/runs/38135343890) is COMPLETED / SUCCESS for this exact head.

Independent checks used Python 3.11.14 and the same frozen dependency pins as the implementation: core `ad479f6d69186105a934d9765a553c48f859ceca` and agents `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`.

| Check | Result |
| --- | --- |
| The three new regression tests with source archived from `864a2c2` | 3 assertion failures, as expected; no test errors |
| `test_discussion_web.py` on the fixed source | 14 passed in one independent run |
| Wheel build | Passed |
| Python compilation | Passed |
| JavaScript syntax | All 9 files passed |

The implementation report's five Discussion runs and full suite were not repeated. Its 724 passed, 1 skipped, 19 sandbox port failures/errors, and separate Coordinator timeout remain implementation evidence. The original web #12 probe was not rerun during publication; its obsolete `running is None` requirement remains documented in the implementation record. Browser and real-provider acceptance were not added.

The temporary publication checkout is clean. The sibling checkout's unrelated edits and existing local evidence were preserved. No merge, PR comment, or branch deletion was made.

The next fix-order item remains the full suite on the integration Head, then T8 / core #197. These checks have not been performed by this publication.

Readback and independent test/build logs are in [publication/](publication/remote-verified.json). `studios.py` SHA-256 is `02fedd6e906d24e912f30ec20033006e4fae76985d1ae60a2fca850d9c21a8a6`.
