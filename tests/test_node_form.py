"""The map's node form (issue #154): right-click the canvas or a card, and the form opens in place.

Run for real under node (tests/js/node_form_harness.js, the map_home harness's pattern), with the page's
own app.js. Where the form says what the server would do (its refusals, its equivalent CLI), the test
asks the real server and the real CLI too: the server is the source of truth.
"""

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _review_client import DirectClient
from proof_cli.cli import app
from proof_cli.proof_map import claim_node, list_nodes
from proof_cli.storage import ensure_project, list_references

HARNESS = Path(__file__).resolve().parent / "js" / "node_form_harness.js"
STATIC = Path(__file__).resolve().parents[1] / "src" / "proof_cli" / "webapp" / "static"
ME = "Researcher <r@example.org>"


def _node(node_id, kind="claim", statement="", dependencies=(), **axes):
    return {
        "id": node_id, "kind": kind, "statement": statement or node_id, "display_label": None, "dependencies": list(dependencies),
        "acceptance_state": "unreviewed", "workflow_state": "open", "integrity_state": "current", "assignee": None, "frontier": False,
        "status": {"text": "Ready", "kind": "ready"} if axes.get("frontier") else {"text": "Open", "kind": "open"}, **axes,
    }


MAP = {"nodes": [
    _node("thm", "theorem", "Every bounded sequence converges", ["base"]),
    _node("base", "claim", "The partial sums are bounded", frontier=True),
    _node("ref_bw", "imported_result", "Bolzano-Weierstrass", acceptance_state="reviewed"),
]}
REFERENCES = {"references": [
    {"id": "rudin", "title": "Principles of Mathematical Analysis", "authors": ["Walter Rudin"], "year": 1976, "source_type": "textbook",
     "identifier": "isbn:0070542350", "url": "", "bibliographic_source": "", "cited_by": [{"id": "ref_bw", "source_version": "3rd ed.", "acceptance_state": "reviewed"}]},
    {"id": "jn61", "title": "On functions of bounded mean oscillation", "authors": ["Fritz John", "Louis Nirenberg"], "year": 1961, "source_type": "research_paper",
     "identifier": "doi:10.1002/cpa.3160140317", "url": "", "bibliographic_source": "", "cited_by": []},
], "source_types": []}


def _form(steps=(), map_=None, references=None, **extra):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    scenario = {"state": {"project_id": "p", "reviewer": ME, "pending": [], "warnings": []}, "map": map_ or MAP,
                "references": references or REFERENCES, "steps": list(steps), **extra}
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


NEW_HERE = [{"contextmenu": {"x": 100, "y": 120}}, {"menu": "New node here…"}]
NEW_IMPORTED = [{"contextmenu": {"x": 100, "y": 120}}, {"menu": "New imported result here…"}]


# -- the entry: right-click (or a long press), never the double-click ----------------------------


def test_right_clicking_the_canvas_offers_a_node_or_an_imported_result_here():
    _, menu, form = _form(NEW_HERE)
    assert menu["menu"] == ["New node here…", "New imported result here…"] and not menu["popover"]
    assert form["popover"] and form["menu"] is None and form["title"] == "New node"
    assert form["focused"] == "nf-id"


def test_right_clicking_a_card_offers_to_split_it_or_hang_a_node_on_it():
    _, menu = _form([{"contextmenu": {"node": "base"}}])
    assert menu["menuHead"] == ["Claim base"]
    assert menu["menu"] == ["Split base into a Claim…", "New node base rests on…", "New imported result base rests on…", "New node resting on base…"]
    _, imported = _form([{"contextmenu": {"node": "ref_bw"}}])
    assert imported["menu"] == ["New node resting on ref_bw…"]  # nothing rests under an imported result, and it can't be split


def test_each_card_item_opens_the_same_form_prefilled():
    split = _form([{"contextmenu": {"node": "base"}}, {"menu": "Split base into a Claim…"}])[-1]
    assert (split["title"], split["parent"], split["mode"]) == ("Split base", "base", "split")
    assert [k["kind"] for k in split["kinds"] if not k["disabled"]] == ["claim"] and split["kindHint"] == "A Split child is always a Claim."
    rests = _form([{"contextmenu": {"node": "base"}}, {"menu": "New node base rests on…"}])[-1]
    assert (rests["parent"], rests["mode"], [k["kind"] for k in rests["kinds"] if k["pressed"]]) == ("base", "rests", ["lemma"])
    imported = _form([{"contextmenu": {"node": "base"}}, {"menu": "New imported result base rests on…"}])[-1]
    assert (imported["parent"], imported["mode"], imported["title"], imported["splitDisabled"]) == ("base", "rests", "New imported result", True)
    resting = _form([{"contextmenu": {"node": "ref_bw"}}, {"menu": "New node resting on ref_bw…"}])[-1]
    assert resting["depChips"] == ["ref_bw"] and resting["parent"] == ""
    # the user can still change what the menu chose
    changed = _form([{"contextmenu": {"node": "base"}}, {"menu": "Split base into a Claim…"}, {"mode": "rests"}, {"kind": "theorem"}])[-1]
    assert changed["mode"] == "rests" and [k["kind"] for k in changed["kinds"] if k["pressed"]] == ["theorem"]


def test_a_double_click_still_zooms_and_opens_nothing():
    before, after = _form([{"dblclick": {"x": 300, "y": 300}}])
    assert after["scene"] != before["scene"] and "scale(1.65" in after["scene"]
    assert after["menu"] is None and not after["popover"]


def test_a_long_press_opens_the_same_menu_and_its_lift_opens_nothing():
    _, blank = _form([{"longpress": {"x": 200, "y": 200}}])
    assert blank["menu"] == ["New node here…", "New imported result here…"]
    _, on_card = _form([{"longpress": {"node": "base"}}])
    assert on_card["menu"][0] == "Split base into a Claim…" and on_card["href"] == ""  # the card was not opened


@pytest.mark.parametrize("close", [{"escape": True}, {"cancel": True}, {"close": True}, {"outside": True}])
def test_the_form_closes_from_escape_cancel_its_button_or_a_click_outside(close):
    *_, opened, closed = _form([*NEW_HERE, close])
    assert opened["popover"] and opened["ghost"] and not closed["popover"] and closed["ghost"] is None


def test_a_click_outside_keeps_a_form_with_unsaved_input_but_escape_still_closes_it():
    *_, typed, outside, escaped = _form([*NEW_HERE, {"fill": {"nf-id": "lem"}}, {"outside": True}, {"escape": True}])
    assert outside["popover"] and outside["ghost"]
    assert not escaped["popover"]


def test_the_maps_own_keys_never_fire_from_inside_the_form():
    *_, opened, slash, fit = _form([*NEW_HERE, {"keyInForm": "/"}, {"keyInForm": "f"}])
    assert not slash["findFocused"] and slash["popover"]
    assert fit["scene"] == opened["scene"]


def test_enter_in_a_search_box_never_creates_the_node():
    *_, entered = _form([*NEW_HERE, {"fill": {"nf-id": "lem", "nf-statement": "S"}}, {"depFind": "base"}, {"enterIn": "nf-deps-find"}])
    assert entered["posted"] == [] and entered["popover"]


def test_on_a_narrow_window_the_popover_is_a_bottom_sheet():
    wide = _form(NEW_HERE)[-1]
    assert wide["style"]["left"] == "116px"
    narrow = _form(NEW_HERE, narrow=True)[-1]
    assert narrow["style"] == {"left": "", "top": ""}  # placed by CSS, not beside the click
    css = (STATIC / "nodeform.css").read_text()
    sheet = css[css.index("@media (max-width: 760px)"):]
    for rule in ("position: fixed", "left: 0 !important", "right: 0", "bottom: 0", "width: auto", "max-width: none"):
        assert rule in sheet, rule
    assert "overflow-x: hidden" in css  # nothing scrolls sideways


def test_near_the_right_edge_the_popover_opens_to_the_left_and_an_imported_result_is_wider():
    right = _form([{"contextmenu": {"x": 700, "y": 120}}, {"menu": "New node here…"}])[-1]
    assert right["style"]["left"] == "284px"  # 700 - 400 - 16
    imported = _form(NEW_IMPORTED)[-1]
    assert "wide" in imported["classes"]
    css = (STATIC / "nodeform.css").read_text()
    assert ".node-pop { position: absolute; z-index: 11; width: 400px;" in css and ".node-pop.wide { width: 480px; }" in css
    assert "max-height: calc(100% - 24px)" in css


def test_the_page_loads_the_form_after_the_map_and_its_stylesheet():
    html = (STATIC / "index.html").read_text()
    assert html.index("/static/app.js") < html.index("/static/nodeform.js")
    assert '<link rel="stylesheet" href="/static/nodeform.css">' in html and 'id="map-stage"' in html


def test_the_form_uses_only_the_pages_colour_tokens():
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "nodeform.css").read_text(), flags=re.S)  # the rules, not the comments
    assert "#" not in css.replace("#dag-svg", "")  # no colour literal: tokens only
    assert "--" not in css.replace("var(--", "")  # and no new token
    # no colour function either, bar the segmented control's own shadow, drawn as app.css draws it
    assert "rgb(" not in css and "rgba(" not in css.replace("rgba(0, 0, 0, .18), 0 0 0 .5px rgba(0, 0, 0, .04)", "") and "hsl" not in css


# -- the ghost: where the new card lands -----------------------------------------------------


def test_the_ghost_marks_where_the_node_lands_and_the_new_card_is_put_there():
    *_, opened, named, created = _form([*NEW_HERE, {"fill": {"nf-id": "lem1", "nf-statement": "S"}}, {"submit": True}])
    assert opened["ghost"]["text"] == "The new node lands here"
    assert named["ghost"]["text"] == "Claim lem1"
    x, y = (float(v) for v in named["ghost"]["transform"].removeprefix("translate(").removesuffix(")").split(","))
    assert created["positions"]["lem1"] == {"x": x, "y": y}  # the browser's drag-position store, as a dragged card's
    assert created["href"] == "/studio/lem1/"


def test_a_node_its_parent_rests_on_lands_below_the_parent_and_one_resting_on_a_card_above_it():
    below = _form([{"contextmenu": {"node": "base"}}, {"menu": "New node base rests on…"}])[-1]["ghost"]["transform"]
    above = _form([{"contextmenu": {"node": "base"}}, {"menu": "New node resting on base…"}])[-1]["ghost"]["transform"]
    y = lambda t: float(t.split(",")[1].rstrip(")"))  # noqa: E731
    assert y(below) > y(above)


def test_an_empty_map_points_at_the_right_click_and_still_shows_the_ghost():
    first, menu, form = _form(NEW_HERE, map_={"nodes": []})
    assert first["empty"] == "Right-click anywhere to create the first node, or run `proof node create`."
    assert form["ghost"]["transform"] == "translate(100,120)"
    assert form["depRows"][0]["text"] == "The map is empty: nothing to depend on yet."


# -- the fields --------------------------------------------------------------------------------


def test_the_statement_and_each_assumption_are_typeset_as_they_are_typed_and_a_bad_formula_shows_as_written():
    *_, typed = _form([*NEW_HERE, {"fill": {"nf-statement": "For $x>0$, $\\frac{1}{x$ and $$y^2$$"}}, {"addAssumption": "$a \\ge 0$"}, {"addAssumption": "$\\sqrt{$"}])
    assert typed["statementMath"] == [
        {"class": "math", "text": "[katex: x>0]"}, {"class": "math unrendered", "text": "$\\frac{1}{x$"}, {"class": "math display", "text": "[katex display: y^2]"}]
    assert typed["assumptionPreviews"] == ["[katex: a \\ge 0]", "$\\sqrt{$"]


def test_an_imported_result_hides_dependencies_and_medium_and_asks_for_its_source():
    local = _form(NEW_HERE)[-1]
    assert local["mediumShown"] and local["depsShown"] and not local["sourceShown"]
    imported = _form(NEW_IMPORTED)[-1]
    assert not imported["mediumShown"] and not imported["depsShown"] and imported["sourceShown"]
    assert imported["immutable"].startswith("The citation is fixed once the node exists (reference_id, ADR-0012).")
    # dependencies chosen before switching stay visible, so they can be removed
    leftover = _form([*NEW_HERE, {"fill": {"nf-id": "r", "nf-statement": "S"}}, {"pick": "base"}, {"kind": "imported_result"}])[-1]
    assert leftover["depsShown"] and leftover["depChips"] == ["base"]
    assert leftover["errors"]["deps"].startswith("IMPORTED_RESULT_HAS_NO_DEPENDENCIES: ")


def test_the_dependency_picker_searches_id_label_and_statement_and_marks_the_match():
    rows = _form([*NEW_HERE, {"depFind": "partial"}])[-1]["depRows"]
    assert [(r["id"], r["marks"]) for r in rows] == [("base", ["partial"])]
    assert rows[0]["chips"] == [{"text": "Ready", "class": "chip state-ready node-status", "icon": "status-icon ready"}]  # its status, as the card shows it
    picked = _form([*NEW_HERE, {"pick": "base"}, {"pick": "thm"}, {"unpick": "base"}])[-1]
    assert picked["depChips"] == ["thm"]


def test_the_picker_and_the_parent_show_the_servers_status_never_one_worked_out_on_the_page():
    """The status is the server's (webapp/node_status.py, issue #157): the form shows the word and kind it was sent,
    with status.js's icons, and a frontier node's Ready beside a warning."""
    odd = {"nodes": [_node("base", acceptance_state="accepted", frontier=True, status={"text": "Numerics · needs you", "kind": "attention"}), MAP["nodes"][2]]}
    form = _form([*NEW_HERE, {"depFind": "base"}], map_=odd)[-1]
    assert [(c["text"], c["class"], c["icon"]) for c in form["depRows"][0]["chips"]] == [
        ("Numerics · needs you", "chip state-attention node-status", "status-icon attention"), ("Ready", "chip state-ready node-status", "status-icon ready")]
    assert form["parentLabels"][1] == "base · Claim, Numerics · needs you"
    source = (STATIC / "nodeform.js").read_text()
    for local in ("tagOf", "statusIcon", "STATUS_OF_VALUE", "STATUS_KINDS", "glyph"):
        assert local not in source, local


def test_a_node_the_form_made_reads_the_status_the_server_sent_for_it():
    steps = [*NEW_HERE, {"fill": {"nf-id": "lem1", "nf-statement": "S"}}, {"submit": True}, *NEW_HERE, {"depFind": "lem1"}]
    row = _form(steps, createdStatus={"text": "Blocked", "kind": "blocked"})[-1]["depRows"][0]
    assert row["id"] == "lem1" and [c["text"] for c in row["chips"]] == ["Blocked"]


def test_the_reference_picker_searches_title_author_and_identifier_and_shows_who_cites_it():
    for query, found in (("bounded mean", "jn61"), ("rudin", "rudin"), ("nirenberg", "jn61"), ("doi:10.1002", "jn61"), ("isbn", "rudin")):
        rows = _form([*NEW_IMPORTED, {"refFind": query}])[-1]["refRows"]
        assert [r["id"] for r in rows] == [found], query
    (rudin, _) = _form(NEW_IMPORTED)[-1]["refRows"]
    assert "cited by ref_bw (3rd ed., reviewed)" in rudin["text"] and "Walter Rudin · 1976 · isbn:0070542350" in rudin["text"] and "textbook" in rudin["text"]
    for legacy in ("candidate", "tentative_source", "callable"):
        assert legacy not in rudin["text"]


def test_a_chosen_reference_shows_as_the_node_page_cites_it_and_only_suggests_the_locator_and_version():
    *_, picked, suggested = _form([*NEW_IMPORTED, {"refPick": "rudin"}, {"suggest": "version"}])
    assert picked["refSelectedBlock"] and "Principles of Mathematical Analysis" in picked["refSelected"] and "reference rudin" in picked["refSelected"]
    assert picked["suggest"] == ["locator", "version"]
    assert "--source-version '<version>'" in picked["cli"]  # nothing filled in until asked
    assert "--source-version 1976" in suggested["cli"] and suggested["suggest"] == ["locator"]
    assert "--reference-id rudin" in suggested["cli"]


def test_a_new_reference_is_imported_first_then_the_node_cites_it():
    steps = [*NEW_IMPORTED, {"fill": {"nf-id": "ref_new", "nf-statement": "K", "nf-locator": "Thm 1", "nf-version": "v1"}},
             {"newRef": {"id": "evans", "year": "2010", "title": "PDE", "authors": "Lawrence C. Evans; Second Author", "source_type": "textbook", "identifier": "doi:10.1090/gsm/019"}},
             {"submit": True}]
    *_, filled, done = _form(steps)
    assert filled["cli"].startswith("proof reference import evans PDE 2010 \\\n    --author 'Lawrence C. Evans' \\\n    --author 'Second Author' \\\n    --source-type textbook")
    assert filled["cliNote"].startswith("2 commands, run in order: not atomic from the CLI")
    assert [p["url"] for p in done["posted"]] == ["/api/references", "/api/nodes"]
    assert done["posted"][0]["body"] == {"reference_id": "evans", "title": "PDE", "year": "2010", "authors": ["Lawrence C. Evans", "Second Author"],
                                         "source_type": "textbook", "identifier": "doi:10.1090/gsm/019", "url": ""}
    assert done["posted"][1]["body"]["reference_id"] == "evans" and done["href"] == "/#/node/ref_new"


def test_a_refused_node_after_a_new_reference_keeps_the_reference_and_does_not_import_it_again():
    steps = [*NEW_IMPORTED, {"fill": {"nf-id": "ref_new", "nf-statement": "K", "nf-locator": "Thm 1", "nf-version": "v1"}},
             {"newRef": {"id": "evans", "year": "2010", "title": "PDE"}}, {"submit": True}, {"submit": True}]
    *_, refused, again = _form(steps, refuse={"POST /api/nodes": {"code": "INTERNAL_ERROR", "message": "boom"}})
    assert refused["refusal"] == "INTERNAL_ERROR: boom" and refused["message"] == "INTERNAL_ERROR: boom" and refused["popover"]
    assert [p["url"] for p in again["posted"]] == ["/api/references", "/api/nodes", "/api/nodes"]
    assert "proof reference import" not in again["cli"] and "--reference-id evans" in again["cli"]


def test_a_parent_held_by_someone_else_offers_to_take_the_claim_over():
    held = {"nodes": [*MAP["nodes"][:1], _node("base", assignee="agent_b"), MAP["nodes"][2]]}
    *_, refused, reassigned = _form([{"contextmenu": {"node": "base"}}, {"menu": "New node base rests on…"},
                                     {"fill": {"nf-id": "lem", "nf-statement": "L"}}, {"reassign": True}], map_=held)
    assert refused["reassignShown"] and refused["reassignText"] == "base is claimed by agent_b: take the claim over (--reassign)"
    assert refused["errors"]["parent"] == "NOT_CLAIMANT: base is claimed by agent_b"
    assert "parent" not in reassigned["errors"] and reassigned["cli"].endswith("--parent base \\\n    --reassign")
    mine = {"nodes": [*MAP["nodes"][:1], _node("base", assignee=ME), MAP["nodes"][2]]}
    assert not _form([{"contextmenu": {"node": "base"}}, {"menu": "New node base rests on…"}], map_=mine)[-1]["reassignShown"]


# -- the equivalent CLI -------------------------------------------------------------------------


def test_the_cli_line_follows_every_field():
    steps = [*NEW_HERE, {"fill": {"nf-id": "lem", "nf-label": "Key", "nf-statement": "It's $x$"}}, {"kind": "lemma"},
             {"addAssumption": "$x>0$"}, {"pick": "base"}, {"medium": "computation"}, {"parent": "thm"}]
    cli = _form(steps)[-1]["cli"]
    assert cli == ("proof node create lem lemma 'It'\\''s $x$' \\\n    --display-label Key \\\n    --assumption '$x>0$' \\\n    --dependency base"
                   " \\\n    --medium computation \\\n    --parent thm")


def test_a_split_with_dependencies_and_a_medium_is_several_commands_not_atomic_from_the_cli():
    steps = [{"contextmenu": {"node": "thm"}}, {"menu": "Split thm into a Claim…"}, {"fill": {"nf-id": "k", "nf-statement": "K", "nf-label": "Step"}},
             {"addAssumption": "a"}, {"pick": "ref_bw"}, {"medium": "computation"}]
    form = _form(steps)[-1]
    assert form["cli"].split("\n")[0] == "proof node split thm \\"
    assert "--child k=K \\\n    --assumption a \\\n    --display-label Step" in form["cli"]
    assert form["cli"].endswith("proof node depend k --add ref_bw\nproof node medium set k computation")
    assert form["cliNote"].startswith("3 commands, run in order: not atomic from the CLI")
    assert form["submit"]["text"] == "Split"


def test_copy_puts_the_command_on_the_clipboard():
    *_, copied = _form([*NEW_HERE, {"fill": {"nf-id": "lem", "nf-statement": "S"}}, {"copy": True}])
    assert copied["copied"] == ["proof node create lem claim S"]


def _seed(root: Path) -> None:
    """The same small project, made with the CLI: the page's and the CLI's results are compared on two copies."""
    runner = CliRunner()
    for args in (
        ["node", "create", "base", "claim", "The partial sums are bounded"],
        ["node", "create", "thm", "theorem", "Every bounded sequence converges", "--dependency", "base"],
        ["reference", "import", "rudin", "Principles of Mathematical Analysis", "1976", "--author", "Walter Rudin", "--source-type", "textbook"],
        ["node", "create", "ref_bw", "imported_result", "BW", "--source-locator", "Thm 3.6", "--source-version", "3rd ed.", "--reference-id", "rudin"],
    ):
        assert runner.invoke(app, [*args, "--root", str(root)]).exit_code == 0


def _project(root: Path):
    _seed(root)
    store = ensure_project(root)
    client = DirectClient(store)
    return store, client


def _page_scenario(client):
    data = lambda path: client.get(path)[1]["data"]  # noqa: E731
    return {"map_": data("/api/map"), "references": data("/api/references")}


def _comparable(store) -> dict:
    volatile = {"created_by", "updated_by", "created_at", "updated_at"}
    nodes = {n.id: {k: v for k, v in n.model_dump(mode="json").items() if k not in volatile} for n in list_nodes(store)}
    refs = {r.id: r.model_dump(mode="json", include={"id", "title", "authors", "year", "source_type", "identifier", "url"}) for r in list_references(store)}
    return {"nodes": nodes, "references": refs}


FORM_STATES = {
    "a computation claim with everything": [*NEW_HERE, {"fill": {"nf-id": "calc", "nf-label": "Count", "nf-statement": "It's $n \\le 2^n$"}},
                                            {"addAssumption": "$n \\ge 1$"}, {"addAssumption": "n is \"even\""}, {"pick": "base"}, {"medium": "computation"}],
    "an imported result citing a reference": [*NEW_IMPORTED, {"fill": {"nf-id": "ref_x", "nf-statement": "K", "nf-locator": "Thm 1.2", "nf-version": "3rd ed."}},
                                              {"fill": {"nf-trust": "external_reference"}}, {"refPick": "rudin"}],
    "an imported result with a new reference": [*NEW_IMPORTED, {"fill": {"nf-id": "ref_y", "nf-statement": "K", "nf-locator": "p. 4", "nf-version": "v2"}},
                                                {"newRef": {"id": "evans", "year": "2010", "title": "PDE: an introduction", "authors": "L. C. Evans", "source_type": "monograph",
                                                            "identifier": "doi:10.1090/gsm/019", "url": "https://example.org/pde"}}],
    "a lemma the theorem rests on": [{"contextmenu": {"node": "thm"}}, {"menu": "New node thm rests on…"}, {"fill": {"nf-id": "lem", "nf-statement": "L"}}, {"addAssumption": "a"}],
    "an imported result the theorem rests on": [{"contextmenu": {"node": "thm"}}, {"menu": "New imported result thm rests on…"},
                                                {"fill": {"nf-id": "ref_z", "nf-statement": "Z", "nf-locator": "l", "nf-version": "v"}}],
    "a split with everything": [{"contextmenu": {"node": "thm"}}, {"menu": "Split thm into a Claim…"}, {"fill": {"nf-id": "k", "nf-statement": "K = 1", "nf-label": "Key"}},
                                {"addAssumption": "$k$ odd"}, {"pick": "ref_bw"}, {"medium": "computation"}],
    "a node resting on another": [{"contextmenu": {"node": "base"}}, {"menu": "New node resting on base…"}, {"fill": {"nf-id": "up", "nf-statement": "U"}}, {"kind": "claim"}],
}


@pytest.mark.parametrize("name", list(FORM_STATES))
def test_the_cli_line_run_in_a_shell_makes_what_the_form_makes(tmp_path: Path, name):
    page_store, page_client = _project(tmp_path / "page")
    cli_root = tmp_path / "cli"
    _seed(cli_root)
    form = _form([*FORM_STATES[name], {"submit": True}], **_page_scenario(page_client))
    filled, done = form[-2], form[-1]
    assert not filled["refusal"], filled["refusal"]
    # the page's requests, through the real server
    for request in done["posted"]:
        status, body = page_client.post(request["url"], request["body"])
        assert status == 200, body
    # the command lines, through the real CLI, as a shell would split them
    runner = CliRunner()
    for command in filled["cliCommands"]:
        args = shlex.split(command.replace(" \\\n    ", " "))
        assert args[0] == "proof"
        result = runner.invoke(app, args[1:], env={"PROOF_ROOT": str(cli_root)})
        assert result.exit_code == 0, (args, result.output)
    assert _comparable(page_store) == _comparable(ensure_project(cli_root))
    page_client.app.close()


# -- refusals: the server's codes and words ---------------------------------------------------


def test_a_refused_check_posts_nothing_and_says_the_servers_code_and_words():
    *_, refused = _form([*NEW_HERE, {"fill": {"nf-id": ".hidden", "nf-statement": "S"}}, {"submit": True}])
    assert refused["posted"] == [] and refused["popover"]
    assert refused["refusal"] == "INVALID_NODE_ID: node id '.hidden' must be letters, digits, '.', '_' or '-', not starting with '.'"


def test_a_server_refusal_shows_as_code_and_message_and_keeps_the_form():
    *_, refused = _form([*NEW_HERE, {"fill": {"nf-id": "lem", "nf-statement": "S"}}, {"submit": True}],
                        refuse={"POST /api/nodes": {"code": "NODE_ALREADY_EXISTS", "message": "proof map node lem already exists"}})
    assert refused["refusal"] == refused["message"] == "NODE_ALREADY_EXISTS: proof map node lem already exists"
    assert refused["popover"] and refused["href"] == "" and not refused["submit"]["disabled"]


PRECHECKS = {
    "no id": [*NEW_HERE, {"fill": {"nf-statement": "S"}}],
    "no statement": [*NEW_HERE, {"fill": {"nf-id": "lem"}}],
    "a bad id": [*NEW_HERE, {"fill": {"nf-id": "has space", "nf-statement": "S"}}],
    "a quoted bad id": [*NEW_HERE, {"fill": {"nf-id": "it's", "nf-statement": "S"}}],
    "a reserved id": [*NEW_HERE, {"fill": {"nf-id": "Preamble.TEX", "nf-statement": "S"}}],
    "an existing id": [*NEW_HERE, {"fill": {"nf-id": "base", "nf-statement": "S"}}],
    "a second theorem": [*NEW_HERE, {"fill": {"nf-id": "t2", "nf-statement": "S"}}, {"kind": "theorem"}],
    "an imported result without its source": [*NEW_IMPORTED, {"fill": {"nf-id": "r", "nf-statement": "S", "nf-locator": "l"}}],
    "an imported result with dependencies": [*NEW_HERE, {"fill": {"nf-id": "r", "nf-statement": "S", "nf-locator": "l", "nf-version": "v"}}, {"pick": "base"}, {"kind": "imported_result"}],
    "a parent held by another": [{"contextmenu": {"node": "held"}}, {"menu": "New node held rests on…"}, {"fill": {"nf-id": "x", "nf-statement": "S"}}],
    "a split of a parent held by another": [{"contextmenu": {"node": "held"}}, {"menu": "Split held into a Claim…"}, {"fill": {"nf-id": "x", "nf-statement": "S"}}],
    "a split child without a statement": [{"contextmenu": {"node": "base"}}, {"menu": "Split base into a Claim…"}, {"fill": {"nf-id": "x"}}],
    "an imported parent": [*NEW_HERE, {"fill": {"nf-id": "x", "nf-statement": "S"}}, {"parent": "ref_bw"}],
    "a split of an imported result": [*NEW_HERE, {"fill": {"nf-id": "x", "nf-statement": "S"}}, {"parent": "ref_bw"}, {"mode": "split"}],
    "a parent that would close a cycle": [{"contextmenu": {"node": "base"}}, {"menu": "New node base rests on…"}, {"fill": {"nf-id": "x", "nf-statement": "S"}}, {"pick": "thm"}],
    "a split child that would close a cycle": [{"contextmenu": {"node": "base"}}, {"menu": "Split base into a Claim…"}, {"fill": {"nf-id": "x", "nf-statement": "S"}}, {"pick": "thm"}],
    "a split child with a bad id": [{"contextmenu": {"node": "base"}}, {"menu": "Split base into a Claim…"}, {"fill": {"nf-id": "fog", "nf-statement": "S"}}],
}


@pytest.mark.parametrize("name", list(PRECHECKS))
def test_each_check_the_form_makes_is_worded_and_coded_as_the_server_refuses_it(tmp_path: Path, name):
    store, client = _project(tmp_path)
    for args in (["node", "create", "held", "claim", "H"],):
        assert CliRunner().invoke(app, [*args, "--root", str(tmp_path)]).exit_code == 0
    claim_node(store, "held", claimant_id="agent_b")
    form = _form([*PRECHECKS[name], {"submit": True}], **_page_scenario(client))[-1]
    assert form["posted"] == [] and form["refusal"], form["refusal"]
    status, body = client.post(form["wouldPost"]["url"], form["wouldPost"]["body"])
    assert status >= 400, body
    assert form["refusal"] == f'{body["error"]["code"]}: {body["error"]["message"]}'
    client.app.close()


@pytest.mark.parametrize("new_ref, expected", [
    ({"id": "rudin", "year": "1976", "title": "Again"}, "INVALID_INPUT: reference rudin already exists; import the new record under a new id"),
    ({"id": "fresh", "year": "19x6", "title": "T"}, "INVALID_INPUT: a reference's year is a whole number"),
    ({"id": "fresh", "year": "1976", "title": ""}, "INVALID_INPUT: a reference needs reference_id, title and year"),
])
def test_a_new_references_checks_are_the_servers(tmp_path: Path, new_ref, expected):
    store, client = _project(tmp_path)
    steps = [*NEW_IMPORTED, {"fill": {"nf-id": "r", "nf-statement": "S", "nf-locator": "l", "nf-version": "v"}}, {"newRef": new_ref}, {"submit": True}]
    form = _form(steps, **_page_scenario(client))[-1]
    assert form["refusal"] == expected and form["posted"] == []
    status, body = client.post("/api/references", {"reference_id": new_ref["id"], "title": new_ref["title"], "year": new_ref["year"], "authors": []})
    assert f'{body["error"]["code"]}: {body["error"]["message"]}' == expected
    client.app.close()
