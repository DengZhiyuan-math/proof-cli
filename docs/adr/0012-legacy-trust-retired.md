# Legacy trust retired; a reference is a citation linked to its imported result

**Status**: accepted (decided in #50; implemented in #90, the link in #91).
- **Amends** ADR-0005 Rule 1: a `ReferenceRecord` is no longer re-reviewed on its own. It is trusted only through the Reference review of the imported_result node that links it.
- **Amends** ADR-0001: `ProofObligation` and `BlockerRecord` stay only as legacy informational notes, with no "resolve", and a `BlockerRecord` is not an annotation attached to a proof-map node (point 6).
- **Amends** ADR-0004: a `CommentThread` is not how an observation about a proof-map node is recorded (point 7).

## Context

The proof map (ADR-0001) took over the job of the older contract registry, but the older model kept its own trust fields: `trust_level`, `review_state`, `is_callable` and the statuses on `TheoremContract`, `ProofObligation`, `BlockerRecord` and `ReferenceRecord`. Since #37 nothing could change them.
- `proof obligation resolve` and `proof reference review` only refused, and sent the researcher to the proof map page, which has no such operations.
- A locally created contract is always `temporary_admit`, so `theorem_callability` always answers "not callable".
- `proof theorem ground` always failed, and each failure filed a new obligation.
- `proof project analyze` suggested "resolve obligation", a step nobody could take.

So the project answered "what can be called?" in two places, and one of them could never change its answer. #50 weighed giving the legacy operations their own recorded decisions on the proof map page (two trust models kept alive) against retiring them.

## Decision

1. **Only proof-map nodes answer "what can be called".** A local node can be depended on once it is Accepted, and an imported_result once it has a Reference review (ADR-0004, ADR-0010). The trust and status fields of `TheoremContract`, `ProofObligation`, `BlockerRecord` and `ReferenceRecord` are no longer the basis of any decision. An obligation or a blocker is an informational note, and there is no longer any "resolve".

2. **The legacy commands are frozen and labelled, not deleted.**
   - `theorem apply`, `theorem extract`, `theorem ground`, `explain apply`, `bug scan` (whose checks call `theorem_callability`), `provenance show`, `reference list` and `export` stay in the Legacy group, or where they were.
   - Every place one of them reports a callable, trust or review state says so: *legacy — not a trust source; what can be called is answered by the proof map*. The text output prints that notice. Under `--json`, the envelope's data carries it as `legacy_notice`.
   - `theorem ground` no longer files an obligation when it fails; it only reports the failure.
   - `project analyze` no longer suggests resolving an obligation. It suggests stating it as a Claim node on the proof map.

3. **The refusing commands are removed.** `proof obligation resolve` and `proof reference review` are gone, so they answer "No such command". The service functions only tests called (`close_obligation`, `block_obligation`, `resolve_blocker` and `storage._reference_trust_level`) are deleted with them.

4. **A `ReferenceRecord` is a citation.** It is the bibliographic entry: the paper, book or arXiv entry. Whether it can be relied on is decided by a human Reference review of the imported_result node that cites it.
   - That node links it by an optional, immutable `reference_id`. The link is set when the node is created (`node create --reference-id`, or the page's form), and the reference must exist (#91).
   - The node page and the review card show the linked entry.
   - A Reference review binds the `reference_id`, not the entry's text. If the linked entry is deleted, the review reads unverifiable. Editing the entry's text doesn't touch the review.

5. **Conditional auto-trust is deferred.** A rule that treats a reference meeting certain conditions as trusted without a review may come later. For now it is recorded under Not yet specified on the wayfinder map (#87).

6. **A `BlockerRecord` is a legacy informational note, not attached to proof-map nodes.** ADR-0001 kept it as "an annotation attached to a node". It isn't one: nothing links it to a node, and none will. A problem with a node is expressed as a Challenge when it calls the node's standing into doubt, or informally otherwise (point 7). *(Researcher's decision, 2026-09-29, closing out #14.)*

7. **Comment threads are not wired to proof-map nodes.** A `CommentThread` is not validated against nodes and is not shown on a node's page. ADR-0004 named it the home of an ordinary observation about a node. Informal discussion of a node lives instead in the studio's agent panel and in git history. *(Researcher's decision, 2026-09-29, closing out #14.)*

## Consequences

- There is one trust model. A caller that needs to know whether something can be depended on reads the proof map, never a contract or a reference.
- Old projects keep all their legacy records, readable as they were, and marked as not a trust source.
- The legacy commands' `--json` envelopes are new: one envelope per call, as ADR-0006's contract (#34) asks, with `legacy_notice` in the data.
- An exchange import that resets the legacy trust fields and `review_state` to local defaults belongs to #31, not here.
