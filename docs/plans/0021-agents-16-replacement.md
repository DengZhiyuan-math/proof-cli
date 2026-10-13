# Replacement draft for zeqome/proof-agents#16

Checked against the live issue on 2026-10-09 (Europe/Zurich).

The live issue is OPEN. Its title and body match the draft described in the conversation. The two question-write fallback requirements and their acceptance criteria depend on the deleted `AgentRun._question` path. The courtesy `_close_note` failure requirement remains relevant.

Suggested title: **Expose failures of AgentRun-owned work-log writes**

Published as the replacement [issue #16 body](https://github.com/zeqome/proof-agents/issues/16) on 2026-10-09. Implementation: `8340de98507a9ed38ce72276ca4b9c9791dcfa53`, [PR #22](https://github.com/zeqome/proof-agents/pull/22), stacked on PR #21. The published body follows.

---

Blocked by: DengZhiyuan-math/proof-cli#198

Implementation baseline: include [proof-agents PR #21](https://github.com/zeqome/proof-agents/pull/21), head `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`. At the time of this check, `integ/0021` is `36c291f6ff26bebc0720b36dcb5708c98d9b8736` and PR #21 is still OPEN. An implementation based on `integ/0021` alone still contains the obsolete `_question` path.

## What

PR #21 removes `AgentRun._question`. Each role records its own Standing questions through `proof node progress --question`. That command returns its failure to the role. The run no longer converts a needs-human decision into a question or records that question on the role's behalf.

The run still catches and discards failures from three work-log writes:

- `_close_note`: `record_close` for closing notes, including the standalone Decomposer's structure decision and a failure to record the Verifier's verdict as an Evidence check.
- `_suggest`: `record_close` for a suggested redirect.
- `_note_turn`: `record_turn` for the turn record.

Expose these failures through `RunState.record_failed` and `AgentRun.view()`. Keep the existing run status, reason, decision, suggestion and scheduling behavior.

## Field and lifetime

Use a bounded mapping from write site to its latest exception, for example:

```json
{
  "record_failed": {
    "_close_note": "record_close: OSError: disk full",
    "_note_turn": "record_turn: OSError: disk full"
  }
}
```

- The three possible sites are `_close_note`, `_suggest` and `_note_turn`. Empty is `{}`.
- Include the hook name, exception class and exception message.
- Keep errors for the current Start. A later successful write does not clear them. A new Start begins with an empty mapping.
- A failure from one site does not replace a failure from another site. Repeated failures at the same site replace only that site's error.
- Attach the error to the `_Start` that attempted the write. Pass or capture that Start before invoking the hook. A late error from an earlier Start must not alter a later Start's diagnostics.
- Update state under the existing lock. Return a copy of the mapping in `view()`.
- Do not attempt to write the failure through the failing work-log hooks.

For the standalone Decomposer's structure decision, visibility is enough for this issue. If its courtesy note fails, the run still ends needs-human and retains its decision. The failure is exposed through `record_failed`.

## Acceptance

- [ ] Inject `OSError` into a closing `record_close` write. `view()["record_failed"]` identifies `_close_note`, `record_close`, the exception class and message. The run's ending and reason remain the same as with a successful write.
- [ ] Inject failure into the standalone Decomposer's structure-proposed note. The split remains recorded, the run still ends needs-human, its decision remains intact, and `_close_note` appears in `record_failed`.
- [ ] Inject `OSError` into `_suggest`'s `record_close` write. The suggested redirect remains in `state.suggestion`; `_suggest` appears in `record_failed`; the failure does not change the run's control flow.
- [ ] Inject `OSError` into `record_turn`. `_note_turn` appears in `record_failed`; the run continues and retains its normal ending. Check that a later successful turn-record write does not clear the earlier failure.
- [ ] Fail two different write sites in one Start. Both errors remain visible. Pause, Resume and Stop do not reset them; a new Start resets them. Mutating the returned view does not mutate run state.
- [ ] Delay a failing write across a new Start. The failure belongs to the earlier Start and does not contaminate the new Start's view.
- [ ] No exception is silently discarded at the three work-log write sites. Existing tests and the PR #21 acceptance probes continue to pass.

## Scope

No retry loop, no wait-for-write state, no conversion to needs-human on a courtesy-write failure, and no change to acceptance or trust rules.

This field is an in-memory diagnostic for the lifetime of a Start. It does not persist a failed note or restore the decision after a server restart. Visibility closes the silent-error defect; it does not establish durable recovery.

Page display belongs in a separate proof-web issue. Recovery of a failed decision note across restart needs its own persisted-state design; page display alone does not provide it.

---

Part of DengZhiyuan-math/proof-cli#193. Supersedes the original `_question` fallback requirements after proof-agents PR #21.
