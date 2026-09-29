"""The proof map page's home (PR #107's instrument panel), run for real under node (issue #112).

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
PENDING = [
    {"kind": "acceptance", "node_id": "lem_bound", "statement": "The partial sums are bounded", "decisions": ["accept", "reject"],
     "candidate_proof": {"id": "cp-v1", "version": 1, "sha256": "a" * 64, "text": "Direct."}, "bindings": {"accept": "b" * 64, "reject": "c" * 64}},
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
    ("CHALLENGED", {"acceptance_state": "accepted", "integrity_state": "challenged"}),
    ("STALE", {"integrity_state": "potentially-stale"}),
    ("UNVERIFIABLE", {"acceptance_state": "unverifiable"}),
])
def test_a_frontier_node_on_the_canvas_keeps_its_frontier_marker_beside_its_warning(warning, axes):
    """Accepted and Challenged (or stale, or unverifiable), yet on the frontier: the warning must not replace the frontier."""
    (shown,) = _home(map_={"nodes": [_node("lem_w", frontier=True, **axes), _node("lem_plain", frontier=True)]})
    node = shown["dag"]["lem_w"]
    assert "frontier" in node["classes"]
    tags = {t["text"]: t["classes"] for t in node["tags"]}
    assert "accent" in tags["FRONTIER"] and "warn" in tags[warning]
    assert "on the frontier" in node["label"]
    # a plain frontier node says it once
    assert [t["text"] for t in shown["dag"]["lem_plain"]["tags"]] == ["FRONTIER"]


def test_a_frontier_node_in_the_tree_keeps_its_frontier_chip_beside_its_warning():
    chain = {"nodes": [_node("thm", "theorem", "Top", ["lem_ch"]), ACCEPTED_CHALLENGED_FRONTIER]}
    *_, tree = _home(map_=chain, steps=[{"view": "tree"}])
    (line,) = [line for line in tree["tree"] if line["id"] == "lem_ch"]
    assert "frontier" in line["chips"] and "challenged" in line["chips"]


def test_the_frontier_border_is_never_overridden_by_a_warning_border():
    css = (STATIC / "app.css").read_text()
    last_frontier = css.rindex("#dag-svg .node.frontier .box")
    for warning in ("challenged", "stale", "unverifiable"):
        assert last_frontier > css.index(f"#dag-svg .node.{warning} .box")  # the later rule of the same weight wins


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
    assert shown["caption"].startswith("3 node(s) · 1 on the frontier")


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
    assert abs(y - (44 + 600) / 2) < 1  # the middle of what the map bar leaves showing
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


def test_the_search_box_sits_on_the_map_bar_in_the_panels_style():
    html = (STATIC / "index.html").read_text()
    head = html[html.index('<div class="maphead">'):html.index('<div id="map-dag"')]
    assert 'id="map-find"' in head and 'type="search"' in head and 'id="map-find-count"' in head
    count = head[head.rindex("<", 0, head.index('id="map-find-count"')):]
    assert 'aria-live="polite"' in count[:count.index(">")]
    css = (STATIC / "app.css").read_text()
    assert "#dag-svg .node.dim" in css and "#map-tree li.dim" in css
    rule = css[css.index(".find {"):]
    assert "clip-path: polygon(" in rule[:rule.index("}")]  # chamfered like the panel's other controls


def test_the_map_bar_wraps_at_phone_width_rather_than_scrolling_sideways():
    css = (STATIC / "app.css").read_text()
    phone = css[css.index("@media (max-width: 720px)"):]
    assert ".maphead" in phone and "flex-wrap: wrap" in phone
    find = phone[phone.index(".find {"):]
    assert "min-width: 0" in find[:find.index("}")]
    box = phone[phone.index(".find input"):]
    assert "width: 100%" in box[:box.index("}")]
