# Proof Routing Plugin

This plugin is the canonical Codex-facing integration layer for Proof CLI once it is installed globally.

## Entry Hierarchy

Use the surfaces in this order:

1. **Plugin-backed MCP tools**: primary Codex path
2. **`proof codex ...`**: explicit CLI fallback and debugging path
3. **`$proof ...`**: compatibility trigger only, not the hard execution guarantee

## Install

From the repository root:

```bash
python plugins/proof-routing/scripts/install_home_plugin.py
```

This installs:

- `~/plugins/proof-routing`
- `~/.agents/plugins/marketplace.json`

## Enable

1. Restart Codex after installation.
2. Ensure Codex can see the home-local plugin marketplace.
3. Prefer plugin tools from `proof-routing` when available.

## Verify

CLI fallback checks:

```bash
proof codex doctor
proof codex status --root "/Users/zhdeng/Proof CLI "
```

Plugin packaging checks:

```bash
python -m pytest tests/test_proof_routing_plugin.py -q
```

Quick end-to-end path:

```bash
python plugins/proof-routing/scripts/install_home_plugin.py
proof codex doctor
proof codex status --root "/Users/zhdeng/Proof CLI "
```

## Surface Relationship

- The plugin does **not** replace Proof CLI.
- The plugin calls the existing `proof codex ...` wrapper.
- Repo-local skills under `.agents/skills/` are for repository debugging and development.
- The global `~/.codex/skills/proof/` skill is a fallback bridge until plugin-backed tools are the normal path in everyday use.
