import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app


runner = CliRunner()


def test_node_create_and_show_human_readable(tmp_path: Path):
    create = runner.invoke(
        app,
        [
            "node",
            "create",
            "thm_main",
            "theorem",
            "A implies B",
            "--root",
            str(tmp_path),
            "--assumption",
            "A",
        ],
    )
    assert create.exit_code == 0
    assert "thm_main" in create.stdout
    assert "theorem" in create.stdout

    show = runner.invoke(app, ["node", "show", "thm_main", "--root", str(tmp_path)])
    assert show.exit_code == 0
    assert "A implies B" in show.stdout


def test_node_create_and_show_json_envelope(tmp_path: Path):
    create = runner.invoke(
        app,
        ["node", "create", "clm_1", "claim", "A claim statement", "--root", str(tmp_path), "--json"],
    )
    assert create.exit_code == 0
    payload = json.loads(create.stdout)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is True
    assert payload["data"]["id"] == "clm_1"
    assert payload["data"]["kind"] == "claim"

    show = runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path), "--json"])
    assert show.exit_code == 0
    show_payload = json.loads(show.stdout)
    assert show_payload["ok"] is True
    assert show_payload["data"]["statement"] == "A claim statement"


def test_node_show_missing_fails_with_json_error_envelope(tmp_path: Path):
    result = runner.invoke(app, ["node", "show", "does_not_exist", "--root", str(tmp_path), "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NODE_NOT_FOUND"
    assert "does_not_exist" in payload["error"]["message"]


def test_node_show_missing_fails_human_readable(tmp_path: Path):
    result = runner.invoke(app, ["node", "show", "does_not_exist", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "does_not_exist" in result.stdout
    assert "{" not in result.stdout


def test_node_create_second_theorem_rejected_with_json_error(tmp_path: Path):
    first = runner.invoke(
        app,
        ["node", "create", "thm_one", "theorem", "First theorem", "--root", str(tmp_path), "--json"],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        ["node", "create", "thm_two", "theorem", "Second theorem", "--root", str(tmp_path), "--json"],
    )
    assert second.exit_code != 0
    payload = json.loads(second.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DUPLICATE_THEOREM"


def test_node_create_invalid_kind_fails_with_json_error_not_a_traceback(tmp_path: Path):
    result = runner.invoke(
        app,
        ["node", "create", "x1", "proposition", "stmt", "--root", str(tmp_path), "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_KIND"


def test_node_create_dangling_dependency_rejected(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "node",
            "create",
            "clm_1",
            "claim",
            "stmt",
            "--root",
            str(tmp_path),
            "--dependency",
            "ghost_node",
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DEPENDENCY_NOT_FOUND"


def test_node_list_json_and_human(tmp_path: Path):
    runner.invoke(app, ["node", "create", "lem_1", "lemma", "Lemma one", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "create", "lem_2", "lemma", "Lemma two", "--root", str(tmp_path)])

    json_result = runner.invoke(app, ["node", "list", "--root", str(tmp_path), "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["ok"] is True
    assert {item["id"] for item in payload["data"]} == {"lem_1", "lem_2"}

    human_result = runner.invoke(app, ["node", "list", "--root", str(tmp_path)])
    assert human_result.exit_code == 0
    assert "lem_1" in human_result.stdout
    assert "lem_2" in human_result.stdout
