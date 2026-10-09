# Progress is not gated by trust: the agents pursue a draft to the end, and the researcher's decisions come after

**Status**: accepted (2026-10-07; the researcher's decision after setting up the #132 tier 3 horocycle trial). Amended by ADR-0022: ADR-0014 no longer stands untouched; a Trust rule does not cover an imported result an agent created, so the Reader's imports reach the review queue unreviewed. Amends:
- ADR-0019 points 10, 11, 17, 18 and 20: a parent is worked on its children's passing verdicts; the Decomposer does not stop; the Coordinator does not wait.
- ADR-0020 points 4 and 7: an agent may write Definitions, and a statement or definition is fixed at the first Review decision that relies on it, not at creation.
- CONTEXT.md's Blocked: it holds back a Review decision, not work.

ADR-0004, ADR-0009, ADR-0010 and ADR-0014 stand untouched: only the researcher changes acceptance, and no node is Accepted on anything unaccepted.

## Context

The third #132 tier 3 trial put the researcher's own half-finished draft in the library: effective equidistribution of horocycle orbits on $\Gamma\backslash(SL_2(\mathbb R)\times SL_2(\mathbb Q_p))$. The main theorem had no statement, the height lemma had no proof, and the height's definition was wrong as written. Nothing in the system could start on it.
- **The draft to the map.** No role may create a Definition, a Theorem or an imported result, or import a reference. The map agent only gives commands "for the researcher to run". The trial's whole map was written by hand: six Definitions, MAIN, two Lemmas, three imported results and five fog items.
- **The Decomposer.** After the map existed, the Decomposer still ends with `needs-human` "structure proposed; the researcher decides", and the Coordinator waits for the researcher's Start.
- **Edges between Claims.** The Decomposer only names them, as commands for the researcher to copy.
- **The Coordinator.** It waits at every `review-requested` Claim until the researcher Accepts. It cannot start the parent before, because a parent with an unaccepted dependency is Blocked, and a Blocked node cannot be claimed.
- **Stuck runs.** A run that stops without a failing verdict waits for the researcher to release it (needs_you).
- **Definitions.** A Definition worded slightly wrong (A9, the second trial) is fixed forever once a node names it.

Of these, only the Acceptance of a node and the Reference review of an imported result decide trust. The others are progress gates, put where they are because each was the most cautious place, not because trust needed them. The researcher's verdict on the trial is that this makes the system unable to move on hard problems by itself: every step waits for an input. The point of the system is that the researcher reads what was done, not that they drive each step.

The guarantee that has to survive is narrower than the gates. An Accepted node rests only on Accepted nodes and Reference-reviewed (or rule-trusted) imported results. What it says never changed after a Review decision relied on it. And only the researcher makes that decision. Nothing in the guarantee requires work to wait.

## Decision

### A. Trust holds back decisions, not work

1. **Blocked holds back a Review decision, not a run.** A node with an unaccepted dependency stays Blocked: it cannot be Accepted, and an Acceptance decision on it is refused, as today. But it can be claimed and worked, and its run can request review. The snapshot waits in Review-needed until its dependencies are Accepted, and then the decision becomes possible. `NODE_BLOCKED` stops being a claim refusal and stays a decision refusal.
2. **Provisional** names an unaccepted node another may rest on for work:
   - a Theorem, Lemma or Claim whose newest Review snapshot is current and carries a passing Verifier Evidence check (ADR-0019 point 4);
   - an imported result not yet Reference-reviewed.

   The map shows a node resting on a Provisional node, directly or through others, as **conditional**: its proof stands only if they do. Conditional is derived, like every workflow state (ADR-0002), and is cleared node by node as the researcher Accepts bottom-up.
3. **A run may rely on a Provisional dependency's statement, never on its proof.** ADR-0019 point 11 stands for the proof: an appeal to a sibling's unaccepted proof text is still an appeal to nothing. What changes is that a Provisional dependency's *statement* may be used as an Accepted one's is. The Verifier checks the appeal against the statement. For an unreviewed imported result, it also reads the cited source, or marks the appeal "unchecked against the source" in its verdict, which the researcher sees at Reference review.
4. **The Coordinator does not wait for the researcher.** It starts a parent's run once every child is Accepted or Provisional. It stops when the subtree's root is requested for review with a passing verdict, when its budget is spent, or when every open node is parked (part C). A child the researcher later rejects or sends back for revision makes the parent's proof Potentially stale, through the integrity axis that already exists. The Coordinator, if running, restarts the child and then the parent.

### B. The draft to the map, by an agent

5. **A new role, the Reader**, turns the library into a map. It is started on a project, or on a library file, with nothing on the map, or with the researcher's partial map. It reads the draft and the works it cites, then writes:
   - Definitions;
   - the Theorems and Lemmas the draft states, or means to state where the draft leaves a statement empty;
   - imported results for the literature it calls on, each with its reference;
   - fog for what the draft leaves open.

   It may run `proof definition add`, `proof node create` (any kind but Claim), `proof reference import` and `proof fog add`, with `--created-by <agent>`. It records, in its closing note and in `scratch/reader/`, every place it departed from the draft and why (in the trial: the height's $\sup 1/\operatorname{Im}$, which is infinite; Γ fixed to $SL_2(\mathbb Z[1/p])$). It never proves anything.
6. **Agent-written text is unfixed until a decision relies on it.** A Definition, or a node's statement, assumptions and named definitions, may be restated while it is **unfixed**. It becomes fixed at the first Review decision on it, or on any node that rests on it. The same Review decision on an imported result fixes it. After that, ADR-0020 point 4 applies unchanged: a correction is a new Definition or a new node.
   - **Who may restate.** The researcher may restate any unfixed text. An agent may restate only unfixed text an agent created (`proof node restate`, `proof definition edit`), with a reason, recorded as an event in the work log.
   - **Effects of a restatement.** Every verdict on the node, and on the nodes resting on it, goes stale. Their snapshots become Potentially stale.
   - **Why this keeps the guarantee.** No Review decision ever saw the text change under it.
   - **The researcher's own text.** Statements the researcher created are fixed for agents from the start, as today.

### C. No step waits for the researcher by default

7. **Pursue** is the researcher's one action on a Theorem: a Coordinator that runs everything below.
   - **No Claims yet.** It starts with a Decomposer turn.
   - **No map yet.** Started on a project, it starts with a Reader turn and pursues each Theorem the Reader states.

   The Decomposer's turn no longer stops for the researcher. Its split is the structure the Coordinator works. It adds the edges between its own Claims itself (`proof node depend <claim> --add <claim> --by <agent>`), since an edge between unaccepted Claims decides nothing. The researcher may edit the structure at any time, and the Coordinator rereads it at every turn boundary. Starting the Decomposer alone, without a Coordinator, still stops after the split, for a researcher who wants to read first.
8. **A choice is made and recorded, not asked.** Where a role would end with `needs-human` because the statement admits two readings, a constant is unspecified or a case split is a judgement call, it instead does the following:
   - it picks the reading the draft most likely means;
   - it records the choice as a **Standing question**: `proof node progress <node> --question "<the choice made and the alternative>"`, a work-log event;
   - it goes on.

   The researcher answers standing questions in the review queue (point 10). An answer different from the choice is a redirect. `needs-human` stays only for what no reading can settle: a contradiction in the node's own statement, or a fact only the researcher can know. Even then it stops the node, not the subtree.
9. **Parked, not waiting.** The Coordinator restarts a stuck run whatever its last verdict, briefed with its attempts (ADR-0019 point 7), until the node's budget is spent. A node out of budget is **parked**.
   - **Parked node.** The Coordinator goes on with every node that does not need it.
   - **Parked Claim.** It may start one further Decomposer turn on the Claim's parent, to try another structure, once per parent.
   - **What the researcher sees.** Parked nodes, with their attempts, are what the researcher sees first in the review queue. They are the places the agents could not go.
   - **At the Start's budget.** When the Coordinator's total budget is spent, no turn starts. The runs still going end under their own caps, and each node is then recorded: Parked by the rule above, or **Interrupted** when its last run ended short of review with node budget left. A node still running is neither. (Amended for zeqome/proof-agents#18.)
10. **The researcher's work is a queue, not a series of gates.** The proof map page gains a review queue, ordered bottom-up so that each Accept makes the next decision possible. It holds:
    - the Provisional nodes awaiting Acceptance;
    - the unreviewed imported results;
    - the unfixed statements and Definitions agents wrote, with what the Reader departed from;
    - the standing questions;
    - the parked nodes.

    Nothing in the queue stops the agents while it waits.

## Considered options

- **Keep the gates and add an "auto-approve" switch.** The switch would let the system Accept on a passing verdict. That breaks ADR-0004, the one rule the system exists for: a machine verdict would become trust. Rejected.
- **Let runs read unaccepted sibling proofs.** This is faster than waiting for a Claim to pass, but it is what ADR-0019 point 11 rejected on good evidence (PatchBoard: unverified repair attempts read as facts). Relying on a statement whose proof passed the Verifier gives most of the speed without that.
- **Leave statements immutable and make the Reader's map a proposal the researcher confirms before any run.** This is safe, but it is the gate this decision removes. The trial's own setup shows the cost: the researcher had to approve six Definitions and five nodes before a single turn ran. Unfixed-until-relied-on keeps the guarantee and drops the wait.

## Consequences

- **What a researcher can do now.** Put a draft in the library and press Pursue on the project. The agents state, decompose, prove and verify as far as they can. What comes back is a map of Provisional nodes, conditional proofs, standing questions and parked nodes, read bottom-up. Acceptance means what it meant before.
- **Wasted work.** Work done on a Provisional dependency is wasted if the researcher rejects it. The cost is bounded by the Verifier's gate on Provisional and paid in agent time, not researcher time.
- **Changes in proof-cli:**
  - Blocked moves from the claim check to the decision check;
  - a derived *conditional* flag;
  - `proof node restate` and the unfixed/fixed rule for statements and Definitions;
  - the `--question` event.
- **Changes in proof-agents:**
  - the Reader role;
  - the Decomposer adds edges and does not stop under a Coordinator;
  - the Coordinator's start rule for parents, its restart rule and parking;
  - briefs that make a choice instead of asking.
- **Changes in proof-web:**
  - Pursue;
  - the review queue;
  - conditional and parked on the map.
- **CONTEXT.md gains** Provisional, Conditional, Reader, Pursue, Standing question, Parked, Unfixed and Review queue. It amends Blocked, Definition, Decomposer and Coordinator.
- **Reversing this** means restoring the claim refusal on Blocked and the Decomposer's stop. Nothing Accepted under this decision rests on anything unaccepted, so no decision would have to be undone.
