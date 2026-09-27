"""The review app's HTTP server (issue #36).

A stdlib `ThreadingHTTPServer` bound to 127.0.0.1 on the project's own
port, so its origin — `http://localhost:<port>` — is the one WebAuthn
origin the project's signatures may come from.

**The server holds no authority.** Read endpoints show what's being
decided; `prepare` only builds the payloads a passkey must sign; every write
endpoint takes a fresh WebAuthn assertion and hands the signed payload to
the service layer, which verifies it like any other caller's. A request
without a valid assertion — an agent `curl`ing the server — changes
nothing. The Host and Origin checks below are hygiene against DNS rebinding
and cross-site requests, not the security boundary: the signature is.

Synchronous threads, not asyncio: `storage`'s open-transaction tracking is
per thread, and an asyncio task would inherit a transaction that isn't its
own (see the note on #36).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from .. import proof_map
from ..authority import (
    ACKNOWLEDGE,
    AuthorityError,
    EnrollmentRequest,
    acknowledge_registry,
    build_decision_payload,
    enroll_reviewer_key,
    list_reviewer_keys,
    project_origin,
    registry_status,
)
from ..collaboration import list_review_records
from ..domain import ProofMapNodeKind
from ..signing import (
    RP_ID,
    DecisionKind,
    DecisionPayload,
    SignatureError,
    SignedDecision,
    WebAuthnAssertion,
    b64url_encode,
    batch_challenge,
    payload_hash,
    public_key_fingerprint,
    verify_registration,
)
from ..storage import ProjectStore, chain_head, get_current_candidate_proof, read_project_instance_id, read_state

_STATIC = resources.files("proof_cli.webapp") / "static"
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
# a registration challenge or pending enrollment is only good for a few minutes
_CEREMONY_TTL_SECONDS = 300
_CEREMONY_LIMIT = 64
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


class ReviewApp:
    """The app's behaviour, separate from HTTP plumbing so it can be tested directly."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.origin = project_origin(store)
        self._ceremonies: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    # -- server-side ceremony state (never authority: every step re-verifies) ----

    def _remember(self, value: dict) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            now = time.monotonic()
            self._ceremonies = {k: v for k, v in self._ceremonies.items() if now - v[0] < _CEREMONY_TTL_SECONDS}
            while len(self._ceremonies) >= _CEREMONY_LIMIT:
                self._ceremonies.pop(next(iter(self._ceremonies)))
            self._ceremonies[token] = (now, value)
        return token

    def _recall(self, token: str) -> dict:
        with self._lock:
            entry = self._ceremonies.pop(token, None)
        if entry is None or time.monotonic() - entry[0] >= _CEREMONY_TTL_SECONDS:
            raise RequestError(HTTPStatus.BAD_REQUEST, "CEREMONY_EXPIRED", "that ceremony expired or was already used; start again")
        return entry[1]

    # -- reads -------------------------------------------------------------------

    def health(self) -> dict:
        return {"project_id": read_state(self.store).project_id, "instance": read_project_instance_id(self.store), "origin": self.origin}

    def state(self) -> dict:
        warnings = proof_map.list_integrity_warnings(self.store)
        return {
            "project_id": read_state(self.store).project_id,
            "origin": self.origin,
            "registry": registry_status(self.store),
            "keys": [
                {**key.model_dump(mode="json"), "reviewer_id": key.reviewer_id}
                for key in list_reviewer_keys(self.store)
            ],
            "warnings": [warning.model_dump(mode="json") for warning in warnings],
            "pending": self._pending(),
        }

    def _pending(self) -> list[dict]:
        pending = []
        legacy = proof_map.legacy_targets(self.store)
        for node in proof_map.list_nodes(self.store):
            if node.id in legacy:
                continue  # re-sign or decline it on the legacy list, with its original context
            if node.kind == ProofMapNodeKind.imported_result:
                if proof_map.get_reference_review_state(self.store, node.id) != "reviewed":
                    pending.append({"node_id": node.id, "kind": "reference_review", "decisions": ["reference-review"], "statement": node.statement})
                continue
            if proof_map.get_workflow_state(self.store, node.id) == "review-needed":
                proof = get_current_candidate_proof(self.store, node.id)
                raw = (self.store.root / proof.file_path).read_bytes() if proof else b""
                pending.append(
                    {
                        "node_id": node.id,
                        "kind": "acceptance",
                        "decisions": [decision.value for decision in proof_map.AcceptanceDecision],
                        "statement": node.statement,
                        "acceptance_state": proof_map.get_acceptance_state(self.store, node.id),
                        "candidate_proof": {
                            "id": proof.id if proof else None,
                            "text": raw.decode("utf-8", errors="replace"),
                            "sha256": hashlib.sha256(raw).hexdigest() if proof else None,
                        },
                    }
                )
        return pending

    def legacy(self) -> list[dict]:
        """Pre-ADR-0009 decisions awaiting re-sign or decline (#42), with what each would sign over."""
        items = []
        for item in proof_map.list_legacy_decisions(self.store):
            context = None
            node_id = item.target_id
            if item.kind == DecisionKind.challenge_resolution:
                challenge = proof_map.get_challenge(self.store, item.target_id)
                node_id = challenge.target_node_id if challenge else None
                context = {"challenge": challenge.model_dump(mode="json") if challenge else None}
            elif item.kind == DecisionKind.evidence_review:
                check = proof_map.get_evidence_check(self.store, item.target_id)
                context = {"evidence_check": check.model_dump(mode="json") if check else None}
                owner = proof_map.get_candidate_proof(self.store, check.candidate_proof_id) if check else None
                node_id = owner.node_id if owner else None
            node = proof_map.get_node(self.store, node_id) if node_id else None
            proof = get_current_candidate_proof(self.store, node.id) if node else None
            items.append(
                {
                    **item.model_dump(mode="json"),
                    "node": node.model_dump(mode="json") if node else None,
                    "candidate_proof": _proof_view(self.store, proof),
                    "pins": [pin.model_dump(mode="json") for pin in proof_map.list_dependency_pins(self.store, node.id)] if node else [],
                    "context": context,
                }
            )
        return items

    def node(self, node_id: str) -> dict:
        store = self.store
        node = proof_map.get_node(store, node_id)
        if node is None:
            raise RequestError(HTTPStatus.NOT_FOUND, "NODE_NOT_FOUND", f"proof map node {node_id} not found")
        proof = get_current_candidate_proof(store, node_id)
        proof_view = _proof_view(store, proof)
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
                    "current": proof_map.dependency_pin_is_current(store, pin) if pin else None,
                }
            )
        challenges = proof_map.list_challenges(store, target_node_id=node_id)
        warnings = proof_map.list_integrity_warnings(store)
        return {
            "node": node.model_dump(mode="json"),
            "workflow_state": proof_map.get_workflow_state(store, node_id),
            "acceptance_state": (
                proof_map.get_reference_review_state(store, node_id)
                if node.kind == ProofMapNodeKind.imported_result
                else proof_map.get_acceptance_state(store, node_id)
            ),
            "integrity_state": proof_map.get_integrity_state(store, node_id),
            "candidate_proof": proof_view,
            "evidence_checks": checks,
            "dependencies": dependencies,
            "challenges": [challenge.model_dump(mode="json") for challenge in challenges],
            "history": [
                record.model_dump(mode="json")
                for record in list_review_records(store, object_type="proof_map_node", object_id=node_id)
            ],
            "warnings": _warnings_for(warnings, node_id, *(challenge.id for challenge in challenges)),
        }

    # -- decisions: prepare (no authority), then decide (a fresh assertion) -------

    def prepare(self, body: dict) -> dict:
        decisions = body.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            raise RequestError(HTTPStatus.BAD_REQUEST, "NO_DECISIONS", "nothing to sign")
        payloads = []
        for item in decisions:
            try:
                payload = proof_map.prepare_decision(
                    self.store,
                    item["kind"],
                    item["target_id"],
                    item["decision"],
                    rationale=item.get("rationale", ""),
                    dependency_id=item.get("dependency_id"),
                    resigns=item.get("resigns"),
                )
            except (KeyError, TypeError, AttributeError) as exc:
                raise RequestError(HTTPStatus.BAD_REQUEST, "MALFORMED_DECISION", f"a decision is malformed: {exc}") from exc
            viewed = item.get("viewed_candidate_proof_sha256")
            if viewed is not None and viewed != payload.candidate_proof_sha256:
                # the proof changed between the researcher reading it and signing
                raise RequestError(
                    HTTPStatus.CONFLICT,
                    "STALE_VIEW",
                    f"the Candidate proof of {payload.target_id} changed since you viewed it; reload and read it again",
                )
            payloads.append(payload)
        return self._to_sign(payloads)

    def _to_sign(self, payloads: list[DecisionPayload]) -> dict:
        batch = [payload_hash(payload) for payload in payloads]
        return {
            "payloads": [payload.model_dump(mode="json") for payload in payloads],
            "batch": batch,
            "challenge": b64url_encode(batch_challenge(batch)),
            "rp_id": RP_ID,
            "allow_credentials": [key.credential_id for key in list_reviewer_keys(self.store) if key.revoked_seq is None],
        }

    def decide(self, body: dict) -> dict:
        payloads, batch, assertion = self._signed_batch(body)
        results = []
        for payload in payloads:
            signed = SignedDecision(payload=payload, batch=batch, assertion=assertion)
            try:
                record = proof_map.apply_signed_decision(self.store, signed)
                results.append({"target_id": payload.target_id, "ok": True, "result": record.model_dump(mode="json")})
            except proof_map.ProofMapError as exc:
                results.append({"target_id": payload.target_id, "ok": False, "error": {"code": exc.code, "message": exc.message, **exc.details}})
        return {"results": results}

    def _signed_batch(self, body: dict) -> tuple[list[DecisionPayload], list[str], WebAuthnAssertion]:
        try:
            payloads = [DecisionPayload.model_validate(raw) for raw in body["payloads"]]
            batch = list(body["batch"])
            assertion = WebAuthnAssertion.model_validate(body["assertion"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "HUMAN_REVIEW_REQUIRED", f"a signed batch is required: {exc}") from exc
        if not payloads or [payload_hash(payload) for payload in payloads] != batch:
            raise RequestError(HTTPStatus.BAD_REQUEST, "SIGNATURE_MISMATCH", "the payloads aren't the batch that was signed")
        return payloads, batch, assertion

    # -- enrollment: a real registration ceremony, then proof of possession --------

    def enroll_begin(self, body: dict) -> dict:
        display_name = str(body.get("display_name") or "").strip()
        if not display_name:
            raise RequestError(HTTPStatus.BAD_REQUEST, "DISPLAY_NAME_REQUIRED", "give the passkey a name you'll recognise")
        challenge = secrets.token_bytes(32)
        user_id = secrets.token_bytes(16)
        token = self._remember({"step": "register", "challenge": challenge, "display_name": display_name})
        return {
            "token": token,
            "public_key": {
                "challenge": b64url_encode(challenge),
                "rp": {"id": RP_ID, "name": f"Proof review · {read_state(self.store).project_id}"},
                "user": {"id": b64url_encode(user_id), "name": display_name, "displayName": display_name},
                "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -8}],
                "authenticatorSelection": {"userVerification": "required", "residentKey": "preferred"},
                "attestation": "none",
                "excludeCredentials": [key.credential_id for key in list_reviewer_keys(self.store)],
                "timeout": 120000,
            },
        }

    def enroll_register(self, body: dict) -> dict:
        ceremony = self._recall(str(body.get("token", "")))
        if ceremony.get("step") != "register":
            raise RequestError(HTTPStatus.BAD_REQUEST, "CEREMONY_EXPIRED", "not a registration in progress")
        try:
            credential = verify_registration(
                str(body.get("client_data_json", "")),
                str(body.get("attestation_object", "")),
                challenge=ceremony["challenge"],
                expected_origin=self.origin,
            )
        except SignatureError as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, exc.code, exc.message) from exc
        fingerprint = public_key_fingerprint(credential.public_key_spki)
        payload = build_decision_payload(
            self.store, DecisionKind.reviewer_enrollment, fingerprint, "enroll", credential_id=credential.credential_id
        )
        existing = [key.credential_id for key in list_reviewer_keys(self.store) if key.revoked_seq is None]
        token = self._remember(
            {
                "step": "possess",
                "credential_id": credential.credential_id,
                "public_key_spki": b64url_encode(credential.public_key_spki),
                "alg": credential.alg,
                "aaguid": credential.aaguid,
                "display_name": ceremony["display_name"],
                "payload": payload.model_dump(mode="json"),
            }
        )
        signing = self._to_sign([payload])
        # the first key proves possession by signing its own enrollment; any
        # later key's enrollment is signed by a key that's already enrolled
        signing["allow_credentials"] = existing or [credential.credential_id]
        return {"token": token, "fingerprint": fingerprint, "aaguid": credential.aaguid, "first_key": not existing, **signing}

    def enroll_complete(self, body: dict) -> dict:
        ceremony = self._recall(str(body.get("token", "")))
        if ceremony.get("step") != "possess":
            raise RequestError(HTTPStatus.BAD_REQUEST, "CEREMONY_EXPIRED", "not an enrollment in progress")
        payload = DecisionPayload.model_validate(ceremony["payload"])
        try:
            assertion = WebAuthnAssertion.model_validate(body["assertion"])
        except (KeyError, ValidationError) as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "HUMAN_REVIEW_REQUIRED", "a passkey assertion is required") from exc
        request = EnrollmentRequest(
            credential_id=ceremony["credential_id"],
            public_key_spki=ceremony["public_key_spki"],
            alg=ceremony["alg"],
            aaguid=ceremony["aaguid"],
            display_name=ceremony["display_name"],
            signed_decision=SignedDecision(payload=payload, batch=[payload_hash(payload)], assertion=assertion),
        )
        key = enroll_reviewer_key(self.store, request)
        return {**key.model_dump(mode="json"), "reviewer_id": key.reviewer_id}

    # -- acknowledging the registry: a tap, so an agent can't silence the banner ---

    def acknowledge_prepare(self) -> dict:
        payload = build_decision_payload(
            self.store, DecisionKind.registry_acknowledgement, chain_head(self.store, "reviewer_keys"), ACKNOWLEDGE
        )
        return self._to_sign([payload])

    def acknowledge(self, body: dict) -> dict:
        payloads, batch, assertion = self._signed_batch(body)
        acknowledge_registry(self.store, SignedDecision(payload=payloads[0], batch=batch, assertion=assertion))
        return registry_status(self.store)


# -- HTTP -------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    app: ReviewApp  # set on the subclass the server builds
    server_version = "proof-review"

    def log_message(self, format: str, *args: Any) -> None:  # keep the terminal quiet
        return

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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
        except AuthorityError as exc:
            self._error(HTTPStatus.FORBIDDEN, exc.code, exc.message, exc.details)
        except SignatureError as exc:
            self._error(HTTPStatus.FORBIDDEN, exc.code, exc.message)
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
        if path == "/api/legacy":
            return self._guarded(self.app.legacy)
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
            "/api/prepare": lambda: self.app.prepare(body),
            "/api/decide": lambda: self.app.decide(body),
            "/api/enroll/begin": lambda: self.app.enroll_begin(body),
            "/api/enroll/register": lambda: self.app.enroll_register(body),
            "/api/enroll/complete": lambda: self.app.enroll_complete(body),
            "/api/acknowledge/prepare": self.app.acknowledge_prepare,
            "/api/acknowledge": lambda: self.app.acknowledge(body),
        }
        route = routes.get(urlsplit(self.path).path)
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
