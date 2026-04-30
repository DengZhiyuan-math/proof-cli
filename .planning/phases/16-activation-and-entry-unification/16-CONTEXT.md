# Phase 16: Activation and Entry Unification - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase makes the global plugin path understandable and testable for a real user.

The main problem is no longer packaging or tool availability. It is ambiguity: the project now has repo-local skills, global skills, `proof codex ...`, and plugin-backed MCP tools. This phase exists to explain which surface is canonical, which is only a fallback, and which is for debugging.

</domain>

<decisions>
## Implementation Decisions

- **D-01:** The global plugin-backed tool surface should be treated as the canonical Codex path once installed.
- **D-02:** `proof codex ...` remains the explicit CLI fallback and debugging path.
- **D-03:** `$proof ...` remains a soft trigger and compatibility bridge, not the primary trust anchor.
- **D-04:** Repo-local skills remain development/debug aids only.
- **D-05:** This phase is documentation and entry-clarification work, not a new proof-state feature phase.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/zhdeng/Proof CLI /plugins/proof-routing/scripts/install_home_plugin.py`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/skills/proof-routing/SKILL.md`
- `/Users/zhdeng/.codex/skills/proof/SKILL.md`
- `/Users/zhdeng/Proof CLI /.agents/skills/proof/SKILL.md`
- `/Users/zhdeng/Proof CLI /.agents/skills/proof-cli/SKILL.md`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/.codex-plugin/plugin.json`
- `/Users/zhdeng/Proof CLI /plugins/proof-routing/.mcp.json`

</canonical_refs>

---

*Phase: 16-activation-and-entry-unification*
*Context gathered: 2026-04-30*
