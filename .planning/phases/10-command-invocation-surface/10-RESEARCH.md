# Phase 10 Research: Command Invocation Surface

**Gathered:** 2026-04-30
**Status:** Complete

## Reusable Capabilities

- `src/proof_cli/cli.py` already exposes a broad Typer-based command tree for read-only and mutating workflows.
- `src/proof_cli/commands.py` already has direct read-only handlers for status, theorem listing, retrieval, and project analysis.
- `src/proof_cli/services.py` already provides a thin workspace-facing layer that can support a dedicated Codex wrapper without forcing shell parsing everywhere.
- Rich is already available in the dependency set, so visible, guided terminal surfaces can be implemented without introducing a new UI framework.
- Project-local and global Codex skills already exist for `proof` and `proof-cli`, so the missing piece is not discoverability alone but a deterministic execution boundary behind those skills.

## Missing Pieces

- There is no hard wrapper or plugin-like execution layer between Codex skill invocation and the underlying `proof` CLI.
- Current global and project-local skills mostly describe routing behavior but do not provide a shared executable or manifest that guarantees consistent command handling.
- There is no machine-readable command catalog that can drive guided behavior for Codex-facing command help.
- There are no dedicated tests for the Codex-facing command boundary itself.
- The current experience is discoverable, but it is not yet guided enough to feel like a visual, general-purpose interface for proof work.

## Recommended Workstreams

1. **Create a deterministic Codex-facing wrapper**
   - Add a dedicated wrapper surface such as `proof-codex` or a `proof codex` command family.
   - Route read-only commands through a single shared dispatch layer.
   - Keep the existing `proof` CLI as the source of truth.

2. **Add a visible command catalog and guidance layer**
   - Define a command manifest or command registry with grouped categories, usage hints, and safe/default root behavior.
   - Render a command palette or command catalog view that helps users discover available read-only actions.
   - Make the wrapper output obvious next actions rather than bare parser failures.

3. **Align global and project-local Codex integration**
   - Point both the global and project-local skills at the same wrapper semantics.
   - Make repo-root resolution deterministic enough for the common single-project case.
   - Keep the wrapper generic enough that later mutation flows can reuse it.

4. **Prove the read-only surface with smoke tests**
   - Add tests that exercise Codex-facing wrapper commands for status, theorem list, search, retrieve, and project analysis.
   - Assert both machine-readable and visible/helpful rendering behavior where appropriate.

## Risks and Ambiguities

- A wrapper that only wraps shell strings may still feel fragile if argument parsing remains ad hoc.
- A wrapper that is too interactive too early may block later machine-readable automation.
- "Visualized" can drift toward browser UI if not constrained; for this phase it should remain terminal/Codex-visible rather than web-first.
- Repo-root auto-detection must be helpful without becoming magical or ambiguous in multi-workspace settings.

## Decision Summary

- Build a harder command-routing surface beyond skill prose alone.
- Start with read-only commands because they are safer and enough to prove the routing boundary.
- Treat visible guidance as part of the core deliverable, not a nice-to-have.
- Reuse existing Typer commands and command handlers instead of duplicating proof logic.
- Keep the wrapper generic enough that later mutation workflows can plug into the same routing layer.

## Validation Architecture

- **Framework:** pytest-based wrapper and CLI smoke tests
- **Quick run command:** `pytest tests/test_cli.py -q`
- **Full run command:** `pytest tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q`
- **Validation focus:** prove that a Codex-facing wrapper can discover, route, and execute read-only proof commands while remaining guided and readable
- **Evidence sources:** wrapper command outputs, CLI smoke tests, command catalog rendering, and root-resolution behavior
- **Manual observation:** whether the wrapper feels like a visible, guided product surface in Codex rather than a raw shell alias

---

*Phase: 10-command-invocation-surface*
*Context gathered: 2026-04-30*
