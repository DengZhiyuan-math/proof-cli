# Show and submit a Pursue's total and time limit before Start

Blocked by: zeqome/proof-agents#19 (the agents PR that computes and enforces it)

## What

proof-agents#19 fixes one total of turns and one time limit for each Pursue at its Start. It is shared by the Reader and every Theorem's Coordinator, and never raised afterwards. proof-web shows the default before Start, lets the researcher change it, and submits it. Budget calculation and enforcement stay in proof-agents.

- **Before Start**, the Pursue panel (project Pursue and a Theorem's Pursue) shows `default_limits()`:
  - total turns and minutes;
  - how they were computed (node budget × open nodes, plus the structure allowance);
  - that a node's budget is a ceiling, and that Claims a split adds spend what is left of the total.
- **The two fields are editable.** Start sends `{"turns", "minutes"}` to `ProjectPursuit.start(provider, limits=…)` or `Coordinator.start(provider, limits=…)`, and shows `INVALID_LIMITS` / `BUDGET_SPENT` refusals.
- **The hub passes** `PursuitHooks(budget=…)`, the node budget it already reads.
- **While running and after**, the page shows the Pursue's turns spent against the total, structure turns and failed launches separately, and the time left. It also lists the `launch_failed` nodes with their reasons, and the Interrupted parents whose re-split the total prevented.
- **Test update:** `test_coordinator_hub.py` asserts `turns_max == 120`; with #19 it is the new default (122).

## Acceptance

- [ ] Before Start, the page shows the default total and time limit and how they were computed.
- [ ] A changed total is what the Pursue enforces; an invalid one is refused with its code.
- [ ] The budget panel shows real turns and failed launches separately.
