# The web app is a full human interaction surface, not a read-only viewer

**Status**: accepted

The local web app (issue #5) could have stayed a pretty graph viewer, leaving every mutation — Accept, revise, Split, Promote, open or resolve a Challenge — to the CLI. That would break the product's own loop: a researcher who can *see* the structure but has to switch to a terminal to *act* on it isn't getting what a visual proof map is for.

Decided: the web app is writable. A researcher can Accept, request revision, Split, Promote, open or resolve a Challenge, and release a claim directly from it — the same operations the CLI exposes, not a subset.

This does not weaken ADR-0004 or ADR-0006, because of what actually changes underneath it. ADR-0006 (point 11) said adapters call "the same application/service operations the CLI does" — worded as if the CLI were the reference implementation everything else defers to. It wasn't quite right: the CLI, the web app, and the Codex/Claude Code adapter are three equally thin callers of one authoritative application/service layer. None of them is the protocol; the service layer is. Each caller still respects the same permission split that layer already enforces:

- **Agent-reachable operations** (claim, submit, split, open a Challenge): available from the CLI and from agent adapters. Never Accept, revise, reject, dismiss, or resolve anything — ADR-0004's Invariant 1 is enforced in the service layer itself, so no caller, however it's built, can reach around it.
- **Human-only operations** (Accept, revision_requested, reject, Promote, dismiss/resolve a Challenge, Reference review, Lightweight re-review): available from the CLI and from the web app, both surfaces for the same person — the researcher — never from an agent adapter. Every one of them requires an explicit human confirmation step in whichever surface issues it (the CLI's existing `confirmed=True` pattern in `review.py`, or the web app's own confirmation dialog) — a click that submits a form is still a human decision, exactly like a `--confirmed` flag is on the CLI, but the confirmation itself is mandatory in either surface.

"Start agent" (handing a claimed-and-ready node to an agent) means posting it to wherever agents pick up work, or notifying one that's already running — it is not the web app spawning or supervising an agent process itself. Agent orchestration belongs to whatever runs the agent (Codex, Claude Code), not to proof-cli's core.

This is hard to reverse the way ADR-0006 already is: once three surfaces are built against one service layer with this permission split baked in, un-writable-ing the web app, or re-centering the protocol back on the CLI specifically, would mean reworking every adapter's relationship to that layer, not a local change.
