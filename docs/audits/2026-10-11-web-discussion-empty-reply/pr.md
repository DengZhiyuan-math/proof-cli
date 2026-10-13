## What

`discussion_view()` now reads the running turn and the pending records *before* the turn records. A turn frees its slot only once its ended record is written (or kept pending), so a turn that ends between the reads shows as still running instead of settled with an empty reply.

The start's failure paths now write the ended record before they free the slot. A start that raises after its started record was written is now ended on record with the error as its reply, instead of staying started for good.

## Tests

There are three new tests in `tests/test_discussion_web.py`, gated with Events and no sleeps. All three fail at `864a2c2`:

- `test_a_view_read_while_the_turn_ends_never_settles_on_an_empty_reply`: the reported race. The view reads the records, and then the turn ends.
- `test_a_refused_start_is_on_record_before_its_slot_is_free`: views taken while the refusal is written all show the turn running.
- `test_a_start_that_fails_after_its_record_is_on_record_as_failed`: the turn ends with the error as its reply.

Results:
- `test_discussion_web.py`: 14 passed in each of 5 runs.
- Full suite: 724 passed and 1 skipped. Separately, 19 local-port tests can't run in the sandbox, and there is one known `test_coordinator_hub` race, whose test fix is in #19.

Closes #20

🤖 Generated with [Claude Code](https://claude.com/claude-code)
