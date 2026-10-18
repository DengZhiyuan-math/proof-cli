# ADR-0024 — Audit first: a Pursue may audit the work awaiting review before it goes on

**Status**: accepted (2026-10-18; the researcher's decision, after a trial project's proofs all awaited review and a new Pursue found nothing to do). Amends ADR-0021 points 4, 7 and 9 for a Start that asks for it. ADR-0004 stands: only the researcher changes acceptance.

## Context

A Pursue's work ends at review requests. Every node of a finished subtree has a snapshot awaiting the researcher's decision, with the Verifier's pass. Under ADR-0021, only the researcher's decision returns such a node to the agents.

Resuming the project after a break then gives the agents nothing to do. The break may be a new session, or a system changed since. Yet each proof was last checked by one Verifier turn, in an earlier session. The researcher asked for the system to audit that work itself, then fix what fails or go on.

## Decision

1. **Audit first is a choice on Start.** It is offered on a Theorem's Coordinator and on the project's Pursue: `{"audit": true}`, or the page's "Audit first, then Pursue". Without it, nothing changes.
2. **An audit is the Verifier's one turn** on a node whose snapshot awaits the researcher's decision. Its brief tells it to read the proof as it stands, as if for the first time:
   - each step;
   - each use of a dependency, against that dependency's statement and definitions as they stand now;
   - each cited result, against its hypotheses;
   - each Standing question's choice.

   It records one verdict and changes no file.
3. **How the verdict is recorded.** It becomes an Evidence check on that snapshot, passed or failed. This happens only when the verdict's inputs digest is the snapshot's own, ADR-0019 point 4's rule. The check is advisory, as every Evidence check is (ADR-0004).
4. **What is audited, and when.**
   - **The nodes awaiting review as the Start begins.** Work requested for review during the Start is not audited by it. A node two Theorems rest on is audited once in a project Pursue.
   - **Leaves first.** A node is audited once every dependency of it that the Start audits has been audited.
   - **Audits first.** Nothing else starts while an audit may start or is going.
5. **A failed audit returns the node to the agents.** This happens only when the failed reading was recorded on the snapshot. The failed reading ends the snapshot's pass. The node is no longer Provisional, and neither is anything resting on it (ADR-0021 point 2).
   - **Rework.** The Coordinator works the node as an open node, the Prover briefed with the audit's objections, until a new snapshot is requested for review with a passing verdict.
   - **Parking.** If the rework runs out of budget, the node is parked as any node is (ADR-0021 point 9). No parent awaiting review is re-split for it.
6. **Otherwise the node is left as it is.** This covers a passed audit, one that recorded no verdict, and a failed one that could not be recorded on the snapshot. No dependent is worked again because a node was only audited.
7. **The end.**
   - **While the root awaits review,** only a failed audit's node is worked; a plain Start would have ended there.
   - **It does not end while an audit or a rework is still due.** It then ends in one of two ways: Done, saying what the audit found; or Stuck, naming each node whose failed audit no rework fixed.
   - **If the total runs out first,** it ends Budget, as any Start does, and names the nodes it did not reach.
8. **Budget.** Each audit is a real turn of the Pursue's total (proof-agents#19). It is not a turn of the node's own proof budget, so a rework has that budget whole. The default total of an audit Start adds one turn per node awaiting review.

## Considered options

- **Audit on every Start.** This is wasteful when the work was checked moments ago. Making it a choice keeps it to the occasions when the researcher wants it.
- **Let the audit reject a node or send it back.** That would be a Review decision, which is the researcher's alone (ADR-0004). A failed reading is advisory evidence. It changes only what the agents may rest on and work.
- **Count a second Verifier pass as trust.** Rejected for the same reason: two machine verdicts are still not Acceptance.

## Consequences

- **proof-agents:**
  - a node run's audit Start (`audit=True`);
  - the Coordinator's audit phase and its ending;
  - `with_audit` for the default total.
- **proof-web:**
  - `audit` on both Starts;
  - the run's `awaiting_snapshot` hook;
  - the subtree card's "Audit first, then Pursue" and what the audit found.
- **proof-cli:** registers the error codes `AUDIT_ROLES` and `INVALID_AUDIT`. Nothing else changes: an Evidence check's failed outcome already ends a pass.
- **CONTEXT.md gains** Audit first.
