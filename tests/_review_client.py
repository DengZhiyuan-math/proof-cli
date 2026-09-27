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
