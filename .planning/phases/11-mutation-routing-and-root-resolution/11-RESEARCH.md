---
phase: 11-mutation-routing-and-root-resolution
type: research
focus: mutation routing, root resolution, codex wrapper ergonomics
date: 2026-04-30
---

# Phase 11 Research

## Research Question

How should the `proof codex` wrapper evolve from read-only routing into safe mutation routing without duplicating Proof CLI logic or weakening the explicit trust boundary?

## Findings

### 1. The underlying mutation engine already exists

The main CLI already exposes mutation commands for:

- `theorem add`
- `obligation add`
- `blocker add`
- `snapshot`

So Phase 11 should not invent a new proof-state write path. The wrapper should translate Codex-facing intent into those existing commands or handlers.

### 2. The current gap is not capability, but interface shape

Phase 10 proved that the wrapper can:

- discover a workspace root
- preserve machine-readable retrieval and analysis
- expose a guided command catalog

But mutation commands are still only placeholder guidance. The missing layer is:

- structured input normalization
- minimum-missing-detail handling
- explicit mutation/read-only separation
- deterministic root behavior under write operations

### 3. Root resolution needs stricter semantics for writes than for reads

The current resolver order is:

1. explicit `--root`
2. `PROOF_ROOT`
3. workspace discovery
4. repo discovery
5. global fallback
6. cwd fallback

This is acceptable for read-only inspection, but mutation flows need extra clarity:

- write commands should surface which root will be mutated before acting
- fallback-to-cwd is risky if the user intended the project workspace but is outside it
- repo discovery and workspace discovery should remain explicit in user-facing messages

The most practical Phase 11 pattern is:

- keep the same precedence order
- add a mutation-safe confirmation/explanation path in wrapper output
- reject or guide more aggressively when the selected root does not already look like a Proof workspace and the command is not `init`

### 4. Theorem creation needs a guided bridge, not a free-form parser

The current CLI signature for theorem creation is strict:

`proof theorem add <theorem_id> <name> <statement> [options]`

Codex-facing users are more likely to type:

- `$proof new theorem`
- `$proof theorem add`
- `$proof theorem add tiny_transitivity`

So the wrapper should:

- detect when required fields are missing
- ask only for the missing pieces
- keep a minimal contract for v1.2 rather than trying to infer all optional fields

Recommended minimal required set:

- theorem id
- theorem name
- statement

Optional fields can stay explicit flags:

- `--kind`
- `--assumption`
- `--export`
- `--notes`

### 5. Obligation, blocker, and snapshot can be hardened with lighter guidance

Compared with theorem creation:

- `obligation add` needs one required statement plus optional linkage
- `blocker add` needs description plus optional scope/failure type
- `snapshot` mostly needs the selected root and maybe a note

So Phase 11 should treat them differently:

- theorem add: heavier guided path
- obligation/blocker add: medium guided path
- snapshot: near-direct wrapper execution

### 6. Trust-boundary clarity should be part of the wrapper output

Mutation routing is not just a technical feature. It is part of the product’s trust model.

The wrapper should clearly signal:

- this command will mutate persisted proof state
- which workspace root is being targeted
- whether it is acting directly or asking for missing details first

That keeps the system “guided” without hiding the fact that a real state transition is happening.

## Recommendations

1. Keep one root resolver shared across read and write flows, but add mutation-specific guardrails.
2. Add explicit mutation command groups under `proof codex` rather than sending users back to raw `proof theorem add` after they enter the wrapper.
3. Support minimum-missing-detail prompts for theorem, obligation, and blocker mutations.
4. Make `snapshot` the simplest end-to-end mutation path.
5. Cover root precedence and mutation flows with CLI smoke tests, not just unit-style parsing assertions.

## Planning Implications

- Phase 11 should implement real wrapper mutations, not just better prose.
- The plan should centralize root resolution behavior before expanding every mutation command.
- Theorem creation deserves its own task because it is the most structurally demanding mutation path.
- Validation should prove both correct routing and correct root targeting.
