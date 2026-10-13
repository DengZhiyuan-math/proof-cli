The map's discussion drawer can settle on an empty reply

**Symptom.** A finished discussion turn can show an empty reply in the drawer even though its record holds the reply. This is the 0 of 9000 characters seen intermittently in the web #12 audit.

**Cause.**
- `StudioHub.discussion_view()` reads the turn records first and the running turn (`_discussion_live`) second.
- When `_discussion_finish` writes the ended record and frees the slot between those two reads, the view returns `running: null` together with the turn's *started* record, whose reply is empty.
- The drawer stops polling once `running` is null, so it keeps that empty reply.

The race is reproduced deterministically, without sleeps, by `docs/audits/2026-10-09-web12-f0ea4a7-evidence/test_discussion_snapshot_probe.py` in proof-cli. It fails at `864a2c2` and at `f0ea4a7`, so the code had it before PR #15.

**The same window in the start's failure paths:**
- A refused start (`agent.start` returns an error) frees the slot *before* writing the ended record.
- A start that raises after the started record was written never writes an ended record, so the turn stays `started` for good, with no reply.

**Expected.**
- A view never reads as settled (`running: null`) while a turn's reply is missing.
- A turn that ends between the reads shows as still running, and the next poll returns its reply.
- Every started turn is ended on record, with its error if it failed to start.
