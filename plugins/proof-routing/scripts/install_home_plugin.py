from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

PLUGIN_NAME = "proof-routing"
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {".DS_Store"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_plugin_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*EXCLUDED_DIRS, *EXCLUDED_FILES, "*.pyc"),
    )


def _marketplace_payload(existing: dict | None, plugin_path: str) -> dict:
    payload = existing or {
        "name": "proof-cli-home",
        "interface": {"displayName": "Proof CLI Home Plugins"},
        "plugins": [],
    }
    payload.setdefault("interface", {})
    payload["interface"].setdefault("displayName", "Proof CLI Home Plugins")
    payload.setdefault("plugins", [])

    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": plugin_path},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }

    replaced = False
    next_plugins = []
    for plugin in payload["plugins"]:
        if plugin.get("name") == PLUGIN_NAME:
            next_plugins.append(entry)
            replaced = True
        else:
            next_plugins.append(plugin)
    if not replaced:
        next_plugins.append(entry)
    payload["plugins"] = next_plugins
    return payload


def install_home_plugin(home: Path) -> tuple[Path, Path]:
    plugin_destination = home / "plugins" / PLUGIN_NAME
    marketplace_path = home / ".agents" / "plugins" / "marketplace.json"

    _copy_plugin_tree(_source_plugin_root(), plugin_destination)

    existing = None
    if marketplace_path.exists():
        existing = json.loads(marketplace_path.read_text())
    payload = _marketplace_payload(existing, f"./plugins/{PLUGIN_NAME}")
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(json.dumps(payload, indent=2) + "\n")
    return plugin_destination, marketplace_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Proof Routing as a home-local Codex plugin.")
    parser.add_argument("--home", default=str(Path.home()), help="Home directory to install into.")
    args = parser.parse_args()

    plugin_destination, marketplace_path = install_home_plugin(Path(args.home).expanduser().resolve())
    print(f"Installed plugin: {plugin_destination}")
    print(f"Updated marketplace: {marketplace_path}")


if __name__ == "__main__":
    main()
