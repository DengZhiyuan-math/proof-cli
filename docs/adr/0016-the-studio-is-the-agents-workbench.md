# The studio is the agent's workbench, watched by the researcher

**Status**: accepted (decided in #144; the run and its roles landed with spec #145 part 3, the page follows). Amends ADR-0011: a local node's studio is no longer a LaTeX workspace with an agent panel, but the place a Proof agent works on the node on its own and the researcher watches and steps in. ADR-0004 and ADR-0010 stand untouched: no role makes a Review decision.

## Context

The studio came from prism-local, a human-led LaTeX editor with an AI assistant: the agent did one turn per prompt, "Prove it" was a canned prompt, and the page's centre was an editor. The researcher's principle for proof-cli is the opposite — an automated, visible, supervisable proof system: the agent is autonomous, the human sees what it does and can step in, and never has to drive it by typing. The two had drifted apart.

## Decision

1. **Start once, then autonomous.** A run is started on a node — from the map, its page or its studio — claims it under the project's agent name (`[studio] agent_name`, default the provider's) and works it without waiting for a prompt: retrieval, writing or computing, self-check, split or request review. It stops only when review is requested, when a step reports stuck or a decision only a human can make, when its budget is spent (`[studio] budget_turns` / `budget_minutes`, default 40 and 60), or when turns stop changing anything. One run per node; runs on different nodes in parallel.
2. **Three roles, in turn.** Prover (finds the proof, drafts in `scratch/`, decides splits and review), Typesetter (writes the LaTeX and the key-ideas text, never does mathematics), Numerics (writes and runs computations, records Evidence). Each is the same CLI with its own brief, environment (`PROOF_AGENT_ROLE`, `PROOF_AGENT_NAME`) and write scope; work moves between them by `proof node progress --handoff`, and the Prover returns after every delegation. A single role may be started on its own.
3. **The work is visible as project state.** Roles report their plan and steps with `proof node progress`; the node's work log merges those reports with what they did through other `proof` commands. It is kept in the project's events, never in the node folder, which a snapshot would freeze. The map shows a claimed node's role and step.
4. **Oversight is four actions, not a prompt.** Pause (the turn finishes, the claim stays), Redirect (one line for the next turn, optionally for one role), Resume, Stop and release. The chat stays as Ask, read-only.
5. **The editor is a view of the product.** The LaTeX and the PDF, or the program and `out/`, remain readable and editable by the researcher as the Files view; the studio's centre is the work log.

## Consequences

- The agent-facing contract is the brief and `proof`; nothing a role writes outside its scope is accepted by a backend that can enforce scope, and the brief is the contract where one cannot (as ADR-0011 said).
- `proof node progress` is agent-reachable; like `created_by`, the role it reports is a cooperative agent's word (ADR-0010's threat model), not a signature.
- Reversing this means removing the run and the roles; every `proof` command they use exists for a human too, so nothing in the map would have to change.
