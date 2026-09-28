# Agent execution protocol: exclusive claims, a unified command surface, a JSON contract

**Status**: accepted; amended by ADR-0010 (submit is "request review" on a snapshot; a claim is a plain assignee, no token)

Every prior decision in this map (ADR-0001 through ADR-0005) fixed the domain model. This one (issue #13) fixes how an agent is allowed to touch it: what a claim actually guards against, what commands exist and how they're grouped, what "the JSON output" concretely looks like, and how "split before you hallucinate a proof" is enforced given the system cannot itself judge whether a proof is too large or too weak. Twelve invariants:

1. **Active claim is exclusive and atomic.** At most one active claim exists per node at a time. A claim record is `{claim_id, node_id, claimant_id, session_id, claimed_at}`; the exclusivity is enforced by a SQLite transaction/unique constraint, not a queue.
2. **Claim conflicts fail fast.** A second claimant gets an immediate, structured `CLAIM_CONFLICT` error carrying the existing claim's basic info (who holds it, since when) — enough to decide what to do next without a second lookup — rather than blocking or queuing.
3. **Repeating the same claim, from the same claimant and session, is idempotent.** It returns the existing claim rather than erroring, so a retried CLI call (network hiccup, agent retry logic) is safe.
   - *Updated by ADR-0009 (#37):* the repeat returns the claim without its token. Only the token's hash is stored, and handing it out again to whoever names the claimant and session would let anyone take the claim. A claimant that lost its token can't submit, so the node needs a force-release in the review app.
4. **Claims never expire automatically.** A long-running research session is a legitimate reason for a claim to sit for hours; a TTL would misfire on real work as often as it catches a stuck one. A display-only age hint (e.g. "claimed for 19h") may exist later, but it never changes state on its own.
5. **The claimant may release their own claim; only the researcher may force-release someone else's.** `proof node release <id>` releases the caller's own active claim. `proof node release <id> --force` is Human authority, and always writes an event recording who forced it, which claim, when, and why — never a silent override.
   - *Updated by ADR-0009 (#37):* the claimant proves ownership with the claim token `claim` returns, not by naming itself; `--force` is a signed decision in the review app, and the CLI answers `HUMAN_REVIEW_REQUIRED`.
6. **All node actions live under one command group, `proof node ...`** (`claim`, `release`, `submit`, `split`, `challenge`, `show`), reflecting that ADR-0001 already unified Theorem/Lemma/Claim/Imported result into one entity. This also sidesteps a real naming collision: spreading these across the old `theorem`/`obligation`/`blocker` groups would put `claim` under a group named after a concept (`obligation`) that CONTEXT.md already retired in favor of Claim.
7. **Human-readable output is the default; `--json` is the stable machine contract**, not just a formatting toggle. In `--json` mode: stdout is exactly one JSON document; no Rich markup; no interactive prompts; failures are also structured JSON, not just a message; every failure pairs a stable error code with a non-zero exit code; every response — success or failure — is wrapped in an envelope carrying a `schema_version`. For example:
   ```json
   {"schema_version": 1, "ok": true, "command": "node.claim",
    "data": {"node_id": "lemma_17", "claim_id": "claim_42"}}
   ```
   ```json
   {"schema_version": 1, "ok": false,
    "error": {"code": "CLAIM_CONFLICT", "message": "Node is already claimed",
              "node_id": "lemma_17", "active_claim_id": "claim_41"}}
   ```
8. **Only the active claimant may normally submit.** Anyone else calling `submit` on a node they don't hold the claim for — including no claim at all — fails with `CLAIM_OWNERSHIP_MISMATCH`. A researcher who needs to submit on someone else's behalf uses an explicit override path, never a silent bypass of the ownership check.
   - *Updated by ADR-0009 (#37):* `submit` needs the claim token; there is no CLI override path.
9. **Every submission records an explicit decomposition rationale, permanently, as Candidate-proof metadata** — not a separate event log entry a reviewer has to go dig up. The system cannot judge whether a node should have been split further (no kernel, no way to assess mathematical scope automatically), so it doesn't try to. Instead `submit` requires a `--split-rationale` argument, always present, asserting *why* this node is appropriately scoped to prove directly right now: "I considered further decomposition and am asserting this node is appropriately scoped, for this reason" — never "the system verified this is appropriately scoped," which isn't a claim proof-cli can make. An agent that judges a node still needs decomposing calls `split` instead of `submit`.
10. **Submit closes the active claim and hands the node to review-needed in the same action.** This tightens ADR-0002/#6's "any review decision ends the claim": since a review decision always comes strictly after submission, and the workflow-state derivation already stops showing `claimed` the moment a candidate proof is awaiting review, the claim is — and always was — already over by submit time. This ADR makes that precise rather than leaving it to be inferred: ownership moves from agent execution to Human Review at `submit`, not when the review decision eventually lands.
11. **Adapters call the same application/service operations the CLI does.** The Codex plugin, Claude Code adapter, and any future web app surface are all thin callers of one underlying layer — never a separate path that could reach the domain model without going through it.
12. **No agent-facing command can change acceptance state.** `claim`/`release`/`submit`/`split` and opening a `challenge` are all agent-reachable and none of them are Human Review actions; this is ADR-0004's Invariant 1 restated as a constraint on the command surface itself, not just on the domain functions underneath it.
   - *Updated by ADR-0009 (#37):* no CLI command at all — agent-facing or not — can make a Human Review decision. Those commands return `HUMAN_REVIEW_REQUIRED` with the review app's URL; decisions are signed there.

**Challenge gets its own command surface, not just a flag.** `proof node challenge <id> ...` opens a Challenge against a node (ADR-0005, Rule 4 — ungated, any agent or collaborator). Once open, a Challenge is independently addressable: `proof challenge list`, `proof challenge show <challenge-id>`. Resolving one — dismissing it, or the revision/re-Acceptance/reference-review decision that follows — goes through `proof review ...`, same as every other Human Review action. Treating Challenge only as a boolean on its target would lose exactly the auditable, listable identity ADR-0005 gave it.

This is hard to reverse the way a public API always is: once the Codex plugin, any MCP tools, and a future web app are all built against this envelope shape and error-code vocabulary, changing it becomes a compatibility break across every adapter at once, not a local edit.

**Update (ADR-0007):** point 11 is restated more precisely: the CLI isn't the reference implementation adapters defer to, it's one of three equally thin callers (CLI, web app, agent adapter) of one authoritative application/service layer. The invariant that matters — no caller can reach the domain model without going through that layer, and none can bypass Human Acceptance Authority — is unchanged; only the CLI's assumed centrality in the wording is corrected.

**Update (ADR-0010, #25):**
- **Command names.** A Challenge is opened with `proof challenge open <node-id>`, not `proof node challenge`, and read with `proof challenge list|show`. A Challenge is an object of its own, so it gets its own group; `proof challenge dismiss` only answers `HUMAN_REVIEW_REQUIRED`. Claims are `proof node claim --assignee` and `proof node unassign` (#52). A proof is handed over with `proof node request-review` (#51).
- **Human Review decisions** are made on the proof map page (`proof map open`), not through `proof review ...`.
- **How a Challenge ends** is read off the decision that closed it:
  - **dismissed** by a dismissal, or by reaffirming an Imported result's Reference review;
  - **resolved-by-revision** when a revised proof is Accepted;
  - **upheld** when the revision is rejected or sent back, or the Imported result is found no longer callable.

  "Upheld" is never recorded on its own for a local node: the Challenge stays open until a decision on a revision closes it.

**Update (#34): the error-code vocabulary is written down in `src/proof_cli/errors.py`.** That module is the one list of codes an agent may branch on. A test fails if the code raises one it doesn't list. Where it differs from the examples above, it wins:
- §8's `CLAIM_OWNERSHIP_MISMATCH` is `NOT_CLAIMANT` (someone else holds the node) or `NO_ACTIVE_CLAIM` (nothing to release).
- §7's `CLAIM_CONFLICT` carries `node_id`, `assignee` and `claimed_at` rather than `active_claim_id`: a claim is an assignee, not a token (ADR-0010).
- **Every `--json` invocation writes exactly one envelope to stdout, a failure included.** A command line that doesn't parse is `USAGE_ERROR` (exit 2). An unexpected failure is `INTERNAL_ERROR` (exit 1), never a traceback. A read pointed at a folder with no project is `PROJECT_NOT_FOUND`, and a read never creates a project.
