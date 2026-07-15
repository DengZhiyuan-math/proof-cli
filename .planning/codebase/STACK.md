# Technology Stack

**Analysis Date:** 2026-04-28

## Languages

**Primary:**
- Python 3.11+ - `src/proof_cli/*.py`, `tests/*.py`, and the CLI entry point in `src/proof_cli/cli.py`

**Secondary:**
- JSON - persisted workspace records, exchange bundles, and CLI payloads in `src/proof_cli/*.py`
- Markdown - planning artifacts under `.planning/`

## Runtime

**Environment:**
- CPython 3.11 or newer, declared in `pyproject.toml`
- Local CLI runtime only; no server runtime detected

**Package Manager:**
- `pip` with setuptools editable installs
- Lockfile: missing

## Frameworks

**Core:**
- `typer>=0.12` - command-line interface in `src/proof_cli/cli.py`
- `pydantic>=2.7` - domain models, validation, and JSON round-tripping across `src/proof_cli/domain.py`, `src/proof_cli/storage.py`, `src/proof_cli/references.py`, and related modules
- `rich>=13.7` - terminal formatting in `src/proof_cli/rendering.py`

**Testing:**
- `pytest>=8.0` - test runner for `tests/*.py`
- `typer.testing.CliRunner` - CLI assertions in `tests/test_cli.py` and `tests/test_theorems.py`

**Build/Dev:**
- `setuptools>=68` and `wheel` - build backend in `pyproject.toml`
- `src/` layout packaging - configured in `pyproject.toml`

## Key Dependencies

**Critical:**
- `pydantic` - all persisted proof, reference, memory, publication, and governance records use typed models
- `typer` - the `proof` executable is defined as `proof_cli.cli:app` in `pyproject.toml`
- `rich` - status/export rendering is terminal-native rather than web-based

**Infrastructure:**
- `sqlite3` from the Python standard library - local state store in `src/proof_cli/db.py` and `src/proof_cli/storage.py`
- `json`, `pathlib`, `uuid`, and `datetime` from the Python standard library - payload serialization and on-disk workspace files

## Configuration

**Environment:**
- Project root is passed through `--root` on CLI commands in `src/proof_cli/cli.py`
- Workspace state is stored under `.proof/` by `src/proof_cli/storage.py`
- The main database path is `.proof/project.sqlite3`

**Build:**
- `pyproject.toml` controls build metadata, dependencies, and the `proof` console script
- Generated packaging metadata appears under `src/mathematical_proof_cli.egg-info/`

**Useful Commands:**
- `python -m pip install -e ".[dev]"` - editable install for development
- `proof --help` - confirm CLI wiring
- `python -m pytest -q` - run the full test suite
- `pytest tests/test_cli.py -q` - narrow CLI verification

## Platform Requirements

**Development:**
- Python 3.11+
- Local filesystem write access for `.proof/`
- SQLite available through the Python standard library

**Production:**
- Local terminal usage; no hosted deployment target detected
- Single-user or collaborator-managed workspace model, not a network service

## Implementation Pointers

- CLI wiring and subcommand registration live in `src/proof_cli/cli.py`
- Persistent storage and schema initialization live in `src/proof_cli/db.py` and `src/proof_cli/storage.py`
- Terminal rendering lives in `src/proof_cli/rendering.py`
- End-to-end behavior is exercised by `tests/test_cli.py`, `tests/test_storage.py`, `tests/test_export.py`, and `tests/test_retrieval.py`

---

*Stack analysis: 2026-04-28*
