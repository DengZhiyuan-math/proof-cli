# proof-web #10 publication and browser acceptance

Date: 2026-10-10 (Europe/Zurich).

## Publication

The supplied scratchpad directory existed but was empty. Its web clone,
`pr10.md`, and `issue10-correction.md` were absent. The preserved format patch
was applied to a new clone of #15. With the patch's author, author date, and
committer date, Git reconstructed the **exact original commit**,
`07bb06e67dbd767a8390593b464fee4dba2d07a4`, parent
`f0ea4a7d1d99716f06356479bceea0771cc2f7c7`.

The user-authorized push created `origin/fix/10-pursuit-history` at that exact
SHA. `git ls-remote` independently confirmed it. No force push was used.

The user approved both replacement bodies with “使用这两份替代稿”.
[PR #16](https://github.com/zeqome/proof-web/pull/16) was created with the exact
requested title, head `fix/10-pursuit-history` and base
`fix/12-pursuit-release-retry`. It was attached to this chat.
[Issue #10](https://github.com/zeqome/proof-web/issues/10) was updated with the
approved recovery correction. Both remote bodies match the approved files
byte-for-byte, including their terminal newline.

The two published files are `pr10-reconstructed.md` and
`issue10-correction-reconstructed.md`. They are reconstructed text, not recovered
copies of the missing originals. The issue's original body is retained in
`issue10-before.json`. Its body was checked for concurrent edits before updating.

The PR and issue remain OPEN. The PR comparison has one commit and the four
expected changed files. Its merge base is #15's exact head `f0ea4a7`. Dependency
PRs #15, core #206 and agents #23 remain OPEN at the requested heads. Once #15
merges, #16's base must change to `feat/0021-pursue-review-queue`, as its approved
body states. The exact-head GitHub `package` check completed with SUCCESS.
No additional tests were run during the publication follow-up.

Publication readback is in `pr16-published.json`, `pr16-compare.json`,
`issue10-after-edit.json`, and `publication-verified.json`.

## Exact sources

| Package | Exact head | Source |
| --- | --- | --- |
| proof-web | `07bb06e67dbd767a8390593b464fee4dba2d07a4` | `/private/tmp/proof-web10-acceptance/web` |
| proof-agents | `e2d6f9ee570f81e99ccaf69a40315ad46bb9cc96` | `/private/tmp/proof-web10-acceptance/agents` |
| proof-cli / latex-agent | `09e64a365153650cade0579afca52a56028b0f07` | `.claude/worktrees/0021-201` |

All three working trees were clean after verification. Existing dirty primary
checkouts were not edited. Dependency PRs #15, #206 and #23 remained OPEN at the
specified heads during the initial live check.

Python: `/opt/anaconda3/bin/python3`, 3.11.14. Browser: Chrome 155.0.8059.39,
attached through agent-browser to an isolated profile at
`/private/tmp/proof-web10-chrome` on CDP port 9223.

## Independent tests

| Check | Result |
| --- | --- |
| `test_pursuit_history.py`, `test_review_queue_page.py`, `test_pursue_review_queue.py` | 56 passed in 4.87s |
| Only the 19 cases previously blocked by port-binding errors | 19 passed in 11.32s; `port-cases-rerun.log` |

The 56 tests include the original audit probe. `rerun_port_cases.py` extracted
the exact 19 node IDs from the preserved full-suite log. This independently
fills that earlier verification gap. It is **not** a fresh full-suite run.
The implementation's historical 744-pass result remains a separate report.

## Browser acceptance

The browser used the production page, JavaScript, HTTP server, StudioHub,
ProjectPursuit, core event recording, and SQLite history. Start and Stop were
clicked through current accessibility snapshots. Reader ran through the normal
AgentManager with a deterministic Backend. Coordinator behavior was supplied
by the submitted `_Coordinator` fixture, with `running: []` added for the map
view. Record failures were injected only in the fixture server.

No real model was called. These checks establish browser and persistence
behavior. They do not establish real-provider or mathematical proof acceptance.

| Scenario | Observed result |
| --- | --- |
| Reader states no Theorem | `stuck — the Reader stated no Theorem`, unchanged after page refresh and a new server process |
| Reader fails | `stuck` with the exact Reader failure reason, unchanged after refresh and process restart |
| First Stop fails; second Stop succeeds | Failure keeps Stop and hides Pursue. Retry records `end released`. `released — stopped by the researcher` survives refresh and restart |
| Release still fails at shutdown | Same live hub retains failure and Stop after refresh. New process reads `interrupted`, retains the failure reason and hides Stop. No `end` event exists |
| Later recording fails | `History not saved: … disk full` follows the status and survives same-hub page refresh |
| Start recording fails | Browser request returns 500; page shows `PURSUIT_RECORD_FAILED`, state stays idle, and no pursuit event exists |

The persisted histories contain only one Start per successful scenario. Refresh
and restart do not add a Start. The retry scenario's phases are:
`start → reader_end → theorem → stop → release_failed → stop → end`.
The unfinished release history has no end. The refused-start history is empty.
`verify_browser_evidence.py` checked the saved browser observations and exported
`browser-results.json` and `project-histories.json`.

Recorded server-process transitions:

| Scenario | Before restart | After restart | Origin |
| --- | --- | --- | --- |
| ending | PID 6625 | PID 6833 | `http://localhost:33878` |
| release-interrupted-v2 | PID 6947 | PID 7026 | `http://localhost:20012` |
| release-retry | PID 7053 | PID 7242 | `http://localhost:24952` |
| reader-error | PID 7324 | PID 7383 | `http://localhost:26842` |

Servers stopped with Ctrl-C and executed `ReviewServer.server_close()`. The
restarted process used the same persisted project and origin. Screenshots,
accessibility snapshots, API observations, and the 500 response observation
are saved beside this file. `browser-errors.txt` is empty.

The first release fixture omitted a field required by the map. That failed
fixture run is documented in `fixture-first-run-error.md` and is excluded from
acceptance. Production sources were unchanged.

All six synthetic-project servers were closed after acceptance. The isolated
agent-browser session was closed. Its Chrome main process (PID 5910, verified
with the exact test profile in its arguments) was then terminated and exited.
Source clones and evidence were retained.
