---
phase: 11-mutation-routing-and-root-resolution
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 10-command-invocation-surface
    provides: the `proof codex` wrapper, command catalog, and baseline root discovery
files_modified:
  - src/proof_cli/codex_router.py
  - src/proof_cli/cli.py
  - src/proof_cli/commands.py
  - src/proof_cli/services.py
  - tests/test_cli.py
  - .agents/skills/proof/SKILL.md
  - .agents/skills/proof-cli/SKILL.md
  - /Users/zhdeng/.codex/skills/proof/SKILL.md
  - /Users/zhdeng/.codex/skills/proof-cli/SKILL.md
autonomous: true
requirements:
  - CMD-04
  - MUT-01
  - MUT-02
  - MUT-03
must_haves:
  truths:
    - mutation routing must use Proof CLI as the write engine
    - root selection for writes must be deterministic and explainable
    - the wrapper should ask only for the minimum missing details
    - read-only and mutating command paths must stay visibly distinct
    - the user experience should remain guided and Codex-friendly rather than falling back to raw undocumented command strings
  artifacts:
    - src/proof_cli/codex_router.py
    - src/proof_cli/cli.py
    - tests/test_cli.py
  key_links:
    - preserve the Phase 10 wrapper rather than bypassing it
    - preserve human review and trust-boundary clarity in all mutation outputs
---

<objective>
Implement safe mutation routing on top of the new `proof codex` wrapper.

Purpose: make Codex able to create or update proof workspace state through the wrapper itself, not just inspect the workspace. The wrapper should now handle theorem creation, obligation creation, blocker creation, and snapshots through the existing Proof CLI commands while resolving roots predictably and asking only for the smallest missing input.
</objective>

<threat_model>
## Threat Model

### High severity
- The wrapper writes to the wrong workspace because root selection is ambiguous.
  - Mitigation: centralize root precedence, expose the selected root in mutation output, and add tests for explicit/global/project-local routing.

- The wrapper re-implements proof-state mutations and drifts from the core CLI behavior.
  - Mitigation: call existing mutation commands or handlers instead of introducing a second write path.

- Codex hides state mutation behind overly friendly language, weakening the trust boundary.
  - Mitigation: make mutation outputs explicitly say that persisted proof state will be changed and which workspace root is targeted.

### Medium severity
- The theorem creation flow asks for too much information and becomes frustrating to use.
  - Mitigation: require only theorem id, name, and statement at first; keep the rest as explicit optional flags.

- Different mutation commands behave inconsistently.
  - Mitigation: standardize mutation entry behavior around the same routing, root, and missing-detail rules.

### Low severity
- Skills and wrapper vocabulary drift apart again.
  - Mitigation: update local and global skills to describe the same mutation command surface after implementation.
</threat_model>

<tasks>

<task type="auto">
  <name>Centralize mutation-safe root resolution and command classification</name>
  <files>src/proof_cli/codex_router.py, src/proof_cli/cli.py, tests/test_cli.py</files>
  <action>Refine the Phase 10 root resolver into a mutation-safe shared path that clearly classifies read-only versus mutating commands. Keep explicit `--root` and `PROOF_ROOT` precedence, but make write flows surface the selected workspace more clearly and avoid silently mutating an accidental fallback target. Expose this behavior through wrapper output and tests.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - root precedence is deterministic for common write scenarios
    - mutation commands clearly expose the selected root
    - the wrapper distinguishes read-only and mutating commands in code and user-facing behavior
    - root behavior is covered by tests, not just prose
  </acceptance_criteria>
  <done>Mutation routing uses deterministic and explainable root resolution</done>
</task>

<task type="auto">
  <name>Implement wrapper mutation routing for theorem, obligation, blocker, and snapshot flows</name>
  <files>src/proof_cli/codex_router.py, src/proof_cli/commands.py, src/proof_cli/services.py, src/proof_cli/cli.py, tests/test_cli.py</files>
  <action>Add real mutating wrapper commands that route through the existing Proof CLI logic for theorem add, obligation add, blocker add, and snapshot. Theorem creation should support a guided minimal contract path, while obligation, blocker, and snapshot should use lighter-weight routing that still preserves explicit state-change messaging.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - theorem, obligation, blocker, and snapshot mutations can be initiated through `proof codex`
    - wrapper mutations use existing Proof CLI handlers or commands rather than manual state edits
    - snapshot is end-to-end runnable through the wrapper
    - user-facing mutation messaging remains explicit about persisted state changes
  </acceptance_criteria>
  <done>The wrapper can perform the core proof-state mutations directly</done>
</task>

<task type="auto">
  <name>Support minimum-missing-detail prompts and align skills with the hardened mutation surface</name>
  <files>src/proof_cli/codex_router.py, tests/test_cli.py, .agents/skills/proof/SKILL.md, .agents/skills/proof-cli/SKILL.md, /Users/zhdeng/.codex/skills/proof/SKILL.md, /Users/zhdeng/.codex/skills/proof-cli/SKILL.md</files>
  <action>Teach the wrapper to ask only for missing theorem, obligation, or blocker details rather than dumping full low-level usage text. Update local and global Codex skills so `$proof ...` describes the hardened mutation surface accurately. Add smoke tests that prove the minimal-detail behavior and wrapper command vocabulary stay aligned.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - underspecified mutation flows produce minimal next-step guidance
    - theorem creation does not require unnecessary fields up front
    - skill docs and wrapper command semantics match
    - smoke tests cover at least one minimal-detail mutation path
  </acceptance_criteria>
  <done>The mutation surface is guided, aligned, and practical for Codex use</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] `proof codex` can run core mutations, not just inspection commands
- [ ] root targeting for writes is deterministic and explicit
- [ ] the wrapper asks only for the minimum missing mutation details
- [ ] mutation flows still use Proof CLI as the source of truth
- [ ] local/global Codex-facing docs match the implemented mutation surface

</verification>

<success_criteria>

- Codex can safely route theorem, obligation, blocker, and snapshot mutations through the wrapper.
- Root resolution is predictable enough for both project-local and global Codex usage.
- Mutation guidance is concise and practical rather than dumping raw CLI internals.
- The explicit trust boundary remains visible even when the wrapper feels friendlier.

</success_criteria>
