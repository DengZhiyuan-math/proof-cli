"""One studio per node, inside the proof map's server (ADR-0011, #69).

Driven through `StudioHub.request`, what the server hands every `/studio/<node>/…` request
to, so no socket is needed; the Host and Origin checks in front of it are in
test_review_app.py.
"""

import json
import shutil
from pathlib import Path
from unittest import mock

import pytest

from _proofs import submit_proof
from proof_cli.proof_map import create_node
from proof_cli.storage import ensure_project
from proof_cli.vault import build_is_current
from proof_cli.webapp.studios import StudioHub

STATIC = Path(__file__).resolve().parents[1] / "src" / "proof_cli" / "studio" / "static"


@pytest.fixture
def hub(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="lemma", statement="a")
    create_node(store, node_id="B", kind="claim", statement="b")
    hub = StudioHub(store)
    yield store, hub
    hub.close()


def _get(hub, path, *, cross_site=False):
    base, _, query = path.partition("?")
    answer = hub.request("GET", base, query, None, cross_site=cross_site)
    return answer.status, (json.loads(answer.body) if answer.content_type == "application/json" else answer)


def _post(hub, path, body):
    answer = hub.request("POST", path, "", body, cross_site=False)
    return answer.status, json.loads(answer.body)


def _save(hub, node, rel, content):
    return _post(hub, f"/studio/{node}/api/file", {"path": rel, "content": content, "base_mtime": None, "force": True})


# -- one studio per node ------------------------------------------------------------


def test_two_nodes_keep_separate_files_builds_and_agents(hub):
    store, hub = hub
    status, _ = _save(hub, "A", "extra.tex", "only in A\n")
    assert status == 200

    files = {node: {f["path"] for f in _get(hub, f"/studio/{node}/api/tree")[1]["files"]} for node in ("A", "B")}
    assert files == {"A": {"proof.tex", "extra.tex"}, "B": {"proof.tex"}}
    a, b = hub.studio("A"), hub.studio("B")
    assert a is hub.studio("A") and a is not b
    assert a.agent is not b.agent and a.build_lock is not b.build_lock

    # a build running on A doesn't make B wait: builds are limited per node, not per process
    with a.build_lock, mock.patch("proof_cli.studio.build.shutil.which", return_value=None):
        assert _post(hub, "/studio/A/api/build", {"mode": "draft"})[1] == {"busy": True}
        assert _post(hub, "/studio/B/api/build", {"mode": "draft"})[1]["busy"] is False


def test_the_page_keys_its_browser_state_by_node_and_uses_relative_urls():
    common = (STATIC / "common.js").read_text()
    assert "proof-studio-pdf:\" + NODE" in common
    for name in ("app.js", "common.js", "pdfview.js", "viewer.js", "index.html", "viewer.html"):
        text = (STATIC / name).read_text()
        # the studio's own files and API are relative; a link to the map ("/") or the node panel's
        # calls to the proof map's API (/api/node/…) are absolute by design
        for absolute in ('"/static/', 'fetch("/api/file', '"/pdf', '"/viewer', 'href="/static', 'src="/'):
            assert absolute not in text, (name, absolute)
        assert '"prism-pdf' not in text and '"prism.' not in text, name


# -- what a node's studio may write -------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    ["snapshots/v1.tex", "reviews.jsonl", "build/proof.tex", "../B/proof.tex", "../preamble.tex", "scratch/notes.tex"],
)
def test_the_studio_writes_only_the_nodes_working_sources(hub, rel):
    store, hub = hub
    submit_proof(store, "A", claimant_id="agent_a", scoping_rationale="scoped", content="\\documentclass{article}\\begin{document}v1\\end{document}\n")
    folder = store.root / "proofs" / "A"
    for made in ("build/proof.tex", "scratch/notes.tex"):
        (folder / made).parent.mkdir(exist_ok=True)
        (folder / made).write_text("untouched\n")
    (folder / "reviews.jsonl").write_text("")
    target = (folder / rel).resolve()
    before = target.read_bytes() if target.exists() else None

    status, body = _save(hub, "A", rel, "overwritten\n")

    assert status == 400, body
    assert (target.read_bytes() if target.exists() else None) == before


def test_snapshots_and_scratch_are_not_listed(hub):
    store, hub = hub
    submit_proof(store, "A", claimant_id="agent_a", scoping_rationale="scoped", content="text\n")
    (store.root / "proofs" / "A" / "scratch").mkdir()
    (store.root / "proofs" / "A" / "scratch" / "check.tex").write_text("x\n")

    files = {f["path"] for f in _get(hub, "/studio/A/api/tree")[1]["files"]}
    assert files == {"proof.tex", "key-ideas.md"}  # the summary is a working source the author edits (ADR-0013)


def test_a_nodes_build_is_fixed_whatever_prism_json_says(hub):
    store, hub = hub
    (store.root / "proofs" / "A" / "prism.json").write_text('{"main": "other.tex", "outdir": "out"}')

    config = _get(hub, "/studio/A/api/config")[1]

    assert (config["main"], config["outdir"]) == ("proof.tex", "build")
    assert "fixed" in config["error"]


# -- building ----------------------------------------------------------------------


def test_without_tex_the_studio_opens_edits_saves_and_says_building_is_unavailable(hub):
    store, hub = hub
    page = hub.request("GET", "/studio/A/", "", None, cross_site=False)
    assert page.status == 200 and b"<html" in page.body.lower()
    assert _save(hub, "A", "proof.tex", "edited\n")[0] == 200
    assert (store.root / "proofs" / "A" / "proof.tex").read_text() == "edited\n"

    with mock.patch("proof_cli.studio.build.shutil.which", return_value=None):
        result = _post(hub, "/studio/A/api/build", {"mode": "draft"})[1]

    assert result["unavailable"] is True


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="needs pdflatex")
def test_a_studio_build_is_the_pdf_review_archives_and_a_failed_one_leaves_it_stale(hub):
    store, hub = hub
    ok = _post(hub, "/studio/A/api/build", {"mode": "draft"})[1]
    assert ok["exit"] == 0, ok["output"][-2000:]
    assert (store.root / "proofs" / "A" / "build" / "proof.pdf").is_file()
    assert build_is_current(store.root, "A")

    proof = store.root / "proofs" / "A" / "proof.tex"
    proof.write_text(proof.read_text().replace("\\end{proof}", "\\undefinedcontrolsequence\\end{proof}"))
    failed = _post(hub, "/studio/A/api/build", {"mode": "strict"})[1]
    assert failed["exit"] != 0
    assert not build_is_current(store.root, "A")


# -- which nodes have a studio, and who may ask -------------------------------------


def test_an_imported_result_or_unknown_node_has_no_studio(hub):
    store, hub = hub
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    status, body = _get(hub, "/studio/ref/api/tree")
    assert (status, body["error"]["code"]) == (404, "NO_STUDIO")
    assert _get(hub, "/studio/nope/")[1]["error"]["code"] == "NODE_NOT_FOUND"


def test_a_cross_site_request_reaches_no_studio_api(hub):
    store, hub = hub
    status, body = _get(hub, "/studio/A/api/tree", cross_site=True)
    assert (status, body["error"]["code"]) == (403, "CROSS_SITE")


def test_the_page_needs_its_trailing_slash_for_relative_urls(hub):
    store, hub = hub
    answer = hub.request("GET", "/studio/A", "", None, cross_site=False)
    assert (answer.status, answer.location) == (308, "/studio/A/")


def test_the_studio_page_and_its_api_carry_a_content_security_policy(hub):
    store, hub = hub
    page = hub.request("GET", "/studio/A/", "", None, cross_site=False)
    assert "script-src 'self'" in page.policy and "frame-ancestors 'none'" in page.policy
    assert hub.request("GET", "/studio/A/static/../server.py", "", None, cross_site=False).status == 404


# -- PR #75 review: closing, the agent's scratch folder, collision-free browser keys ----


def test_after_close_no_studio_starts_a_build_or_an_agent_turn(hub):
    store, hub = hub
    studio = hub.studio("A")  # a request that got its studio before the server closed
    hub.close()

    with mock.patch("proof_cli.studio.build.Build.run") as run:
        result = studio.run_build("draft")
    run.assert_not_called()
    assert result["closed"] is True
    assert "closed" in studio.agent.start("prove it", None, "edit")["error"]
    assert hub.request("GET", "/studio/A/api/tree", "", None, cross_site=False).status == 503


def test_a_turn_stopped_before_its_cli_starts_never_runs_it(tmp_path):
    import sys

    from proof_cli.studio.backends import CliBackend, Job

    class Sleeper(CliBackend):
        def command(self, job):
            return [sys.executable, "-c", "import time; time.sleep(3)"], ""

        def handle(self, d, job, st):
            pass

    job = Job(1)
    job.root = tmp_path
    job.cancel.set()  # the studio closed between admitting the turn and starting it
    Sleeper("sleeper").run(job)
    assert job.proc is None  # never started, not started and waited for


@pytest.mark.parametrize("rel", ["scratch/check.py", "scratch/check.tex", "scratch/out/result.txt", "proof.tex"])
def test_the_agent_may_write_the_nodes_scratch_folder(hub, rel):
    store, hub = hub
    assert hub.studio("A").agent_writable(rel) == (store.root / "proofs" / "A" / rel).resolve()


@pytest.mark.parametrize("rel", ["snapshots/v1.tex", "build/proof.pdf", "reviews.jsonl", "../B/proof.tex", "scratch/../../B/proof.tex", "/etc/passwd", "scratch/.git/config"])
def test_the_agent_still_may_not_write_protected_paths(hub, rel):
    store, hub = hub
    with pytest.raises(ValueError):
        hub.studio("A").agent_writable(rel)


def test_the_agents_turns_see_and_can_undo_scratch_files(hub):
    store, hub = hub
    scratch = store.root / "proofs" / "A" / "scratch"
    scratch.mkdir()
    (scratch / "check.py").write_text("print(1)\n")
    assert "scratch/check.py" in hub.studio("A").agent_files()
    assert "scratch/check.py" not in hub.studio("A").list_files()  # still hidden from the editor


def test_browser_keys_cannot_collide_between_node_ids_with_dots():
    """PR #75 review: node `A` key `chat.session` and node `A.chat` key `session` were one key."""
    common = (STATIC / "common.js").read_text()
    assert "JSON.stringify([NODE, k])" in common


def test_a_turn_admitted_but_not_yet_given_its_provider_is_still_cancelled_by_shutdown(tmp_path):
    """PR #76 audit: shutdown landing after `active` was set but before `provider` was left the
    turn uncancelled, and its CLI started anyway."""
    from proof_cli.studio.agent import AgentManager
    from proof_cli.studio.backends import Job

    manager = AgentManager(lambda: tmp_path, lambda: [], backends=({}, "none", None))
    job = Job(1)  # admitted: active, but no provider yet
    manager.jobs[job.id] = job
    manager.active = job

    manager.shutdown()

    assert job.cancel.is_set()  # so the CLI backend refuses to start (checked before and after its Popen)


def test_a_turn_is_given_its_provider_before_it_becomes_active(tmp_path):
    from proof_cli.studio.agent import AgentManager
    from proof_cli.studio.backends import Backend

    class Quiet(Backend):
        def run(self, job):
            return {}

    manager = AgentManager(lambda: tmp_path, lambda: [], backends=({"quiet": Quiet("quiet")}, "quiet", None))
    released = []

    class Watched:
        """The manager's lock, noting the active turn's provider each time it's let go."""

        def __init__(self, lock):
            self.lock = lock

        def __enter__(self):
            return self.lock.__enter__()

        def __exit__(self, *exc):
            released.append(manager.active.provider if manager.active else None)
            return self.lock.__exit__(*exc)

    manager.lock = Watched(manager.lock)
    assert "job" in manager.start("hi", None, "ask")
    assert released[0] == "quiet"  # already set when the turn was published as active
