# Proof CLI

A human-machine collaborative proof system for research mathematics. It keeps a proof's dependency structure, open work, and trust boundary explicit and persistent, so agents can do local proof work while the researcher keeps final judgement.

## Language

**Proof map**:
The evolving dependency graph of one research effort, from its target theorem down to the claims and lemmas it rests on. It is an execution map: its proof map nodes are resolved by producing proofs, not decisions. A project holds exactly one proof map.
_Avoid_: proof tree (it is a DAG), project

**Frontier**:
The set of proof map nodes ready to be worked right now — no unresolved dependency, no active claim. The first thing an agent or a researcher checks, and the strongest visual signal in any Proof map view, ahead of workflow/acceptance/integrity state. See ADR-0006, ADR-0008.
_Avoid_: ready queue, backlog

**Proof fog**:
A known difficulty not yet precise enough to state as a Claim. It lives outside the proof map as its own list, never as a graph node — giving it a node would force a fake-precise statement, or a special kind every graph operation would have to account for. See ADR-0008.
_Avoid_: fog node, vague claim

**Crystallize**:
Turning a Proof fog item into a proof map node once it becomes precise enough to state and depend on. An ordinary node creation, not a migration of the fog entry itself — the fog entry is just dropped once the node exists.
_Avoid_: promote (already means Claim → Lemma), formalize the fog

**DAG view**:
The canonical presentation of a proof map — the real dependency structure, including a node depended on by more than one other node. The only Proof map presentation that's a source of truth; a Tree view is always derived from it. See ADR-0008.
_Avoid_: graph view (ambiguous with Tree view, which is also a graph)

**Tree view**:
A presentation rooted at one node, answering "how is this proved?" — it deliberately re-shows a shared dependency at every place it's used, rather than deduplicating it the way the DAG view does. Derived from the DAG view on demand; never itself canonical. See ADR-0008.
_Avoid_: proof tree (see Proof map's own _Avoid_ — a proof map is a DAG; this is one rooted, duplicating rendering of it, not a claim that the structure is a tree)

**Proof map node**:
The single entity type for every vertex in a proof map — theorem, lemma, claim, or imported result. All four share one structure (statement, assumptions, dependencies, status, candidate proof); `kind` distinguishes what role a node plays, not its shape. See ADR-0001.
_Avoid_: node (ambiguous with generic graph/UI nodes), ticket (carries software-wayfinder connotations), work unit

**Theorem** (a proof map node kind):
The single target node of a proof map — the result the whole map exists to establish.
_Avoid_: destination, goal

**Lemma** (a proof map node kind):
An accepted, local result with independent standing that other nodes may depend on. A node only becomes a Lemma by Promote, which requires it already be Accepted.
_Avoid_: proposition, corollary, result — these are display labels for how a Lemma is described in writing, not distinct kinds

**Claim** (a proof map node kind):
A local proof obligation serving a specific parent node, not yet judged reusable enough to stand as a Lemma. Note the deliberate homonym with the verb "to claim" (see Claimed, below) — the noun names a node kind, the verb names an agent's action; they are disambiguated by part of speech, not by spelling.
_Avoid_: obligation, proof obligation, open goal

**Imported result** (a proof map node kind):
An external, already-established result pulled in as a dependency. It carries a trust level instead of a candidate proof, and enters the map through Reference review rather than Acceptance. Immutable once created — its statement, source locator, and source version never change in place. If the cited source is corrected or reinterpreted, that's a new Imported result node, not a revision of this one; dependents migrate to it deliberately. Its `ReferenceRecord` (the citation itself — paper, book, arXiv entry) is a separate thing and can still be freely re-reviewed. See ADR-0005.
_Avoid_: reference, external theorem

**Candidate proof**:
A proof an agent or collaborator submits for a proof map node; it is a reviewable artifact, never an established result. Its text lives as a Markdown file in the Proof vault, one immutable file per attempt; the proof map node itself (id, kind, dependencies) stays in SQLite. See ADR-0003.
_Avoid_: resolution, solution

**Proof vault**:
The repo's top-level `proofs/` directory: one Markdown file per Candidate proof attempt (`proofs/<node-id>/v<N>.md`), openable directly as an Obsidian vault. Distinct from `.proof/`, which holds internal, non-human-authored project state.
_Avoid_: .proof, proof store

**Acceptance**:
The researcher's explicit decision that a candidate proof for a Theorem, Lemma, or Claim node enters the established proof map and may be depended on. Does not apply to Imported result nodes — see Reference review.
_Avoid_: close, merge, verify

**Reference review**:
The researcher's explicit decision that an Imported result's external source is trustworthy enough to be depended on. Distinct from Acceptance: it judges the reliability of a source, not whether a proof holds.
_Avoid_: acceptance, verification

**Promote**:
The researcher's explicit decision to change an Accepted Claim's kind to Lemma, marking it as independently reusable. Only possible after the Claim has been Accepted; a node's kind is never automatically reassigned, and Promote does not currently support demotion.
_Avoid_: upgrade, generalize

**Evidence check**:
An automated or semi-automated check (a verifier, a checker) run against a specific Candidate proof, recorded as passed, failed, inconclusive, error, or stale. The researcher may separately judge an Evidence check trusted or unusable, but that only judges the check's own credibility — an Evidence check can never itself grant or revoke Acceptance, or close or block anything. See ADR-0004.
_Avoid_: verification result, verify accept

**Challenge**:
A claim, raised against an already-Accepted node or an Imported result, that it may no longer be safe to depend on (for example, a missing assumption noticed after the fact). Any agent or collaborator may open one — raising a concern isn't a mathematical judgment, so it isn't gated. Opening a Challenge sets its target's integrity state to Challenged; it never changes the target's acceptance state. Only the researcher resolves a Challenge: for a local node, by dismissing it or by revising the node and re-Accepting it; for an Imported result, through Reference review (reaffirming trust, or treating it as no longer callable so dependents migrate to a corrected node). An ordinary observation that doesn't call a node's standing into doubt is a Comment, not a Challenge — Challenge is reserved for the invalidating case. A Challenge is itself an addressable, listable object once opened, not just a flag on its target. See ADR-0004, ADR-0005, ADR-0006.
_Avoid_: bug, finding

**Accepted mathematical interface**:
The part of a node's accepted content that other nodes actually depend on — its statement, assumptions, and mathematical scope. Never its internal proof, proof strategy, or Evidence checks: a dependent relies on what a node says, not how it was shown. Whether a dependency needs only a Lightweight re-review or a whole new Candidate proof after a revision turns on whether this — not the proof text — changed. See ADR-0005.
_Avoid_: statement (too narrow — assumptions and scope matter too), interface version

**Lightweight re-review**:
Human Review's confirmation that an existing Candidate proof remains valid after one of its dependencies advanced to a new accepted version, because that dependency's Accepted mathematical interface didn't change — only its internal proof did. Updates the dependency edge's pinned version and is recorded as its own kind of review decision (`dependency_revalidation`, decision `reaffirmed`); it does not create a new Candidate proof, and it does not touch the reviewing node's own acceptance state. If the interface did change, this doesn't apply — a new Candidate proof is required instead. See ADR-0005.
_Avoid_: reaccept, re-approve, revalidate (as a bare verb — say what's being revalidated)

### Node lifecycle

A proof map node's state is tracked along three independent axes, never folded into one flat status. None are stored directly — each is computed from lower-level records (an active claim, the node's latest Candidate proof and its review decision, its dependencies' own state, and any open Challenges). See ADR-0002, ADR-0004.

- **workflow state**: Claimed, Review-needed, Revision requested, Blocked — how far the current attempt has gotten
- **acceptance state**: Accepted, Rejected, or unreviewed by default — set only by the researcher's Human Review
- **integrity state**: current by default, Potentially stale, or Challenged — a derived warning overlay, never itself a workflow or acceptance value

**Claimed** (a workflow state):
A researcher or agent has taken ownership of a proof map node to work on it, and has not yet submitted a Candidate proof for it. At most one claim is active on a node at a time; submitting a Candidate proof ends it, handing the node to review-needed — the next attempt needs a fresh claim. See ADR-0006.
_Avoid_: assigned, in progress, proof-drafted

**Review-needed** (a workflow state):
A proof map node has a submitted Candidate proof awaiting the researcher's Acceptance or Reference review decision.
_Avoid_: pending review, submitted

**Revision requested** (a workflow state):
The researcher's decision that a Candidate proof does not stand, but the node itself is still worth pursuing — the next attempt targets the same node, not a new one.
_Avoid_: rejected, needs work

**Blocked** (a workflow state):
A proof map node has at least one dependency that has not yet reached Acceptance (for a Theorem, Lemma, or Claim dependency) or Reference review (for an Imported result dependency). Blocked overrides Claimed, Review-needed, and Revision requested within the workflow axis. It says nothing about a node's acceptance or integrity state — those are separate axes, tracked and shown alongside it, not competed with for the same slot.
_Avoid_: waiting

**Accepted** (an acceptance state):
The researcher has given this node Acceptance (or, for an Imported result, Reference review); it may be depended on. Only a Human Review decision sets or changes this — no other subsystem may.
_Avoid_: verified, established

**Rejected** (an acceptance state):
The researcher's decision that a node's approach does not hold and should not be pursued further. The node and its full candidate-proof and review history stay in the proof map permanently, as the record of the abandoned route.
_Avoid_: closed, abandoned, revision requested

**Integrity state**:
A derived overlay on a node's acceptance state — current, Potentially stale, or Challenged — computed from the dependency graph. It is never stored, and it is never itself a workflow or acceptance value, or a change to either. See ADR-0004.
_Avoid_: status, health

**Potentially stale** (an integrity state):
An Accepted node has an ancestor with an open Challenge, or has a dependency edge whose pinned version no longer matches its target's current accepted version (the two may still share the same Accepted mathematical interface — that's exactly what a Lightweight re-review checks). Computed by reachability over the dependency graph from every open Challenge's target and every version-mismatched edge, never stored per node: nothing is cleared by hand, dismissing a Challenge or reconfirming a dependency (by Lightweight re-review or a new Candidate proof) just makes the same query stop returning true. A node that isn't yet Accepted shows the same underlying cause as Blocked instead, labelled dependency-challenged, rather than Potentially stale. See ADR-0005.
_Avoid_: stale, out of date

**Split**:
Decomposing a Theorem, Lemma, or Claim into new Claim nodes that become its dependencies, so each can be worked and Accepted independently. Not gated by review — it proposes work structure, not a mathematical result — so any agent or collaborator may do it. Splitting doesn't resolve the parent: once its new dependencies are Accepted, the parent still needs its own Candidate proof (even a short one) and its own Acceptance, combining them. A parent's existing dependencies aren't automatically reassigned to the new children; only a person or agent explicitly moving one decides that. Split doesn't apply to an Imported result (nothing to decompose) or a Rejected node (pursue a new node instead of reviving that one). A node produced by a split records which node it was split from, in `derived_from`.
_Avoid_: decompose (fine informally, but keep decisions and CLI/agent protocol on "split"), break down
