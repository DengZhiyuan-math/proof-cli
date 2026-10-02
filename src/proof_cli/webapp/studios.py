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

import hashlib
import threading
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, unquote

from .. import proof_map
from ..domain import ProofMapNodeKind
from ..reviews import git_identity
from ..storage import ProjectStore, get_current_candidate_proof
from ..studio.agent_run import ACTIVE, RunHooks
from ..studio.proof_agent import ProofAgentContext, agent_name, budget, library_folders, open_command
from ..studio.server import Studio
from ..authority import candidate_proof_sha256
from ..vault import OUT_DIR, manifest_digest, node_folder, working_inputs

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
    ".woff2": "font/woff2",  # KaTeX's fonts (ADR-0013)
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
        self._closed = False

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
            if self._closed:
                raise NoStudio("STUDIO_CLOSED", "the proof map's server is shutting down")
            if node.id not in self._studios:
                root, node_id = self.store.root, node.id
                self._studios[node.id] = Studio(
                    folder, fixed_build=NODE_BUILD, hidden=NODE_HIDDEN, agent_scratch="scratch",
                    # the node's proof agent: rooted at the project, reading its library (ADR-0011 point 8),
                    # and knowing the node's dependencies as of each turn, to draft its key ideas (ADR-0013).
                    # A run's turn (spec #145) comes with its role and name from the run's own record; the
                    # researcher's own turn (an Ask) comes with none, whatever the run is doing meanwhile.
                    agent_context=lambda turn=None: ProofAgentContext(
                        node_id, root, library_folders(root), dependencies=self._dependencies(node_id),
                        name=(turn or {}).get("name") or "studio-agent",
                        on_drafted=lambda agent, data: proof_map.record_key_ideas_draft(self.store, node_id, agent=agent, content=data),
                        role=(turn or {}).get("role"),
                    ),
                    run_hooks=RunHooks(
                        agent_name=lambda provider: agent_name(root, provider),
                        budget=lambda: budget(root),
                        assign=lambda name: proof_map.claim_node(self.store, node_id, claimant_id=name),
                        release=lambda name, reason: self._release(node_id, name, reason),
                        work_log=lambda: proof_map.work_log(self.store, node_id),
                        record_close=lambda role, name, status, note: proof_map.record_progress(
                            self.store, node_id, role=role, by=name, step=self._last_step(node_id), status=status, note=note),
                        record_turn=lambda turn: proof_map.record_agent_turn(self.store, node_id, **turn),
                        transcript=lambda turn: proof_map.agent_turn_transcript(self.store, node_id, turn),
                    ),
                    # the node's Medium as of each request, a run recorded as an Evidence check as the page's
                    # identity, and the project's optional open command (spec #145)
                    node_medium=lambda: self._medium(node_id),
                    on_run=lambda outcome, notes, before, after: self._record_run(node_id, outcome, notes, before, after),
                    working_digest=lambda: self._working_digest(node_id),
                    open_command=lambda: open_command(root),
                )
            return self._studios[node.id]

    def _release(self, node_id: str, name: str, reason: str) -> None:
        """Release the node when the run still holds it (a review request already released it), saying why."""
        claim = proof_map.get_active_claim(self.store, node_id)
        if claim is not None and claim.claimant_id == name:
            proof_map.release_node(self.store, node_id, claimant_id=name, reason=reason)

    def _last_step(self, node_id: str) -> int:
        steps = [e["step"] for e in proof_map.work_log(self.store, node_id) if e.get("kind") == "step"]
        return steps[-1] if steps else 1

    def run_action(self, node_id: str, action: str, body: dict) -> tuple[int, dict]:
        """The researcher's oversight of a node's run through the map's own API (spec #145): (status, the studio's answer)."""
        try:
            studio = self.studio(node_id)
        except NoStudio as exc:
            code, message = exc.args
            return int(HTTPStatus.NOT_FOUND), {"error": message, "code": code}
        return studio.run_action(action, body or {})

    def run_state(self, node_id: str) -> dict | None:
        """The node's run as the map shows it (spec #145): while it is active, or waiting on a decision only the
        researcher can make; None otherwise."""
        studio = self._studios.get(node_id)
        if studio is None or studio.run is None:
            return None
        view = studio.run.view()
        if view["status"] not in (*ACTIVE, "needs-human"):
            return None
        return {"status": view["status"], "role": view["role"], "step": view["step"], "steps": view["steps"], "decision": view["decision"]}

    def _medium(self, node_id: str) -> str | None:
        node = proof_map.get_node(self.store, node_id)
        return node.medium.value if node is not None and node.medium is not None else None

    def _working_digest(self, node_id: str) -> tuple[str, str]:
        """What a run ran, twice over: the content digest of the node folder's inputs, as a snapshot would freeze them,
        and a stamp of every input but the outputs — its size and the time it was last written. A program's inputs
        must not be touched while it runs: an edit undone before the run ends leaves the content as it was, not the
        stamp (audit R-S1). Its outputs it writes itself, so they are compared by content alone."""
        inputs = working_inputs(self.store.root, node_id)
        content = manifest_digest({rel: hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in inputs.items()})
        stamp = manifest_digest({rel: f"{st.st_size}:{st.st_mtime_ns}:{st.st_ino}" for rel, path in inputs.items()
                                 if rel.split("/", 1)[0] != OUT_DIR for st in [path.stat()]})
        return content, stamp

    def _record_run(self, node_id: str, outcome: str, notes: str, before: tuple[str, str] | None, after: tuple[str, str] | None) -> dict:
        """A run is an Evidence check on a specific Candidate proof (ADR-0004): recorded only when the folder it ran in
        is the current snapshot — untouched from before the run to after it (content and stamp alike), and the same as
        what was frozen. Otherwise nothing is recorded, and the answer says why."""
        proof = get_current_candidate_proof(self.store, node_id)
        if proof is None:
            return {"evidence": None, "note": "no snapshot yet: request review, and runs of what it froze are recorded as Evidence checks on it"}
        if before is None or before != after:
            return {"evidence": None, "note": f"the folder changed during the run, so it is not snapshot v{proof.version} that ran: request review to freeze what is there now"}
        if before[0] != candidate_proof_sha256(self.store, proof.id):
            return {"evidence": None, "note": f"the program differs from snapshot v{proof.version}: request review to freeze it, and runs of it are recorded"}
        check = proof_map.record_evidence_check(self.store, proof.id, outcome, notes=notes, run_by=git_identity(self.store.root))
        return {"evidence": check.model_dump(mode="json"), "note": ""}

    def _dependencies(self, node_id: str) -> list[str]:
        node = proof_map.get_node(self.store, node_id)
        return list(node.dependencies) if node is not None else []

    def close(self) -> None:
        with self._lock:
            self._closed = True
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
            return _error(HTTPStatus.SERVICE_UNAVAILABLE if code == "STUDIO_CLOSED" else HTTPStatus.NOT_FOUND, code, message)
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
