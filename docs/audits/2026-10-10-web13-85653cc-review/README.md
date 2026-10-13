# proof-web 85653cc: review of the local warning-attribution fix

Date: 2026-10-10 (Europe/Zurich). Commit `85653cc5f16a86435407e09b870489ffeff1cffd` (branch `D_m/fix-13-warning-attribution`, parent PR #13 head `e4a123a`, not pushed). The fix's own record is [2026-10-10-web13-warning-attribution-fix](../2026-10-10-web13-warning-attribution-fix/README.md); this is a separate check and changes nothing there. The commit was fetched into a Claude Code scratchpad clone; the other session's checkout was not touched. `review_queue.py` sha256 at 85653cc: `6646fe4da7f1c21eb78af88da69ca3c977ba00c99c6ebf02938443b1156e2b1d`. Pins: core `ad479f6`, agents `9558fd0`.

## Finding: P2 regression, a warning disappears

With L resting on R and R2, each of these notes yields no mark on any import at 85653cc:

```text
Unchecked against the source; R2's paper could not be opened.
R2's statement differs from the cited version; unchecked against the source.
```

The semicolon now ends the clause, so the clause with the unchecked phrase names no import, and the snapshot rests on two, so the single-import fallback does not apply. At e4a123a the whole sentence was read, named R2 and marked R2. Both probes pass at e4a123a and fail at 85653cc. A lost warning is worse than a misplaced one: the researcher's Reference review of R2 shows no sign that its source was unchecked.

Possible fix: when an unchecked clause names no import, fall back to the imports named in its whole sentence before the single-import rule. Add both notes as tests.

## Probe results (`probe_85653cc.py`; the same file against e4a123a is `probe_at_e4a123a.py`)

| Probe | e4a123a | 85653cc |
| --- | --- | --- |
| Three de96466 probes; removed edge keeps mark; unnamed mark with two imports | 5 passed | 5 passed |
| Semicolon clause naming another import | failed | passed |
| `e.g.` splitting the sentence | failed | passed |
| Unchecked clause and the import it concerns on either side of `;` (two probes) | passed | **failed: warning lost** |
| `R: checked, R2: unchecked against the source.` | failed | failed (unchanged, narrow: the comma splits only after a full "checked against the source") |

Logs: `probes-85653cc.log` (3 failed, 7 passed), `probes-all-at-e4a123a.log` (3 failed, 7 passed).

## Full web suite at 85653cc

738 passed, 5 failed, 14 errors, 1 skipped in 246s (`full-suite-85653cc.log`). All 19 failures and errors are `PermissionError: [Errno 1] Operation not permitted` binding a local port in the sandbox. Those 19 tests are unverified, not passed. The log holds no other assertion error. The 10 more passes than at e4a123a (728) are the fix's new tests.

No push, PR comment or merge. No browser or provider check.
