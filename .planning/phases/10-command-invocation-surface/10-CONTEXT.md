# Phase 10: Command Invocation Surface - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase makes Codex-facing `proof` command entry deterministic enough to behave like a real product surface instead of a loose skill hint.

The phase is about the first hard layer between Codex and Proof CLI: a stable invocation surface for read-only proof commands, a command catalog that Codex can rely on, and a guided user experience that feels visible and understandable inside Codex and the terminal.

The phase is not about full browser UI, full theorem-mutation ergonomics, or marketplace packaging. It is about building a dependable first command boundary that is general enough to work globally, visible enough to orient users, and guided enough to reduce friction.

</domain>

<decisions>
## Implementation Decisions

### Invocation shape
- **D-01:** The command surface should no longer rely on skill prose alone. Phase 10 should introduce a harder wrapper or routing entry point that Codex can target deterministically.
- **D-02:** The Proof CLI remains the execution engine and source of truth. The wrapper layer should route into existing CLI behavior rather than re-implement proof-state logic.
- **D-03:** Phase 10 should focus on read-only commands first: status, theorem list/show, obligation list, blocker list, search, retrieve, and project analysis.

### Visualized and guided UX
- **D-04:** "Visualized" means structured, glanceable command UX inside Codex and the terminal: clear command names, grouped command categories, readable help output, and obvious next actions.
- **D-05:** "Guided" means the system should expose a command catalog and friendly prompts so the user is not required to remember every subcommand or root flag.
- **D-06:** The first visible layer should feel productized, not like raw shell plumbing. Rich terminal output, structured JSON where appropriate, and readable command summaries are all in scope.

### General and reusable behavior
- **D-07:** The invocation surface should work both as a project-local integration and as a global Codex skill or wrapper entry point.
- **D-08:** Repo-root resolution should be deterministic enough that users do not have to manually pass `--root` for ordinary read-only inspection flows.
- **D-09:** This phase should establish a stable abstraction that later phases can reuse for mutating commands instead of hardcoding per-command skill behavior.

### the agent's Discretion
- Whether the harder boundary is best expressed as a dedicated `proof-codex` executable, a `proof codex ...` command family, or both.
- Whether command metadata should live in Python structures, a machine-readable manifest, or a hybrid arrangement.
- How much of the guided experience should be rendered through Rich versus plain JSON for downstream routing.

</decisions>

<specifics>
## Specific Ideas

- The user wants Proof CLI to become "visualized, general, guided, and easy to use" inside Codex.
- The user is asking for a harder command-routing plugin or wrapper, not another round of looser skill descriptions.
- The first experience should make `$proof status` and related commands feel natural and dependable.
- The first phase should bias toward read-only inspection flows because they are safer, easier to validate, and enough to prove that the routing layer is real.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `/Users/zhdeng/Proof CLI /.planning/PROJECT.md` - milestone framing, constraints, and why the command boundary now matters
- `/Users/zhdeng/Proof CLI /.planning/REQUIREMENTS.md` - Phase 10 requirement vocabulary and traceability
- `/Users/zhdeng/Proof CLI /.planning/ROADMAP.md` - phase dependency ordering and success criteria
- `/Users/zhdeng/Proof CLI /.planning/STATE.md` - current milestone state

### Existing command surfaces
- `/Users/zhdeng/Proof CLI /src/proof_cli/cli.py` - main Typer app and current CLI command registration
- `/Users/zhdeng/Proof CLI /src/proof_cli/commands.py` - command implementations and output shape
- `/Users/zhdeng/Proof CLI /src/proof_cli/services.py` - workspace-facing helpers that can support a wrapper layer
- `/Users/zhdeng/Proof CLI /pyproject.toml` - console script registration for `proof`

### Existing Codex-facing skill surfaces
- `/Users/zhdeng/Proof CLI /.agents/skills/proof/SKILL.md` - project-local Codex skill entry
- `/Users/zhdeng/Proof CLI /.agents/skills/proof-cli/SKILL.md` - project-local Proof CLI skill guidance
- `/Users/zhdeng/.codex/skills/proof/SKILL.md` - global Codex skill entry for `$proof`
- `/Users/zhdeng/.codex/skills/proof-cli/SKILL.md` - global alias skill

### Relevant tests
- `/Users/zhdeng/Proof CLI /tests/test_cli.py` - CLI command invocation coverage
- `/Users/zhdeng/Proof CLI /tests/test_retrieval.py` - retrieval command shape and read-only inspection behavior
- `/Users/zhdeng/Proof CLI /tests/test_phase9_validation.py` - current end-to-end theorem workflow that later Codex routing should be able to reach

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `cli.py` already centralizes command registration through Typer, so a wrapper can likely reuse existing command implementations rather than inventing a second logic stack.
- `commands.py` already separates read-only command handlers like `cmd_status`, `cmd_theorem_list`, `cmd_proof_retrieve`, and `cmd_project_analyze`.
- Rich is already available as a dependency, so the command wrapper can provide more visible, guided terminal output without adding a new UI stack.

### Established Patterns
- The project already distinguishes read-only inspection flows from state-mutating flows in the command layer.
- JSON-first outputs already exist for retrieval and analysis, which gives the wrapper a structured substrate for Codex routing.
- The current skill-based routing is descriptive but not deterministic enough; this is the exact boundary Phase 10 should harden.

### Integration Points
- A wrapper or plugin layer should call into existing `commands.py` handlers or the existing CLI entrypoint, not fork behavior.
- The codex-facing entry point should connect to project-local and global skills so both use the same routing engine.
- The first visible UX should orient the user toward the next valid read-only command rather than dropping them into a raw parser error.

</code_context>

<deferred>
## Deferred Ideas

- Rich theorem creation forms and guided mutating workflows belong to later phases once the command boundary is stable.
- Browser-based command dashboards stay out of scope for this phase.
- Full plugin marketplace packaging can wait until the local and global wrapper behavior is proven.

</deferred>

---

*Phase: 10-command-invocation-surface*
*Context gathered: 2026-04-30*
