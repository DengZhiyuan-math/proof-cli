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
from ..domain import Medium, ProofMapNodeKind
from ..reviews import git_identity
from ..storage import ProjectStore, get_current_candidate_proof
from ..studio.proof_agent import ProofAgentContext, library_folders, open_command
from ..studio.server import ComputationHooks, FinishedRun, RunInputs, RunRecord, Studio
from ..vault import (SNAPSHOT_MANIFEST, frozen_digests, frozen_role, node_folder, read_working_snapshot,
                     working_inputs)

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
    """The hub's refusals in the studio's one error shape, {"error": message, "code": CODE}."""
    import json

    body = json.dumps({"error": message, "code": code}).encode("utf-8")
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
                    # and knowing the node's dependencies as of each turn, to draft its key ideas (ADR-0013)
                    agent_context=lambda: ProofAgentContext(
                        node_id, root, library_folders(root), dependencies=self._dependencies(node_id),
                        on_drafted=lambda agent, data: proof_map.record_key_ideas_draft(self.store, node_id, agent=agent, content=data),
                    ),
                    # the node's Medium as of each request, a run recorded as an Evidence check as the page's
                    # identity, and the project's optional open command (spec #145)
                    computation=ComputationHooks(
                        medium=lambda: self._medium(node_id),
                        run_inputs=lambda: self._run_inputs(node_id),
                        record_run=lambda run: self._record_run(node_id, run),
                        open_command=lambda: open_command(root),
                    ),
                )
            return self._studios[node.id]

    def _medium(self, node_id: str) -> str | None:
        node = proof_map.get_node(self.store, node_id)
        return node.medium.value if node is not None and node.medium is not None else None

    def _run_inputs(self, node_id: str) -> RunInputs | None:
        """The state of the program's inputs (`vault.frozen_role` is `input`: its scripts, data and hidden environment
        files, never `out/`): their inputs digest, as `frozen_inputs_digest` hashes a snapshot's, and a stamp of each
        (size, mtime, ctime, inode). An input edited during a run and put back before it ends has its content as
        before but not its stamp (audit R-S1); its ctime no program can set back. None when an input can't be read."""
        try:
            paths = {rel: path for rel, path in working_inputs(self.store.root, node_id, Medium.computation).items()
                     if frozen_role(rel) == "input"}
            stamps = {rel: f"{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}:{st.st_ino}" for rel, path in paths.items() for st in [path.stat()]}
            digest = read_working_snapshot(self.store.root, node_id, Medium.computation).inputs_digest()
        except OSError:
            return None
        return RunInputs(digest, stamps)

    @staticmethod
    def _changed_during(before: RunInputs, after: RunInputs) -> str | None:
        """Why the inputs are not the ones the run started with, naming the first input that changed; None if none did."""
        if before == after:
            return None
        written = sorted(set(after.stamps) - set(before.stamps))
        if written:
            return f"the run wrote outside out/ ({written[0]}), which changed its inputs"
        touched = sorted(rel for rel in before.stamps if before.stamps[rel] != after.stamps.get(rel))
        return f"inputs changed during the run ({touched[0]})" if touched else "inputs changed during the run"

    def _record_run(self, node_id: str, run: FinishedRun) -> RunRecord:
        """The Evidence rule (ADR-0015): a run is an Evidence check on the node's current snapshot only when it ran to
        its end (not stopped, not timed out), its inputs were untouched from before it to after it, and they are the
        inputs the snapshot froze. Its outputs may differ: the check is of the execution outcome for the frozen
        inputs, not a certificate of the frozen outputs. Recorded bound to the snapshot hash read together with the
        frozen inputs it was compared with; otherwise nothing is recorded, and the note says why."""
        proof = get_current_candidate_proof(self.store, node_id)
        if run.stopped is not None:
            return {"evidence": None, "note": f"{run.stopped} — not recorded as an Evidence check: only a run that completes is one"}
        if proof is None:
            return {"evidence": None, "note": "no snapshot yet — not recorded: request review, and runs of what it froze are recorded as Evidence checks on it"}
        version = f"snapshot v{proof.version}"
        if run.before is None or run.after is None:
            return {"evidence": None, "note": f"an input could not be read — not recorded against {version}"}
        changed = self._changed_during(run.before, run.after)
        if changed:
            return {"evidence": None, "note": f"{changed} — not recorded against {version}"}
        snapshot = self.store.root / proof.file_path
        frozen = frozen_digests(snapshot.parent) if snapshot.name == SNAPSHOT_MANIFEST else None
        if frozen is None:
            return {"evidence": None, "note": f"{version} can't be read — not recorded"}
        snapshot_sha256, frozen_inputs = frozen
        if run.before.digest != frozen_inputs:
            return {"evidence": None, "note": f"inputs differ from {version} — not recorded: request review to freeze them"}
        try:
            check = proof_map.record_evidence_check(self.store, proof.id, run.outcome, notes=run.notes,
                                                    run_by=git_identity(self.store.root), snapshot_sha256=snapshot_sha256)
        except proof_map.ProofMapError as exc:  # the snapshot changed between the comparison and the record
            return {"evidence": None, "note": f"{version} changed while the run was recorded — not recorded: {exc.message}"}
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
