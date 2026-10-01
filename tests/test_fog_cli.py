"""`proof fog …` (spec #136): the exposed surface only — envelopes, error codes, what `node show` says
about fog, and `project analyze` reading the last dropped item. The rules themselves are tested at the
service layer in tests/test_fog.py."""

import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.fog import add_fog, drop_fog, list_fog, require_fog
from proof_cli.proof_map import create_node, get_node
from proof_cli.storage import ensure_project

runner = CliRunner()


def _project(root: Path):
    store = ensure_project(root)
    create_node(store, node_id="L1", kind="lemma", statement="a lemma")
    create_node(store, node_id="C1", kind="claim", statement="a claim", dependencies=["L1"])
    return store


def _json(root: Path, *args: str, ok: bool = True) -> dict:
    result = runner.invoke(app, [*args, "--root", str(root), "--json"])
    envelope = json.loads(result.output)
    assert (result.exit_code == 0) == ok, result.output
    assert envelope["ok"] == ok
    return envelope


def test_add_list_show_edit_drop_and_reopen_under_json(tmp_path: Path):
    store = _project(tmp_path)

    added = _json(tmp_path, "fog", "add", "the constant is probably optimal", "--near", "L1", "--notes", "try small n", "--created-by", "agent_a")
    assert added["command"] == "fog.add" and added["data"]["id"] == "fog-1" and added["data"]["near"] == ["L1"] and added["data"]["created_by"] == "agent_a"
    _json(tmp_path, "fog", "add", "a second one")

    listed = _json(tmp_path, "fog", "list")
    assert listed["command"] == "fog.list" and [item["id"] for item in listed["data"]] == ["fog-1", "fog-2"]

    edited = _json(tmp_path, "fog", "edit", "fog-2", "--text", "sharper", "--near", "C1")
    assert edited["command"] == "fog.edit" and (edited["data"]["text"], edited["data"]["near"]) == ("sharper", ["C1"])
    assert _json(tmp_path, "fog", "edit", "fog-2", "--clear-near")["data"]["near"] == []

    dropped = _json(tmp_path, "fog", "drop", "fog-2", "--reason", "not going anywhere", "--by", "agent_a")
    assert dropped["command"] == "fog.drop" and (dropped["data"]["status"], dropped["data"]["reason"], dropped["data"]["dropped_by"]) == ("dropped", "not going anywhere", "agent_a")
    assert [item["id"] for item in _json(tmp_path, "fog", "list")["data"]] == ["fog-1"]
    assert [item["id"] for item in _json(tmp_path, "fog", "list", "--all")["data"]] == ["fog-1", "fog-2"]

    reopened = _json(tmp_path, "fog", "reopen", "fog-2")
    assert reopened["command"] == "fog.reopen" and reopened["data"]["status"] == "open"

    shown = _json(tmp_path, "fog", "show", "fog-1")
    assert shown["command"] == "fog.show"
    assert (shown["data"]["text"], shown["data"]["experiments"], shown["data"]["latest_experiment"]) == ("the constant is probably optimal", [], None)
    assert (shown["data"]["folder"], shown["data"]["folder_exists"]) == ("proofs/fog/fog-1", False)
    assert require_fog(store, "fog-1").notes == "try small n"


def test_experiments_are_recorded_and_listed_under_json_and_show_lists_the_newest_first(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "one", near=["L1"])
    script = store.root / "proofs" / "L1" / "scratch" / "run.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")

    first = _json(tmp_path, "fog", "experiment", "record", "fog-1", "supports", "--summary", "small cases work", "--run-by", "agent_a", "--path", "proofs/L1/scratch/run.py")
    assert first["command"] == "fog.experiment.record" and (first["data"]["seq"], first["data"]["outcome"], first["data"]["path"]) == (1, "supports", "proofs/L1/scratch/run.py")
    _json(tmp_path, "fog", "experiment", "record", "fog-1", "error", "--summary", "ran out of memory", "--run-by", "agent_a")

    listed = _json(tmp_path, "fog", "experiment", "list", "fog-1")
    assert listed["command"] == "fog.experiment.list" and [e["seq"] for e in listed["data"]] == [1, 2]
    script.unlink()
    shown = _json(tmp_path, "fog", "show", "fog-1")["data"]
    assert [e["seq"] for e in shown["experiments"]] == [2, 1] and shown["experiments"][1]["missing"] is True
    assert shown["latest_experiment"]["outcome"] == "error"


def test_crystallize_prints_the_node_with_a_fog_field_and_node_show_names_its_origin(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "the second half follows from compactness", near=["L1"])

    made = _json(tmp_path, "fog", "crystallize", "fog-1", "C_new", "If X is compact the second half holds", "--assumption", "X compact", "--created-by", "agent_a")

    assert made["command"] == "fog.crystallize"
    assert made["data"]["id"] == "C_new" and made["data"]["kind"] == "claim" and made["data"]["derived_from"] == "L1" and made["data"]["assumptions"] == ["X compact"]
    assert made["data"]["fog"] == {"id": "fog-1", "status": "crystallized", "node_id": "C_new"} and made["data"]["reminder"] == ""
    assert get_node(store, "L1").dependencies == ["C_new"] and list_fog(store) == []

    shown = _json(tmp_path, "node", "show", "C_new")["data"]
    assert shown["crystallized_from"] == "fog-1" and shown["fog_near"] == []
    add_fog(store, "about the new claim", near=["C_new"])
    assert _json(tmp_path, "node", "show", "C_new")["data"]["fog_near"] == ["fog-2"]
    text = runner.invoke(app, ["node", "show", "C_new", "--root", str(tmp_path)])
    assert "Crystallized from" in text.output and "fog-1" in text.output and "fog-2" in text.output


def test_refusals_are_error_envelopes_with_the_service_codes(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "near two", near=["L1", "C1"])
    drop_fog(store, "fog-1", reason="no")
    add_fog(store, "open, near two", near=["L1", "C1"])

    assert _json(tmp_path, "fog", "show", "fog-9", ok=False)["error"]["code"] == "FOG_NOT_FOUND"
    assert _json(tmp_path, "fog", "edit", "fog-1", "--text", "x", ok=False)["error"]["code"] == "FOG_NOT_OPEN"
    ambiguous = _json(tmp_path, "fog", "crystallize", "fog-2", "X", "s", ok=False)
    assert ambiguous["error"]["code"] == "FOG_PARENT_AMBIGUOUS" and ambiguous["error"]["candidates"] == ["L1", "C1"]
    assert _json(tmp_path, "fog", "crystallize", "fog-2", "X", "s", "--parent", "L1", "--no-parent", ok=False)["error"]["code"] == "FOG_FLAG_CONFLICT"
    assert _json(tmp_path, "fog", "edit", "fog-2", "--near", "L1", "--clear-near", ok=False)["error"]["code"] == "FOG_FLAG_CONFLICT"
    assert _json(tmp_path, "fog", "experiment", "record", "fog-2", "maybe", "--summary", "s", "--run-by", "a", ok=False)["error"]["code"] == "INVALID_OUTCOME"
    assert _json(tmp_path, "fog", "experiment", "record", "fog-2", "supports", "--summary", "  ", "--run-by", "a", ok=False)["error"]["code"] == "FOG_SUMMARY_REQUIRED"
    assert _json(tmp_path, "fog", "experiment", "record", "fog-2", "supports", "--summary", "s", "--run-by", " ", ok=False)["error"]["code"] == "FOG_RUN_BY_REQUIRED"
    assert _json(tmp_path, "fog", "experiment", "record", "fog-2", "supports", "--summary", "s", "--run-by", "a", "--path", "proofs/", ok=False)["error"]["code"] == "FOG_EXPERIMENT_PATH_INVALID"
    assert _json(tmp_path, "fog", "add", "near nothing", "--near", "nope", ok=False)["error"]["code"] == "NODE_NOT_FOUND"
    assert get_node(store, "X") is None


def test_the_human_readable_views_read_as_a_list_and_an_item(tmp_path: Path):
    store = _project(tmp_path)
    empty = runner.invoke(app, ["fog", "list", "--root", str(tmp_path)])
    assert empty.exit_code == 0 and "No fog" in empty.output
    add_fog(store, "the constant is probably optimal", near=["L1"])
    runner.invoke(app, ["fog", "experiment", "record", "fog-1", "supports", "--summary", "small cases work", "--run-by", "agent_a", "--root", str(tmp_path)])
    listed = runner.invoke(app, ["fog", "list", "--root", str(tmp_path)])
    assert listed.exit_code == 0 and "fog-1" in listed.output and "L1" in listed.output and "supports" in listed.output
    shown = runner.invoke(app, ["fog", "show", "fog-1", "--root", str(tmp_path)])
    assert shown.exit_code == 0 and "small cases work" in shown.output and "agent_a" in shown.output and "proofs/fog/fog-1" in shown.output


def test_fog_add_does_not_start_a_project(tmp_path: Path):
    result = runner.invoke(app, ["fog", "add", "x", "--root", str(tmp_path / "nowhere"), "--json"])
    assert result.exit_code != 0 and json.loads(result.output)["error"]["code"] == "PROJECT_NOT_FOUND"
    assert not (tmp_path / "nowhere" / ".proof").exists()


def test_analyze_reports_where_its_route_bottleneck_came_from(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "generating functions by brute force")
    drop_fog(store, "fog-1", reason="the coefficients grow too fast")
    result = runner.invoke(app, ["project", "analyze", "--root", str(tmp_path)])
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert (report["bottleneck_kind"], report["bottleneck_source"]) == ("route", "fog") and "fog-1" in report["bottleneck_summary"]
