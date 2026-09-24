# Proof CLI

A human-machine collaborative proof system for research mathematics. It keeps a proof's dependency structure, open work, and trust boundary explicit and persistent, so agents can do local proof work while the researcher keeps final judgement.

## Language

**Proof map**:
The evolving dependency graph of one research effort, from its target theorem down to the claims and lemmas it rests on. It is an execution map: its work units are resolved by producing proofs, not decisions.
_Avoid_: proof tree (it is a DAG), project

**Candidate proof**:
A proof an agent or collaborator submits for a work unit; it is a reviewable artifact, never an established result.
_Avoid_: resolution, solution

**Acceptance**:
The researcher's explicit decision that a candidate proof enters the established proof map and may be depended on.
_Avoid_: close, merge, verify
