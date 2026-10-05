# Development plan: the proving framework after ADR-0019

Drafted 2026-10-04. Decision: `docs/adr/0019-the-run-is-a-prove-verify-loop-over-the-map.md` (proposed). This plan says what is built where, in what order, and fixes the interfaces between the three repositories so the work can run in parallel.

## Where the code is (as of today)

| repository | path on this machine | what it holds | state |
|---|---|---|---|
| proof-cli (core) | `~/proof-cli` | `proof_cli`: domain (`AgentRole`), `proof node progress` and the work log (`proof_map.record_progress`, `work_log`), snapshots and input digests (`vault`), Evidence checks, memory, retrieval; `packages/latex-agent` (the studio, standard library only) | master `7ed8e4b`, 1005 tests |
| proof-agents | `~/proof-agents` | `proof_agents.proof_agent` (roles: brief, permissions, write scope; `ProofAgentContext`) and `proof_agents.agent_run` (`AgentRun`, `RunHooks`: the state machine) | `9c5daca`, 6 tests (state machine only) |
| proof-web | `~/proof-web` | `proof_web.studios.StudioHub` wires one `Studio` per node with `ProofAgentContext` and `AgentRun(agent, RunHooks(...))`; `server.py` routes; `static/studio/` run pane (`run.js`) and fragments | `c53ea8e`, 31 test files |

Dependencies point one way: proof_web → proof_agents → proof_cli; latex_agent → nothing. A role's turn is one `AgentManager.start(...)` job (latex-agent); one job per studio, one studio per node, so **parallelism is across nodes, never within one**.

What exists that ADR-0019 builds on:

- `record_progress` writes `agent_progress` events with `kind` ∈ plan | step | handoff; `work_log` merges them with splits, review requests, Evidence checks, fog, experiments, dependency edits and claims, and passes a progress payload through unchanged, so new kinds need no merge code.
- `vault.working_inputs_digest(root, node_id, medium)` is the SHA-256 a Review snapshot's manifest would have for the folder as it stands; a snapshot's `frozen_inputs_digest` is the same function on the frozen files.
- `record_evidence_check(store, candidate_proof_id, outcome, notes=, run_by=, snapshot_sha256=)` already binds a check to a snapshot's hash.
- Memory already has `layer` (working | semantic | episodic | procedural) and `status` (stable | tentative | failed | tactic), scoped by `--node-id`; `node_scope_memory` and `list_memory_artifacts(status=, node_id=)` read it; `retrieval.retrieve_candidates` ranks by text.
- `AgentRun` already records every turn (`record_turn`, `transcript`), computes the turn's `changed` files from the agent manager, and ends on review-requested, stuck, budget, or `STUCK_TURNS` turns without change.

## Phases

**Phase 1 — the Verifier, the verdict gate, the record and the briefing** (ADR-0019 parts A and B, point 21 of D in its hash-only form). Three repositories, two waves. This phase alone closes the trust gap the ADR names: nothing reaches review from the agent unread.

**Phase 2 — sharing across nodes** (part C). Typed memory writes in the Prover's and Verifier's briefs; the briefing's shared section (dependencies and dependents, siblings, `proof retrieve`); the suggested-redirect surfaced from repeated objections (point 17). Mostly proof-agents and proof-web hooks; the core gains `proof_map.siblings` and `dependents` if phase 1 did not.

**Phase 3 — the Coordinator** (points 18–19). A new object in proof-agents (`coordinator.py`) over several `AgentRun`s, started from a Theorem's page; `[studio] parallel`; its researcher actions; proof-web routes and a pane on the Theorem's page. Needs the hub to start node runs without a page open on each node.

**Phase 4 — the Decomposer** (point 20) and the researcher's edits as a diff in the briefing (point 21 in full). Small once phases 1–3 exist.

Not planned (ADR-0019 part E): a population of Provers on one node, the round verifier, graded verdicts.

## Phase 1 in detail

### Wave 1 — proof-cli (core), branch `feat/0019-verdict-attempt`

1. `domain.AgentRole` gains `verifier` and `decomposer`; `AGENT_ROLES` follows. Every message that lists the roles (`record_progress`'s errors, the CLI help) is derived from `AGENT_ROLES`, not spelled out.
2. `record_progress` gains two kinds, both `agent_progress` events on the node, both insert-only:
   - **verdict** — `proof node progress <node> --verdict passed|failed [--note "<objections>"]`. Payload `{"kind": "verdict", "role", "by", "outcome", "note", "inputs_sha256"}`, where `inputs_sha256` is `vault.working_inputs_digest` of the node folder at record time (the node's Medium decides which files). Only the `verifier` role may record one (`VERDICT_ROLE_REQUIRED`); an outcome outside passed | failed is `INVALID_VERDICT`; a failed verdict needs a note (`OBJECTIONS_REQUIRED`).
   - **attempt** — `proof node progress <node> --attempt "<what it tried to establish>" [--method "<how>"] --failed-on "<the objection or obstruction>"`. Payload `{"kind": "attempt", "role", "by", "goal", "method", "failed_on"}`. Any role; `--attempt` without `--failed-on` is `ATTEMPT_INCOMPLETE`.
   - The three new codes join `errors.py`; the `--json` envelope test covers them.
3. Read side: `proof_map.verdicts(store, node_id) -> list[dict]` (newest last) and `proof_map.latest_verdict(store, node_id) -> dict | None`; `proof_map.attempts(store, node_id)`. `proof node progress <node>` (no flags) and `rendering.py` show a verdict as `verifier: passed|failed — <note>` and an attempt as `attempt: <goal> (<method>) failed on <failed_on>`.
4. `proof_map.dependents(store, node_id)` and `proof_map.siblings(store, node_id)` (the other dependencies of each node this one is a dependency of), for phase 2's briefing; small, and natural to add beside `list_nodes`.
5. Tests: `tests/test_progress.py` (service and CLI, the hash bound to the folder's state, the role rule, the error codes), `tests/test_json_envelopes.py` for the codes, `tests/test_cli_contract.py` if it lists commands.

### Wave 2a — proof-agents, branch `feat/0019-verifier-briefing` (after wave 1 is importable)

1. `proof_agent.ROLES` gains **verifier**: brief as ADR-0019 point 1 (adversarial; objections numbered, each naming the step or citation; records `--verdict`; may run computation to check a claim; may open a Challenge; never splits, never requests review); writes `./scratch/verifier/**`; `proof` commands: the reads, `proof node progress *`, `proof challenge open *`, `proof challenge list *`; programs: `COMPUTATION`. The Prover's brief gains: close an abandoned line with `--attempt … --failed-on …`; hand to the Verifier when the draft is complete (`--handoff verifier`); request review only after the Verifier passed this version. The Typesetter's brief is told the Verifier reads what it writes.
2. **The gate.** `ProofAgentContext` gains `may_request_review: bool = False`; `claude_args` includes `Bash(proof node request-review *)` for the Prover only when it is true; the brief says the same for Codex. The run sets it from the newest verdict: outcome passed and `inputs_sha256 == hooks.inputs_digest()`.
3. **The cycle.** `_next_role`: a hand-off wins; else after a Typesetter turn whose `changed` includes a `.tex` file → verifier; after a verdict → prover; else prover (as today). A single role asked for still means one turn.
4. **The briefing.** New module `briefing.py`: `build_briefing(parts: BriefingParts) -> str`, pure, tested on its own. Sections in the ADR's fixed order: node statement and dependencies (from `hooks.node_brief()`), the researcher's redirect, the last hand-off or report, the newest verdict's objections, attempts newest first (capped), "the working inputs changed since the last turn" when `hooks.inputs_digest()` differs from the digest recorded at the previous turn's end, shared notes (from `hooks.shared_notes()`, each marked with its node and *unverified*; phase 1 passes them through, phase 2 fills them). A role-dependent order: the Verifier gets the objections and dependencies first, the Prover the attempts first. A size cap, with the oldest attempts dropped first.
5. **The Evidence check.** When a turn ends with a `review-requested` event and the gating verdict's hash is known, the run calls `hooks.record_evidence(candidate_proof_id, "passed", run_by=f"{name}/verifier", notes=verdict_note, inputs_sha256=verdict_hash)`; the hook returns whether it recorded (it compares the hash with the snapshot's own and refuses silently on a mismatch). The run writes nothing itself.
6. `RunHooks` grows **optional** fields, default `None`, so proof-web's wiring and every existing test keep working: `inputs_digest: Callable[[], str | None]`, `node_brief: Callable[[], dict]` (`{"statement", "dependencies": [{"id", "statement", "accepted": bool, "key_ideas": str | None}]}`), `shared_notes: Callable[[], list[dict]]`, `record_evidence: Callable[..., bool]`. `RunState.view()` gains `verdict` (the newest outcome) for the pane.
7. Tests (fake agent whose turns "report" by appending to a fake work log): the Verifier follows a Typesetter turn that changed `.tex`; a failed verdict sends the work back to the Prover with the objections in the prompt; the Prover's turn carries the request-review permission only after a matching passing verdict; the hash mismatch drops the gate; the Evidence check is asked for exactly once on review-requested; the briefing's order, caps and *unverified* marks.

### Wave 2b — proof-web, branch `feat/0019-run-hooks` (in parallel with 2a, against the contract above)

1. `StudioHub` wires the four new hooks: `inputs_digest` → `vault.working_inputs_digest(root, node_id, medium)`; `node_brief` → the node's statement, each dependency's statement, acceptance state and current key ideas; `shared_notes` → phase 1: the node's own `node_scope_memory` entries with `status` ∈ failed | tactic | tentative, as `{"node_id", "status", "text", "by"}`; `record_evidence` → compares `inputs_sha256` with the candidate proof's `frozen_inputs_digest` and calls `record_evidence_check(..., snapshot_sha256=)` when equal, returning the result.
2. The run pane (`static/studio/run.js`, its fragment) renders `verdict` entries (outcome, objections, who) and `attempt` entries (goal, method, failed on) in the work log; the node section shows the newest verdict beside the role and step; the map's claimed-node label gains the Verifier's glyph where roles are shown (`status.js`).
3. Tests: `test_agent_run.py` and `test_studio_run.py` run a node through a Verifier turn with the fake backend; `test_run_pane.py` for the two new entry kinds; a hash-mismatch case where no Evidence check is recorded.

### Order and parallelism

```
wave 1   proof-cli core ─────────────┐
                                     ├─ wave 2a proof-agents ──┐
                                     └─ wave 2b proof-web ─────┴─ integrate: proof-web's tests against both branches
```

Wave 2b can begin on the pane (its point 2) at once; its hooks (point 1) need 2a's `RunHooks` fields, which this document fixes, so the two run in parallel and meet at integration. Each branch carries its own tests and commits; nothing is pushed or merged without the researcher.

### Done when

- A run on a LaTeX node goes Prover → Typesetter → Verifier → Prover → request-review, with a passing verdict in the work log and an Evidence check on the snapshot that names `<agent>/verifier`.
- A failed verdict's objections are the first thing the next Prover turn reads, and the Prover's turn cannot request review until a new passing verdict matches the folder.
- Stop, Start: the new Prover's briefing lists every earlier attempt.
- The researcher's Review what it has, and their own request-review on the page, work exactly as before, verdict or none.
- `pytest` passes in all three repositories.

## Phase 2 in detail (built 2026-10-05: branch `feat/0019-sharing` in each repository, stacked on phase 1's branch there)

### proof-cli (core)

1. A memory entry's `source` is free text: a run's role tags what it learned with `--source <agent>/<role>` (ADR-0019 point 8); the CLI's `memory add` help says so and what the three learned statuses mean.
2. `retrieval.retrieve_memory(store, query, *, limit, statuses, exclude_node_ids)` ranks memory entries by the words of a query, best first and newest among equals; `proof retrieve --json` carries the hits as `memory` beside its candidates (point 14).
3. Tests: `tests/test_memory_sharing.py`.

### proof-agents

1. The Prover's and the Verifier's briefs: what was learned, as against what was tried, goes to this node's memory — `proof memory add "<it>" --node-id <node> --layer episodic|procedural|semantic --status failed|tactic|tentative --source <name>/<role>` — and never another node's (points 8, 12); other nodes' notes are unverified and a result needed from another node is a Claim both depend on (point 11); a split-out Claim a sibling could use is left as a memory entry (point 15). The permission is `MEMORY_WRITE`, `Bash(proof memory add --node-id {node} *)`, with the node filled in per turn by `ProofAgentContext.claude_args`.
2. `briefing.py`: a shared entry carries its `relation` to the node (dependency | dependent | sibling | retrieved) and a `progress` entry says where a neighbouring node stands (points 13, 14); `SHARED_SHOWN` is 12.
3. `patterns.py`: `suggested_redirects(log, shared)` reads the record for the same objection in three failed verdicts and for a dead end this node hit that another node's memory holds. `AgentRun._suggest` records each once in the work log, after the turn that completed the pattern, as a progress note `suggested redirect: …` under the turn's role and name; `RunState.suggestion` (in `view()`) carries the newest for the page (point 17). No role is briefed with it; nothing is reallocated by it.
4. Tests: `tests/test_patterns.py`; additions to `tests/test_briefing.py` and `tests/test_prove_verify_loop.py`.

### proof-web

1. `StudioHub._shared_notes`, in the subscription order, each source bounded (`OWN_NOTES` 4, `NEIGHBOUR_NOTES` 2, `RETRIEVED_NOTES` 4): the node's own learned entries; each dependency's and dependent's, with its standing (`_standing`: its claim, its step of its plan, its last verdict — project state already there); each sibling's; then `retrieve_memory` by the node's statement, leaving out the nodes already covered.
2. The run pane shows `The record suggests: …` with a *Use as redirect* button that puts it in the redirect box while the run is active; only the researcher sends it.
3. Tests: additions to `tests/test_run_hooks.py` and `tests/test_run_pane.py`; `tests/test_agent_run.py`'s rule check reads a rule that names an option.

### Left to later phases

- The Coordinator's redirect when a dependency is Accepted (point 19) is phase 3; a Decomposer's turn and the researcher's diff in the briefing (points 20, 21 in full) are phase 4.
- On Codex the memory-write scope is the brief's rule, as every scope is there (ADR-0010).

## Phase 3 in detail (built 2026-10-05: branch `feat/0019-coordinator` in each repository, stacked on phase 2's)

### proof-cli (core)

1. `record_progress(..., coordinator="<note>")` and `proof node progress <node> --coordinator "<note>"`: a `coordinator` entry on a node's work log, with no role (a Coordinator holds no node and takes no turn); `rendering.py` shows it as `coordinator: <note>`. The Coordinator's refusal codes join `errors.py` (`NO_SUBTREE`, `COORDINATOR_ACTIVE`, `NO_COORDINATOR`, `NOT_PAUSED`, `NOTHING_OPEN`, `COORDINATOR_REFUSED`).
2. Tests: `tests/test_progress.py`.

### proof-agents

1. `coordinator.py`: `Coordinator(hooks, root)` over several `AgentRun`s, with `CoordinatorHooks` (`subtree`, `run`, `budget`, `parallel`, `agent_name`, `record`), a `CoordinatorState` and `view()`. Its loop looks at the subtree every `TICK`: it starts node runs on the frontier within the subtree — the open nodes, which is the core's frontier rule, so the parent is startable once every child is Accepted — up to `parallel` at a time; restarts a node whose run ended on a failed verdict (`stuck` or `budget`, the newest verdict `failed`) while the node budget (one Start's turns) is not spent; redirects the running dependents of a newly Accepted node once, with its statement and key ideas (point 19); and ends when the root is requested for review or Accepted, when its budget (the node budget × the open nodes at Start) is spent, or when nothing runs, nothing can start and no node waits for review (every open node is stuck). A node waiting for review is not stuck: it holds the Coordinator waiting. Actions: `start(provider)`, `pause()` (no new run; the running ones pause after their turn), `resume()` (only the runs Pause held), `release()` (every run it started). Every action and ending is a `coordinator` note through `record`.
2. `proof_agent.parallel(root)`: `[studio] parallel`, default 2.
3. Tests: `tests/test_coordinator.py`, with fake runs and a subtree the test moves along.

### proof-web

1. `StudioHub.coordinator(root)` (one per root, made on first use; refused for an imported result or a node with no dependencies), `_subtree` (the root and what it rests on, transitively: Accepted or Reference-reviewed, the workflow axis, the claim, the key ideas once Accepted, whether a run can work it), `_run_of` (the node's run through a studio made on demand: no page needs to be open), `coordinator_action`, `coordinator_view` (with the subtree's counts and the parallelism), `coordinator_state` (for the map while active), and `_record_coordinator` (the note on the root's log). `close()` releases a Coordinator at work first.
2. Routes: `GET /api/node/<id>/coordinator`, `POST /api/node/<id>/coordinator/<start|pause|resume|release>`; the map's node payload carries `coordinator` while one is active.
3. The run pane: a *Subtree* card above the node's own run on a node that rests on others — Start subtree; while it works, where it stands (the runs on, accepted of total, turns of budget), Pause/Resume subtree, Stop subtree; a `coordinator` note in the work log.
4. Tests: `tests/test_coordinator_hub.py` (the stub Claude Code works T over A and B one at a time, the root once both are Accepted; Stop and release releases the run it started), `tests/test_run_pane.py`.

### Left to phase 4

- The Decomposer's turn (point 20) and the researcher's diff in the briefing (point 21 in full) — built, below.
- A Coordinator's state lives in the page's process, as a run's does; its notes on the root's log are its record across a restart.

## Phase 4 in detail (built 2026-10-05: branch `feat/0019-decomposer` in each repository, stacked on phase 3's)

### proof-cli (core)

`AgentRole.decomposer` has been in the domain since phase 1, `proof node progress` reports under it, and `--status needs-human` is the step status the run already stops for (ADR-0019 point 20, as amended). The run's two new refusal codes, `ROLE_ALONE` and `NOT_DECOMPOSABLE`, join `errors.py` (with `RUN_GONE`, a Coordinator's from phase 3 that had escaped the registry); nothing else changes here.

### proof-agents

1. **The Decomposer** (point 20). `ROLES["decomposer"]`, a `Role` with `alone=True`: its brief reads the library and the literature first, splits the node into the Claims the course of the proof needs (`proof node split … --created-by <name>`, one call), puts what it cannot yet state in the fog near the node, keeps its notes under `scratch/decomposer/`, and ends with exactly `proof node progress <node> --step 1 --status needs-human --note "structure proposed; the researcher decides"` — or, when the node is one argument after all, says so and splits nothing. Its `proof` commands are the reads, `proof fog add` and `proof node split <node>` — the rule names the node, filled in per turn like the memory rule, so it splits the node it works and no other (audit P1: the unbound `proof node split *` let it split another node and take it over with `--reassign`); the Prover's `split` and `depend` rules and every role's `progress` rule are bound the same way, and `--root` on any `proof` command is denied to every role (`NO_OTHER_PROJECT`). It writes `./scratch/decomposer/**`; it runs no program; it never requests review, never edits an edge, never hands off. `CYCLE_ROLES` is every role with a brief but one started alone: a whole run never gives the Decomposer a turn and a `--handoff decomposer` hands to nobody.
2. **The run's side of the stop.** A Start naming the Decomposer with any other role is refused (`ROLE_ALONE`). A Start naming it alone is refused (`NOT_DECOMPOSABLE`) when the node brief's `kind` is not `theorem` or `lemma`, or when the node has children — the Claims a split made, which the brief marks `split_child` (ADR-0019 point 20's "no children": a Theorem resting on an ordinary premise, Accepted or not, is still the Decomposer's; a host whose brief does not mark children is read as if every dependency were one); a host whose brief has no `kind` refuses nothing on kind. After a Decomposer turn that recorded a split and no `needs-human` step of its own, the run ends `needs-human` anyway (`structure proposed (<n> Claim(s): …); the researcher decides`) and leaves that as its closing note: the human stop is the run's, not the brief's. A decision — the role's own `needs-human`, or the Decomposer's split — is read before the budget (audit P2-2): a turn the time budget stopped still ends `needs-human`, its reason saying the budget ended it. *Implementation choice:* the ADR's point 20 says "a Theorem"; the Decomposer accepts a Lemma too, as the Coordinator (point 18) does, since the one proposes the structure the other works.
3. **The researcher's diff** (point 21 in full). `RunHooks.working_inputs: Callable[[], dict]` — one read of the working inputs, `{"digest", "files": {path: text, or bytes for a file that is not text}}` — optional like the other ADR-0019 hooks. The digest and the text come from the same read (audit P2-3: read apart, an edit landing between them left a baseline of old digest and new text, and the next turn said only that the inputs changed); when the hook is there the run takes both from it, before and after each turn, and `inputs_digest` serves the gate and the verdict's staleness as before. At each turn's end the run keeps the text with the digest (`_Start.inputs_text_after_turn`); at the next turn's start, when the digest differs, it diffs the two (`briefing.inputs_diff`: a unified diff per file, added and removed files named, a file that is not text compared by its bytes and named as changed, added or removed — audit P2-4 — cut at `DIFF_SHOWN` 2500 and marked). `BriefingParts.inputs_diff` heads the briefing for every role — "The researcher changed the working inputs since the last turn ended … the Verifier reads the changed steps as adversarially as any other, and the Prover does not revert them" — ahead of the verdict and the node; without the hook the hash-only sentence of phase 1 is said, and heads the briefing too. The diff is of one Start: across Stop and Start the next first turn reads the files as they are.
4. Tests: `tests/test_briefing.py` (the diff heads every role's briefing, file by file, its cap), `tests/test_prove_verify_loop.py` (the diff between two turns and the fact without the hook; the Decomposer alone, its refusals, its forced stop, the cycle without it, its permissions).

### proof-web

1. `StudioHub._node_brief` carries `kind` and marks each dependency `split_child` (its `derived_from` is this node); `_working_inputs(node_id)` reads exactly the files `_inputs_digest` hashes once (`read_working_snapshot`) and gives their digest with each file as UTF-8 text, or its bytes where it is not text, and raises where the digest would (an unreadable folder, a link), so the run says the inputs changed and no more. Both are passed as hooks only where this proof-agents has the fields.
2. The run pane: on a Theorem or Lemma that rests on nothing and is unreviewed, *Propose a split* beside *Start agent* (it reads the node's own payload when no run is on), which starts the Decomposer alone; a hint says what it does. The Decomposer's stop reads as every needs-human stop does: *Needs you: structure proposed …*. The role select already offered *Decomposer only*.
3. Tests: `tests/test_run_hooks.py` (the kind and the split children, one read's digest and text, the binary file as bytes), `tests/test_run_pane.py` (the offer and where it is withheld), `tests/test_agent_run.py` (the stub Claude Code splits T into T1 and T2 through `proof` and the run stops needs-human with the claim kept, under a split rule bound to T; a Claim, a split node and a Start with the Prover are refused; a Theorem resting on an Accepted premise but never split is accepted; an edit of proof.tex while the run is paused heads the next turn's prompt as a diff). The rule-to-command check reads `{node}` as the per-turn fill it is.

### Done when (phase 4)

- Start → Decomposer on a Theorem not yet split ends with the Claims on the map and the run stopped for the researcher; Start with any other role, or on a Claim or a split node, is refused before the node is assigned.
- An edit of the working inputs between two turns of one Start is the first thing the next turn reads, as a diff; the Verifier's verdict on the earlier version is stale as before.
- `pytest` passes in all three repositories, the core's CLI contract included (proof-web's port-binding tests excepted where a sandbox forbids binding).

### Audit of phase 4 (2026-10-05)

Four findings, all fixed on the same branches: P1, the Decomposer's unbound split rule (every node-acting rule now names the node; `--root` denied); P2, the budget read before the decision; P2, the digest and the text read apart; P2, a binary file compared as None. The audit also read ADR-0019 point 20's "no children" against this plan's "no dependencies": the plan now follows the ADR (`split_child`).
