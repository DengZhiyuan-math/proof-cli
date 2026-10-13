# Companion proof-web issue draft

Suggested title: **Show AgentRun work-log write failures in the node's run pane**

Published as [proof-web #11](https://github.com/zeqome/proof-web/issues/11) on 2026-10-09. Its native blocking dependency points to proof-agents #16. The published body follows.

---

Blocked by: zeqome/proof-agents#16

## What

AgentRun exposes `record_failed` when its own closing-note, suggested-redirect or turn-record hook fails. The node's run pane must show those diagnostics while the current Start remains available.

Show a short message that the indicated work-log write failed. Include the write site, hook name and error returned by AgentRun. Keep the run's existing status, reason, decision and controls. A needs-human decision must remain visible beside the diagnostic.

Display the errors as text. Older proof-agents versions without `record_failed`, and empty mappings, show no warning.

## Acceptance

- [ ] A failed closing-note, suggestion or turn-record write shows its site and error in the run pane.
- [ ] Multiple sites' errors are shown together. Polling and later successful writes do not hide the errors retained by AgentRun.
- [ ] A needs-human run with a failed note still shows its decision and existing controls.
- [ ] An empty or missing field renders normally. A new Start reflects its fresh diagnostic state.
- [ ] Error text is escaped through the existing page rendering path.

## Scope

Display only. The page does not retry writes, change run status, or provide persistence and restart recovery. It must not describe these in-memory errors as a saved work-log record.
