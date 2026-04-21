# Stack Research

**Domain:** Research mathematics CLI / proof workflow OS
**Researched:** 2026-04-21
**Confidence:** MEDIUM

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Node.js | 22 LTS | Runtime for the CLI and orchestration layer | Strong cross-platform CLI support, good ecosystem, simple process model for spawning checks and tools |
| TypeScript | Latest stable | Primary implementation language | Keeps the codebase explicit and refactorable, which matters for stateful proof tooling |
| SQLite | 3.x | Local persistent store for project state | Fits the local-first, stateful nature of theorem contracts and proof sessions |
| Markdown + JSON | N/A | Human-readable project artifacts and machine-readable metadata | Matches the workflow’s need for auditable state and durable docs |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `zod` | Latest stable | Runtime schema validation | Use for contracts, obligations, and config validation |
| `commander` | Latest stable | CLI command parsing | Use if the CLI has multiple subcommands and flags |
| `better-sqlite3` | Latest stable | Synchronous local SQLite access | Use when the app benefits from simple local persistence and fast reads |
| `execa` | Latest stable | Safe child-process execution | Use for invoking external checkers, solvers, and search tools |
| `picocolors` | Latest stable | Terminal coloring | Use for concise, readable CLI output |
| `fast-glob` | Latest stable | Workspace file discovery | Use for finding proof artifacts and imported documents |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `eslint` | Static linting | Keep rules strict around async/process boundaries |
| `prettier` | Formatting | Reduce noise in planning and source files |
| `tsx` | TS execution in dev | Good for fast iteration on CLI workflows |
| `vitest` | Test runner | Good fit for stateful logic and contract checks |

## Installation

```bash
npm install zod commander better-sqlite3 execa picocolors fast-glob
npm install -D typescript eslint prettier tsx vitest
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| SQLite | JSON files only | Only for very small prototypes with no multi-session state |
| Node.js + TypeScript | Python | If the project becomes heavily notebook-driven or Python-native tooling dominates |
| `commander` | `oclif` | If the CLI grows into a larger plugin ecosystem |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Full formal kernel in v1 | Too much scope before proving the workflow value | Explicit contracts + checkers + human review |
| Vector DB as the primary state model | Summaries do not capture obligations, dependencies, or trust | SQLite + structured proof state |
| Browser-first UI | Pulls the first release away from the workflow’s strongest shape | CLI-first with optional later console |

## Stack Patterns by Variant

**If the project stays local-first:**
- Keep the persistence layer in SQLite
- Prefer deterministic CLI commands over remote services
- Because proof state needs to be inspectable and recoverable

**If external retrieval becomes important early:**
- Add a dedicated retrieval adapter layer
- Because imported results need source metadata and trust handling

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| TypeScript | Node.js 22 LTS | Keep `tsconfig` aligned with current runtime features |
| `better-sqlite3` | Node.js 22 LTS | Best used with native build support available |

## Sources

- Project proposal in `mathematical_proof_cli_project_plan.md`
- Local-first CLI and persistent state requirements from the product vision

---
*Stack research for: Research mathematics CLI / proof workflow OS*
*Researched: 2026-04-21*
