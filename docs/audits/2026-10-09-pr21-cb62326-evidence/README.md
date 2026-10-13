# PR #21 verification at cb62326

Date: 2026-10-09. Head: `cb623269bbef89331f467b457f043090b2cf8d6c`.
Core dependency: `b7f394374ce73e9a23754e12506e87e97326efd9`.

The exact-head agents suite passes: 157 tests. The replacement acceptance probe advances the Coordinator through five ticks with a free slot. It verifies both first and further splits, with normal and needs-human endings. All four cases pass. Existing Claims continue; new Claims wait while their Decomposer runs.

## Remaining P1: map and run snapshots can describe different instants

`_step` reads `subtree` before `_running`. The following interleaving is reproducible:

1. The map read captures T's old Claims.
2. The Decomposer commits C1 and C2, then ends needs-human.
3. `_running` observes that ending. `_park` parks T using the old map, which does not contain C1 or C2.
4. The next tick sees C1 and C2. `_park` skips T because it is already parked. `_split_by_running` does not block the children because T is no longer running.
5. Both new Claims start. `held` is empty.

```sh
python3 docs/audits/2026-10-09-pr21-cb62326-evidence/probe_acceptance.py
python3 docs/audits/2026-10-09-pr21-cb62326-evidence/probe_snapshot_race.py
```

The first command passes. The second fails. The probe inserts a map commit and a run ending immediately after the map snapshot is captured, before the next run-state read. It uses no sleeps or threads.

A small candidate reads completed runs before reading the map. A Decomposer whose ending was observed has already completed its CLI writes, so the subsequent map read sees its new Claims. If its ending was not yet observed, it stays in `running` for this tick and the existing new-Claim guard applies.

The local candidate, retained as `coordinator-read-order-candidate.py` and `candidate-read-order.patch`, passes both probes and all 37 Coordinator tests. It does not modify the working source or PR.

All these checks use synthetic runs and maps. They do not perform provider or browser acceptance. Earlier evidence remains unchanged.
