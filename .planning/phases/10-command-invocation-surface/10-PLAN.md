---
phase: 10-command-invocation-surface
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 08-retrieval-and-snapshots
    provides: JSON-first retrieval and analysis outputs that a Codex wrapper can expose
  - phase: 09-radial-system-validation
    provides: a small theorem workflow that later validation can reuse through the command layer
files_modified:
  - src/proof_cli/cli.py
  - src/proof_cli/commands.py
  - src/proof_cli/services.py
  - pyproject.toml
  - .agents/skills/proof/SKILL.md
  - .agents/skills/proof-cli/SKILL.md
  - /Users/zhdeng/.codex/skills/proof/SKILL.md
  - /Users/zhdeng/.codex/skills/proof-cli/SKILL.md
  - tests/test_cli.py
  - tests/test_retrieval.py
  - tests/test_phase9_validation.py
autonomous: true
requirements:
  - CMD-01
  - CMD-02
  - CMD-03
must_haves:
  truths:
    - Codex command entry must become deterministic rather than relying on skill prose alone
    - the first hard wrapper should focus on read-only commands
    - the user-facing experience should be visible, guided, and easier to use inside Codex and the terminal
    - the wrapper must remain general enough to support both project-local and global Codex usage
    - the existing Proof CLI remains the execution engine and source of truth
  artifacts:
    - src/proof_cli/cli.py
    - src/proof_cli/commands.py
    - src/proof_cli/services.py
    - pyproject.toml
    - tests/test_cli.py
  key_links:
    - keep wrapper dispatch aligned with existing Typer and command handler patterns
    - keep guidance visible through structured output rather than browser UI
    - keep the phase focused on the first dependable command boundary, not full mutation ergonomics
---

<objective>
Implement the first hard Codex-facing command surface for Proof CLI.

Purpose: make `proof` commands feel like a dependable, visible, guided interface inside Codex and the terminal. Phase 10 should establish a stable routing layer for read-only commands, command discovery, and readable guidance so users can inspect proof state without relying on fragile skill-text behavior.

Execution split:
1. Build a deterministic wrapper or routing entry for read-only Proof CLI commands.
2. Add a visible command catalog and guided output layer so the wrapper feels like a product surface.
3. Align project-local and global Codex skills with the wrapper and lock the behavior down with smoke tests.
</objective>

<threat_model>
## Threat Model

### High severity
- Codex still interprets `proof` commands as loose text after Phase 10.
  - Mitigation: introduce a dedicated wrapper entry point and route skills toward it instead of leaving routing semantics implicit.

- The wrapper duplicates Proof CLI logic and drifts from the actual command layer.
  - Mitigation: call existing command handlers or the existing CLI registration layer wherever possible, keeping Proof CLI as the sole execution engine.

- The new layer looks technical but not usable, leaving users unsure what command to run next.
  - Mitigation: include a visible command catalog, grouped command discovery, and explicit next-step guidance as first-class outputs.

### Medium severity
- Repo-root auto-detection feels magical or ambiguous.
  - Mitigation: keep the first phase conservative, prefer obvious current-project resolution, and show the selected root in guided/help output.

- Rich or visual output becomes hard to test or parse.
  - Mitigation: keep a machine-readable substrate under the visible layer and test both dispatch and readable guidance at the wrapper boundary.

### Low severity
- Global and project-local skills diverge slightly.
  - Mitigation: point both skill layers at the same wrapper semantics and keep command vocabulary centralized.
</threat_model>

<tasks>

<task type="auto">
  <name>Build a deterministic Codex-facing wrapper for read-only commands</name>
  <files>src/proof_cli/cli.py, src/proof_cli/commands.py, src/proof_cli/services.py, pyproject.toml, tests/test_cli.py</files>
  <action>Create a dedicated command-routing surface for Codex, preferably as a wrapper executable or a dedicated `proof codex` family, that handles read-only commands like status, theorem list/show, obligation list, blocker list, search, retrieve, and project analysis. Route into the existing Proof CLI command layer instead of re-implementing proof-state logic. Make repo-root selection deterministic for the common single-project case and expose it clearly in the wrapper output.</action>
  <verify>pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - there is a harder command-routing surface beyond prose-only skill descriptions
    - read-only commands can be dispatched deterministically through the wrapper
    - the wrapper reuses the existing Proof CLI execution layer
    - repo-root behavior is explicit and deterministic enough for common Codex usage
  </acceptance_criteria>
  <done>Codex has a stable read-only command wrapper for Proof CLI</done>
</task>

<task type="auto">
  <name>Add visible command discovery and guided output</name>
  <files>src/proof_cli/cli.py, src/proof_cli/commands.py, src/proof_cli/services.py, tests/test_cli.py</files>
  <action>Add a command catalog or command-palette-style help surface for the wrapper so users can see grouped commands, short descriptions, selected root, and likely next actions. Use readable terminal output so the system feels visible and guided inside Codex without requiring a browser UI. Keep machine-readable support where it already exists, but make the default discovery path human-friendly.</action>
  <verify>pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - the wrapper exposes a visible command discovery surface
    - command groups and short descriptions are readable inside the terminal/Codex context
    - the output helps orient the user toward the next useful read-only command
    - the phase meaningfully improves usability beyond raw command dispatch
  </acceptance_criteria>
  <done>The command layer is visible and guided rather than only routable</done>
</task>

<task type="auto">
  <name>Align global and project-local Codex integration with smoke tests</name>
  <files>.agents/skills/proof/SKILL.md, .agents/skills/proof-cli/SKILL.md, /Users/zhdeng/.codex/skills/proof/SKILL.md, /Users/zhdeng/.codex/skills/proof-cli/SKILL.md, tests/test_cli.py, tests/test_retrieval.py, tests/test_phase9_validation.py</files>
  <action>Update project-local and global Codex skills so they target the same wrapper semantics and command vocabulary. Add smoke tests that cover representative read-only commands and prove the Codex-facing wrapper can reach real Proof CLI functionality. Reuse a small theorem workflow as a reality check where it helps prove the wrapper is genuinely useful.</action>
  <verify>pytest tests/test_cli.py tests/test_retrieval.py tests/test_phase9_validation.py -q</verify>
  <acceptance_criteria>
    - global and project-local `proof` skill entry points describe the same wrapper behavior
    - smoke tests cover representative read-only wrapper routes
    - the command layer is general enough for both global and project-local Codex usage
    - the wrapper is proven against real proof-work inspection behavior, not just synthetic parsing
  </acceptance_criteria>
  <done>Codex-facing command routing is aligned and smoke-tested</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] Codex has a deterministic read-only `proof` command surface
- [ ] the wrapper feels visible and guided inside Codex or the terminal
- [ ] command routing remains general enough for global and project-local use
- [ ] existing Proof CLI logic remains the source of truth
- [ ] smoke tests prove the wrapper reaches real proof-work commands

</verification>

<success_criteria>

- Codex can invoke read-only Proof CLI commands through a deterministic command entry point.
- The first command surface is visible, guided, and easier to use than raw skill prose alone.
- Repo-root resolution is predictable enough for ordinary Codex usage.
- The wrapper remains general enough to support both global and project-local command entry.
- The routing layer is validated with smoke tests against real Proof CLI behavior.

</success_criteria>
