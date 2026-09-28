"""Each local node's studio, served by the proof map's own server (ADR-0011, #69).

A node's page is its folder's LaTeX studio: `/studio/<node-id>/` serves the studio page, and
everything under that prefix (its static files, `viewer`, `pdf`, `api/…`) belongs to that
node's `Studio`, created on first use. The page's URLs are relative, so it reaches only its
own node, and it keys its browser storage by node.

What a node's studio may write is its working sources: `proof.tex` and the other sources in
its folder. Its snapshots and scratch folder are hidden from the editor, its build output
and `reviews.jsonl` aren't editable, and another node's folder is outside it. Its build is
fixed: `proof.tex` → `build/proof.pdf`, the PDF review archives when it is current.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, unquote

from .. import proof_map
from ..domain import ProofMapNodeKind
from ..storage import ProjectStore
from ..studio.server import Studio
from ..vault import node_folder

STUDIO_STATIC = Path(__file__).resolve().parent.parent / "studio" / "static"
# the node's build: what vault.build_is_current checks and review archives (ADR-0010)
NODE_BUILD = ("proof.tex", "build")
# a node folder's own folders the editor neither lists nor writes (ADR-0011 point 6)
NODE_HIDDEN = ("snapshots", "scratch")
# CodeMirror and PDF.js set element styles and run PDF.js's worker; scripts stay same-origin only
STUDIO_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; "
    "connect-src 'self'; frame-ancestors 'none'"
)
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}
_PAGES = {"": "index.html", "index.html": "index.html", "viewer": "viewer.html"}


@dataclass
class StudioAnswer:
    """What the server sends back: `policy` is the Content-Security-Policy, or None (a PDF)."""

    status: int
    body: bytes
    content_type: str
    policy: str | None = STUDIO_POLICY
    location: str | None = None


def _error(status: HTTPStatus, code: str, message: str) -> StudioAnswer:
    import json

    body = json.dumps({"ok": False, "error": {"code": code, "message": message}}).encode("utf-8")
    return StudioAnswer(int(status), body, "application/json")


class NoStudio(Exception):
    """This node has no studio: (code, message)."""


class StudioHub:
    """The project's node studios, one per local node folder, created on first use."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._studios: dict[str, Studio] = {}
        self._lock = threading.Lock()

    def studio(self, node_id: str) -> Studio:
        node = proof_map.get_node(self.store, node_id)
        if node is None:
            raise NoStudio("NODE_NOT_FOUND", f"proof map node {node_id} not found")
        if node.kind == ProofMapNodeKind.imported_result:
            raise NoStudio("NO_STUDIO", f"{node_id} is an imported result: it has no proof to write")
        folder = node_folder(self.store.root, node.id)
        if not folder.is_dir():
            raise NoStudio("NO_PROOF_FOLDER", f"{node_id} has no proof folder")
        with self._lock:
            if node.id not in self._studios:
                self._studios[node.id] = Studio(folder, fixed_build=NODE_BUILD, hidden=NODE_HIDDEN)
            return self._studios[node.id]

    def close(self) -> None:
        with self._lock:
            studios, self._studios = list(self._studios.values()), {}
        for studio in studios:
            studio.close()

    def request(self, method: str, path: str, query: str, body: dict | None, *, cross_site: bool) -> StudioAnswer:
        """Answer one request under `/studio/<node-id>/`. `cross_site`: the browser says another
        site sent it (Sec-Fetch-Site, or a foreign Origin), which only the static page may be."""
        node_part, slash, rest = path.removeprefix("/studio/").partition("/")
        node_id = unquote(node_part)
        if not slash:  # the page's relative URLs need the trailing slash
            return StudioAnswer(int(HTTPStatus.PERMANENT_REDIRECT), b"", "text/plain", location=f"/studio/{node_part}/")
        try:
            studio = self.studio(node_id)
        except NoStudio as exc:
            code, message = exc.args
            return _error(HTTPStatus.NOT_FOUND, code, message)
        if method == "GET" and rest in _PAGES:
            return self._static(_PAGES[rest])
        if method == "GET" and rest.startswith("static/"):
            return self._static(rest.removeprefix("static/"))
        if not (rest == "pdf" or rest.startswith("api/")):
            return _error(HTTPStatus.NOT_FOUND, "NOT_FOUND", path)
        if cross_site:  # a studio GET can start programs (git, the agent's CLI) or read the project
            return _error(HTTPStatus.FORBIDDEN, "CROSS_SITE", "the studio answers only its own page")
        route = "/" + rest
        if method == "GET":
            answer = studio.get(route, {k: v[0] for k, v in parse_qs(query).items()})
        else:
            answer = studio.post(route, body or {})
        return StudioAnswer(answer.status, answer.body, answer.ctype, None if answer.ctype == "application/pdf" else STUDIO_POLICY)

    def _static(self, rel: str) -> StudioAnswer:
        asset = (STUDIO_STATIC / rel).resolve()
        if STUDIO_STATIC not in asset.parents or not asset.is_file():
            return _error(HTTPStatus.NOT_FOUND, "NOT_FOUND", rel)
        return StudioAnswer(200, asset.read_bytes(), _TYPES.get(asset.suffix, "text/plain; charset=utf-8"))
