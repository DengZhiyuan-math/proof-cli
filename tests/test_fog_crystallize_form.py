"""The fog drawer's Crystallize… opens the map's node form (issue #155, after #154; ADR-0008).

The form opens beside the item's near node (the canvas centre when it has none), with the parent
prefilled only when the item has exactly one near node, an empty statement and the item's text above
it for reference. It posts to the crystallize service, never a plain create, and shows `proof fog
crystallize …` as the equivalent command. Run for real under node (tests/js/node_form_harness.js);
where the form says what the server would do, the test asks the real server and the real CLI too.
"""

import json
import shlex
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _review_client import DirectClient
from proof_cli.cli import app
from proof_cli.fog import require_fog
from proof_cli.proof_map import claim_node, list_nodes
from proof_cli.storage import ensure_project
from test_node_form import _form

FOG = {"items": [
    {"id": "fog-1", "text": "the partial sums might be bounded by a geometric series", "near": ["base"], "notes": "", "status": "open", "node_id": None,
     "experiments": [], "experiment_count": 0, "latest_experiment": None},
    {"id": "fog-2", "text": "a compactness argument, somewhere between the two", "near": ["base", "thm"], "notes": "", "status": "open", "node_id": None,
     "experiments": [], "experiment_count": 0, "latest_experiment": None},
    {"id": "fog-3", "text": "is there a variational characterisation?", "near": [], "notes": "", "status": "open", "node_id": None,
     "experiments": [], "experiment_count": 0, "latest_experiment": None},
]}


def _crystallize(fog_id, steps=(), **extra):
    return _form([{"crystallize": fog_id}, *steps], fog=extra.pop("fog", FOG), **extra)


def _xy(transform):
    x, y = transform.removeprefix("translate(").removesuffix(")").split(",")
    return float(x), float(y)


# -- opening it from the drawer --------------------------------------------------------------------


def test_a_single_near_node_is_the_prefilled_parent_and_the_form_opens_beside_it():
    form = _crystallize("fog-1")[-1]
    assert form["popover"] and form["title"] == "Crystallize fog-1"
    assert form["parent"] == "base" and not form["modesShown"]  # a crystallize with a parent is a single-child Split of it
    assert [k["kind"] for k in form["kinds"] if not k["disabled"]] == ["claim"] and form["kindHint"] == "A crystallize states a Claim."
    assert not form["depsShown"]  # crystallize takes no dependencies
    # beside the near node: the ghost below it, where a Split child lands, and the popover by its card
    centre, zoom = form["centres"]["base"], form["zoom"]
    gx, gy = _xy(form["ghost"]["transform"])
    assert gx == centre["x"] and gy > centre["y"]
    assert form["anchor"] == {"x": centre["x"] * zoom["k"] + zoom["tx"], "y": centre["y"] * zoom["k"] + zoom["ty"]}
    assert form["submit"]["text"] == "Crystallize"
    assert form["cli"] == "proof fog crystallize fog-1 '<node-id>' '<statement>' \\\n    --parent base"


def test_several_near_nodes_leave_the_parent_unset_and_crystallize_is_refused_as_the_cli_refuses_it():
    *_, opened, refused, chosen = _crystallize("fog-2", [{"fill": {"nf-id": "k", "nf-statement": "K"}}, {"submit": True}, {"parent": "thm"}])
    assert opened["parent"] == "" and opened["parentOptions"][:2] == ["", ":none"]
    assert opened["parentLabels"][0] == "Choose: it is near base, thm"
    assert refused["posted"] == [] and refused["popover"]
    assert refused["refusal"] == "FOG_PARENT_AMBIGUOUS: fog-2 is near 2 nodes (base, thm); say which is the parent with --parent, or --no-parent for none"
    assert chosen["refusal"] == "" and chosen["cli"].endswith("--parent thm")
    # beside the first near node on the canvas
    assert _xy(opened["ghost"]["transform"])[0] == opened["centres"]["base"]["x"]


def test_no_near_node_opens_at_the_canvas_centre_with_no_parent():
    form = _crystallize("fog-3")[-1]
    assert form["parent"] == ":none" and "" not in form["parentOptions"]
    zoom = form["zoom"]
    assert form["anchor"] == {"x": 400, "y": 300}
    assert _xy(form["ghost"]["transform"]) == ((400 - zoom["tx"]) / zoom["k"], (300 - zoom["ty"]) / zoom["k"])
    assert form["cli"] == "proof fog crystallize fog-3 '<node-id>' '<statement>'"  # no parent flag: the CLI's default is none


def test_the_fog_text_is_shown_above_the_form_and_the_statement_starts_empty():
    form = _crystallize("fog-1")[-1]
    assert form["fogShown"] and "fog-1" in form["fogText"] and FOG["items"][0]["text"] in form["fogText"]
    assert form["statementPreview"] == "" and form["wouldPost"]["body"]["statement"] == ""
    plain = _form([{"contextmenu": {"x": 100, "y": 120}}, {"menu": "New node here…"}])[-1]
    assert not plain["fogShown"] and plain["title"] == "New node"  # the canvas's own form carries no fog


def test_the_parent_shows_the_servers_status():
    form = _crystallize("fog-1")[-1]
    assert "base · Claim, Ready" in form["parentLabels"]  # the status the map was sent (#157), never one worked out here


# -- submitting ------------------------------------------------------------------------------------


def test_submitting_posts_the_crystallize_and_opens_the_new_claim():
    steps = [{"fill": {"nf-id": "geo", "nf-statement": "$s_n \\le 2$", "nf-label": "Geometric"}}, {"addAssumption": "$a_n \\ge 0$"}, {"medium": "computation"}, {"submit": True}]
    *_, filled, done = _crystallize("fog-1", steps)
    (sent,) = done["posted"]
    assert sent == {"url": "/api/fog/fog-1/crystallize", "body": {
        "node_id": "geo", "statement": "$s_n \\le 2$", "display_label": "Geometric", "assumptions": ["$a_n \\ge 0$"], "medium": "computation",
        "parent": "base", "no_parent": False, "reassign": False}}
    assert done["href"] == "/studio/geo/" and done["message"] == "Crystallized fog-1 as geo." and not done["popover"]
    x, y = _xy(filled["ghost"]["transform"])
    assert done["positions"]["geo"] == {"x": x, "y": y}
    assert filled["cliCommands"] == ["proof fog crystallize fog-1 geo '$s_n \\le 2$' \\\n    --parent base \\\n    --assumption '$a_n \\ge 0$' \\\n    --display-label Geometric \\\n    --medium computation"]


def test_choosing_none_with_a_near_node_says_no_parent():
    *_, chosen = _crystallize("fog-1", [{"noParent": True}, {"fill": {"nf-id": "free", "nf-statement": "F"}}])
    assert chosen["wouldPost"]["body"]["no_parent"] is True and chosen["wouldPost"]["body"]["parent"] is None
    assert chosen["cli"] == "proof fog crystallize fog-1 free F \\\n    --no-parent"


def test_a_server_refusal_keeps_the_form_and_says_its_code():
    refuse = {"POST /api/fog/fog-1/crystallize": {"code": "FOG_NOT_OPEN", "message": "fog-1 is crystallized as node x; crystallizing it belongs to that node now"}}
    *_, refused = _crystallize("fog-1", [{"fill": {"nf-id": "geo", "nf-statement": "S"}}, {"submit": True}], refuse=refuse)
    assert refused["popover"] and refused["refusal"] == "FOG_NOT_OPEN: fog-1 is crystallized as node x; crystallizing it belongs to that node now"


# -- the result is the CLI's -----------------------------------------------------------------------


def _seed(root: Path) -> None:
    runner = CliRunner()
    for args in (
        ["node", "create", "base", "claim", "The partial sums are bounded"],
        ["node", "create", "thm", "theorem", "Every bounded sequence converges", "--dependency", "base"],
        ["node", "create", "held", "claim", "H"],
        ["reference", "import", "rudin", "Principles of Mathematical Analysis", "1976", "--author", "Walter Rudin"],
        ["node", "create", "ref_bw", "imported_result", "BW", "--source-locator", "Thm 3.6", "--source-version", "3rd ed.", "--reference-id", "rudin"],
        ["fog", "add", "a geometric bound", "--near", "base"],
        ["fog", "add", "compactness, somewhere", "--near", "base", "--near", "thm"],
        ["fog", "add", "a variational characterisation?"],
        ["fog", "add", "about the imported result", "--near", "ref_bw"],
        ["fog", "add", "about the held claim", "--near", "held"],
    ):
        result = runner.invoke(app, [*args, "--root", str(root)])
        assert result.exit_code == 0, (args, result.output)


def _project(root: Path):
    _seed(root)
    store = ensure_project(root)
    claim_node(store, "held", claimant_id="agent_b")
    return store, DirectClient(store)


def _page_scenario(client):
    data = lambda path: client.get(path)[1]["data"]  # noqa: E731
    return {"map_": data("/api/map"), "references": data("/api/references"), "fog": data("/api/fog")}


def _comparable(store) -> dict:
    volatile = {"created_by", "updated_by", "created_at", "updated_at"}
    nodes = {n.id: {k: v for k, v in n.model_dump(mode="json").items() if k not in volatile} for n in list_nodes(store)}
    fog = {f"fog-{n}": {k: v for k, v in require_fog(store, f"fog-{n}").model_dump(mode="json").items() if k not in volatile} for n in range(1, 6)}
    return {"nodes": nodes, "fog": fog}


CRYSTALLIZES = {
    "the one near node as parent": ("fog-1", [{"fill": {"nf-id": "geo", "nf-statement": "$s_n \\le 2$"}}]),
    "a chosen one of several": ("fog-2", [{"parent": "thm"}, {"fill": {"nf-id": "cpt", "nf-statement": "K is compact", "nf-label": "Compact"}}, {"addAssumption": "it's \"closed\""}]),
    "none, though near one": ("fog-1", [{"noParent": True}, {"fill": {"nf-id": "free", "nf-statement": "F"}}]),
    "no near node, a computation": ("fog-3", [{"fill": {"nf-id": "var", "nf-statement": "V"}}, {"medium": "computation"}]),
}


@pytest.mark.parametrize("name", list(CRYSTALLIZES))
def test_the_page_and_its_cli_line_crystallize_alike(tmp_path: Path, name):
    page_store, page_client = _project(tmp_path / "page")
    cli_store, _ = _project(tmp_path / "cli")
    fog_id, steps = CRYSTALLIZES[name]
    *_, filled, done = _crystallize(fog_id, [*steps, {"submit": True}], **_page_scenario(page_client))
    assert not filled["refusal"], filled["refusal"]
    (request,) = done["posted"]
    status, body = page_client.post(request["url"], request["body"])
    assert status == 200, body
    made = body["data"]
    assert made["fog"] == {"id": fog_id, "status": "crystallized", "node_id": made["id"]} and made["page"] == f"/studio/{made['id']}/"
    (command,) = filled["cliCommands"]
    args = shlex.split(command.replace(" \\\n    ", " "))
    result = CliRunner().invoke(app, [*args[1:], "--json"], env={"PROOF_ROOT": str(tmp_path / "cli")})
    assert result.exit_code == 0, result.output
    cli = json.loads(result.output)["data"]
    who = ("created_by", "updated_by", "created_at", "updated_at")  # the page writes as its git identity, the CLI as "human"
    assert {k: v for k, v in made.items() if k not in (*who, "page")} == {k: v for k, v in cli.items() if k not in who}
    assert _comparable(page_store) == _comparable(cli_store)
    # the node and its fog item name each other, as after the CLI
    assert page_client.get(f"/api/node/{made['id']}")[1]["data"]["crystallized_from"] == fog_id
    page_client.app.close()


PRECHECKS = {
    "several near, none chosen": ("fog-2", [{"fill": {"nf-id": "k", "nf-statement": "K"}}]),
    "no statement": ("fog-1", [{"fill": {"nf-id": "k"}}]),
    "a blank statement, no parent": ("fog-3", [{"fill": {"nf-id": "k", "nf-statement": "   "}}]),
    "no id": ("fog-1", [{"fill": {"nf-statement": "K"}}]),
    "a bad id": ("fog-3", [{"fill": {"nf-id": "has space", "nf-statement": "K"}}]),
    "an existing id": ("fog-1", [{"fill": {"nf-id": "thm", "nf-statement": "K"}}]),
    "an imported result as parent": ("fog-4", [{"fill": {"nf-id": "k", "nf-statement": "K"}}]),
    "a parent held by another": ("fog-5", [{"fill": {"nf-id": "k", "nf-statement": "K"}}]),
}


@pytest.mark.parametrize("name", list(PRECHECKS))
def test_each_check_the_form_makes_is_the_servers_and_the_clis_refusal(tmp_path: Path, name):
    store, client = _project(tmp_path)
    fog_id, steps = PRECHECKS[name]
    form = _crystallize(fog_id, [*steps, {"submit": True}], **_page_scenario(client))[-1]
    assert form["posted"] == [] and form["refusal"], form["refusal"]
    status, body = client.post(form["wouldPost"]["url"], form["wouldPost"]["body"])
    assert status >= 400, body
    assert form["refusal"] == f'{body["error"]["code"]}: {body["error"]["message"]}'
    (command,) = form["cliCommands"]
    if "<node-id>" not in command and "<statement>" not in command:  # a placeholder is the form's prompt, not a value to run
        args = shlex.split(command.replace(" \\\n    ", " "))
        result = CliRunner().invoke(app, [*args[1:], "--json"], env={"PROOF_ROOT": str(tmp_path)})
        refused = json.loads(result.output)["error"]
        assert result.exit_code == 1 and form["refusal"] == f'{refused["code"]}: {refused["message"]}'
    assert require_fog(store, fog_id).status.value == "open"
    client.app.close()


# -- the endpoint ----------------------------------------------------------------------------------


def test_the_endpoint_answers_as_the_cli_and_refuses_with_its_codes(tmp_path: Path):
    store, client = _project(tmp_path)
    status, missing = client.post("/api/fog/fog-9/crystallize", {"node_id": "k", "statement": "K"})
    assert status == 400 and missing["error"] == {"code": "FOG_NOT_FOUND", "message": "no fog item is named fog-9"}
    status, conflict = client.post("/api/fog/fog-1/crystallize", {"node_id": "k", "statement": "K", "parent": "base", "no_parent": True})
    assert conflict["error"]["code"] == "FOG_FLAG_CONFLICT"
    status, malformed = client.post("/api/fog/fog-1/crystallize", {"node_id": 3, "statement": "K"})
    assert status == 400 and malformed["error"]["code"] == "INVALID_REQUEST"
    status, made = client.post("/api/fog/fog-1/crystallize", {"node_id": "geo", "statement": "S"})  # the CLI's default: the one near node
    assert status == 200 and made["data"]["derived_from"] == "base" and made["data"]["created_by"] == client.app._actor()
    status, again = client.post("/api/fog/fog-1/crystallize", {"node_id": "geo2", "statement": "S"})
    assert again["error"]["code"] == "FOG_NOT_OPEN" and "geo2" not in {n.id for n in list_nodes(store)}
    client.app.close()


def test_the_endpoint_is_behind_the_same_origin_guard(tmp_path: Path):
    """Through the real handler's do_POST (no socket): a write from another origin is refused and changes nothing."""
    from proof_cli.webapp.server import ReviewApp, _Handler

    store = ensure_project(tmp_path)
    _seed(tmp_path)
    review = ReviewApp(store)
    sent = []
    handler = object.__new__(type("H", (_Handler,), {"app": review}))
    handler._send = lambda status, body, content_type, **_: sent.append((int(status), json.loads(body)))
    payload = json.dumps({"node_id": "geo", "statement": "S"}).encode()
    host = review.origin.split("://", 1)[1]
    for origin in ("http://evil.example", review.origin):
        handler.headers = {"Host": host, "Origin": origin, "Content-Type": "application/json", "Content-Length": str(len(payload))}
        handler.path, handler.rfile = "/api/fog/fog-1/crystallize", BytesIO(payload)
        handler.do_POST()
    (refused_status, refused), (ok_status, ok) = sent
    assert refused_status == 403 and refused["error"]["code"] == "WRONG_ORIGIN"
    assert ok_status == 200 and ok["data"]["fog"]["status"] == "crystallized"
    review.close()


def test_the_cli_refuses_a_blank_statement_too(tmp_path: Path):
    _seed(tmp_path)
    result = CliRunner().invoke(app, ["fog", "crystallize", "fog-1", "k", " ", "--json", "--root", str(tmp_path)])
    assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "FOG_STATEMENT_REQUIRED"
    assert require_fog(ensure_project(tmp_path), "fog-1").status.value == "open"


def test_the_glossary_says_crystallize_is_on_the_page_and_the_cli():
    context = (Path(__file__).resolve().parents[1] / "CONTEXT.md").read_text()
    assert "crystallize stays a CLI command until the page's node form returns" not in context
    assert "until it opens the same node form" not in context
