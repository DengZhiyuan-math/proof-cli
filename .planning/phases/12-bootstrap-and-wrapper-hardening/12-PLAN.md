---
phase: 12-bootstrap-and-wrapper-hardening
plan: 01
type: execute
wave: 1
depends_on:
  - phase: 10-command-invocation-surface
    provides: the initial hard wrapper and guided command catalog
  - phase: 11-mutation-routing-and-root-resolution
    provides: write-safe root routing and minimum-missing-detail mutation behavior
files_modified:
  - src/proof_cli/codex_router.py
  - src/proof_cli/cli.py
  - pyproject.toml
  - tests/test_cli.py
  - .agents/skills/proof/SKILL.md
  - .agents/skills/proof-cli/SKILL.md
  - /Users/zhdeng/.codex/skills/proof/SKILL.md
  - /Users/zhdeng/.codex/skills/proof-cli/SKILL.md
autonomous: true
requirements:
  - BST-01
  - BST-02
must_haves:
  truths:
    - missing executable states must be detected and explained clearly
    - the system must not auto-install or auto-repair the local environment
    - global skill configuration is the canonical user-facing entry path
    - project-local skill copies remain debugging and development helpers only
    - degraded command-layer behavior should stay terminal-native and deterministic
  artifacts:
    - src/proof_cli/codex_router.py
    - tests/test_cli.py
    - /Users/zhdeng/.codex/skills/proof/SKILL.md
  key_links:
    - preserve the wrapper semantics already established in Phases 10 and 11
    - keep explicit user control over environment changes
---

<objective>
Harden the Codex command layer when the local environment is incomplete.

Purpose: make unavailable-command and mixed-scope situations deterministic and understandable. Phase 12 should detect missing or degraded command entry points, explain what is wrong, and tell the user what to run next, without auto-installing or silently rewriting the environment.
</objective>

<threat_model>
## Threat Model

### High severity
- The wrapper silently mutates the environment while trying to recover.
  - Mitigation: forbid automatic install/repair behavior and keep recovery messaging advisory only.

- Global and project-local skills produce ambiguous or conflicting user expectations.
  - Mitigation: make the global skill canonical in wording and behavior, and label local skills as debugging/development helpers.

- Missing command availability collapses into generic errors that users cannot act on.
  - Mitigation: classify degraded states and provide explicit next-step commands.

### Medium severity
- Error handling drifts across entry points and becomes inconsistent.
  - Mitigation: centralize command-readiness checks and reuse a shared diagnostic rendering path.

- Hardening work accidentally weakens the normal happy-path wrapper behavior.
  - Mitigation: preserve existing read/write smoke coverage while adding degraded-state tests.

### Low severity
- Documentation says one thing while command behavior says another.
  - Mitigation: update both global and project-local skills alongside the implementation.
</threat_model>

<tasks>

<task type="auto">
  <name>Implement command-readiness diagnostics without automatic environment repair</name>
  <files>src/proof_cli/codex_router.py, src/proof_cli/cli.py, tests/test_cli.py</files>
  <action>Add a shared readiness/diagnostic path that can recognize missing `proof` or `proof-codex` entry points, degraded wrapper availability, and invalid command-layer startup states. Return clear terminal-native explanations and concrete next commands, but never auto-install or auto-repair anything.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - missing or degraded command-entry states are detected deliberately
    - recovery messaging is explicit and actionable
    - no automatic installation or environment mutation occurs
    - the behavior is covered by tests rather than only by skill prose
  </acceptance_criteria>
  <done>The command layer explains degraded readiness states clearly and safely</done>
</task>

<task type="auto">
  <name>Clarify canonical global skill routing versus project-local debug routing</name>
  <files>.agents/skills/proof/SKILL.md, .agents/skills/proof-cli/SKILL.md, /Users/zhdeng/.codex/skills/proof/SKILL.md, /Users/zhdeng/.codex/skills/proof-cli/SKILL.md, tests/test_cli.py</files>
  <action>Align local and global skill docs so the global `proof` skill is clearly the canonical user-facing entry path, while project-local skills are described as debugging and development helpers. Ensure the resulting command vocabulary is still consistent across contexts and add smoke coverage where useful.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - the global skill is clearly documented as the primary entry point
    - project-local skills are explicitly framed as repo-local debugging aids
    - skill vocabulary remains aligned with the implemented wrapper
    - there is no ambiguity about the intended normal user path
  </acceptance_criteria>
  <done>Skill scope is explicit and unambiguous</done>
</task>

<task type="auto">
  <name>Preserve normal wrapper behavior while adding degraded-state smoke tests</name>
  <files>tests/test_cli.py, src/proof_cli/codex_router.py</files>
  <action>Add smoke tests that cover representative degraded command-layer states alongside the existing happy-path wrapper behavior. The goal is to prove that hardening does not regress Phase 10/11 routing while still making failure modes deterministic and understandable.</action>
  <verify>python -m pytest tests/test_cli.py -q</verify>
  <acceptance_criteria>
    - degraded-state tests exist for at least one missing-entry or unavailable-wrapper path
    - happy-path wrapper tests still pass
    - Phase 12 hardening is validated by behavior, not just intent
  </acceptance_criteria>
  <done>The wrapper is hardened without regressing the established command surface</done>
</task>

</tasks>

<verification>
Before declaring this plan complete:
- [ ] degraded command-entry states are detected and explained cleanly
- [ ] no automatic installation or environment repair is attempted
- [ ] global skill routing is documented as canonical
- [ ] local project skills are clearly scoped as debugging/development helpers
- [ ] hardening tests preserve the existing happy path

</verification>

<success_criteria>

- Missing `proof` or `proof-codex` states produce clear, actionable terminal-native guidance.
- The system does not automatically alter the user's environment.
- Global and local skill scope is explicit and no longer ambiguous.
- Existing wrapper routing continues to work while degraded states become deterministic.

</success_criteria>
