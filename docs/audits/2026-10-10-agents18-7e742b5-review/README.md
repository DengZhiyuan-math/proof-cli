# proof-agents #18: review of `7e742b5`

Date: 2026-10-10. Reviewed commit `7e742b5823ad72ee37f429aa4983e8d632102796` on `origin/fix/18-park-at-budget` (the PR #24 branch). Its parent is `ef7db62`, audited in `../2026-10-09-agents18-ef7db62-evidence/`. This commit is the one meant to cover the remaining requirement of the live issue: the final result of a node that is still running at the budget boundary.

I could not read the PR itself (private repo, `gh` unavailable). The branch head is `7e742b5`. The fix-order entry still names `ef7db62`.

## What it changes

- At the total budget, the Coordinator no longer ends at once:
  - `_park` runs first and parks the ended nodes. It starts nothing, including the Decomposer re-split it proposes.
  - While any run is going, the Coordinator stays active, with the reason "…no new turn starts, and the run(s) on X end on their own".
- Once no run is going, `_interrupt` marks open nodes whose last run ended `stuck`/`budget` with node budget left, or `no-split`, as **Interrupted**. That is a new `CoordinatorState.interrupted` field, shown in `view()` and noted in the record. Then the Coordinator ends with `budget`.
- In `ProjectPursuit`, `release()` after `budget` is unchanged; the comment is corrected.

## Results

| Check | Result |
| --- | --- |
| Full agents suite at `7e742b5`, core `b7f3943` | 159 passed (`full-suite.log`) |
| `test_coordinator.py -k budget`, 3 repeats | 5 passed each time |
| `probe_7e742b5.py` at `7e742b5` | 6 passed (`probes.log`) |
| The same probes at `ef7db62` (control) | 5 failed: probes 3, 4 and 5 on behaviour; 1 and 6 only on the missing `interrupted` key (`control-ef7db62.log`) |

Probes, all on synthetic maps and runs:

1. The audit's spec probe (a split, then one Claim turn, total budget 2): A is Parked with a `parked A:` note, and no re-split starts.
2. Through `ProjectPursuit`: the result is `budget`, the Coordinator is `released`, and A's claim is released.
3. B is running at the boundary: it is not Parked while running, and the Coordinator stays active. When B later ends with `budget`, it is Parked, `nodes.B.last == "budget"`, and release clears its claim. At `ef7db62`, B's late result was never collected.
4. B ends `stuck` with node budget left: it reads Interrupted, not Parked.
5. Stop while waiting: the Coordinator is `released`, and B's claim is released.

Both acceptance items pass: the spec probe parks and logs the Claim with its claim released, and a node running at the boundary is not Parked.

## Findings

- **P3: a re-split that was due is dropped without a result.** In probe 6, after A (a Claim) is Parked at the budget's end, its parent T's one re-split is due. Nothing starts, which is correct, but T ends with `last: "split"`: neither Parked nor Interrupted, and no note says a re-split was due. `_interrupt` covers `stuck`/`budget`/`no-split`, not a parent with a pending `_resplits` entry. The researcher still sees A Parked in the review queue. If "each node's result, Parked or Interrupted" is meant to cover T, `_interrupt` should also mark a parent with a due re-split ("a re-split was due when the budget ran out").
- **Note: nothing caps the wait.** The Coordinator waits for running runs with no cap of its own. It relies on each `AgentRun` ending under its own node-budget remainder and deadline. That is the issue's stated design ("the running turns stop under the existing deadline"). A hung run would keep the Coordinator active until Stop.
- **Note: never-started nodes get no result.** Open nodes that never ran have no `state.nodes` entry, so they get no result. I read the issue as covering nodes that ran.

## Reproduce

```sh
AGENTS=<proof-agents checkout at 7e742b5> PYTHONPATH=<proof-cli src> python3 -m pytest -q -s probe_7e742b5.py
```
