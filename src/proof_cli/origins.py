"""Where a project's proof map page lives: its origin, derived from the project instance (ADR-0008, ADR-0017).

The page itself is proof-web's, but its address is the project's — one localhost port per project
instance, the same whichever process serves it — and the CLI says it when it refuses a Human
Review decision (`HUMAN_REVIEW_REQUIRED` carries the URL). So the derivation lives here, and
proof-web imports it.
"""

from __future__ import annotations

import hashlib

from .storage import ProjectStore, read_project_instance_id

RP_ID = "localhost"
ORIGIN_PORT_BASE = 20000
ORIGIN_PORT_SPAN = 20000


def origin_port(instance: str) -> int:
    """The project's own port, stable per project instance."""
    return ORIGIN_PORT_BASE + int(hashlib.sha256(f"proof-cli origin {instance}".encode()).hexdigest()[:8], 16) % ORIGIN_PORT_SPAN


def project_origin(store: ProjectStore) -> str:
    return f"http://{RP_ID}:{origin_port(read_project_instance_id(store))}"


def project_url(store: ProjectStore, node_id: str | None = None) -> str:
    """The project's page, at a node's page when `node_id` is given."""
    base = project_origin(store)
    return f"{base}/#/node/{node_id}" if node_id else base


__all__ = ["ORIGIN_PORT_BASE", "ORIGIN_PORT_SPAN", "RP_ID", "origin_port", "project_origin", "project_url"]
