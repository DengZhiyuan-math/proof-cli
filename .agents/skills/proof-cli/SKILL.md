---
name: "proof-cli"
description: "Work with the Mathematical Proof CLI / Research Proof OS repository, including command-style triggers"
metadata:
  short-description: "Proof CLI project skill"
---

# Proof CLI

Use this skill when working in the `Mathematical Proof CLI / Research Proof OS` repository.

This project-local skill is primarily for repository debugging and development work. The canonical user-facing entry path is the global `~/.codex/skills/proof/` skill.

## Command-style triggers

If the user writes a short command such as:

- `$proof theorem add`
- `$proof new theorem`
- `$proof status`
- `$proof search ...`

treat it as an instruction to run the matching Proof Codex wrapper flow directly.

Prefer these shortcuts as canonical entry points for Codex:

- `$proof status` -> `proof codex status`
- `$proof theorem list` -> `proof codex theorem list`
- `$proof theorem add` / `$proof new theorem` -> `proof codex theorem add` or `proof codex new theorem`
- `$proof obligation list` / `$proof obligation add` -> `proof codex obligation list` or `proof codex obligation add`
- `$proof blocker list` / `$proof blocker add` -> `proof codex blocker list` or `proof codex blocker add`
- `$proof search <query>` -> `proof codex search <query>`
- `$proof retrieve <query>` -> `proof codex retrieve <query>`
- `$proof project analyze` -> `proof codex project analyze`
- `$proof snapshot` -> `proof codex snapshot`
- `$proof doctor` -> `proof codex doctor`

When a command is underspecified, choose the smallest safe default and ask for only the minimum missing detail.

## Setup

- Install the project with:
  - `python -m pip install -e ".[dev]"`
- Confirm CLI availability with:
  - `proof --help`
  - `proof codex`
  - `proof-codex status`
  - `proof codex doctor`

## What to do first

- Treat the `proof` executable as the source of truth.
- Treat `proof codex` and `proof-codex` as the hard Codex-facing command surface.
- Prefer local project state over new search.
- Check `proof codex status --root <root>` before making assumptions about current proof state.
- When inspecting a workspace, prefer this order:
  1. `proof codex status --root <root>`
  2. `proof codex theorem list --root <root>`
  3. `proof codex obligation list --root <root>`
  4. `proof codex blocker list --root <root>`
- Use retrieval-first inspection before inventing new work:
  - `proof codex search "<query>"`
  - `proof codex retrieve "<query>"`
  - `proof theorem list`
  - `proof reference list`
  - `proof memory list`

## Common commands

- `proof --help`
- `proof codex`
- `proof-codex status`
- `proof codex status`
- `proof codex theorem list`
- `proof codex theorem show <theorem_id>`
- `proof codex search "<query>"`
- `proof codex retrieve "<query>"`
- `proof codex project analyze --query "<query>"`
- `proof codex new theorem`
- `proof codex theorem add`
- `proof codex obligation add "<goal_statement>"`
- `proof codex blocker add "<description>"`
- `proof codex snapshot`
- `proof init`
- `proof theorem extract <theorem_id>`
- `proof reference list`
- `proof memory list`
- `proof debug list`
- `proof bug list`
- `proof snapshot`

## Usage pattern

For interactive Codex work, prefer this pattern:

1. User issues a short `$proof ...` command.
2. Resolve the command to the corresponding `proof codex` action first.
3. Let the wrapper call the underlying Proof CLI logic.
4. Inspect current workspace state before mutating anything.
5. Keep proof changes small, local, and auditable.
6. Validate with the smallest relevant test or command set.

## Working conventions

- Retrieval first: check existing project results and trusted references before proposing new proof search.
- Prefer using the `proof` CLI instead of editing workspace state files by hand.
- Do not manually edit persisted proof workspace files unless explicitly asked.
- Keep state local and auditable.
- Respect the human review boundary for imported results and trust changes.
- For write commands, the wrapper should show the selected root and make the persisted-state change explicit.
- If command entrypoints are unavailable, surface the error and the next command to run; do not auto-install tooling.
- If a task affects proof state, update or inspect the persisted workspace state rather than relying on chat memory.
- Preserve backward compatibility of existing CLI flows unless explicitly asked otherwise.

## Validation

- After changing CLI behavior, run tests.
- When developing the CLI itself, run:
  - `python -m pytest -q`
- Relevant `proof` or `proof codex` commands should succeed.
- Tests should pass or failures should be explained clearly.
