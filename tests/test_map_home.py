"""The proof map page's home (PR #107, redesigned in Apple's design language), run for real under node (issue #112).

A review card shows its snapshot's 核心思路 and 难点, and a map node's hover its 核心思路 (ADR-0013).

The frontier is its own, strongest signal (ADR-0008): a warning is shown beside it, never in
its place. Tree lines name their node and how many parents share it in data attributes.
The search box picks nodes out on the canvas and the tree (issue #116).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "proof_cli" / "webapp" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "map_home_harness.js"


def _node(node_id, kind="lemma", statement="", dependencies=(), **axes):
    return {
        "id": node_id, "kind": kind, "statement": statement or node_id, "display_label": None, "dependencies": list(dependencies),
        "acceptance_state": "unreviewed", "workflow_state": "open", "integrity_state": "current", "assignee": None, "frontier": False, **axes,
    }


MAP = {"nodes": [
    _node("thm_main", "theorem", "Every bounded sequence has a convergent subsequence", ["lem_bound", "ref_bw"]),
    _node("lem_bound", "lemma", "The partial sums are bounded", frontier=True),
    _node("ref_bw", "imported_result", "Bolzano-Weierstrass"),
]}
SUMMARY = {"text": "", "drafted_by": None, "fields": {
    "core_idea": "CORE: each partial sum is at most $\\sum 2^{-n}$", "main_steps": "STEPS: 1. compare termwise",
    "difficulties": "HARD: the comparison needs $a_n \\ge 0$", "not_covered": "OPEN: 无"}}
PENDING = [
    {"kind": "acceptance", "node_id": "lem_bound", "statement": "The partial sums are bounded", "decisions": ["accept", "reject"],
     "candidate_proof": {"id": "cp-v1", "version": 1, "sha256": "a" * 64, "text": "Direct.", "key_ideas": SUMMARY},
     "bindings": {"accept": "b" * 64, "reject": "c" * 64}},
    {"kind": "reference_review", "node_id": "ref_bw", "statement": "Bolzano-Weierstrass", "decisions": ["reference-review"], "candidate_proof": None, "bindings": {}},
]


def _state(pending=(), warnings=()):
    return {"project_id": "p", "reviewer": "Researcher <r@example.org>", "pending": list(pending), "warnings": list(warnings)}


def _home(state=None, steps=(), map_=None, nodes=None):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    scenario = {"state": state or _state(PENDING), "map": map_ or MAP, "steps": list(steps), "nodes": nodes or {}}
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# -- the frontier is its own signal (ADR-0008) -------------------------------------------

ACCEPTED_CHALLENGED_FRONTIER = _node("lem_ch", "lemma", "Challenged but claimable", acceptance_state="accepted", integrity_state="challenged", frontier=True)


@pytest.mark.parametrize("warning, axes", [
    ("Challenged", {"acceptance_state": "accepted", "integrity_state": "challenged"}),
    ("Dependency changed", {"integrity_state": "potentially-stale"}),
    ("Decision outdated", {"acceptance_state": "unverifiable"}),
])
def test_a_frontier_node_on_the_canvas_keeps_its_frontier_marker_beside_its_warning(warning, axes):
    """Accepted and Challenged (or stale, or unverifiable), yet on the frontier: the warning must not replace the frontier."""
    (shown,) = _home(map_={"nodes": [_node("lem_w", frontier=True, **axes), _node("lem_plain", frontier=True)]})
    node = shown["dag"]["lem_w"]
    assert "frontier" in node["classes"] and "state-attention" in node["classes"]
    # the warning's badge and the frontier's own, side by side; the word names the warning
    assert node["icons"] == ["attention", "ready"]
    assert [t["text"] for t in node["tags"]] == [warning]
    assert "on the frontier" in node["label"]
    # a plain frontier node says it once
    plain = shown["dag"]["lem_plain"]
    assert plain["icons"] == ["ready"] and [t["text"] for t in plain["tags"]] == ["Ready"]


def test_a_frontier_node_in_the_tree_keeps_its_frontier_chip_beside_its_warning():
    chain = {"nodes": [_node("thm", "theorem", "Top", ["lem_ch"]), ACCEPTED_CHALLENGED_FRONTIER]}
    *_, tree = _home(map_=chain, steps=[{"view": "tree"}])
    (line,) = [line for line in tree["tree"] if line["id"] == "lem_ch"]
    assert "frontier" in line["chips"] and "challenged" in line["chips"]


def test_the_frontier_border_is_never_overridden_by_a_state_border():
    """Every state tints its card's edge; the frontier's blue edge comes after them all, so it wins."""
    css = (STATIC / "app.css").read_text()
    last_frontier = css.rindex("#dag-svg .node.frontier .box")
    for state_rule in ('#dag-svg .node[class*="state-"] .box', "#dag-svg .node.state-open .box"):
        assert last_frontier > css.rindex(state_rule)  # the later rule wins


# -- the tree's data attributes ----------------------------------------------------------


def test_each_tree_line_names_its_node_and_how_many_parents_share_it():
    diamond = {"nodes": [_node("thm", "theorem", "Top", ["a", "b"]), _node("a", dependencies=["base"]), _node("b", dependencies=["base"]), _node("base")]}
    *_, tree = _home(map_=diamond, steps=[{"view": "tree"}])
    assert [(line["id"], line["sharedBy"]) for line in tree["tree"]] == [("thm", None), ("a", None), ("base", "2"), ("b", None), ("base", "2")]
    assert [line["children"] for line in tree["tree"]] == [["a", "b"], ["base"], [], ["base"], []]
    assert "shared" in tree["tree"][2]["chips"]


def test_a_missing_dependency_still_names_its_node():
    dangling = {"nodes": [_node("thm", "theorem", "Top", ["ghost"])]}
    *_, tree = _home(map_=dangling, steps=[{"view": "tree"}])
    assert [line["id"] for line in tree["tree"]] == ["thm", "ghost"]


def test_the_tree_can_be_rooted_at_any_node():
    *_, rooted = _home(steps=[{"view": "tree"}, {"root": "lem_bound"}])
    assert [line["id"] for line in rooted["tree"]] == ["lem_bound"]


# -- the map's caption -------------------------------------------------------------------


def test_the_caption_counts_the_nodes_and_the_frontier():
    (shown,) = _home()
    assert shown["caption"].startswith("3 nodes · 1 on the frontier")


# -- Awaiting review ---------------------------------------------------------------------


def test_recording_with_nothing_ticked_records_nothing():
    first, pressed = _home(steps=[{"record": True}])
    assert pressed["message"] == "Tick at least one decision."
    assert not pressed["confirmShown"] and not [p for p in pressed["posted"] if p["url"] == "/api/decide"]


def test_a_ticked_decision_carries_the_snapshot_and_binding_it_was_made_on():
    *_, recorded = _home(steps=[{"tick": "lem_bound"}, {"choose": "lem_bound", "value": "reject"}, {"record": True}])
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    (decision,) = sent["body"]["decisions"]
    assert decision == {"kind": "acceptance", "target_id": "lem_bound", "decision": "reject", "rationale": "",
                        "viewed_candidate_proof_sha256": "a" * 64, "binding": "c" * 64}


def test_empty_review_and_warnings_sections_say_so():
    (empty,) = _home(state=_state())
    assert empty["pendingRows"] == ["Nothing is awaiting review."] and empty["pendingCount"] == "0"
    assert empty["warnings"] == ["None."]
    warning = {"code": "STALE", "message": "a dependency moved", "details": {"node_id": "thm_main"}}
    (full,) = _home(state=_state(PENDING, [warning]))
    assert len(full["pendingRows"]) == 2 and full["pendingCount"] == "2"
    assert full["warnings"] == ["STALE a dependency moved"]


# -- the linked citation (issue #91) -----------------------------------------------------

CITATION = {"reference_id": "rudin", "missing": False, "title": "Principles of Mathematical Analysis", "authors": ["Walter Rudin"],
            "year": 1976, "identifier": "isbn:0-07-054235-X", "url": "", "locator": "Theorem 3.6", "version": "3rd edition"}
MISSING = {**CITATION, "missing": True, "title": None, "authors": [], "year": None, "identifier": None, "url": None}


def _imported_page(citation):
    return {"node": {"id": "ref_bw", "kind": "imported_result", "statement": "Bolzano-Weierstrass", "assumptions": [], "reference_id": "rudin" if citation else None},
            "workflow_state": "open", "acceptance_state": "unreviewed", "integrity_state": "current", "claim": None, "studio": None, "folder": None,
            "source": {"locator": "Theorem 3.6", "version": "3rd edition", "trust_level": None}, "citation": citation,
            "dependents": [], "pdfs": {}, "dependencies": [], "challenges": [], "candidate_proof": None, "evidence_checks": [],
            "decisions": [], "history": [], "warnings": []}


def _open(citation):
    """The home with the imported result's review card, then its own page."""
    cards = [{**PENDING[0], "citation": None}, {**PENDING[1], "citation": citation}]
    return _home(state=_state(cards), steps=[{"open": "ref_bw"}], nodes={"ref_bw": _imported_page(citation)})


def test_the_review_card_shows_the_linked_citation():
    home, _ = _open(CITATION)
    card = home["pendingCitations"][1]
    for text in ("Principles of Mathematical Analysis", "Walter Rudin", "Theorem 3.6", "3rd edition", "rudin"):
        assert text in card
    assert home["pendingCitations"][0] == ""  # a local node's card cites nothing
    assert home["pendingCitationMissing"] == [False, False]


def test_the_imported_results_page_shows_the_linked_citation():
    _, page = _open(CITATION)
    assert page["nodePageShown"]
    for text in ("Principles of Mathematical Analysis", "Walter Rudin", "1976", "Theorem 3.6", "3rd edition", "rudin"):
        assert text in page["nodeSource"]
    assert page["nodeSourceWarnings"] == []


def test_a_missing_citation_is_marked_on_the_page_and_the_card():
    home, page = _open(MISSING)
    assert home["pendingCitationMissing"] == [False, True] and "citation missing" in home["pendingCitations"][1]
    (warning,) = page["nodeSourceWarnings"]
    assert "citation missing" in warning and "rudin" in warning


def test_an_imported_result_without_a_link_shows_its_source_as_before():
    home, page = _open(None)
    assert home["pendingCitations"] == ["", ""]
    assert "Theorem 3.6 · 3rd edition" in page["nodeSource"] and "Citation" not in page["nodeSource"]


# -- the search box (issue #116) ---------------------------------------------------------

LABELLED = {"nodes": [*MAP["nodes"][:2], {**MAP["nodes"][2], "display_label": "Compactness on the line"}]}
NUMBER = r"(-?[\d.]+(?:e-?\d+)?)"


def _dims(reading):
    return {node_id: "dim" in node["classes"] for node_id, node in reading["dag"].items()}


def _centre(reading, node_id):
    """Where a node's centre lands on the canvas: the scene's translate and scale applied to the node's own translate."""
    tx, ty, k = map(float, re.fullmatch(rf"translate\({NUMBER},{NUMBER}\) scale\({NUMBER}\)", reading["scene"]).groups())
    x, y = map(float, re.fullmatch(rf"translate\({NUMBER},{NUMBER}\)", reading["at"][node_id]).groups())
    return tx + x * k, ty + y * k, k


@pytest.mark.parametrize("query, matched", [
    ("LEM_BOUND", {"lem_bound"}),                        # by id, whatever the case
    ("partial sums", {"lem_bound"}),                     # by statement
    ("compactness", {"ref_bw"}),                         # by label
    ("b", {"thm_main", "lem_bound", "ref_bw"}),
])
def test_the_search_box_dims_every_node_on_the_canvas_it_does_not_match(query, matched):
    first, found = _home(map_=LABELLED, steps=[{"find": query}])
    assert not any(_dims(first).values()) and first["find"]["count"] == "" and not first["filtering"]
    assert {node_id for node_id, dim in _dims(found).items() if not dim} == matched
    assert found["filtering"]
    assert found["find"]["count"].startswith(f"{len(matched)} of 3 match")


def test_the_search_box_dims_the_tree_too():
    *_, tree = _home(steps=[{"view": "tree"}, {"find": "bolzano"}])
    assert [(line["id"], line["dim"]) for line in tree["tree"]] == [("thm_main", True), ("lem_bound", True), ("ref_bw", False)]
    assert tree["find"]["count"].startswith("1 of 3 match")
    # the search stays on across a switch of view
    *_, back = _home(steps=[{"find": "bolzano"}, {"view": "tree"}, {"view": "dag"}])
    assert _dims(back) == {"thm_main": True, "lem_bound": True, "ref_bw": False}


def test_the_search_box_says_when_nothing_matches():
    *_, nothing = _home(steps=[{"find": "hilbert"}])
    assert all(_dims(nothing).values())
    assert nothing["find"]["count"].startswith("0 of 3 match") and "No node" in nothing["find"]["count"]


def test_escape_clears_the_search():
    *_, found, cleared = _home(steps=[{"view": "tree"}, {"find": "bound"}, {"key": "Escape"}])
    assert any(line["dim"] for line in found["tree"])
    assert cleared["find"]["value"] == "" and cleared["find"]["count"] == ""
    assert not any(line["dim"] for line in cleared["tree"])
    *_, dag = _home(steps=[{"find": "bound"}, {"key": "Escape"}])
    assert not any(_dims(dag).values()) and not dag["filtering"]


def test_enter_first_brings_the_first_match_into_view_then_opens_it():
    first, typed, shown, opened = _home(steps=[{"find": "partial"}, {"key": "Enter"}, {"key": "Enter"}])
    # the first Enter pans (and zooms, to at least life size) so the match sits in the middle of the canvas
    x, y, k = _centre(shown, "lem_bound")
    assert abs(x - 400) < 1 and k >= 1
    assert abs(y - 600 / 2) < 1  # the middle of the canvas: the toolbar sits above it, not over it
    assert shown["scene"] != typed["scene"] and shown["href"] == ""
    assert "Enter again" in shown["find"]["count"]
    # the second opens its page: a lemma in its studio
    assert opened["href"] == "/studio/lem_bound/"


def test_enter_opens_an_imported_result_on_its_own_page():
    *_, opened = _home(steps=[{"find": "bolzano"}, {"key": "Enter"}, {"key": "Enter"}])
    assert opened["href"] == "#/node/ref_bw"


def test_a_changed_search_starts_again_from_bringing_the_match_into_view():
    *_, shown = _home(steps=[{"find": "partial"}, {"key": "Enter"}, {"find": "bolzano"}, {"key": "Enter"}])
    assert shown["href"] == ""
    x, _, _ = _centre(shown, "ref_bw")
    assert abs(x - 400) < 1


def test_enter_with_nothing_matched_does_nothing():
    *_, pressed = _home(steps=[{"find": "hilbert"}, {"key": "Enter"}, {"key": "Enter"}])
    assert pressed["href"] == ""


def test_slash_focuses_the_search_box_and_f_still_fits_the_map():
    first, slash = _home(steps=[{"key": "/"}])
    assert not first["find"]["focused"] and slash["find"]["focused"]
    # typed inside the box, "f" is just a character: the map is not refitted under the researcher
    *_, shown, typed_f = _home(steps=[{"find": "partial"}, {"key": "Enter"}, {"key": "f"}])
    assert typed_f["scene"] == shown["scene"]
    # outside the box, F still fits the whole map
    fitted, *_, refitted = _home(steps=[{"find": "partial"}, {"key": "Enter"}, {"blur": True}, {"key": "f"}])
    assert refitted["scene"] == fitted["scene"]


def test_the_search_box_sits_in_the_toolbar_as_a_rounded_search_field():
    html = (STATIC / "index.html").read_text()
    head = html[html.index('<header class="toolbar">'):html.index("</header>")]
    assert 'id="map-find"' in head and 'type="search"' in head and 'id="map-find-count"' in head
    count = head[head.rindex("<", 0, head.index('id="map-find-count"')):]
    assert 'aria-live="polite"' in count[:count.index(">")]
    css = (STATIC / "app.css").read_text()
    assert "#dag-svg .node.dim" in css and "#map-tree li.dim" in css
    rule = css[css.index(".find {"):]
    assert "border-radius" in rule[:rule.index("}")]  # rounded like the toolbar's other controls
    assert 'body:not([data-page="map"]) .find' in css  # the map's own control: shown on the map only


def test_the_toolbar_wraps_at_phone_width_rather_than_scrolling_sideways():
    css = (STATIC / "app.css").read_text()
    phone = css[css.index("@media (max-width: 760px)"):]
    toolbar = phone[phone.index(".toolbar {"):]
    assert "flex-wrap: wrap" in toolbar[:toolbar.index("}")]
    find = phone[phone.index(".find {"):]
    assert "min-width: 0" in find[:find.index("}")]
    box = phone[phone.index(".find input"):]
    assert "width: 100%" in box[:box.index("}")]


# -- the key ideas on the review card and the map (ADR-0013) ------------------------------


def test_a_review_card_shows_the_core_idea_and_the_difficulties_not_the_latex():
    (shown,) = _home()
    card = shown["pendingKeyIdeas"][0]
    # the maths is typeset by KaTeX (ADR-0013): the harness's KaTeX parses it and marks what it rendered
    assert "核心思路" in card and "CORE: each partial sum is at most [katex: \\sum 2^{-n}]" in card
    assert "难点" in card and "HARD: the comparison needs [katex: a_n \\ge 0]" in card
    assert "STEPS" not in card and "OPEN" not in card  # the whole summary is in the studio's review view
    assert "Direct." not in shown["pendingRows"][0]  # the snapshot's LaTeX isn't pasted on the card
    assert shown["pendingKeyIdeas"][1] == ""  # an imported result's card has no summary


def test_a_review_card_of_an_old_snapshot_says_it_has_no_summary():
    old = {**PENDING[0], "candidate_proof": {**PENDING[0]["candidate_proof"], "key_ideas": None}}
    (shown,) = _home(state=_state([old]))
    assert "这个 snapshot 没有关键思路摘要" in shown["pendingRows"][0]
    assert "Direct." not in shown["pendingRows"][0]


def test_hovering_a_map_node_shows_its_core_idea_and_nothing_else_of_the_summary():
    with_idea = {"nodes": [_node("lem_bound", "lemma", "The partial sums are bounded", core_idea="CORE: compare with a geometric series"),
                           _node("lem_open", "lemma", "Not yet reviewed", core_idea=None)]}
    (shown,) = _home(map_=with_idea)
    hover = shown["dag"]["lem_bound"]["title"]
    assert "核心思路" in hover and "CORE: compare with a geometric series" in hover
    assert "难点" not in hover and "主要步骤" not in hover
    assert shown["dag"]["lem_open"]["title"] == "Not yet reviewed"  # no summary yet: the statement, as before


def _card_with(core):
    item = {**PENDING[0], "candidate_proof": {**PENDING[0]["candidate_proof"], "key_ideas": {**SUMMARY, "fields": {**SUMMARY["fields"], "core_idea": core}}}}
    (shown,) = _home(state=_state([item]))
    return shown


def test_a_review_cards_maths_is_rendered_inline_and_on_display():
    shown = _card_with("Inline $x^2$ and shown $$\\int_0^1 f$$ too.")
    assert {"tex": "x^2", "displayMode": False} in shown["katex"] and {"tex": "\\int_0^1 f", "displayMode": True} in shown["katex"]
    assert {"class": "math", "text": "[katex: x^2]"} in shown["pendingMath"][0]
    assert {"class": "math display", "text": "[katex display: \\int_0^1 f]"} in shown["pendingMath"][0]


def test_a_malformed_formula_on_a_review_card_shows_as_the_text_it_was_written_as():
    shown = _card_with("Broken $\\frac{1}{$ here, fine $y$.")
    maths = shown["pendingMath"][0]
    assert {"class": "math unrendered", "text": "$\\frac{1}{$"} in maths
    assert {"class": "math", "text": "[katex: y]"} in maths  # the rest still renders
    assert "Broken $\\frac{1}{$ here" in shown["pendingKeyIdeas"][0]


def test_the_map_page_loads_the_vendored_katex_and_serves_only_it_from_the_studio():
    from proof_cli.webapp.server import shared_asset

    html = (STATIC / "index.html").read_text()
    for src in ("/static/shared/vendor/katex.min.css", "/static/shared/vendor/katex.min.js", "/static/shared/mathtext.js"):
        assert src in html, src
    assert html.index("katex.min.js") < html.index("mathtext.js") < html.index("/static/app.js")
    assert "http" not in html.split("<body")[0].replace("http-equiv", "")  # nothing from the network
    assert shared_asset("vendor/katex.min.js") and shared_asset("vendor/fonts/KaTeX_Main-Regular.woff2")
    for refused in ("app.js", "vendor/codemirror.js", "../studio/server.py", "vendor/fonts/../../server.py", "mathtext.js/../app.js"):
        assert shared_asset(refused) is None, refused


# -- the warnings page (the Apple redesign) ------------------------------------------------


def test_the_warnings_page_lists_the_nodes_that_need_attention_and_the_sidebar_counts_them():
    nodes = {"nodes": [_node("lem_ch", "lemma", "Challenged one", integrity_state="challenged"),
                       _node("lem_st", "lemma", "Stale one", integrity_state="potentially-stale"),
                       _node("lem_ok", "lemma", "Fine one")]}
    warning = {"code": "UNCONFIRMED", "message": "a decision git doesn't have", "details": {}}
    (shown,) = _home(state=_state([], [warning]), map_=nodes)
    assert len(shown["attention"]) == 2
    assert "Challenged one" in shown["attention"][0] and "A Challenge is open" in shown["attention"][0]
    assert "Stale one" in shown["attention"][1] and "A dependency moved" in shown["attention"][1]
    assert shown["railWarnings"] == "3"  # two nodes and one review record
    (quiet,) = _home(state=_state(), map_={"nodes": [_node("lem_ok")]})
    assert quiet["attention"] == ["Nothing on the map needs attention."] and quiet["railWarnings"] == ""


# -- each Evidence check names the Review snapshot it checked (issue #122) -------------------

SHA_V1, SHA_V2 = "1" * 8 + "e" * 56, "2" * 8 + "f" * 56


def _check(check_id, proof_id, version, sha256, *, current, unreadable=False, outcome="passed"):
    return {"id": check_id, "candidate_proof_id": proof_id, "outcome": outcome, "notes": "", "run_by": "lean",
            "snapshot": {"id": proof_id, "version": version, "sha256": sha256, "current": current, "unreadable": unreadable,
                         "location": f"proofs/lem_bound/snapshots/v{version}/"}}


def _local_page(checks):
    return {"node": {"id": "lem_bound", "kind": "lemma", "statement": "The partial sums are bounded", "assumptions": []},
            "workflow_state": "review-needed", "acceptance_state": "unreviewed", "integrity_state": "current", "claim": None,
            "studio": "/studio/lem_bound/", "folder": "/p/proofs/lem_bound", "source": None, "citation": None,
            "dependents": [], "pdfs": {}, "dependencies": [], "challenges": [],
            "candidate_proof": {"id": "cp-v2", "version": 2, "sha256": SHA_V2, "text": "Direct.", "files": {"proof.tex": "Direct."}, "unreadable": False},
            "evidence_checks": checks, "decisions": [], "history": [], "warnings": []}


def _evidence(checks):
    _, page = _home(steps=[{"open": "lem_bound"}], nodes={"lem_bound": _local_page(checks)})
    assert page["nodePageShown"]
    return page["nodeEvidence"]


def test_each_evidence_check_shows_the_version_and_hash_of_the_snapshot_it_checked():
    on_current, on_older = _evidence([
        _check("ev-2", "cp-v2", 2, SHA_V2, current=True),
        _check("ev-1", "cp-v1", 1, SHA_V1, current=False, outcome="failed"),
    ])
    assert "v2" in on_current["text"] and SHA_V2[:12] in on_current["text"] and SHA_V2 not in on_current["text"]
    assert any(SHA_V2 in title for title in on_current["titles"])  # the full hash on hover
    assert "older" not in on_current["text"] and on_current["warnings"] == []
    # a check on an older snapshot says so, and where that frozen snapshot is
    assert "v1" in on_older["text"] and SHA_V1[:12] in on_older["text"]
    assert on_older["warnings"] == ["for an older version v1"]
    assert "proofs/lem_bound/snapshots/v1/" in on_older["text"]


def test_an_evidence_check_on_an_unreadable_snapshot_is_marked_and_the_page_still_shows():
    (shown,) = _evidence([_check("ev-1", "cp-v1", 1, SHA_V1, current=False, unreadable=True)])
    assert "v1" in shown["text"] and SHA_V1[:12] in shown["text"]
    assert shown["warnings"] == ["for an older version v1", "snapshot unreadable"]


def test_an_evidence_check_without_a_snapshot_record_still_shows():
    """A check listed without its snapshot (an older server's view) reads as before, and never throws."""
    (shown,) = _evidence([{"id": "ev-1", "candidate_proof_id": "cp-v1", "outcome": "passed", "notes": "", "run_by": "lean"}])
    assert "passed" in shown["text"] and "cp-v1" in shown["text"]


def test_an_evidence_check_whose_snapshot_changed_since_it_is_flagged_and_an_unbound_one_says_so():
    changed = {**_check("ev-2", "cp-v2", 2, SHA_V2, current=True), "binding": {"sha256": SHA_V1, "state": "changed", "label": "snapshot changed since this check"}}
    unbound = {**_check("ev-3", "cp-v2", 2, SHA_V2, current=True), "binding": {"sha256": None, "state": "unbound", "label": "not bound (recorded before binding)"}}
    matches = {**_check("ev-4", "cp-v2", 2, SHA_V2, current=True), "binding": {"sha256": SHA_V2, "state": "matches", "label": f"bound to {SHA_V2[:12]}…"}}
    shown_changed, shown_unbound, shown_matches = _evidence([changed, unbound, matches])
    assert shown_changed["warnings"] == ["snapshot changed since this check"] and SHA_V1[:12] in shown_changed["text"]
    assert "not bound (recorded before binding)" in shown_unbound["text"] and shown_unbound["warnings"] == []
    assert shown_matches["warnings"] == [] and "changed" not in shown_matches["text"]


# -- Trusted by rule (ADR-0014): the review page's own section, the rules sheet, the chips ------------

TRUSTED = [{"node_id": "ref_bw", "statement": "Bolzano-Weierstrass", "citation": CITATION, "trust_rule": ["textbooks"],
            "rationale": "matched trust rule textbooks; reviewed explicitly", "decisions": ["reference-review", "no-longer-callable"],
            "bindings": {"reference-review": "d" * 64, "no-longer-callable": "e" * 64}}]
RULE = {"name": "textbooks", "rationale": "standard textbooks", "retired": False, "declared_by": "Researcher <r@example.org>", "declared_at": "2026-09-30T10:00:00+00:00",
        "changed_by": "Researcher <r@example.org>", "changed_at": "2026-09-30T10:00:00+00:00", "conditions": [{"kind": "source_type_in", "values": ["textbook", "monograph"]}],
        "conditions_text": ["source_type in {textbook, monograph}"], "trusting": ["ref_bw"], "history": [{"decision": "declare"}]}
RULES = {"rules": [RULE, {**RULE, "name": "old", "retired": True, "trusting": [], "history": [{"decision": "declare"}, {"decision": "retire"}]}],
         "source_types": ["standard_reference", "research_paper", "textbook", "survey", "monograph", "website", "other"], "weak_source_types": ["website", "other"]}


def _trusted_state(trusted=TRUSTED):
    return {**_state([PENDING[0]]), "trusted_by_rule": list(trusted)}


def test_trusted_by_rule_nodes_are_listed_apart_and_never_counted_as_awaiting():
    (shown,) = _home(state=_trusted_state())
    assert shown["pendingCount"] == "1" and len(shown["pendingRows"]) == 1  # the local node awaiting review, only
    (trusted,) = shown["trustedRows"]
    assert "ref_bw" in trusted["text"] and "Bolzano-Weierstrass" in trusted["text"] and "Principles of Mathematical Analysis" in trusted["text"]
    assert trusted["rules"] == ["textbooks"] and trusted["rationale"] == "matched trust rule textbooks; reviewed explicitly"
    assert shown["trustedCount"] == "1"
    (empty,) = _home(state=_trusted_state([]))
    assert empty["trustedRows"][0]["text"] == "No imported result is trusted by rule." and empty["trustedCount"] == ""


def test_review_explicitly_records_the_ordinary_reference_review_with_the_prefilled_rationale():
    _, recorded = _home(state=_trusted_state(), steps=[{"reviewExplicitly": "ref_bw"}])
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    assert sent["body"] == {"decisions": [{"kind": "reference_review", "target_id": "ref_bw", "decision": "reference-review",
                                           "rationale": "matched trust rule textbooks; reviewed explicitly", "binding": "d" * 64}]}


def test_the_rules_sheet_lists_the_rules_and_records_a_declaration():
    _, opened, filled, recorded = _home(state=_trusted_state(), steps=[
        {"manage": True},
        {"rule": {"name": "arxiv", "rationale": "preprints I follow", "arxiv": True}},
        {"ruleRecord": True},
    ])
    assert opened["rulesSheetShown"]
    assert opened["ruleFormTitle"] == "Declare a rule" and not opened["ruleNameDisabled"]
    assert opened["rulesListed"] == [] and opened["ruleReminder"] == ""
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    assert sent["body"] == {"decisions": [{"kind": "trust_rule", "target_id": "arxiv", "decision": "declare", "rationale": "preprints I follow",
                                           "conditions": [{"kind": "identifier_has_arxiv"}]}]}


def _home_with_rules(steps):
    scenario = {"state": _trusted_state(), "map": MAP, "steps": list(steps), "nodes": {}, "rules": RULES,
                "preview": {"losing": ["ref_bw"], "depended_on_by_accepted": ["ref_bw"], "gaining": []}}
    if shutil.which("node") is None:
        pytest.skip("needs node")
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_sheet_shows_each_rule_with_its_conditions_and_what_it_trusts_and_the_retired_ones_apart():
    _, opened = _home_with_rules([{"manage": True}])
    (rule,) = opened["rulesListed"]
    assert rule["name"] == "textbooks" and "source_type in {textbook, monograph}" in rule["text"] and "trusting ref_bw" in rule["text"]
    assert rule["buttons"] == ["Amend", "Retire"]
    assert opened["rulesRetired"] == ["old"]


def test_a_weak_source_type_gets_a_reminder_and_a_change_shows_its_impact_before_recording():
    _, _, weak, retiring, recorded = _home_with_rules([
        {"manage": True},
        {"rule": {"name": "web", "types": ["website"]}},
        {"retire": "textbooks"},
        {"ruleRecord": True},
    ])
    assert "website" in weak["ruleReminder"] and weak["ruleImpact"] == ""  # a declaration has no impact to preview
    assert retiring["ruleFormTitle"] == "Retire textbooks" and retiring["ruleNameDisabled"] and retiring["ruleReminder"] == ""
    assert "1 node(s) would stop reading trusted by rule" in retiring["ruleImpact"] and "1 of them depended on by Accepted nodes" in retiring["ruleImpact"]
    (preview,) = [p for p in retiring["posted"] if p["url"] == "/api/trust-rules/preview"]
    assert preview["body"] == {"name": "textbooks", "decision": "retire"}
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    assert sent["body"]["decisions"] == [{"kind": "trust_rule", "target_id": "textbooks", "decision": "retire", "rationale": ""}]


def test_amending_prefills_the_rules_conditions_and_sends_the_changed_ones():
    _, _, amending, _, recorded = _home_with_rules([{"manage": True}, {"amend": "textbooks"}, {"rule": {"rationale": "tightened", "doi": True}}, {"ruleRecord": True}])
    assert amending["ruleFormTitle"] == "Amend textbooks" and amending["ruleNameDisabled"]
    (preview,) = [p for p in amending["posted"] if p["url"] == "/api/trust-rules/preview"]
    assert preview["body"] == {"name": "textbooks", "decision": "amend", "conditions": [{"kind": "source_type_in", "values": ["textbook", "monograph"]}]}
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    assert sent["body"]["decisions"] == [{"kind": "trust_rule", "target_id": "textbooks", "decision": "amend", "rationale": "tightened",
                                          "conditions": [{"kind": "identifier_has_doi"}, {"kind": "source_type_in", "values": ["textbook", "monograph"]}]}]


def test_a_trusted_by_rule_node_reads_so_on_the_canvas_the_tree_and_its_page():
    trusted_node = _node("ref_bw", "imported_result", "Bolzano-Weierstrass", acceptance_state="trusted-by-rule", trust_rule=["textbooks"])
    page = {**_imported_page(CITATION), "acceptance_state": "trusted-by-rule", "trust_rule": ["textbooks"],
            "rule_events": [{"rule": "textbooks", "at": "2026-09-30T10:00:00+00:00"}],
            "decisions": [{"kind": "reference_review", "target_id": "ref_bw", "decision": "reference-review", "binding": "d" * 64},
                          {"kind": "reference_review", "target_id": "ref_bw", "decision": "no-longer-callable", "binding": "e" * 64}]}
    shown, tree, opened = _home(map_={"nodes": [MAP["nodes"][0], MAP["nodes"][1], trusted_node]}, steps=[{"view": "tree"}, {"open": "ref_bw"}], nodes={"ref_bw": page})
    card = shown["dag"]["ref_bw"]
    assert "state-accepted" in card["classes"] and card["tags"] == [{"text": "Trusted by rule", "classes": ["tag"]}] and card["icons"] == ["accepted"]
    assert card["title"].endswith("trusted by rule textbooks") and "trusted by rule textbooks" in card["label"]  # the names, a hover away
    (line,) = [li for li in tree["tree"] if li["id"] == "ref_bw"]
    assert line["chips"][0] == "trusted by rule textbooks"
    assert opened["nodeAxes"][1] == "trusted by rule textbooks" and "state-accepted" in opened["nodeAxisClasses"][1]  # the accepted family, named
    assert opened["nodeHistory"] == ["2026-09-30T10:00:00+00:00 · trusted by rule textbooks since then — no decision written; the rule's declaration is the record"]
    assert opened["nodeDecisionRationales"] == ["matched trust rule textbooks; reviewed explicitly", ""]


def _home_rules(steps, **scenario):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    full = {"state": _trusted_state(), "map": MAP, "steps": list(steps), "nodes": {}, "rules": RULES,
            "preview": {"losing": ["ref_bw"], "depended_on_by_accepted": ["ref_bw"], "gaining": []}, **scenario}
    done = subprocess.run(["node", str(HARNESS), json.dumps(full)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_change_is_recorded_only_against_the_impact_of_the_form_as_it_stands():
    """A preview answering an earlier state of the form is dropped; Record waits for the current one and stays off if it failed."""
    *_, ordered, recorded = _home_rules([{"manage": True}, {"retire": "textbooks"}, {"amend": "textbooks"}, {"ruleRecord": True}], previewOutOfOrder=True)
    assert "stale-answer" not in ordered["ruleImpact"] and "1 node(s) would stop" in ordered["ruleImpact"]
    assert not ordered["ruleRecordDisabled"]
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    assert sent["body"]["decisions"][0]["decision"] == "amend"

    *_, failed, pressed = _home_rules([{"manage": True}, {"retire": "textbooks"}, {"ruleRecord": True}], previewFails=True)
    assert failed["ruleRecordDisabled"] and "TRUST_RULE_NOT_FOUND" in failed["ruleImpact"] and "nothing can be recorded" in failed["ruleImpact"]
    assert not [p for p in pressed["posted"] if p["url"] == "/api/decide"]

    _, declaring = _home_rules([{"manage": True}])
    assert not declaring["ruleRecordDisabled"]  # a declaration has no impact to wait for


# -- the fog drawer (issue #137, ADR-0008): the toolbar badge, the drawer over the canvas, the rows ------

def _fog(fog_id, text, near=(), status="open", experiments=(), **extra):
    experiments = list(experiments)
    return {"id": fog_id, "text": text, "notes": "", "near": list(near), "status": status, "reason": None, "dropped_by": None, "dropped_at": None,
            "node_id": None, "created_by": "human", "created_at": "2026-09-28T10:12:00+00:00", "updated_at": "2026-09-28T10:12:00+00:00",
            "experiments": list(reversed(experiments)), "experiment_count": len(experiments), "latest_experiment": experiments[-1] if experiments else None,
            "folder": f"proofs/fog/{fog_id}", "folder_exists": False, **extra}


def _experiment(fog_id, seq, outcome, summary, run_by="agent_a", path=None):
    return {"fog_id": fog_id, "seq": seq, "outcome": outcome, "summary": summary, "run_by": run_by, "recorded_at": "2026-09-29T21:40:00+00:00", "path": path, "missing": False}


FOG = {"items": [
    _fog("fog-1", "the constant in lem_bound is probably optimal", ["lem_bound"],
         experiments=[_experiment("fog-1", 1, "supports", "n ≤ 10⁶ checked, the ratio tends to 1", path="proofs/lem_bound/scratch/constant.py")]),
    _fog("fog-2", "is there a variational characterisation?"),
]}
FOG_ALL = {"items": FOG["items"] + [
    _fog("fog-3", "brute-force the generating function", ["lem_bound"], status="dropped", reason="the coefficients grow too fast", dropped_by="human", dropped_at="2026-09-29T09:03:00+00:00"),
    _fog("fog-4", "the dependence on epsilon may be polynomial", ["thm_main"], status="crystallized", node_id="eps_poly"),
]}


def _fog_home(steps=(), fog=FOG, fog_all=FOG_ALL, nodes=None):
    return _home_rules(steps, state=_state(PENDING), nodes=nodes or {}, fog=fog, fogAll=fog_all)


def test_the_toolbar_badge_counts_the_open_fog_and_opens_the_drawer_listing_each_item():
    closed, opened = _fog_home(steps=[{"fog": True}])
    assert closed["fogBadge"] == "2" and not closed["fogDrawerShown"]
    assert opened["fogDrawerShown"] and opened["fogCount"] == "2"
    first, second = opened["fogRows"]
    assert first["id"] == "fog-1" and "the constant in lem_bound is probably optimal" in first["text"]
    assert first["near"] == ["lem_bound"] and first["exp"].startswith("supports") and "ratio tends to 1" in first["exp"]
    assert "agent_a" in first["expTitle"] and "proofs/lem_bound/scratch/constant.py" in first["expTitle"]
    assert first["actions"] == ["Crystallize…", "Record experiment…", "Drop…"]
    assert second["id"] == "fog-2" and second["near"] == [] and second["exp"] == "no experiment yet"
    assert opened["fogRows"] == [r for r in opened["fogRows"] if r["status"] is None]  # open items carry no status line


def test_hovering_a_row_marks_its_near_nodes_the_way_the_search_box_does_and_draws_nothing():
    _, _, hovered, left = _fog_home(steps=[{"fog": True}, {"fogHover": "fog-1"}, {"fogLeave": "fog-1"}])
    assert hovered["fogFocus"]  # the canvas filters, as for a search
    assert "found" in hovered["dag"]["lem_bound"]["classes"] and "dim" not in hovered["dag"]["lem_bound"]["classes"]
    assert "dim" in hovered["dag"]["thm_main"]["classes"] and "dim" in hovered["dag"]["ref_bw"]["classes"]
    assert not left["fogFocus"] and all("dim" not in n["classes"] and "found" not in n["classes"] for n in left["dag"].values())
    assert all(len(n["texts"]) == len(m["texts"]) for n, m in zip(hovered["dag"].values(), left["dag"].values()))  # nothing added to the cards


def test_hovering_a_row_marks_the_tree_too():
    hovered = _fog_home(steps=[{"view": "tree"}, {"fog": True}, {"fogHover": "fog-1"}])[-1]
    lines = {line["id"]: line for line in hovered["tree"]}
    assert not lines["lem_bound"]["dim"] and lines["thm_main"]["dim"]


def test_adding_from_the_composer_posts_the_text_and_the_near_node_and_clears_the_box():
    _, _, added = _fog_home(steps=[{"fog": True}, {"fogAdd": {"text": "maybe the bound is sharp", "near": "lem_bound"}}])
    (sent,) = [p for p in added["posted"] if p["url"] == "/api/fog"]
    assert sent["body"] == {"text": "maybe the bound is sharp", "near": ["lem_bound"]}
    assert added["fogAddText"] == "" and added["message"] == "Fog item added."


def test_adding_nothing_posts_nothing():
    _, _, added = _fog_home(steps=[{"fog": True}, {"fogAdd": {"text": "   "}}])
    assert added["posted"] == [] and added["message"] == "Say what the difficulty is."


def test_dropping_asks_for_a_reason_inline_and_posts_it():
    readings = _fog_home(steps=[
        {"fog": True}, {"fogButton": {"id": "fog-1", "text": "Drop…"}},
        {"fogButton": {"id": "fog-1", "text": "Drop"}},
        {"fogFill": {"id": "fog-1", "name": "reason", "value": "the ratio is not monotone after all"}}, {"fogButton": {"id": "fog-1", "text": "Drop"}},
    ])
    asked, refused, dropped = readings[2], readings[3], readings[5]
    (row,) = [r for r in asked["fogRows"] if r["id"] == "fog-1"]
    assert row["form"] and "Drop" in row["actions"] and "Cancel" in row["actions"]
    assert refused["posted"] == [] and refused["message"] == "A reason is required to drop a fog item."
    (sent,) = dropped["posted"]
    assert sent == {"url": "/api/fog/fog-1/drop", "body": {"reason": "the ratio is not monotone after all"}}
    assert dropped["message"] == "fog-1: dropped."


def test_recording_an_experiment_posts_its_outcome_and_summary():
    recorded = _fog_home(steps=[
        {"fog": True}, {"fogButton": {"id": "fog-2", "text": "Record experiment…"}},
        {"fogFill": {"id": "fog-2", "name": "outcome", "value": "refutes"}}, {"fogFill": {"id": "fog-2", "name": "summary", "value": "the functional has no critical point for n = 7"}},
        {"fogButton": {"id": "fog-2", "text": "Record"}},
    ])[-1]
    (sent,) = recorded["posted"]
    # who ran it is the request's to say: the page's own identity, prefilled and editable; no path unless one is given
    assert sent == {"url": "/api/fog/fog-2/experiment", "body": {"outcome": "refutes", "summary": "the functional has no critical point for n = 7", "run_by": "Researcher <r@example.org>"}}


def test_an_experiment_can_name_who_ran_it_and_where_its_files_are():
    recorded = _fog_home(steps=[
        {"fog": True}, {"fogButton": {"id": "fog-2", "text": "Record experiment…"}},
        {"fogFill": {"id": "fog-2", "name": "summary", "value": "ran out of memory"}}, {"fogFill": {"id": "fog-2", "name": "run_by", "value": "agent_a"}},
        {"fogFill": {"id": "fog-2", "name": "path", "value": "proofs/fog/fog-2/variational.sage"}}, {"fogButton": {"id": "fog-2", "text": "Record"}},
    ])[-1]
    (sent,) = recorded["posted"]
    assert sent["body"] == {"outcome": "supports", "summary": "ran out of memory", "run_by": "agent_a", "path": "proofs/fog/fog-2/variational.sage"}


def test_the_toggle_lists_dropped_and_crystallized_items_apart_and_reopens_a_dropped_one():
    _, _, everything, reopened = _fog_home(steps=[{"fog": True}, {"fogAll": True}, {"fogButton": {"id": "fog-3", "text": "Reopen"}}])
    assert [r["id"] for r in everything["fogRows"]] == ["fog-1", "fog-2", "fog-3", "fog-4"]
    assert everything["fogCount"] == "2" and everything["fogBadge"] == "2"  # the counts stay the open items
    dropped, crystallized = everything["fogRows"][2], everything["fogRows"][3]
    assert dropped["status"].startswith("dropped · human, 2026-09-29") and "the coefficients grow too fast" in dropped["status"]
    assert dropped["actions"] == ["Reopen"]
    assert crystallized["status"] == "crystallized as eps_poly" and crystallized["actions"] == []
    (sent,) = reopened["posted"]
    assert sent == {"url": "/api/fog/fog-3/reopen", "body": {}}


def test_crystallize_shows_the_cli_command_with_the_near_node_as_the_parent():
    _, _, shown = _fog_home(steps=[{"fog": True}, {"fogButton": {"id": "fog-1", "text": "Crystallize…"}}])
    (row,) = [r for r in shown["fogRows"] if r["id"] == "fog-1"]
    assert row["cli"] == 'proof fog crystallize fog-1 <node-id> "<statement>" --parent lem_bound'
    assert shown["posted"] == []
    _, _, loose = _fog_home(steps=[{"fog": True}, {"fogButton": {"id": "fog-2", "text": "Crystallize…"}}])
    (row,) = [r for r in loose["fogRows"] if r["id"] == "fog-2"]
    assert row["cli"] == 'proof fog crystallize fog-2 <node-id> "<statement>"'


def test_the_drawer_closes_from_its_button_and_the_badge_reads_the_same():
    _, opened, closed = _fog_home(steps=[{"fog": True}, {"fogClose": True}])
    assert opened["fogDrawerShown"] and not closed["fogDrawerShown"] and closed["fogBadge"] == "2"


NODE_VIEW = {
    "node": {"id": "eps_poly", "kind": "claim", "statement": "The dependence on epsilon is polynomial", "assumptions": [], "dependencies": []},
    "workflow_state": "open", "acceptance_state": "unreviewed", "integrity_state": "current", "warnings": [], "claim": None, "studio": "/studio/eps_poly/",
    "folder": "proofs/eps_poly", "source": None, "citation": None, "dependents": [], "pdfs": {}, "dependencies": [], "challenges": [], "candidate_proof": None,
    "evidence_checks": [], "decisions": [], "history": [], "crystallized_from": "fog-4",
    "fog_near": [_fog("fog-5", "does the polynomial degree depend on the dimension?", ["eps_poly"], experiments=[_experiment("fog-5", 1, "inconclusive", "degree 2 up to n = 4")])],
}


def test_the_node_page_says_which_fog_item_it_was_crystallized_from_and_lists_the_fog_near_it():
    _, opened = _fog_home(steps=[{"open": "eps_poly"}], nodes={"eps_poly": NODE_VIEW})
    assert opened["nodePageShown"]
    assert "Crystallized from fog-4" in opened["nodeFog"]
    assert "Fog near this node" in opened["nodeFog"] and "does the polynomial degree depend on the dimension?" in opened["nodeFog"]
    assert "inconclusive" in opened["nodeFog"] and opened["nodeFogLinks"] == ["fog-4", "fog-5"]
    assert opened["nodeFogHrefs"] == ["#/fog/fog-4", "#/fog/fog-5"]  # each opens the drawer at the item
    _, plain = _fog_home(steps=[{"open": "eps_poly"}], nodes={"eps_poly": {**NODE_VIEW, "crystallized_from": None, "fog_near": []}})
    assert plain["nodeFog"] == ""


def test_a_fog_link_opens_the_drawer_at_the_item_showing_the_rest_when_it_has_left_the_list():
    _, followed = _fog_home(steps=[{"hash": "#/fog/fog-4"}])
    assert followed["page"] == "map" and followed["fogDrawerShown"] and followed["fogFound"] == ["fog-4"]
    assert [r["id"] for r in followed["fogRows"]] == ["fog-1", "fog-2", "fog-3", "fog-4"]  # a crystallized item: the toggle went on
    _, plain = _fog_home(steps=[{"hash": "#/fog/fog-2"}])
    assert plain["fogFound"] == ["fog-2"] and [r["id"] for r in plain["fogRows"]] == ["fog-1", "fog-2"]


def test_the_badge_on_another_page_goes_to_the_map_with_the_drawer_open():
    _, review, back = _fog_home(steps=[{"hash": "#/review"}, {"fog": True}])
    assert review["page"] == "review" and not review["fogDrawerShown"]
    assert back["page"] == "map" and back["fogDrawerShown"]


def test_a_second_click_on_a_row_button_closes_its_form():
    _, _, shown, hidden = _fog_home(steps=[{"fog": True}, {"fogButton": {"id": "fog-1", "text": "Drop…"}}, {"fogButton": {"id": "fog-1", "text": "Drop…"}}])
    (row,) = [r for r in shown["fogRows"] if r["id"] == "fog-1"]
    assert row["form"]
    (row,) = [r for r in hidden["fogRows"] if r["id"] == "fog-1"]
    assert not row["form"]


# -- the Medium of a node (spec #145): a computation node says so on its card --------------------

def test_a_computation_nodes_card_names_its_medium_beside_its_kind():
    computation = {**_node("c_check", "claim", "For every n ≤ 10^4 the inequality holds"), "medium": "computation"}
    latex = {**_node("c_plain", "claim", "A written claim"), "medium": "latex"}
    (shown,) = _home(map_={"nodes": [computation, latex]})
    assert shown["dag"]["c_check"]["texts"][0].startswith("Claim · computation")  # the kind line, then the id
    assert shown["dag"]["c_plain"]["texts"][0].startswith("Claim ") and "computation" not in shown["dag"]["c_plain"]["texts"][0]


def test_the_node_page_lists_a_computations_frozen_outputs_and_previews_its_images():
    proof = {"id": "cp-v1", "version": 1, "sha256": "a" * 64, "text": "", "files": {"run.sh": "#!/usr/bin/env bash\n", "out/table.csv": "n,ratio\n"}, "key_ideas": None, "unreadable": False,
             "outputs": [{"path": "out/plot.png", "type": "image/png", "bytes": 70}, {"path": "out/table.csv", "type": "text/csv", "bytes": 8}]}
    view = {**NODE_VIEW, "node": {**NODE_VIEW["node"], "id": "c_check", "medium": "computation"}, "candidate_proof": proof, "crystallized_from": None, "fog_near": []}
    _, opened = _fog_home(steps=[{"open": "c_check"}], nodes={"c_check": view})
    plot, table = opened["nodeOutputs"]
    assert plot["href"] == "/api/node/c_check/snapshot/file?path=out%2Fplot.png" and plot["image"] == [plot["href"]]
    assert "image/png" in plot["text"] and table["image"] == [] and "text/csv" in table["text"]
    _, plain = _fog_home(steps=[{"open": "c_check"}], nodes={"c_check": {**view, "candidate_proof": None}})
    assert plain["nodeOutputs"] == []
