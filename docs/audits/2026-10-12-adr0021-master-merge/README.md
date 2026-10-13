# ADR-0021 master integration, 2026-10-12

Q1–Q6 executed. Integration merges used the order core → agents → web. All seven prerequisite PRs were merged before the first master merge.

| Decision | Result |
|---|---|
| Q1 | core #210–#212, agents #27–#28, web #22–#23 merged into integration first. |
| Q2 | Real-provider Pursue remains #197 after master integration. No model trial ran here. |
| Q3 | core [#217](https://github.com/DengZhiyuan-math/proof-cli/pull/217), agents [#29](https://github.com/zeqome/proof-agents/pull/29), web [#24](https://github.com/zeqome/proof-web/pull/24) merged in that order. Exact heads, bases and merge-bases are in manifest.json. |
| Q4 | Final macOS full suites and browser Home → Proof map → Studio → Review passed. Skips are recorded separately. |
| Q5 | web #5 closed as superseded; core #184 and web #6 became merged automatically; web #17 merged independently; core #183 remains open; agents #8 closed. |
| Q6 | CLAUDE_CONFIG_DIR stays in the serving process environment. core #183 was trimmed at d4e977fa9c02a5525e0bd2b29a1f0d12639a11c5; context ring, Show here and no-git-remote remain. Unpublished unknown-key branches were preserved. |

## Final source versions

| Package | Master head | Merge-base with pre-integration master |
|---|---|---|
| core | `d433159214156239e31094d1eaea3b7b991b927f` | `c259da02f2ddb7c255aecf0db3d5ec2af40bb357` |
| agents | `7d3f312269b9868415e06302b97637db1a490220` | `dc802c068a4b81f611b2d791b1c5087405c24844` |
| web | `af687b02b7d03dbf5bd2b60062284d8421dfa5c0` | `045307a54bf03e8fda9558d9ecd127bdd8dc15f6` |
| latex_agent | `d433159214156239e31094d1eaea3b7b991b927f` | `c259da02f2ddb7c255aecf0db3d5ec2af40bb357` |

latex-agent is a path in the core repository. It shares the core commit; manifest.json separately records its source tree and last path commit. The independent core #183 changes are not in this merged master.

## Final macOS full suites

| Suite | Passed | Skipped | Failed | Errors |
|---|---:|---:|---:|---:|
| core | 1158 | 15 | 0 | 0 |
| agents | 200 | 0 | 0 | 0 |
| web | 821 | 1 | 0 | 0 |

The core suite includes latex-agent. Core skips cover two optional wall-clock benchmarks, two Windows-only checks, and eleven checks that need a full TeX distribution. The web skip needs pdflatex. No local-port test was skipped: all 19 known port cases passed in the final web suite (port-cases.json). Skips are not counted as passes.

Before agents merged, its full suite passed against the merged core master (logs/after-core-agents.json). Before web merged, its full suite passed against merged core and agents master (logs/after-agents-web.json). All three full suites then ran on the exact final master heads. Commands, XML, timing and source versions are under logs/.

## Browser evidence

browser-master/checks.json records Home → Proof map → Studio → Review, page URLs and actual loaded source paths. Both CLI executables point to `/usr/bin/false`, the system program that exits without contacting any provider. This preserves the normal provider-list interface with zero model calls. No Start, Send, Compile or Record Selected Decisions action was used. The fixture has a pending Candidate proof and no mathematical Acceptance. Screenshots and accessibility snapshots are under browser-master/.

The first fixture disabled both providers. Studio misread its empty provider list as an older server. This is a preexisting configuration edge case: the affected app.js file is identical before and after this integration. browser-master/empty-provider-observation.json and browser-master-empty-providers/ preserve it. The final four-step smoke passed with the two non-model CLI stand-ins and no legacy-server warning. Production code was not changed for this separate observation.

## Evidence boundaries

- Local full suites: passed with the skips above.
- Browser smoke: passed on the final master sources, with zero model calls.
- Real-provider Pursue: not run; #197 remains open.
- Researcher mathematical Acceptance: not performed; #132 remains open.
- GitHub CI: separate compatibility/packaging evidence. remote-readback.json records the snapshot; pending jobs are not reported as passed. No separate CI edit or branch-protection change was made. The workflow changes in #212 were merged as approved.

The original core #217 body contained the sentence "Does not close #197". GitHub treated its `close #197` phrase as a closing keyword and closed #197 when the PR merged. The body was corrected and #197 reopened. The final readback confirms both #197 and #132 are OPEN; this execution did not perform their remaining provider or mathematical acceptance work.

The shared primary checkout's dirty and untracked files were preserved. Verification used isolated macOS checkouts under /private/tmp/proof-0021-merge-jbf0__fm. This audit directory is local evidence; no audit commit or separate audit PR was published.
