# ADR-0024 — Audit first: a Pursue may audit the work awaiting review before it goes on

**Status**: accepted (2026-10-18; the researcher's decision, after a trial project's proofs all awaited review and a new Pursue found nothing to do). Amends ADR-0021 points 4, 7 and 9 for a Start that asks for it. ADR-0004 stands: only the researcher changes acceptance. Amended the same day (point 2's mechanical checks, and ADR-0019 point 3's gate), after a trial's audit ended with no verdict on a check added since the snapshot. Amended by ADR-0025: awaiting review and a failed audit's effect read as the Proof layer and the computed conclusions, and an audit records no Challenge endings; a failure on the mechanical checks is no verdict (point 13, 2026-10-21).

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

   **The mechanical checks first (issue #180).** As in any run, the Verifier is not called while the node folder's checks report an error. A snapshot frozen before a check existed, or under an older rule, can fail one now. Its audit then fails on the findings, without a turn, and the failure is recorded as the audit's failed reading (point 3). Checks that cannot run conclude nothing: the node is left as it is.
3. **How the verdict is recorded.** It becomes an Evidence check on that snapshot, passed or failed. This happens only when the verdict's inputs digest is the snapshot's own, ADR-0019 point 4's rule. The check is advisory, as every Evidence check is (ADR-0004).
4. **What is audited, and when.**
   - **The nodes awaiting review as the Start begins.** Work requested for review during the Start is not audited by it. A node two Theorems rest on is audited once in a project Pursue. One whose snapshot passed an audit already, with nothing it rests on changed since, is audited again only when the Start asks (point 15).
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
8. **The Prover's gate holds the checks too** (amends ADR-0019 point 3). A passing verdict on the files as they stand opens the gate only while the mechanical checks pass. Otherwise a rework after a failed audit, or any run after a check was added, could request review on the old pass.
9. **Budget.** Each audit is a real turn of the Pursue's total (proof-agents#19). It is not a turn of the node's own proof budget, so a rework has that budget whole. The default total of an audit Start adds one turn per node awaiting review.

## Amendment: what two audit-first trials showed (2026-10-18)

A review of the records of the first two audit-first runs found the following. These amendments are the researcher's decisions.

10. **A proof does not restate standing.** A dependency's standing is the map's. Accepted, Provisional and Conditional are derived (CONTEXT.md), and the page shows what a proof rests on.
    - **What went wrong.** The Verifier's checklist asked the proof text to keep reliance on Provisional statements "explicit as Conditional support". A failed audit ends the node's and its dependents' Provisional standing (point 5). So the dependents audited next failed on wording that had just gone stale, in a cascade.
    - **What changes.** No brief makes standing part of the proof, and wording about standing is no objection.
11. **A failed dependency is fixed first.** A node one of whose dependencies failed its audit is audited once that dependency's rework is requested for review, on its standing as it then is. While audits wait on such a rework, the failed nodes are worked; point 4's "audits first" otherwise stands.
12. **What the ending says.**
    - A failed audit of a node that rested on something neither Accepted nor Provisional at the time says so.
    - A node whose audit recorded no verdict is named.
    - Audit turns are counted apart from proof turns.
13. **What an audit is briefed with.**
    - **No earlier record.** An audit's briefing carries no earlier verdict and no attempts. Its reading is fresh, and nothing anchors it.
    - **A no-turn failure counts as the newest verdict.** An audit that failed on the mechanical checks, with no turn, leaves only its closing note. Later runs read that note as the newest verdict, failed: neither their briefing nor the Prover's gate reads the older pass as current.
      *Amended by ADR-0025 (zeqome/proof-agents#46, the researcher's decision of 2026-10-21):* the proof is its `.tex`; a check the files fail says nothing of the mathematics. Such a failure is the audit's Evidence check, failed, and no verdict. While the checks fail on the files as they stand, no gate opens, and the briefing and the run's card say they fail beside the newest verdict. Once they pass on the same files, the earlier pass stands. A check the files must change to pass leaves that pass stale anyway.
14. **The project's Pursue on a map that is already there.**
    - **Offered on the page.** The page offers it once the map has a Theorem, with "Audit first, then Pursue" when nodes await review. It is recorded as a project pursuit.
    - **What the pursuit's history keeps.** Its history keeps whether it audited first, and what it has spent as each turn ends.
    - **After a stop.** One the server stopped reads back what it spent, as incomplete.

## Amendment: what a third audit-first trial showed (2026-10-18)

A review of a third audit-first run's records found that its audit Start re-read 13 snapshots of 15 that had passed an audit already, on the same files, with nothing they rest on changed since: most of its turns, finding nothing new. Its audits also read the earlier record their briefing left out (point 13). These amendments are the researcher's decisions.

15. **A snapshot whose audit passed is not audited again by default** (amends point 4).
    - **What is skipped.** A node whose snapshot awaiting review passed an audit, with nothing it rests on changed since: no restatement and no Definition edit under it (`restated_at`), and no change to its dependencies. What tells an audit's pass from the Prover's gate check on the same snapshot is the audit's closing note in the work log, after the snapshot's review request, its verdict recorded on the snapshot.
    - **Auditing them again is a choice of its own.** A Start may ask for it (`reaudit`); the page offers "Audit all again, then Pursue" beside "Audit first, then Pursue" when such snapshots await review.
    - **The ending names what it skipped,** and the default total counts only the nodes the Start audits.
16. **An audit's runtime keeps the earlier record out of reach** (point 13). `proof node show --json` withholds every node's Evidence checks, the work log read gives only the Standing questions and their answers, and the audit works in a scratch folder of its own, made empty.

## Amendment: what a fourth audit-first trial showed (2026-10-19)

A fourth audit-first run, on one Theorem's subtree, ended Stuck on a parked node. A review of its records found three gaps. A node was audited while a failed node further down was still being worked. The outcome of a failed audit, and the Start's own ending, lived only in the hub's memory, so a restarted page read the project's older Pursue, Done, as the last. And Prover turns were spent only on requesting review once the Verifier had passed the files. These amendments are the researcher's decisions.

17. **Leaves first, through everything beneath** (amends points 4 and 11). A node is audited once every node beneath it, not only its direct dependencies, that the Start audits has been audited. It is not audited while a node beneath it failed its audit and no rework has fixed it yet.
18. **A failed audit stands across Starts** (amends points 4 and 5).
    - **Read off the record.** How the newest audit of each snapshot awaiting review ended, passed or failed, is read off the node's work log when a Start begins. A pass counts only while nothing the node rests on has changed since (point 15). A failure stands until the node is worked again.
    - **Any Start works the failed nodes again first.** A plain Start does as an audit Start does: the failed nodes are reworked before the others. An audit Start does not audit them again.
    - **The ending names the cause.** A failed audit that no rework fixed because its node rests on a parked node names that node.
19. **The run requests review itself** (amends ADR-0019 point 3). Once the Verifier passed the files as they stand and the mechanical checks pass, the run requests review under its own name, by the verdict's hash. Its rationale is the hand-off to the Verifier. The request is refused on the same grounds as the Prover's: a stale verdict, a failing check, no key ideas. A refused request is left to the Prover's next turn, as before.
20. **A re-split that keeps the parked Claim holds its new Claims** (amends ADR-0021 point 9). The Decomposer's further turn on a parked Claim's parent goes ahead as before. While the parent still rests on the parked Claim, the Claims the re-split made are not started: the structure they serve waits on the researcher's decision about the parked Claim. They start once the parent no longer rests on a parked node.
21. **A Pursue on one node's subtree is kept with the project** (extends point 14). It is recorded as a pursuit that names its root: its start, its spend as each turn ends, and its end or failed release. A restarted page reads its ending on that node's Coordinator. The project's Pursue view does not take it for the project's own; it says the Pursue came since.
22. **No role's turn reads the project's own state** (extends point 16). The project's `.proof/` holds the earlier turns' conversations and the record an audit is not to read. A role reads the map through `proof`, which withholds what an audit may not see.

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
- **proof-cli:** registers the error codes `AUDIT_ROLES` and `INVALID_AUDIT`. In an audit's runtime (`PROOF_AGENT_AUDIT`, point 13), `proof node show --json` withholds every node's Evidence checks and `proof node progress <node>` reads only the Standing questions and their answers. Nothing else changes: an Evidence check's failed outcome already ends a pass.
- **CONTEXT.md gains** Audit first.
- **The fourth amendment (points 17–22):**
  - proof-agents: the Coordinator's `audit_outcomes` hook, read at Start and for the totals rather than on every look at the subtree, and its `ended` hook; the run's `request_review` hook; a role's turn given its tools alone (`--tools`), no skills and no MCP server but the studio's compile tool, and no read of `.proof/`.
  - proof-web: implements the three hooks; records a subtree's Pursue; the subtree card shows its last recorded ending and the failed audits.
  - proof-cli: `record_pursuit(root=…)`, read back by `project_progress` and named by `proof project progress`.
