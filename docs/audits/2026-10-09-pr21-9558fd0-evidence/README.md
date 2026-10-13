# PR #21 local audit passes at 9558fd0

Date: 2026-10-09. Head: `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`.
Base: `integ/0021`. Core test dependency: `b7f394374ce73e9a23754e12506e87e97326efd9`.

The #15 findings reproduced in this chat are resolved at this head:

- An explicit needs-human decision remains a stop, including a turn that also splits.
- The split remains in the map. Its new Claims are held when that turn ends needs-human.
- While the creating Decomposer runs, its new Claims wait. Existing Claims and siblings continue.
- A normal split ending lets the new Claims start on the next tick.
- Reading runs before the map prevents an old map snapshot from losing the hold when the turn ends between reads.

## Evidence

- Exact-head agents tests: 158 passed in 9.36s. See `pytest.log`.
- Standalone acceptance probe: all four cases pass, covering first and further splits with normal and needs-human endings.
- Standalone snapshot-race probe: only S starts; T is parked; C1 and C2 are held.
- GitHub CI: Python 3.11 and 3.12 both SUCCESS on this exact head.

```sh
python3 docs/audits/2026-10-09-pr21-9558fd0-evidence/probe_acceptance.py
python3 docs/audits/2026-10-09-pr21-9558fd0-evidence/probe_snapshot_race.py
```

This is local implementation verification with synthetic runs and maps. It does not perform T8 with a real provider or browser. PR #21 remains OPEN and has not been merged into the integration branch. Earlier failed-head evidence is retained unchanged.

## Next triage item

proof-agents#16 remains OPEN. Its original failure path, AgentRun._question, was deleted by the first commit of PR #21. Reassess the issue scope before implementing its old fallback requirements. The separate requirement about surfacing courtesy _close_note failures still needs a decision and verification.
