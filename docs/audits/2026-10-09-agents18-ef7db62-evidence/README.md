# proof-agents #18: ef7db62 audit

Date: 2026-10-09 (Europe/Zurich).

[PR #24](https://github.com/zeqome/proof-agents/pull/24) was created with the requested title and body. Its base is `fix/15-needs-human-kept`; its exact head is `ef7db6227406e6a39b287856df242db406ccdb07`. The merge base is #21's `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`. One commit changes `coordinator.py` and its tests. It does not include #22 or #23.

## Result

The narrow fix passes. At the total budget boundary, `_park()` now records nodes whose runs have already ended and meet the existing parking rules. It excludes running nodes. It does not start the parent Decomposer turn proposed by `_park()`.

| Check | Result |
| --- | --- |
| Complete proof-agents suite at ef7db62 | 159 passed in 12.66s |
| GitHub CI at ef7db62 | Python 3.11 and 3.12: SUCCESS |
| Original audit probe, function copied without changes | 1 passed in 0.07s |
| Original probe against 9558fd0 | Fails because A is absent from `parked` |
| Three scope checks | 3 passed in 0.69s |
| Normal Project Pursue budget release | A is recorded as Parked; its claim is released |
| Node ending after the Coordinator has stopped | Its final result is not collected; explicit release still clears its claim |

The full suite used Python 3.11.14 at `/opt/anaconda3/bin/python` and immutable core source `b7f394374ce73e9a23754e12506e87e97326efd9`. These are synthetic maps and runs. No real provider or browser acceptance was performed.

## Remaining acceptance boundary

The live [issue #18](https://github.com/zeqome/proof-agents/issues/18) also requires each running node's eventual result to be recorded as Parked or Interrupted. This patch does not implement that requirement. The scope probe confirms the stated limit: B ends after the Coordinator's budget exit, but B has no final result in `view()["nodes"]`, no Parked record, and no Coordinator node-ending note. Releasing the Coordinator gives B back; it does not collect B's final result.

Parking and releasing are separate operations. The normal Project Pursue path satisfies the claim-release check, but release failure handling remains #17's responsibility. The #17 pending-release findings from the prior audit are not included or resolved here.

This is a pass for the submitted narrow change, not complete acceptance of the live issue's broader requirements. To complete those requirements, either collect final results through the existing run-ending or release settlement path, or explicitly revise the issue scope. A new persistent watcher is not established as necessary by this audit.

No issue body, PR comment, review, merge, or branch was changed. The existing retarget automation now includes PR #24 and remains **PAUSED**, as requested by the user.

## Reproduce

```sh
/opt/anaconda3/bin/python -m pytest -q docs/audits/2026-10-09-agents18-ef7db62-evidence/probe_scope.py
```

The folder contains the exact Coordinator source, its official test fixtures, the scope probes, full-suite and probe logs, the expected old-head failure, and verified PR metadata. The third scope check asserts the known limit; its passing result does not mean the broader final-result requirement is satisfied.
