"""One status per node, the same in every view (issue #157).

The server derives a node's status once (webapp/node_status.py) and sends it with the node on
`/api/map` and `/api/node`. The map card, the legend, the tree, the node page and the studio's
node panel all show that status: the same word, the same colour (state-<kind>) and the same icon,
drawn from glyphs defined once (studio/static/status.js). A frontier node with a warning shows
the warning and, beside it, its Ready mark (ADR-0008).

A node whose Candidate proof got Revision requested is back on the frontier: it reads Ready, blue,
as its map card always showed it — the frontier is the strongest signal, ahead of the workflow
state (CONTEXT.md, Frontier). Its workflow chip, Revision requested, is neutral, not the orange of
Awaiting review.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from _review_client import DirectClient
from proof_cli.proof_map import create_node, open_challenge
from proof_cli.storage import ensure_project
from proof_cli.webapp.node_status import KINDS, node_status

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent / "src" / "proof_cli"
MAP_HARNESS = TESTS / "js" / "map_home_harness.js"
PANEL_HARNESS = TESTS / "js" / "node_panel_harness.js"

# one node per status, and what every view must show for it: (word, kind), then a frontier node's Ready beside it
EXPECTED = {
    "K1": [("Ready", "ready")],  # on the frontier
    "K5": [("Ready", "ready")],  # revision requested: back on the frontier
    "I3": [("Open", "open")],  # an imported result nobody has reviewed
    "K6": [("Blocked", "blocked")],
    "K2": [("Awaiting review", "review")],
    "K3": [("Accepted", "accepted")],
    "K4": [("Rejected", "rejected")],
    "K7": [("Challenged", "attention"), ("Ready", "ready")],  # accepted, challenged, on the frontier (ADR-0008)
}


def _prove(store, node_id, decision=None):
    submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="scoped", content=f"\\begin{{proof}}{node_id}.\\end{{proof}}\n")
    if decision:
        researcher(store).decide_acceptance(node_id, decision, rationale=f"{decision} {node_id}")


@pytest.fixture
def statuses(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id in ("K1", "K2", "K3", "K4", "K5", "K7"):
        create_node(store, node_id=node_id, kind="claim", statement=f"Claim {node_id}")
    create_node(store, node_id="K6", kind="claim", statement="Claim K6", dependencies=["K2"])
    create_node(store, node_id="I3", kind="imported_result", statement="Known result I3", source_locator="Theorem 3", source_version="v1")
    _prove(store, "K2")
    _prove(store, "K3", "accept")
    _prove(store, "K4", "reject")
    _prove(store, "K5", "revision-requested")
    _prove(store, "K7", "accept")
    open_challenge(store, "K7", opened_by="agent_b", rationale="a second look")
    client = DirectClient(store)
    nodes = client.get("/api/map")[1]["data"]["nodes"]
    pages = {n["id"]: client.get(f"/api/node/{n['id']}")[1]["data"] for n in nodes}
    state = client.get("/api/state")[1]["data"]
    return {"nodes": nodes, "pages": pages, "state": state}


# -- the server: one derivation, sent on both routes ----------------------------------------


def test_the_map_and_the_node_page_send_the_same_status_and_frontier(statuses):
    for n in statuses["nodes"]:
        page = statuses["pages"][n["id"]]
        assert page["status"] == n["status"] and page["frontier"] == n["frontier"], n["id"]
        assert set(n["status"]) == {"text", "kind"} and n["status"]["kind"] in KINDS


def test_each_node_reads_its_expected_status(statuses):
    got = {n["id"]: (n["status"]["text"], n["status"]["kind"], n["frontier"]) for n in statuses["nodes"]}
    assert got == {node_id: (*marks[0], len(marks) > 1 or marks[0][1] == "ready") for node_id, marks in EXPECTED.items()}


def test_revision_requested_reads_ready_on_the_frontier_and_its_axis_chip_is_neutral(statuses):
    (k5,) = [n for n in statuses["nodes"] if n["id"] == "K5"]
    assert k5["workflow_state"] == "revision-requested" and k5["frontier"]
    assert k5["status"] == {"text": "Ready", "kind": "ready"}
    status_js = (ROOT / "studio" / "static" / "status.js").read_text()
    assert '"revision-requested"' not in status_js.split("var STATUS_OF_VALUE")[1].split("};")[0]  # a neutral grey chip


@pytest.mark.parametrize("node, expected", [
    ({"workflow_state": "open", "acceptance_state": "unreviewed", "integrity_state": "current", "frontier": True}, ("Ready", "ready")),
    ({"workflow_state": "revision-requested", "acceptance_state": "unreviewed", "integrity_state": "current", "frontier": True}, ("Ready", "ready")),
    ({"workflow_state": "open", "acceptance_state": "unreviewed", "integrity_state": "current", "frontier": False}, ("Open", "open")),
    ({"workflow_state": "blocked", "acceptance_state": "unreviewed", "integrity_state": "current"}, ("Blocked", "blocked")),
    ({"workflow_state": "review-needed", "acceptance_state": "unreviewed", "integrity_state": "current"}, ("Awaiting review", "review")),
    ({"workflow_state": "open", "acceptance_state": "accepted", "integrity_state": "current"}, ("Accepted", "accepted")),
    ({"workflow_state": "open", "acceptance_state": "rejected", "integrity_state": "current"}, ("Rejected", "rejected")),
    ({"workflow_state": "open", "acceptance_state": "accepted", "integrity_state": "challenged", "frontier": True}, ("Challenged", "attention")),
    ({"workflow_state": "claimed", "acceptance_state": "unreviewed", "integrity_state": "current", "assignee": "ada"}, ("Ada", "claimed")),
    ({"workflow_state": "claimed", "acceptance_state": "unreviewed", "integrity_state": "current", "assignee": "claude-code",
      "run": {"status": "needs-human", "role": "numerics", "step": 2, "steps": 3}}, ("Numerics · needs you", "attention")),
])
def test_the_status_derivation(node, expected):
    assert tuple(node_status(node).values()) == expected


# -- the five views ----------------------------------------------------------------------


def _node(*args):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    done = subprocess.run(["node", *map(str, args)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _map_views(statuses):
    """The map page: the DAG and the legend, then the tree rooted at each node, then each node's own page."""
    ids = [n["id"] for n in statuses["nodes"]]
    steps = [{"view": "tree"}, *({"root": node_id} for node_id in ids), *({"open": node_id} for node_id in ids)]
    scenario = {"state": statuses["state"], "map": {"nodes": statuses["nodes"]}, "steps": steps, "nodes": statuses["pages"]}
    dag, _, *rest = _node(MAP_HARNESS, json.dumps(scenario))
    lines = {node_id: reading["tree"][0] for node_id, reading in zip(ids, rest)}
    return dag, lines, dict(zip(ids, rest[len(ids):]))


def _panel(view):
    scenario = {"view": view, "saveAll": True, "svg": True}
    return _node(PANEL_HARNESS, json.dumps(scenario))["status"]


def test_every_view_shows_the_same_word_colour_and_icon(statuses):
    dag, tree, pages = _map_views(statuses)
    legend = {entry["kind"]: entry for entry in dag["legend"]}
    for node_id, marks in EXPECTED.items():
        # the map card: its word and colour, its icon, then a frontier's Ready badge beside a warning
        card = dag["dag"][node_id]["status"]
        assert (card["text"], card["kind"]) == marks[0], node_id
        assert [icon["kind"] for icon in card["icons"]] == [kind for _, kind in marks], node_id
        icons = {icon["kind"]: icon["shapes"] for icon in card["icons"]}
        # the tree (rooted at the node), the node page and the studio panel: one chip per mark
        assert tree[node_id]["id"] == node_id
        views = {"tree": tree[node_id]["status"], "node page": pages[node_id]["nodeStatus"]}
        if statuses["pages"][node_id]["node"]["kind"] != "imported_result":  # an imported result has no studio
            views["studio panel"] = _panel(statuses["pages"][node_id])
        for view, chips in views.items():
            assert [(c["text"], c["kind"]) for c in chips] == marks, (node_id, view)
            assert [c["icon"]["kind"] for c in chips] == [kind for _, kind in marks], (node_id, view)
            assert [c["icon"]["shapes"] for c in chips] == [icons[kind] for _, kind in marks], (node_id, view)
        # the legend: the same kind, drawn with the same icon
        for _, kind in marks:
            assert legend[kind]["icon"]["shapes"] == icons[kind], (node_id, kind)


def test_the_legend_lists_every_kind_open_included():
    if shutil.which("node") is None:
        pytest.skip("needs node")
    scenario = {"state": {"project_id": "p", "reviewer": "r", "pending": [], "warnings": []}, "map": {"nodes": []}, "steps": [], "nodes": {}}
    (home,) = _node(MAP_HARNESS, json.dumps(scenario))
    assert [(e["kind"], e["text"]) for e in home["legend"]] == [
        ("ready", "Ready to start"), ("claimed", "In progress"), ("blocked", "Blocked"), ("review", "Awaiting review"),
        ("accepted", "Accepted"), ("rejected", "Rejected"), ("attention", "Needs attention"), ("open", "Open"),
    ]
    assert [e["kind"] for e in home["legend"]] == [e["icon"]["kind"] for e in home["legend"]] and set(KINDS) == {e["kind"] for e in home["legend"]}


# -- the glyphs, defined once ----------------------------------------------------------------

GLYPH_PATHS = ("M6.4 4.9v6.2L11.3 8z", "M9.4 6.6 4.7 11.3", "M6.4 7.3V6.1a1.6 1.6 0 0 1 3.2 0v1.2", "M8 4.6V8l2.3 1.5",
               "M4.9 8.3 7 10.4l4.2-4.6", "M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8", "M8 5.6v3.9", "M8 1.1c.5 0")
PAGES = [ROOT / "webapp" / "static" / name for name in ("index.html", "app.js")] + [ROOT / "studio" / "static" / name for name in ("node.js", "index.html", "app.js")]


def test_the_status_glyphs_are_defined_once_and_both_pages_load_them():
    shared = (ROOT / "studio" / "static" / "status.js").read_text()
    for glyph in GLYPH_PATHS:
        assert shared.count(glyph) == 1, glyph
        for page in PAGES:
            assert glyph not in page.read_text(), (page.name, glyph)
    from proof_cli.webapp.server import shared_asset

    assert shared_asset("status.js")  # the map page loads it from the studio's folder
    webapp = (ROOT / "webapp" / "static" / "index.html").read_text()
    assert webapp.index("/static/shared/status.js") < webapp.index("/static/app.js")
    studio = (ROOT / "studio" / "static" / "index.html").read_text()
    assert studio.index("static/status.js") < studio.index("static/node.js")
