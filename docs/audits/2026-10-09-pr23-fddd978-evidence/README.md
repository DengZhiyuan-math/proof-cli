# PR #23 verification at fddd978

Date: 2026-10-09. Head: `fddd978008e385bbbc0a1c331dc26f099ad64579`.
Merge base: `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f` (PR #21).

Publication is complete: PR #23 is stacked on #21; proof-web #12 is filed with a native blocking dependency on agents #17; the existing hourly follow-up now handles both PR #22 and PR #23 after #21 merges.

The exact-head full suite passes (160 tests). Both original #17 audit probes pass. The release-failed result, retained Theorem and successful Stop retry are covered by the new repository tests.

## Remaining P2: release still pending does not block all new work

### A retried Stop exposes released before release returns

1. T1's release fails. ProjectPursuit and its worker have ended release-failed, retaining T1.
2. Retry Stop. `stop()` sets the project state to released before calling the Coordinator's release hook.
3. Hold the real node release with an Event. The project worker is already over.
4. A new Start succeeds. T1's Coordinator refuses Start because it is still releasing; the new ProjectPursuit records that refusal and starts T2.
5. T1 still owns its node. The new pursuit should have been refused until the retry completed.

The probe reports `pending_view.status == "released"`, a Start answer of `reading`, and `T2_starts == 1` while the release gate is closed.

### COORDINATOR_ACTIVE is a pending release, not an empty Coordinator

1. T1's Coordinator spends its budget while its node run still owns its node.
2. Another caller starts Stop just before the project's budget-path release call.
3. The real Coordinator returns COORDINATOR_ACTIVE to the second release call because `_releasing` is true.
4. `_release` only recognizes RELEASE_FAILED. The budget path therefore starts T2 before the other Stop has released T1.

The probe reports `release_answer.code == "COORDINATOR_ACTIVE"` and `T2_starts == 1` while T1's release remains pending.

NO_COORDINATOR means there is nothing to release. COORDINATOR_ACTIVE means release has not finished. These answers must not share the same proceed-to-next-Theorem behavior.

## Required boundary

Keep the project unavailable to Start while any release is pending. Report released only after release completes successfully. Keep current Theorem and ownership identity through pending and failed release. A retry failure retains release-failed. A successful retry ends released. A concurrent pending release must be waited for or left pending; it must not start another Theorem.

Reuse the existing state field and the Coordinator's pending-release behavior. The audit's stopping → released / release-failed transition describes this boundary. No changes to the implementation were made in this audit.

## Reproduce

Both scripts include the exact-head Coordinator and repository test fixtures. They use Events to trigger the overlap and no real provider or browser.

```sh
/opt/anaconda3/bin/python docs/audits/2026-10-09-pr23-fddd978-evidence/probe_pending_retry.py
/opt/anaconda3/bin/python docs/audits/2026-10-09-pr23-fddd978-evidence/probe_concurrent_release.py
```

Both fail at the assertions that T2 must not start. Cleanup releases the fixtures after the assertions. Logs and exact source hashes are retained beside this record.
