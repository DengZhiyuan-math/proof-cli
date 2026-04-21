<!-- GSD:project-start source:PROJECT.md -->
## Project

**Mathematical Proof CLI / Research Proof OS**

This is a human-machine collaborative proof operating system for research mathematics. It is not trying to replace mathematicians or fully formalize every proof step; it is trying to make proof work stateful, debuggable, and trustworthy.

The CLI should help a researcher manage theorem contracts, proof state, dependencies, blockers, and imported results so long-running proof work can survive context loss and stay auditable.

**Core Value:** Manage the trust boundary around mathematical proof work: know what can be called, under what assumptions, and what proof obligations remain.

### Constraints

- **Human-in-the-loop**: Final acceptance must stay with the researcher — the system can suggest and check, but not silently decide
- **Retrieval-first**: Project results and trusted references must be checked before any new proof search
- **Local-state-first**: Long tasks must survive context loss through persisted project state
- **CLI-first**: The initial user experience should be terminal-native, with browser views deferred
- **No full kernel in v1**: The first release should support rigorous collaboration without attempting a complete formal logic foundation
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

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
- Keep the persistence layer in SQLite
- Prefer deterministic CLI commands over remote services
- Because proof state needs to be inspectable and recoverable
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
