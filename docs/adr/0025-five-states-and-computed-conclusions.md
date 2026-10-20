# ADR-0025 — Five states and four computed conclusions: one state model for the agents and the researcher

**Status**: accepted (2026-10-20; the researcher's decisions in the planning maps [#254](https://github.com/DengZhiyuan-math/proof-cli/issues/254) and [#267](https://github.com/DengZhiyuan-math/proof-cli/issues/267)). Not yet implemented: the implementation tickets are listed in [#260](https://github.com/DengZhiyuan-math/proof-cli/issues/260), and until they land the code keeps the earlier model under its earlier names. Amends ADR-0002, 0004, 0005, 0006, 0007, 0008, 0010, 0011, 0012, 0013, 0014, 0016, 0019, 0020, 0021, 0022, 0023 and 0024; each one's Status line says how.

## Context

The first map (#254) set out to make the statement a review accepts the same text a dependent calls, and to tell apart proved criteria, checked criteria, counterexamples and work awaiting the researcher. Its decisions kept adding states and marks. The second map (#267) counted what the three packages already had: 54 concepts with 278 values, 205 gates and 220 stored fields (#268, #272). Several concepts held the same fact, several gates read descriptive text, and 25 names meant more than one thing.

The researcher's premise: states and labels are a permission mechanism for the agents, there to keep automated work running, not something a person has to remember. The researcher talks to the agents in natural language and the system parses it. "Simpler" measures the effort the system spends on two things: judging whether a label is right, and knowing what to do on seeing it. The existing concepts get no priority for being there already.

## Decision

### A. The model

1. **Only five states are kept as source facts.** Every gate reads only these and what is computed from them.

   | State | Who changes it | Values |
   |---|---|---|
   | **Seal** (封存) | the researcher only | unsealed, sealed true, sealed false |
   | **Statement layer** (命题层) | the agents; the researcher may raise a Challenge | unchallenged, challenged as false, false |
   | **Proof layer** (证明层) | the agents and the researcher | incomplete, checks passed, expert-verified |
   | **Assignee** (领取) | the agents and the researcher | who is working on the node |
   | **Run state** (运行) | the system | running, paused, not running |

   Each state is read off its own record (the assignment, the check and verification records, the seal lines, the run records), never cached in a status field beside them: ADR-0002's principle, applied to fewer states. How a run, a Coordinator or a Pursue ended (done, stuck, budget, parked, interrupted) is a run record, not a value of Run state. A sixth state needs the error it prevents named first, and the researcher's consent.
2. **Four conclusions are computed, never kept**: uncertain, true, verified true, false.
   - Sealed true → verified true; sealed false → false.
   - Unsealed: statement false → false; challenged as false → uncertain; unchallenged with the proof incomplete → uncertain; unchallenged with checks passed → true; unchallenged and expert-verified → verified true.
   - An imported result has no proof of its own: until the researcher verifies it, its Proof layer counts as checks passed, so it is true; verified, or covered by a Trust rule, it is expert-verified.
3. **A conclusion is never above its weakest dependency.** A true dependency caps the node at true. An uncertain one makes it uncertain, and only the dependency is worked: once it recovers, the node recovers with no action. A false one makes the node uncertain, not false: the node needs a proof that does not use it, and its verification is void. Only a direct dependency's falsehood voids a verification, and for good: a dependency found false after the verification (sealed false, or found no longer callable) leaves it void even once unsealed, and only a new verification restores it. A false node further down voids nothing above its users: those are uncertain, capped by their weakest dependency, and recover with it (#279).
4. **Three checks measure the model**:
   1. every gate reads only the five states and what is computed from them, parses no descriptive text, and names the error it prevents;
   2. one fact is recorded in one place, and everywhere else it is computed;
   3. one name means one thing.

   Counts of fields, event kinds and page labels are observed, never targets: most are records, and one more record does not make an agent's judgement harder. "Parses no descriptive text" means no state is read off a hand-off note, a reason or a closing note; a mechanical check reads `proof.tex` itself, and its result is a check record the Proof layer is computed from.
5. **The dispositions.** Every value the inventory found goes to one of five places: one of the five states; computed; a record (what happened, which no agent has to judge); deleted; or moved out (not about proofs). The counts, with the per-item detail kept local, are in the result of #272.

### B. Challenges

6. **Anyone may raise a Challenge, and it takes effect at once.** It comes from an agent or the researcher, and nobody reviews the Challenge first. A sealed node cannot be challenged. A Challenge has a kind:
   - **against the proof**: the Proof layer goes back to incomplete and the gap is recorded. Only that node is reworked; parallel work goes on.
   - **against the statement**: the Statement layer becomes challenged as false. Work stops below every node that uses it directly, on that branch only. Example: A uses U1 and U2, and U1 uses N and S. When N is challenged as false, all work under U1 stops, S included; U2 goes on; A is uncertain and waits.
7. **An agent's statement Challenge comes with a counterexample**, an ordinary node with its scope in its own statement, for example "f(x)=x(1−x) is continuous on [0,1] and not monotone". The Challenge links to it; the link has no state of its own, and that the counterexample does not rest on its target is computed from the graph. While the branch is stopped, both sides are checked: one repairs the counterexample's argument, the other writes a proof of the challenged statement, and that proof's Verifier must read the counterexample and say where it fails. Whichever passes its check first decides. If a few rounds within the budget leave it undecided, or the statement is false, the work goes back one level for a new approach or a re-split, within the existing re-split limit, and then to the researcher. Counterexamples that refute each other in a cycle are all uncertain and go back by the same budget; there is no conflict pause. A statement Challenge the researcher raises is discussed with the agents, and the researcher concludes.
8. **A Verifier's objection is a proof Challenge**, numbered within its Verdict, which has a stable id and is bound to one version. The Work log records who raised it, against which version, where and why.
9. **A Challenge ends in one of three ways, each recorded in the Work log**:
   - **fixed**: a passed Verdict states, for each objection of the previous version still open, where and why it is fixed. A passed Verdict that leaves one out is refused.
   - **withdrawn**, with a reason. Any agent may withdraw any agent's Challenge; the reason is a record, it enters the next briefing, and the branch resumes. A Challenge the researcher raised is withdrawn only by the researcher. Without agent withdrawal, automated work would stall.
   - **superseded by a restatement**, recorded by the system. A statement Challenge follows a restatement to the new version, and both sides are checked afresh; if the restatement changed the conditions so the counterexample no longer applies, it is withdrawn with that reason. A proof gap is superseded with the old version.

   An audit records no endings; old objections are left to the next ordinary Verifier. A researcher who finds something not fixed raises a new Challenge on the current version.
10. **"Not a problem"** is the researcher's answer withdrawing an agent's Challenge. On a proof the researcher verified, unchanged since, it restores the verification.
11. **Fog is not a statement.** A counterexample to an assertion in a fog item is only a link, briefed later, and stops nothing. A Claim crystallized as that assertion takes the Challenge with it, as a restatement would.
12. **The agents do not hold parallel discussions.** An agent's Challenge goes through the existing relay: written as a record, briefed to the next role, bounded by the turn and budget limits, then a re-split, then the researcher.

### C. Verification and Seal

13. **Verification** is the researcher's "checked, and I believe it": the Proof layer becomes expert-verified, for that version only. It replaces Acceptance and Reference review. A node may be verified before its dependencies; its conclusion stays capped by them and rises with no action once they are verified. If a direct dependency is later false, the node becomes uncertain and the verification is void (point 3). When an agent challenges a verified, unsealed node, the verification lapses at once; after the fix the researcher rereads the changed part, or answers "not a problem".
14. **A Seal** is absolute belief, the researcher's responsibility. Sealing true seals everything the node rests on with it: only the directly sealed node is recorded, the coverage is computed, and unsealing releases it together. The coverage is computed when the seal is made, from what the node rests on then, and recorded in the seal's line with each covered node's statement: what the page showed is what is sealed, a node that comes to rest under it later is not sealed by it, and unsealing removes that seal and its coverage, while a node sealed itself, or covered by another true seal, stays sealed (#279). Sealing false seals only the node. The agents never challenge or audit a sealed node; they use it as known, and the researcher's seal note is in their briefings. Promote needs a Claim that is expert-verified or sealed true. Text is fixed, for everyone, by the first verification or Seal that relies on it (ADR-0020 point 4, ADR-0021 point 6); a Challenge against the proof does not fix it.
15. **Before every seal and unseal the system lists what it does**, never blocks, and asks for a note:
    - sealing true: how many nodes it covers, which of them are unverified, which have a Challenge not ended (for example a counterexample being checked both ways), and that audits and both-way checks stop there;
    - sealing false: the nodes that use it directly, which become uncertain and need another route, and which of those the researcher verified, whose verifications lapse;
    - unsealing: the nodes released with it, and that the agents will audit and challenge them again.
16. **What takes effect only on the researcher's click**: verifying, sealing true, sealing false, unsealing, and a "not a problem" that restores a verification. The Coordinator may only propose them. Each is one line in the node's git-tracked `reviews.jsonl` naming who, when, which version and the note, committed with the researcher as author; the Work log reads it from there. No agent records a verification or a seal (ADR-0010's boundary). In a project that is not a git repository, or when the commit fails, the decision still takes effect, recorded locally and marked uncommitted.
17. **What takes effect when said**: raising a Challenge, withdrawing one's own, and "not a problem" on an unverified proof. These are only in the Work log, with the researcher's words and the Coordinator's reading; a misreading is undone by saying so.
18. **There is no Rejected.** A researcher who doubts a node raises a Challenge. The discussion writes down the reason and settles it in an existing mechanism: a counterexample that passes its check, or sealing false; a new version; a dependency edit that takes the node off the route; or withdrawing the Challenge.

### D. The Coordinator parses the researcher's words

19. **Every project has one Coordinator, always listening**, open as soon as the map is, with no Pursue running. It parses what the researcher says, discusses it and records the actions. It hands out work only inside a Pursue; outside one, it asks the researcher whether to start one. It is therefore a model-backed agent, no longer a controller that runs no model and exists only while a Pursue runs. It stays in proof-agents with the other roles; proof-web serves its input box (ADR-0018), and what it records is project state, in the Work log.
20. **The studio's input box is the same Coordinator**, knowing which node the researcher means. It is the one parser: what changes state is recorded as an action, and an instruction for a node's agent goes to that node's next turn as a redirect. Redirect and Ask merge into this box. The editor's own AI panel edits files and never touches state.
21. **Talking with the Coordinator is not counted in a Pursue's budget**, which limits only the agents' work while the researcher is not watching. Handing out work again after a confirmation follows the existing rules; a re-split uses the Decomposer's turns and limit.
22. **When readings differ in consequence, it asks first**, saying what each reading would do, and nothing changes until the answer. With only one reading it acts and records "I read this as …". Words about verifying or sealing only ever produce a proposal. For example, "L5 isn't right" may mean a gap in the proof (only L5 is reworked) or a false statement (the branch using L5 stops), so it asks; "step 2 of L5 has a gap" has one reading, and it records a proof Challenge on L5.

### E. Kept from the first map

23. These decisions of #254 stand under this model:
    - conditions are written out in the statement (#261); a mechanical check marks other node ids in a statement as a hint to the Verifier, gating nothing;
    - a proof states how it uses each dependency, in its `Uses of dependencies` section (#262, #256); a proof without it never reaches checks passed;
    - what changed between two versions is computed from their snapshots (#264);
    - a node's assumptions and Definitions reach whoever reads it, in briefings (#266);
    - shared conditions are Definitions, not inherited assumptions (#255); a stale Verdict is the Proof layer back to incomplete;
    - a node names only the Definitions its statement and assumptions use, and each is one of its conditions (#286, amending ADR-0020 point 3): splitting, creating under a parent and crystallizing under a parent no longer name the parent's automatically. The Verifier fails a statement that uses a Definition its node does not name, or names one its statement and assumptions do not use. A condition the statement states but the proof does not need is not an error;
    - criteria, checks and counterexamples are ordinary statements (#263); "awaiting the researcher" is computed: checks passed, not expert-verified, unsealed;
    - questions and objections are bound to a version, a Verdict has a stable id, an audit sees no earlier Verdict, and "superseded by a restatement" is computed (#258, #265);
    - from #257: a counterexample is a statement; a node that changes the basis it rests on must change its proof and be checked again, and removing the edge alone does not count; a fog Experiment's `refutes` is only a record; a running agent stops at a safe point and keeps its work; a Pursue keeps Stuck and reports per target, telling a statement that is false or challenged as false apart from a blocked proof route.

### F. What goes

24. No longer states or decisions: the three state axes (workflow, acceptance, integrity); Rejected; Revision requested, now a proof Challenge; Unverifiable, since a verification counts only for its own version; Potentially stale and Challenged; Blocked, Provisional and Conditional, replaced by the conclusions and point 3; Lightweight re-review and Dependent migration, since a pin follows an unchanged interface by itself and dependents move by ordinary dependency edits; Evidence review; No longer callable, now sealing false; Trusted by rule as a state, now computed as expert-verified from the Trust rule records; and a Challenge's stored status. Their records stay as history.
25. Withdrawn from #254 (#258, #265): the "vN addressed, awaiting confirmation" mark, objections closed only by the researcher, and the researcher confirming or reopening each one. From #257, everything but the link from a Challenge to its counterexample: the relation's four states, its activation conditions, its own check, the conflict pause, automatic Challenges, the post-crystallize wait.

### G. Existing projects

26. **A project switches once, automatically**, the first time the new version opens it. There is no dedicated migration flow and no confirmation step (#254's standing constraints 2 and 4); the researcher's stated focus is the system's stability, not real proofs.
    - Accepted nodes, and imported results Reference-reviewed or covered by a Trust rule, are expert-verified. Nothing is sealed automatically.
    - A Rejected node nothing rests on any more is history. One still rested on becomes the researcher's Challenge, with the original reason; its branch stops, and the Coordinator asks the researcher how to settle it.
    - An open Challenge becomes a Challenge by the same raiser, its text kept. The Coordinator reads it as against the statement or against the proof; when the readings differ in consequence it asks, and until then the node is not true and its branch waits. Closed Challenges are records.
    - A Verdict from before the switch is not a check under this model. An unaccepted node with a passed one is incomplete and is checked again in the next Pursue, after the Prover adds `Uses of dependencies`. Old objections are briefed as text; the rule in point 9 that a passed Verdict must end each one applies only to objections recorded under this model.
    - An imported result found no longer callable is sealed false. `reviews.jsonl` is not rewritten: an old Acceptance reads as a verification, an old rejection as history.
    - Runs from before the switch do not continue: they read interrupted, their assignees are released, and their drafts and Work log stay. A copy of the old database is kept for diagnosis, and the Work log records what the switch changed, with counts.

## Considered options

- **Keep the three axes and add the new marks** (the first map's path). Each mark answered a real case, but every gate then had to read several overlapping states, and the counts showed the same fact in many places. Rejected for check 2.
- **Store a status per node** was rejected in ADR-0002 as a second source of truth. This model keeps five source facts and computes everything else, which is the same principle applied to fewer, different states.
- **Let only the researcher withdraw a Challenge.** Automated runs would stall at every mistaken objection. Rejected by the researcher.
- **Seal all old Accepted nodes, or seal all Rejected ones false.** Sealing is absolute belief, which an old Acceptance does not state, and a rejection often says only that an approach failed. Rejected.

## Consequences

- CONTEXT.md is revised with this ADR. Until the implementation lands, the code's names are those listed under each entry's _Avoid_.
- The baseline the implementation is measured against (#272): 95 gates fail check 1 (13 belong to deleted operations, 5 to the legacy Challenge fallback; 21 budget and record-once gates are excluded as only literal failures); 123 stored fields hold a value that can be computed and 148 duplicate a fact kept elsewhere (50 facts), with 28 values computed twice; 16 names still mean more than one thing.
- Known gaps for the implementation: today's Challenge has no kind; the authorship of a node and its text is read by 7 gates but is not an inventory concept, and is treated as structure, like the node kind; audit results and the Verifier's checks are recognised today from descriptive text and need structured marks.
- AGENTS.md's Core Value and Constraints still speak of Accepted and Reference-reviewed nodes; they are reworded when the implementation lands.
