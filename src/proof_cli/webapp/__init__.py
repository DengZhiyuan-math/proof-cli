"""The local review web app (ADR-0007/0008/0009, issue #36): the only surface that issues signed decisions."""

from .server import ReviewServer, serve

__all__ = ["ReviewServer", "serve"]
