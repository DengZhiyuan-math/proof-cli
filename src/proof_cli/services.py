from __future__ import annotations

from pathlib import Path

from .commands import (
    cmd_export,
    cmd_history,
    cmd_snapshot,
    cmd_status,
)
from .storage import ProjectStore, ensure_project


def open_store(root: str | Path = ".") -> ProjectStore:
    return ensure_project(root)


def workspace_status(root: str | Path = ".") -> str:
    return cmd_status(root)


def workspace_snapshot(root: str | Path = ".", note: str = "") -> str:
    return cmd_snapshot(root, handoff_note=note)


def workspace_history(root: str | Path = ".") -> str:
    return cmd_history(root)


def workspace_export(root: str | Path = ".") -> str:
    return cmd_export(root)

