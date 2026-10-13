# web #9 P3: an unnamed unchecked clause took the import its sentence called checked

Date: 2026-10-11 (Europe/Zurich).

Publication update: `90c0377` was pushed on 2026-10-11. The remote branch and PR head were verified, and package CI passed. See [PUBLICATION.md](PUBLICATION.md) for independent checks and readback evidence. The implementation record below describes the pre-push work.

The fix is commit `90c0377` (full SHA in `HEAD`) on `fix/9-reference-review-marks`. Its parent is `83dbc43`, the prior pushed head of [PR #13](https://github.com/zeqome/proof-web/pull/13). It was **not pushed at the time of the implementation checks below**; the patch is `0001-…patch`. Its `review_queue.py` sha256 is `7a030b68b4083264b55955d5cbb77effb6f6057472bbd2b1d00356816b920739`.

Pins, exported with `git archive` into the scratchpad:
- core `ad479f6` (#199)
- agents `9558fd0`

These are the same pins the 83dbc43 review used.

## The P3

Found in [the 83dbc43 review](../2026-10-10-web13-83dbc43-review/README.md).

The note is `R: checked against the source; unchecked against the source for the other import.` and L rests on R and R2. The note marked R. The unchecked clause names no import, so the sentence fallback found R, the import the note had just called checked. The same probe also fails at e4a123a, so this is not a regression.

## Reproduction at 83dbc43

New tests were added before the source change and run at `83dbc43`. The log is `tests-before-fix-83dbc43.txt`, and the result was 4 failed, each marking R:

- `R: checked against the source; unchecked against the source for the other import.` (the reported note)
- `R checked against the source; the other import unchecked against the source.`
- `Unchecked against the source for the other import; R: checked against the source.`
- With three imports: `R: checked against the source; unchecked against the source for the others.`

## Fix

In `review_queue._marks`:

1. A clause's own import names decide first. This is unchanged.
2. The sentence's names and the single-import fallback now leave out every import that another clause of the same sentence calls checked.
3. A clause calls an import checked when it contains `checked` as a word. "unchecked" doesn't match, and neither do the negated forms "not checked", "never checked" and "wasn't checked".

Results:
- With R left out, R2 is the snapshot's one remaining import, so R2 is marked.
- With several imports left, none is chosen. That is the existing rule for any unnamed mark on a snapshot of several imports.
- The "checked" exclusion applies only within a sentence. A checked import in an earlier sentence is not left out. This keeps the reading sentence by sentence; the earlier test `test_the_sentence_fallback_does_not_take_an_import_from_another_sentence` is unchanged.

## Results at 90c0377

| Check | Result |
| --- | --- |
| `test_import_review.py` | 27 passed (21 before, plus 4 P3 cases and 2 "not checked" guards). With the source change reverted: 4 failed, 23 passed |
| The 83dbc43 review's 11 probes, paths repointed (`probe_p3.py`) | 11 passed, including `test_ambiguous_sentence_fallback_reaches_the_import_named_checked`, which failed at 83dbc43 and e4a123a |
| web full suite | 748 passed, 1 skipped; 19 sandbox port failures and errors (unverified). One other failure, see below |

The one other failure was `test_coordinator_hub.py::test_the_coordinator_works_the_children_then_the_root…`. It timed out waiting for T after the children were Accepted. That is the known Coordinator race from [web18-p2-hub-race](../2026-10-11-web18-p2-hub-race/README.md). Its test fix is in web PR #19 (`355837c`), not on this branch. This commit touches only `review_queue.py` and `test_import_review.py`. On rerun, the file passed in 2 of 3 runs.

No push, PR comment or merge. No browser check.
