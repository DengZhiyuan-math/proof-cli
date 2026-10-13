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

import dataclasses
import hashlib
import threading
import uuid
from dataclasses import dataclass, fields
from functools import partial
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from proof_cli import key_ideas, node_check, proof_map
from proof_cli.memory import node_scope_memory
from proof_cli.retrieval import retrieve_memory
from proof_cli.domain import Medium, ProofMapNodeKind
from proof_cli.reviews import git_identity
from proof_cli.errors import ERROR_CODES
from proof_cli.key_ideas import KEY_IDEAS_FILE
from .definitions_view import node_definitions
from proof_cli.storage import ProjectStore, get_active_claim, get_current_candidate_proof, read_project_instance_id
from proof_agents.agent_run import ACTIVE, AgentRun, RunHooks
from proof_agents.coordinator import Coordinator, CoordinatorHooks
try:  # ADR-0021: Pursue on a project with no map; an older proof-agents has no Reader and no project pursuit
    from proof_agents.coordinator import ProjectPursuit, PursuitHooks
    from proof_agents.reader import ReaderContext
except ImportError:  # pragma: no cover — the page then offers Pursue on a Theorem only
    ProjectPursuit = PursuitHooks = ReaderContext = None
from proof_agents.map_agent import MAP_AGENT_NAME, MapAgentContext
from proof_agents.proof_agent import ProofAgentContext, agent_name, budget, library_folders, open_command, parallel, studio_settings

_CONTEXT_HAS_GATE = "review_gate" in {f.name for f in dataclasses.fields(ProofAgentContext)}  # ADR-0019 wave 2a
_CONTEXT_HAS_PROJECT = "project_id" in {f.name for f in fields(ProofAgentContext)}  # re-audit P1: the memory rule names the project too
_CONTEXT_HAS_PURSUE = "pursue" in {f.name for f in fields(ProofAgentContext)}  # ADR-0021 point 7: a Coordinator's Decomposer does not stop
_COORDINATOR_PARKS = "park" in {f.name for f in fields(CoordinatorHooks)}  # ADR-0021 point 9
# a project pursuit's Stop while its Reader reads stops the Reader's turn too (contract C4); an older one leaves it to the host
_PURSUIT_STOPS_READ = PursuitHooks is not None and "stop_read" in {f.name for f in fields(PursuitHooks)}
_PURSUIT_AT_WORK = ("reading", "pursuing")
# a pursuit giving its runs back, or holding them after that failed (proof-agents#17): Stop goes on, Pursue waits
_PURSUIT_HOLDING = ("stopping", "release-failed")
from latex_agent.agent import AgentManager
from proof_web.review_queue import PARKED_NOTE, awaiting_review, parked_reason
from latex_agent.server import ComputationHooks, FinishedRun, RunInputs, RunRecord, Studio
from proof_cli.vault import (read_working_snapshot, RUN_SCRIPT, SNAPSHOT_MANIFEST, NodeFolderLinks, frozen_digests, frozen_role, inputs_digest, is_executable,
                     node_folder, working_inputs, working_links)

from latex_agent.httpbase import STATIC as STUDIO_STATIC  # the studio page: latex-agent's, served here per node

# the briefing's shared entries (ADR-0019 point 14): a fixed count from each source, the whole briefing capped by the run
LEARNED = ("failed", "tactic", "tentative")   # memory's statuses that are what was learned, as against what is settled (point 8)
OWN_NOTES = 4          # this node's own learned entries, newest first
NEIGHBOUR_NOTES = 2    # each dependency's, dependent's and sibling's
RETRIEVED_NOTES = 4    # memory elsewhere in the map, by the node's statement
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
# The node page is latex-agent's studio page with this package's scripts appended (ADR-0018): the node panel, the
# run pane and the agent panel's "+" menu speak to the map's routes; the status glyphs and the maths renderer are the
# map page's too. Resolved before latex-agent's folder when the page asks for `static/<name>`.
WEB_STATIC = Path(__file__).resolve().parent / "static"
NODE_STATIC = WEB_STATIC / "studio"
HOST_SCRIPTS = ("menu.js", "mathtext.js", "status.js", "node.js", "run.js")  # in load order: menu.js first, as the page had it
HOST_FILES = {"menu.js": NODE_STATIC / "menu.js", "node.js": NODE_STATIC / "node.js", "run.js": NODE_STATIC / "run.js",
              "status.js": WEB_STATIC / "status.js", "mathtext.js": WEB_STATIC / "mathtext.js", "node.css": NODE_STATIC / "node.css"}
# the studio page's host slots (latex-agent's index.html: `<!-- host:NAME -->`) and the markup this package puts in each
HOST_SLOTS = ("brand", "sidebar", "centre-top", "centre-pane", "chat-foot", "chat-actions")
FRAGMENTS = NODE_STATIC / "fragments"


def node_page() -> bytes:
    """A node's page, assembled from parts (ADR-0018): latex-agent's studio page, its host slots filled with this package's
    markup (the node section, the centre's Work log tab bar and run pane, the review card and the "+" menu, the link back to
    the map), this package's stylesheet in its head and its scripts before </body>."""
    page = (STUDIO_STATIC / "index.html").read_text(encoding="utf-8")
    for slot in HOST_SLOTS:
        marker = f"<!-- host:{slot} -->"
        assert page.count(marker) == 1, f"the studio page has no {marker} slot"
        page = page.replace(marker, (FRAGMENTS / f"{slot}.html").read_text(encoding="utf-8").strip("\n"))
    assert page.count("<!-- host:head -->") == 1 and page.count("</body>") == 1
    page = page.replace("<!-- host:head -->", '<link rel="stylesheet" href="static/node.css">')
    tags = "".join(f'<script src="static/{name}"></script>\n' for name in HOST_SCRIPTS)
    return page.replace("</body>", tags + "</body>").encode("utf-8")


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
        # The project this hub was made for, by instance id. A folder can come to hold another project (deleted and
        # started again at the same path, from the Home or a terminal) while an old turn is still ending; what that
        # turn's hooks would write — a release, a closing note, a turn's record, a draft, a run's record — belongs to
        # the old project, so every write first asks whether the folder still holds it (`_attached`). The Home also
        # says so outright (`detach`) when it retires the page.
        self._instance = read_project_instance_id(store)
        self._detached = False
        self._coordinators: dict[str, Coordinator] = {}   # one per subtree root it was started on (ADR-0019 point 18)
        self._pursuit = None  # Pursue on a project with no map (ADR-0021 point 7): a Reader turn, then each Theorem's Coordinator
        self._discussion: AgentManager | None = None   # the map's agent (issue #177), made on first use; one turn at a time
        self._reader: AgentManager | None = None       # the Reader's (ADR-0021 point 5), for Pursue on a project with no map
        self._read_job: int | None = None              # the Reader's turn while one runs: what Stop stops
        self._read_stopped = False                     # Stop came while the Reader's turn was being prepared: it never starts
        self._discussion_live: dict | None = None      # {"job", "turn", "provider"} while a discussion turn runs (or is starting)
        self._discussion_pending: dict[str, dict] = {}  # ended turns whose record could not be written yet: kept, shown, written on the next read (audit)

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
                    # the host's names for the summary and the program (ADR-0013, ADR-0015), and its error codes
                    key_ideas_file=KEY_IDEAS_FILE, run_script=RUN_SCRIPT, refusal_codes=ERROR_CODES,
                    # the node's proof agent: rooted at the project, reading its library (ADR-0011 point 8),
                    # and knowing the node's dependencies as of each turn, to draft its key ideas (ADR-0013).
                    # A run's turn (spec #145) comes with its role and name from the run's own record; the
                    # researcher's own turn (an Ask) comes with none, whatever the run is doing meanwhile.
                    agent_context=lambda turn=None: ProofAgentContext(
                        node_id, root, library_folders(root), dependencies=self._dependencies(node_id),
                        name=(turn or {}).get("name") or "studio-agent",
                        on_drafted=lambda agent, data: self._record_draft(node_id, agent, data),
                        role=(turn or {}).get("role"),
                        # the Verifier's gate (ADR-0019 point 3): the run says whether this turn's Prover may request
                        # review; passed through only where this proof-agents has the field
                        **({"review_gate": (turn or {}).get("review_gate") or None} if _CONTEXT_HAS_GATE else {}),
                        # the project's instance id (ADR-0019 point 12): a role's memory writes are bound to this project
                        # and node by `proof memory add --project <id> --node-id <node>`, the one form the rule admits
                        **({"project_id": self._instance} if _CONTEXT_HAS_PROJECT else {}),
                        # a turn a Coordinator's Pursue started (ADR-0021 point 7): its Decomposer adds its Claims' edges
                        # and does not stop for the researcher
                        **({"pursue": bool((turn or {}).get("pursue"))} if _CONTEXT_HAS_PURSUE else {}),
                    ),
                    # the node's run (proof-agents, spec #145), on this studio's agent manager
                    run=lambda agent: AgentRun(agent, self._run_hooks(node_id)),
                    # the node's Medium as of each request, a run recorded as an Evidence check as the page's
                    # identity, and the project's optional open command (spec #145)
                    computation=ComputationHooks(
                        medium=lambda: self._medium(node_id),
                        run_inputs=lambda: self._run_inputs(node_id),
                        record_run=lambda run: self._record_run(node_id, run),
                        open_command=lambda: open_command(root),
                    ),
                )
                # the agent's compile tool builds through this node's studio (taken from upstream, 2938c05):
                # a LaTeX node's Typesetter compiles what the researcher sees; a computation node has no build
                self._studios[node.id].agent.compile_url = partial(self._compile_url, node_id)
            return self._studios[node.id]

    def _compile_url(self, node_id: str) -> str | None:
        """The studio the agent's compile tool builds through, as of the turn: a LaTeX node's own; a computation
        node has no build, so none."""
        return None if self._medium(node_id) == "computation" else self._studio_url(node_id)

    def _studio_url(self, node_id: str) -> str:
        from .server import project_origin  # the page's pinned origin (a late import: server.py imports this module)

        return f"{project_origin(self.store)}/studio/{quote(node_id, safe='')}/"

    # -- the project this hub was made for: nothing is written to another one in the same folder --------------------

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
        project): from here on its runs' hooks write nothing — a release, a closing note, a draft — so that closing
        the old page can't touch the new project's state (a node and a claimant of the same names, say)."""
        self._detached = True
        with self._lock:
            coordinators = list(self._coordinators.values())
        for coordinator in coordinators:  # a Coordinator at work on the old project ends; its runs' hooks write nothing now
            if coordinator.active():
                coordinator.release()

    def _still_this_project(self) -> None:
        """A write on behalf of this page's project: refused when the folder holds another (as a refusal, with its code)."""
        if not self._attached():
            raise proof_map.ProofMapError("PROJECT_REPLACED", "the project this page was opened for is no longer in its folder; open the project from the Home")

    def _assign(self, node_id: str, name: str) -> None:
        """A Start claims the node for the run — only while the folder still holds this project."""
        self._still_this_project()
        proof_map.claim_node(self.store, node_id, claimant_id=name)

    def _work_log(self, node_id: str) -> list[dict]:
        return proof_map.work_log(self.store, node_id) if self._attached() else []

    def _record_close(self, node_id: str, role: str, name: str, status: str, note: str) -> None:
        """The run's closing progress note — unless the project it ran on is gone from the folder."""
        if not self._attached():
            return
        proof_map.record_progress(self.store, node_id, role=role, by=name, step=self._last_step(node_id), status=status, note=note)

    def _record_question(self, node_id: str, role: str, name: str, text: str) -> None:
        """A Standing question the run's role recorded (ADR-0021 point 8) — unless the project is gone from the folder."""
        if not self._attached():
            return
        proof_map.record_progress(self.store, node_id, role=role, by=name, question=text)

    def _record_turn(self, node_id: str, turn: dict) -> None:
        """A turn's record (started, ended, its conversation) — unless the project it ran on is gone from the folder."""
        if not self._attached():
            return
        proof_map.record_agent_turn(self.store, node_id, **turn)

    def _record_draft(self, node_id: str, agent: str, data: bytes) -> None:
        """A drafting turn's last word (ADR-0013), which arrives after the turn — unless the project it drafted for is
        gone from the folder: then the summary there is the new project's author's, not this agent's draft."""
        if not self._attached():
            return
        proof_map.record_key_ideas_draft(self.store, node_id, agent=agent, content=data)

    def _run_hooks(self, node_id: str) -> RunHooks:
        """What a node's run asks of the project (spec #145), and what ADR-0019's prove–verify loop adds: the working
        inputs' digest, the node's brief, the shared notes and the Verifier's Evidence check. The four are passed only
        where this proof-agents has the fields, so an older run takes the hooks it knows."""
        root = self.store.root
        wanted = {
            "agent_name": lambda provider: agent_name(root, provider),
            "budget": lambda: budget(root),
            "assign": lambda name: self._assign(node_id, name),
            "release": lambda name, reason: self._release(node_id, name, reason),
            "work_log": lambda: self._work_log(node_id),
            "record_close": lambda role, name, status, note: self._record_close(node_id, role, name, status, note),
            "record_turn": lambda turn: self._record_turn(node_id, turn),
            "transcript": lambda turn: proof_map.agent_turn_transcript(self.store, node_id, turn),
            "review_now": lambda: self._review_now(node_id),
            # ADR-0019 (phase 1): the verdict's hash to compare with, the briefing's sources, the gate's Evidence check
            "inputs_digest": lambda: self._inputs_digest(node_id),
            "node_brief": lambda: self._node_brief(node_id),
            "working_inputs": lambda: self._working_inputs(node_id),  # phase 4: the files' text, for the researcher's diff (point 21)
            "check_inputs": lambda: node_check.check_node(self.store, node_id) if self._attached() else [],  # the mechanical checks (issue #180)
            "shared_notes": lambda: self._shared_notes(node_id),
            # ADR-0021 point 8: a choice the role made, recorded as a Standing question on the node
            "record_question": lambda role, name, text: self._record_question(node_id, role, name, text),
            "record_evidence": lambda candidate_proof_id, outcome, *, run_by, notes, inputs_sha256: self._record_evidence(
                node_id, candidate_proof_id, outcome, run_by=run_by, notes=notes, inputs_sha256=inputs_sha256),
        }
        known = {f.name for f in fields(RunHooks)}
        return RunHooks(**{name: hook for name, hook in wanted.items() if name in known})

    # -- what the prove–verify loop reads and records (ADR-0019, phase 1) ---------------------------------------------

    def _inputs_digest(self, node_id: str) -> str | None:
        """The digest of the node folder as it stands — the SHA-256 a Review snapshot of it would be known by, every file
        the Verifier read, a computation's `out/` included (ADR-0019 point 2; audit P1-2): what a verdict's `inputs_sha256`
        is compared with to tell a current verdict from a stale one. None when the folder can't be read or holds a link
        where a snapshot would read: then no verdict is current."""
        try:
            return read_working_snapshot(self.store.root, node_id, self._medium_of(node_id)).digest()
        except (OSError, NodeFolderLinks):
            return None

    def _medium_of(self, node_id: str) -> Medium | None:
        node = proof_map.get_node(self.store, node_id)
        return node.medium if node is not None else None

    def _working_inputs(self, node_id: str) -> dict:
        """One read of the working inputs — exactly the files `_inputs_digest` hashes, read once: their digest, as it gives
        it, and each file by its path as UTF-8 text, or as its bytes where it is not text (the diff then names it as
        changed and no more) — for the run to diff a turn's end against the next turn's start: the researcher's edit, read
        to them (ADR-0019 point 21; audit P2-3, P2-4). An unreadable folder, or one with a link where a snapshot would
        read, raises, and the run says the inputs changed without the diff."""
        contents = read_working_snapshot(self.store.root, node_id, self._medium_of(node_id))
        files: dict[str, str | bytes] = {}
        for rel, data in contents.files.items():
            try:
                files[rel] = data.decode("utf-8")
            except UnicodeDecodeError:
                files[rel] = data
        return {"digest": contents.digest(), "files": files}

    def _node_brief(self, node_id: str) -> dict:
        """The node, its kind, its statement and its dependencies' statements, each saying whether it is Accepted and, when
        it is, carrying its key ideas (ADR-0019 point 9): what every turn's briefing opens with, how the run tells this
        node's memory from another's (audit P2), and what tells it whether a Decomposer may be started here (point 20: a
        Theorem or Lemma not yet split). An unaccepted dependency's key ideas are not a fact the run may build on, so
        they are not passed."""
        node = proof_map.require_node(self.store, node_id)
        dependencies = []
        for dep_id in node.dependencies:
            dep = proof_map.get_node(self.store, dep_id)
            if dep is None:
                continue
            accepted = self._settled(dep)
            dependencies.append({"id": dep.id, "kind": dep.kind.value, "statement": dep.statement, "accepted": accepted,
                                 # rested on for its statement, never its proof (ADR-0021 point 3)
                                 "provisional": proof_map.is_provisional(self.store, dep_id),
                                 "key_ideas": self._key_ideas_text(dep_id) if accepted and dep.kind != ProofMapNodeKind.imported_result else None,
                                 "split_child": dep.derived_from == node.id})  # a child a split made, as against a premise (point 20)
        return {"node_id": node.id, "kind": node.kind.value, "statement": node.statement, "dependencies": dependencies,
                "definitions": node_definitions(self.store, node)}  # what the statement is written in, read before it (ADR-0020)

    def _settled(self, node) -> bool:
        """Whether a node is what a dependent may rest on for trust: Accepted, or for an imported result Reference-reviewed
        or trusted by a rule (ADR-0014)."""
        if node.kind == ProofMapNodeKind.imported_result:
            return proof_map.get_reference_review_state(self.store, node.id) in ("reviewed", "trusted-by-rule")
        return proof_map.get_acceptance_state(self.store, node.id) == "accepted"

    def _key_ideas_text(self, node_id: str) -> str | None:
        """The node's current key-ideas.md as text, or None when it has none."""
        try:
            return (node_folder(self.store.root, node_id) / key_ideas.KEY_IDEAS_FILE).read_text(encoding="utf-8")
        except OSError:
            return None

    def _shared_notes(self, node_id: str) -> list[dict]:
        """Part C's shared entries for the node's briefing, in the subscription order (ADR-0019 point 14), each bounded:
        what was learned on this node itself, as memory's typed entries say it (point 8: the dead ends, `failed`; the
        techniques that worked, `tactic`; the observations not yet trusted, `tentative`), newest first; then the same
        from each dependency and dependent, and where that node stands (point 13: its claim, its step, its last verdict —
        project state already); then from each sibling, the other children beside it under the same parents; then
        memory elsewhere in the map retrieved by this node's statement. Every entry names its node and its relation;
        the briefing marks each unverified. Nothing is pushed to a running turn: this is read when a turn begins."""
        node = proof_map.require_node(self.store, node_id)
        dependents = proof_map.dependents(self.store, node_id)
        neighbours = [(proof_map.get_node(self.store, dep_id), "dependency") for dep_id in node.dependencies]
        neighbours += [(dependent, "dependent") for dependent in dependents]
        neighbours += [(sibling, "sibling") for sibling in proof_map.siblings(self.store, node_id)]
        notes = self._learned(node_id, None, OWN_NOTES)
        covered = {node_id}
        for other, relation in neighbours:
            if other is None or other.id in covered:
                continue
            covered.add(other.id)
            notes += self._learned(other.id, relation, NEIGHBOUR_NOTES)
            standing = self._standing(other.id)
            if standing:
                notes.append({"node_id": other.id, "relation": relation, "status": "progress", "text": standing, "by": None})
        for hit in retrieve_memory(self.store, node.statement, limit=RETRIEVED_NOTES, statuses=LEARNED, exclude_node_ids=sorted(covered)):
            notes.append({"node_id": hit.node_id, "relation": "retrieved", "status": hit.status, "text": hit.content, "by": hit.source})
        return notes

    def _learned(self, node_id: str, relation: str | None, limit: int) -> list[dict]:
        """A node's learned memory entries (failed, tactic, tentative), newest first, at most `limit`."""
        entries = [entry for entry in node_scope_memory(self.store, node_id) if entry.status.value in LEARNED]
        return [{"node_id": entry.scope.node_id or node_id, **({"relation": relation} if relation else {}), "status": entry.status.value,
                 "text": entry.content, "by": entry.source} for entry in reversed(entries)][:limit]

    def _standing(self, node_id: str) -> str | None:
        """Where a neighbouring node stands, from project state already there (ADR-0019 point 13): who holds it, the
        step it is on of its plan, and its newest verdict. None when nothing has happened on it."""
        claim = get_active_claim(self.store, node_id)
        log = proof_map.work_log(self.store, node_id)
        plans = [e for e in log if e.get("kind") == "plan"]
        steps = [e for e in log if e.get("kind") == "step"]
        verdict = proof_map.latest_verdict(self.store, node_id)
        if claim is None and not steps and verdict is None:
            return None
        parts = [f"claimed by {claim.claimant_id}" if claim is not None else "unclaimed"]
        if steps:
            step, plan = steps[-1], list(plans[-1].get("plan") or []) if plans else []
            number = step.get("step")
            what = f": {plan[number - 1]}" if isinstance(number, int) and 0 < number <= len(plan) else ""
            parts.append(f"on step {number}{f' of {len(plan)}' if plan else ''}{what} ({step.get('status')})")
        if verdict is not None:
            note = str(verdict.get("note") or "").strip()
            parts.append(f"the last verdict {verdict.get('outcome')}" + (f": {note[:160]}" if note and verdict.get("outcome") == "failed" else ""))
        return "; ".join(parts)

    def _record_evidence(self, node_id: str, candidate_proof_id: str, outcome: str, *, run_by: str, notes: str, inputs_sha256: str | None) -> bool | str:
        """The run records a passing verdict as an Evidence check on the snapshot it gated (ADR-0019 point 4) — only when
        the verdict's inputs digest is the snapshot's own frozen inputs digest, so the check is of the proof the
        researcher is asked to read and nothing else. A mismatch, an unreadable snapshot or a project gone from the
        folder record nothing, and the run's work log says why. Advisory, as every Evidence check is (ADR-0004)."""
        if not self._attached():
            return "the project this page was opened for is no longer in its folder"
        if not inputs_sha256:
            return "the verdict carries no digest (the folder could not be read when it was made)"
        proof = next((p for p in proof_map.list_candidate_proofs(self.store, node_id) if p.id == candidate_proof_id), None)
        if proof is None:
            return f"no Candidate proof {candidate_proof_id} on {node_id}"
        snapshot = self.store.root / proof.file_path
        frozen = frozen_digests(snapshot.parent) if snapshot.name == SNAPSHOT_MANIFEST else None
        if frozen is None:
            return f"snapshot v{proof.version} can't be read"
        snapshot_sha256, _ = frozen
        if snapshot_sha256 != inputs_sha256:  # the snapshot is not of the files the Verifier passed (an edit since; audit P1-1)
            return f"snapshot v{proof.version} ({snapshot_sha256[:12]}…) is not of the files the Verifier passed ({inputs_sha256[:12]}…)"
        try:
            proof_map.record_evidence_check(self.store, proof.id, outcome, notes=notes, run_by=run_by, snapshot_sha256=snapshot_sha256)
        except proof_map.ProofMapError as exc:  # the snapshot changed between the comparison and the record
            return f"snapshot v{proof.version} changed while the check was recorded: {exc.message}"
        return True

    def _release(self, node_id: str, name: str, reason: str) -> None:
        """Release the node when the run still holds it (a review request already released it), saying why."""
        if not self._attached():  # the folder holds another project now (or none): not this run's node to release
            return
        claim = proof_map.get_active_claim(self.store, node_id)
        if claim is not None and claim.claimant_id == name:
            proof_map.release_node(self.store, node_id, claimant_id=name, reason=reason)

    def _review_now(self, node_id: str) -> dict:
        """Review what the agent has (spec #145): freeze a snapshot of the folder as it stands. The researcher asks
        for it, so it is recorded as the researcher — the page's git identity, as every page-initiated human action
        is — whoever holds the node: the holder's claim (the run's, or another person's) ends in the same request,
        an unassignment by the researcher, so the run ends as any review request ends it."""
        self._still_this_project()
        record = proof_map.request_review(self.store, node_id, requested_by=git_identity(self.store.root),
                                          rationale="the researcher reviews what the agent has, as it stands", unassign=True)
        return record.model_dump(mode="json")

    def _last_step(self, node_id: str) -> int:
        steps = [e["step"] for e in proof_map.work_log(self.store, node_id) if e.get("kind") == "step"]
        return steps[-1] if steps else 1

    def run_action(self, node_id: str, action: str, body: dict) -> tuple[int, dict]:
        """The researcher's oversight of a node's run through the map's own API (spec #145): (status, the studio's answer)."""
        try:
            studio = self.studio(node_id)
        except NoStudio as exc:
            code, message = exc.args
            return int(HTTPStatus.GONE if code == "PROJECT_REPLACED" else HTTPStatus.NOT_FOUND), {"error": message, "code": code}
        return studio.run_action(action, body or {})

    # -- the Coordinator over a Theorem's or Lemma's subtree (ADR-0019 points 18 and 19, phase 3) --------------------

    def coordinator(self, root_id: str) -> Coordinator:
        """The Coordinator of a node's subtree, made on first use. The node is a local one that rests on something: a
        Theorem or Lemma with children, usually. It starts node runs through the studios, made on demand — no page
        needs to be open on any node of the subtree."""
        if not self._attached():
            raise NoStudio("PROJECT_REPLACED", "the project this page was opened for is no longer in its folder; open the project from the Home")
        node = proof_map.get_node(self.store, root_id)
        if node is None:
            raise NoStudio("NODE_NOT_FOUND", f"proof map node {root_id} not found")
        if node.kind == ProofMapNodeKind.imported_result:
            raise NoStudio("NO_SUBTREE", f"{root_id} is an imported result: it has no subtree to work")
        if not node.dependencies and node.kind not in (ProofMapNodeKind.theorem, ProofMapNodeKind.lemma):
            # a Theorem or Lemma with no Claims yet is pursued from a Decomposer turn (ADR-0021 point 7)
            raise NoStudio("NO_SUBTREE", f"{root_id} rests on nothing: there is no subtree to coordinate")
        with self._lock:
            if self._closed:
                raise NoStudio("STUDIO_CLOSED", "the proof map's server is shutting down")
            if root_id not in self._coordinators:
                root = self.store.root
                self._coordinators[root_id] = Coordinator(CoordinatorHooks(
                    subtree=lambda: self._subtree(root_id),
                    run=lambda node_id: self._run_of(node_id),
                    budget=lambda: budget(root),
                    parallel=lambda: parallel(root),
                    agent_name=lambda provider: agent_name(root, provider),
                    record=lambda note: self._record_coordinator(root_id, note),
                    **({"park": lambda node_id, reason: self._park(root_id, node_id, reason)} if _COORDINATOR_PARKS else {}),
                ), root_id)
            return self._coordinators[root_id]

    # -- Pursue on a project (ADR-0021 point 7): the Reader states the draft, then each Theorem is pursued -------------

    @staticmethod
    def project_pursuit_available() -> bool:
        """Whether this proof-agents has a project pursuit (a Reader and ProjectPursuit): the Home asks it too."""
        return ProjectPursuit is not None

    def can_pursue(self) -> bool:
        """Whether Pursue starts from the draft: a library to read, no map yet, and no pursuit still at work."""
        return (self.project_pursuit_available() and bool(library_folders(self.store.root)) and not proof_map.list_nodes(self.store)
                and not self._pursuit_busy())

    def pursuit(self):
        """The project's pursuit, made on first use."""
        if ProjectPursuit is None:
            raise NoStudio("NO_SUBTREE", "this proof-agents has no project pursuit; pursue a Theorem from its page")
        if not self._attached():
            raise NoStudio("PROJECT_REPLACED", "the project this page was opened for is no longer in its folder; open the project from the Home")
        with self._lock:
            if self._closed:
                raise NoStudio("STUDIO_CLOSED", "the proof map's server is shutting down")
            if self._pursuit is None:
                self._pursuit = ProjectPursuit(PursuitHooks(
                    read=lambda provider: self._read_turn(provider),
                    theorems=lambda: [n.id for n in proof_map.list_nodes(self.store) if n.kind == ProofMapNodeKind.theorem] if self._attached() else [],
                    coordinator=lambda theorem: self.coordinator(theorem),
                    record=lambda note: None,
                    **({"stop_read": self._stop_read} if _PURSUIT_STOPS_READ else {}),
                ))
            return self._pursuit

    def _reader_agent(self) -> AgentManager:
        """The Reader's agent manager: one for the project, rooted at it, made on first use, closed with the hub."""
        with self._lock:
            if self._closed:
                raise NoStudio("STUDIO_CLOSED", "the proof map's server is shutting down")
            if self._reader is None:
                root = self.store.root
                self._reader = AgentManager(lambda: root, lambda: [], None, context_fn=lambda turn=None: ReaderContext(
                    root, library_folders(root), project_id=self._instance))
            return self._reader

    def _read_turn(self, provider: str) -> dict:
        """One Reader turn on the whole library, run to its end (ADR-0021 point 5): {} once it ended, or the refusal."""
        agent = self._reader_agent()
        try:
            started = agent.start("Read the draft in the library and state it as the proof map, as your brief says.",
                                  None, "edit", None, None, None, provider or None,
                                  unless=lambda: self._read_stopped, begin=self._reading)
            if "error" in started:
                return {"error": str(started["error"]), "code": str(started.get("code") or "AGENT_REFUSED")}
            job = agent.jobs[started["job"]]
            if self._read_job is None:  # a manager that did not call `begin`
                self._reading(job)
            with job.cond:
                while not job.done:
                    job.cond.wait(1.0)
        finally:
            with self._lock:
                self._read_job = None
        done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
        if done.get("is_error") or done.get("exit") not in (None, 0):
            return {"error": str(done.get("stderr") or done.get("subtype") or "the Reader's turn failed").strip(), "code": "READER_FAILED"}
        return {}

    def _reading(self, job) -> None:
        """The Reader's turn exists: Stop now stops it; a Stop that came first stops it at once."""
        with self._lock:
            self._read_job = job.id
            stopped, reader = self._read_stopped, self._reader
        if stopped and reader is not None:
            reader.stop(job.id)

    def _stop_read(self) -> None:
        """Stop the Reader's turn, running or about to start (ADR-0021 point 7's Stop, while the pursuit reads)."""
        with self._lock:
            self._read_stopped = True
            job, reader = self._read_job, self._reader
        if job is not None and reader is not None:
            reader.stop(job)

    def _pursuit_busy(self) -> bool:
        """Whether the project's pursuit is still at work: pursuing, giving its runs back (`stopping`), holding them after
        a release that failed (`release-failed`, proof-agents#17: only its Stop goes on), or stopped but its thread or its
        Reader's turn not yet ended. A second Pursue then waits, though the map may still be empty."""
        pursuit = self._pursuit
        if pursuit is None:
            return False
        if pursuit.view()["status"] in (*_PURSUIT_AT_WORK, *_PURSUIT_HOLDING) or self._read_job is not None:
            return True
        if hasattr(pursuit, "active"):  # contract C4: its thread alive, a Stop's Reader or Coordinator not yet ended
            return pursuit.active()
        thread = getattr(pursuit, "_thread", None)  # an older proof-agents
        return thread is not None and thread.is_alive()

    def pursuit_action(self, action: str, body: dict) -> tuple[int, dict]:
        """Pursue on the project (start) and Stop."""
        try:
            pursuit = self.pursuit()
        except NoStudio as exc:
            code, message = exc.args
            return int(HTTPStatus.GONE if code == "PROJECT_REPLACED" else HTTPStatus.CONFLICT), {"error": message, "code": code}
        if action == "start":
            if self._pursuit_busy():
                return int(HTTPStatus.CONFLICT), {"error": "this project is still being pursued, or its Stop has not ended the "
                                                  "Reader's turn yet; wait for it", "code": "PURSUIT_ACTIVE"}
            provider = str(body.get("provider") or "").strip()
            if not provider:
                backend = self._reader_agent().backend(None)
                provider = backend.id if backend is not None else ""
            with self._lock:
                self._read_stopped = False  # a new pursuit's Reader: the last Stop is over
            answer = pursuit.start(provider)
        elif action == "stop":
            reading = pursuit.view()["status"] == "reading"
            answer = pursuit.stop()
            if reading and not _PURSUIT_STOPS_READ:  # an older pursuit does not stop its Reader: the host does
                self._stop_read()
            if answer.get("code") == "NO_PURSUIT":  # it had ended already: nothing to stop, its ending stands
                return int(HTTPStatus.OK), self.pursuit_view()
        else:
            return int(HTTPStatus.NOT_FOUND), {"error": f"no pursue action {action!r}", "code": "NOT_FOUND"}
        return (int(HTTPStatus.CONFLICT) if "error" in answer else int(HTTPStatus.OK)), answer

    def pursuit_view(self) -> dict:
        view = self._pursuit.view() if self._pursuit is not None else {"status": "idle", "reason": "", "theorems": [], "current": None, "results": {}}
        # stopped, but its Reader's turn (or its thread) not ended yet, or its runs being given back: no Pursue until it
        # has. A release that failed is not stopping: it holds its runs until the researcher's Stop gives them back
        stopping = view["status"] == "stopping" or (view["status"] not in (*_PURSUIT_AT_WORK, "release-failed") and self._pursuit_busy())
        return {**view, "can_pursue": self.can_pursue(), "stopping": stopping}

    def parked(self, node_id: str) -> str | None:
        """Why a node is parked: as a Coordinator at work here parked it, else as its work log last said."""
        return parked_reason(self.store, node_id)

    def _run_of(self, node_id: str):
        """A node's run, its studio made if none is open: how the Coordinator starts a run without a page on the node."""
        run = self.studio(node_id).run
        if run is None:
            raise NoStudio("NO_RUN", f"{node_id} has no run")
        return run

    def _subtree(self, root_id: str) -> list[dict]:
        """The root and every node it rests on, transitively, as the Coordinator reads them: Accepted or not (an imported
        result: Reference-reviewed or trusted by rule), the workflow axis (`open` is the frontier rule: unclaimed, every
        dependency settled), who holds it, its key ideas once Accepted (for the redirect of point 19), and whether a run
        can work it (a local node with a proof folder)."""
        if not self._attached():  # the folder holds another project now, or none: nothing to read, and nothing recreated (audit P5)
            return []
        out: list[dict] = []
        seen: set[str] = set()
        queue = [root_id]
        while queue:
            node_id = queue.pop(0)
            if node_id in seen:
                continue
            seen.add(node_id)
            node = proof_map.get_node(self.store, node_id)
            if node is None:
                continue
            imported = node.kind == ProofMapNodeKind.imported_result
            accepted = self._settled(node)
            claim = get_active_claim(self.store, node_id)
            out.append({"id": node.id, "kind": node.kind.value, "statement": node.statement, "dependencies": list(node.dependencies),
                        "accepted": accepted, "workflow": proof_map.get_workflow_state(self.store, node_id),
                        "claimed_by": claim.claimant_id if claim is not None else None,
                        "key_ideas": self._key_ideas_text(node_id) if accepted and not imported else None,
                        "has_run": not imported and node_folder(self.store.root, node_id).is_dir(),
                        # ADR-0021: rested on for work; a snapshot awaiting the researcher even where the axis reads
                        # Blocked; and the Claims its Split made
                        "provisional": proof_map.is_provisional(self.store, node_id),
                        "awaiting_review": awaiting_review(self.store, node),
                        "split_children": self._split_children(node)})
            queue.extend(node.dependencies)
        return out

    def _split_children(self, node) -> list[str]:
        """The Claims a Split of `node` made that it still rests on."""
        children = []
        for dep_id in node.dependencies:
            dep = proof_map.get_node(self.store, dep_id)
            if dep is not None and dep.derived_from == node.id:
                children.append(dep_id)
        return children

    def _park(self, root_id: str, node_id: str, reason: str) -> None:
        """A node the Coordinator of `root_id` parked (ADR-0021 point 9), on the node's own work log: the map marks it and
        the review queue lists it, with its attempts, until work on it begins again."""
        if not self._attached():
            return
        coordinator = self._coordinators.get(root_id)
        name = (coordinator.state.name if coordinator is not None else "") or "coordinator"
        proof_map.record_progress(self.store, node_id, role=None, by=f"{name}/coordinator", coordinator=f"{PARKED_NOTE}{reason}")

    def _record_coordinator(self, root_id: str, note: str) -> None:
        """What the Coordinator did, on the root's work log — unless the project is gone from the folder."""
        if not self._attached():
            return
        coordinator = self._coordinators.get(root_id)
        name = (coordinator.state.name if coordinator is not None else "") or "coordinator"
        proof_map.record_progress(self.store, root_id, role=None, by=f"{name}/coordinator", coordinator=note)

    def coordinator_action(self, root_id: str, action: str, body: dict) -> tuple[int, dict]:
        """The researcher's actions on a subtree's Coordinator (ADR-0019 point 18): Start, Pause, Resume, Stop and release."""
        try:
            coordinator = self.coordinator(root_id)
        except NoStudio as exc:
            code, message = exc.args
            return int(HTTPStatus.GONE if code == "PROJECT_REPLACED" else HTTPStatus.NOT_FOUND), {"error": message, "code": code}
        if action == "start":
            provider = str(body.get("provider") or "").strip()
            if not provider:
                backend = self.studio(root_id).agent.backend(None)
                provider = backend.id if backend is not None else ""
            answer = coordinator.start(provider)
        elif action == "pause":
            answer = coordinator.pause()
        elif action == "resume":
            answer = coordinator.resume()
        elif action == "release":
            answer = coordinator.release()
        else:
            return int(HTTPStatus.NOT_FOUND), {"error": f"no coordinator action {action!r}", "code": "NOT_FOUND"}
        return (int(HTTPStatus.CONFLICT) if "error" in answer else int(HTTPStatus.OK)), answer

    def coordinator_view(self, root_id: str) -> dict:
        """The Coordinator as the root's page reads it: its state, and the subtree's counts and the parallelism it works at."""
        view = self.coordinator(root_id).view()
        nodes = self._subtree(root_id)
        view["subtree"] = {"nodes": len(nodes), "accepted": sum(1 for n in nodes if n["accepted"]),
                           "open": sum(1 for n in nodes if n["has_run"] and not n["accepted"])}
        view["parallel"] = parallel(self.store.root)
        return view

    def coordinator_state(self, node_id: str) -> dict | None:
        """The node's Coordinator as the map shows it: while it is active; None otherwise."""
        coordinator = self._coordinators.get(node_id)
        if coordinator is None or not coordinator.active():
            return None
        view = coordinator.view()
        return {"status": view["status"], "running": view["running"], "turns": view["turns"], "turns_max": view["turns_max"]}

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

    def _run_inputs(self, node_id: str) -> RunInputs:
        """The state of the program's inputs (`vault.frozen_role` is `input`: its scripts, data and hidden environment
        files, never `out/`): their inputs digest, as `frozen_inputs_digest` hashes a snapshot's, and a stamp of each
        (size, mtime, ctime, inode). An input edited during a run and put back before it ends has its content as
        before but not its stamp (audit R-S1); its ctime no program can set back. The digest is
        `vault.inputs_digest` over exactly the files `working_inputs_digest` reads, without refusing a link under
        `out/`: only a symbolic link among the inputs, or an unreadable input, is no state to compare, and says why."""
        folder = node_folder(self.store.root, node_id)
        try:
            links = sorted(path.relative_to(folder).as_posix() for path, _ in working_links(self.store.root, node_id, Medium.computation)
                           if frozen_role(path.relative_to(folder).as_posix()) == "input")
            if links:  # a link among the outputs is an output, and outputs may differ (Q41)
                return RunInputs("", {}, f"{', '.join(links)}: a symbolic link among the program's inputs, which a Run's inputs are "
                                         "never compared through")
            paths = {rel: path for rel, path in working_inputs(self.store.root, node_id, Medium.computation).items()
                     if frozen_role(rel) == "input"}
            stamps = {rel: f"{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}:{st.st_ino}" for rel, path in paths.items() for st in [path.stat()]}
            digest = inputs_digest({rel: hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in paths.items()},
                                   [rel for rel, path in paths.items() if is_executable(path)])
        except OSError as exc:
            where = Path(exc.filename).relative_to(folder).as_posix() if exc.filename and Path(exc.filename).is_relative_to(folder) else str(folder)
            return RunInputs("", {}, f"{where} can't be read ({exc.strerror or exc}), so the program's inputs can't be compared")
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
        if not self._attached():
            return {"evidence": None, "note": "the project this studio was opened for is no longer in its folder — not recorded"}
        proof = get_current_candidate_proof(self.store, node_id)
        if run.stopped is not None:
            return {"evidence": None, "note": f"{run.stopped} — not recorded as an Evidence check: only a run that completes is one"}
        if proof is None:
            return {"evidence": None, "note": "no snapshot yet — not recorded: request review, and runs of what it froze are recorded as Evidence checks on it"}
        version = f"snapshot v{proof.version}"
        if run.before is None or run.after is None:
            return {"evidence": None, "note": f"an input could not be read — not recorded against {version}"}
        unreadable = run.before.unreadable or run.after.unreadable
        if unreadable:
            return {"evidence": None, "note": f"the run was not recorded as an Evidence check on {version}: {unreadable}"}
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

    # -- the map-level discussion (issue #177): the researcher and the map's agent on the proof plan --------------------

    def _discussion_name(self) -> str:
        """The name the map's agent speaks and adds fog under: `[studio] agent_name`, else "map-agent"."""
        name = studio_settings(self.store.root).get("agent_name")
        return name.strip() if isinstance(name, str) and name.strip() else MAP_AGENT_NAME

    def _discussion_agent(self) -> AgentManager:
        """The map's agent manager: one for the project, rooted at the project, with no file to diff (a discussion turn
        writes none) and the map agent's context for every turn. Made on first use, closed with the hub."""
        with self._lock:
            if self._closed:
                raise NoStudio("STUDIO_CLOSED", "the proof map's server is shutting down")
            if self._discussion is None:
                root = self.store.root
                self._discussion = AgentManager(lambda: root, lambda: [], None, context_fn=lambda turn=None: self._discussion_context())
            return self._discussion

    def _discussion_context(self) -> MapAgentContext:
        """The map agent's context for one turn: the project, its library folders (proof.toml), the agent's name, the project's id."""
        root = self.store.root
        return MapAgentContext(root, library_folders(root), name=self._discussion_name(), project_id=self._instance)

    @staticmethod
    def _discussion_abandon(agent: AgentManager) -> None:
        """A job the manager registered but never ran — its context failed to build inside `start` — is marked done, so the
        manager is not busy forever (audit: a configuration error once left every later message a 409)."""
        job = agent.active
        if job is None or job.done or job.proc is not None or any(e.get("t") == "done" for e in job.events):
            return
        job.emit({"t": "done", "turn": job.id, "provider": job.provider, "changed": [], "exit": None, "is_error": True, "stderr": "the turn never started"})
        with job.cond:
            job.done = True
            job.cond.notify_all()

    def discussion_view(self) -> dict:
        """The discussion as the drawer reads it: its turns (oldest first, each reply whole — read back from the transcript
        when the record kept only its head), the turn running now, the providers and the agent's name. An ended turn whose
        record could not be written is written now if it can be, else shown from memory and marked (`record_error`)."""
        self._discussion_flush()
        turns = proof_map.discussion_turns(self.store) if self._attached() else []
        for turn in turns:
            if turn.get("ended") and len(turn.get("reply") or "") >= proof_map.DISCUSSION_REPLY_KEPT and turn.get("transcript"):
                kept = proof_map.discussion_transcript(self.store, turn["turn"]) or {}
                texts = [str(e.get("text") or "") for e in kept.get("events") or [] if e.get("t") == "text" and e.get("text")]
                if texts:
                    turn["reply"] = "\n\n".join(texts)
        with self._lock:
            live = dict(self._discussion_live) if self._discussion_live else None
            pending = {turn_id: dict(record) for turn_id, record in self._discussion_pending.items()}
        for turn in turns:  # a turn ended in memory but not yet on record: shown ended, with its reply, and said to be unrecorded
            record = pending.get(turn["turn"])
            if record is not None and not turn.get("ended"):
                turn.update(ended=True, reply=record["reply"], session_id=record["session_id"], is_error=record["is_error"], record_error=record["error"])
        try:
            info = self._discussion_agent().info()
        except NoStudio:
            info = {}
        return {"turns": turns, "running": live, "providers": info.get("providers") or [], "default": info.get("default"), "name": self._discussion_name(),
                "unrecorded": sorted(pending)}

    def _discussion_flush(self) -> None:
        """Write the ended records that could not be written when their turn ended (a transcript or database error): each
        is tried again, kept while it still fails, dropped once it is on record."""
        with self._lock:
            pending = list(self._discussion_pending.items())
        if not pending or not self._attached():
            return
        for turn_id, record in pending:
            try:
                proof_map.record_discussion_turn(self.store, phase="ended", turn=turn_id, **{k: v for k, v in record.items() if k != "error"})
            except Exception as exc:  # noqa: BLE001 — still not writable: kept, and the view says so
                with self._lock:
                    if turn_id in self._discussion_pending:
                        self._discussion_pending[turn_id]["error"] = f"{type(exc).__name__}: {exc}"
                continue
            with self._lock:
                self._discussion_pending.pop(turn_id, None)

    def _discussion_session(self, provider: str) -> str | None:
        """The backend session the next message continues: the newest turn on this provider, when it ended and left one — on
        record, or still waiting to be written (`_discussion_pending`: the session is known either way). A turn that is
        still running is the busy case; one that failed left none, so the next message starts afresh."""
        with self._lock:
            pending = {turn_id: record.get("session_id") for turn_id, record in self._discussion_pending.items()}
        for turn in reversed(proof_map.discussion_turns(self.store)):
            if (turn.get("provider") or "") == provider:
                if turn.get("ended"):
                    return turn.get("session_id")
                return pending.get(turn["turn"])  # ended in memory: its session; still running: none
        return None

    def discussion_start(self, body: dict) -> tuple[int, dict]:
        """One message to the map's agent: recorded as a started turn, then the backend's turn — in the project root,
        continuing the provider's last session unless `fresh`. (status, answer): the job and turn, or the refusal."""
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return 400, {"error": "say what to discuss", "code": "PROMPT_EMPTY"}
        if not self._attached():
            return 410, {"error": "the project this page was opened for is no longer in its folder; open the project from the Home", "code": "PROJECT_REPLACED"}
        try:
            agent = self._discussion_agent()
        except NoStudio as exc:
            return 409, {"error": exc.args[1], "code": exc.args[0]}
        backend = agent.backend(str(body.get("provider") or "") or None)
        provider = str(body.get("provider") or (backend.id if backend is not None else "") or "")
        fresh = bool(body.get("fresh"))
        self._discussion_flush()  # before the session is chosen: an ended turn not yet on record may be the one to continue
        session = None if fresh else self._discussion_session(provider)
        turn, name = uuid.uuid4().hex[:16], self._discussion_name()
        with self._lock:
            if self._discussion_live is not None:
                return 409, {"error": "the map's agent is still answering the previous message; wait, or stop it", "code": "AGENT_BUSY"}
            self._discussion_live = {"job": None, "turn": turn, "provider": provider}  # reserved while the turn starts
        try:
            self._discussion_context()  # built once here first: a configuration error (a library path, say) is the answer, not a registered job
            proof_map.record_discussion_turn(self.store, phase="started", turn=turn, by=name, provider=provider, prompt=prompt, fresh=fresh)
            # "edit" is the manager's mode in which Claude Code runs with its default permissions and an allowlist (plan mode would
            # refuse the `proof` reads); the context itself allows no file write (MapAgentContext), and gives the manager no file to diff
            started = agent.start(prompt, session, "edit", body.get("model") or None, body.get("effort") or None, None, provider or None)
            if "error" in started:
                with self._lock:
                    self._discussion_live = None
                self._discussion_record_ended(turn, by=name, provider=provider, prompt=prompt, job=None, session_id=None, events=None,
                                              reply=str(started["error"]), is_error=True)
                status = 409 if started.get("code") in ("AGENT_BUSY", "STUDIO_CLOSED", "TURN_CALLED_OFF") else 400
                return status, {"error": str(started["error"]), "code": str(started.get("code") or "AGENT_REFUSED")}
            job = agent.jobs[started["job"]]
        except Exception as exc:  # noqa: BLE001 — the context, the record or the start failed: the slot is free again, the manager too, and the error is the answer (audit)
            with self._lock:
                self._discussion_live = None
            self._discussion_abandon(agent)
            return 500, {"error": f"the message could not be sent: {type(exc).__name__}: {exc}", "code": "INTERNAL_ERROR"}
        provider = str(started.get("provider") or provider)
        with self._lock:
            self._discussion_live = {"job": job.id, "turn": turn, "provider": provider}
        threading.Thread(target=self._discussion_finish, args=(job, turn, name, provider, prompt), name="map-discussion", daemon=True).start()
        return 200, {"job": job.id, "turn": turn, "provider": provider}

    def _discussion_record_ended(self, turn: str, **record) -> None:
        """The ended record, or — when it cannot be written now — the record kept in memory to be written on the next read
        and shown meanwhile (audit: a failure here was silent, and a refresh lost the reply and the session)."""
        if not self._attached():
            return
        try:
            proof_map.record_discussion_turn(self.store, phase="ended", turn=turn, **record)
        except Exception as exc:  # noqa: BLE001 — kept, said, tried again
            with self._lock:
                self._discussion_pending[turn] = {**record, "error": f"{type(exc).__name__}: {exc}"}

    def _discussion_finish(self, job, turn: str, name: str, provider: str, prompt: str) -> None:
        """When the backend's turn ends: the ended record — the reply's text, the session it left, whether it failed, and
        the conversation without its deltas — then the slot is free. Written only while the folder still holds this project."""
        with job.cond:
            while not job.done:
                job.cond.wait(1.0)
        done = next((e for e in reversed(job.events) if e.get("t") == "done"), {})
        texts = [str(e.get("text") or "") for e in job.events if e.get("t") == "text" and e.get("text")]
        reply = "\n\n".join(texts) or "".join(str(e.get("text") or "") for e in job.events if e.get("t") == "delta")
        is_error = bool(done.get("is_error")) or done.get("exit") not in (None, 0)
        if is_error and not reply:
            reply = str(done.get("stderr") or done.get("subtype") or "the agent's turn failed").strip()
        self._discussion_record_ended(turn, by=name, provider=provider, prompt=prompt, job=job.id, session_id=done.get("session_id"),
                                      events=[e for e in job.events if e.get("t") != "delta"], reply=reply, is_error=is_error)
        with self._lock:
            if self._discussion_live and self._discussion_live.get("turn") == turn:
                self._discussion_live = None

    def discussion_events(self, job_id: int, after: int) -> tuple[int, dict]:
        """The events of a discussion turn from `after` on, waiting a while for more: what the drawer streams."""
        try:
            agent = self._discussion_agent()
        except NoStudio as exc:
            return 409, {"error": exc.args[1], "code": exc.args[0]}
        job = agent.jobs.get(job_id)
        if job is None:
            return 404, {"error": "no such discussion turn", "code": "NO_SUCH_JOB"}
        events, done = job.wait_events(after, 20.0)
        return 200, {"events": events, "done": done}

    def discussion_stop(self, body: dict) -> tuple[int, dict]:
        try:
            agent = self._discussion_agent()
        except NoStudio as exc:
            return 409, {"error": exc.args[1], "code": exc.args[0]}
        try:
            job_id = int(body.get("job") or 0)
        except (TypeError, ValueError):
            job_id = 0
        if job_id not in agent.jobs:
            return 404, {"error": "no such discussion turn", "code": "NO_SUCH_JOB"}
        agent.stop(job_id)
        return 200, {"ok": True}

    def close(self) -> None:
        pursuit = self._pursuit
        if pursuit is not None and pursuit.view()["status"] in ("reading", "pursuing"):
            pursuit.stop()  # before the hub closes: its Stop releases the Coordinator it is on through the hub
        with self._lock:
            self._closed = True
            studios, self._studios = list(self._studios.values()), {}
            coordinators, self._coordinators = list(self._coordinators.values()), {}
            discussion, self._discussion = self._discussion, None
            reader, self._reader = self._reader, None
        for manager in (discussion, reader):  # the map's agent (issue #177) and the Reader's, with the studios
            if manager is not None:
                manager.shutdown()
        for coordinator in coordinators:  # a Coordinator at work releases every run it started before the studios close
            if coordinator.active():
                coordinator.release()
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
        if rel == "index.html":
            return StudioAnswer(200, node_page(), _TYPES[".html"])
        if rel in HOST_FILES:  # this package's scripts and stylesheet, before latex-agent's folder
            return StudioAnswer(200, HOST_FILES[rel].read_bytes(), _TYPES[HOST_FILES[rel].suffix])
        asset = (STUDIO_STATIC / rel).resolve()
        if STUDIO_STATIC not in asset.parents or not asset.is_file():
            return _error(HTTPStatus.NOT_FOUND, "NOT_FOUND", rel)
        return StudioAnswer(200, asset.read_bytes(), _TYPES.get(asset.suffix, "text/plain; charset=utf-8"))
