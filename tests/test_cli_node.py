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


def test_node_claim_and_release_human_readable(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])

    claim_result = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"]
    )
    assert claim_result.exit_code == 0
    assert "agent_a" in claim_result.stdout

    release_result = runner.invoke(
        app, ["node", "release", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"]
    )
    assert release_result.exit_code == 0
    assert "agent_a" in release_result.stdout


def test_node_reclaim_same_claimant_is_idempotent_via_cli(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])

    first = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a", "--json"]
    )
    second = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a", "--json"]
    )
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert json.loads(first.stdout)["data"]["id"] == json.loads(second.stdout)["data"]["id"]


def test_node_claim_conflict_json_envelope_includes_details(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    conflict = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert conflict.exit_code != 0
    payload = json.loads(conflict.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CLAIM_CONFLICT"
    assert payload["error"]["details"]["claimant_id"] == "agent_a"


def test_node_release_without_ownership_or_force_is_rejected(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    result = runner.invoke(
        app, ["node", "release", "clm_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "NOT_CLAIMANT"


def test_node_force_release_requires_actor_and_reason(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    missing_reason = runner.invoke(
        app,
        [
            "node", "release", "clm_1", "--root", str(tmp_path),
            "--claimant", "researcher", "--force", "--actor", "researcher", "--json",
        ],
    )
    assert missing_reason.exit_code != 0
    assert json.loads(missing_reason.stdout)["error"]["code"] == "FORCE_RELEASE_REQUIRES_REASON"

    force_release = runner.invoke(
        app,
        [
            "node", "release", "clm_1", "--root", str(tmp_path),
            "--claimant", "researcher", "--force",
            "--actor", "researcher", "--reason", "agent stuck", "--json",
        ],
    )
    assert force_release.exit_code == 0
    payload = json.loads(force_release.stdout)
    assert payload["data"]["released_by"] == "researcher"
    assert payload["data"]["release_reason"] == "agent stuck"


def test_node_submit_human_readable(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    result = runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_a",
            "--content", "By direct computation the claim holds.",
            "--rationale", "This is a single algebraic step; no further decomposition needed.",
        ],
    )
    assert result.exit_code == 0
    assert "clm_1" in result.stdout
    assert "v1" in result.stdout.lower()
    assert (tmp_path / "proofs" / "clm_1" / "v1.md").exists()


def test_node_submit_json_envelope(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    result = runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_a",
            "--content", "proof body",
            "--rationale", "scoped correctly",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["node_id"] == "clm_1"
    assert payload["data"]["version"] == 1
    assert payload["data"]["file_path"] == "proofs/clm_1/v1.md"

    # the claim ended automatically; the node can be claimed by someone else now
    reclaim = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert reclaim.exit_code == 0


def test_node_submit_by_non_claimant_rejected_with_json_error(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    result = runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_b",
            "--content", "proof body",
            "--rationale", "scoped correctly",
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NOT_CLAIMANT"


def test_node_submit_without_claim_rejected_with_json_error(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])

    result = runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_a",
            "--content", "proof body",
            "--rationale", "scoped correctly",
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NO_ACTIVE_CLAIM"


def test_node_submit_without_rationale_rejected(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])

    result = runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_a",
            "--content", "proof body",
            "--rationale", "   ",
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "SCOPING_RATIONALE_REQUIRED"


def test_node_second_submit_creates_v2(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a"])
    runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_a", "--content", "v1 text", "--rationale", "first attempt",
        ],
    )
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_b"])
    second = runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path),
            "--claimant", "agent_b", "--content", "v2 text", "--rationale", "second attempt", "--json",
        ],
    )
    assert second.exit_code == 0
    payload = json.loads(second.stdout)
    assert payload["data"]["version"] == 2
    assert (tmp_path / "proofs" / "clm_1" / "v1.md").exists()
    assert (tmp_path / "proofs" / "clm_1" / "v2.md").exists()
