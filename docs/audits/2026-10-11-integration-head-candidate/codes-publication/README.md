# Pursue budget codes: PR publication verified

Date: 2026-10-11 (Europe/Zurich).

Created and attached [PR #209](https://github.com/DengZhiyuan-math/proof-cli/pull/209) with the user's exact title and body. The saved body is [pr-body.md](pr-body.md), including the supplied attribution. The remote title and body were read back and compared exactly.

Verified publication:

- Head: `fix/0021-pursue-budget-codes`, `24d3a296d9995774c01df755df904c769d6598da`.
- Base: `integ/0021`, `b7f394374ce73e9a23754e12506e87e97326efd9`.
- Two commits: `f711138d2c6de715b3bd689d9243a43251b88b6c`, then `24d3a296d9995774c01df755df904c769d6598da`.
- Two changed files: `src/proof_cli/errors.py` and `tests/test_cli_contract.py`.
- The PR remains OPEN and is not a draft.

Fetched the saved core candidate bundle into a temporary comparison clone. The rebuilt branch and the original `a7a38570fb4f581531c1444cf267f26f38ad17c1` have exactly the same Git tree: `4354a6a2af5b409fed1ff5b9813cbd798de89723`. The original candidate manifest was preserved unchanged; it still describes the original local candidate. T8 must use a new manifest made from the real merged heads.

Independent verification: `tests/test_cli_contract.py` passed all 33 tests on Python 3.11.14, using the codes worktree's core and studio source plus the current sibling checkouts' agents and web source. This is a scoped branch check, separate from the candidate's full-suite evidence. The log is [contract-tests.txt](contract-tests.txt).

At publication readback, all four jobs in [PR #209 CI](https://github.com/DengZhiyuan-math/proof-cli/actions/runs/38144445188) were IN_PROGRESS. No CI result is claimed.

The scanner's known limitation is retained: any dictionary spread is classified as a refusal. A spread-based notice would be misclassified. This is a test-scanner limitation; this publication adds no production behavior beyond the registry entries.

## Merge recommendation

Recommend merging #209 into `integ/0021` once its CI passes. Hold the broader batch until [core PR #208's failed CI](https://github.com/DengZhiyuan-math/proof-cli/actions/runs/38058081895) is resolved.

Both Linux jobs for #208 fail at `test_reassign_without_parent_stays_a_usage_error_without_the_role`: the result has the expected exit code 2, but its output does not match the literal `--reassign goes with --parent`. CI used Typer 0.25.1, Click 8.5.0, and Rich 15.0.0. A local forced-color probe on Typer 0.20.0 passed, so it does not resolve the CI discrepancy. Windows jobs were cancelled and provide no passing result. The failure logs are preserved in [pr208-failed-ci.txt](pr208-failed-ci.txt).

This recommendation does not record any merge approval or perform any merge. Once #208 is resolved, use the candidate's supplied core → agents → web order, including the saved conflict resolutions and required retargets. After the real merges, record fresh heads and run T8 with the 19 port tests, 3 Tectonic tests, browser check, and real-provider check outside the sandbox.

No merge, retarget, additional push, or PR comment was made. The existing worktrees and original candidate evidence were preserved. Remote readback is in [remote-verified.json](remote-verified.json).
