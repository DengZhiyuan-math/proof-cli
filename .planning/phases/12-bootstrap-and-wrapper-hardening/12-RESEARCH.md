---
phase: 12-bootstrap-and-wrapper-hardening
type: research
focus: degraded-environment behavior, command fallback, skill-source clarity
date: 2026-04-30
---

# Phase 12 Research

## Research Question

How should the Codex-facing Proof CLI wrapper behave when local command availability or skill scope is incomplete, while preserving a deterministic and user-controlled workflow?

## Findings

### 1. The current wrapper assumes the executable path is already healthy

Phases 10 and 11 established a solid command surface:

- `proof codex ...`
- `proof-codex ...`
- aligned skill vocabulary
- deterministic read/write root handling

But they largely assume the command entry points already exist and work. Phase 12 needs to explicitly model the unhappy path rather than letting failures surface as generic shell or Typer errors.

### 2. Auto-install would conflict with the product boundary

The user explicitly clarified that this system is a mathematical proof assistant workflow, not a programming assistant that should manipulate the environment on the user's behalf.

That means:

- no automatic `pip install -e ".[dev]"` retries
- no silent environment rewrites
- no "helpful" automatic mutation of the user's Python setup

The correct Phase 12 behavior is:

- detect the problem
- explain it clearly
- provide the next command(s) the user can choose to run

### 3. "Bootstrap" should be interpreted narrowly

For this milestone, bootstrap means command-layer readiness checks such as:

- `proof` missing from PATH
- `proof-codex` unavailable
- wrapper invocation surface incomplete
- skill scope ambiguity between project-local and global routing

It should not expand into:

- full environment managers
- package installers
- project initializers unrelated to command routing

This keeps the phase aligned with `BST-01` and `BST-02`.

### 4. Global skill should be canonical, project-local skill should be diagnostic

The user explicitly wants:

- global `~/.codex/skills/proof/` as the real entry point
- repo-local skill copies primarily for debugging and development

So Phase 12 should reinforce this in two ways:

1. behavior and docs should point users toward the global skill as the default mental model
2. project-local skills should remain available, but their role should be documented as local debugging/development support

### 5. The most useful failures are categorized failures

Instead of one vague "proof command failed" path, the wrapper should probably separate:

- executable missing
- wrapper entry missing
- workspace invalid
- command routing mismatch

That makes the next-step guidance short and actionable.

### 6. Hardening should stay terminal-native

The current milestone explicitly excludes browser-first remediation flows. So the best hardening pattern is:

- human-readable terminal error
- short explanation
- exact next command(s)
- optional machine-readable check surface only if it helps downstream validation

## Recommendations

1. Add a dedicated diagnostic layer for command availability and wrapper readiness.
2. Standardize degraded-environment messages across `proof codex` and related skills.
3. Do not auto-install anything; only recommend commands.
4. Clarify the role split between global skills and project-local debug skills.
5. Validate degraded-environment behavior with CLI smoke tests and simulated failure cases.

## Planning Implications

- Phase 12 should implement explicit error-classification and recovery messaging.
- The plan should include at least one task around diagnostic normalization, not just skill text cleanup.
- Tests should simulate unavailable executable or unavailable wrapper conditions in a controlled way.
