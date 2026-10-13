# e4a123a: a full web suite run and one more probe (supplement)

Date: 2026-10-10. A second, independent pass over the same head, adding to [README.md](README.md), which remains the audit record. Same pins: web `e4a123a` (`review_queue.py` sha256 `fb2f949e…bee9`, matching `manifest.json`), core `ad479f6`, agents `9558fd0`. It used a git clone in a Claude Code scratchpad, not the archive in `manifest.json`.

## Full web suite (README: not rerun)

728 passed, 5 failed, 14 errors, 1 skipped in 238s (`full-suite.log`). All 19 failures and errors are `PermissionError: [Errno 1] Operation not permitted` binding a local port in the sandbox (`test_home.py`, `test_review_app.py`), and the log holds no other assertion error. Those 19 tests are unverified, not passed. The two non-port failures in the de96466 run (closing note, Coordinator waiting for stuck) did not occur here; that does not establish that they are gone.

## Probes (`probe_attribution_e4a123a.py`, `probes.log`: 2 failed, 5 passed)

- The three de96466 probes pass. So do two new ones: removing an edge keeps the historical mark, and an unnamed mark on a snapshot resting on two imports goes to neither.
- `R2: unchecked against the source; R checked against the source.` marks R. This is the README's remaining P2, in the other order.
- New, P3: `Unchecked against the source, e.g. R2 could not be opened.`, with L resting on R alone, marks R. The period after `e.g.` ends the sentence, which then names no import, so the single-import fallback applies. It needs an unusual note form.

`targeted-tests.log`: `test_import_review.py` 6 passed. `control-de96466.log`: the same file against de96466 source, 2 failed and 4 passed, as in the README.
