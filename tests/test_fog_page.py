"""The proof map page's fog data (spec #136): what the drawer will read and the writes it will make, driven
through `ReviewApp` directly. The presentation itself is issue #137; here only the interface is tested."""

from pathlib import Path

import pytest

from _review_client import DirectClient
from proof_cli.fog import add_fog, crystallize_fog, drop_fog, get_fog, list_experiments
from proof_cli.proof_map import create_node
from proof_cli.storage import ensure_project


@pytest.fixture
def page(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L1", kind="lemma", statement="a lemma")
    create_node(store, node_id="C1", kind="claim", statement="a claim", dependencies=["L1"])
    yield store, DirectClient(store)


def _ok(response):
    status, body = response
    assert status == 200 and body["ok"], body
    return body["data"]


def test_the_fog_list_carries_each_open_item_with_its_near_nodes_and_latest_experiment(page):
    store, client = page
    add_fog(store, "the constant is optimal", near=["L1"], notes="n ≤ 10^6 first")
    add_fog(store, "dropped one")
    drop_fog(store, "fog-2", reason="no")
    script = store.root / "proofs" / "L1" / "scratch" / "run.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    _ok(client.post("/api/fog/fog-1/experiment", {"outcome": "supports", "summary": "small cases work", "run_by": "agent_a", "path": "proofs/L1/scratch/run.py"}))

    listed = _ok(client.get("/api/fog"))
    (item,) = listed["items"]
    assert (item["id"], item["text"], item["near"], item["notes"], item["status"]) == ("fog-1", "the constant is optimal", ["L1"], "n ≤ 10^6 first", "open")
    assert item["latest_experiment"]["outcome"] == "supports" and item["latest_experiment"]["path"] == "proofs/L1/scratch/run.py" and item["latest_experiment"]["missing"] is False
    assert [e["seq"] for e in item["experiments"]] == [1] and item["experiment_count"] == 1
    everything = _ok(client.get("/api/fog?all=1"))
    assert [(i["id"], i["status"]) for i in everything["items"]] == [("fog-1", "open"), ("fog-2", "dropped")]
    assert everything["items"][1]["reason"] == "no"


def test_the_page_adds_edits_drops_and_reopens_as_its_git_identity(page):
    store, client = page
    added = _ok(client.post("/api/fog", {"text": "maybe a variational characterisation", "near": ["L1"]}))
    assert added["id"] == "fog-1" and added["near"] == ["L1"] and added["created_by"] == client.app._actor()

    edited = _ok(client.post("/api/fog/fog-1/edit", {"text": "sharper", "near": [], "notes": "see the experiment"}))
    assert (edited["text"], edited["near"], edited["notes"]) == ("sharper", [], "see the experiment")

    dropped = _ok(client.post("/api/fog/fog-1/drop", {"reason": "not going anywhere"}))
    assert dropped["status"] == "dropped" and dropped["dropped_by"] == client.app._actor() and dropped["reason"] == "not going anywhere"
    assert _ok(client.get("/api/fog"))["items"] == []

    reopened = _ok(client.post("/api/fog/fog-1/reopen", {}))
    assert reopened["status"] == "open" and reopened["reason"] is None
    assert get_fog(store, "fog-1").status.value == "open"


@pytest.mark.parametrize("path, body, code", [
    ("/api/fog", {"text": "  "}, "FOG_TEXT_REQUIRED"),
    ("/api/fog", {"text": "x", "near": ["nope"]}, "NODE_NOT_FOUND"),
    ("/api/fog/fog-9/drop", {"reason": "why"}, "FOG_NOT_FOUND"),
    ("/api/fog/fog-1/drop", {}, "FOG_REASON_REQUIRED"),
    ("/api/fog/fog-1/experiment", {"outcome": "maybe", "summary": "s", "run_by": "a"}, "INVALID_OUTCOME"),
    ("/api/fog/fog-1/experiment", {"outcome": "supports", "summary": "s", "run_by": "a", "path": "proofs/L1/none.py"}, "FOG_EXPERIMENT_PATH_INVALID"),
    ("/api/fog/fog-1/nothing", {}, "NOT_FOUND"),
])
def test_a_write_the_page_cannot_make_is_refused_with_the_service_code(page, path, body, code):
    store, client = page
    add_fog(store, "one")
    status, response = client.post(path, body)
    assert status >= 400 and response["error"]["code"] == code
    assert get_fog(store, "fog-1").status.value == "open" and list_experiments(store, "fog-1") == []


def test_an_experiment_recorded_from_the_page_names_the_actor_unless_told_who_ran_it(page):
    store, client = page
    add_fog(store, "one")
    mine = _ok(client.post("/api/fog/fog-1/experiment", {"outcome": "inconclusive", "summary": "unstable"}))
    theirs = _ok(client.post("/api/fog/fog-1/experiment", {"outcome": "refutes", "summary": "counterexample at n = 7", "run_by": "agent_a"}))
    assert (mine["seq"], mine["run_by"]) == (1, client.app._actor()) and (theirs["seq"], theirs["run_by"]) == (2, "agent_a")
    assert get_fog(store, "fog-1").status.value == "open"


def test_the_node_page_carries_the_fog_near_it_and_its_origin(page):
    store, client = page
    add_fog(store, "about L1", near=["L1"])
    add_fog(store, "about both", near=["L1", "C1"])
    add_fog(store, "to be stated", near=["L1"])
    crystallize_fog(store, "fog-3", "C_new", "a precise statement")

    lemma = _ok(client.get("/api/node/L1"))
    assert [(f["id"], f["text"]) for f in lemma["fog_near"]] == [("fog-1", "about L1"), ("fog-2", "about both")] and lemma["crystallized_from"] is None
    assert all("latest_experiment" in f for f in lemma["fog_near"])
    made = _ok(client.get("/api/node/C_new"))
    assert made["crystallized_from"] == "fog-3" and made["fog_near"] == []
    assert made["node"]["derived_from"] == "L1"
