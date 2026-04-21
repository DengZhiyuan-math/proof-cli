# Architecture Research

**Domain:** Research mathematics CLI / proof workflow OS
**Researched:** 2026-04-21
**Confidence:** MEDIUM

## Standard Architecture

### System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                         CLI Layer                           │
├─────────────────────────────────────────────────────────────┤
│  Commands   │  Proof scripts  │  Retrieval  │  Review flow │
├─────────────┴─────────────────┴─────────────┴───────────────┤
│                     Orchestration Layer                     │
├─────────────────────────────────────────────────────────────┤
│  State engine  │  Registry  │  Elaborator  │  Checkers      │
├─────────────────────────────────────────────────────────────┤
│                     Persistence Layer                       │
├─────────────────────────────────────────────────────────────┤
│  SQLite  │  Markdown project docs  │  JSON metadata         │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| CLI commands | Expose user actions and project status | Typed command handlers with subcommands |
| State engine | Track open goals, obligations, blockers, and snapshots | SQLite-backed state store with projection helpers |
| Registry | Store theorem contracts and dependency metadata | Structured records with explicit assumptions and exports |
| Elaborator | Expand compressed proof steps into checkable actions | Rule-based transformation plus obligation generation |
| Checkers | Validate assumptions, export strength, circularity, and notation | Deterministic validation pipeline |
| Retrieval | Find existing internal results before external sources | Search index + source metadata + ranking rules |
| Review flow | Gate trust changes and imported claims | Human approval workflow with explicit prompts |

## Recommended Project Structure

```text
src/
├── cli/                # command entry points and argument parsing
├── state/              # proof state, blockers, snapshots
├── registry/           # theorem contracts and dependency graph
├── dsl/                # parser and elaborator for proof scripts
├── checks/             # assumption, export, circularity, notation checks
├── retrieval/          # internal and external search adapters
├── memory/             # working, semantic, episodic, procedural memory
└── review/             # human approval and trust workflows
```

### Structure Rationale

- `state/` and `registry/` should be separate because the current proof session is not the same thing as the library of reusable contracts.
- `dsl/` and `checks/` should be separate because syntax translation and semantic validation fail in different ways.

## Architectural Patterns

### Pattern 1: Contract-First Proof Objects

**What:** Represent theorem/lemma results as explicit contracts with assumptions, exports, and dependencies.
**When to use:** Whenever a proof result may be reused later.
**Trade-offs:** Adds structure up front, but prevents trust from leaking through informal summaries.

### Pattern 2: Obligation Pipeline

**What:** Translate each proof script step into one or more obligations that validators can inspect.
**When to use:** When proof prose is compressed or uses omitted reasoning.
**Trade-offs:** More implementation work, but makes gaps visible instead of hidden.

### Pattern 3: Retrieval Before Search

**What:** Check the project registry and memory before looking outside the project.
**When to use:** For any user request that might reuse an existing result.
**Trade-offs:** Requires disciplined indexing, but avoids repeated work and stale reinvention.

## Data Flow

### Request Flow

```text
[User command]
    ↓
[CLI handler] → [State query] → [Registry lookup] → [Checker/Elaborator]
    ↓                 ↓               ↓                    ↓
[Response] ← [Snapshot update] ← [Obligation records] ← [Validation results]
```

### State Management

```text
[Project state store]
    ↓ (read/write)
[CLI] ←→ [State engine] → [Snapshots] → [Persistent storage]
```

### Key Data Flows

1. Proof step intake: script text is parsed, elaborated, and converted into obligations.
2. Contract reuse: a theorem call is checked against assumptions and dependency metadata before it is accepted.
3. Import workflow: external results are recorded with source metadata and trust level before they can be reused.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-1k projects | Single local process and SQLite are enough |
| 1k-100k projects | Add indexing and better query projections |
| 100k+ projects | Split search, indexing, and UI concerns if needed |

### Scaling Priorities

1. First bottleneck: search and retrieval latency.
2. Second bottleneck: checker throughput on large obligation graphs.

## Anti-Patterns

### Anti-Pattern 1: Flat Notes Instead of Contracts

**What people do:** Store theorem results as plain summaries.
**Why it's wrong:** Summaries cannot enforce assumptions or exports.
**Do this instead:** Store contract objects with dependency metadata.

### Anti-Pattern 2: Single Summary Memory

**What people do:** Compress everything into one rolling note.
**Why it's wrong:** It loses blockers, obligations, and provenance.
**Do this instead:** Keep structured memory tiers and snapshots.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Document search | Adapter layer | Use source metadata and trust levels |
| Optional theorem search | Adapter layer | Keep source provenance explicit |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| CLI ↔ state engine | direct | Keep the interface small and deterministic |
| registry ↔ checks | direct | Checks need contract metadata, not prose |
| retrieval ↔ review | direct | Imported results should not bypass human approval |

## Sources

- Project proposal in `mathematical_proof_cli_project_plan.md`
- Standard local-first CLI architecture patterns

---
*Architecture research for: Research mathematics CLI / proof workflow OS*
*Researched: 2026-04-21*
