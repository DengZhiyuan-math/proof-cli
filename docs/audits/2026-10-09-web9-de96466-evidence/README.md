# proof-web #9: de96466 audit

Date: 2026-10-09 (Europe/Zurich).

[PR #13](https://github.com/zeqome/proof-web/pull/13) was created and attached with the requested title and body. Head: `de964662146afccca83ac88c6f5ae263c78d6360`. Base: `feat/0021-pursue-review-queue`; merge base: `864a2c29bd4f41a5344ae7be960b842a1d4aed62`. It contains one commit.

The audit uses immutable core #199 source `ad479f6d69186105a934d9765a553c48f859ceca`, including `would_meet_trust_rules`, and proof-agents #21 source `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`. Core PR #204 was OPEN at the check. This dependency is not assumed to be merged into integration.

## Findings

### P2: associate an unchecked mark with its import, not every import mentioned in its note

`source_marks()` accepts a whole Evidence-check note if it contains the unchecked phrase and either names this import anywhere or the current dependent has exactly one import.

Both independent cases fail:

1. L depends only on R. Its Evidence check explicitly says `R2: unchecked against the source`. The single-import fallback wrongly adds that mark to R.
2. L depends on R and R2. Its note says `R: checked against the source.` followed by `R2: unchecked against the source; source unavailable.` R is wrongly marked unchecked because its name appears elsewhere in the same note.

This contradicts the stated rule that a mark naming a different import is never assigned to this one. Read the import identity from the clause containing the unchecked mark. Do not use the single-import fallback when that mark explicitly names another import. This can use the existing note format and standard library; no new persistence model is required by these cases.

### P2: use the snapshot's dependency set to interpret its mark

`imports` is built from the dependent's current dependencies. It is then reused for every historical Candidate proof. Candidate proofs already store their frozen `dependencies`.

The independent case fails: L v1 depends only on R and has an unnamed unchecked mark. Add R2 to L, then request v2 with no unchecked mark. The v1 warning disappears from R because the current L now has two imports. It should remain visible as L v1, superseded.

Use the existing Candidate proof `dependencies` for each check's attribution. Historical snapshot selection must also follow the dependencies the snapshot recorded; current map edges cannot establish or erase a historical warning. Older records with no stored dependencies need an explicit fallback.

## Verification

| Check | Result |
| --- | --- |
| New `test_import_review.py` tests | 3 passed in 2.23s |
| Original warning-surfacing audit probe, unchanged function | 1 passed in 1.14s |
| Three new tests against old web 864a2c2 | 3 failed in 3.14s; baseline source and page resources pinned |
| Independent attribution probes | 3 failed in 1.25s; the two findings above |
| Complete web suite with core ad479f6 and agents 9558fd0 | 742 passed, 2 failed, 1 skipped in 593.10s |
| GitHub `package` check | SUCCESS; this is packaging evidence |

This run had no port-binding PermissionError failures. Its result differs from the user's sandbox run of 725 passed, 19 port-binding failures and 1 skipped; the dependency heads and environment are recorded explicitly.

The two full-suite failures remain unresolved:

- `test_the_run_leaves_a_closing_note_on_every_stop`: no step entry existed after the wait, causing IndexError. Its isolated rerun passed in 4.80s.
- `test_a_naturally_stuck_coordinator_can_release_its_claims_through_the_page`: waiting for `stuck` timed out at 60s. The isolated new-web rerun also failed; the old-web control passed in 55.17s. This does not establish that the failure is inherited from the baseline.

Both test files and `studios.py` are byte-identical to the base. That fact alone does not establish the cause. The audit does not report a green full suite or classify these two failures as port restrictions. Their tracebacks and control results are retained.

Tests use Python 3.11.14 at `/opt/anaconda3/bin/python`. The page check is a JavaScript harness, not a live browser session. No real provider acceptance was performed.

The stated limit of reading only snapshot-bound Evidence checks matches the live #9 scope. Work-log-only verdicts have no snapshot identity. That limit is separate from the attribution defects.

No PR review, comment, merge, issue edit, push, or automation change was made. The retarget automation remains paused.

## Reproduce the findings

The probe reads the immutable archive paths from `manifest.json` and checks the loaded review-queue source hash. Run:

```sh
/opt/anaconda3/bin/python docs/audits/2026-10-09-web9-de96466-evidence/probe_attribution.py
```

`src/proof_web/review_queue.py` is the exact submitted source. `probe_attribution.py` contains the three independent failing cases. `probe_original.py` contains the original audit function. The logs distinguish passing feature checks from the remaining defects.
