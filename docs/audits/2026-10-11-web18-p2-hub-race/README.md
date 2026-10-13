# web #18 follow-up: the structure-turn P2 and the hub-test timeout

Date: 2026-10-11. This follows `2026-10-11-web18-c0232ef-publication-browser/`. Nothing here is pushed: each repo gets two local commits, saved as patches.

| Repo | Branch | Base | New head | Patches |
| --- | --- | --- | --- | --- |
| proof-agents | `fix/19-structure-budget` (PR #26) | `d9f98fa` | `ead54fe8d3480f1d4ba45a5b7b1bfb97b0f796ee` | `agents/0001`, `agents/0002` |
| proof-web | `fix/18-pursue-limits` (PR #19) | `c0232ef` | `355837c333fd8189c105aa241d4e9fa8ffe50e6f` | `web/0001`, `web/0002` |

To apply: run `git am` on each patch directory, on the branch's current head.

## P2: project structure-turn counts (fixed)

**Cause.** The P2 is as reported. `_pursuit_spend` started structure turns at 0 and read only the working Coordinator's own count. The Reader's turn and the Decomposer turns of finished Theorems were never added. Once the Pursue ended, the count read 0.

**Fix in agents, `9f4bacf`:**
- `PursueBudget` gets `structure_spent`, and `view()` includes it.
- The project Pursue adds to it the Reader's turns (they are structure, part of the allowance) and each finished Coordinator's `structure_turns`.
- `CoordinatorState.structure_before` takes a snapshot of it at Start. The view then reports `pursue_structure_turns`, the same way `turns_before` and `pursue_turns` work. With a snapshot, nothing is counted twice in the window after a Coordinator ends but before the next Theorem becomes `current`.

**Fix in web, `1b6af73`:**
- The spend line reads `budget.structure_spent`. While a Theorem is being worked, it reads that Coordinator's `pursue_structure_turns` instead.
- An older proof-agents falls back to the old reading.

**Tests:**
- agents: a new test runs the Reader (1 turn), T1 (split, Claim, own proof) and T2. It checks 1, then 2, then 2 while T2 is worked, then `spent=5`, `structure_spent=2` after the end. The deferred-total test also checks `structure_spent == 1`.
- web: the Reader-only Pursue reads `structure_turns == 1` after it ends, which is the browser observation. A hub test checks the live value (6/3) and the value after the end (4/2), not 0.
- Without the source changes, both new agents tests fail, and both web tests fail.

## The hub timeout (cause found, older than #19)

`test_coordinator_hub.py::test_the_coordinator_works_the_children_then_the_root_and_the_page_and_the_map_read_it` had three independent races. All three show up only under load. A diagnostic copy of the test, not committed, dumped the Coordinator's state at the timeout. See `hub-stuck-dump.txt`.

1. **The Coordinator ends before the researcher decides.**
   - Once A and B await review, T rests on nodes no run will settle. The Coordinator ends `stuck` ("T rest(s) on what no run will settle"). That is ADR-0021's rule: it never waits for a Review decision.
   - The test accepted A and B 0.5s or more after B requested review. It passed only when the Coordinator hadn't yet taken its next look.
   - Against agents without #19 (`agents-17`, `e2d6f9e`), 1 of 6 concurrent copies failed the same way. So this is not a #19 regression.
   - **Fix (test):** pause the Coordinator while B's turn runs. The trigger is that B's `proof.tex` holds the turn's exact text, written before a 2s sleep in the turn. Then accept both and resume. Pausing on `claimed` was too early: it could hold B's run before its turn began, and B then never requested review (seen once).
2. **The start note came after the loop's first note.** `Coordinator.start` started its thread before writing "started on T …". Under load, "started a run on A" was written first, so the work log read out of order (2 of 12 copies).
   - **Fix (agents `ead54fe`):** write the note, then start the thread.
   - A Stop or Pause that comes in between is honoured when `_loop` begins.
   - A second Start sees `starting` and is refused.
   - There are no `join`s on the thread.
3. **The test read the notes before they were written.** `_end` sets the status to `done` and writes its notes afterwards. The test read the work log as soon as the Coordinator was no longer active (1 of 12 copies).
   - **Fix (test):** also wait until the view no longer reports `settling`, which happens only once the thread has ended.

## Results

Sandbox, Python `/opt/anaconda3/bin/python`. Core: worktree `0021-201` (`09e64a3`, the same source the browser check used). Agents: `agents-combined`, which is `d9f98fa` + fix/17 `e2d6f9e` + the two new commits, merged automatically and not published.

| Check | Result |
| --- | --- |
| agents suite at `ead54fe` | 178 passed |
| agents combined build | 182 passed |
| web limits, page, history and review-queue tests (combined) | 109 passed |
| web limits and history tests against agents `d9f98fa` (fallback) | 45 passed, 4 skipped |
| hub test, 6 copies at once, before the fixes | 3 of 6 failed (`stuck`) |
| hub test with all three fixes, 18 copies at once, two rounds (combined; 6 of the first on agents-17) | 36/36 |
| web full suite at `355837c` (combined) | 5 failed, 760 passed, 1 skipped, 14 errors: all 19 are the sandbox's port tests |

`hub-load-runs.txt` lists every concurrent run:
- `hubload`/`hubold`: before the fixes, using the diagnostic copy.
- `hubr2`/`hubr3`: race 1 fixed, which exposed race 2.
- `hubr6`/`hubr7`: race 2 fixed, which exposed race 3.
- `hubr8`–`hubr10`: race 3 fixed, with the early Pause trigger.
- `hubr11`–`hubr16`: everything fixed.

`hubload.sh` now runs the committed test file.

## Not done

- No browser rerun of the panel after the P2 fix.
- The 19 port tests were not rerun outside the sandbox.
- agents #23/#26 still need the saved merge resolution. Both new agents commits merged into the combined build without conflict, so the resolution still applies.
