# PR #21 verification, 2026-10-09

Head: `15ce077519f881c28d73ec8390dcb831697716e5`.
Core dependency: `b7f394374ce73e9a23754e12506e87e97326efd9`.

The 155 proof-agents tests pass. The original ended-turn probe now starts only the existing sibling S. These are local tests with synthetic runs, not provider or browser acceptance.

## Remaining P1: a split becomes visible before its Decomposer turn ends

1. T's further Decomposer run starts with existing split Claims A and B.
2. It creates A2 while its run is still active. A free parallel slot lets the Coordinator start A2.
3. T then ends `needs-human`. The Coordinator parks T and marks A2 held.
4. A2 has already started and is still running. Holding it does not stop that run.

The new regression ends T immediately after it changes the map. It does not cover an intervening Coordinator tick. The probe below uses the exact-head Coordinator and the repository's World and FakeRun fixtures. It fails with A2 starts equal to 1.

```sh
python3 docs/audits/2026-10-09-pr21-15ce077-evidence/probe_split_mid_turn.py
```

Keep the decision to let earlier Claims and siblings continue. A Split makes the parent depend on Claims. The parent is not automatically a premise of each Claim. For this issue, delay only the new split Claims while their creating Decomposer run is active. A normal split ending makes them eligible. A `needs-human` ending keeps them held. Reuse `running`, the entry's `role`, and `split_before`.

The original finding is fixed for an already-ended turn. PR #21 still needs this timing regression before #15 is fully resolved.
