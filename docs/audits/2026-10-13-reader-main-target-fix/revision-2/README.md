# Revised #197 contract fix evidence

This directory supersedes validation in the parent directory. Those earlier files remain historical evidence. The first #197 run was judged **failed** by the researcher; its results do not enter Human Review or macOS maturity.

The revision removes the Reader target-file self-check. Pursue checks the actual project's dependency closure and requires each Theorem's Coordinator to finish `done`. Reader keeps the only Theorem for the main result and stops on a duplicate target. Core records an agent's own review request as unconfirmed by the author; web displays that label without changing old snapshot records.

Reader, Prover, Decomposer and map discussion now share autonomous retrieval instructions. Missing draft citations do not disable retrieval. Search is based on mathematical objects, hypotheses and conclusions, with primary-source applicability checks and recorded queries, mismatches and failures. No paper, author, URL, identifier or mathematical result is inserted in the production brief. The generic contract and offline limits are in [agents revision-2 evidence](https://github.com/zeqome/proof-agents/blob/D_m/reader-main-target/docs/audits/2026-10-13-reader-main-target-fix/revision-2/autonomous-literature-retrieval.md).

`offline-verification.json` identifies the release base, pre-commit source bytes, imported package paths, commands, passed/failed/skipped counts, and unchanged baseline lint debt. `pytest.xml` is the full suite; other pytest XML files rerun affected cases. Counts overlap. Deduplicated: **1161 passed, 15 skipped**. Tests use fresh temporary projects and fake provider boundaries. The no-bibliography tests and real manager/CLI launch check cannot establish whether a real model will choose adequate queries, discover a source or match the theorem correctly.

Related Draft PRs: [core #220](https://github.com/DengZhiyuan-math/proof-cli/pull/220), [agents #30](https://github.com/zeqome/proof-agents/pull/30), [web #25](https://github.com/zeqome/proof-web/pull/25). The coupled local verification uses all three candidate checkouts. Web project Pursue requires agents #30's map-read hook; an older agents package is refused before any provider starts. Web #26's queue-header count is outside this change.

The preservation manifest and digest verifier are in [core revision-2 evidence](https://github.com/DengZhiyuan-math/proof-cli/tree/D_m/reader-main-target/docs/audits/2026-10-13-reader-main-target-fix/revision-2). They cover 134 captured files: 130 run-related files and 4 later diagnostic files, all unchanged from the first publication snapshot. This is not a complete run-start environment inventory.

No new real Proof provider call, trial service update, pin change, merge, issue closure, or Acceptance was performed. #197 and #132 stay open. A fresh trial is required to evaluate real autonomous retrieval.

From the repository root, verify the public preservation manifest:

```sh
python3 -I docs/audits/2026-10-13-reader-main-target-fix/revision-2/verify_preservation.py docs/audits/2026-10-13-reader-main-target-fix/revision-2/trial-preservation.json
```

Add `--trial-root /path/to/trial-197` to check local bytes. Aggregate rows sorted by relative path as UTF-8 `path + U+0000 + hex digest + LF`, then SHA-256 the concatenation. Before and after: `12f3749b60e8fa08086b191003cca45aefbc14ce24188e93641df2dce9a9ee5e`.
