"""The proof map page's home (PR #107's instrument panel), run for real under node (issue #112).

The frontier is its own, strongest signal (ADR-0008): a warning is shown beside it, never in
its place. Tree lines name their node and how many parents share it in data attributes.
"""

import json
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
