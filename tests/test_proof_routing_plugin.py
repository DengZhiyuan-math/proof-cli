from __future__ import annotations

import importlib.util
import json
from pathlib import Path


PLUGIN_SERVER = Path(__file__).resolve().parent.parent / "plugins" / "proof-routing" / "scripts" / "proof_mcp_server.py"
HOME_INSTALLER = Path(__file__).resolve().parent.parent / "plugins" / "proof-routing" / "scripts" / "install_home_plugin.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("proof_mcp_server", PLUGIN_SERVER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_home_installer_module():
    spec = importlib.util.spec_from_file_location("install_home_plugin", HOME_INSTALLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_registers_expected_tools():
    module = _load_plugin_module()
    tool_names = [tool.name for tool in module.SERVER._tool_manager.list_tools()]
    assert tool_names == [
        "doctor",
        "status",
        "init",
        "theorem_list",
        "theorem_show",
        "theorem_add",
        "obligation_list",
        "obligation_add",
        "blocker_list",
        "blocker_add",
        "search",
        "retrieve",
        "project_analyze",
        "snapshot",
    ]


def test_theorem_add_routes_to_proof_codex(monkeypatch):
    module = _load_plugin_module()
    captured = {}

    def fake_run(command, capture_output, text, check):
        captured["command"] = command

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.theorem_add(
        theorem_id="tiny",
        name="Tiny theorem",
        statement="P implies P",
        assumptions=["P"],
        exports=["P"],
        notes="demo",
        root="/tmp/proof-plugin",
    )

    assert result == "ok"
    assert captured["command"] == [
        "proof",
        "codex",
        "theorem",
        "add",
        "tiny",
        "Tiny theorem",
        "P implies P",
        "--assumption",
        "P",
        "--export",
        "P",
        "--notes",
        "demo",
        "--root",
        "/tmp/proof-plugin",
    ]


def test_project_analyze_routes_to_proof_codex(monkeypatch):
    module = _load_plugin_module()
    captured = {}

    def fake_run(command, capture_output, text, check):
        captured["command"] = command

        class Result:
            returncode = 0
            stdout = "analysis"
            stderr = ""

        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.project_analyze(query="bridge", root="/tmp/proof-plugin", limit=7)

    assert result == "analysis"
    assert captured["command"] == [
        "proof",
        "codex",
        "project",
        "analyze",
        "--query",
        "bridge",
        "--limit",
        "7",
        "--root",
        "/tmp/proof-plugin",
    ]


def test_mcp_config_uses_plugin_relative_script_path():
    mcp_config = json.loads((PLUGIN_SERVER.parent.parent / ".mcp.json").read_text())
    assert mcp_config == {
        "mcpServers": {
            "proof-routing": {
                "command": "python3",
                "args": ["./scripts/proof_mcp_server.py"],
            }
        }
    }


def test_home_installer_creates_plugin_and_marketplace(tmp_path):
    module = _load_home_installer_module()
    plugin_destination, marketplace_path = module.install_home_plugin(tmp_path)

    assert plugin_destination == tmp_path / "plugins" / "proof-routing"
    assert marketplace_path == tmp_path / ".agents" / "plugins" / "marketplace.json"
    assert (plugin_destination / ".codex-plugin" / "plugin.json").exists()
    assert (plugin_destination / ".mcp.json").exists()
    assert (plugin_destination / "scripts" / "proof_mcp_server.py").exists()

    marketplace = json.loads(marketplace_path.read_text())
    assert marketplace["name"] == "proof-cli-home"
    assert marketplace["plugins"] == [
        {
            "name": "proof-routing",
            "source": {"source": "local", "path": "./plugins/proof-routing"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
    ]


def test_plugin_readme_documents_entry_hierarchy():
    readme = (PLUGIN_SERVER.parent.parent / "README.md").read_text()
    assert "Plugin-backed MCP tools" in readme
    assert "`proof codex ...`" in readme
    assert "`$proof ...`" in readme


def test_installed_plugin_copy_supports_e2e_status_flow(tmp_path):
    installer = _load_home_installer_module()
    plugin_destination, _marketplace_path = installer.install_home_plugin(tmp_path)

    spec = importlib.util.spec_from_file_location(
        "installed_proof_mcp_server", plugin_destination / "scripts" / "proof_mcp_server.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    doctor_output = module.doctor()
    status_output = module.status(root=str(Path(__file__).resolve().parent.parent))

    assert "Proof Codex Diagnostics" in doctor_output
    assert "Status: ready" in doctor_output
    assert "Proof Status" in status_output
