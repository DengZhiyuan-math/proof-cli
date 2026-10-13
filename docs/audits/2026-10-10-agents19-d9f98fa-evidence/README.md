# proof-agents #19: local commit `d9f98fa`

- Commit `d9f98faf76a64bc5609ea134183dc8096041257f` (`d9f98fa.patch`). Branch `fix/19-structure-budget` in the scratchpad clone of zeqome/proof-agents. Its parent is `7e742b5`, the live head of PR #24 (#18), as the user verified. **Not pushed.**
- Test core: proof-cli `integ/0021` `b7f3943`.

## Decisions applied (user, 2026-10-10)

1. **Explicit total, editable before Start.**
   - The default is `node_budget × max(1, open_nodes_at_Start) + structure_allowance` (`pursue_limits`). There is no expected-Claims setting.
   - The structure allowance is `STRUCTURE_TURNS` (2) per Theorem or Lemma open at Start (at least one), plus the Reader's turn when one is due.
   - The time limit is the node budget's minutes in the same proportion.
   - The total is shared: a node's proof budget is a ceiling, and new Claims spend what is left.
   - The total and the deadline are frozen for the whole Pursue (`PursueBudget`, shared by the Reader and every Theorem's Coordinator).
2. **The web display is a separate proof-web issue and PR.** proof-agents computes and enforces the limits; proof-web shows and submits them. See the draft `web-issue-draft.md`. "Shown before Start" stays pending until that is verified.
3. **Three failed launches per node per Start**, the first attempt counted:
   - A successful launch does not reset the count.
   - A failed launch spends no turn, but time still runs.
   - At the limit, the node is not tried again, its claim is given back, and the failure is recorded apart (`launch_failed`).
4. **A due re-split at the budget's end:** the parent is Interrupted, with a reason saying the Pursue's total (or time limit) prevented its re-split. Never-started nodes stay unstarted.

## API (for proof-web)

- `Coordinator.default_limits()` and `ProjectPursuit.default_limits()`: `{"turns", "minutes", "node_turns", "node_minutes", "open_nodes", "structure_allowance"}`. The second also counts the Reader's turn when there is no map. It returns `NO_BUDGET` when it has neither a `budget` hook nor a Theorem.
- `Coordinator.start(provider, *, limits=None, budget=None)` and `ProjectPursuit.start(provider, *, limits=None)`. `limits` is `{"turns": int ≥ 1, "minutes": > 0}`; anything else is refused with `INVALID_LIMITS`. A spent shared total is refused with `BUDGET_SPENT`.
- `PursuitHooks.budget`: new and optional. Without it, the default total is computed from the map the Reader states, counting the Reader's turn.
- `PursuitHooks.read` may return `{"turns": n}`; if it doesn't, the Reader's turn counts as 1.
- New view keys:
  - Coordinator: `turns_max` (the Pursue's total), `turns_before`, `pursue_turns`, `minutes_max`, `deadline`, `failed_launches`, `structure_turns`, `launch_failed`, `resplit_refused`.
  - Pursuit: `budget` (`turns_max`, `minutes_max`, `deadline`, `spent`, `failed_launches`).
  - Node entries: `structure_turns`, `structure_starts`, `failed_launches`, `cap`.
- `AgentRun.start(..., minutes=)` caps the run's time below the node budget's minutes, the way `turns=` caps its turns.

## Results

| Run | Result |
| --- | --- |
| agents full suite at `d9f98fa`, 3 repeats | 177 passed each time |
| new `tests/test_pursue_budget.py` | 17 passed |
| `test_pursue_budget.py` on `7e742b5` (control) | collection error: `PursueBudget` does not exist there, so no behavioural control |
| proof-web `feat/0021-pursue-review-queue` (`864a2c2`) with the new agents | 6 failed, 721 passed, 1 skipped, 14 errors |
| the same with agents `7e742b5` | 5 failed, 722 passed, 1 skipped, 14 errors |

- The one new web failure is `test_coordinator_hub.py::test_the_coordinator_works_the_children_then_the_root_and_the_page_and_the_map_read_it`. It asserts the old default `turns_max == 120` (40 × 3); the new default is 122 (40 × 3 + 2). The web PR updates it.
- The other failures and errors appear with both agents versions. They are the sandbox's local-port PermissionErrors.

Acceptance in `test_pursue_budget.py`:

- [x] A parent that split still has its full proof budget: its proof run's cap is 3 of 3, and the Decomposer turn shows as `structure_turns`.
- [x] A second re-split on the same parent is refused: T gets one Decomposer turn, `resplit_refused == ["T"]`, and one note.
- [x] The total never rises after Start: it stays the same after a split into 3 Claims, retries and the total's end; C never starts.
- [x] Failed launches are counted apart from turns: `turns` stays 0, `failed_launches` is 1, and the end note gives both.

Edges also covered: a first split or a re-split whose launch failed is tried again as a split; three failures give the node up and its claim back; the time limit caps each run and starts no new turn; a project Pursue shares one total and deadline across the Reader and its Theorems, and starts no Theorem once the total is spent; a host with no `budget` hook gets the deferred default; limits that aren't a total are refused.

## Notes for review

- **Changed meaning:** `turns_max` in the Coordinator view now means the Pursue's total. `turns` is this Start's real turns, structure and proof together.
- **Shared total:** a project Pursue that spends its total in one Theorem starts no further Theorem. Each unstarted Theorem's result is `not-started`, and the Pursue ends `budget`.
- **Wall-clock deadline:** the Pursue's deadline is not paused by the Coordinator's Pause, unlike `AgentRun`'s own clock.
- **Failed launch defined:** a run that ends `stuck` or `budget` before any turn counted. One that ends `needs-human`, `done` or `released` with no turn is not a failed launch.
- **No overshoot:** a new run's cap sets aside the running runs' remaining caps, so parallel runs cannot overshoot the total.
