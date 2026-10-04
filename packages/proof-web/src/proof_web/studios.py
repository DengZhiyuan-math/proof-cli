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
from urllib.parse import parse_qs, quote, unquote

from proof_cli import proof_map
from proof_cli.domain import ProofMapNodeKind
from proof_cli.reviews import git_identity
from proof_cli.storage import ProjectStore, get_current_candidate_proof, read_project_instance_id
from proof_cli.authority import candidate_proof_sha256
from proof_cli.key_ideas import KEY_IDEAS_FILE
from proof_cli.vault import OUT_DIR, RUN_SCRIPT, manifest_digest, node_folder, working_inputs
from latex_agent.httpbase import STATIC as STUDIO_STATIC  # the studio page: latex-agent's, served here per node
from latex_agent.server import Studio
from proof_agents.agent_run import AgentRun, RunHooks
from proof_agents.proof_agent import ProofAgentContext, agent_name, budget, library_folders, open_command

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
        # The project this hub was made for, by instance id. A folder can come to hold another project (deleted and
        # started again at the same path, from the Home or a terminal) while an old turn is still ending; what that
        # turn's hooks would write — a release, a stuck step, a draft, a run's record — belongs to the old project,
        # so every write first asks whether the folder still holds it (`_attached`). The Home also says so outright
        # (`detach`) when it retires the page.
        self._instance = read_project_instance_id(store)
        self._detached = False

    def studio(self, node_id: str) -> Studio:
        if not self._attached():  # the folder holds another project now (or none): this page's studios are not its
            raise NoStudio("PROJECT_REPLACED", "the project this page was opened for is no longer in its folder; open the project from the Home")
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
                    key_ideas_file=KEY_IDEAS_FILE, run_script=RUN_SCRIPT,
                    # the node's proof agent: rooted at the project, reading its library (ADR-0011 point 8),
                    # and knowing the node's dependencies as of each turn, to draft its key ideas (ADR-0013)
                    agent_context=lambda: ProofAgentContext(
                        node_id, root, library_folders(root), dependencies=self._dependencies(node_id),
                        name=self.turn_name(node_id),
                        on_drafted=lambda agent, data: self._record_draft(node_id, agent, data),
                        # a run's turn (spec #145): which role, and the researcher's redirect for it
                        role=self.turn_role(node_id), redirect=self.turn_redirect(node_id),
                    ),
                    # the node's run (proof-agents, spec #145), on this studio's agent manager
                    run=lambda agent: AgentRun(agent, RunHooks(
                        agent_name=lambda provider: agent_name(root, provider),
                        budget=lambda: budget(root),
                        assign=lambda name: self._assign(node_id, name),
                        release=lambda name: self._release(node_id, name),
                        work_log=lambda: self._work_log(node_id),
                        record_stuck=lambda role, name, note: self._record_stuck(node_id, role, name, note),
                        review_now=lambda: self._review_now(node_id),
                    )),
                    # the node's Medium as of each request, a run recorded as an Evidence check as the page's
                    # identity, and the project's optional open command (spec #145)
                    node_medium=lambda: self._medium(node_id),
                    on_run=lambda outcome, notes, before, after: self._record_run(node_id, outcome, notes, before, after),
                    working_digest=lambda: self._working_digest(node_id),
                    open_command=lambda: open_command(root),
                )
                # the agent's compile tool builds through this node's studio (taken from upstream, 2938c05):
                # a LaTeX node's Typesetter compiles what the researcher sees; a computation node has no build
                self._studios[node.id].agent.server_url = lambda: self._studio_url(node_id) if self._medium(node_id) != "computation" else None
            return self._studios[node.id]

    def _studio_url(self, node_id: str) -> str:
        from .server import project_origin  # the page's pinned origin (a late import: server.py imports this module)

        return f"{project_origin(self.store)}/studio/{quote(node_id, safe='')}/"

    # -- a run's turn (spec #145): what the context of the turn being started takes from the node's run
    def _active_run(self, node_id: str):
        studio = self._studios.get(node_id)
        run = studio.run if studio is not None else None
        return run if run is not None and run.active() else None

    def turn_role(self, node_id: str) -> str | None:
        run = self._active_run(node_id)
        return run.role_for_turn() if run is not None else None

    def turn_redirect(self, node_id: str) -> str | None:
        run = self._active_run(node_id)
        return run.redirect_for_turn() if run is not None else None

    def turn_name(self, node_id: str) -> str:
        run = self._active_run(node_id)
        return run.state.name if run is not None and run.state.name else "studio-agent"

    def _still_this_project(self) -> None:
        """A write on behalf of this page's project: refused when the folder holds another (as a refusal, with its code)."""
        if not self._attached():
            raise proof_map.ProofMapError("PROJECT_REPLACED", "the project this page was opened for is no longer in its folder; open the project from the Home")

    def _assign(self, node_id: str, name: str) -> None:
        """A Start claims the node for the run — only while the folder still holds this project."""
        self._still_this_project()
        proof_map.claim_node(self.store, node_id, claimant_id=name)

    def _release(self, node_id: str, name: str) -> None:
        """Release the node when the run still holds it (a review request already released it)."""
        if not self._attached():  # the folder holds another project now (or none): not this run's node to release
            return
        claim = proof_map.get_active_claim(self.store, node_id)
        if claim is not None and claim.claimant_id == name:
            proof_map.release_node(self.store, node_id, claimant_id=name, reason="released by the researcher")

    def _review_now(self, node_id: str) -> dict:
        """Review what the agent has (spec #145): freeze a snapshot of the folder as it stands. A node someone holds
        is theirs to hand over, so the request is made in the assignee's name — the run's — which ends the run as
        a review request does; an unheld node is frozen as the researcher."""
        self._still_this_project()
        claim = proof_map.get_active_claim(self.store, node_id)
        requested_by = claim.claimant_id if claim is not None else git_identity(self.store.root)
        record = proof_map.request_review(self.store, node_id, requested_by=requested_by, rationale="the researcher reviews what the agent has, as it stands")
        return record.model_dump(mode="json")

    def _record_draft(self, node_id: str, agent: str, data: bytes) -> None:
        """A drafting turn's last word (ADR-0013), which arrives after the turn — unless the project it drafted for is
        gone from the folder: then the summary there is the new project's author's, not this agent's draft."""
        if not self._attached():
            return
        proof_map.record_key_ideas_draft(self.store, node_id, agent=agent, content=data)

    def _work_log(self, node_id: str) -> list[dict]:
        return proof_map.work_log(self.store, node_id) if self._attached() else []

    def _record_stuck(self, node_id: str, role: str, name: str, note: str) -> None:
        """The run's own last word as a stuck step — unless the project it ran on is gone from the folder."""
        if not self._attached():
            return
        proof_map.record_progress(self.store, node_id, role=role, by=name, step=self._last_step(node_id), status="stuck", note=note)

    def _last_step(self, node_id: str) -> int:
        steps = [e["step"] for e in proof_map.work_log(self.store, node_id) if e.get("kind") == "step"]
        return steps[-1] if steps else 1

    def run_action(self, node_id: str, action: str, body: dict) -> tuple[int, dict]:
        """The researcher's oversight of a node's run through the map's own API (spec #145): (status, the studio's answer)."""
        try:
            studio = self.studio(node_id)
        except NoStudio as exc:
            code, message = exc.args
            return int(HTTPStatus.GONE if code == "PROJECT_REPLACED" else HTTPStatus.NOT_FOUND), {"error": code, "message": message}
        return studio.run_action(action, body or {})

    def run_state(self, node_id: str) -> dict | None:
        """The node's run as the map shows it (spec #145): None when no run is active."""
        run = self._active_run(node_id)
        if run is None:
            return None
        view = run.view()
        return {"status": view["status"], "role": view["role"], "step": view["step"], "steps": view["steps"]}

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
        if not self._attached():
            return {"evidence": None, "note": "the project this studio was opened for is no longer in its folder: nothing recorded"}
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

    def _attached(self) -> bool:
        """Whether the folder still holds the project this hub was made for."""
        if self._detached or not self.store.db_path.is_file():
            return False
        try:
            return read_project_instance_id(self.store) == self._instance
        except Exception:  # noqa: BLE001 — a database that can't be read is not this project's either
            return False

    def detach(self) -> None:
        """The folder this hub serves holds another project now, or none (the Home found a new instance id, or no
        project): from here on its runs' hooks write nothing — a release, a stuck step — so that closing the old
        page can't touch the new project's state (a node and a claimant of the same names, say)."""
        self._detached = True

    def close(self) -> None:
        with self._lock:
            self._closed = True
            studios, self._studios = list(self._studios.values()), {}
        failed: list[Exception] = []
        for studio in studios:  # every studio closes, whatever one of them raises
            try:
                studio.close()
            except Exception as exc:  # noqa: BLE001 — reported once the rest are closed
                failed.append(exc)
        if failed:
            raise failed[0]

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
            status = {"STUDIO_CLOSED": HTTPStatus.SERVICE_UNAVAILABLE, "PROJECT_REPLACED": HTTPStatus.GONE}.get(code, HTTPStatus.NOT_FOUND)
            return _error(status, code, message)
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
