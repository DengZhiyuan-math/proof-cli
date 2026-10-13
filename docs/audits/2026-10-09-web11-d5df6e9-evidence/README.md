# proof-web #11: d5df6e9 audit

Date: 2026-10-09 (Europe/Zurich).

[PR #14](https://github.com/zeqome/proof-web/pull/14) was created and attached with the user's exact title and body, including the Claude Code footer. Head: `d5df6e98088bf13d073977d072293b5eea9e4cdf`. Base: `feat/0021-pursue-review-queue`; merge base: `864a2c29bd4f41a5344ae7be960b842a1d4aed62`. It contains one commit.

The audit uses immutable core integration source `b7f394374ce73e9a23754e12506e87e97326efd9` and proof-agents #16 source `8340de98507a9ed38ce72276ca4b9c9791dcfa53`. Agents [PR #22](https://github.com/zeqome/proof-agents/pull/22) remains OPEN, based on `fix/15-needs-human-kept`, at this check. This web change does not include web #9 or require core #199.

## Feature result

No new defect was found in the inspected display change. Production changes are confined to `run.js` and warning styles in `node.css`.

- Each write site's latest error is shown through the existing `textContent` rendering helper.
- The warning states that the write is absent from the work log. Its tooltip identifies the diagnostics as belonging to this Start and not being persisted.
- The decision, status, reason and controls are preserved.
- The existing poll signature includes the whole run view, so a change only to `record_failed` triggers rendering.
- Missing, null and empty fields do not add a warning. A new Start's fresh state clears the display.
- The existing run endpoint passes `view()` through. No new server API or persistence layer was added.

| Check | Result |
| --- | --- |
| Complete run-pane tests and real AgentRun/StudioHub failure test, agents 8340de9 | 44 passed in 17.26s |
| Same targets with older agents 9558fd0 | 43 passed, 1 skipped in 18.52s |
| New UI cases against old production source 864a2c2 | 3 failed, 3 passed, 37 deselected in 3.84s |
| Complete web suite, core b7f3943 and agents 8340de9 | 747 passed, 1 failed, 1 skipped in 491.62s |
| Isolated rerun of the full-suite failing Coordinator test | 1 passed in 8.00s |
| GitHub package check | SUCCESS; packaging evidence only |

The old-web control copies only the new test file and harness into the old archive. Its production sources and CSS remain unchanged. The three failures are the intended shown-error cases; the three empty-field parameter cases pass.

The real failure-path test uses AgentRun and StudioHub with a scripted role job and CLI subprocesses. A standalone Decomposer splits T without recording its own needs-human step. Failing `_record_close` leaves its decision and split available, exposes `_close_note` in `record_failed`, and creates no saved needs-human note. This is not a real agent-provider trial or a live browser check.

## Full suite

The independent full suite ended with **747 passed, 1 failed, 1 skipped**. This environment had no port-binding PermissionError failures. The user's separately reported result was 728 passed, 1 skipped and 20 failed or errored, including 19 port-binding restrictions and one Coordinator timeout. The independent result is recorded separately rather than substituted for that report.

The one failure is the same test the user reported: `test_coordinator_hub.py::test_the_coordinator_works_the_children_then_the_root_and_the_page_and_the_map_read_it`. It timed out after 60s waiting for T to be requested for review. An isolated rerun against the same exact source heads passed in 8.00s. A read-only pytest report hook captured Coordinator `status=done`, `reason=T is requested for review`, plus the three run views; the capture did not change the test or the control flow.

The cause remains unresolved. This audit does not claim that the full suite is green or that the failure is an established baseline defect. The timeout matches the user's report, and the isolated pass supports investigating its timing or interaction with the full run; it does not prove the cause. The feature checks, old-agent compatibility and old-web control passed as recorded above. The full log, JUnit report and isolated state are retained.

## Scope and publication

The page can merge before agents #16 because the missing field is supported. The diagnostics become available only with agents #16; a fully integrated acceptance check still needs that upstream change. No merge is authorized or performed by this audit.

No PR comment, review, issue edit, push, branch deletion or automation change was made. The retarget automation remains paused.

The archive paths and exact heads are stored in `manifest.json`. Tests used Python 3.11.14 at `/opt/anaconda3/bin/python`. The folder preserves both production files, both changed Python test files, the JavaScript harness, comparison data and verification logs.
