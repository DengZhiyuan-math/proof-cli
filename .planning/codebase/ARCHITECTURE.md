<!-- refreshed: 2026-04-28 -->
# Architecture

**Analysis Date:** 2026-04-28

## System Overview

```text
CLI entry
  ├─ `pyproject.toml`
  ├─ `src/proof_cli/cli.py:97`
  └─ `src/proof_cli/services.py`

Orchestration
  └─ `src/proof_cli/commands.py`

Domain and state
  ├─ `src/proof_cli/theorems.py`
  ├─ `src/proof_cli/references.py`
  ├─ `src/proof_cli/proof_state.py`
  └─ `src/proof_cli/memory.py`

Persistence
  ├─ `src/proof_cli/db.py`
  ├─ `src/proof_cli/storage.py`
  └─ `.proof/project.sqlite3`, `.proof/collaboration.json`, `.proof/memory.json`
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI surface | Exposes the `proof` executable and nested Typer command groups | `src/proof_cli/cli.py` |
| Command orchestration | Converts CLI arguments into workspace mutations and rendered output | `src/proof_cli/commands.py` |
| Workspace bootstrap and storage schema | Opens the project store, creates `.proof/project.sqlite3`, and manages SQLite tables | `src/proof_cli/storage.py`, `src/proof_cli/db.py` |
| Proof state | Maintains current theorem, goals, obligations, blockers, routes, and snapshot summaries | `src/proof_cli/proof_state.py` |
| Snapshot and handoff | Produces resumable handoff state and publication-linked snapshots | `src/proof_cli/snapshot.py` |
| Retrieval | Ranks local theorems and external candidates from current proof context | `src/proof_cli/retrieval.py` |
| Theorem registry | Creates, versions, grounds, and applies theorem contracts | `src/proof_cli/theorems.py` |
| Reference registry | Imports and reviews trusted references | `src/proof_cli/references.py` |
| Collaboration state | Tracks contributors, reviews, comments, branches, and shared publications | `src/proof_cli/collaboration.py` |
| Memory and debug history | Stores layered memory plus verification/debug history in `.proof/memory.json` | `src/proof_cli/memory.py` |
| Governance workflows | Records reusable assets, packs, policies, recommendations, automation, and benchmark runs | `src/proof_cli/governance.py` |

## Pattern Overview

**Overall:** command-driven local workspace with layered domain modules.

**Key Characteristics:**
- The CLI is the primary entrypoint, not a web layer.
- `commands.py` is the central orchestration hub; feature modules stay focused on domain rules and persistence helpers.
- State is local-first and auditable: SQLite holds canonical records and append-only events, while some collaboration and memory views are mirrored into JSON files under `.proof/`.
- Pydantic models carry the domain boundary; the CLI mostly marshals JSON, strings, and enums into those models.

## Layers

**Presentation Layer:**
- Purpose: parse arguments and print text or JSON output.
- Location: `src/proof_cli/cli.py`
- Contains: Typer apps, subcommands, root options.
- Depends on: `src/proof_cli/commands.py`, `src/proof_cli/review.py`.
- Used by: `proof` console script from `pyproject.toml`.

**Orchestration Layer:**
- Purpose: coordinate workspace reads/writes and format results for terminal use.
- Location: `src/proof_cli/commands.py`
- Contains: `cmd_*` functions for status, theorem, obligation, blocker, reference, memory, publication, verification, exchange, and automation flows.
- Depends on: storage, state, retrieval, review, rendering, and feature modules.
- Used by: `src/proof_cli/cli.py`, `src/proof_cli/services.py`.

**Domain Layer:**
- Purpose: define proof contracts, obligations, blockers, references, collaboration records, verification IR, and support models.
- Location: `src/proof_cli/domain.py` and feature modules such as `src/proof_cli/theorems.py`, `src/proof_cli/references.py`, `src/proof_cli/collaboration.py`.
- Contains: Pydantic models, enums, and domain rules.
- Depends on: `pydantic`, `datetime`, small helper modules.
- Used by: orchestration and persistence layers.

**Persistence Layer:**
- Purpose: persist the project workspace and event history.
- Location: `src/proof_cli/storage.py`, `src/proof_cli/db.py`
- Contains: SQLite schema, `ProjectStore`, CRUD helpers, event log writes.
- Depends on: `sqlite3`, `Path`, Pydantic adapters.
- Used by: all workflow modules.

## Data Flow

### Primary CLI Path

1. `proof ...` resolves to `src/proof_cli/cli.py:97` through the console script in `pyproject.toml`.
2. Typer command handlers forward to `cmd_*` functions in `src/proof_cli/commands.py:1889` and related handlers.
3. Command helpers call `ensure_project()` / `get_store()` in `src/proof_cli/storage.py:560` and `src/proof_cli/commands.py:1889`.
4. State mutations go through `src/proof_cli/proof_state.py:90` and storage helpers in `src/proof_cli/storage.py:123`.
5. Output is returned as plain text, formatted JSON, or Rich-rendered status output from `src/proof_cli/rendering.py:9`.

### Status and Snapshot Flow

1. `cmd_status()` loads project state and collaboration state, then renders a terminal summary (`src/proof_cli/commands.py:1895`).
2. `cmd_snapshot()` builds a snapshot from live state and writes it through `src/proof_cli/proof_state.py:328` and `src/proof_cli/snapshot.py:16`.
3. `build_snapshot()` collects open goals, obligations, blockers, recent theorem usage, literature routes, and publication metadata before storing a `ProjectSnapshot` (`src/proof_cli/proof_state.py:328`).
4. Snapshot persistence lands in SQLite via `src/proof_cli/storage.py:494`, with an event appended in `src/proof_cli/storage.py:140`.

### Retrieval Flow

1. `workspace_retrieval()` in `src/proof_cli/services.py:36` opens the project store.
2. `retrieve_candidates()` in `src/proof_cli/retrieval.py:668` reads current proof context from `read_state()` and scores local contracts first.
3. Project-local and imported theorem contracts are ranked ahead of external bibliographic candidates, then truncated to the requested limit.

**State Management:**
- The canonical workspace state is project-local.
- `ProjectState` tracks current theorem, current context, open goals, open obligations, blockers, failed routes, session history, and unresolved trust-sensitive calls.
- Some adjacent state is stored separately: collaboration data in `.proof/collaboration.json` and memory/debug history in `.proof/memory.json`.

## Key Abstractions

**`ProjectStore`:**
- Purpose: encapsulates the project root and SQLite path.
- Examples: `src/proof_cli/storage.py`
- Pattern: thin wrapper around the workspace root.

**`ProjectState` and `ProjectSnapshot`:**
- Purpose: hold live proof state and resumable handoff state.
- Examples: `src/proof_cli/domain.py`, `src/proof_cli/proof_state.py`, `src/proof_cli/snapshot.py`
- Pattern: Pydantic models with JSON serialization.

**`TheoremContract`:**
- Purpose: versioned theorem/lemma/result record with trust and review metadata.
- Examples: `src/proof_cli/domain.py`, `src/proof_cli/theorems.py`
- Pattern: current version is stored in SQLite and older versions remain in `theorem_contracts`.

**`ReferenceRecord` and `ReferenceReviewRecord`:**
- Purpose: model imported trusted references and their review trail.
- Examples: `src/proof_cli/references.py`, `src/proof_cli/storage.py`
- Pattern: candidate/imported records are promoted or rejected through explicit review actions.

**`CollaborationState`:**
- Purpose: track human collaboration metadata separately from proof state.
- Examples: `src/proof_cli/collaboration.py`
- Pattern: JSON-backed project-local state plus event emission.

## Entry Points

**Console script:**
- Location: `pyproject.toml`
- Trigger: `proof`
- Responsibilities: launches the Typer app defined in `src/proof_cli/cli.py:97`.

**Workspace initialization:**
- Location: `src/proof_cli/commands.py:1889`
- Trigger: `proof init`
- Responsibilities: creates/opens the project store and ensures the default project state exists.

**Workspace inspection:**
- Location: `src/proof_cli/commands.py:1895`, `src/proof_cli/commands.py:2060`, `src/proof_cli/commands.py:2070`
- Trigger: `proof status`, `proof snapshot`, `proof export`
- Responsibilities: summarize current state, persist a snapshot, or export the assembled workspace.

## Architectural Constraints

- **Local-first storage:** The implementation assumes a project root containing `.proof/project.sqlite3`; no remote state service is part of the current architecture.
- **Human confirmation boundary:** trust changes, review actions, and related state transitions remain explicit in command handlers and review modules.
- **Single-process CLI model:** the code uses synchronous SQLite and direct command invocation rather than worker orchestration.
- **Mixed persistence model:** canonical proof records live in SQLite, while collaboration and memory also keep JSON mirrors under `.proof/`.
- **Append-only traceability:** state mutations emit events through `append_event()` so history can be replayed or inspected.

## Anti-Patterns

### Bypassing workspace helpers

**What happens:** code writes directly to `.proof/` paths or mutates SQLite tables without `ProjectStore`, `ensure_project()`, or the domain helpers.
**Why it's wrong:** it breaks schema initialization, event logging, and the current state contract.
**Do this instead:** use `src/proof_cli/storage.py`, `src/proof_cli/proof_state.py`, or the feature module helpers that already wrap them.

### Treating retrieval as a source of truth

**What happens:** new proof work is added before checking existing contracts, references, and project state.
**Why it's wrong:** it violates the retrieval-first workflow and duplicates already-tracked obligations.
**Do this instead:** call `proof search`, `proof theorem list`, `proof reference list`, or `workspace_retrieval()` before adding new proof material.

## Error Handling

**Strategy:** return structured records or plain text results; record failures in the event log and proof state when actions are blocked.

**Patterns:**
- `theorem_callability()` returns `(ok, reason)` and `apply_theorem()` logs rejected calls.
- Review-sensitive actions require confirmation flags and emit blocked events when confirmation is missing.
- Missing records typically return `None`, `False`, or a short human-readable message rather than raising deep exceptions.

## Cross-Cutting Concerns

**Logging:** event log entries are appended through `src/proof_cli/storage.py:140`; many workflows also write summaries into `session_history`.

**Validation:** Pydantic models validate payloads at the boundary in `domain.py`, `references.py`, `verification_ir.py`, and related modules.

**Authentication:** not applicable; human review and confirmation are the trust boundary.

---

*Architecture analysis: 2026-04-28*
