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
An external, already-established result pulled in as a dependency. It carries a trust level instead of a candidate proof, and enters the map through Reference review rather than Acceptance. Immutable once created — its statement, source locator, and source version never change in place. If the cited source is corrected or reinterpreted, that's a new Imported result node, not a revision of this one; dependents migrate to it deliberately. An Imported result has no dependencies of its own: it is established elsewhere. Its `ReferenceRecord` is only the citation (paper, book, arXiv entry), linked by the node's immutable `reference_id` (#91). It has no trust of its own: it is relied on only through the Reference review of the Imported result that links it. See ADR-0005, ADR-0012.
_Avoid_: reference, external theorem

**Candidate proof**:
A proof of a proof map node, written by an agent or collaborator; a reviewable artifact, never an established result. It is a standalone LaTeX document, the node's working file `proofs/<node-id>/proof.tex`, which agents and the researcher edit freely. What gets reviewed is never the moving working file but a Review snapshot of it. The proof map node itself (id, kind, dependencies) stays in SQLite. See ADR-0010.
_Avoid_: resolution, solution

**Proof vault**:
The repo's top-level `proofs/` directory. It holds a shared `preamble.tex`, and one folder per node with its working `proof.tex`, its Review snapshots (`snapshots/v<N>/`, every input of the proof frozen with a manifest; older ones are single `v<N>.tex` files) and its Review decisions (`reviews.jsonl`), all tracked by git. Each node folder is an ordinary LaTeX project: the node's studio edits it, and any LaTeX editor can open it as is. Older `v<N>.md` files from ADR-0003 remain as read-only history. Distinct from `.proof/`, which holds internal, non-human-authored project state.

**Review snapshot**:
Every input of a node's proof, frozen together when its author requests review: the node's working sources and the shared preamble, stored as `snapshots/v<N>/` with a manifest of each file's SHA-256. It is never overwritten. Its SHA-256 is the manifest's, recomputed from the stored files, so a change to any input is a new snapshot and an edit to a frozen file breaks every decision on it. A Review decision is always about one snapshot, named by that hash; a compiled PDF may be archived beside it (only when the build was current against every input), but the frozen files and their hash are what count. Older snapshots are a single `v<N>.tex` and its hash. See ADR-0010, ADR-0011.
_Avoid_: version (ambiguous with a dependency's accepted version), submission
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
An automated or semi-automated check (a verifier, a checker) run against a specific Candidate proof, recorded as passed, failed, inconclusive, error, or stale. The researcher may separately judge an Evidence check trusted or unusable, but that only judges the check's own credibility — an Evidence check can never itself grant or revoke Acceptance, or close or block anything. A checker records one with `proof node evidence record`, naming itself with `--run-by`; the node page shows who ran it. `proof verify run` records none: it runs no backend, and is only logged against the legacy obligation, theorem or blocker it names, changing none of their statuses (#27). See ADR-0004.
_Avoid_: verification result, verify accept

**Challenge**:
A claim, raised against an already-Accepted node or an Imported result, that it may no longer be safe to depend on (for example, a missing assumption noticed after the fact). Any agent or collaborator may open one — raising a concern isn't a mathematical judgment, so it isn't gated. Opening a Challenge sets its target's integrity state to Challenged; it never changes the target's acceptance state. Only the researcher resolves a Challenge: for a local node, by dismissing it or by revising the node and re-Accepting it; for an Imported result, through Reference review (reaffirming trust, or treating it as no longer callable so dependents migrate to a corrected node). How it ended is read off the Review decision that closed it: **dismissed** (a false alarm, or the Imported result reaffirmed), **upheld** (the revision was rejected or sent back, or the Imported result is no longer callable), or **resolved-by-revision** (a revised proof was Accepted). An ordinary observation that doesn't call a node's standing into doubt is not a Challenge — Challenge is reserved for the invalidating case. It is informal discussion, which lives in the studio's agent panel and in git history: comment threads aren't attached to proof map nodes, and neither are legacy blocker records (ADR-0012). A Challenge is itself an addressable, listable object once opened, not just a flag on its target. See ADR-0004, ADR-0005, ADR-0006.
_Avoid_: bug, finding

**Accepted mathematical interface**:
The part of a node's accepted content that other nodes actually depend on — its statement, assumptions, and mathematical scope. Never its internal proof, proof strategy, or Evidence checks: a dependent relies on what a node says, not how it was shown. Whether a dependency needs only a Lightweight re-review or a whole new Candidate proof after a revision turns on whether this — not the proof text — changed. See ADR-0005.
_Avoid_: statement (too narrow — assumptions and scope matter too), interface version

**Lightweight re-review**:
Human Review's confirmation that an existing Candidate proof remains valid after one of its dependencies advanced to a new accepted version, because that dependency's Accepted mathematical interface didn't change — only its internal proof did. Updates the dependency edge's pinned version and is recorded as its own kind of review decision (`dependency_revalidation`, decision `reaffirmed`); it does not create a new Candidate proof, and it does not touch the reviewing node's own acceptance state. If the interface did change, this doesn't apply — a new Candidate proof is required instead. See ADR-0005.
_Avoid_: reaccept, re-approve, revalidate (as a bare verb — say what's being revalidated)

**Review decision**:
A Human Review decision (Acceptance, Reference review, Evidence review, Lightweight re-review, Challenge resolution, Promote, Dependent migration) as it is recorded: one line in the node's git-tracked `reviews.jsonl`, naming the Review snapshot's SHA-256, the rationale and the time, committed together with that snapshot by the reviewer. The commit's author, a GitHub identity, *is* the reviewer, and the pushed commit is the record of who decided what. Made only on the proof map page, by the researcher; no CLI command and no agent, in a terminal or as the studio's proof agent, makes one. That boundary is a convention for cooperative agents, not a security mechanism. See ADR-0010.
_Avoid_: signed decision, confirmation, `--confirm`, approval flag

**Proof map page**:
proof-cli's own local web page, the map's home, and the researcher's one entry: the DAG and tree, the frontier, creating nodes, each node's three state axes, and the one place Review decisions are made. A theorem, lemma or claim opens in its **studio**, a LaTeX workspace built from prism-local's code with a node panel for claim, split, request review, Challenge and Evidence check. An imported result opens on its own page. See ADR-0008, ADR-0010, ADR-0011.
_Avoid_: review app (its ADR-0009 name), dashboard, admin panel

**Studio**:
A local node's page on the proof map page: a LaTeX workspace over the node's folder `proofs/<node-id>/`, built from prism-local's code and served by the map's own server. It has an editor, compile (`proof.tex` → `build/proof.pdf`, when TeX or Tectonic is installed), the PDF with SyncTeX both ways, the proof agent, and a node panel for claim, split, request review, Challenge, Evidence check and the node's Review decisions. Its editor writes only the node's working sources; snapshots, build output and `reviews.jsonl` are never edited there. An imported result has no studio. See ADR-0011.
_Avoid_: prism-local (the separate project it was copied from), editor window

**Proof agent**:
The agent a node's studio runs: an automated prover on that node, not a LaTeX assistant. It reads the whole project, the library folders `proof.toml` lists, and the web; it runs `proof` and computation (Python, SageMath, Lean); it writes files only in the node's sources and its `scratch/` folder, and changes project state only through `proof`. It runs in the node's folder with `PROOF_ROOT` set to the project, on the Claude Code or the Codex CLI, with explicit permissions and none of the repository's own instructions. It never makes a Review decision, and its Undo restores files only. See ADR-0011.
_Avoid_: assistant, chat, agent panel (the panel is where it runs)

**No longer callable** (a Reference review outcome):
The researcher's judgment that an Imported result can't be relied on after all. Final: its dependents read potentially stale or blocked, and a corrected source becomes a new Imported result node. The researcher then moves the dependents onto it on the proof map page (a Dependent migration decision). Rejected dependents stay where they were, as the record of an abandoned route. An Accepted dependent's Acceptance was made against the withdrawn citation, so it stops counting until the researcher re-Accepts the node against the correction. See #20.
_Avoid_: rejected reference, revoked citation

### Node lifecycle

A proof map node's state is tracked along three independent axes, never folded into one flat status. None are stored directly — each is computed from lower-level records (an active claim, the node's latest Candidate proof and its review decision, its dependencies' own state, and any open Challenges). See ADR-0002, ADR-0004.

- **workflow state**: Claimed, Review-needed, Revision requested, Blocked — how far the current attempt has gotten
- **acceptance state**: Accepted, Rejected, or unreviewed by default — set only by the researcher's Human Review, and only ever read off the newest Review decision. Reads *unverifiable* when that decision no longer matches its snapshot or its node
- **integrity state**: current by default, Potentially stale, or Challenged — a derived warning overlay, never itself a workflow or acceptance value

**Claimed** (a workflow state):
A researcher or agent has assigned a proof map node to itself before working on it, as a wayfinder ticket is claimed by its assignee: the assignee *is* the claim. It is transitional, a planning signal that tells concurrent agents to skip the node, never a lock. It doesn't gate editing the working file, carries no token, and a stale one is simply reassigned or cleared. One assignee per node; the claim ends when its holder requests review or unassigns. The **frontier** is the open, unblocked, unclaimed nodes. See ADR-0006, ADR-0010.
_Avoid_: lock, lease, in progress, proof-drafted

**Review-needed** (a workflow state):
A proof map node's author has requested review, so a Review snapshot awaits the researcher's Acceptance or Reference review decision. It is the only workflow state in which an Acceptance decision (accept, revision requested, reject) can be made. A node with no snapshot, Blocked, or whose newest snapshot was already decided can't receive one.
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

**Unverifiable** (an acceptance state):
The node's newest Review decision no longer matches what it decided: its Review snapshot's file no longer hashes to the SHA-256 it names, or the node's statement, assumptions or dependencies changed since. The node is neither Accepted nor open to pick up; the researcher decides it afresh. It never falls back to an older decision. See ADR-0010.
_Avoid_: unsigned, invalid, unreviewed

**Rejected** (an acceptance state):
The researcher's decision that a node's approach does not hold and should not be pursued further. The node and its full candidate-proof and review history stay in the proof map permanently, as the record of the abandoned route. Rejected is terminal: the node can't be decided again, claimed, or split.
_Avoid_: closed, abandoned, revision requested

**Integrity state**:
A derived overlay on a node's acceptance state — current, Potentially stale, or Challenged — computed from the dependency graph. It is never stored, and it is never itself a workflow or acceptance value, or a change to either. See ADR-0004.
_Avoid_: status, health

**Potentially stale** (an integrity state):
An Accepted node has an ancestor with an open Challenge, or has a dependency edge whose pinned version no longer matches its target's current accepted version (the two may still share the same Accepted mathematical interface — that's exactly what a Lightweight re-review checks). Computed by reachability over the dependency graph from every open Challenge's target and every version-mismatched edge, never stored per node: nothing is cleared by hand, dismissing a Challenge or reconfirming a dependency (by Lightweight re-review or a new Candidate proof) just makes the same query stop returning true. A node that isn't yet Accepted shows the same underlying cause as Blocked instead, rather than Potentially stale: labelled dependency-challenged when a Challenge (or a citation found no longer callable) is upstream, and dependency-stale when only a lagging or changed pin is. See ADR-0005.
_Avoid_: stale, out of date

**Split**:
Decomposing a Theorem, Lemma, or Claim into new Claim nodes that become its dependencies, so each can be worked and Accepted independently. Not gated by review — it proposes work structure, not a mathematical result — so any agent or collaborator may do it, except that a node someone else has claimed is theirs to split unless it is taken over (`--reassign`), which moves the claim to the splitter — even for a node that is Blocked and so can't be claimed. A split is all or nothing: if any new Claim can't be created, none is, and the parent is left as it was. Splitting doesn't resolve the parent: once its new dependencies are Accepted, the parent still needs its own Candidate proof (even a short one) and its own Acceptance, combining them. A parent's existing dependencies aren't automatically reassigned to the new children; only a person or agent explicitly moving one decides that. Split doesn't apply to an Imported result (nothing to decompose) or a Rejected node (pursue a new node instead of reviving that one). A node produced by a split records which node it was split from, in `derived_from`.
_Avoid_: decompose (fine informally, but keep decisions and CLI/agent protocol on "split"), break down
