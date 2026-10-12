# A Trust rule covers the researcher's imports: an agent's imported result needs its own Reference review

**Status**: accepted (2026-10-08; the researcher's decision after the ADR-0021 design audit, `docs/audits/2026-10-08-adr0021-design-audit.md`). Amends:
- ADR-0014 points 2 and 3 and its first consequence: a Trust rule is met only by an imported result the researcher created.
- ADR-0021's preamble: ADR-0014 no longer stands untouched. ADR-0004, ADR-0009 and ADR-0010 still do.

## Context

ADR-0014 lets the researcher declare in advance that a class of citations is trustworthy. Its conditions read the citation: `source_type`, `identifier`, and whether the same source at the same version was already Reference-reviewed. Nothing in it reads the node's statement, by design: free text is never a condition.

That was safe while the researcher typed most imported results. A rule vouches for the *source*. The statement and source locator that say *what* the source proves were the researcher's own. ADR-0021 point 5 changed who writes them: the Reader imports the literature a draft calls on, and its statement of each result is its own paraphrase. A paraphrase that drifts from the source is the Reader's most likely mistake. The trial's departures show it rewrites what it reads.

The audit found that both ways a Reader import meets a rule are ADR-0014 working as written:
- the researcher declared a rule on `source_type in {other}`, and the Reader's citation had the default type;
- the Reader cited a reference the researcher had already imported with a DOI, and a rule on `identifier has DOI` matched.

Either way the import read `trusted-by-rule`. It was callable, and no one had read its statement against the source. It also bypassed two things ADR-0021 relies on. Point 3 says the Verifier's "unchecked against the source" mark is seen at Reference review. Point 10 lists unreviewed imported results in the review queue. A rule-trusted import goes through neither.

## Decision

1. **A Trust rule is met only by an imported result the researcher created.** An imported result whose `created_by` is not the researcher meets no rule, whatever its citation. This includes `source already reviewed`: that condition shows the source was read, not that this statement is in it. Such a node gains standing only through its own explicit Reference review. Precedence is otherwise ADR-0014 point 2's: `no-longer-callable` > a counting explicit Reference review > `trusted-by-rule` > `unverifiable` > `unreviewed`.
2. **The node's author decides, never the citation's.** The check reads the imported result node's `created_by`, not the `ReferenceRecord`'s. Reusing a citation the researcher imported, adding a DOI to it or citing a source the researcher already reviewed does not change who wrote the statement. `created_by` is self-declared, as every author field is. The check holds against cooperative agents, the scope of ADR-0010, and is not a security mechanism.
3. **The review queue makes the review cheap.** An agent's imported result appears in the review queue as unreviewed (ADR-0021 point 10). It shows:
   - each rule it would meet had the researcher imported it;
   - every "unchecked against the source" mark a Verifier left on a dependent's verdict (ADR-0021 point 3), naming the dependent, its snapshot and whether that snapshot is still current.

   The Reference review's rationale is prefilled from the rules it would meet. The decision itself is the ordinary Reference review.
4. **The researcher's own imports are unchanged.** For an imported result the researcher created, ADR-0014 applies as written, conditions and precedence included.
5. **An agent's import that loses standing loses it as under ADR-0014 point 4.** An agent-created imported result that read `trusted-by-rule` before this decision reads `unreviewed` from now on. Under ADR-0021, that makes it Provisional. Its unaccepted dependents become conditional, and their Acceptance waits on its Reference review. Its Accepted dependents keep their Acceptance. The event that recorded when it first met a rule stays in its history.

## Considered options

- **Keep ADR-0014 and only show the warning.** List agent imports in the rule-trusted section with the Verifier's "unchecked against the source" marks. No ADR changes, but an agent's paraphrase would be callable before anyone read it. A rule the researcher declared about sources would decide something about statements. Rejected.
- **A new condition, `created by the researcher`, in the closed vocabulary.** The researcher could add it to each rule. Every rule declared before it would still cover agent imports, so the safe reading would be opt-in. Rejected.
- **Check the statement against the source automatically.** No offline check can tell a faithful statement from a paraphrase that drifted. The Verifier's reading of the source (ADR-0021 point 3) is the closest, and it is advice to the researcher, not trust.

## Consequences

- **What stays the same.** There is still one trust model with one author. A Trust rule is still a Human Review decision made in advance. It now covers only statements the researcher wrote.
- **What the researcher pays.** Every imported result the Reader writes is reviewed one by one. Point 3 keeps that to reading a statement against its source and pressing Review.
- **The Reader's bibliography is complete again.** The Reader no longer has to leave out `--identifier` and `--source-type` as a guard against rules: those fields no longer give its imports any trust. Its permission to create no Claim stays, as a role constraint (ADR-0010).
- **Changes in proof-cli:**
  - rule matching skips an imported result not created by the researcher;
  - `--json` keeps `trust_rule` for the rules that count, and adds `would_meet_trust_rule` for an agent import's rules that would have counted.
- **Changes in proof-agents:** the Reader's ban on `--identifier` and `--source-type` is lifted.
- **Changes in proof-web:**
  - the review queue shows the rules an agent import would meet, and the Verifier's "unchecked against the source" marks;
  - the Reference review's rationale is prefilled.
- **Before release**, count the agent-created imported results in existing projects that read `trusted-by-rule`. Point 5 drops them to unreviewed.
- **CONTEXT.md** amends Trust rule and Trusted by rule.
- **Reversing this** means dropping the author check. No decision was written or unwritten by it, so nothing has to be undone.
