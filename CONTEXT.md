# Proof CLI

A human-machine collaborative proof system for research mathematics. It keeps a proof's dependency structure, open work, and trust boundary explicit and persistent, so agents can do local proof work while the researcher keeps final judgement.

## Language

**Proof map**:
The evolving dependency graph of one research effort, from its target theorem down to the claims and lemmas it rests on. It is an execution map: its proof map nodes are resolved by producing proofs, not decisions. A project holds exactly one proof map.
_Avoid_: proof tree (it is a DAG), project

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
A local proof obligation serving a specific parent node, not yet judged reusable enough to stand as a Lemma.
_Avoid_: obligation, proof obligation, open goal

**Imported result** (a proof map node kind):
An external, already-established result pulled in as a dependency. It carries a trust level instead of a candidate proof, and enters the map through Reference review rather than Acceptance.
_Avoid_: reference, external theorem

**Candidate proof**:
A proof an agent or collaborator submits for a proof map node; it is a reviewable artifact, never an established result.
_Avoid_: resolution, solution

**Acceptance**:
The researcher's explicit decision that a candidate proof for a Theorem, Lemma, or Claim node enters the established proof map and may be depended on. Does not apply to Imported result nodes — see Reference review.
_Avoid_: close, merge, verify

**Reference review**:
The researcher's explicit decision that an Imported result's external source is trustworthy enough to be depended on. Distinct from Acceptance: it judges the reliability of a source, not whether a proof holds.
_Avoid_: acceptance, verification

**Promote**:
The researcher's explicit decision to change an Accepted Claim's kind to Lemma, marking it as independently reusable. Only possible after the Claim has been Accepted; a node's kind is never automatically reassigned, and Promote does not currently support demotion.
_Avoid_: upgrade, generalize
