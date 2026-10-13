Found when the three repos were run together on the integration candidate (docs/audits/2026-10-11-integration-head-candidate). Neither problem shows in a single repo's suite.

- Registers INVALID_LIMITS, BUDGET_SPENT and NO_BUDGET in ERROR_CODES. proof-agents#19 and proof-web#18 raise them.
- The contract test's scanner now treats a dict that spreads another dict (`{**answer, "code": CODE}`, as in proof-agents#17's RELEASE_FAILED) as a refusal, not a notice. Adds a planted test case for it.

tests/test_cli_contract.py: 33 passed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)