from __future__ import annotations

import json
from typing import Any


SCHEMA_VERSION = "1.0"


def success_envelope(data: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "ok": True, "data": data}


def error_envelope(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"schema_version": SCHEMA_VERSION, "ok": False, "error": error}


def dump_envelope(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, default=str)
