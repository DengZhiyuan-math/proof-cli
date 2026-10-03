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
A known difficulty not yet precise enough to state as a Claim. It lives outside the proof map as its own flat list, never as a graph node — giving it a node would force a fake-precise statement, or a special kind every graph operation would have to account for. A fog item (`fog-N`, never reused) is `open`, `dropped` (with a reason; dropping is reversible) or `crystallized` (stated as a Claim, which it names). It may be *near* one or more proof map nodes: an informal "about this" pointer that is never a dependency and never changes a node's state. Anyone, agents included, may add, edit or drop one — fog is not a mathematical judgment — with `proof fog …` or from the proof map page. Its record is SQLite; its folder `proofs/fog/<fog-id>/` is created only when something is put there. It is a list of things still to think through, not a record of what was learned (that is memory). `project analyze` reads the last dropped item as the abandoned route; the older `failed_routes` list is legacy. See ADR-0008.
_Avoid_: fog node, vague claim, memory entry, note, todo

**Crystallize**:
Turning a Proof fog item into a Claim once it becomes precise enough to state and depend on: from the fog drawer's Crystallize… (the map's node form, the item's text shown above it) or `proof fog crystallize <fog-id> <node-id> "<statement>"`, one transaction either way, with the same checks. The statement is written then, never taken from the item's text, and never blank. With a parent (given, or the item's single near node; `--no-parent` for none) it is exactly a single-child Split of that parent, every Split rule kept; a Claim only, one per crystallize. The fog item leaves the fog list — it reads `crystallized` and names the node, keeping its text, notes, near nodes and Experiments — and the node's page says "crystallized from fog-N". Only an open item crystallizes; a crystallized one never reopens. See ADR-0008.
_Avoid_: promote (already means Claim → Lemma), formalize the fog

**Experiment**:
A numerical or computational run made to probe a Proof fog item before it has a statement: what was computed, what it showed, and where its script and output live. Recorded against the fog item as `supports`, `refutes`, `inconclusive` or `error`, by whoever ran it (`proof fog experiment record`), with an optional path under `proofs/` — a person's `proofs/fog/<fog-id>/`, a proof agent's own `scratch/`. It never changes the fog item's status and never becomes an Evidence check — an Evidence check is run against a Candidate proof of a stated node, and an idea that crystallizes gets checked afresh against its proof. Insert-only: a mistaken record is answered by a new `error` one. See ADR-0008.
_Avoid_: evidence, check, verification, test

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
An external, already-established result pulled in as a dependency. It carries a trust level instead of a candidate proof, and enters the map through Reference review rather than Acceptance. Immutable once created — its statement, source locator, and source version never change in place. If the cited source is corrected or reinterpreted, that's a new Imported result node, not a revision of this one; dependents migrate to it deliberately. An Imported result has no dependencies of its own: it is established elsewhere. Its `ReferenceRecord` is only the citation (paper, book, arXiv entry), linked by the node's immutable `reference_id` (#91). It has no trust of its own: it is relied on only through the Reference review of the Imported result that links it, or a Trust rule its citation meets. See ADR-0005, ADR-0012, ADR-0014.
_Avoid_: reference, external theorem

**Candidate proof**:
A proof of a proof map node, written by an agent or collaborator; a reviewable artifact, never an established result. It is a standalone LaTeX document, the node's working file `proofs/<node-id>/proof.tex`, which agents and the researcher edit freely — or, for a node whose Medium is `computation`, the program `run.sh` and what it writes to `out/`. What gets reviewed is never the moving working file but a Review snapshot of it. The proof map node itself (id, kind, dependencies) stays in SQLite. See ADR-0010.
_Avoid_: resolution, solution

**Medium** (of a Theorem, Lemma or Claim):
What the node's Candidate proof is made of: `latex`, a standalone LaTeX document (`proof.tex`), or `computation`, a program (`run.sh` as its entry, its outputs in `out/`) whose run is meant to establish the statement — a case-by-case check, an enumeration, a formal verification, a simulation. The medium changes what the studio shows and what a Review snapshot freezes, never how the node is claimed, reviewed or Accepted: the researcher still decides whether what was frozen establishes the statement. Set at creation (`node create --medium`), changeable at any time (`node medium set`) without touching the Accepted mathematical interface. An Imported result has none.
_Avoid_: numerical node, kind (that is theorem / lemma / claim), workspace

**Proof vault**:
The repo's top-level `proofs/` directory. It holds a shared `preamble.tex`, and one folder per node with its working `proof.tex` (or, for a node whose Medium is `computation`, its `run.sh` and `out/`), its Review snapshots (`snapshots/v<N>/`, every input of the proof frozen with a manifest; older ones are single `v<N>.tex` files) and its Review decisions (`reviews.jsonl`), all tracked by git. Each node folder is an ordinary LaTeX project: the node's studio edits it, and any LaTeX editor can open it as is. Older `v<N>.md` files from ADR-0003 remain as read-only history. Distinct from `.proof/`, which holds internal, non-human-authored project state.

**Review snapshot**:
Every input of a node's proof, frozen together when its author requests review: the node's working sources, its Key-ideas summary and the shared preamble — for a node whose Medium is `computation`, its inputs (scripts, data, each script's executable bit, and only the allowlisted environment files at its root such as `.python-version`; no preamble), its outputs in `out/` and its summary, told apart so a later run can be checked against the frozen inputs (ADR-0015). Secrets (`.env`, `.env.*`, `.envrc`, `.netrc`) are never frozen or exported, nor is any other hidden file or folder; requesting review lists by path what it left out — stored as `snapshots/v<N>/` with a manifest of each file's SHA-256. What an Acceptance accepts is the summary the researcher read together with the frozen proof; requesting review is refused without a summary (`KEY_IDEAS_REQUIRED`), and a change to the summary alone is a new snapshot. It is never overwritten. Its SHA-256 is the manifest's, recomputed from the stored files, so a change to any input is a new snapshot and an edit to a frozen file breaks every decision on it. A Review decision is always about one snapshot, named by that hash; a compiled PDF may be archived beside it (only when the build was current against every input it compiles), but the frozen files and their hash are what count. Older snapshots are a single `v<N>.tex` and its hash. An unchanged proof is not snapshotted again, unless the current snapshot is missing or can't be read: requesting review then takes a *re-snapshot after loss* as the next version, which needs its own Human Review, while decisions on the lost one stay unverifiable. A snapshot from before ADR-0013 has no summary and is reviewed as before. See ADR-0010, ADR-0011, ADR-0013.
_Avoid_: version (ambiguous with a dependency's accepted version), submission

**Key-ideas summary**:
A node's `proofs/<node-id>/key-ideas.md`: its proof's key ideas in Markdown (maths as `$…$`), under four headings. 核心思路 (why it holds) and 主要步骤 (3–7 steps, each naming the dependency it uses) are required; 难点 (where it is most likely wrong) and 未覆盖 (what it leaves out) may be 「无」. It is frozen in every Review snapshot and is where review starts: the studio's review view shows it with the decisions, a review card its 核心思路 and 难点, a map node's hover its 核心思路. Its `$…$` and `$$…$$` are typeset with the vendored KaTeX. When it is missing, the proof agent can draft it, and the studio records the draft and its SHA-256 in project state; its author confirms it by requesting review. The snapshot then records who wrote the summary (`key_ideas_drafted_by`: the author, the agent's draft as confirmed, or the agent's draft as edited), and every decision on the snapshot binds it. See ADR-0013.
_Avoid_: abstract, description (the node's statement is what it claims; the summary is how the proof goes)
_Avoid_: .proof, proof store

**Acceptance**:
The researcher's explicit decision that a candidate proof for a Theorem, Lemma, or Claim node enters the established proof map and may be depended on. Does not apply to Imported result nodes — see Reference review.
_Avoid_: close, merge, verify

**Reference review**:
The researcher's explicit decision that an Imported result's external source is trustworthy enough to be depended on. Distinct from Acceptance: it judges the reliability of a source, not whether a proof holds. It may also be given in advance, for a class of citations, by a Trust rule; the node then reads Trusted by rule rather than reviewed.
_Avoid_: acceptance, verification

**Trust rule**:
A standing Reference review the researcher declares in advance: any Imported result whose citation meets the rule's conditions may be depended on without a review of its own. Declared and changed only by the researcher, on the proof map page, like every other Human Review decision; the declaration is the only record (one line per decision in the project's git-tracked `proofs/trust-rules.jsonl`: declare, amend, retire), no decision is written on the nodes it covers. A rule has an immutable name, a required rationale and one or more conditions, all of which must hold; several rules each count on their own. The conditions are a closed vocabulary: `source already reviewed` (another citation of the same reference at the same version carries the researcher's explicit Reference review, never another rule-trusted node), `source_type in {…}`, `identifier has DOI`, `identifier has arXiv`. Never the node's own trust level, free text or library folders. `proof trust-rule list` and `show` read the rules; no CLI command writes one. See ADR-0014.
_Avoid_: auto-trust, policy, whitelist, auto-accept

**Trusted by rule** (an acceptance state, Imported results only):
Derived, never stored: the node has no counting Reference review of its own but meets a Trust rule. Dependents treat it as Reference-reviewed. An explicit decision on the node, made or later, takes precedence; No longer callable is final regardless. The review page lists such nodes in their own section, apart from what awaits the researcher, each with a button to review it explicitly. Losing the rule (tightened or retired) is losing standing, nothing more: unaccepted dependents block, Accepted ones keep their Acceptance.
_Avoid_: auto-reviewed, pre-approved, reviewed (that is the explicit decision)

**Promote**:
The researcher's explicit decision to change an Accepted Claim's kind to Lemma, marking it as independently reusable. Only possible after the Claim has been Accepted; a node's kind is never automatically reassigned, and Promote does not currently support demotion.
_Avoid_: upgrade, generalize

**Evidence check**:
An automated or semi-automated check (a verifier, a checker) run against a specific Candidate proof, recorded as passed, failed, inconclusive, error, or stale. The researcher may separately judge an Evidence check trusted or unusable, but that only judges the check's own credibility — an Evidence check can never itself grant or revoke Acceptance, or close or block anything. A checker records one with `proof node evidence record`, naming itself with `--run-by`; the node page shows who ran it. Each is bound to a snapshot SHA-256: a recorded check to the one its checker names (`--snapshot-sha256`, refused unless it is the snapshot's hash now), otherwise to the snapshot's hash at the moment of recording — what it was recorded against, not necessarily what the checker ran on. The node page and `node show --json` show each check's own bound hash, flag one whose snapshot changed since, and show a check from before binding as not bound. A computation node's Run in its studio records one only when it completes with the snapshot's frozen inputs, untouched throughout, and is bound to the snapshot its inputs matched; it then establishes the execution outcome of those inputs, never the frozen outputs (ADR-0015). `proof verify run` records none: it runs no backend, and is only logged against the legacy obligation, theorem or blocker it names, changing none of their statuses (#27). See ADR-0004.
_Avoid_: verification result, verify accept, experiment (that is fog's)

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
A Human Review decision (Acceptance, Reference review, Evidence review, Lightweight re-review, Challenge resolution, Promote, Dependent migration; a Trust rule declared, amended or retired) as it is recorded: one line in the node's git-tracked `reviews.jsonl` (the project's `trust-rules.jsonl` for a Trust rule), naming the Review snapshot's SHA-256, the rationale and the time, committed together with that snapshot by the reviewer. The commit's author, a GitHub identity, *is* the reviewer, and the pushed commit is the record of who decided what. Made only on the proof map page, by the researcher; no CLI command and no agent, in a terminal or as the studio's proof agent, makes one. That boundary is a convention for cooperative agents, not a security mechanism. See ADR-0010.
_Avoid_: signed decision, confirmation, `--confirm`, approval flag

**Proof map page**:
proof-cli's own local web page, the map's home, and the researcher's one entry: the DAG and tree, the frontier, each node's three state axes, and the one place Review decisions are made. Nodes are created on the page (right-click the canvas or a card) or with `proof node create`; the form shows the equivalent command. The Proof fog is a drawer beside the map, opened from the toolbar's Fog badge: the open items, each near the nodes it is about (lit up on the canvas on hover, never drawn on it), their newest Experiment, and the adds, drops, reopens, Experiments and crystallizes; a crystallize opens the same node form, beside the item's near node, and shows `proof fog crystallize …` as its command (#155). A theorem, lemma or claim opens in its **studio**, a LaTeX workspace built from prism-local's code with a node panel for claim, split, request review, Challenge and Evidence check. An imported result opens on its own page. See ADR-0008, ADR-0010, ADR-0011.
_Avoid_: review app (its ADR-0009 name), dashboard, admin panel

**Studio**:
A local node's page on the proof map page: the Proof agent's workbench, watched by the researcher. Its centre is the node's Work log — the run's plan, its role and step, and the oversight actions (Start, Pause, Redirect, Resume, Stop and release, and Review what it has, which freezes a snapshot and, as any review request does, hands the node over) — and the editor and PDF, or a `computation` node's program and `out/`, are its Files view; a computation node's bar offers Run and Open in VS Code where a LaTeX node's offers Compile. It has a node panel for the node's state and dependencies, the review sheet for the researcher's decisions, and an Ask box for read-only questions to the agent. While a turn runs, the Files view shows the agent at work (the lines it reads, the file as it writes it, the lines it changed), and a LaTeX node's agent compiles through the studio's own build. Served by the map's own server; built from prism-local's code. See ADR-0011, ADR-0015, ADR-0016.
_Avoid_: prism-local (the separate project it was copied from), editor window, LaTeX editor

**Proof agent**:
The agent run a node's studio starts and the researcher watches: one run holds the node's claim under the project's agent name and works the node to a review request on its own, as three roles in turn — Prover, Typesetter and Numerics. It reads the whole project, the library folders `proof.toml` lists, and the web; it runs `proof` and computation; it writes files only in the node's folder, within each role's scope, and changes project state only through `proof`. It runs in the node's folder with `PROOF_ROOT` set to the project, on the Claude Code or the Codex CLI, with explicit permissions and none of the repository's own instructions. It reports its plan and each step with `proof node progress`, stops for a review request, a decision only a human can make, its budget or when stuck, and never makes a Review decision. Started once, from the map, the node page or the studio; paused, redirected, resumed or released by the researcher. See ADR-0011, ADR-0016.
_Avoid_: assistant, chat, agent panel (the panel is where it is watched), prompt-driven

**Prover** (a Proof agent role):
Finds the proof — retrieval first, then reasoning — and writes its structure as a draft in `scratch/`; decides when to split the node and when to request review; may open a Challenge on a dependency that may no longer hold (`proof challenge open`; dismissing or resolving one stays the researcher's); hands work to the Typesetter or Numerics and takes it back.
_Avoid_: solver, assistant

**Typesetter** (a Proof agent role):
Writes the Prover's draft as the node's LaTeX and its key-ideas summary, compiles and fixes it; never supplies a missing step itself — it reports the gap and the Prover takes it from there; never splits, never requests review.
_Avoid_: LaTeX assistant, editor

**Numerics** (a Proof agent role):
Writes and runs the computations — the candidate proof of a `computation` node, or evidence for a LaTeX one — and records what they showed as Evidence checks or Experiments; never edits the LaTeX.
_Avoid_: verifier (an Evidence check's checker), simulator

**Work log**:
A node's record of what its Proof agent did, in time order: the plan and each step the roles reported with `proof node progress`, merged with what they did through other `proof` commands — a split, a review request, an Evidence check, a fog item, a dependency edit — each with the role of the turn it happened in — and the turns themselves, each with its job, its backend session and the step it belongs to. Project state (events), never a file in the node folder; a turn's raw conversation is kept beside it under `.proof/agent-turns/`. What the studio's centre shows.
_Avoid_: transcript (the raw conversation, folded under a step), chat history

**No longer callable** (a Reference review outcome):
The researcher's judgment that an Imported result can't be relied on after all. Final: its dependents read potentially stale or blocked, and a corrected source becomes a new Imported result node. The researcher then moves the dependents onto it on the proof map page (a Dependent migration decision). Rejected dependents stay where they were, as the record of an abandoned route. An Accepted dependent's Acceptance was made against the withdrawn citation, so it stops counting until the researcher re-Accepts the node against the correction. See #20.
_Avoid_: rejected reference, revoked citation

### Node lifecycle

A proof map node's state is tracked along three independent axes, never folded into one flat status. None are stored directly — each is computed from lower-level records (an active claim, the node's latest Candidate proof and its review decision, its dependencies' own state, and any open Challenges). See ADR-0002, ADR-0004.

- **workflow state**: Claimed, Review-needed, Revision requested, Blocked — how far the current attempt has gotten
- **acceptance state**: Accepted, Rejected, or unreviewed by default — set only by the researcher's Human Review, and only ever read off the newest Review decision. Reads *unverifiable* when that decision no longer matches its snapshot or its node. An Imported result reads its Reference review here: reviewed, no longer callable, or *Trusted by rule* when a Trust rule covers it
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
The node's newest Review decision no longer matches what it decided: its Review snapshot's files (the frozen Key-ideas summary among them) no longer hash to the SHA-256 it names, or the node's statement, assumptions or dependencies changed since. The node is neither Accepted nor open to pick up; the researcher decides it afresh. It never falls back to an older decision. See ADR-0010.
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
Decomposing a Theorem, Lemma, or Claim into new Claim nodes that become its dependencies, so each can be worked and Accepted independently. Not gated by review — it proposes work structure, not a mathematical result — so any agent or collaborator may do it, except that a node someone else has claimed is theirs to split unless it is taken over (`--reassign`), which moves the claim to the splitter — even for a node that is Blocked and so can't be claimed. A split is all or nothing: if any new Claim can't be created, none is, and the parent is left as it was. Splitting doesn't resolve the parent: once its new dependencies are Accepted, the parent still needs its own Candidate proof (even a short one) and its own Acceptance, combining them. A parent's existing dependencies aren't automatically reassigned to the new children; only a person or agent explicitly moving one decides that (`proof node depend <parent> --move <dependency> --to <child>`, which also adds or removes an edge; the same claimant and Accepted-node rules apply, and the pins are taken at the next request-review). A new Claim may name dependencies of its own, which may not rest on the node being split. Split doesn't apply to an Imported result (nothing to decompose) or a Rejected node (pursue a new node instead of reviving that one). A node produced by a split records which node it was split from, in `derived_from`.
_Avoid_: decompose (fine informally, but keep decisions and CLI/agent protocol on "split"), break down

### Publication

A claim's way into a paper runs on two tracks that never feed each other (#30). The **mathematical track** is the node's own acceptance and integrity, read live from the counted Review decisions; publication never writes it. The **editorial track** is Editorial readiness. Nothing on either track is derived from the other: Accepted never makes a claim paper_ready, and paper_ready never makes a node Accepted.

**Editorial readiness**:
How far a claim has got towards a paper: internal_draft → collaborator_ready → supplement_ready → paper_ready, or withdrawn. It is editorial, not a Human Review decision, so any agent or collaborator may set it with `proof publication set`, and every output labels it editorial. The allowed moves are one step forward or back, withdrawn from any state, and withdrawn → internal_draft to start again; re-setting the current state (to edit a claim's details) is always allowed. Anything else fails with `INVALID_READINESS_TRANSITION`. Only a node that is Accepted · current may be put at supplement_ready or paper_ready (`PUBLICATION_NOT_ACCEPTED`); a theorem contract has no acceptance axis, so its claim never gets there (`PUBLICATION_NO_ACCEPTANCE_AXIS`). A ready claim whose node later stops being Accepted · current, for example because a Challenge was opened, is **withheld** from the paper and supplement exports and listed with the reason. The retired values migrate when a claim is loaded: `disputed` and `blocked` become internal_draft (the node's own axes now carry those facts), and `superseded` becomes withdrawn; the claim keeps `migrated_from` and a note.
_Avoid_: publication status, approved (for readiness), paper-accepted

**Release record**:
An editorial note that a bundle went out to an audience (`proof publication release`, `proof publication withdraw`). `--approved-by` names who said so; it is not a Human Review decision. A release sign-off on record is the author of the git commit that releases it (the ADR-0010 pattern), with no mechanism of its own.
_Avoid_: release approval (as if it were a review decision), sign-off record
