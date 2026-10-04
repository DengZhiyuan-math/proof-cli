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
