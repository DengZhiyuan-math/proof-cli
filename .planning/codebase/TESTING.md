# Testing Patterns

**Analysis Date:** 2026-04-28

## Test Framework

**Runner:**
- `pytest` 8.x
- Config: `pyproject.toml`

**Assertion Library:**
- Built-in `assert` statements
- `pytest.raises(...)` for failure paths

**Run Commands:**
```bash
python -m pytest -q
pytest -q
```

## Test File Organization

**Location:**
- Co-located by behavior area under `tests/`
- Filenames use `test_<module>.py`, matching the source module or workflow

**Naming:**
- Test functions use `test_<behavior>()`
- Helper builders and seeders are private functions prefixed with `_`

**Structure:**
```text
tests/
├── test_cli.py
├── test_storage.py
├── test_theorems.py
├── test_retrieval.py
└── ...
```

## Test Structure

**Suite Organization:**
```python
def test_project_create_and_reopen(tmp_path: Path):
    store = ensure_project(tmp_path)
    state = read_state(store)
    assert state.project_id == "proj_alpha"

    store_state(store, ProjectState(...))

    reopened = ensure_project(tmp_path)
    reopened_state = read_state(reopened)
    assert reopened_state.current_theorem == "thm_1"
```

**Patterns:**
- `tmp_path` is the standard isolation primitive for filesystem-backed state.
- Tests seed state through public helpers such as `ensure_project`, `add_theorem`, `add_obligation`, `add_blocker`, and `record_memory`.
- Behavior is validated through model fields, persisted state, and rendered CLI text.
- Round-trip serialization is common: `model_validate_json(model_dump_json())` or `type(model).model_validate_json(...)`.

## Mocking

**Framework:** Minimal; no dedicated mocking library usage was detected in the sampled tests.

**Patterns:**
```python
runner = CliRunner()
result = runner.invoke(app, ["search", "Auxiliary Lemma", "--root", str(tmp_path)])
assert result.exit_code == 0
assert "query: Auxiliary Lemma" in result.stdout
```

**What to Mock:**
- Not generally mocked; tests prefer real local state and real model serialization.

**What NOT to Mock:**
- Do not mock the local store or model layer when a real `tmp_path` project can exercise the workflow end to end.

## Fixtures and Factories

**Test Data:**
- Explicit inline builders are preferred over shared fixture factories.
- Private helpers like `_seed_phase_two_project(...)` and `_domain_pack()` create reusable local setup in the test file.

**Location:**
- Test-local helper functions inside each `tests/test_*.py` file

## Coverage

**Requirements:** None enforced in repo config

**View Coverage:**
```bash
python -m pytest --cov
```
- Coverage tooling is not configured in `pyproject.toml`; ad hoc coverage requires an explicit plugin install.

## Test Types

**Unit Tests:**
- Most tests are unit-level checks of domain models, persistence helpers, retrieval scoring, and command formatting.

**Integration Tests:**
- CLI behavior is exercised with `typer.testing.CliRunner` in `tests/test_cli.py` and `tests/test_theorems.py`.
- Filesystem-backed state is tested with `ensure_project(tmp_path)` and subsequent rereads from disk.

**E2E Tests:**
- Not detected.

## Common Patterns

**Async Testing:**
```python
assert result.exit_code == 0
assert "Verification record:" in result.stdout
```
- The codebase is synchronous; async test helpers were not detected.

**Error Testing:**
```python
with pytest.raises(ValueError, match="scenario_id must be provided"):
    replay_automation_benchmark([...])
```
- Error-path assertions check both exception type and message text.

---

*Testing analysis: 2026-04-28*
