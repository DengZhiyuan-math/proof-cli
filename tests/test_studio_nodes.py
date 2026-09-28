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
    assert "proof.studio.${NODE}." in common and "proof-studio-pdf:\" + NODE" in common
    for name in ("app.js", "common.js", "pdfview.js", "viewer.js", "index.html", "viewer.html"):
        text = (STATIC / name).read_text()
        for absolute in ('"/static/', 'fetch("/', '"/pdf', '"/viewer', 'href="/', 'src="/'):
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
    assert files == {"proof.tex"}


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
