"""Agent sessions for the studio.

A chat turn runs on one of the AI backends (backends.py): the Claude Code CLI or the
Codex CLI. This module does the
part that is the same for all of them: it checks the request, states the turn's
file scope, snapshots the editable files before the turn, reports per-file diffs
afterwards and can undo the turn.
"""
from __future__ import annotations

import difflib
import itertools
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .backend_claude import claude_bin  # noqa: F401 — re-exported
from .backends import NO_WINDOW, SYSTEM_APPEND, Backend, Job, kill_tree, load_backends  # noqa: F401
from .fsutil import write_bytes

# A model alias or id such as "opus", "sonnet[1m]", "deepseek-chat" or
# "deepseek/deepseek-chat" (OpenRouter). Never a flag.
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,119}")
MAX_TURNS = 50          # turns kept in memory for their events and Undo


def _coded(answer: dict, code: str) -> dict:
    """A backend's own answer in the studio's error shape: an `error` it gives without a code gets `code`."""
    if isinstance(answer, dict) and "error" in answer and "code" not in answer:
        return {**answer, "code": code}
    return answer


class AgentManager:
    def __init__(self, root_fn: Callable[[], Path], files_fn: Callable[[], list[str]],
                 writable_fn: Callable[[str], object] | None = None,
                 backends: tuple[dict[str, Backend], str, str | None] | None = None,
                 context_fn: Callable[[], object] | None = None):
        self.root_fn = root_fn        # current repository root
        self.files_fn = files_fn      # editable files (repo-relative)
        # Raises ValueError for a path an agent may not write (server.resolve).
        self.writable_fn = writable_fn
        # a node's proof agent context, fresh each turn (proof_agent.py); None outside a proof map
        self.context_fn = context_fn
        self.backends, self.default, self.config_error = backends or load_backends()
        self.jobs: dict[int, Job] = {}
        self.turns: dict[int, Job] = {}
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        self.active: Job | None = None
        self.closed = False        # set by shutdown(): no turn starts after it
        # the studio's own URL for the agent's compile tool (mcp_compile.py), asked once per turn
        # (None: no compile tool, as on a computation node)
        self.compile_url: Callable[[], str | None] | None = None

    def backend(self, provider: str | None) -> Backend | None:
        return self.backends.get(provider or self.default)

    def info(self) -> dict:
        return {"default": self.default, "config_error": self.config_error,
                "providers": [b.info() for b in self.backends.values()],
                "proof_agent": bool(self.context_fn)}  # a node's proof agent (ADR-0011 point 8)

    # ------------------------------------------------------------ snapshots
    # Files are kept as bytes: Undo puts back exactly what was there (line ends, encoding),
    # and a file that is not UTF-8 cannot stop a turn.
    def _snapshot(self) -> dict[str, bytes | None]:
        root, snap = self.root_fn(), {}
        for rel in self.files_fn():
            try:
                snap[rel] = (root / rel).read_bytes()
            except OSError:
                snap[rel] = None
        return snap

    @staticmethod
    def _diff(rel: str, a: bytes | None, b: bytes | None) -> str:
        text = lambda d: d.decode("utf-8", "replace").replace("\r\n", "\n")  # noqa: E731
        diff = "".join(difflib.unified_diff(
            text(a or b"").splitlines(keepends=True), text(b or b"").splitlines(keepends=True),
            fromfile=f"a/{rel}" if a is not None else "/dev/null",
            tofile=f"b/{rel}" if b is not None else "/dev/null", n=2))
        return diff or f"(only the line ends or the encoding of {rel} changed)\n"

    def _writable(self, job: Job, rel: str) -> bool:
        if job.mode != "edit":
            return False
        if job.scope:
            return rel in job.scope
        if self.writable_fn is None:
            return True
        try:
            self.writable_fn(rel)
            return True
        except ValueError:
            return False

    def edit_turn_running(self) -> bool:
        """An edit turn is running now: what is saved meanwhile becomes part of its changes."""
        job = self.active
        return job is not None and not job.done and job.mode == "edit"

    # ------------------------------------------------------------ run
    def start(self, prompt: str, session_id: str | None, mode: str,
              model: str | None = None, effort: str | None = None,
              scope: list[str] | None = None, provider: str | None = None,
              unless: Callable[[], bool] | None = None,
              turn: dict | None = None,
              begin: Callable[[Job], None] | None = None) -> dict:
        """Run one turn. `scope` (project-relative files) limits which files the agent may
        change in edit mode; None lets it change any file and create new ones. `unless` is asked once more, after the checks and
        the preflight, right before the turn exists: true, and no turn starts (a run stopped
        while its turn was being prepared). `turn` is a run's turn (agent_run.py): its role,
        name and redirect, handed to the node's context as they are — None for the
        researcher's own turn, which no run's role reaches. `begin` is told the turn's job once the
        turn exists, right before its backend starts (a run marks its turn as started there)."""
        if self.closed:
            return {"error": "The studio is closed.", "code": "STUDIO_CLOSED"}
        backend = self.backend(provider)
        if backend is None:
            return {"error": f"Unknown provider: {provider}", "code": "AGENT_UNKNOWN_PROVIDER"}
        why = backend.unavailable()
        if why:
            return {"error": why, "code": "AGENT_UNAVAILABLE"}
        if model and not MODEL_RE.fullmatch(model):
            return {"error": f"Not a model name: {model}", "code": "AGENT_INVALID_OPTION"}
        bad = backend.check(model, effort)
        if bad:
            return {"error": bad, "code": "AGENT_INVALID_OPTION"}
        bad = backend.preflight(self.root_fn())
        if bad:
            return {"error": bad, "code": "AGENT_UNAVAILABLE"}
        with self.lock:
            if self.closed:
                return {"error": "The studio is closed.", "code": "STUDIO_CLOSED"}
            if unless is not None and unless():
                return {"error": "The turn was called off before it started.", "code": "TURN_CALLED_OFF"}
            if self.active and not self.active.done:
                return {"error": "The agent is still working on the previous message.", "code": "AGENT_BUSY"}
            job = Job(next(self.ids))
            job.provider = backend.id   # before it is visible as active: stop() finds its backend
            # and its mode: an edit turn is one from the moment anyone can see it (edit_turn_running)
            job.mode = mode if mode in ("edit", "ask") else "ask"
            self.jobs[job.id] = job
            self.active = job
        job.scope = scope if mode == "edit" and scope else None
        if job.scope:
            note = ("You may change ONLY these files in this turn: " + ", ".join(job.scope)
                    + ". Do not edit or create any other file; if the request needs that, "
                    "say so instead.")
        elif mode == "edit":
            note = ("You may change any file in the project and create new files in this "
                    "turn. File restrictions from earlier turns no longer apply.")
        else:
            note = None
        # Each turn states its own scope at the end of the message. A resumed conversation
        # remembers earlier turns, and a note there outweighs one in the system prompt.
        # (Appended, not prepended: a /command must stay first.)
        if note:
            prompt = f"{prompt}\n\n[Scope for this turn] {note}"
        job.provider, job.prompt, job.session_id = backend.id, prompt, session_id
        job.model, job.effort = model, effort
        job.root, job.files = self.root_fn(), self.files_fn
        job.context = (self.context_fn(turn) if turn is not None else self.context_fn()) if self.context_fn else None
        job.turn = turn
        job.compile_url = self.compile_url() if self.compile_url else None
        job.writable = lambda rel: self._writable(job, rel)
        job.before = self._snapshot()
        if begin is not None:
            try:
                begin(job)
            except Exception as e:  # noqa: BLE001 — the turn is registered as active: it must still run and end
                job.emit({"t": "error", "message": f"{type(e).__name__}: {e}"})
        threading.Thread(target=self._run, args=(job, backend), daemon=True).start()
        return {"job": job.id, "provider": backend.id}

    def _run(self, job: Job, backend: Backend) -> None:
        t0, res = time.time(), {}
        try:
            res = backend.run(job) or {}
        except Exception as e:  # noqa: BLE001 — report anything to the UI
            job.emit({"t": "error", "message": f"{type(e).__name__}: {e}"})
            res = {"is_error": True}
        finally:
            time.sleep(0.2)
            job.after = self._snapshot()
            out_of_scope = [rel for rel in sorted(set(job.before) | set(job.after))
                            if job.scope and rel not in job.scope
                            and job.before.get(rel) != job.after.get(rel)]
            reverted = []
            if out_of_scope and not backend.enforces_scope:
                # This backend cannot be kept to the @-mentioned files, so undo what it
                # wrote outside them (only where nothing else changed the file since).
                reverted = self._restore(job, out_of_scope)
                job.after = self._snapshot()
            changed = []
            for rel in sorted(set(job.before) | set(job.after)):
                a, b = job.before.get(rel), job.after.get(rel)
                if a != b:
                    changed.append({"path": rel, "diff": self._diff(rel, a, b),
                                    "created": a is None, "deleted": b is None})
            # What the turn left may need recording in project state: a key-ideas summary an agent turn wrote is the
            # agent's draft (ADR-0013), whichever turn wrote it — a run's role, a one-off task from the "+" menu.
            ended = getattr(job.context, "turn_ended", None)
            if ended is not None and job.mode == "edit":
                try:
                    ended(job.root, [c["path"] for c in changed if not c["deleted"]])
                except Exception as e:  # noqa: BLE001 — report it; the turn still ends
                    job.emit({"t": "error", "message": f"{type(e).__name__}: {e}"})
            # Undo needs only the files this turn changed: keep just those in memory.
            keep = [c["path"] for c in changed]
            job.before = {r: job.before.get(r) for r in keep}
            job.after = {r: job.after.get(r) for r in keep}
            self.turns[job.id] = job
            with self.lock:
                while len(self.turns) > MAX_TURNS:
                    self.turns.pop(next(iter(self.turns)))
                while len(self.jobs) > MAX_TURNS and next(iter(self.jobs)) != job.id:
                    self.jobs.pop(next(iter(self.jobs)))
            ev = {"t": "done", "turn": job.id, "provider": job.provider, "changed": changed,
                  "exit": res.get("exit"), "scope": job.scope,
                  "out_of_scope": [r for r in out_of_scope if r not in reverted],
                  "reverted": reverted,
                  "session_id": res.get("session_id") or job.session_id,
                  "duration": res.get("duration") or int((time.time() - t0) * 1000)}
            for k in ("cost", "billing", "usage", "is_error", "subtype", "denials", "denied", "stderr"):
                if res.get(k) is not None:
                    ev[k] = res[k]
            job.emit(ev)
            with job.cond:
                job.done = True
                job.cond.notify_all()

    # ------------------------------------------------------------ backend extras
    def commands(self, provider: str | None, refresh: bool = False) -> dict:
        backend = self.backend(provider)
        if backend is None:
            return {"error": f"Unknown provider: {provider}", "code": "AGENT_UNKNOWN_PROVIDER"}
        return _coded(backend.commands(self.root_fn(), refresh), "AGENT_UNAVAILABLE")

    def probe_rate(self, provider: str | None = None) -> dict:
        backend = self.backend(provider)
        if backend is None or not backend.usage_limits:
            return {"error": "This provider reports no usage limits.", "code": "AGENT_NO_USAGE_LIMITS"}
        # The probe is a (tiny) model call, so it passes the same check as a turn.
        bad = backend.preflight(self.root_fn())
        if bad:
            return {"error": bad, "code": "AGENT_UNAVAILABLE", "rate": getattr(backend, "rate", None)}
        return _coded(backend.probe_rate(), "AGENT_UNAVAILABLE")

    def stop(self, jid: int) -> dict:
        job = self.jobs.get(jid)
        if job and not job.done:
            job.cancel.set()            # whatever else: a turn not started yet then never starts
            backend = self.backends.get(job.provider)
            if backend:
                backend.stop(job)
            return {"ok": True}
        return {"ok": False}

    def built(self, result: dict) -> None:
        """A build the agent ran with its compile tool: the panel shows it as the editor's."""
        job = self.active
        if job and not job.done:
            job.emit({"t": "build", "result": result})

    def busy(self) -> bool:
        job = self.active
        return bool(job and not job.done)

    def shutdown(self) -> None:
        """Stop a turn that is still running when the server exits, and start no other."""
        with self.lock:
            self.closed = True
            job = self.active
        if job and not job.done:
            self.stop(job.id)

    def _restore(self, job: Job, rels) -> list[str]:
        """Put `rels` back as they were before `job`, where they still match its result."""
        root, restored = self.root_fn(), []
        for rel in rels:
            a, b = job.before.get(rel), job.after.get(rel)
            p = root / rel
            try:
                cur = p.read_bytes() if p.exists() else None
            except OSError:
                continue                 # cannot tell what is there now; leave it
            if cur != b:
                continue                 # edited again since; never clobber
            try:
                if a is None:
                    p.unlink()
                else:
                    write_bytes(p, a)
            except OSError:
                continue                 # locked by another program: reported as not restored
            restored.append(rel)
        return restored

    def undo(self, turn: int) -> dict:
        """Restore files changed in `turn`, only where they still match the turn's result."""
        job = self.turns.get(turn)
        if not job:
            return {"error": "unknown turn", "code": "NO_SUCH_JOB"}
        rels = [rel for rel in sorted(set(job.before) | set(job.after))
                if job.before.get(rel) != job.after.get(rel)]
        restored = self._restore(job, rels)
        return {"restored": restored, "skipped": [r for r in rels if r not in restored]}
