"""Trust rules from the CLI (ADR-0014, issue #134): read-only views of the rules in force, and what an
imported result trusted by rule reads under `--json`, so a retrieval-first agent treats it as callable.
No CLI command declares or changes a rule (tests/test_no_cli_decisions.py walks every command for that)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from _researcher import researcher
from proof_cli.cli import app
from proof_cli.proof_map import create_node
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference

runner = CliRunner()

RUDIN = ReferenceRecord(id="rudin", title="Principles of Mathematical Analysis", authors=["Walter Rudin"], year=1976,
                        source_type=ReferenceSourceType.textbook, identifier="isbn:0-07-054235-X")
TEXTBOOKS = [{"kind": "source_type_in", "values": ["textbook", "monograph"]}]


def _project(root: Path, *, rule: bool = True):
    store = ensure_project(root)
    import_reference(store, RUDIN)
    create_node(store, node_id="ref_bw", kind="imported_result", statement="Bolzano-Weierstrass", source_locator="Theorem 3.6",
                source_version="3rd edition", reference_id="rudin")
    if rule:
        researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    return store


def _json(root: Path, *args: str) -> dict:
    result = runner.invoke(app, [*args, "--root", str(root), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_trust_rule_list_json_names_every_rule_in_force_and_its_conditions(tmp_path: Path):
    store = _project(tmp_path)
    researcher(store).declare_trust_rule("gone", conditions=[{"kind": "identifier_has_doi"}], rationale="soon retired")
    researcher(store).retire_trust_rule("gone", rationale="retired")

    envelope = _json(tmp_path, "trust-rule", "list")

    assert envelope["ok"] and envelope["command"] == "trust-rule.list"
    (rule,) = envelope["data"]
    assert (rule["name"], rule["rationale"], rule["retired"]) == ("textbooks", "standard textbooks", False)
    assert rule["conditions"] == TEXTBOOKS and rule["conditions_text"] == ["source_type in {textbook, monograph}"]
    assert rule["declared_by"] == "Researcher <researcher@example.org>"
    assert [r["name"] for r in _json(tmp_path, "trust-rule", "list", "--all")["data"]] == ["textbooks", "gone"]


def test_trust_rule_show_json_carries_the_rules_history(tmp_path: Path):
    store = _project(tmp_path)
    researcher(store).amend_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="tightened")

    envelope = _json(tmp_path, "trust-rule", "show", "textbooks")

    assert envelope["command"] == "trust-rule.show"
    assert envelope["data"]["rationale"] == "tightened"
    assert [(row["decision"], row["rationale"]) for row in envelope["data"]["history"]] == [("declare", "standard textbooks"), ("amend", "tightened")]
    assert envelope["data"]["trusting"] == ["ref_bw"]


def test_an_unknown_rule_is_an_error_envelope(tmp_path: Path):
    _project(tmp_path)
    result = runner.invoke(app, ["trust-rule", "show", "nothing", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "TRUST_RULE_NOT_FOUND"


def test_the_human_readable_views_name_the_rules_and_their_conditions(tmp_path: Path):
    _project(tmp_path)
    listed = runner.invoke(app, ["trust-rule", "list", "--root", str(tmp_path)])
    assert listed.exit_code == 0 and "textbooks" in listed.output and "source_type in {textbook, monograph}" in listed.output
    shown = runner.invoke(app, ["trust-rule", "show", "textbooks", "--root", str(tmp_path)])
    assert shown.exit_code == 0 and "standard textbooks" in shown.output and "declare" in shown.output
    empty = runner.invoke(app, ["trust-rule", "list", "--root", str(_project(tmp_path / "other", rule=False).root)])
    assert empty.exit_code == 0 and "No trust rule" in empty.output


def test_node_show_and_list_json_report_trusted_by_rule_and_the_rules(tmp_path: Path):
    _project(tmp_path)

    shown = _json(tmp_path, "node", "show", "ref_bw")["data"]
    assert shown["acceptance_state"] == "trusted-by-rule" and shown["trust_rule"] == ["textbooks"]
    assert [event["rule"] for event in shown["trust_rule_events"]] == ["textbooks"]

    (listed,) = _json(tmp_path, "node", "list")["data"]
    assert listed["acceptance_state"] == "trusted-by-rule" and listed["trust_rule"] == ["textbooks"]

    text = runner.invoke(app, ["node", "show", "ref_bw", "--root", str(tmp_path)])
    assert "trusted-by-rule" in text.output and "textbooks" in text.output


def test_an_explicitly_reviewed_imported_result_reads_reviewed_under_json(tmp_path: Path):
    store = _project(tmp_path, rule=False)
    researcher(store).decide_reference_review("ref_bw", rationale="checked")
    shown = _json(tmp_path, "node", "show", "ref_bw")["data"]
    assert shown["acceptance_state"] == "reviewed" and shown["trust_rule"] == []
