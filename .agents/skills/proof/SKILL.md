---
name: "proof"
description: "Run Mathematical Proof CLI commands from Codex using $proof command-style triggers"
metadata:
  short-description: "Proof CLI command trigger"
---

<codex_skill_adapter>
## A. Skill Invocation
- This skill is invoked by mentioning `$proof`.
- Treat all user text after `$proof` as `{{PROOF_ARGS}}`.
- If no arguments are present, treat `{{PROOF_ARGS}}` as empty and show the available Proof Codex commands.

## B. Command Routing
- `$proof status` means: run `proof codex status --root <repo root>`.
- `$proof theorem list` means: run `proof codex theorem list --root <repo root>`.
- `$proof theorem show <id>` means: run `proof codex theorem show <id> --root <repo root>`.
- `$proof theorem add` means: run `proof codex theorem add --root <repo root>` for the guided mutation entry.
- `$proof new theorem` means: run `proof codex new theorem --root <repo root>`.
- `$proof obligation list` means: run `proof codex obligation list --root <repo root>`.
- `$proof obligation add` means: run `proof codex obligation add ... --root <repo root>`.
- `$proof blocker list` means: run `proof codex blocker list --root <repo root>`.
- `$proof blocker add` means: run `proof codex blocker add ... --root <repo root>`.
- `$proof search <query>` means: run `proof codex search "<query>" --root <repo root>`.
- `$proof retrieve <query>` means: run `proof codex retrieve "<query>" --root <repo root>`.
- `$proof project analyze` means: run `proof codex project analyze --root <repo root>`.
- `$proof snapshot` means: run `proof codex snapshot --root <repo root>`.
- `$proof export` means: inspect state first, then route to the relevant export flow.

## C. Execution Defaults
- If the current working directory contains a Proof CLI workspace, use it as `<repo root>`.
- Otherwise, use `/Users/zhdeng/Proof CLI ` as the default repo root.
- Prefer executing `proof codex ...` as the guided entry surface.
- If the command would mutate proof state and key theorem details are missing, ask only for the minimum missing detail.
- If the `proof` executable is unavailable, report the problem clearly and suggest the next command. Do not auto-install anything.
</codex_skill_adapter>

# Proof Command Trigger

This project-local copy exists mainly for repository debugging and development. The canonical everyday entry path is the global Proof Routing plugin tool surface once installed; the global `~/.codex/skills/proof/` skill is the fallback bridge when plugin tools are unavailable.

Use this skill when the user writes a command beginning with `$proof`, such as:

- `$proof status`
- `$proof theorem list`
- `$proof new theorem`
- `$proof theorem add`
- `$proof search radial system`

The text after `$proof` is the intended Proof CLI command. Resolve it through the hard wrapper first, then let the wrapper call the underlying Proof CLI logic.

## Routing

- `$proof status` -> run `proof codex status --root <repo root>`
- `$proof theorem list` -> run `proof codex theorem list --root <repo root>`
- `$proof theorem show <id>` -> run `proof codex theorem show <id> --root <repo root>`
- `$proof theorem add` -> run `proof codex theorem add --root <repo root>`
- `$proof new theorem` -> run `proof codex new theorem --root <repo root>`
- `$proof obligation list` -> run `proof codex obligation list --root <repo root>`
- `$proof obligation add` -> run `proof codex obligation add ... --root <repo root>`
- `$proof blocker list` -> run `proof codex blocker list --root <repo root>`
- `$proof blocker add` -> run `proof codex blocker add ... --root <repo root>`
- `$proof search <query>` -> run `proof codex search "<query>" --root <repo root>`
- `$proof retrieve <query>` -> run `proof codex retrieve "<query>" --root <repo root>`
- `$proof project analyze` -> run `proof codex project analyze --root <repo root>`
- `$proof snapshot` -> run `proof codex snapshot --root <repo root>`
- `$proof doctor` -> run `proof codex doctor`

If the command is unclear, inspect state first with `proof codex status --root <repo root>`, then ask only for the missing detail needed to continue.

## Default Repo Root

When working in this repository, use:

`/Users/zhdeng/Proof CLI `

as the default `--root` value unless the user provides a different root.

## Working Rules

- Treat the local `proof` executable as the source of truth.
- Prefer plugin-backed MCP tools over `$proof ...` when the Proof Routing plugin is installed.
- Treat `proof codex` as the guided Codex-facing entry surface.
- Treat the global `~/.codex/skills/proof/` skill as canonical; treat this project-local copy as a debug/development helper.
- For mutating commands, expect the wrapper to show the selected root and whether persisted state will change.
- Prefer local project state before new proof search.
- Keep proof-state changes small and auditable.
- Do not silently decide mathematical truth; keep the human review boundary explicit.
- Use retrieval before proposing a new proof route.
- Validate command behavior with the smallest relevant `proof` command or test.
