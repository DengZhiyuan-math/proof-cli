# Published integration heads and T8 on macOS

The three integration branches were pushed in core → agents → web order. GitHub independently reports all 18 PRs as MERGED. `manifest.json` fixes the exact sources used throughout this run.

| Repository | Integration branch | Published head | PRs confirmed MERGED |
|---|---|---|---|
| proof-cli | integ/0021 | 3dd0a7bde3ad1ea9e040c02b1bff6589a9cf378c | #204, #205, #206, #207, #208, #209 |
| proof-agents | integ/0021 | 3ff0a7121e82b3c8eb1153c7bc1e296c96a36c69 | #21–#26 |
| proof-web | feat/0021-pursue-review-queue | b8157191d26834c570a0edbc310599a632b355b8 | #13, #14, #15, #16, #19, #21 |

## Native verification

macOS ARM64, `/opt/anaconda3/bin/python` 3.11.14. `loaded-sources.json` confirms imports from the published checkouts. The runs allowed native port binding and Tectonic network access. Windows was not a gate.

| Suite | Passed | Skipped | Failed/errors |
|---|---:|---:|---:|
| Core and LaTeX studio | 1153 | 15 | 0 |
| Agents | 199 | 0 | 0 |
| Web | 816 | 1 | 0 |
| Saved integration probes | 9 | 0 | 0 |

All 19 previously restricted port tests and all three previously blocked Tectonic tests passed in the full suites. See `verification-summary.json`, JUnit XML, logs, and command records.

The probes' first collection attempt selected obsolete source paths. The final run explicitly fixes source/test paths and pytest configuration. Assertions are unchanged from the saved adapted probes; `probes-source-path.diff` records the source setup change.

## T8 controlled browser

Chrome 155 and a dedicated agent-browser session exercised actual HTTP pages and the published state machine with a controlled backend. No model calls occurred in this stage. `controlled-results.json` records each scenario and its evidence.

Pursue, Stop, retry, refresh, server interruption/recovery, Reader with no Theorem, release failure/retry, a small-budget Parked claim, a total-budget Interrupted node, Provisional/Conditional marks, unchecked-source warnings, and Standing question answers were observed. The answer remains stored after refresh and server restart. Mathematical Acceptance was not performed.

Definition editing correctly marks the Claim and its dependent stale, with Definition D and the edit reason in the stored work log. The browser explanation is incomplete: Warnings says an accepted dependency version moved, and the studio shows only `definition-edited`, without the Definition ID or reason. This stage is therefore not a full acceptance pass.

Harness mistakes and corrections are retained in `controlled-results.json`. They do not alter the published sources.

## T8 real trial

The primary trial ended automatically after **40 turns in 87.6 minutes**, within its fixed 60-turn, 120-minute budget. The actual model was `claude-opus-5-5` through Claude Code 2.1.296. It received no researcher input after Start. All 40 provider processes returned exit 0. The work log retains eight passed Verifier verdicts and one failed verdict that led to a correction cycle.

The fresh project had only the original `library-horo/main.tex` as mathematical input. Its SHA-256 remains `147afc8d0a3f69cddd4c35c768ade58c8e3719a0d8be35a01d6c4d7ee4c47333`. The input and exact hand-map script hashes, model choice, limits, and Start timestamp are in `real-trial-preflight.json`.

| Result | Recorded outcome |
|---|---|
| Reader map | 18 nodes, 15 Definitions, 9 Fog items; about 9.2 minutes |
| Final map | 24 nodes: 1 Theorem, 7 Lemmas, 6 Claims, 10 imports |
| Provisional proof nodes | 7; Conditional support remains visible |
| Parked nodes | main-theorem, height-vs-distance, cuspidal-exceptional-finite |
| Open questions / Fog | 9 / 12 |
| Researcher Acceptance / Reference review | None; all nodes and imports remain unreviewed |
| Automatic stop | No work remains without researcher choices; the three Sobolev lemmas rest on parked work |

The project loop reports `done`; the Theorem result is `stuck`. The model reported objections to the main bound, the height/metric statement, and global exceptional-spectrum finiteness. These objections are preserved for researcher review. They are not independent mathematical conclusions.

See [the full real-trial result](real-trial-results.md), [the Reader/hand-map comparison](reader-comparison.md), and `real-trial-summary.json` for node states, stop reasons, departures, resource counts, and question records. The decomposition Lemma has an older Verifier pass but is not Provisional after its structure changed.

The complete 68-entry queue and Reader departures survived refresh and a separate server restart unchanged. Stored nodes, Definitions, questions, Fog, work logs, and proof marks also remained identical. Parked entries come first, bottom-up; the remaining node entries follow dependency depth. The parked theorem's studio retained enabled `Start agent` and single-role `Start` controls. No extra provider calls occurred during the restart check.

The completed global view had `can_pursue=false` before and after restart. Live run overlays and coordinator counters reset to idle on restart. The primary snapshots and work log retain the completed trial. `real-restart-check.json` records these differences rather than claiming identical live views.

## T8 acceptance gaps

T8 was executed on macOS, but its acceptance result is **partial**. Core #197 remains open.

1. The first isolated launch ignored the project's `claude_config_dir`, used the unauthenticated default profile, and ended with the misleading reason `the Reader's turn failed: success`. It used zero model tokens and counted one Reader turn. That attempt is retained separately. The successful primary trial used a fresh project and set the existing configured profile in the server environment.
2. The controlled Definition edit marks dependent nodes stale and records the Definition ID and reason correctly. Browser Warnings gives an accepted-dependency explanation, and Work log omits the Definition ID and edit reason.

These findings do not change the published sources. No mathematical Acceptance was performed.

## Evidence scope

Push logs, pre-push metadata, read-back PR states, exact source heads, native results, browser screenshots, and local trial state remain in this directory. The original candidate manifest is preserved. No issue-close commands or comments were sent. No additional code changes were pushed.
