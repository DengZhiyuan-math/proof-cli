"""The proof map's local web page: where the researcher makes Human Review decisions (ADR-0010).

A stdlib `ThreadingHTTPServer` bound to 127.0.0.1 on the project's own port.
Read endpoints show what's being decided — the exact Review snapshot, the
dependencies and pins, the open Challenges; `POST /api/decide` records the
researcher's decisions through the service layer, as the git identity this
server runs under, and proof-cli commits each one with its snapshot.

There is no passkey (ADR-0009 is superseded): the boundary is that no CLI
command, Codex route or MCP tool makes a decision, and git history is the
record. The Host, Origin and content-type checks below keep other web pages
from submitting decisions through the researcher's browser.

Synchronous threads, not asyncio: `storage`'s open-transaction tracking is
per thread, and an asyncio task would inherit a transaction that isn't its
own (see the note on #36).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from .. import proof_map
from ..collaboration import list_review_records
from ..domain import ProofMapNodeKind
from ..reviews import git_identity
from ..storage import ProjectStore, get_active_claim, get_current_candidate_proof, read_project_instance_id, read_state
from ..vault import build_pdf_path, node_folder

PRISM_LOCAL_ENV_VAR = "PROOF_CLI_PRISM_LOCAL"
_PRISM_START_SECONDS = 10


def prism_local_command() -> str | None:
    """The prism-local executable: `$PROOF_CLI_PRISM_LOCAL`, else `prism-local` on PATH (ADR-0010 point 5)."""
    return os.environ.get(PRISM_LOCAL_ENV_VAR) or shutil.which("prism-local")

RP_ID = "localhost"
_ORIGIN_PORT_BASE = 20000
_ORIGIN_PORT_SPAN = 20000


def origin_port(instance: str) -> int:
    """The project's own port, stable per project instance."""
    return _ORIGIN_PORT_BASE + int(hashlib.sha256(f"proof-cli origin {instance}".encode()).hexdigest()[:8], 16) % _ORIGIN_PORT_SPAN


def project_origin(store: ProjectStore) -> str:
    return f"http://{RP_ID}:{origin_port(read_project_instance_id(store))}"


_STATIC = resources.files("proof_cli.webapp") / "static"
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
_MAX_BODY_BYTES = 2_000_000


class RequestError(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def _proof_view(store: ProjectStore, proof) -> dict | None:
    """A Candidate proof as the page shows it: the exact bytes whose SHA-256 a signature binds."""
    if proof is None:
        return None
    raw = (store.root / proof.file_path).read_bytes()
    return {"id": proof.id, "version": proof.version, "text": raw.decode("utf-8", errors="replace"), "sha256": hashlib.sha256(raw).hexdigest()}


def _warnings_for(warnings: list, *ids: str) -> list[dict]:
    wanted = {value for value in ids if value}
    return [
        warning.model_dump(mode="json")
        for warning in warnings
        if wanted & {str(value) for value in warning.details.values() if isinstance(value, str)}
    ]


def _remedy(dependency: dict) -> str | None:
    """What a lagging or changed pin needs: a Lightweight re-review, or a new Candidate proof (#23, #24)."""
    pin = dependency["pin"]
    if pin is None:
        return None
    if dependency["current"] is False:
        return "new-candidate-proof"
    if dependency["accepted_version"] is not None and pin["pinned_version"] != dependency["accepted_version"]:
        return "lightweight-re-review"
    return None


def _available_decisions(store: ProjectStore, node, *, claim, proof, dependencies: list[dict], challenges: list) -> list[dict]:
    """Every Human Review decision the researcher could sign on this node's page right now.

    Only what to offer: whether one may be made is checked again, with the
    signature, by the service function each lands on.
    """
    offered: list[dict] = []
    if node.kind == ProofMapNodeKind.imported_result:
        if proof_map.get_reference_review_state(store, node.id) != "no-longer-callable":
            offered += [{"kind": "reference_review", "target_id": node.id, "decision": d} for d in proof_map.REFERENCE_REVIEW_DECISIONS]
        elif proof_map.list_migratable_dependents(store, node.id):
            # a corrected source is a new imported result: offer moving the dependents onto each usable one (#20)
            offered += [
                {"kind": "dependent_migration", "target_id": node.id, "decision": "superseded", "dependency_id": other.id}
                for other in proof_map.list_nodes(store)
                if other.kind == ProofMapNodeKind.imported_result
                and other.id != node.id
                and proof_map.get_reference_review_state(store, other.id) != "no-longer-callable"
            ]
    else:
        if proof_map.get_workflow_state(store, node.id) == "review-needed":
            offered += [{"kind": "acceptance", "target_id": node.id, "decision": d.value} for d in proof_map.AcceptanceDecision]
        accepted = proof_map.get_acceptance_state(store, node.id) == "accepted"
        if node.kind == ProofMapNodeKind.claim and accepted and not any(c.status.value == "open" for c in challenges):
            offered.append({"kind": "promote", "target_id": node.id, "decision": "promote"})
        for dependency in dependencies:
            # a changed interface needs a new Candidate proof, not a re-review (#24): the page says so
            if accepted and dependency["remedy"] == "lightweight-re-review":
                offered.append({"kind": "dependency_revalidation", "target_id": node.id, "decision": "reaffirmed", "dependency_id": dependency["node_id"]})
        if proof is not None:
            for check in proof_map.list_evidence_checks(store, proof.id):
                offered += [{"kind": "evidence_review", "target_id": check.id, "decision": d} for d in ("trusted", "unusable")]
    for challenge in challenges:
        if challenge.status.value == "open":
            offered.append({"kind": "challenge_resolution", "target_id": challenge.id, "decision": "dismissed"})
    return [{**item, "binding": _binding(store, item["kind"], item["target_id"], item["decision"], item.get("dependency_id"))} for item in offered]


def _binding(store: ProjectStore, kind: str, target_id: str, decision: str, dependency_id: str | None = None) -> str | None:
    """What a decision offered on this page would be made on, as a digest the page sends back with it:
    the decision is refused (STALE_VIEW) if that changed before it is recorded."""
    try:
        return proof_map.binding_digest(proof_map.prepare_decision(store, kind, target_id, decision, dependency_id=dependency_id))
    except proof_map.ProofMapError:
        return None


class ReviewApp:
    """The page's behaviour, separate from HTTP plumbing so it can be tested directly."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.origin = project_origin(store)

    # -- reads -------------------------------------------------------------------

    def health(self) -> dict:
        return {"project_id": read_state(self.store).project_id, "instance": read_project_instance_id(self.store), "origin": self.origin}

    def _one_state(self):
        """Hold the project's write lock while a page is read (PR #63 audit): no decision or other
        write can land between reading what the page shows and computing the bindings it sends
        back, so both describe one state. Writers wait for the read; it takes milliseconds."""
        return self.store.transaction()

    def state(self) -> dict:
        with self._one_state():
            return self._state()

    def _state(self) -> dict:
        warnings = proof_map.list_integrity_warnings(self.store)
        return {
            "project_id": read_state(self.store).project_id,
            "origin": self.origin,
            # whose decisions these will be: the git identity that commits them
            "reviewer": git_identity(self.store.root),
            "warnings": [warning.model_dump(mode="json") for warning in warnings],
            "pending": self._pending(),
        }

    def map(self) -> dict:
        """The whole proof map: every node with its three axes, its assignee, and whether it's on the frontier (ADR-0008)."""
        frontier = {node.id for node in proof_map.get_frontier(self.store)}
        nodes = []
        for node in proof_map.list_nodes(self.store):
            imported = node.kind == ProofMapNodeKind.imported_result
            workflow = proof_map.get_workflow_state(self.store, node.id)
            claim = get_active_claim(self.store, node.id)
            nodes.append(
                {
                    "id": node.id,
                    "kind": node.kind.value,
                    "display_label": node.display_label,
                    "statement": node.statement,
                    "dependencies": node.dependencies,
                    "workflow_state": workflow,
                    "blocked_reason": proof_map.get_blocked_reason(self.store, node.id) if workflow == "blocked" else None,
                    "acceptance_state": proof_map.get_reference_review_state(self.store, node.id) if imported else proof_map.get_acceptance_state(self.store, node.id),
                    "integrity_state": proof_map.get_integrity_state(self.store, node.id),
                    "assignee": claim.claimant_id if claim else None,
                    "frontier": node.id in frontier,
                }
            )
        return {"nodes": nodes}

    def _pdfs(self, node_id: str, proof) -> dict:
        """The compiled PDFs a reader can open: the one archived with the snapshot, and prism-local's current build."""
        snapshot_pdf = (self.store.root / proof.file_path).with_suffix(".pdf") if proof is not None else None
        return {
            "snapshot": snapshot_pdf is not None and snapshot_pdf.is_file(),
            "build": build_pdf_path(self.store.root, node_id).is_file(),
        }

    def pdf(self, node_id: str, which: str) -> bytes:
        proof_map.require_node(self.store, node_id)  # a known node id: a plain folder name, never a path
        if which == "snapshot":
            proof = get_current_candidate_proof(self.store, node_id)
            path = (self.store.root / proof.file_path).with_suffix(".pdf") if proof is not None else None
        else:
            path = build_pdf_path(self.store.root, node_id)
        if path is None or not path.is_file():
            raise RequestError(HTTPStatus.NOT_FOUND, "NO_PDF", f"no {which} PDF for {node_id}")
        return path.read_bytes()

    def open_in_prism(self, node_id: str) -> dict:
        """Open the node's folder in prism-local, if it's configured; always say which folder it is."""
        node = proof_map.require_node(self.store, node_id)
        folder = node_folder(self.store.root, node.id)
        command = prism_local_command()
        if node.kind == ProofMapNodeKind.imported_result or not folder.is_dir():
            raise RequestError(HTTPStatus.NOT_FOUND, "NO_PROOF_FOLDER", f"{node_id} has no proof folder to open")
        if command is None:
            return {"opened": False, "folder": str(folder), "hint": f"set {PRISM_LOCAL_ENV_VAR} or put prism-local on PATH"}
        # a free port, so a prism-local already running for another node never collides; it
        # exits a little after its last page closes, and says where it listens once it does
        with tempfile.TemporaryDirectory() as scratch:
            ready = Path(scratch) / "ready.json"
            process = subprocess.Popen(
                [command, str(folder), "--port", "0", "--exit-when-idle", "--ready-file", str(ready)],
                cwd=str(folder),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            deadline = time.monotonic() + _PRISM_START_SECONDS
            while time.monotonic() < deadline:
                if ready.is_file():
                    try:
                        started = json.loads(ready.read_text())
                    except ValueError:
                        started = None
                    if isinstance(started, dict):
                        return {"opened": True, "folder": str(folder), "command": command, "url": started.get("url")}
                if process.poll() is not None:
                    error = (process.stderr.read() or b"").decode("utf-8", errors="replace").strip()
                    return {"opened": False, "folder": str(folder), "command": command, "error": error or f"prism-local exited with code {process.returncode}"}
                time.sleep(0.05)
        return {"opened": False, "folder": str(folder), "command": command, "error": "prism-local didn't report ready in time"}

    def _pending(self) -> list[dict]:
        pending = []
        for node in proof_map.list_nodes(self.store):
            if node.kind == ProofMapNodeKind.imported_result:
                if proof_map.get_reference_review_state(self.store, node.id) in ("unreviewed", "unverifiable"):
                    decisions = list(proof_map.REFERENCE_REVIEW_DECISIONS)
                    pending.append(
                        {
                            "node_id": node.id,
                            "kind": "reference_review",
                            "decisions": decisions,
                            "bindings": {d: _binding(self.store, "reference_review", node.id, d) for d in decisions},
                            "statement": node.statement,
                        }
                    )
                continue
            if proof_map.get_workflow_state(self.store, node.id) == "review-needed":
                proof = get_current_candidate_proof(self.store, node.id)
                pending.append(
                    {
                        "node_id": node.id,
                        "kind": "acceptance",
                        "decisions": [decision.value for decision in proof_map.AcceptanceDecision],
                        "bindings": {d.value: _binding(self.store, "acceptance", node.id, d.value) for d in proof_map.AcceptanceDecision},
                        "statement": node.statement,
                        "acceptance_state": proof_map.get_acceptance_state(self.store, node.id),
                        "candidate_proof": _proof_view(self.store, proof) or {"id": None, "text": "", "sha256": None},
                    }
                )
        return pending

    def node(self, node_id: str) -> dict:
        with self._one_state():
            return self._node(node_id)

    def _node(self, node_id: str) -> dict:
        store = self.store
        node = proof_map.get_node(store, node_id)
        if node is None:
            raise RequestError(HTTPStatus.NOT_FOUND, "NODE_NOT_FOUND", f"proof map node {node_id} not found")
        proof = get_current_candidate_proof(store, node_id)
        checks = [check.model_dump(mode="json") for check in proof_map.list_evidence_checks(store, proof.id)] if proof else []
        dependencies = []
        for dependency_id in node.dependencies:
            pin = proof_map.get_dependency_pin(store, node_id, dependency_id)
            dependency = proof_map.get_node(store, dependency_id)
            dependencies.append(
                {
                    "node_id": dependency_id,
                    "statement": dependency.statement if dependency else None,
                    "pin": pin.model_dump(mode="json") if pin else None,
                    # the pin lag a Lightweight re-review is about (#23/#24)
                    "accepted_version": proof_map.get_accepted_version(store, dependency_id),
                    "current": proof_map.dependency_pin_is_current(store, pin) if pin else None,
                }
            )
            dependencies[-1]["remedy"] = _remedy(dependencies[-1])
        challenges = proof_map.list_challenges(store, target_node_id=node_id)
        warnings = proof_map.list_integrity_warnings(store)
        claim = get_active_claim(store, node_id)
        return {
            # its assignee: a planning signal, cleared with `proof node unassign` (ADR-0010)
            "claim": {"id": claim.id, "claimant_id": claim.claimant_id, "claimed_at": claim.claimed_at.isoformat()} if claim else None,
            "node": node.model_dump(mode="json"),
            "workflow_state": proof_map.get_workflow_state(store, node_id),
            "acceptance_state": (
                proof_map.get_reference_review_state(store, node_id)
                if node.kind == ProofMapNodeKind.imported_result
                else proof_map.get_acceptance_state(store, node_id)
            ),
            "integrity_state": proof_map.get_integrity_state(store, node_id),
            "candidate_proof": _proof_view(store, proof),
            "folder": str(node_folder(store.root, node_id)) if node.kind != ProofMapNodeKind.imported_result else None,
            "pdfs": self._pdfs(node_id, proof),
            "evidence_checks": checks,
            "dependencies": dependencies,
            "challenges": [challenge.model_dump(mode="json") for challenge in challenges],
            "history": [
                record.model_dump(mode="json")
                for record in list_review_records(store, object_type="proof_map_node", object_id=node_id)
            ],
            "warnings": _warnings_for(warnings, node_id, *(challenge.id for challenge in challenges)),
            "decisions": _available_decisions(store, node, claim=claim, proof=proof, dependencies=dependencies, challenges=challenges),
        }

    # -- decisions ----------------------------------------------------------------

    def decide(self, body: dict) -> dict:
        """Record each decision, in order, as this server's git identity; one result per decision."""
        decisions = body.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            raise RequestError(HTTPStatus.BAD_REQUEST, "NO_DECISIONS", "nothing to decide")
        results = []
        for item in decisions:
            if not isinstance(item, dict):
                raise RequestError(HTTPStatus.BAD_REQUEST, "MALFORMED_DECISION", "each decision is an object")
            try:
                kind, target_id, decision = item["kind"], item["target_id"], item["decision"]
                viewed = item.get("viewed_candidate_proof_sha256")
                if viewed is not None:
                    current = proof_map.prepare_decision(self.store, kind, target_id, decision, dependency_id=item.get("dependency_id"))
                    if viewed != current.candidate_proof_sha256:
                        # the snapshot changed between the researcher reading it and deciding
                        raise proof_map.ProofMapError(
                            "STALE_VIEW", f"the Review snapshot of {target_id} changed since you viewed it; reload and read it again"
                        )
                record = proof_map.apply_decision(
                    self.store,
                    kind,
                    target_id,
                    decision,
                    rationale=str(item.get("rationale") or ""),
                    dependency_id=item.get("dependency_id"),
                    # what the page showed this decision is made on: checked on the decision's own write transaction
                    viewed_binding=item.get("binding"),
                )
                results.append({"target_id": target_id, "ok": True, "result": record.model_dump(mode="json")})
            except KeyError as exc:
                raise RequestError(HTTPStatus.BAD_REQUEST, "MALFORMED_DECISION", f"a decision is missing {exc}") from exc
            except proof_map.ProofMapError as exc:
                results.append({"target_id": item.get("target_id"), "ok": False, "error": {"code": exc.code, "message": exc.message, **exc.details}})
        return {"results": results}


# -- HTTP -------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    app: ReviewApp  # set on the subclass the server builds
    server_version = "proof-review"

    def log_message(self, format: str, *args: Any) -> None:  # keep the terminal quiet
        return

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, *, policy: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if policy:  # a PDF goes to the browser's own viewer, which a page policy can break
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, value: Any) -> None:
        self._send(status, json.dumps(value, default=str).encode("utf-8"), "application/json")

    def _error(self, status: HTTPStatus, code: str, message: str, details: dict | None = None) -> None:
        self._json(status, {"ok": False, "error": {"code": code, "message": message, **(details or {})}})

    def _host_ok(self) -> bool:
        # the page must be on the pinned origin's host, or WebAuthn origins
        # won't match; this also refuses DNS-rebinding hosts
        return self.headers.get("Host") == urlsplit(self.app.origin).netloc

    def _guarded(self, action: Callable[[], Any]) -> None:
        try:
            self._json(HTTPStatus.OK, {"ok": True, "data": action()})
        except RequestError as exc:
            self._error(exc.status, exc.code, exc.message, exc.details)
        except proof_map.ProofMapError as exc:
            self._error(HTTPStatus.BAD_REQUEST, exc.code, exc.message, exc.details)
        except Exception as exc:  # never drop the connection with a traceback on the terminal
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", f"{type(exc).__name__}")

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "WRONG_HOST", f"open this app at {self.app.origin}")
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path.removeprefix("/static/"))
        if path == "/api/health":
            return self._guarded(self.app.health)
        if path == "/api/state":
            return self._guarded(self.app.state)
        if path == "/api/map":
            return self._guarded(self.app.map)
        if path.startswith("/api/node/") and path.endswith(("/pdf/snapshot", "/pdf/build")):
            node_id, _, which = unquote(path.removeprefix("/api/node/")).rpartition("/pdf/")
            try:
                data = self.app.pdf(node_id, which)
            except RequestError as exc:
                return self._error(exc.status, exc.code, exc.message)
            except proof_map.ProofMapError as exc:
                return self._error(HTTPStatus.NOT_FOUND, exc.code, exc.message)
            return self._send(HTTPStatus.OK, data, "application/pdf", policy=False)
        if path.startswith("/api/node/"):
            node_id = unquote(path.removeprefix("/api/node/"))
            return self._guarded(lambda: self.app.node(node_id))
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "WRONG_HOST", f"open this app at {self.app.origin}")
        if self.headers.get("Origin") != self.app.origin:
            return self._error(HTTPStatus.FORBIDDEN, "WRONG_ORIGIN", "writes are only accepted from this app's own page")
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON_REQUIRED", "send application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, "BAD_LENGTH", "Content-Length isn't a number")
        if length < 0:
            return self._error(HTTPStatus.BAD_REQUEST, "BAD_LENGTH", "Content-Length can't be negative")
        if length > _MAX_BODY_BYTES:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "BODY_TOO_LARGE", "the request body is too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return self._error(HTTPStatus.BAD_REQUEST, "MALFORMED_JSON", "the request body isn't JSON")
        if not isinstance(body, dict):
            return self._error(HTTPStatus.BAD_REQUEST, "MALFORMED_JSON", "the request body must be a JSON object")
        routes: dict[str, Callable[[], Any]] = {
            "/api/decide": lambda: self.app.decide(body),
        }
        path = urlsplit(self.path).path
        route = routes.get(path)
        if route is None and path.startswith("/api/node/") and path.endswith("/open"):
            node_id = unquote(path.removeprefix("/api/node/").removesuffix("/open"))
            route = lambda: self.app.open_in_prism(node_id)
        if route is None:
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", self.path)
        self._guarded(route)

    def _static(self, name: str) -> None:
        if "/" in name or name.startswith("."):
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", name)
        asset = _STATIC / name
        if not asset.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", name)
        suffix = "." + name.rsplit(".", 1)[-1]
        self._send(HTTPStatus.OK, asset.read_bytes(), _CONTENT_TYPES.get(suffix, "application/octet-stream"))


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, store: ProjectStore, *, port: int | None = None) -> None:
        self.app = ReviewApp(store)
        handler = type("ReviewHandler", (_Handler,), {"app": self.app})
        pinned = urlsplit(self.app.origin).port
        super().__init__(("127.0.0.1", pinned if port is None else port), handler)

    @property
    def url(self) -> str:
        return self.app.origin


def serve(store: ProjectStore) -> ReviewServer:
    """Bind the project's review app on its pinned port (not started)."""
    return ReviewServer(store)


def project_url(store: ProjectStore, node_id: str | None = None) -> str:
    base = project_origin(store)
    return f"{base}/#/node/{node_id}" if node_id else base


__all__ = ["ReviewApp", "ReviewServer", "project_url", "serve"]
