# proof-web release retry controls

Published as [proof-web #12](https://github.com/zeqome/proof-web/issues/12) on 2026-10-09. Native blocking dependency: agents #17.

Blocked by: zeqome/proof-agents#17

## What

With proof-agents PR #23, a project Pursue whose release fails stays `release-failed`. Stop retries the release; Start is refused until it succeeds.

On proof-web's ADR-0021 branch, `showPursuit` in `src/proof_web/static/app.js` treats only `reading` and `pursuing` as states that offer Stop. A `release-failed` view hides Stop and offers Start instead. The researcher cannot perform the supported retry from the page.

Show Stop and hide Start for `release-failed`. Keep the existing Stop action and show the current Theorem and release-failure reason. Preserve the existing controls for other statuses.

Source checked at proof-web `864a2c29bd4f41a5344ae7be960b842a1d4aed62`, `showPursuit` lines 330–341. Backend fix: https://github.com/zeqome/proof-agents/pull/23.

## Acceptance

- [ ] A `release-failed` view shows Stop and hides Start, including when `can_pursue` is true.
- [ ] Clicking Stop sends the existing project Pursue Stop request. If release still fails, Stop remains available and Start stays hidden.
- [ ] A successful retry shows `released` and returns to the existing completed-pursuit controls.
- [ ] Reading and pursuing retain their existing Stop controls. Idle and other ended statuses retain their existing behavior.
- [ ] A browser check confirms failure, visible retry controls, repeated failure, and successful retry. State the provider/fixture used for that check.

## Scope

Live project Pursue retry controls only. No backend retry loop, no change to trust decisions, and no history or restart recovery.

proof-web#10 already mentions release-failure retry as part of persisted history. This ticket supplies the controls for the current live run; history and reconstruction remain in #10. It does not depend on core#201.

Part of DengZhiyuan-math/proof-cli#193.
