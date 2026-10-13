# proof-web: the Discussion empty-reply race

Date: 2026-10-11 (Europe/Zurich).

Publication update: `bb9ac29` was pushed on 2026-10-11. [Issue #20](https://github.com/zeqome/proof-web/issues/20) and [PR #21](https://github.com/zeqome/proof-web/pull/21) were created with the supplied text; the issue placeholder in `pr.md` is now `#20`. Remote heads, base, and exact text were verified, and package CI passed. See [PUBLICATION.md](PUBLICATION.md). The implementation record below describes the pre-publication work.

The fix is commit `bb9ac29` (full SHA in `HEAD`) on the new branch `fix/discussion-empty-reply`. Its base is `feat/0021-pursue-review-queue` at `864a2c2`. At the time of the implementation checks below, it was **not pushed**, and the issue and PR were drafts; the patch is `0001-…patch`. The issue draft is `issue.md` and the PR draft is `pr.md`, with base `feat/0021-pursue-review-queue`.

Pins: core `ad479f6` and agents `9558fd0`, the same exports as the web #9 P3 check.

## The race

This is from the [web #12 audit](../2026-10-09-web12-f0ea4a7-evidence/README.md), the P2 that was already in the code.
- `discussion_view()` read the turn records, then `_discussion_live`. A turn that ended in between came back with `running: null` and its started record's empty reply.
- The drawer's `_settled` stops on `running: null`, so it kept the empty reply.

Two more places left the same window:
1. **A refused start.** When `agent.start` returned an error, the code set `_discussion_live = None` *before* writing the ended record.
2. **A start that raised after the started record was written.** No ended record was ever written. The turn stayed `started` for good: never running, never ended, with an empty reply.

## Fix (`studios.py`)

- **`discussion_view`:** take the snapshot of `_discussion_live` and `_discussion_pending` under the lock first, then read the records.
  - `_discussion_finish` writes the ended record, or keeps it in pending, before it frees the slot. So whenever the snapshot shows the slot free, that turn's ended record is already readable.
  - A pending entry is removed only after it has been written, so it is either in the snapshot or already in the records.
  - A turn that ends between the two reads shows as running, and the next poll gets its reply.
- **Refused start:** write the ended record, then free the slot.
- **Start that raised:** if the started record was written, write an ended record with the error (`is_error`) before freeing the slot. The 500 answer is unchanged.

## Reproduction and results

| Check | Result |
| --- | --- |
| The 3 new tests at `864a2c2` (`tests-before-fix-864a2c2.txt`) | 3 failed: `running` None with reply `''`; the views during the refusal showed `running` None; the failed start's turn was not ended |
| `test_discussion_web.py` at `bb9ac29` | 14 passed in each of 5 runs |
| Web #12's original probe at `bb9ac29` (`original-probe-bb9ac29.log`) | Fails on its first assertion, `running is None`. The view now reports `running={job, turn, provider}`: the turn still running, not settled with an empty reply. The probe required the settled form; the new regression test accepts either "running" or "settled with the full reply" |
| Web full suite at `bb9ac29` (`full-suite-bb9ac29.txt`) | 724 passed, 1 skipped. 19 failures and errors are sandbox port tests (unverified). One more failure is the known `test_coordinator_hub` race (timed out waiting for T after the Acceptances); its test fix is in web PR #19, not on this base |

No push, issue, PR or browser check.
