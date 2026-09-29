"""The map home page's redesign (issue #88): the find box and the Awaiting review cards, run for real under node."""

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
    return {"project_id": "p", "origin": "/tmp/p", "reviewer": "Researcher <r@example.org>", "pending": list(pending), "warnings": list(warnings)}


def _home(state=None, steps=(), map_=None):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    scenario = {"state": state or _state(PENDING), "map": map_ or MAP, "steps": list(steps)}
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# -- the find box ---------------------------------------------------------------------


def test_the_find_box_picks_out_nodes_by_id_label_or_statement():
    before, by_id, by_statement = _home(steps=[{"filter": "lem_"}, {"filter": "WEIERSTRASS"}])
    assert not before["filtering"] and before["caption"] == "3 nodes · 1 ready to claim"
    assert by_id["filtering"] and by_id["matched"] == ["lem_bound"]
    assert by_id["caption"] == "1 of 3 match · Enter opens the first"
    assert by_statement["matched"] == ["ref_bw"]  # case-insensitive, on the statement


def test_the_find_box_says_when_nothing_matches_and_escape_clears_it():
    _, none, cleared = _home(steps=[{"filter": "no such node"}, {"key": "Escape"}])
    assert none["matched"] == [] and none["caption"] == "0 of 3 match"
    assert not cleared["filtering"] and cleared["caption"] == "3 nodes · 1 ready to claim"


def test_enter_in_the_find_box_opens_the_first_match_where_it_lives():
    """A local node opens in its studio, an imported result on its own page (ADR-0011)."""
    *_, local = _home(steps=[{"filter": "bounded"}, {"key": "Enter"}])
    assert local["href"] == "/studio/thm_main/"
    *_, imported = _home(steps=[{"filter": "ref_"}, {"key": "Enter"}])
    assert imported["href"] == "#/node/ref_bw"


def test_the_tree_dims_what_the_find_box_does_not_match():
    *_, tree = _home(steps=[{"view": "tree"}, {"filter": "lem_bound"}])
    assert tree["dimmed"] == ["thm_main", "ref_bw"]


# -- the frontier is its own signal (ADR-0008) -------------------------------------------

CLAIMABLE_BUT_CHALLENGED = {"nodes": [
    _node("lem_ch", "lemma", "Challenged but claimable", acceptance_state="accepted", integrity_state="challenged", frontier=True),
    _node("lem_plain", "lemma", "Only claimable", frontier=True),
]}


def test_a_frontier_node_shows_the_frontier_and_its_warning_side_by_side_in_the_dag():
    """Accepted and Challenged, yet on the frontier: the warning must not replace 'ready to claim' (PR #93 review)."""
    (shown,) = _home(map_=CLAIMABLE_BUT_CHALLENGED)
    node = shown["dag"]["lem_ch"]
    assert {"frontier", "challenged"} <= set(node["classes"])
    assert "ready to claim" in node["texts"] and "challenged" in node["texts"]
    assert "ready to claim" in node["label"] and "challenged" in node["label"]
    assert shown["dag"]["lem_plain"]["texts"].count("ready to claim") == 1  # said once, not twice


def test_a_frontier_node_shows_the_frontier_and_its_warning_side_by_side_in_the_tree():
    chain = {"nodes": [_node("thm", "theorem", "Top", ["lem_ch"]), *CLAIMABLE_BUT_CHALLENGED["nodes"][:1]]}
    *_, tree = _home(map_=chain, steps=[{"view": "tree"}])
    assert tree["tree"]["lem_ch"] == ["ready to claim", "challenged"]


def test_the_frontier_border_is_never_overridden_by_a_warning_border():
    css = (STATIC / "app.css").read_text()
    frontier = css.index("#dag-svg .node.frontier rect.box")
    warning = css.index("#dag-svg .node.challenged rect.box")
    assert frontier > warning  # the later rule of the same weight wins: the frontier's


# -- Awaiting review --------------------------------------------------------------------


def test_the_batch_button_is_disabled_until_something_is_ticked():
    first, ticked, unticked = _home(steps=[{"tick": "lem_bound"}, {"tick": "lem_bound", "on": False}])
    assert first["batchDisabled"] and first["selected"] == "Tick the ones to record"
    assert not ticked["batchDisabled"] and ticked["selected"] == "1 selected"
    assert unticked["batchDisabled"]


def test_choosing_an_outcome_ticks_the_card_and_the_batch_carries_its_binding():
    *_, chosen, recorded = _home(steps=[{"choose": "lem_bound", "value": "reject"}, {"record": True}])
    assert not chosen["batchDisabled"] and chosen["selected"] == "1 selected"
    (sent,) = [p for p in recorded["posted"] if p["url"] == "/api/decide"]
    (decision,) = sent["body"]["decisions"]
    assert decision == {"kind": "acceptance", "target_id": "lem_bound", "decision": "reject", "rationale": "",
                        "viewed_candidate_proof_sha256": "a" * 64, "binding": "c" * 64}


def test_the_review_and_warnings_sections_show_only_when_they_have_something():
    (empty,) = _home(state=_state())
    assert empty["reviewHidden"] and empty["warningsHidden"]
    warning = {"code": "STALE", "message": "a dependency moved", "details": {"node_id": "thm_main"}}
    (full,) = _home(state=_state(PENDING, [warning]))
    assert not full["reviewHidden"] and not full["warningsHidden"] and full["pendingCount"] == "2 pending"


# -- the page itself --------------------------------------------------------------------


def test_the_home_page_carries_the_redesigns_controls():
    index = (STATIC / "index.html").read_text()
    assert 'id="toasts" class="toasts" role="status" aria-live="polite"' in index and 'id="message"' not in index
    assert 'id="map-filter" type="search"' in index
    assert 'class="segmented"' in index and 'id="tree-root"' in index
    assert '<details class="legend">' in index and "Arrows point to what a node depends on." in index
    assert 'id="decide-batch" type="button" class="primary" disabled' in index
    assert 'id="new-node"' in index  # the New node form (#70) stays


def test_the_page_does_not_scroll_sideways_at_phone_width():
    css = (STATIC / "app.css").read_text()
    assert "@media (max-width: 640px)" in css and "#map-filter { width: 100%; }" in css
    assert "overflow: auto" in css  # the graph scrolls inside its frame, not the page
    assert "minmax(min(14rem, 100%), 1fr)" in css  # the New node form's columns never outgrow the screen
