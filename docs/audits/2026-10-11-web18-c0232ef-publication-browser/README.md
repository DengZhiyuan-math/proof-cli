# proof-web #18 publication and browser check

Record date: 2026-10-11, Europe/Zurich.

## Publication

The saved patch restored the exact commit `c0232effb7f130368a4053d5491fabdfc7cd6c73`, parent `07bb06e67dbd767a8390593b464fee4dba2d07a4` (PR #16).

The branch `fix/18-pursue-limits` was pushed without force. [PR #19](https://github.com/zeqome/proof-web/pull/19) was created with the supplied title and `pr18.md` verbatim, base `fix/10-pursuit-history`. It is OPEN and attached to this chat. The remote branch SHA, PR head, base, title and full body were read back and verified. Its `package` CI check is SUCCESS. No PR was merged.

## Exact test sources

| Package | Source |
| --- | --- |
| proof-web | `c0232effb7f130368a4053d5491fabdfc7cd6c73`, clean checkout |
| proof-cli / latex-agent | `09e64a365153650cade0579afca52a56028b0f07`, exported with `git archive` |
| proof-agents | `d9f98faf76a64bc5609ea134183dc8096041257f` plus `e2d6f9ee570f81e99ccaf69a40315ad46bb9cc96` in a temporary merge |

The agents resolution and test adaptations match the supplied evidence: coordinator blob `9c8ba7d6cf56bda06f5f1679fe474af80d801a57`, test blob `515345e9dfaeb33599295ed73205313646d6e38c`. This temporary merge was not committed or published. Merging agents PRs #23 and #26 still requires this resolution and the two test adaptations.

Checkouts and synthetic projects are retained under `/private/tmp/proof-web18-acceptance-0noofz6p`. The primary checkouts and unrelated untracked work were not changed.

## Independent tests

Python: `/opt/anaconda3/bin/python`. These runs are separate from the implementer's full-suite reports.

| Check | Result | Evidence |
| --- | --- | --- |
| Combined agents suite | 181 passed in 16.53s | `agents-combined.log` |
| Limits, page, history, review queue and hub tests | 111 passed, 1 failed in 108.51s | `web-targeted.log` |
| The 19 previously port-blocked cases | 19 passed in 11.25s | `web-port-cases.log` |
| Isolated rerun of the failing hub test | 1 failed in 63.19s | `web-hub-isolated.log` |

The failing test is `test_coordinator_hub.py::test_the_coordinator_works_the_children_then_the_root_and_the_page_and_the_map_read_it`. Both attempts timed out after 60 seconds waiting for T to request review after its children were Accepted. It now reproduces in isolation as well as in a group. The cause and regression status are unresolved. No fresh full-suite pass is claimed.

The first port-test selection truncated two parameterized identifiers at spaces and collected no tests. That runner error is retained in `web-port-cases-selection-error.log`. The corrected full identifiers are in `port-cases.txt`; all 19 then passed outside the sandbox binding restriction.

## Browser check

Chrome 155.0.8059.39 used an isolated profile through the `agent-browser` CLI, attached to CDP port 9223. The unchanged production HTML, CSS, JavaScript, HTTP server, StudioHub, ProjectPursuit, Coordinator, AgentRun, AgentManager and SQLite were used. Only the Backend was deterministic. It ran no model calls and made no mathematical Review decisions.

The project panel was observed at `http://localhost:20669/`, title `Proof map`. The subtree panel was observed at `http://localhost:23413/studio/T/`, title `proof studio`. The launch-failure scenario used `http://localhost:21194/studio/T/`.

| Scenario | Result |
| --- | --- |
| Project before Start | Shows 5 turns, 10 minutes, formula and shared-ceiling explanation |
| Edit project limits, then refresh page data | Keeps 9 turns and 3.5 minutes |
| Invalid project total | HTTP 400 `INVALID_LIMITS`; state idle; no backend turn or pursuit event |
| Valid project Start | Actual request submits 9 turns and 3.5 minutes; shared budget fixes those values; Reader consumes one total turn |
| Subtree before Start | Shows 4 turns, 8 minutes, formula and shared-ceiling explanation |
| Edit subtree limits, then refresh page data | Keeps 3 turns and 5 minutes |
| Invalid subtree time limit | HTTP 400 `INVALID_LIMITS`; Coordinator stays idle |
| Valid subtree Start | Actual request submits 3 turns and 5 minutes; reaches budget at 3/3 with one Decomposer structure turn and two proof turns |
| Pending re-split | T is Interrupted with the total-budget reason; A is Parked; both are shown in the card |
| Failed launches | Three preflight failures, zero backend turns, zero total turns; A is listed with its reason and its claim is released |
| Project structure accounting after completion | **Failed:** completed Reader consumes one total turn but reports zero structure turns |

The refresh checks exercised the page's own data refresh and polls. They do not establish persistence of unsubmitted input through a full document reload.

Start was clicked through observed browser controls. Fetch instrumentation recorded the real request and cloned response; it did not replace responses. Invalid and valid request observations are retained in the `*-invalid.json`, `*-running.json` and `*-after.json` files. Screenshots were inspected visually. Browser JavaScript errors were empty.

## Finding

**P2: project structure-turn spending is not cumulative.** In `proof_web/studios.py:804-818` at `c0232ef`, `_pursuit_spend` initializes structure spending to zero and reads only the current Coordinator while the Pursue is active. It omits the Reader and completed Coordinators. After completion, it returns zero. The Reader-only browser observation is `spend.turns=1`, `spend.structure_turns=0`. The panel therefore omits completed structure spending. Total-turn enforcement remains correct.

The Reader-only result was observed in the browser. The loss of completed Coordinator counts follows from source inspection. No completed multi-Theorem browser scenario was run. The exact source excerpt is in `project-structure-count-source.txt`. This publication did not modify the submitted commit to repair the finding.

## Cleanup and evidence

All three synthetic test servers were stopped through their KeyboardInterrupt cleanup paths. Their ports and CDP port 9223 no longer answer. The isolated agent-browser session was closed, and only the Chrome process with the exact test-profile argument was terminated. Synthetic claims were verified released. Source checkouts and evidence were retained.

`publication-verified.json` contains remote metadata, CI, source hashes, results and closed-port checks. `browser-results.json` contains the browser checks and display finding. `project-history.json` contains the real persisted synthetic-project history. The original PR description was kept verbatim; its browser-pending sentence is the original publication text, not the current verification result.
