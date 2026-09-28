"""The proof map's local web page (ADR-0007/0008/0010): the only surface where Human Review decisions are made."""

from .server import ReviewServer, serve

__all__ = ["ReviewServer", "serve"]
