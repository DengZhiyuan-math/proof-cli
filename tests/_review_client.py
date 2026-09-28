"""The review app over plain HTTP, as a browser on its page reaches it (issues #36, #38)."""

import http.client
import json
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

from proof_cli.webapp.server import ReviewServer


@contextmanager
def serving(store):
    """The project's review app, running on its own origin, and a client for it."""
    server = ReviewServer(store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(server.url)
    finally:
        server.shutdown()
        server.server_close()


class Client:
    """What a browser on the app's page sends: the pinned Host and Origin, JSON bodies."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.netloc = urlsplit(origin).netloc

    def request(self, method: str, path: str, body=None, *, host: str | None = None, origin: str | None = "same", content_type="application/json"):
        port = urlsplit(self.origin).port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Host": host or self.netloc}
        if origin is not None:
            headers["Origin"] = self.origin if origin == "same" else origin
        payload = None
        if body is not None:
            payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
            headers["Content-Type"] = content_type
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            return response.status, json.loads(data)
        except ValueError:
            return response.status, data

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, body=None, **kwargs):
        return self.request("POST", path, {} if body is None else body, **kwargs)


class DirectClient:
    """The same calls as `Client`, straight into `ReviewApp` — no socket, so it runs anywhere.

    Only the routes the page's logic uses; the HTTP checks themselves (Host,
    Origin, content type, headers) are covered over a real socket in
    test_review_app.py.
    """

    def __init__(self, store) -> None:
        from proof_cli.webapp.server import ReviewApp

        self.app = ReviewApp(store)
        self.origin = self.app.origin

    def _call(self, action):
        from proof_cli.proof_map import ProofMapError
        from proof_cli.webapp.server import RequestError

        try:
            return 200, json.loads(json.dumps({"ok": True, "data": action()}, default=str))
        except RequestError as exc:
            return int(exc.status), {"ok": False, "error": {"code": exc.code, "message": exc.message, **exc.details}}
        except ProofMapError as exc:
            return 400, {"ok": False, "error": {"code": exc.code, "message": exc.message, **exc.details}}

    def get(self, path, **kwargs):
        if path == "/api/state":
            return self._call(self.app.state)
        if path == "/api/health":
            return self._call(self.app.health)
        if path.startswith("/api/node/"):
            node_id = path.removeprefix("/api/node/")
            return self._call(lambda: self.app.node(node_id))
        raise AssertionError(f"DirectClient doesn't route GET {path}")

    def post(self, path, body=None, **kwargs):
        if path == "/api/decide":
            return self._call(lambda: self.app.decide(body or {}))
        raise AssertionError(f"DirectClient doesn't route POST {path}")


def decide(client, decisions):
    """What the page's Record button sends."""
    return client.post("/api/decide", {"decisions": decisions})
