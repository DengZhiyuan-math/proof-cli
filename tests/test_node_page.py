"""The map page is the one human entry, and a local node's page is its studio (ADR-0011, #70)."""

from pathlib import Path

import pytest

from _review_client import DirectClient
from proof_cli.proof_map import claim_node, get_active_claim, get_node, get_workflow_state, list_nodes
from proof_cli.storage import ensure_project

WEBAPP = Path(__file__).resolve().parents[1] / "src" / "proof_cli" / "webapp"
STUDIO_STATIC = Path(__file__).resolve().parents[1] / "src" / "proof_cli" / "studio" / "static"


@pytest.fixture
def page(tmp_path: Path):
    store = ensure_project(tmp_path)
    client = DirectClient(store)
    yield store, client
    client.app.close()


def _ok(response):
    status, body = response
    assert status == 200 and body["ok"], body
    return body["data"]


def _refused(response):
    status, body = response
    assert status >= 400 and not body["ok"], body
    return body["error"]["code"]


# -- creating nodes from the map ----------------------------------------------------


def test_the_page_alone_builds_a_map_from_nothing(page):
    store, client = page
    theorem = _ok(client.post("/api/nodes", {"node_id": "thm", "kind": "theorem", "statement": "T"}))
    claim = _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C", "assumptions": ["x > 0"], "dependencies": ["thm"]}))
    ref = _ok(client.post("/api/nodes", {
        "node_id": "ref", "kind": "imported_result", "statement": "K",
        "source_locator": "doi:10.1/x", "source_version": "v2", "trust_level": "external_reference",
    }))

    assert {n.id for n in list_nodes(store)} == {"thm", "c1", "ref"}
    assert get_node(store, "c1").dependencies == ["thm"] and get_node(store, "c1").assumptions == ["x > 0"]
    assert (theorem["page"], claim["page"], ref["page"]) == ("/studio/thm/", "/studio/c1/", "/#/node/ref")
    assert (store.root / "proofs" / "c1" / "proof.tex").is_file()
    assert client.app.studios.request("GET", "/studio/c1/", "", None, cross_site=False).status == 200


def test_creating_a_node_is_refused_the_way_the_cli_refuses_it(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "a", "kind": "claim", "statement": "A"}))
    assert _refused(client.post("/api/nodes", {"node_id": "a", "kind": "claim", "statement": "again"})) == "NODE_ALREADY_EXISTS"
    assert _refused(client.post("/api/nodes", {"node_id": "r", "kind": "imported_result", "statement": "K"})) == "IMPORTED_RESULT_REQUIRES_SOURCE"
    assert _refused(client.post("/api/nodes", {"node_id": "b", "kind": "claim", "statement": "B", "dependencies": ["nope"]})) == "DEPENDENCY_NOT_FOUND"
    assert _refused(client.post("/api/nodes", {"kind": "claim", "statement": "no id"})) == "INVALID_REQUEST"


def test_the_created_by_is_the_pages_git_identity(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "a", "kind": "claim", "statement": "A"}))
    assert get_node(store, "a").created_by == client.app.state()["reviewer"]


# -- a local node's page is its studio; an imported result's is not -------------------


def test_a_local_node_opens_its_studio_and_an_imported_result_its_own_page(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C"}))
    _ok(client.post("/api/nodes", {"node_id": "ref", "kind": "imported_result", "statement": "K", "source_locator": "doi:k", "source_version": "v1"}))
    _ok(client.post("/api/nodes", {"node_id": "c2", "kind": "claim", "statement": "uses ref", "dependencies": ["ref"]}))

    local, imported = _ok(client.get("/api/node/c1")), _ok(client.get("/api/node/ref"))
    assert [(d["node_id"], d["kind"]) for d in _ok(client.get("/api/node/c2"))["dependencies"]] == [("ref", "imported_result")]
    assert local["studio"] == "/studio/c1/" and imported["studio"] is None
    assert imported["source"] == {"locator": "doi:k", "version": "v1", "trust_level": None}
    assert imported["dependents"] == ["c2"]
    assert {d["kind"] for d in imported["decisions"]} == {"reference_review"}
    assert client.app.studios.request("GET", "/studio/ref/", "", None, cross_site=False).status == 404


# -- the node panel's actions: the CLI's effects and refusals ------------------------


def test_claim_unassign_and_reassign_from_the_node_panel(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C"}))
    me = client.app.state()["reviewer"]

    _ok(client.post("/api/node/c1/claim", {}))
    assert get_active_claim(store, "c1").claimant_id == me
    _ok(client.post("/api/node/c1/unassign", {}))
    assert get_active_claim(store, "c1") is None

    claim_node(store, "c1", claimant_id="agent_b")
    assert _refused(client.post("/api/node/c1/claim", {})) == "CLAIM_CONFLICT"
    _ok(client.post("/api/node/c1/claim", {"reassign": True}))
    assert get_active_claim(store, "c1").claimant_id == me


def test_split_from_the_node_panel_is_all_or_nothing_and_moves_on_to_the_first_child(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "p", "kind": "claim", "statement": "P"}))
    _ok(client.post("/api/nodes", {"node_id": "taken", "kind": "claim", "statement": "exists"}))

    assert _refused(client.post("/api/node/p/split", {"children": [{"id": "k1", "statement": "a"}, {"id": "taken", "statement": "b"}]})) == "NODE_ALREADY_EXISTS"
    assert get_node(store, "k1") is None and get_node(store, "p").dependencies == []

    result = _ok(client.post("/api/node/p/split", {"children": [{"id": "k1", "statement": "a"}, {"id": "k2", "statement": "b"}]}))
    assert result["next"] == "/studio/k1/"
    assert get_node(store, "p").dependencies == ["k1", "k2"]
    assert (store.root / "proofs" / "k1" / "proof.tex").is_file()

    _ok(client.post("/api/nodes", {"node_id": "q", "kind": "claim", "statement": "Q"}))
    claim_node(store, "q", claimant_id="agent_b")
    assert _refused(client.post("/api/node/q/split", {"children": [{"id": "k3", "statement": "c"}]})) == "NOT_CLAIMANT"
    _ok(client.post("/api/node/q/split", {"children": [{"id": "k3", "statement": "c"}], "reassign": True}))


def test_request_review_from_the_node_panel(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C"}))
    assert _refused(client.post("/api/node/c1/request-review", {"rationale": "  "})) == "SCOPING_RATIONALE_REQUIRED"
    snapshot = _ok(client.post("/api/node/c1/request-review", {"rationale": "a single computation"}))
    assert snapshot["version"] == 1 and get_workflow_state(store, "c1") == "review-needed"
    assert _refused(client.post("/api/node/c1/request-review", {"rationale": "again"})) == "WORKING_PROOF_UNCHANGED"

    claim_node(store, "c1", claimant_id="agent_b")
    (store.root / "proofs" / "c1" / "proof.tex").write_text("changed\n")
    assert _refused(client.post("/api/node/c1/request-review", {"rationale": "mine now"})) == "NOT_CLAIMANT"


def test_a_challenge_and_an_evidence_check_from_the_node_panel(page):
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C"}))
    assert _refused(client.post("/api/node/c1/challenge", {"rationale": "missing assumption"})) == "TARGET_NOT_ACCEPTED"
    assert _refused(client.post("/api/node/c1/evidence", {"outcome": "passed"})) == "INVALID_REQUEST"  # which snapshot?
    v1 = _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    (store.root / "proofs" / "c1" / "proof.tex").write_text("a second version\n")
    v2 = _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    # PR #76 audit: a check made on v1 is recorded on v1, never silently on the newer v2
    check = _ok(client.post("/api/node/c1/evidence", {"candidate_proof_id": v1["id"], "outcome": "failed", "notes": "counterexample at n=3", "run_by": "sage"}))
    assert (check["candidate_proof_id"], check["outcome"], check["run_by"]) == (v1["id"], "failed", "sage")
    assert _refused(client.post("/api/node/c1/evidence", {"candidate_proof_id": v2["id"], "outcome": "maybe"})) == "INVALID_OUTCOME"
    assert _refused(client.post("/api/node/c1/evidence", {"candidate_proof_id": "nope", "outcome": "passed"})) == "CANDIDATE_PROOF_NOT_FOUND"
    _ok(client.post("/api/nodes", {"node_id": "c2", "kind": "claim", "statement": "other"}))
    assert _refused(client.post("/api/node/c2/evidence", {"candidate_proof_id": v1["id"], "outcome": "passed"})) == "NOT_THIS_NODE"
    assert _refused(client.post("/api/node/c1/frobnicate", {})) == "NOT_FOUND"


# -- no more launching prism-local --------------------------------------------------


def test_no_page_offers_open_in_prism_local():
    for path in [*WEBAPP.rglob("*.py"), *(WEBAPP / "static").iterdir()]:
        text = path.read_text()
        assert "prism-local" not in text.lower() and "PROOF_CLI_PRISM_LOCAL" not in text, path.name


def test_the_studio_page_carries_the_node_panel():
    index = (STUDIO_STATIC / "index.html").read_text()
    assert 'src="static/node.js"' in index and 'id="node-panel"' in index
    panel = (STUDIO_STATIC / "node.js").read_text()
    for action in ("claim", "unassign", "split", "request-review", "challenge", "evidence"):
        assert f"/{action}" in panel, action


# -- the panel in the browser (PR #76 audit), run for real under node ------------------

import json as _json
import shutil as _shutil
import subprocess as _subprocess

HARNESS = Path(__file__).resolve().parent / "js" / "node_panel_harness.js"
VIEW = {
    "node": {"id": "A", "kind": "claim", "statement": "A", "assumptions": []},
    "workflow_state": "open", "acceptance_state": "unreviewed", "integrity_state": "current", "claim": None,
    "candidate_proof": {"id": "cp-v1", "version": 1, "sha256": "abc"},
    "dependencies": [
        {"node_id": "lem", "kind": "lemma", "pin": {"pinned_version": 3, "pinned_fingerprint": "fp"}, "accepted_version": 4, "current": True, "remedy": "lightweight-re-review"},
        {"node_id": "ref", "kind": "imported_result", "pin": {"pinned_version": None, "pinned_fingerprint": None}, "accepted_version": None, "current": True, "remedy": None},
    ],
}


def _panel(**scenario):
    if _shutil.which("node") is None:
        pytest.skip("needs node")
    done = _subprocess.run(["node", str(HARNESS), _json.dumps({"view": VIEW, "saveAll": True, **scenario})], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return _json.loads(done.stdout)


def test_request_review_saves_the_editor_first_and_stops_if_it_cannot():
    refused = _panel(saveAll=False, click={"label": "Request review", "values": {"rationale": "one argument"}})
    assert refused["events"] == ["saveAll"]  # nothing requested from stale text on disk
    assert "saved" in refused["note"]

    saved = _panel(click={"label": "Request review", "values": {"rationale": "one argument"}})
    assert saved["events"][0] == "saveAll" and saved["events"][1]["post"] == "/api/node/A/request-review"


def test_the_dependency_list_shows_pins_and_opens_each_dependency_where_it_lives():
    shown = _panel()
    assert shown["links"] == ["/studio/lem/", "/#/node/ref"]
    assert "pinned v3" in shown["deps"] and "accepted v4" in shown["deps"]


def test_an_evidence_check_names_the_snapshot_it_checked():
    sent = _panel(answer={"outcome": "passed"}, click={"label": "Record an Evidence check on snapshot v1", "values": {"outcome": "passed", "run_by": "lean"}})
    assert sent["events"][-1]["body"]["candidate_proof_id"] == "cp-v1"


# -- the New node form, run for real under node (PR #63 review) -----------------------

NEW_NODE_HARNESS = Path(__file__).resolve().parent / "js" / "new_node_harness.js"


def _new_node_form(**scenario):
    if _shutil.which("node") is None:
        pytest.skip("needs node")
    done = _subprocess.run(["node", str(NEW_NODE_HARNESS), _json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return _json.loads(done.stdout)


def test_switching_the_form_to_an_imported_result_drops_the_dependencies_it_had():
    """Dependencies chosen for a claim, then the kind switched: an imported result takes none."""
    result = _new_node_form(kind="claim", dependencies=["thm"], switchTo="imported_result")
    (body,) = result["sent"]
    assert body["kind"] == "imported_result" and body["dependencies"] == []
    assert result["selectedAfter"] == []  # the disabled list no longer holds a hidden choice


def test_an_imported_result_never_sends_dependencies_even_if_some_are_selected():
    (body,) = _new_node_form(kind="imported_result", dependencies=["thm"], switchTo=None)["sent"]
    assert body["dependencies"] == [] and body["source_locator"] == "doi:x"


def test_a_local_node_still_sends_its_dependencies():
    (body,) = _new_node_form(kind="claim", dependencies=["thm", "lem"], switchTo=None)["sent"]
    assert body["dependencies"] == ["thm", "lem"]



# -- review in the studio (#71) --------------------------------------------------------

REVIEW_VIEW = {
    **VIEW,
    "workflow_state": "review-needed",
    "candidate_proof": {"id": "cp-v2", "version": 2, "sha256": "d" * 64, "text": "MAIN",
                        "files": {"proof.tex": "MAIN", "body.tex": "BODY", "../preamble.tex": "PRE"}},
    "pdfs": {"snapshot": True, "build": True},
    "decisions": [{"kind": "acceptance", "target_id": "A", "decision": "accept", "binding": "b" * 64}],
}


def test_the_review_section_opens_every_frozen_file_read_only():
    shown = _panel(view=REVIEW_VIEW, press="body.tex")
    assert {"openReadOnly": "v2 · body.tex", "text": "BODY"} in shown["events"]
    assert "Snapshot v2" in shown["review"] and "archived" in shown["review"]


def test_a_decision_from_the_studio_carries_its_binding_and_the_snapshot_it_showed():
    sent = _panel(view=REVIEW_VIEW, press="Accept this snapshot", rationale="every step checked",
                  answer={"results": [{"ok": True}]})
    posted = [e for e in sent["events"] if isinstance(e, dict) and e.get("post") == "/api/decide"]
    (decision,) = posted[0]["body"]["decisions"]
    assert decision["binding"] == "b" * 64 and decision["viewed_candidate_proof_sha256"] == "d" * 64
    assert decision["rationale"] == "every step checked" and "confirm" in sent["events"]


def test_a_refused_confirmation_records_nothing():
    sent = _panel(view=REVIEW_VIEW, press="Accept this snapshot", confirm=False)
    assert not [e for e in sent["events"] if isinstance(e, dict) and e.get("post")]


def test_deciding_on_a_snapshot_the_page_no_longer_shows_is_refused(page):
    """The page showed v1; v2 (a changed \\input file) came since: the Accept it offered is STALE_VIEW."""
    store, client = page
    _ok(client.post("/api/nodes", {"node_id": "c1", "kind": "claim", "statement": "C"}))
    folder = store.root / "proofs" / "c1"
    (folder / "body.tex").write_text("first\n")
    _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    view = _ok(client.get("/api/node/c1"))
    assert set(view["candidate_proof"]["files"]) == {"proof.tex", "body.tex", "../preamble.tex"}
    accept = next(d for d in view["decisions"] if d["decision"] == "accept")

    (folder / "body.tex").write_text("second\n")
    _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    stale = {**accept, "viewed_candidate_proof_sha256": view["candidate_proof"]["sha256"]}
    result = _ok(client.post("/api/decide", {"decisions": [stale]}))["results"][0]
    assert result["error"]["code"] == "STALE_VIEW"

    fresh_view = _ok(client.get("/api/node/c1"))
    fresh = {**next(d for d in fresh_view["decisions"] if d["decision"] == "accept"), "viewed_candidate_proof_sha256": fresh_view["candidate_proof"]["sha256"]}
    assert _ok(client.post("/api/decide", {"decisions": [fresh]}))["results"][0]["ok"]


def test_the_pending_list_sends_a_local_node_to_its_studios_review():
    text = (WEBAPP / "static" / "app.js").read_text()
    assert "`/studio/${encodeURIComponent(item.node_id)}/#review`" in text



def test_a_damaged_snapshot_shows_as_such_in_the_review_section():
    broken = {**REVIEW_VIEW, "candidate_proof": {"id": "cp-v2", "version": 2, "sha256": None, "text": "", "files": {}, "unreadable": True}}
    shown = _panel(view=broken)
    assert "can't be read" in shown["review"]
