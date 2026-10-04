"""proof-web: the proof map's local web app (ADR-0007/0008/0010/0017) — the Home, each project's proof map
page and each node's page, with the studio (latex-agent) and the node's run (proof-agents) served inside it.
The only surface where Human Review decisions are made. Installed, it adds `proof home`, `proof map open`
and `proof map serve` to the `proof` CLI (`proof_web.cli`)."""

from .server import ReviewServer, serve

__all__ = ["ReviewServer", "serve"]
