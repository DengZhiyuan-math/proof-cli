# Derive proof map node lifecycle state; reuse collaboration review machinery

**Status**: accepted

A proof map node needs to expose seven lifecycle states (open, claimed, review-needed, accepted, revision requested, rejected, blocked), and the revise loop needs those states to stay consistent across repeated attempts on the same node. We considered giving `Proof map node` a stored `status` field, updated by every mutating action, but rejected it: it would be a second, denormalized source of truth alongside the claim, candidate-proof, and review records that already determine it, and every new action that touches those records would also have to remember to keep the cached field in sync.

Decided instead: **no stored status field**. Every lifecycle state is computed at read time from three inputs — whether an active claim exists, the node's latest candidate proof and its review decision, and whether the node's dependencies have themselves reached Acceptance or Reference review:

| state | derivation |
|---|---|
| open | none of the below hold |
| claimed | an active claim exists and no candidate proof is awaiting review |
| review-needed | a candidate proof exists with no review decision yet |
| accepted | the latest review decision is `approved` |
| revision requested | the latest review decision is `revision_requested` |
| rejected | the latest review decision is `rejected` |
| blocked | a dependency has not reached Acceptance / Reference review |

`proof-drafted` from the original concept collapses into `claimed` — there is no signal in this model that distinguishes "claimed but not yet started" from "claimed and drafting."

We also decided to reuse the existing `ReviewRecord` / `ReviewGovernanceState` / `record_review_request` / `record_review_decision` machinery in `collaboration.py` — already the mechanism behind `approve_imported_result` and `close_obligation_review` — as the audit trail behind both Acceptance and Reference review, rather than inventing a parallel review record type for proof map nodes. This requires adding one new `ReviewGovernanceState` value, `revision_requested`, since the existing values (`approved`, `rejected`, `superseded`, `disputed`) have no way to say "this attempt failed, but the node is still worth pursuing" as distinct from "this route is abandoned."

Revising a node submits a new candidate proof (and gets a new review record) against the *same* node id; nothing is deleted. This is why the derivation above always reads "the latest" review decision rather than "the" review decision — the full history of prior attempts stays queryable, which is what makes a `rejected` node's own persistence sufficient as the historical record of an abandoned route (see `CONTEXT.md`'s Node lifecycle section). `ProjectState.failed_routes` is narrowed to cover only proof-fog-level abandonment — a direction dropped before it became precise enough to be a Claim node — never a route that already has a rejected node recording it, so the two don't drift into disagreeing histories.

This is hard to reverse once agents and the CLI start querying node state through this derivation instead of a status column — switching to a stored field later would mean re-deriving `status` retroactively from history for every existing project, not just adding a migration default.
