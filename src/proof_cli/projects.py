"""The researcher's projects, as the Home lists them (ADR-0017).

A project is a folder with `.proof/project.sqlite3`; the Home needs to know which folders those
are. They are kept in one user-level file, `projects.json` in the proof-cli config directory
(`$PROOF_CLI_CONFIG_HOME`, else `$XDG_CONFIG_HOME/proof-cli`, else `~/.config/proof-cli`): one
entry per project path, when it was added and when its map was last opened. Nothing about the
project itself is copied here: the Home reads each project live from its own database.

A project is registered when it is started (`proof init`), when its map is served or opened,
and when it is added or created on the Home. Forgetting one only drops it from this list; the
project's folder is never touched.

Several processes write the list — the Home, `proof init` and `proof map open` in terminals, an
agent's `proof init` — so each change is one transaction under a cross-process lock on
`projects.json.lock` (`_locked`): read, change, write to a private temporary file, replace. Without
it two registrations at once lost one of them.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

USER_CONFIG_ENV_VAR = "PROOF_CLI_CONFIG_HOME"
PROJECTS_FILE = "projects.json"


def user_config_dir() -> Path:
    if os.environ.get(USER_CONFIG_ENV_VAR):
        return Path(os.environ[USER_CONFIG_ENV_VAR])
    base = Path(os.environ["XDG_CONFIG_HOME"]) if os.environ.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "proof-cli"


def projects_file() -> Path:
    return user_config_dir() / PROJECTS_FILE


def project_key(root: str | Path) -> str:
    """One spelling per folder: `~` expanded, made absolute, symlinks followed where the folder exists."""
    path = Path(root).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


LOCK_FILE = PROJECTS_FILE + ".lock"
_thread_lock = threading.Lock()  # one transaction at a time in this process too; the file lock is per process


@contextmanager
def _locked():
    """Hold the list's cross-process lock for one read-change-write transaction."""
    path = projects_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock, open(path.with_name(LOCK_FILE), "a+b") as lock:
        _lock_file(lock)
        try:
            yield
        finally:
            _unlock_file(lock)


if os.name == "nt":  # pragma: no cover — exercised on Windows only
    import msvcrt

    def _lock_file(lock) -> None:
        while True:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)  # retries for about ten seconds, then raises
                return
            except OSError:
                continue

    def _unlock_file(lock) -> None:
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_file(lock) -> None:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

    def _unlock_file(lock) -> None:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read() -> list[dict]:
    try:
        data = json.loads(projects_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("projects", []) if isinstance(data, dict) else []
    return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("path"), str)]


def _write(entries: list[dict]) -> None:
    path = projects_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")  # this writer's own
    try:
        tmp.write_text(json.dumps({"projects": entries}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def list_registered() -> list[dict]:
    """Every registered project, most recently opened first (then most recently added)."""
    entries = _read()
    return sorted(entries, key=lambda e: (e.get("opened_at") or "", e.get("added_at") or ""), reverse=True)


def register_project(root: str | Path, *, opened: bool = False) -> dict:
    """Add the folder to the list (once), and note the opening when `opened`. Returns its entry."""
    key = project_key(root)
    with _locked():
        entries = _read()
        entry = next((e for e in entries if e["path"] == key), None)
        if entry is None:
            entry = {"path": key, "added_at": _now(), "opened_at": None}
            entries.append(entry)
        if opened:
            entry["opened_at"] = _now()
        _write(entries)
    return dict(entry)


def forget_project(root: str | Path) -> bool:
    """Drop the folder from the list; the folder itself is left as it is. False when it wasn't listed."""
    key = project_key(root)
    with _locked():
        entries = _read()
        kept = [e for e in entries if e["path"] != key]
        if len(kept) == len(entries):
            return False
        _write(kept)
    return True


def is_project(root: str | Path) -> bool:
    """Whether the folder holds a proof project: its database exists."""
    return (Path(project_key(root)) / ".proof" / "project.sqlite3").is_file()


__all__ = ["USER_CONFIG_ENV_VAR", "forget_project", "is_project", "list_registered", "project_key", "projects_file", "register_project", "user_config_dir"]
