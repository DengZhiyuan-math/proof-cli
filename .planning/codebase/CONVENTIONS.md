# Coding Conventions

**Analysis Date:** 2026-04-28

## Naming Patterns

**Files:**
- `src/proof_cli/*.py` uses lower_snake_case module names by concern, such as `storage.py`, `proof_state.py`, `verification_ir.py`, and `formal_bridge.py`.
- `tests/test_*.py` mirrors the source module or workflow being exercised, such as `tests/test_storage.py` and `tests/test_cli.py`.

**Functions:**
- Public helpers and command implementations use lower_snake_case, including `add_theorem`, `load_state`, `cmd_proof_asset_publish`, and `render_verification_output`.
- Private helpers are prefixed with `_`, such as `_root`, `_append_history`, and `_format_candidate_line`.
- CLI-facing command wrappers in `src/proof_cli/cli.py` use verb-first names and frequently start with the workflow noun, such as `asset_list`, `theorem_show`, and `verify_run`.

**Variables:**
- Short, concrete names are preferred for domain objects: `store`, `state`, `contract`, `snapshot`, `result`, `record`.
- Boolean-returning checks are named as predicates or unpack into `ok, reason`.

**Types:**
- Pydantic models, enums, and dataclasses use PascalCase, such as `ProjectState`, `TheoremContract`, `VerificationResult`, and `ProjectStore`.
- Enum values are lower_snake_case strings, matching serialized payloads and CLI output.

## Code Style

**Formatting:**
- `from __future__ import annotations` appears at the top of many modules.
- Imports are grouped as stdlib, third-party, then local project imports.
- Type hints are used throughout, including `list[str]`, `tuple[bool, str]`, and `Path | str`.
- Source files rely on standard Python formatting conventions; no repo-local formatter config was detected.

**Linting:**
- No repo-local lint configuration was detected in `pyproject.toml` or adjacent config files.
- Type-adjacent validation is pushed into Pydantic models and typed helper functions rather than runtime lint enforcement.

## Import Organization

**Order:**
1. Standard library imports
2. Third-party imports such as `typer`, `pydantic`, and `pytest`
3. Local `proof_cli.*` imports

**Path Aliases:**
- Not detected. Imports use the package name directly: `from proof_cli...`.

## Error Handling

**Patterns:**
- Missing entities raise `KeyError`, especially for theorem and blocker lookup paths in `src/proof_cli/theorems.py`, `src/proof_cli/blockers.py`, and `src/proof_cli/commands.py`.
- Invalid project or compatibility state raises `ValueError`, with tests asserting the message text in modules such as `tests/test_automation_eval.py` and `tests/test_domain_packs.py`.
- Validation is primarily handled by Pydantic via `model_validate_json`, `model_validate`, and `TypeAdapter.validate_json`.
- Many business rules avoid exceptions and return a structured result instead, for example `theorem_callability()` returning `(bool, reason)`.

## Logging

**Framework:** None detected

**Patterns:**
- The codebase uses durable domain events through `append_event(...)` in `src/proof_cli/storage.py` rather than a dedicated logging framework for most workflow actions.
- CLI output is rendered with Typer and Rich helpers in `src/proof_cli/cli.py` and `src/proof_cli/rendering.py`.

## Comments

**When to Comment:**
- Comments are sparse and usually reserved for small implementation details, not prose explanations.
- Most behavior is encoded in names, model fields, and tests rather than inline comments.

**JSDoc/TSDoc:**
- Not detected.

## Function Design

**Size:**
- Functions are generally small and single-purpose.
- Larger workflows are decomposed into helper layers in `src/proof_cli/commands.py`, `src/proof_cli/storage.py`, and domain-specific modules.

**Parameters:**
- Keyword arguments are common for optional workflow inputs, especially in command functions and record builders.
- Many helpers accept `root: str | Path = "."` or a `ProjectStore` handle to keep state local and explicit.

**Return Values:**
- CRUD helpers usually return the created or updated model object.
- Status checks return structured tuples or model objects instead of printing.

## Module Design

**Exports:**
- Modules are organized by domain concern, not by layer-wide utilities.
- `src/proof_cli/cli.py` is the command surface; `src/proof_cli/commands.py` is the orchestration layer; model/persistence code stays in focused modules such as `domain.py`, `storage.py`, `proof_state.py`, and `verification_ir.py`.

**Barrel Files:**
- Not detected.

---

*Convention analysis: 2026-04-28*
