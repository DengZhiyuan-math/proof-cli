# External Integrations

**Analysis Date:** 2026-04-28

## APIs & External Services

**Bibliographic / reference metadata:**
- No live network client detected
- Reference records in `src/proof_cli/references.py` and `src/proof_cli/storage.py` carry fields for `origin`, `bibliographic_source`, `identifier`, and `url`
- Test fixtures reference arXiv, zbMATH, DOI-like identifiers, and `example.test` URLs, but the implementation stores those values locally rather than calling an API

**Exchange formats:**
- JSON bundle import/export in `src/proof_cli/exchange.py`
- Human-readable proof export in `src/proof_cli/export.py`
- Publication workspace serialization in `src/proof_cli/publication.py`

## Data Storage

**Databases:**
- SQLite, local file-backed
  - Connection: `.proof/project.sqlite3` from `src/proof_cli/storage.py`
  - Client: stdlib `sqlite3` via `src/proof_cli/db.py`
  - Schema: `project_meta`, `events`, `theorem_contracts`, `obligations`, `blockers`, `snapshots`, `publication_state`, `publication_bundle_snapshots`, `state`, plus reference tables in `src/proof_cli/storage.py`

**File Storage:**
- `.proof/collaboration.json` - collaboration state in `src/proof_cli/collaboration.py`
- `.proof/memory.json` - layered memory and handoff state in `src/proof_cli/memory.py`
- `.proof/project.sqlite3` - core persistent workspace state in `src/proof_cli/storage.py`

**Caching:**
- None detected

## Authentication & Identity

**Auth Provider:**
- Custom/local identity only
- Reviewer, contributor, and creator fields are carried in model data in `src/proof_cli/collaboration.py`, `src/proof_cli/publication.py`, `src/proof_cli/governance.py`, and `src/proof_cli/review.py`

## Monitoring & Observability

**Error Tracking:**
- None detected

**Logs:**
- Event log table in SQLite populated by `append_event` in `src/proof_cli/storage.py`
- Session history strings in `src/proof_cli/governance.py`, `src/proof_cli/review.py`, `src/proof_cli/memory.py`, and related modules act as an audit trail

## CI/CD & Deployment

**Hosting:**
- Not detected

**CI Pipeline:**
- Not detected

## Environment Configuration

**Required env vars:**
- None detected

**Secrets location:**
- Not applicable

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## Local Integration Surfaces

- CLI commands in `src/proof_cli/cli.py` orchestrate local workflows such as `proof status`, `proof snapshot`, `proof export`, `proof search`, `proof theorem ...`, `proof reference ...`, `proof memory ...`, and `proof publication ...`
- Cross-workspace import/export is handled by `src/proof_cli/exchange.py`
- Publication-facing bundles and selective release artifacts are handled by `src/proof_cli/publication.py`

---

*Integration audit: 2026-04-28*
