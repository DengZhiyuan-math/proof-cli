---
name: "proof-routing"
description: "Use local MCP tools from the Proof Routing plugin instead of relying on $proof skill prose alone."
---

# Proof Routing Plugin

Use this plugin skill when the user wants Proof CLI to behave like a real Codex tool surface rather than a soft skill trigger.

## Entry hierarchy

- Prefer plugin-backed MCP tools first.
- Use `proof codex ...` as the explicit CLI fallback.
- Treat `$proof ...` as a compatibility trigger, not as the strongest execution path.

## Preferred behavior

- Prefer the plugin MCP tools over text-only skill interpretation.
- Use explicit Proof Routing tools such as:
  - `doctor`
  - `status`
  - `init`
  - `theorem_list`
  - `theorem_show`
  - `theorem_add`
  - `obligation_list`
  - `obligation_add`
  - `blocker_list`
  - `blocker_add`
  - `search`
  - `retrieve`
  - `project_analyze`
  - `snapshot`

## Working rules

- Keep Proof CLI as the source of truth.
- Use the selected root explicitly for stateful operations.
- Keep theorem-state mutations small and auditable.
- Do not silently decide mathematical truth.
- Treat repo-local `.agents/skills/` entries as debugging helpers, not the canonical everyday interface.
