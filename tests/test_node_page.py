"""The map page is the one human entry, and a local node's page is its studio (ADR-0011, #70)."""

from pathlib import Path

import pytest

from _proofs import KEY_IDEAS, write_key_ideas
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
    assert _refused(client.post("/api/node/c1/request-review", {"rationale": "a single computation"})) == "KEY_IDEAS_REQUIRED"
    write_key_ideas(store, "c1")
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
    write_key_ideas(store, "c1")
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
    for action in ("claim", "unassign", "split", "depend", "request-review", "challenge", "evidence"):
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


# -- review in the studio (#71) --------------------------------------------------------

SUMMARY = {
    "text": KEY_IDEAS,
    "fields": {"core_idea": "CORE: compactness of $[0, 1]$", "main_steps": "STEPS: 1. cover (uses lem)", "difficulties": "HARD: the subcover", "not_covered": "OPEN: 无"},
    "drafted_by": None,
}
REVIEW_VIEW = {
    **VIEW,
    "workflow_state": "review-needed",
    "candidate_proof": {"id": "cp-v2", "version": 2, "sha256": "d" * 64, "text": "MAIN",
                        "files": {"proof.tex": "MAIN", "body.tex": "BODY", "key-ideas.md": KEY_IDEAS, "../preamble.tex": "PRE"},
                        "key_ideas": SUMMARY},
    "pdfs": {"snapshot": True, "build": True},
    "decisions": [{"kind": "acceptance", "target_id": "A", "decision": "accept", "binding": "b" * 64}],
    "key_ideas_working": {"exists": True, "missing": []},
}


def test_the_review_view_shows_only_the_summary_and_the_decision_controls():
    shown = _panel(view=REVIEW_VIEW)
    review = shown["review"]
    assert "Snapshot v2" in review
    for title, text in (("核心思路", "CORE: compactness of"), ("主要步骤", "STEPS"), ("难点", "HARD"), ("未覆盖", "OPEN")):
        assert title in review and text in review
    assert "Accept this snapshot" in shown["reviewButtons"]
    # no LaTeX source and no PDF: neither a frozen file's text, nor its name, nor the archived PDF
    for source in ("MAIN", "BODY", "PRE", "body.tex", "proof.tex", "preamble.tex"):
        assert source not in review, source
    assert not [href for href in shown["reviewLinks"] if "pdf" in href]
    assert shown["reviewButtons"] == ["Accept this snapshot"]
    # the frozen sources and the PDF are a link away, on the node's page
    assert "/#/node/A" in shown["reviewLinks"]


@pytest.mark.parametrize("provenance, shown_as", [
    ("agent (confirmed by author at request-review)", "由 agent 起草、作者确认"),
    ("agent draft, edited by author", "由 agent 起草、作者修改"),
    ("author", "作者撰写"),
])
def test_the_review_view_says_who_wrote_the_summary(provenance, shown_as):
    view = {**REVIEW_VIEW, "candidate_proof": {**REVIEW_VIEW["candidate_proof"], "key_ideas": {**SUMMARY, "drafted_by": provenance}}}
    assert shown_as in _panel(view=view)["review"]
    assert "由 agent 起草" not in _panel(view=REVIEW_VIEW)["review"]  # an older record says nothing


def test_an_old_snapshot_without_a_summary_is_reviewed_with_a_note_and_a_link():
    old = {**REVIEW_VIEW, "candidate_proof": {**REVIEW_VIEW["candidate_proof"], "files": {"proof.tex": "MAIN"}, "key_ideas": None}}
    shown = _panel(view=old)
    assert "这个 snapshot 没有关键思路摘要" in shown["review"]
    assert "/#/node/A" in shown["reviewLinks"]
    assert shown["reviewButtons"] == ["Accept this snapshot"]  # still decided as before
    assert "MAIN" not in shown["review"]


def test_the_panel_offers_the_proof_agents_draft_when_the_node_has_no_summary():
    missing = {**VIEW, "key_ideas_working": {"exists": False, "missing": ["key-ideas.md"]}}
    drafted = _panel(view=missing, press="Draft key ideas with the proof agent")
    assert "draftKeyIdeas" in drafted["events"]
    assert "request review to confirm" in drafted["note"]
    # with a summary in place there is nothing to draft; an incomplete one says what it lacks
    assert "Draft key ideas with the proof agent" not in _panel(view=REVIEW_VIEW)["buttons"]
    partial = _panel(view={**VIEW, "key_ideas_working": {"exists": True, "missing": ["主要步骤"]}})
    assert "主要步骤" in partial["text"] and "Draft key ideas with the proof agent" not in partial["buttons"]


def test_the_studio_page_can_draft_key_ideas_through_the_agent_panel():
    app = (STUDIO_STATIC / "app.js").read_text()
    assert "async function draftKeyIdeas()" in app and '"/api/key-ideas/draft"' in app


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
    write_key_ideas(store, "c1")
    _ok(client.post("/api/node/c1/request-review", {"rationale": "scoped"}))
    view = _ok(client.get("/api/node/c1"))
    assert set(view["candidate_proof"]["files"]) == {"proof.tex", "body.tex", "key-ideas.md", "../preamble.tex"}
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



# -- maths in the summary is typeset with the vendored KaTeX (ADR-0013) ---------------------


def _review_with(core, **scenario):
    view = {**REVIEW_VIEW, "candidate_proof": {**REVIEW_VIEW["candidate_proof"], "key_ideas": {**SUMMARY, "fields": {**SUMMARY["fields"], "core_idea": core}}}}
    return _panel(view=view, **scenario)


def test_the_review_view_renders_inline_and_display_maths():
    shown = _review_with("By $[0, 1]$ compact, $$\\sup_{x} f(x) < \\infty.$$ Costs \\$5.")
    assert {"tex": "[0, 1]", "displayMode": False} in shown["katex"]
    assert {"tex": "\\sup_{x} f(x) < \\infty.", "displayMode": True} in shown["katex"]
    assert {"class": "math", "text": "[katex: [0, 1]]", "title": None} in shown["math"]
    assert {"class": "math display", "text": "[katex display: \\sup_{x} f(x) < \\infty.]", "title": None} in shown["math"]
    assert "Costs \\$5." in shown["review"]  # an escaped dollar is a dollar


def test_a_malformed_formula_in_the_review_view_shows_as_text_and_never_throws():
    shown = _review_with("Broken $\\frac{1}{$ but $\\alpha$ is fine; an unclosed $ stays text.")
    (bad,) = [m for m in shown["math"] if m["class"] == "math unrendered"]
    assert bad["text"] == "$\\frac{1}{$" and bad["title"]  # KaTeX's parse error, on hover
    assert {"class": "math", "text": "[katex: \\alpha]", "title": None} in shown["math"]
    assert "an unclosed $ stays text." in shown["review"]
    assert shown["reviewButtons"] == ["Accept this snapshot"]  # the panel still rendered whole


def test_without_katex_the_maths_shows_as_written():
    shown = _review_with("By $[0, 1]$ compact.", katex=False)
    assert shown["katex"] == [] and "$[0, 1]$" in shown["review"]


def test_the_studio_page_loads_the_vendored_katex_before_the_node_panel():
    index = (STUDIO_STATIC / "index.html").read_text()
    assert 'href="static/vendor/katex.min.css"' in index
    assert index.index('src="static/vendor/katex.min.js"') < index.index('src="static/mathtext.js"') < index.index('src="static/node.js"')
    vendor = STUDIO_STATIC / "vendor"
    assert (vendor / "LICENSE-katex").read_text().startswith("The MIT License")
    assert len(list((vendor / "fonts").glob("KaTeX_*.woff2"))) == 20
    css = (vendor / "katex.min.css").read_text()
    assert "url(fonts/KaTeX_Main-Regular.woff2)" in css and "http" not in css  # every font is local
