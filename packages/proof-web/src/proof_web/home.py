"""The Home: the researcher's projects, in front of each project's proof map page (ADR-0017).

One local server on its own fixed localhost port (`home_origin()`), the same for every project.
It lists the registered projects (`proof_cli.projects`), each read live from its own database:
its id, its theorem, how many nodes, what is on the frontier, what awaits the researcher. Opening
one starts that project's own `ReviewServer`, on the project's own origin, inside this process
(`ProjectHub`), and the browser moves there; a project page opened this way links back here.
A project already served elsewhere (a `proof map serve` in a terminal) is used as it is.

The Home writes nothing in any project. Its own writes are the project list (add, forget) and
`create`, which starts a new project the way `proof init` does. Host and Origin are checked as
on the project page: another web page in the researcher's browser can't start or forget projects.
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from proof_cli import proof_map
from proof_cli.domain import ProofMapNodeKind
from proof_cli.fog import list_fog
from proof_cli.projects import forget_project, is_project, list_registered, project_key, register_project
from proof_cli.storage import ProjectStore, ensure_project, read_only, read_project_instance_id, read_scope, read_state
from .server import RP_ID, _ORIGIN_PORT_BASE, _ORIGIN_PORT_SPAN, RequestError, ReviewServer, _Handler, project_origin

HOME_PORT = _ORIGIN_PORT_BASE + int(hashlib.sha256(b"proof-cli home").hexdigest()[:8], 16) % _ORIGIN_PORT_SPAN


def home_origin() -> str:
    """The Home's own origin: one fixed port on localhost, the same on every project."""
    return f"http://{RP_ID}:{HOME_PORT}"


def _health(url: str, timeout: float = 2) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            return json.loads(response.read())["data"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def project_answering(store: ProjectStore) -> bool:
    """Whether this project's proof map page already answers on its origin (from any process)."""
    health = _health(project_origin(store))
    return health is not None and health.get("instance") == read_project_instance_id(store)


def home_answering() -> bool:
    """Whether a Home already answers on its port."""
    health = _health(home_origin())
    return health is not None and health.get("home") is True


def ask_home_to_open(root: str | Path) -> str:
    """Ask the running Home to serve the project at `root` (as its page would); the project's URL."""
    body = json.dumps({"path": project_key(root)}).encode("utf-8")
    request = urllib.request.Request(
        f"{home_origin()}/api/projects/open", data=body, method="POST",
        headers={"Content-Type": "application/json", "Origin": home_origin()},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        answer = json.loads(response.read())
    if not answer.get("ok"):
        raise OSError(answer.get("error", {}).get("message", "the Home refused"))
    return answer["data"]["url"]


class ProjectHub:
    """The project pages this process serves, one `ReviewServer` per project folder, started on first open.

    A page is the page of a project *instance*, not of a folder: its origin is derived from the
    instance id, and its node studios and runs belong to that project. A folder that comes to hold
    another project (deleted and started again at the same path) gets a new page; the old one, with
    its studios, is closed first.
    """

    def __init__(self) -> None:
        self._servers: dict[str, tuple[ReviewServer, str]] = {}  # key -> (server, the instance id it serves)
        self._lock = threading.Lock()

    def url_of(self, key: str) -> str | None:
        """The project's URL when this process serves it."""
        served = self._servers.get(key)
        return served[0].url if served is not None else None

    @staticmethod
    def _instance(key: str) -> str | None:
        """The instance id of the project in the folder now, or None when it holds none (never starts one)."""
        return read_project_instance_id(ProjectStore(Path(key))) if is_project(key) else None

    @staticmethod
    def _retire(server: ReviewServer, *, stale: bool) -> None:
        """Close a page. `stale`: the folder holds another project now (or none), so the page's studios are
        detached first and write nothing there — a release or a draft of the old project's run must not
        land on the new project's node of the same name."""
        if stale:
            server.app.studios.detach()
            try:
                _close(server)
            except Exception:  # noqa: BLE001 — a dead page's trouble closing is not the next page's
                pass
        else:
            _close(server)

    def ensure(self, key: str) -> str:
        """Serve the project (once per instance); its URL. A page already answering elsewhere is left to answer."""
        with self._lock:
            store = ProjectStore(Path(key))
            instance = self._instance(key)
            served = self._servers.get(key)
            if served is not None:
                if served[1] == instance:
                    return served[0].url
                self._servers.pop(key)
                self._retire(served[0], stale=True)
            if instance is None:
                raise RequestError(HTTPStatus.NOT_FOUND, "PROJECT_NOT_FOUND", f"no proof project at {key}")
            if project_answering(store):
                return project_origin(store)
            try:
                server = ReviewServer(store, home_url=home_origin())
            except OSError as exc:
                raise RequestError(HTTPStatus.CONFLICT, "PORT_BUSY", f"this project's port is taken by something else ({exc})")
            threading.Thread(target=server.serve_forever, daemon=True, name=f"proof-map {Path(key).name}").start()
            self._servers[key] = (server, instance)
            return server.url

    def stop(self, key: str) -> None:
        """Stop the project's page (Forget, or the Home closing); stale when the folder's project is not the one it served."""
        with self._lock:
            served = self._servers.pop(key, None)
            stale = served is not None and self._instance(key) != served[1]
        if served is not None:
            self._retire(served[0], stale=stale)

    def close(self) -> None:
        """Stop every page; one page's trouble closing doesn't leave the others running (reported once all are stopped)."""
        failed: list[Exception] = []
        for key in list(self._servers):
            try:
                self.stop(key)
            except Exception as exc:  # noqa: BLE001
                failed.append(exc)
        if failed:
            raise failed[0]


def _close(server: ReviewServer) -> None:
    """Stop a project page: its listener, then what its node studios still run (builds, agent turns, runs)."""
    server.shutdown()
    server.server_close()


class HomeApp:
    """The Home's behaviour, apart from HTTP, so it can be tested directly."""

    def __init__(self) -> None:
        self.origin = home_origin()
        self.hub = ProjectHub()

    def close(self) -> None:
        self.hub.close()

    def health(self) -> dict:
        return {"home": True, "origin": self.origin}

    # -- reads -------------------------------------------------------------------

    def projects(self) -> dict:
        return {"origin": self.origin, "projects": [self._summary(entry) for entry in list_registered()]}

    def _summary(self, entry: dict) -> dict:
        """One project as its card shows it, read live from its database; a folder that is gone, or
        isn't a project, says so (and is still listed, so it can be forgotten)."""
        key = entry["path"]
        path = Path(key)
        card = {
            "path": key,
            "name": path.name or key,
            "added_at": entry.get("added_at"),
            "opened_at": entry.get("opened_at"),
            "exists": path.is_dir(),
            "project": is_project(key),
            "running": self.hub.url_of(key) is not None,
            "url": None,
            "project_id": None,
            "theorem": None,
            "counts": None,
            "error": None,
        }
        if not card["exists"]:
            card["error"] = "The folder is gone (moved or deleted)."
            return card
        if not card["project"]:
            card["error"] = "No proof project in this folder: `proof init` starts one."
            return card
        store = ProjectStore(path)
        try:
            with read_only(), store.transaction(), read_scope():
                nodes = proof_map.list_nodes(store)
                frontier = len(proof_map.get_frontier(store))
                awaiting = accepted = 0
                theorem = None
                for node in nodes:
                    if node.kind == ProofMapNodeKind.imported_result:
                        if proof_map.get_reference_review_state(store, node.id) in ("unreviewed", "unverifiable"):
                            awaiting += 1
                        continue
                    if node.kind == ProofMapNodeKind.theorem and theorem is None:
                        theorem = node.display_label or node.statement
                    if proof_map.get_workflow_state(store, node.id) == "review-needed":
                        awaiting += 1
                    if proof_map.get_acceptance_state(store, node.id) == "accepted":
                        accepted += 1
                card.update(
                    project_id=read_state(store).project_id,
                    url=project_origin(store),
                    theorem=theorem,
                    counts={"nodes": len(nodes), "frontier": frontier, "awaiting": awaiting, "accepted": accepted, "fog": len(list_fog(store))},
                )
        except Exception as exc:  # a damaged or locked database: the card says so, the list still shows
            card["error"] = f"The project can't be read ({type(exc).__name__})."
        if not card["running"] and card["url"]:
            card["running"] = _health(card["url"], timeout=0.3) is not None  # served from a terminal
        return card

    # -- writes ------------------------------------------------------------------

    @staticmethod
    def _path(body: dict) -> str:
        raw = body.get("path")
        if not isinstance(raw, str) or not raw.strip():
            raise RequestError(HTTPStatus.BAD_REQUEST, "PATH_REQUIRED", "say which folder")
        return project_key(raw.strip())

    def open(self, body: dict) -> dict:
        """Serve the project and say where: {url}. Only a listed project opens from here."""
        key = self._path(body)
        if key not in {entry["path"] for entry in list_registered()}:
            raise RequestError(HTTPStatus.NOT_FOUND, "PROJECT_UNKNOWN", "this folder isn't in your projects; add it first")
        url = self.hub.ensure(key)  # PROJECT_NOT_FOUND when the folder holds none, after closing any page it served
        register_project(key, opened=True)
        return {"url": url, "path": key}

    def add(self, body: dict) -> dict:
        """List an existing project. A folder without one is refused: `create` starts one."""
        key = self._path(body)
        if not Path(key).is_dir():
            raise RequestError(HTTPStatus.NOT_FOUND, "FOLDER_NOT_FOUND", f"no folder at {key}")
        if not is_project(key):
            raise RequestError(HTTPStatus.BAD_REQUEST, "NOT_A_PROJECT", f"no proof project at {key} (create one there instead?)")
        return self._summary(register_project(key))

    def create(self, body: dict) -> dict:
        """Start a project in the folder (made if need be), as `proof init` does, and list it."""
        key = self._path(body)
        if is_project(key):
            raise RequestError(HTTPStatus.CONFLICT, "ALREADY_A_PROJECT", f"{key} already holds a project; add it instead")
        self.hub.stop(key)  # a page still served for a project that was deleted from this folder: retired (detached) before the new one starts
        project_id = body.get("project_id")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise RequestError(HTTPStatus.BAD_REQUEST, "BAD_PROJECT_ID", "the project id must be a non-empty string")
        try:
            ensure_project(key, project_id.strip()) if project_id else ensure_project(key)
        except OSError as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "CANNOT_CREATE", f"can't start a project at {key}: {exc}")
        return self._summary(register_project(key))

    def forget(self, body: dict) -> dict:
        """Drop the project from the list, stopping its page if this process serves it; the folder is untouched."""
        key = self._path(body)
        self.hub.stop(key)
        return {"forgotten": forget_project(key), "path": key}


class _HomeHandler(_Handler):
    app: HomeApp  # type: ignore[assignment]  # the Host and Origin checks need only `.origin`
    server_version = "proof-home"

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.MISDIRECTED_REQUEST, "WRONG_HOST", f"open the Home at {self.app.origin}")
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self._static("home.html")
        if path.startswith("/static/shared/"):
            return self._shared(path.removeprefix("/static/shared/"))
        if path.startswith("/static/"):
            return self._static(path.removeprefix("/static/"))
        if path == "/api/health":
            return self._guarded(self.app.health)
        if path == "/api/projects":
            return self._guarded(self.app.projects)
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", path)

    def do_POST(self) -> None:  # noqa: N802
        body = self._json_body()
        if body is None:
            return
        routes = {
            "/api/projects/open": self.app.open,
            "/api/projects/add": self.app.add,
            "/api/projects/create": self.app.create,
            "/api/projects/forget": self.app.forget,
        }
        route = routes.get(urlsplit(self.path).path)
        if route is None:
            return self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", self.path)
        self._guarded(lambda: route(body))


class HomeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *, port: int | None = None) -> None:
        self.app = HomeApp()
        handler = type("HomeHandler", (_HomeHandler,), {"app": self.app})
        super().__init__(("127.0.0.1", HOME_PORT if port is None else port), handler)

    @property
    def url(self) -> str:
        return self.app.origin

    def server_close(self) -> None:
        super().server_close()
        self.app.close()


__all__ = ["HOME_PORT", "HomeApp", "HomeServer", "ProjectHub", "ask_home_to_open", "home_answering", "home_origin", "project_answering"]
