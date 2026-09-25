from __future__ import annotations

import json
from typing import Any


SCHEMA_VERSION = 1


def success_envelope(command: str, data: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "ok": True, "command": command, "data": data}


def error_envelope(command: str, code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error.update(details)
    return {"schema_version": SCHEMA_VERSION, "ok": False, "command": command, "error": error}


def dump_envelope(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, default=str)
