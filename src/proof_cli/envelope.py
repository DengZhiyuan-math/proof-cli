from __future__ import annotations

import json
from typing import Any


SCHEMA_VERSION = "1.0"


def success_envelope(data: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "ok": True, "data": data}


def error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "ok": False, "error": {"code": code, "message": message}}


def dump_envelope(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, default=str)
