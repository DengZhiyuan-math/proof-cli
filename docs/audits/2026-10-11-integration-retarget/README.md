# ADR-0021 integration PR retargeting

Date: 2026-10-11 (Europe/Zurich).

Ran the user's supplied `retarget-0021.sh` after checking all PR identities and local merge ancestry. All 18 PRs are OPEN and now target their repository's intended integration branch.

| Repository | PRs verified | Final base | Bases changed |
| --- | --- | --- | --- |
| DengZhiyuan-math/proof-cli | #204–#209 | `integ/0021` | #205 |
| zeqome/proof-agents | #21–#26 | `integ/0021` | #22, #23, #24, #26 |
| zeqome/proof-web | #13, #14, #15, #16, #19, #21 | `feat/0021-pursue-review-queue` | #16, #19 |

Readback confirmed that every PR retains its exact head SHA, head branch, title, body, state, and draft status. Each PR head is an ancestor of its corresponding local merge head. All three local merge checkouts were clean.

The printout is correct. The following heads are ready for the user's ordinary integration-branch pushes, in this order:

| Order | Repository | Local merge head | Push target | Remote target before and after retargeting |
| --- | --- | --- | --- | --- |
| 1 | proof-cli | `3dd0a7bde3ad1ea9e040c02b1bff6589a9cf378c` | `integ/0021` | `b7f394374ce73e9a23754e12506e87e97326efd9` |
| 2 | proof-agents | `3ff0a7121e82b3c8eb1153c7bc1e296c96a36c69` | `integ/0021` | `36c291f6ff26bebc0720b36dcb5708c98d9b8736` |
| 3 | proof-web | `b8157191d26834c570a0edbc310599a632b355b8` | `feat/0021-pursue-review-queue` | `864a2c29bd4f41a5344ae7be960b842a1d4aed62` |

The current remote target is an ancestor of the local merge head in each repository. This task changed PR bases only. It did not push, merge, close, or delete any branch or PR. All affected PRs were attached to this chat.

After the pushes, verify each remote integration tip and each PR's actual MERGED state. Then write a fresh manifest from those published heads and run T8 on macOS. The user's macOS target remains authoritative; Windows CI timeouts do not block this batch.

No test suite was rerun for this metadata change. The original candidate evidence, #208's test fix, and the reported 50-test check remain separate from this retargeting verification. Port, Tectonic, browser, and real-provider checks remain T8 work.

Evidence: [before.json](before.json), [preflight.json](preflight.json), [script-output.txt](script-output.txt), [after.json](after.json), and [verified-at.json](verified-at.json). A copy of the executed script is [retarget-0021.sh](retarget-0021.sh).
