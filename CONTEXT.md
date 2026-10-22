# Proof CLI

A human-machine collaborative proof system for research mathematics. It keeps a proof's dependency structure, open work, and trust boundary explicit and persistent, so agents can do local proof work while the researcher keeps final judgement.

## Language

**Proof map**:
The evolving dependency graph of one research effort, from its target theorem down to the claims and lemmas it rests on. It is an execution map: its proof map nodes are resolved by producing proofs, not decisions. A project holds exactly one proof map.
_Avoid_: proof tree (it is a DAG), project

**Frontier**:
The set of proof map nodes ready to be worked right now — Proof layer incomplete, no Assignee, unsealed, not stopped by a statement Challenge, and every dependency true or verified true. The first thing an agent or a researcher checks, and the strongest visual signal in any Proof map view, ahead of the node's other states. See ADR-0006, ADR-0008, ADR-0021, ADR-0025.
_Avoid_: ready queue, backlog

**Proof fog**:
A known difficulty not yet precise enough to state as a Claim. It lives outside the proof map as its own flat list, never as a graph node — giving it a node would force a fake-precise statement, or a special kind every graph operation would have to account for. A fog item (`fog-N`, never reused) is `open`, `dropped` (with a reason; dropping is reversible) or `crystallized` (stated as a Claim, which it names). It may be *near* one or more proof map nodes: an informal "about this" pointer that is never a dependency and never changes a node's state. Anyone, agents included, may add, edit or drop one — fog is not a mathematical judgment — with `proof fog …` or from the proof map page. Its record is SQLite; its folder `proofs/fog/<fog-id>/` is created only when something is put there. It is a list of things still to think through, not a record of what was learned (that is memory). `project analyze` reads the last dropped item as the abandoned route; the older `failed_routes` list is legacy. See ADR-0008.
_Avoid_: fog node, vague claim, memory entry, note, todo

**Crystallize**:
Turning a Proof fog item into a Claim once it becomes precise enough to state and depend on: `proof fog crystallize <fog-id> <node-id> "<statement>"`, one transaction. The statement is written then, never taken from the item's text. With a parent (given, or the item's single near node; `--no-parent` for none) it is exactly a single-child Split of that parent, every Split rule kept; a Claim only, one per crystallize. On the proof map page, **Crystallize…** on a fog item opens the node form preset this way, the item's text shown to write the statement against (#155). The fog item leaves the fog list — it reads `crystallized` and names the node, keeping its text, notes, near nodes and Experiments — and the node's page says "crystallized from fog-N". Only an open item crystallizes; a crystallized one never reopens. See ADR-0008.
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
The single entity type for every vertex in a proof map — theorem, lemma, claim, or imported result. All four share one structure (statement, assumptions, dependencies, the five states of Node state, candidate proof); `kind` distinguishes what role a node plays, not its shape. See ADR-0001.
_Avoid_: node (ambiguous with generic graph/UI nodes), ticket (carries software-wayfinder connotations), work unit

**Definition**:
A project's named piece of mathematical text — a definition, the setting of a model, notation — that node statements are written in. A Proof map node names, when it is created, the definitions its statement and assumptions are written in and no others, and they change only by a restatement while Unfixed; a Claim split from a node names only those of that node's definitions it uses. The researcher or the Reader writes them. A definition is Unfixed until a verification or a Seal relies on it, then fixed like a statement: a corrected one is a new definition, named by new nodes. What a node says is its statement, assumptions and definitions together, so each definition it names is one of its conditions, which whoever uses it must meet. See ADR-0020, ADR-0021, ADR-0025.
_Avoid_: notation file, glossary, context (as a noun for this), setting (say the definition's term)

**Theorem** (a proof map node kind):
The single target node of a proof map — the result the whole map exists to establish.
_Avoid_: destination, goal

**Lemma** (a proof map node kind):
A verified, local result with independent standing that other nodes may depend on. A node only becomes a Lemma by Promote, which requires it already be expert-verified or sealed true.
_Avoid_: proposition, corollary, result — these are display labels for how a Lemma is described in writing, not distinct kinds

**Claim** (a proof map node kind):
A local proof obligation serving a specific parent node, not yet judged reusable enough to stand as a Lemma. The word names only this node kind: who is working on a node is its Assignee (ADR-0025).
_Avoid_: obligation, proof obligation, open goal

**Imported result** (a proof map node kind):
An external, already-established result pulled in as a dependency. It carries a trust level instead of a candidate proof: until the researcher verifies it (a judgement of its source, not of a proof) its Proof layer counts as checks passed. Its statement is Unfixed until its verification, or the first verification or Seal of a node resting on it, relies on it (ADR-0021 point 6); from then on it is immutable — its statement, source locator, and source version never change in place. If the cited source is corrected or reinterpreted, that's a new Imported result node, not a revision of this one; dependents move to it by ordinary dependency edits. An Imported result has no dependencies of its own: it is established elsewhere. Its `ReferenceRecord` is only the citation (paper, book, arXiv entry), linked by the node's immutable `reference_id` (#91). Its bibliography (title, authors, year, source type, identifier, URL, notes) is corrected in place with `proof reference edit … --reason`, recorded as an event with the editor, the reason and the old and new values; the node's statement, source and `reference_id` are not edited there (#202). It has no trust of its own: it is relied on only through the verification of the Imported result that links it, or a Trust rule its citation meets. See ADR-0005, ADR-0012, ADR-0014, ADR-0025.
_Avoid_: reference, external theorem

**Candidate proof**:
A proof of a proof map node, written by an agent or collaborator; a reviewable artifact, never an established result. It is a standalone LaTeX document, the node's working file `proofs/<node-id>/proof.tex`, which agents and the researcher edit freely — or, for a node whose Medium is `computation`, the program `run.sh` and what it writes to `out/`. What gets reviewed is never the moving working file but a Review snapshot of it. The proof map node itself (id, kind, dependencies) stays in SQLite. See ADR-0010.
_Avoid_: resolution, solution

**Medium** (of a Theorem, Lemma or Claim):
What the node's Candidate proof is made of: `latex`, a standalone LaTeX document (`proof.tex`), or `computation`, a program (`run.sh` as its entry, its outputs in `out/`) whose run is meant to establish the statement — a case-by-case check, an enumeration, a formal verification, a simulation. The medium changes what the studio shows and what a Review snapshot freezes, never how the node is assigned, checked or verified: the researcher still decides whether what was frozen establishes the statement. Set at creation (`node create --medium`), changeable at any time (`node medium set`) without touching the Mathematical interface. An Imported result has none.
_Avoid_: numerical node, kind (that is theorem / lemma / claim), workspace

**Proof vault**:
The repo's top-level `proofs/` directory. It holds a shared `preamble.tex`, and one folder per node with its working `proof.tex` (or, for a node whose Medium is `computation`, its `run.sh` and `out/`), its Review snapshots (`snapshots/v<N>/`, every input of the proof frozen with a manifest; older ones are single `v<N>.tex` files) and its Researcher decisions (`reviews.jsonl`), all tracked by git. Each node folder is an ordinary LaTeX project: the node's studio edits it, and any LaTeX editor can open it as is. Older `v<N>.md` files from ADR-0003 remain as read-only history. Distinct from `.proof/`, which holds internal, non-human-authored project state.

**Review snapshot**:
Every input of a node's proof, frozen together when its author requests review: the node's working sources, its Key-ideas summary and the shared preamble — for a node whose Medium is `computation`, its inputs (scripts, data, each script's executable bit, and only the allowlisted environment files at its root such as `.python-version`; no preamble), its outputs in `out/` and its summary, told apart so a later run can be checked against the frozen inputs (ADR-0015). Secrets (`.env`, `.env.*`, `.envrc`, `.netrc`) are never frozen or exported, nor is any other hidden file or folder; requesting review lists by path what it left out — stored as `snapshots/v<N>/` with a manifest of each file's SHA-256. What a verification verifies is the summary the researcher read together with the frozen proof; requesting review is refused without a summary (`KEY_IDEAS_REQUIRED`), and a change to the summary alone is a new snapshot. It is never overwritten. Its SHA-256 is the manifest's, recomputed from the stored files, so a change to any input is a new snapshot and an edit to a frozen file breaks every decision on it. A Researcher decision is always about one snapshot, named by that hash; a compiled PDF may be archived beside it (only when the build was current against every input it compiles and its log has no errors; the request records the build's error and warning counts), but the frozen files and their hash are what count. Older snapshots are a single `v<N>.tex` and its hash. An unchanged proof is not snapshotted again, unless the current snapshot is missing or can't be read: requesting review then takes a *re-snapshot after loss* as the next version, which needs its own verification, while a verification of the lost one no longer counts. A snapshot from before ADR-0013 has no summary and is reviewed as before. See ADR-0010, ADR-0011, ADR-0013.
_Avoid_: version (ambiguous with a dependency's accepted version), submission

**Key-ideas summary**:
A node's `proofs/<node-id>/key-ideas.md`: its proof's key ideas in Markdown (maths as `$…$`), under four headings. 核心思路 (why it holds) and 主要步骤 (3–7 steps, each naming the dependency it uses) are required; 难点 (where it is most likely wrong) and 未覆盖 (what it leaves out) may be 「无」. It is frozen in every Review snapshot and is where review starts: the studio's review view shows it with the decisions, a review card its 核心思路 and 难点, a map node's hover its 核心思路. Its `$…$` and `$$…$$` are typeset with the vendored KaTeX. When it is missing, the proof agent can draft it, and the studio records the draft and its SHA-256 in project state; only a researcher request that confirms the summary can record author confirmation. Ask and other agent requests do not. The snapshot records known draft authorship, changes and confirmation separately in its provenance label; missing draft records do not establish authorship (`key_ideas_drafted_by`), and every decision on the snapshot binds it. See ADR-0013.
_Avoid_: abstract, description (the node's statement is what it claims; the summary is how the proof goes)
_Avoid_: .proof, proof store

**Trust rule**:
A standing verification the researcher declares in advance: any Imported result whose citation meets the rule's conditions counts as expert-verified without a verification of its own (computed, never written on the node). Declared and changed only by the researcher, on the proof map page, like every other Researcher decision; the declaration is the only record (one line per decision in the project's git-tracked `proofs/trust-rules.jsonl`: declare, amend, retire), no decision is written on the nodes it covers. A rule has an immutable name, a required rationale and one or more conditions, all of which must hold; several rules each count on their own. The conditions are a closed vocabulary: `source already reviewed` (another citation of the same reference at the same version carries the researcher's explicit verification, never another rule-covered node), `source_type in {…}`, `identifier has DOI`, `identifier has arXiv`. Never the node's own trust level, free text or library folders. A rule covers only Imported results the researcher created: one an agent created (its `created_by`, never the citation's) meets no rule and needs its own verification, since a rule vouches for the source, not for an agent's statement of it. An explicit decision on the node takes precedence, and sealed false is final regardless. The review page lists covered nodes in their own section, apart from what awaits the researcher, each with a button to verify it explicitly. Losing the rule (tightened or retired) is losing standing, nothing more: the import falls back to true and caps what rests on it, and verifications already made stay. `proof trust-rule list` and `show` read the rules; no CLI command writes one. See ADR-0014, ADR-0022, ADR-0025.
_Avoid_: auto-trust, policy, whitelist, auto-accept, Trusted by rule (as a state of its own)

**Promote**:
The researcher's explicit decision to change a Claim's kind to Lemma, marking it as independently reusable. Only possible once the Claim is expert-verified or sealed true; a node's kind is never automatically reassigned, and Promote does not currently support demotion.
_Avoid_: upgrade, generalize

**Evidence check**:
An automated or semi-automated check (a verifier, a checker) run against a specific Candidate proof, recorded as passed, failed, inconclusive, error, or stale. It is a check record: with the Verdicts and the mechanical checks, it is what the Proof layer is computed from, and it never verifies or seals a node. A checker records one with `proof node evidence record`, naming itself with `--run-by`; the node page shows who ran it. Each is bound to a snapshot SHA-256: a recorded check to the one its checker names (`--snapshot-sha256`, refused unless it is the snapshot's hash now), otherwise to the snapshot's hash at the moment of recording — what it was recorded against, not necessarily what the checker ran on. The node page and `node show --json` show each check's own bound hash, flag one whose snapshot changed since, and show a check from before binding as not bound. A computation node's Run in its studio records one only when it completes with the snapshot's frozen inputs, untouched throughout, and is bound to the snapshot its inputs matched; it then establishes the execution outcome of those inputs, never the frozen outputs (ADR-0015). `proof verify run` records none: it runs no backend, and is only logged against the legacy obligation, theorem or blocker it names, changing none of their statuses (#27). See ADR-0004.
_Avoid_: verification result, verify accept, experiment (that is fog's)

**Challenge** (质疑):
A doubt about a node, raised by an agent or the researcher, that takes effect at once with no review of it first; a sealed node cannot be challenged. Against the proof, it puts the Proof layer back to incomplete and only that node is reworked. Against the statement, it makes the Statement layer challenged as false and stops the work below every node that uses it directly; an agent's comes with a Counterexample, and both sides are then checked. It ends **fixed** (a passed Verdict says where and why), **withdrawn** (with a reason; any agent may withdraw an agent's Challenge, only the researcher the researcher's) or **superseded by a restatement** (recorded by the system), each in the Work log. The researcher's "not a problem" withdraws an agent's Challenge and, on a verified proof unchanged since, restores the verification. A Verifier's objection is a Challenge against the proof. See ADR-0025.
_Avoid_: dispute, refutation, rejection, dismissed (say withdrawn), resolved, upheld, bug, finding

**Counterexample**:
An ordinary node whose statement, its scope written into it, contradicts a challenged statement — for example "f(x)=x(1−x) is continuous on [0,1] and not monotone". A statement Challenge links to it; the link has no state of its own, and that the counterexample does not rest on its target is computed from the graph (ADR-0025).
_Avoid_: refutation, refutes (an Experiment's outcome), rebuttal

**Mathematical interface**:
The part of a node's content that other nodes actually depend on — its statement, assumptions, the Definitions it names (ADR-0020), and mathematical scope. Never its internal proof, proof strategy, or Evidence checks: a dependent relies on what a node says, not how it was shown. When it is unchanged, a dependent's pin follows the dependency's new version by itself; when it changed, the dependent's Verdicts go stale and its Proof layer is incomplete again. See ADR-0005, ADR-0025.
_Avoid_: statement (too narrow — assumptions and scope matter too), interface version, Accepted mathematical interface

**Researcher decision**:
A decision only the researcher makes — verifying, sealing true or false, unsealing, a "not a problem" that restores a verification, Promote; a Trust rule declared, amended or retired — as it is recorded: one line in the node's git-tracked `reviews.jsonl` (the project's `trust-rules.jsonl` for a Trust rule), naming the Review snapshot's SHA-256, the note and the time, committed together with that snapshot by the researcher. The commit's author, a GitHub identity, *is* the decider, and the pushed commit is the record of who decided what; outside git, or when the commit fails, it still takes effect, recorded locally as uncommitted. It takes effect only on the researcher's click on the proof map page, made directly or on the Coordinator's proposal; no CLI command and no agent makes one. That boundary is a convention for cooperative agents, not a security mechanism. See ADR-0010, ADR-0025.
_Avoid_: Review decision, Human Review, signed decision, confirmation, `--confirm`, approval flag, approved

**Home**:
The web app's first page: the researcher's proof projects, each a card read live from its own database (its id and folder, its theorem, its node, frontier, awaiting-verification and verified counts, the open fog, whether its page is being served, when it was last opened). Opening a card serves that project's Proof map page on the project's own origin and moves the browser there; the project page links back. Its list is one user-level file (`projects.json` in the proof-cli config directory), kept by `proof init`, `proof map open` / `serve`, and the Home's own Add existing, New project (as `proof init`) and Forget (the list only, never the folder); nothing scans the disk. Opened with `proof home`; one fixed localhost port, the same for every project. It writes nothing in any project. Served by the proof-web package (ADR-0018). See ADR-0017.
_Avoid_: dashboard, launcher, hub (the server object is `ProjectHub`; the page is the Home), project manager

**Proof map page**:
proof-cli's own local web page, the map's home, and the researcher's one entry into a project (reached from the Home, ADR-0017): the DAG and tree, the frontier, each node's five states and its conclusion, and the one place Researcher decisions take effect. Nodes are created on the page (right-click the canvas or a card) or with `proof node create`; the form shows the equivalent command. The Proof fog is a drawer beside the map, opened from the toolbar's Fog badge: the open items, each near the nodes it is about (lit up on the canvas on hover, never drawn on it), their newest Experiment, and the adds, drops, reopens and Experiments; Crystallize… on an item opens the same node form, preset to a Claim split from the item's one near node (#155). A theorem, lemma or claim opens in its **studio**, a LaTeX workspace built from prism-local's code with a node panel for the Assignee, split, request review, Challenge and Evidence check. An imported result opens on its own page. The page, its server and its commands (`proof home`, `proof map open`, `proof map serve`) are the proof-web package, over proof-cli's state (ADR-0018). See ADR-0008, ADR-0010, ADR-0011.
_Avoid_: review app (its ADR-0009 name), dashboard, admin panel

**Studio**:
A local node's page on the proof map page: the Proof agent's workbench, watched by the researcher. Its centre is the node's Work log — the run's plan, its role and step, and the oversight actions (Start, Pause, Resume, Stop and release, and Review what it has, which freezes a snapshot and, as any review request does, hands the node over) — and the editor and PDF, or a `computation` node's program and `out/`, are its Files view; a computation node's bar offers Run and Open in VS Code where a LaTeX node's offers Compile. It has a node panel for the node's states and dependencies, the review sheet for the researcher's decisions, and the Coordinator's input box, which knows the node; Redirect and Ask are merged into it (ADR-0025). While a turn runs, the Files view shows the agent at work (the lines it reads, the file as it writes it, the lines it changed), and a LaTeX node's agent compiles through the studio's own build. Its editor, build, PDF and agent panel are the latex-agent package, built from prism-local's code and knowing nothing of the proof map; proof-web serves one per node inside the map's own server and hands it the node's agent context and its run (ADR-0018). See ADR-0011, ADR-0015, ADR-0016.
_Avoid_: prism-local (the separate project it was copied from), editor window, LaTeX editor

**Proof agent**:
The agent run a node's studio starts and the researcher watches: one run is the node's Assignee under the project's agent name and works the node to a review request on its own, in a prove–verify cycle with Prover, Typesetter, Numerics and Verifier. A Reader states a draft as a map; a Decomposer splits a Theorem into Claims. It reads the whole project, the library folders `proof.toml` lists, and the web; it runs `proof` and computation; it writes files only in the node's folder, within each role's scope, and changes project state only through `proof`. It runs in the node's folder with `PROOF_ROOT` set to the project, on the Claude Code or the Codex CLI, with explicit permissions and none of the repository's own instructions. It reports its plan and each step with `proof node progress`, makes a choice it can make and records it as a Standing question, stops for a review request, a fact only a human can know, its budget or when stuck, and never makes a Researcher decision. Started once, from the map, the node page or the studio; paused, resumed or released by the researcher, and redirected through the Coordinator. Its roles and its run (the state machine) are the proof-agents package (ADR-0018). See ADR-0011, ADR-0016, ADR-0019.
_Avoid_: assistant, chat, agent panel (the panel is where it is watched), prompt-driven

**Prover** (a Proof agent role):
Finds the proof — retrieval first, then reasoning — and writes its structure as a draft in `scratch/`; decides when to split the node; review is requested only after the newest Verifier verdict passes the current working inputs — by the run itself, under its name, the moment that verdict stands with the checks passing, or by the Prover when the run's request is refused (ADR-0024 point 19); may raise a Challenge on a dependency that may not hold (`proof challenge open`), a statement Challenge with its Counterexample, and may withdraw an agent's Challenge with a reason; hands work to the Typesetter or Numerics and takes it back.
_Avoid_: solver, assistant

**Typesetter** (a Proof agent role):
Writes the Prover's draft as the node's LaTeX and its key-ideas summary, compiles and fixes it; never supplies a missing step itself — it reports the gap and the Prover takes it from there; never splits, never requests review.
_Avoid_: LaTeX assistant, editor

**Numerics** (a Proof agent role):
Writes and runs the computations — the candidate proof of a `computation` node, or evidence for a LaTeX one — and records what they showed as Evidence checks or Experiments; never edits the LaTeX.
_Avoid_: verifier (an Evidence check's checker), simulator

**Verifier** (a Proof agent role):
Reads the current proof against the statement and dependencies, and a challenged statement's proof against its Counterexample, and records a Verdict. It writes only under `scratch/verifier/`, never splits, never requests review and never makes a Researcher decision (ADR-0019, ADR-0025).

**Verdict**:
A passed or failed adversarial reading in the Work log, with a stable id, bound to the SHA-256 of the working inputs. Its objections are Challenges against the proof, numbered within it. The newest passed Verdict on the current inputs, with the mechanical checks passing (`Uses of dependencies` among them), puts the Proof layer at checks passed and permits an agent's request for review; a passed one that does not say, for each open objection of the previous version, where and why it is fixed is refused. The researcher's request remains ungated; a Verdict never verifies or seals (ADR-0019, ADR-0025).

**Uses of dependencies**:
The section after a proof in `proof.tex`, one `depuse` entry per dependency, each use an application with its Substitution, Premises, Conclusion and Constants. The mechanical check requires it complete; the Verifier checks each application (#256, #262).

**Attempt**:
An insert-only Work log entry naming what a proof approach tried to establish, its method and the obstruction. Failed Verdict objections and stuck steps also enter the next Briefing as attempts (ADR-0019).

**Briefing**:
The bounded context the run builds for each turn from statements with their assumptions and Definitions, the researcher's redirect, hand-off, Verdict objections, Challenges and the reasons for withdrawn ones, sealed nodes' seal notes, Attempts and shared Memory. Shared observations stay unverified. The researcher's working-input diff comes first when the inputs changed since the previous turn ended (ADR-0019).

**Coordinator**:
The project's one agent that parses the researcher's words, always listening while the map is open, with or without a Pursue; the studio's input box is the same Coordinator, knowing the node. What changes state it records as an action, writing "I read this as …"; when readings differ in consequence it asks first and changes nothing until answered; verifying and sealing it only proposes; an instruction for a node's agent goes to that node's next turn as a redirect. Inside a Pursue it controls a subtree: it starts frontier node runs within the parallel limit, retries within each node's remaining budget, starts a parent once every child is true, restarts stuck runs and parks nodes; outside one it hands out no work and asks whether to start a Pursue. Talking with it counts against no budget. It never makes a Researcher decision. Pause holds its runs at turn boundaries; Stop and release releases the runs it still owns (ADR-0019, ADR-0021, ADR-0025).
_Avoid_: controller, scheduler, chat, Ask

**Decomposer** (a Proof agent role):
Starts alone on a Theorem or Lemma with no children created by Split; ordinary dependency nodes are not children. It retrieves first and proposes a Split into Claims, with unresolved statements in the Proof fog. It adds the edges between its own Claims. Under a Coordinator its Split is the structure worked next; started alone, the Split stops the run for the researcher (ADR-0019, ADR-0021).

**Reader** (a Proof agent role):
States a draft in the library as a map: Definitions, Theorems and Lemmas, imported results with their references, and fog. It records where it departed from the draft and why, and proves nothing (ADR-0021). Its turn is kept with the project, as a node's turns are, though it works no node. Its runtime sets the reader role (`PROOF_AGENT_ROLE=reader`, no node role), under which `proof node create` refuses, on the parsed arguments, a Claim, `--parent` and `--reassign` (READER_ROLE_REFUSED); a statement's text is never searched (#203).
It identifies the draft's main result before creating nodes and reserves the project's one Theorem for it. Supporting local results are Lemmas regardless of their draft labels; literature results are imported results. Before making a supporting result a local proof task, it searches by its mathematical content even when the draft gives no citation. It checks the original source's assumptions, conclusion and normalisation, then records the queries, applicability, mismatches and access failures. Failure to locate a source does not establish novelty. It records supplied statements and conflicting targets as departures; a duplicate Theorem is reported, never worked around by downgrading the main result.
The Reader phase uses at most one quarter of the total minutes; cancellation preserves partial work and ends Budget without an automatic retry. Coverage does not identify the mathematical main theorem. See proposed ADR-0023.
_Avoid_: importer, parser, formalizer

**Pursue**:
The researcher's one action that sets the agents working to the end: a Coordinator on a Theorem, preceded by a Decomposer turn when it has no Claims, or by a Reader turn when started on a project with no map (ADR-0021). A project Pursue's steps are recorded as `pursuit` events, read by `proof project progress`; one with no recorded end reads interrupted, and nothing resumes it (issue #201). What it has spent is recorded as each turn ends, so an interrupted one reads back what it spent, as incomplete. A Pursue on one node's subtree is recorded the same way, naming its root: a restarted page reads its ending on that node, never as the project's own Pursue (ADR-0024 point 21). On a map that is already there, the page offers it once the map has a Theorem, with audit first when nodes await review (ADR-0024).
A Pursue has one total turn budget and one time limit, fixed at Start and shared by its Reader, Decomposers and node runs. Each node turn reserves one unit as it starts, so parallel runs share the total turn by turn; a node's own budget is a ceiling on its turns, never an allocation. The Reader runs alone before the node runs, and its actual turns are counted when that phase ends. A turn whose backend started consumes its unit even if Stop follows. A failed launch returns its reserved unit and is recorded separately. Cancellation before backend startup returns the unit without counting a turn or a failed launch (proof-agents#19).
On every Start, Project Pursue checks active local coverage before node runs. Parked and detached split Claims, nodes sealed false, and Off route nodes are historical routes, not coverage blockers; a Done ending names the Off route ones and the removal that took each off. An agent's local node outside every chosen Theorem's subtree ends the pursuit as Stuck, naming it, on every Start until someone wires, parks or deletes it. The researcher's own standalone work does not block: it is left outside this pursuit, and a Done ending names it. Done means the selected Theorem Coordinators ended Done, with no uncovered agent-made local nodes; another ending names the result that did not finish. This checks coverage and progress, not verification, and does not gate map edits on a Reader's notes. A Pursue reports per target, telling a statement that is false or challenged as false apart from a blocked proof route.
_Avoid_: autopilot, auto mode

**Audit first**:
A choice on a Pursue's Start (ADR-0024). Before anything else, each node Awaiting verification gets one independent Verifier turn, briefed as an audit, leaves first. Its verdict is recorded as an Evidence check on that snapshot.
An audit reads the proof afresh: its runtime (`PROOF_AGENT_AUDIT`) shows it no earlier Evidence check and, of the work log, only the Standing questions and their answers.
A node is audited once every node beneath it that the Start audits has been, and not while a failed one beneath it is still being reworked.
A failed audit stands across Starts: any Start, read off the record, works the failed nodes again first, and an audit Start does not audit them again (ADR-0024 points 17 and 18).
A snapshot whose audit passed, with nothing it rests on changed since, is not audited again unless the Start asks to (`reaudit`, "Audit all again, then Pursue").
A failed audit's objections are Challenges against the proof: the Proof layer is incomplete again and the node returns to the agents. A passed audit leaves the node as it is. An audit records no Challenge endings and never verifies; a sealed node is not audited.
A proof never restates a dependency's conclusion: conclusions are the map's, computed.
_Avoid_: re-review, second review

**Standing question**:
A choice a role made itself where the text admits more than one reading, recorded in the Work log with the alternative and bound to the statement's version, and answered by the researcher later, to the Coordinator; an answer that differs goes to the node's next turn as a redirect (ADR-0021, ADR-0025).
_Avoid_: blocker, needs-human (which is for what no choice settles)

**Parked**:
A node the Coordinator no longer starts: its run budget is spent, or its last run ended needing the researcher or was refused. Computed from the run records. The Coordinator goes on with the rest of the subtree; a parked node waits in the Review queue with its Attempts (ADR-0021). A Coordinator's ending with every open node parked is its own run record, not this. A re-split of a parked Claim's parent goes ahead, but while the parent still rests on the parked Claim the new Claims it made are not started (ADR-0024 point 20).
_Avoid_: stuck (a run's state), failed

**Review queue**:
Everything waiting on the researcher, ordered bottom-up: nodes Awaiting verification, imported results included, Unfixed agent-written text, Standing questions, Parked nodes, and the Challenges the Coordinator has asked the researcher to settle — only these last stop anything, and only their own branch (ADR-0021, ADR-0025). Off route nodes and imported results nothing rests on come last, each item saying why: history, kept and never hidden, that no route waits on (ADR-0023 point 4).
_Avoid_: inbox, approvals

**Off route**:
A node nothing on a live route rests on: a dependency removal took it off every route, or only such nodes rest on it. History, kept and never hidden; the agents do not work it (ADR-0023 point 4).
_Avoid_: dropped (a fog item's), abandoned, Rejected

**Decidable now**:
The part of the Review queue the researcher can verify or seal now. It is a view of the queue, not a separate queue or a workflow state. Inclusion does not mean that a decision has been made.

**Work log**:
A node's record of what its Proof agent did, in time order: the plan, each step, Verdicts, Attempts, Challenges and how each ended, the researcher's words with the Coordinator's reading of them, how each node run ended (done, stuck, budget, needs-human, released or release-failed, with why: the run's record of it, never a closing note's words), and Coordinator notes reported with `proof node progress`, merged with what they did through other `proof` commands — a split, a review request, an Evidence check, a fog item, a dependency edit — each with the role of the turn that did it, saying when that turn worked another node, and saying the role is unknown when no record ties the entry to one turn — and the turns themselves, each with its job, its backend session and the step it belongs to. Project state (events), never a file in the node folder; a turn's conversation, as its backend reported it, is kept beside it under `.proof/agent-turns/`. What the studio's centre shows.
_Avoid_: transcript (the conversation as its backend reported it, folded under a step), chat history

### Node state

A proof map node keeps five states, each read off its own record, never a cached status; everything else about it, its conclusion first, is computed from them, and every gate reads only them and what they compute (ADR-0025). Until ADR-0025's implementation lands, the code still has the three axes of ADR-0002 under the names each entry lists to avoid.

**Seal** (封存):
The researcher's absolute belief in a node: unsealed, sealed true or sealed false. Sealing true seals everything the node rests on with it — only the directly sealed node is recorded, with the set it rested on when sealed, so a node that comes to rest under it later is not sealed by it, and unsealing removes that seal's coverage, while a node sealed itself or covered by another true seal stays sealed; sealing false seals only the node. The agents never challenge or audit a sealed node and use it as known, briefed with the researcher's seal note. Set only by the researcher's click, after the system lists what it will do.
_Avoid_: lock, freeze, no longer callable (now sealed false)

**Statement layer** (命题层):
Whether a node's statement stands: unchallenged, challenged as false, or false. The agents change it through statement Challenges and their Counterexamples, the researcher by raising a Challenge.
_Avoid_: refuted, disputed, Rejected

**Proof layer** (证明层):
How far a node's proof has got: incomplete, checks passed (the newest passed Verdict on the current inputs, with the mechanical checks passing) or expert-verified (the researcher verified this version). A Challenge against the proof puts it back to incomplete. An imported result counts as checks passed until it is verified.
_Avoid_: workflow state, Review-needed, Revision requested, Accepted, acceptance state

**Verification** (验证):
The researcher's "checked, and I believe it", which makes a node's Proof layer expert-verified, for that version only; for an imported result, a judgement of its source rather than of a proof. A node may be verified before its dependencies. It lapses when an agent challenges the node, unless the researcher answers "not a problem" on the unchanged version, and is void, for good, when a direct dependency is later found false: unsealing that dependency restores nothing, only a new verification does. A false node further down only caps it, through its weakest dependency. Unlike a Seal, it leaves the node open to Challenges and audits.
_Avoid_: Acceptance, Reference review, accept, approve, review (as the decision)

**Assignee** (领取):
Who is working on a node, a researcher or an agent, as a wayfinder ticket's assignee: a planning signal that tells others to skip the node, never a lock. It doesn't gate editing the working file and carries no token; one per node, it ends when its holder requests review or releases it, and a stale one is simply reassigned or cleared. See ADR-0006, ADR-0010.
_Avoid_: claim, claimed (Claim is a node kind), lock, lease, in progress

**Run state** (运行):
Whether the agents are working: running, paused or not running. Set by the system. How a node run ended (done, stuck, budget, needs-human, released, release-failed), and how a Coordinator or a Pursue ended (parked and interrupted too), is a run record, always named with what ended, not a Run state.
_Avoid_: status, active

**Conclusion** (结论):
What a node's states say about it, computed and never kept: verified true, true, uncertain or false. Sealed true is verified true and sealed false is false. Otherwise a false statement is false; a statement challenged as false, or an incomplete proof, is uncertain; checks passed is true; expert-verified is verified true. A conclusion is never above the node's weakest dependency: a true dependency caps it at true, an uncertain one makes it uncertain until the dependency recovers, and a false one makes it uncertain, not false, until it has a proof that does not use it.
_Avoid_: status, standing, trust, Provisional, Conditional, Blocked, Potentially stale, integrity state

**Awaiting verification**:
A node whose conclusion is true but not verified true: checks passed, not expert-verified, unsealed. Computed; what the Review queue lists first.
_Avoid_: awaiting review, review-needed, pending review

**Unfixed**:
A statement or Definition no verification or Seal has yet relied on. The researcher may restate any unfixed text, an agent only what an agent wrote (never a Definition a node of the researcher's names); a restatement is a work-log event and makes the Verdicts on it and on what rests on it stale. The first verification or Seal of it, or of a node whose verified or sealed snapshot rested on it, fixes it, for everyone (ADR-0021, ADR-0025).
_Avoid_: draft (a draft is the researcher's LaTeX), editable

**Split**:
Decomposing a Theorem, Lemma, or Claim into new Claim nodes that become its dependencies, so each can be worked and verified independently. Not gated by review — it proposes work structure, not a mathematical result — so any agent or collaborator may do it, except that a node with another Assignee is theirs to split unless it is taken over (`--reassign`), which makes the splitter its Assignee. A split is all or nothing: if any new Claim can't be created, none is, and the parent is left as it was. Splitting doesn't resolve the parent: once its new dependencies are true, the parent still needs its own Candidate proof (even a short one), combining them, checked like any other. A parent's existing dependencies aren't automatically reassigned to the new children; only a person or agent explicitly moving one decides that (`proof node depend <parent> --move <dependency> --to <child>`, which also adds or removes an edge; the same Assignee and sealed-node rules apply, and the pins are taken at the next request-review). A new Claim may name dependencies of its own, which may not rest on the node being split. Split doesn't apply to an Imported result (nothing to decompose) or a node sealed false (pursue a new node instead of reviving that one). A node produced by a split records which node it was split from, in `derived_from`.
_Avoid_: decompose (fine informally, but keep decisions and CLI/agent protocol on "split"), break down

**Search route**:
One possible way to prove a statement, recorded through attempts and memory; alternative search routes are choices, while a proof map node's dependencies are the premises required by its chosen proof.

### Publication

A claim's way into a paper runs on two tracks that never feed each other (#30). The **mathematical track** is the node's own conclusion, computed live; publication never writes it. The **editorial track** is Editorial readiness. Nothing on either track is derived from the other: verified true never makes a claim paper_ready, and paper_ready never verifies a node.

**Editorial readiness**:
How far a claim has got towards a paper: internal_draft → collaborator_ready → supplement_ready → paper_ready, or withdrawn. It is editorial, not a Researcher decision, so any agent or collaborator may set it with `proof publication set`, and every output labels it editorial. The allowed moves are one step forward or back, withdrawn from any state, and withdrawn → internal_draft to start again; re-setting the current state (to edit a claim's details) is always allowed. Anything else fails with `INVALID_READINESS_TRANSITION`. Only a node whose conclusion is verified true may be put at supplement_ready or paper_ready (`PUBLICATION_NOT_ACCEPTED`); a theorem contract has no conclusion, so its claim never gets there (`PUBLICATION_NO_ACCEPTANCE_AXIS`). A ready claim whose node later stops being verified true, for example because a Challenge was raised, is **withheld** from the paper and supplement exports and listed with the reason. The retired values migrate when a claim is loaded: `disputed` and `blocked` become internal_draft (the node's own states now carry those facts), and `superseded` becomes withdrawn; the claim keeps `migrated_from` and a note.
_Avoid_: publication status, approved (for readiness), paper-accepted

**Release record**:
An editorial note that a bundle went out to an audience (`proof publication release`, `proof publication withdraw`). `--approved-by` names who said so; it is not a Researcher decision. A release sign-off on record is the author of the git commit that releases it (the ADR-0010 pattern), with no mechanism of its own.
_Avoid_: release approval (as if it were a review decision), sign-off record
