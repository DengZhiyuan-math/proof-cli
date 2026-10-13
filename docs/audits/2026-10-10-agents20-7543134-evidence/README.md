# agents #20 — local commit `7543134`

- Commit `7543134d…` (see `7543134.patch`). Branch `fix/20-reader-role-bibliography` in a scratchpad clone of zeqome/proof-agents, based on `origin/integ/0021` (`36c291f`). **Not pushed.**
- Depends on core PR #204 (`ad479f6`, #199) and core PR #208 (`d17b484`, #203). Both are OPEN.
- Test core: a detached merge of `origin/integ/0021` (`b7f3943`) with both PR heads, merge `6510278`. It merged cleanly; it exists only locally.

## Change (`src/proof_agents/reader.py`)

- `ReaderContext.env()` sets `PROOF_AGENT_ROLE=reader` (`READER_ROLE`, equal to `proof_cli.domain.READER_ROLE`). Before, it removed the variable.
- `READER_WRITES` allows `Bash(proof node create *)`. `READER_KINDS` and `READER_DENIED` are removed: the raw `claim "` patterns, the `--parent` and `--reassign` patterns, and the `--identifier` and `--source-type` bans.
- `NO_OTHER_PROJECT` (`--root`) and the inline-code denials still apply.
- Brief, point 4: `reference import` now asks for `--identifier` and `--source-type`, and says they give the Reader's import no trust, which only the researcher's Reference review gives. The "Leave out" line is gone.

## Tests

| Run | Result |
| --- | --- |
| `tests/test_reader.py` + new `tests/test_reader_cli.py`, combined core | 21 passed |
| the same, core `integ/0021` only | 10 passed, 1 skipped (`test_reader_cli.py` skips itself without #203/#199) |
| new `test_reader_cli.py` on the old agents `36c291f` (the `READER_ROLE` constant inlined), combined core | 11 failed (control) |
| the whole agents suite, combined core | 165 passed |
| proof-web `feat/0021-pursue-review-queue`: `test_review_queue_page.py` and `test_pursue_review_queue.py`, with the new agents and the combined core | 34 passed |

`test_reader_cli.py` runs each command through the Reader's Claude Code permissions (`_permitted`) and then through the `proof` CLI in `ReaderContext.env()`:

- Statements quoting `claim "` or `claim '` are written.
- Seven spellings of a Claim, `--parent`, `--parent=` and `--reassign` are refused with `READER_ROLE_REFUSED` (with the option named), and nothing is written.
- An import with `--identifier 10.2307/…` and `--source-type research_paper` under a matching DOI + research_paper rule reads `unreviewed`; `would_meet_trust_rules` names the rule.

CI note: agents CI installs proof-cli `master`, which has neither #203 nor #199. There, `test_reader_cli.py` skips, and the acceptance checks run only locally against the combined core.
