# proof-web 83dbc43: review of the anonymous-warning fix

Date: 2026-10-10 (Europe/Zurich). Commit `83dbc43f33e0dfdb5c9fb27bca0b39422283aac4` on `D_m/fix-13-warning-attribution` (parent `85653cc`, grandparent PR #13 head `e4a123a`), not pushed. The fix's own record is [2026-10-10-web13-anonymous-warning-fix](../2026-10-10-web13-anonymous-warning-fix/README.md); the 85653cc review is [2026-10-10-web13-85653cc-review](../2026-10-10-web13-85653cc-review/README.md). The commit was fetched into a Claude Code scratchpad clone. `review_queue.py` sha256: `9e5d22634fad0f188bdab6add8bb3ddb14a34bc33be0071d6ad5b171a92c20e9`. Pins: core `ad479f6`, agents `9558fd0`. The tested checkout and the other session's checkout were both at 83dbc43 when the suite ended.

## Result: the 85653cc regression is fixed; nothing blocks the push

`probes-83dbc43.log`: 10 passed, 1 failed.

- The two notes whose warning was lost at 85653cc now mark R2.
- `R: checked, R2: unchecked against the source.` no longer marks R.
- The three de96466 probes, the removed-edge and unnamed-two-imports probes, and the semicolon and `e.g.` probes still pass.

## Follow-up, P3 (not blocking, by the researcher's decision)

`R: checked against the source; unchecked against the source for the other import.`, with L resting on R and R2, marks R. The unchecked clause names no import, so the sentence fallback finds only R, which the note just called checked. The same probe also fails at e4a123a (`probe_83dbc43_at_e4a123a.py -k ambiguous`), so this is not a regression. Possible fix: the sentence fallback leaves out imports named in a checked clause.

## Full web suite at 83dbc43

743 passed, 5 failed, 14 errors, 1 skipped in 239s (`full-suite-83dbc43.log`). All 19 failures and errors are `PermissionError: [Errno 1] Operation not permitted` binding a local port in the sandbox. Those 19 tests are unverified, not passed. The log holds no other assertion error.

No push, PR comment or merge. No browser or provider check.
