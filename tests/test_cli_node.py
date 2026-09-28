import json

import pytest
from pathlib import Path

from typer.testing import CliRunner

from _researcher import researcher
from proof_cli.storage import load_project

from proof_cli.cli import app


runner = CliRunner()


def _claim_via_cli(tmp_path: Path, node_id: str, claimant: str) -> None:
    result = runner.invoke(app, ["node", "claim", node_id, "--root", str(tmp_path), "--claimant", claimant, "--json"])
    assert result.exit_code == 0, result.stdout


def _request_review_via_cli(tmp_path: Path, node_id: str, by: str, *, content: str = "proof text", rationale: str = "scoped correctly", json_output: bool = False):
    """Write the node's working proof.tex and request review of it, as an agent does (ADR-0010)."""
    (tmp_path / "proofs" / node_id / "proof.tex").write_text(content)
    args = ["node", "request-review", node_id, "--root", str(tmp_path), "--requested-by", by, "--rationale", rationale]
    return runner.invoke(app, args + (["--json"] if json_output else []))


def _submit_via_cli(tmp_path: Path, node_id: str, claimant: str) -> None:
    _claim_via_cli(tmp_path, node_id, claimant)
    result = _request_review_via_cli(tmp_path, node_id, claimant)
    assert result.exit_code == 0, result.stdout


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
    assert payload["schema_version"] == 1
    assert payload["ok"] is True
    assert payload["command"] == "node.create"
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

    release_result = runner.invoke(app, ["node", "unassign", "clm_1", "--root", str(tmp_path), "--by", "agent_a"])
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
    _claim_via_cli(tmp_path, "clm_1", "agent_a")

    conflict = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert conflict.exit_code != 0
    payload = json.loads(conflict.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CLAIM_CONFLICT"
    assert (payload["error"]["assignee"], payload["error"]["node_id"]) == ("agent_a", "clm_1")

    taken = runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--assignee", "agent_b", "--reassign", "--json"])
    assert taken.exit_code == 0 and json.loads(taken.stdout)["data"]["claimant_id"] == "agent_b"


def test_anyone_can_unassign_a_claim_on_the_cli(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_a")

    result = runner.invoke(app, ["node", "unassign", "clm_1", "--root", str(tmp_path), "--by", "researcher", "--reason", "stale", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["released_by"] == "researcher"


def test_node_request_review_human_readable(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_a")

    result = _request_review_via_cli(
        tmp_path, "clm_1", "agent_a",
        content="By direct computation the claim holds.",
        rationale="This is a single algebraic step; no further decomposition needed.",
    )
    assert result.exit_code == 0
    assert "clm_1" in result.stdout
    assert "v1" in result.stdout.lower()
    assert (tmp_path / "proofs" / "clm_1" / "snapshots" / "v1.tex").exists()


def test_node_request_review_json_envelope(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_a")

    result = _request_review_via_cli(tmp_path, "clm_1", "agent_a", json_output=True)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["node_id"] == "clm_1"
    assert payload["data"]["version"] == 1
    assert payload["data"]["file_path"] == "proofs/clm_1/snapshots/v1.tex"

    # the claim ended automatically; the node can be claimed by someone else now
    reclaim = runner.invoke(
        app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert reclaim.exit_code == 0


def test_node_request_review_needs_no_claim_but_not_someone_elses(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_b")

    result = _request_review_via_cli(tmp_path, "clm_1", "agent_a", json_output=True)
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NOT_CLAIMANT"


def test_node_request_review_without_rationale_rejected(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_a")

    result = _request_review_via_cli(tmp_path, "clm_1", "agent_a", rationale="   ", json_output=True)
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "SCOPING_RATIONALE_REQUIRED"


def test_node_second_request_review_creates_v2(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_a")
    _request_review_via_cli(tmp_path, "clm_1", "agent_a", content="v1 text", rationale="first attempt")
    _claim_via_cli(tmp_path, "clm_1", "agent_b")
    second = _request_review_via_cli(tmp_path, "clm_1", "agent_b", content="v2 text", rationale="second attempt", json_output=True)
    assert second.exit_code == 0
    payload = json.loads(second.stdout)
    assert payload["data"]["version"] == 2
    assert (tmp_path / "proofs" / "clm_1" / "snapshots" / "v1.tex").read_text() == "v1 text"
    assert (tmp_path / "proofs" / "clm_1" / "snapshots" / "v2.tex").read_text() == "v2 text"


def test_node_submit_is_retired(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    result = runner.invoke(
        app, ["node", "submit", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a", "--content", "x", "--rationale", "r"]
    )
    assert result.exit_code != 0
    assert not (tmp_path / "proofs" / "clm_1" / "v1.md").exists()


def _create_claim_and_submit(tmp_path: Path, node_id: str = "clm_1") -> None:
    runner.invoke(app, ["node", "create", node_id, "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, node_id, "agent_a")
    _request_review_via_cli(tmp_path, node_id, "agent_a")


def test_node_create_imported_result_requires_source_fields(tmp_path: Path):
    result = runner.invoke(
        app,
        ["node", "create", "ref_1", "imported_result", "An external theorem", "--root", str(tmp_path), "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "IMPORTED_RESULT_REQUIRES_SOURCE"


def test_node_create_imported_result_json_envelope_includes_source_fields(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "node", "create", "ref_1", "imported_result", "An external theorem", "--root", str(tmp_path),
            "--source-locator", "doi:10.1234/example",
            "--source-version", "v1",
            "--trust-level", "external_reference",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["source_locator"] == "doi:10.1234/example"
    assert payload["data"]["source_version"] == "v1"
    assert payload["data"]["trust_level"] == "external_reference"


def _create_imported_result(tmp_path: Path, node_id: str = "ref_1") -> None:
    runner.invoke(
        app,
        [
            "node", "create", node_id, "imported_result", "An external theorem", "--root", str(tmp_path),
            "--source-locator", "doi:10.1234/example", "--source-version", "v1",
        ],
    )


def test_node_claim_on_imported_result_rejected_with_json_error(tmp_path: Path):
    _create_imported_result(tmp_path)

    result = runner.invoke(
        app, ["node", "claim", "ref_1", "--root", str(tmp_path), "--claimant", "agent_a", "--json"]
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "IMMUTABLE_NODE"


def test_node_show_displays_all_three_axes_human_readable(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])

    result = runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Workflow state" in result.stdout
    assert "Acceptance state" in result.stdout
    assert "Integrity state" in result.stdout
    assert "open" in result.stdout
    assert "unreviewed" in result.stdout
    assert "current" in result.stdout


def test_node_show_axes_json_envelope(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_1", "agent_a")

    result = runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["workflow_state"] == "claimed"
    assert payload["data"]["acceptance_state"] == "unreviewed"
    assert payload["data"]["integrity_state"] == "current"


def test_node_show_workflow_state_blocked_on_dependency(tmp_path: Path):
    runner.invoke(app, ["node", "create", "lem_base", "lemma", "Base lemma", "--root", str(tmp_path)])
    runner.invoke(
        app,
        [
            "node", "create", "clm_1", "claim", "Depends on base", "--root", str(tmp_path),
            "--dependency", "lem_base",
        ],
    )

    result = runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path), "--json"])
    assert json.loads(result.stdout)["data"]["workflow_state"] == "blocked"


def test_frontier_lists_unclaimed_unblocked_nodes_json(tmp_path: Path):
    runner.invoke(app, ["node", "create", "lem_base", "lemma", "Base lemma", "--root", str(tmp_path)])
    runner.invoke(
        app,
        [
            "node", "create", "clm_blocked", "claim", "Blocked claim", "--root", str(tmp_path),
            "--dependency", "lem_base",
        ],
    )
    runner.invoke(app, ["node", "create", "clm_open", "claim", "Open claim", "--root", str(tmp_path)])

    result = runner.invoke(app, ["frontier", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    ids = {item["id"] for item in payload["data"]}
    assert ids == {"lem_base", "clm_open"}


def test_frontier_human_readable(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_open", "claim", "Open claim", "--root", str(tmp_path)])

    result = runner.invoke(app, ["frontier", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "clm_open" in result.stdout


def test_frontier_empty_project_human_readable(tmp_path: Path):
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    result = runner.invoke(app, ["frontier", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No frontier nodes" in result.stdout


def _create_dependent_with_accepted_dependency(tmp_path: Path, dependent: str = "clm_1", target: str = "lem_base") -> None:
    runner.invoke(app, ["node", "create", target, "lemma", "Base lemma", "--root", str(tmp_path)])
    _submit_via_cli(tmp_path, target, "agent_a")
    researcher(load_project(tmp_path)).decide_acceptance(target, "accept")
    runner.invoke(
        app,
        ["node", "create", dependent, "claim", "Depends on base", "--root", str(tmp_path), "--dependency", target],
    )
    _submit_via_cli(tmp_path, dependent, "agent_b")


def _create_and_accept_node(tmp_path: Path, node_id: str = "lem_1", claimant: str = "agent_a") -> None:
    runner.invoke(app, ["node", "create", node_id, "lemma", "stmt", "--root", str(tmp_path)])
    _submit_via_cli(tmp_path, node_id, claimant)
    researcher(load_project(tmp_path)).decide_acceptance(node_id, "accept")


def test_challenge_open_requires_no_confirmation(tmp_path: Path):
    _create_and_accept_node(tmp_path)

    result = runner.invoke(
        app,
        ["challenge", "open", "lem_1", "--root", str(tmp_path), "--opened-by", "any_agent", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "challenge.open"
    assert payload["data"]["target_node_id"] == "lem_1"
    assert payload["data"]["status"] == "open"


def test_challenge_open_against_unaccepted_node_fails(tmp_path: Path):
    runner.invoke(app, ["node", "create", "lem_1", "lemma", "Base lemma", "--root", str(tmp_path)])

    result = runner.invoke(app, ["challenge", "open", "lem_1", "--root", str(tmp_path), "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "TARGET_NOT_ACCEPTED"


def test_challenge_show_human_readable(tmp_path: Path):
    _create_and_accept_node(tmp_path)
    open_result = runner.invoke(app, ["challenge", "open", "lem_1", "--root", str(tmp_path), "--json"])
    challenge_id = json.loads(open_result.stdout)["data"]["id"]

    result = runner.invoke(app, ["challenge", "show", challenge_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "lem_1" in result.stdout
    assert "open" in result.stdout


def test_challenge_list_json(tmp_path: Path):
    _create_and_accept_node(tmp_path)
    runner.invoke(app, ["challenge", "open", "lem_1", "--root", str(tmp_path)])

    result = runner.invoke(app, ["challenge", "list", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert any(item["target_node_id"] == "lem_1" for item in payload["data"])


def test_challenge_dismiss_clears_integrity_overlay(tmp_path: Path):
    _create_and_accept_node(tmp_path)
    open_result = runner.invoke(app, ["challenge", "open", "lem_1", "--root", str(tmp_path), "--json"])
    challenge_id = json.loads(open_result.stdout)["data"]["id"]

    show_challenged = runner.invoke(app, ["node", "show", "lem_1", "--root", str(tmp_path), "--json"])
    assert json.loads(show_challenged.stdout)["data"]["integrity_state"] == "challenged"

    # the dismissal itself is a passkey decision made in the review app
    researcher(load_project(tmp_path)).dismiss_challenge(challenge_id, rationale="checked")

    show_cleared = runner.invoke(app, ["node", "show", "lem_1", "--root", str(tmp_path), "--json"])
    assert json.loads(show_cleared.stdout)["data"]["integrity_state"] == "current"


def test_challenge_unlocks_reclaim_of_accepted_node(tmp_path: Path):
    _create_and_accept_node(tmp_path)

    blocked = runner.invoke(
        app, ["node", "claim", "lem_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert blocked.exit_code != 0
    assert json.loads(blocked.stdout)["error"]["code"] == "NODE_ALREADY_ACCEPTED"

    runner.invoke(app, ["challenge", "open", "lem_1", "--root", str(tmp_path)])

    reclaim = runner.invoke(
        app, ["node", "claim", "lem_1", "--root", str(tmp_path), "--claimant", "agent_b", "--json"]
    )
    assert reclaim.exit_code == 0


def _create_and_accept_claim(tmp_path: Path, node_id: str = "clm_1", claimant: str = "agent_a") -> None:
    runner.invoke(app, ["node", "create", node_id, "claim", "stmt", "--root", str(tmp_path)])
    _submit_via_cli(tmp_path, node_id, claimant)
    researcher(load_project(tmp_path)).decide_acceptance(node_id, "accept")


def test_node_promote_has_no_demote_command(tmp_path: Path):
    result = runner.invoke(app, ["node", "demote", "lem_1", "--root", str(tmp_path)])
    assert result.exit_code != 0


def test_node_split_creates_children_json_envelope(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_parent", "claim", "A big claim", "--root", str(tmp_path)])

    result = runner.invoke(
        app,
        [
            "node", "split", "clm_parent", "--root", str(tmp_path),
            "--child", "clm_child_1=First sub-claim",
            "--child", "clm_child_2=Second sub-claim",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "node.split"
    ids = {item["id"] for item in payload["data"]}
    assert ids == {"clm_child_1", "clm_child_2"}
    assert all(item["derived_from"] == "clm_parent" for item in payload["data"])

    parent_show = runner.invoke(app, ["node", "show", "clm_parent", "--root", str(tmp_path), "--json"])
    parent_deps = set(json.loads(parent_show.stdout)["data"]["dependencies"])
    assert parent_deps == {"clm_child_1", "clm_child_2"}


@pytest.mark.parametrize("json_output", [True, False])
def test_node_split_of_a_node_someone_else_holds_needs_reassign(tmp_path: Path, json_output: bool):
    runner.invoke(app, ["node", "create", "clm_parent", "claim", "A big claim", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, "clm_parent", "agent_b")
    split = ["node", "split", "clm_parent", "--root", str(tmp_path), "--created-by", "agent_a", "--child", "c1=First"]
    flags = ["--json"] if json_output else []

    refused = runner.invoke(app, split + flags)
    assert refused.exit_code == 1
    if json_output:
        assert json.loads(refused.stdout)["error"]["code"] == "NOT_CLAIMANT"
    else:
        assert "claimed by agent_b" in refused.output

    taken_over = runner.invoke(app, split + ["--reassign"] + flags)
    assert taken_over.exit_code == 0, taken_over.output
    show = json.loads(runner.invoke(app, ["node", "show", "clm_parent", "--root", str(tmp_path), "--json"]).stdout)
    assert show["data"]["dependencies"] == ["c1"]


def test_node_split_human_readable(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_parent", "claim", "A big claim", "--root", str(tmp_path)])

    result = runner.invoke(
        app,
        [
            "node", "split", "clm_parent", "--root", str(tmp_path),
            "--child", "clm_child_1=First sub-claim",
        ],
    )
    assert result.exit_code == 0
    assert "clm_child_1" in result.stdout


def test_node_split_on_imported_result_fails(tmp_path: Path):
    runner.invoke(
        app,
        [
            "node", "create", "ref_1", "imported_result", "An external theorem", "--root", str(tmp_path),
            "--source-locator", "doi:10.1234/example", "--source-version", "v1",
        ],
    )

    result = runner.invoke(
        app,
        ["node", "split", "ref_1", "--root", str(tmp_path), "--child", "clm_child_1=A sub-claim", "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "IMMUTABLE_NODE"


def test_node_split_invalid_child_spec_fails(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_parent", "claim", "A big claim", "--root", str(tmp_path)])

    result = runner.invoke(
        app,
        ["node", "split", "clm_parent", "--root", str(tmp_path), "--child", "not-a-valid-spec", "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "INVALID_CHILD_SPEC"


def _create_claimed_and_submitted(tmp_path: Path, node_id: str = "clm_1", claimant: str = "agent_a") -> str:
    runner.invoke(app, ["node", "create", node_id, "claim", "stmt", "--root", str(tmp_path)])
    _claim_via_cli(tmp_path, node_id, claimant)
    submit = _request_review_via_cli(tmp_path, node_id, claimant, json_output=True)
    return json.loads(submit.stdout)["data"]["id"]


def test_node_evidence_record_json_envelope(tmp_path: Path):
    proof_id = _create_claimed_and_submitted(tmp_path)

    result = runner.invoke(
        app,
        [
            "node", "evidence", "record", proof_id, "passed", "--root", str(tmp_path),
            "--notes", "ran the smt backend", "--run-by", "ci-bot", "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "node.evidence.record"
    assert payload["data"]["outcome"] == "passed"
    assert payload["data"]["candidate_proof_id"] == proof_id


def test_node_evidence_record_human_readable(tmp_path: Path):
    proof_id = _create_claimed_and_submitted(tmp_path)

    result = runner.invoke(
        app, ["node", "evidence", "record", proof_id, "passed", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "passed" in result.stdout


def test_node_evidence_record_invalid_outcome_json_error(tmp_path: Path):
    proof_id = _create_claimed_and_submitted(tmp_path)

    result = runner.invoke(
        app, ["node", "evidence", "record", proof_id, "definitely-correct", "--root", str(tmp_path), "--json"]
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "INVALID_OUTCOME"


def test_node_evidence_review_never_touches_acceptance_state(tmp_path: Path):
    proof_id = _create_claimed_and_submitted(tmp_path)
    record = runner.invoke(
        app, ["node", "evidence", "record", proof_id, "passed", "--root", str(tmp_path), "--json"]
    )
    check_id = json.loads(record.stdout)["data"]["id"]
    researcher(load_project(tmp_path)).decide_evidence_review(check_id, "trusted")

    show = runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path), "--json"])
    assert json.loads(show.stdout)["data"]["acceptance_state"] == "unreviewed"


def test_verify_accept_and_reject_commands_no_longer_exist(tmp_path: Path):
    result = runner.invoke(app, ["verify", "accept", "thm_x", "--root", str(tmp_path)])
    assert result.exit_code != 0

    result = runner.invoke(app, ["verify", "reject", "thm_x", "--root", str(tmp_path)])
    assert result.exit_code != 0


HUMAN_ONLY_COMMANDS = [
    ["node", "review", "clm_1", "accept"],
    ["node", "review", "clm_1", "reject"],
    ["node", "review", "ref_1", "reference-review"],
    ["node", "revalidate", "clm_1", "lem_base"],
    ["node", "promote", "clm_1"],
    ["node", "migrate-dependents", "ref_1", "ref_2"],
    ["node", "evidence", "review", "chk_1", "trusted"],
    ["node", "release", "clm_1", "--force", "--reason", "stuck"],
    ["challenge", "dismiss", "ch_1"],
    ["reference", "review", "ref_std", "approve"],
    ["obligation", "resolve", "obl_1"],
]
# whatever an agent tries adding to them
EXTRA_FLAGS = [[], ["--confirm"], ["--signed-decision", "decision.json"], ["--reviewer", "researcher", "--rationale", "trust me"]]


@pytest.mark.parametrize("command", HUMAN_ONLY_COMMANDS, ids=lambda c: " ".join(c[:3]))
@pytest.mark.parametrize("json_output", [True, False])
def test_every_human_only_command_says_where_to_decide_and_changes_nothing(tmp_path: Path, command, json_output):
    """ADR-0009, #37: the CLI never makes a Human Review decision, whatever flags it's given."""
    _create_and_accept_claim(tmp_path)
    store = load_project(tmp_path)
    before = runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path), "--json"]).stdout

    for extra in EXTRA_FLAGS:
        result = runner.invoke(app, [*command, "--root", str(tmp_path), *extra, *(["--json"] if json_output else [])])
        assert result.exit_code != 0, (command, extra)
        if extra in ([], ["--reviewer", "researcher", "--rationale", "trust me"]) or extra == ["--confirm"]:
            pass  # an unknown flag is a usage error (exit 2) — also no decision
        if json_output and result.exit_code == 1:
            error = json.loads(result.stdout)["error"]
            assert error["code"] == "HUMAN_REVIEW_REQUIRED" and error["url"].startswith("http://localhost:")
        elif result.exit_code == 1:
            assert "proof map page" in result.output and "http://localhost:" in result.output

    assert runner.invoke(app, ["node", "show", "clm_1", "--root", str(tmp_path), "--json"]).stdout == before
    assert store  # (the project is untouched)


def test_a_bare_human_only_command_is_a_clean_human_review_required(tmp_path: Path):
    _create_and_accept_claim(tmp_path)
    result = runner.invoke(app, ["node", "review", "clm_1", "accept", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "HUMAN_REVIEW_REQUIRED"
    assert error["url"].endswith("/#/node/clm_1")
