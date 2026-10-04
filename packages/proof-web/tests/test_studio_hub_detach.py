"""Closing the page of a project that is gone from its folder (review of ADR-0018, second round): the old runs'
hooks reach the database by path, so without care they would act on whatever project the folder holds now.
A detached hub writes nothing, and the agent's processes are shut down whatever the run's release does."""

import shutil
import threading
import time
from pathlib import Path

import pytest

from _proofs import KEY_IDEAS
from latex_agent.backends import Backend
from proof_cli.key_ideas import KEY_IDEAS_FILE
from proof_cli.proof_map import ProofMapError, claim_node, create_node, get_active_claim, list_candidate_proofs, work_log
from proof_cli.storage import ensure_project, list_events
from proof_cli.vault import node_folder
from proof_web.studios import NoStudio, StudioHub


def _project_with(folder: Path, node_id="lem"):
    store = ensure_project(folder)
    create_node(store, node_id=node_id, kind="lemma", statement="The partial sums are bounded")
    return store


class ActiveRun:
    """A run still active when the studio closes: its release gives the node back through the hooks, as AgentRun's does."""

    def __init__(self, hooks, name):
        self.hooks, self.name, self.released = hooks, name, False

    def active(self):
        return True

    def release(self, reason=""):
        self.released = True
        self.hooks.record_stuck("prover", self.name, reason)
        self.hooks.release(self.name)
        return {"status": "released"}


def test_a_detached_hub_releases_nothing_in_the_project_now_in_the_folder(tmp_path, monkeypatch):
    folder = tmp_path / "bw"
    _project_with(folder)
    hub = StudioHub(ensure_project(folder))
    studio = hub.studio("lem")
    hooks, name = studio.run.hooks, studio.run.hooks.agent_name("claude")
    shutdown = []
    monkeypatch.setattr(studio.agent, "shutdown", lambda: shutdown.append(True))
    studio.run = ActiveRun(hooks, name)

    shutil.rmtree(folder)
    new_store = _project_with(folder)  # another project at the same path, with a node and a claimant of the same names
    claim_node(new_store, "lem", claimant_id=name)

    hub.detach()
    hub.close()

    assert studio.run.released and shutdown == [True]
    assert get_active_claim(new_store, "lem").claimant_id == name  # the new project's claim is untouched
    assert [e for e in work_log(new_store, "lem") if e.get("status") == "stuck"] == []  # and no stuck step was written there
    assert hooks.work_log() == []


def test_closing_over_an_empty_new_project_still_shuts_the_agent_down(tmp_path, monkeypatch):
    folder = tmp_path / "bw"
    _project_with(folder)
    hub = StudioHub(ensure_project(folder))
    studio = hub.studio("lem")
    hooks, name = studio.run.hooks, studio.run.hooks.agent_name("claude")
    shutdown = []
    monkeypatch.setattr(studio.agent, "shutdown", lambda: shutdown.append(True))
    studio.run = ActiveRun(hooks, name)

    shutil.rmtree(folder)
    ensure_project(folder)  # empty: node "lem" no longer exists

    hub.detach()
    hub.close()  # nothing raises: the hooks write nothing

    assert shutdown == [True]


def test_the_agent_shuts_down_even_when_the_runs_release_raises(tmp_path, monkeypatch):
    class BrokenRun:
        def active(self):
            return True

        def release(self, reason=""):
            raise RuntimeError("boom")

    folder = tmp_path / "bw"
    hub = StudioHub(_project_with(folder))
    studio = hub.studio("lem")
    shutdown = []
    monkeypatch.setattr(studio.agent, "shutdown", lambda: shutdown.append(True))
    studio.run = BrokenRun()

    with pytest.raises(RuntimeError):
        hub.close()

    assert shutdown == [True]


def test_a_stale_pages_start_and_review_now_are_refused_and_write_nothing_on_the_new_project(tmp_path):
    """Review of ADR-0018 (fifth round): the old page's Start claimed the new project's node, and its Review-now
    froze a Candidate proof of it. Refused now, from the hub, from a studio it had already made, and at the hooks."""
    folder = tmp_path / "bw"
    _project_with(folder)
    hub = StudioHub(ensure_project(folder))
    studio = hub.studio("lem")  # made while the project was there, as the old page's would be
    hooks = studio.run.hooks

    shutil.rmtree(folder)
    new_store = _project_with(folder)

    with pytest.raises(NoStudio) as refused:
        hub.studio("lem")
    assert refused.value.args[0] == "PROJECT_REPLACED"
    status, answer = hub.run_action("lem", "start", {"provider": "claude"})
    assert status == 410 and answer["error"] == "PROJECT_REPLACED"

    status, answer = studio.run_action("start", {"provider": "claude"})  # the studio the old page already had
    assert status == 400 and answer["error"] == "PROJECT_REPLACED", answer
    status, answer = studio.run_action("review-now", {})
    assert status == 409 and answer["error"] == "PROJECT_REPLACED", answer
    with pytest.raises(ProofMapError):
        hooks.assign("claude-code")
    with pytest.raises(ProofMapError):
        hooks.review_now()

    assert get_active_claim(new_store, "lem") is None and list_candidate_proofs(new_store, "lem") == []
    hub.close()


# -- a drafting turn that ends after the project it drafted for is gone (ADR-0013, review third round) ----------


class _DraftingBackend(Backend):
    """A backend whose one turn writes the key-ideas file, then waits to be stopped (or released) before it returns.
    Its `finish` callback — the draft's record — then runs as every turn's does, after the backend."""

    kind = id = label = "fake"

    def __init__(self):
        super().__init__("fake")
        self.release = threading.Event()

    def run(self, job):
        (job.root / KEY_IDEAS_FILE).write_text(KEY_IDEAS, encoding="utf-8")
        job.cancel.wait(5) or self.release.wait(5)
        return {"is_error": job.cancel.is_set(), "subtype": "stopped" if job.cancel.is_set() else "success"}


def _start_draft(hub: StudioHub, node_id: str):
    studio = hub.studio(node_id)
    backend = _DraftingBackend()
    studio.agent.backends, studio.agent.default = {"fake": backend}, "fake"
    context = studio.agent.context_fn()
    target = studio.root / KEY_IDEAS_FILE
    answer = studio.agent.start(context.key_ideas_prompt(), None, "edit", None, None, [KEY_IDEAS_FILE], "fake",
                                finish=lambda: context.record_draft(target))
    assert "job" in answer, answer
    return studio, backend, studio.agent.jobs[answer["job"]]


def _finished(job, seconds=10):
    deadline = time.time() + seconds
    while not job.done and time.time() < deadline:
        time.sleep(0.02)
    assert job.done


def _drafts(store):
    return [e for e in list_events(store) if e.kind == "proof_map_key_ideas_drafted"]


def test_a_drafting_turn_cancelled_by_a_detached_close_records_no_draft_on_the_new_project(tmp_path):
    folder = tmp_path / "bw"
    _project_with(folder)
    hub = StudioHub(ensure_project(folder))
    studio, backend, job = _start_draft(hub, "lem")
    while not (studio.root / KEY_IDEAS_FILE).exists():
        time.sleep(0.02)

    shutil.rmtree(folder)
    new_store = _project_with(folder)  # the new project's author writes their own summary
    (node_folder(folder, "lem") / KEY_IDEAS_FILE).write_text(KEY_IDEAS, encoding="utf-8")

    hub.detach()
    hub.close()  # cancels the turn; its finish callback still runs, after the backend returns
    _finished(job)

    assert _drafts(new_store) == []  # the author's summary is not marked as the old agent's draft


def test_a_drafting_turn_that_ends_after_the_project_was_replaced_records_nothing_even_before_anyone_retires_the_page(tmp_path):
    """Review of ADR-0018 (fourth round): the folder is emptied and a project started again at the same path from a
    terminal while the old turn is still running; nothing has told the hub. The turn ends before the next `open`
    (or any Forget): the hub sees for itself that the folder's project isn't the one it was made for."""
    folder = tmp_path / "bw"
    _project_with(folder)
    hub = StudioHub(ensure_project(folder))
    studio, backend, job = _start_draft(hub, "lem")
    while not (studio.root / KEY_IDEAS_FILE).exists():
        time.sleep(0.02)

    shutil.rmtree(folder)
    new_store = _project_with(folder)  # as `proof init` plus the author's own summary would
    (node_folder(folder, "lem") / KEY_IDEAS_FILE).write_text(KEY_IDEAS, encoding="utf-8")

    backend.release.set()  # the old turn ends on its own; no detach, no close
    _finished(job)

    assert _drafts(new_store) == []
    hub.close()  # and closing now (the Home retiring it later) releases nothing of the new project's either
    assert _drafts(new_store) == []


def test_the_same_drafting_turn_on_a_live_project_records_its_draft(tmp_path):
    """The control: the path the test above cuts is the one that records a draft when the project is still there."""
    folder = tmp_path / "bw"
    store = _project_with(folder)
    hub = StudioHub(store)
    studio, backend, job = _start_draft(hub, "lem")
    backend.release.set()
    _finished(job)

    (draft,) = _drafts(store)
    assert draft.entity_id == "lem"
    hub.close()
