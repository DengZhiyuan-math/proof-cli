"""Issue #202: `proof reference edit` fixes a citation's bibliography in place, with a reason.

What isn't given keeps its value; id, created_by and created_at never change; each edit is a
`reference_edited` event with the editor, the reason and the old and new values. An imported
result's mathematical interface is not bibliography and is refused with a code.
"""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _researcher import researcher
from proof_cli.cli import app
from proof_cli.proof_map import ProofMapError, create_node, get_reference_review_state, get_workflow_state, require_node
from proof_cli.reference_edit import REFERENCE_EDITED_EVENT, edit_reference
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, get_reference, import_reference, list_events

runner = CliRunner()

HARDY = ReferenceRecord(id="hardy", title="An Introducton to the Theory of Numbers", authors=["G. H. Hardy"], year=1938,
                        source_type=ReferenceSourceType.other, url="https://example.org/hardy", notes="the 4th edition",
                        created_by="agent_reader")


def _edits(store) -> list[dict]:
    return [event.payload for event in list_events(store) if event.kind == REFERENCE_EDITED_EVENT]


def _cli(root: Path, *args: str):
    return runner.invoke(app, ["reference", "edit", *args, "--root", str(root), "--json"])


def test_a_partial_edit_keeps_the_other_fields_and_records_the_old_and_new_values_and_the_reason(tmp_path: Path):
    store = ensure_project(tmp_path)
    before = import_reference(store, HARDY)

    after = edit_reference(store, "hardy", {"title": "An Introduction to the Theory of Numbers", "authors": ["G. H. Hardy", "E. M. Wright"],
                                            "source_type": "textbook"}, edited_by="human", reason="typo; Wright is a co-author")

    assert get_reference(store, "hardy") == after
    assert (after.title, after.authors, after.source_type) == ("An Introduction to the Theory of Numbers", ["G. H. Hardy", "E. M. Wright"], ReferenceSourceType.textbook)
    assert (after.year, after.url, after.notes, after.identifier) == (1938, "https://example.org/hardy", "the 4th edition", "")
    assert (after.id, after.created_by, after.created_at) == (before.id, "agent_reader", before.created_at)
    assert after.updated_at > before.updated_at
    [edit] = _edits(store)
    assert edit == {
        "reference_id": "hardy",
        "by": "human",
        "reason": "typo; Wright is a co-author",
        "fields": {
            "title": {"old": "An Introducton to the Theory of Numbers", "new": "An Introduction to the Theory of Numbers"},
            "authors": {"old": ["G. H. Hardy"], "new": ["G. H. Hardy", "E. M. Wright"]},
            "source_type": {"old": "other", "new": "textbook"},
        },
    }


def test_the_cli_edits_in_place_and_leaves_what_it_isnt_given(tmp_path: Path):
    store = ensure_project(tmp_path)
    import_reference(store, HARDY)

    result = _cli(tmp_path, "hardy", "--year", "1979", "--identifier", "isbn:0-19-853171-0", "--url", "", "--reason", "the 5th edition's metadata", "--by", "agent_reader")

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True and envelope["command"] == "reference.edit"
    assert (envelope["data"]["year"], envelope["data"]["identifier"], envelope["data"]["url"]) == (1979, "isbn:0-19-853171-0", "")
    assert envelope["data"]["title"] == HARDY.title and envelope["data"]["authors"] == HARDY.authors
    [edit] = _edits(store)
    assert edit["by"] == "agent_reader" and set(edit["fields"]) == {"year", "identifier", "url"}
    assert edit["fields"]["url"] == {"old": "https://example.org/hardy", "new": ""}


def test_changing_nothing_records_nothing(tmp_path: Path):
    store = ensure_project(tmp_path)
    import_reference(store, HARDY)
    assert edit_reference(store, "hardy", {"year": 1938}) == get_reference(store, "hardy")
    assert _edits(store) == []


@pytest.mark.parametrize("option, field", [
    ("--statement", "statement"),
    ("--source-locator", "source_locator"),
    ("--source-version", "source_version"),
    ("--reference-id", "reference_id"),
])
def test_editing_the_mathematical_interface_is_refused_with_a_code(tmp_path: Path, option, field):
    store = ensure_project(tmp_path)
    import_reference(store, HARDY)
    create_node(store, node_id="ref_thm", kind="imported_result", statement="every n is a sum of four squares",
                source_locator="Theorem 369", source_version="4th edition", reference_id="hardy")

    result = _cli(tmp_path, "hardy", option, "other", "--title", "Another title", "--reason", "swap the theorem")

    assert result.exit_code == 1
    error = json.loads(result.output)["error"]
    assert error["code"] == "REFERENCE_FIELD_NOT_EDITABLE" and error["field"] == field
    assert "new imported result" in error["message"]
    assert get_reference(store, "hardy") == HARDY.model_copy(update={"created_at": get_reference(store, "hardy").created_at,
                                                                     "updated_at": get_reference(store, "hardy").updated_at})
    node = require_node(store, "ref_thm")
    assert (node.statement, node.source_locator, node.source_version, node.reference_id) == ("every n is a sum of four squares", "Theorem 369", "4th edition", "hardy")
    assert _edits(store) == []


@pytest.mark.parametrize("call, code", [
    (lambda store: edit_reference(store, "nobody", {"year": 2000}, reason="r"), "REFERENCE_NOT_FOUND"),
    (lambda store: edit_reference(store, "hardy", {"year": 2000}), "REFERENCE_EDIT_REASON_REQUIRED"),
    (lambda store: edit_reference(store, "hardy", {"year": 2000}, reason="   "), "REFERENCE_EDIT_REASON_REQUIRED"),
    (lambda store: edit_reference(store, "hardy", {"source_type": "blog"}, reason="r"), "INVALID_SOURCE_TYPE"),
    (lambda store: edit_reference(store, "hardy", {"title": " "}, reason="r"), "REFERENCE_TITLE_REQUIRED"),
    (lambda store: edit_reference(store, "hardy", {"created_by": "human"}, reason="r"), "REFERENCE_FIELD_NOT_EDITABLE"),
    (lambda store: edit_reference(store, "hardy", {"id": "hardy2"}, reason="r"), "REFERENCE_FIELD_NOT_EDITABLE"),
    (lambda store: edit_reference(store, "hardy", {"review_status": "approved"}, reason="r"), "REFERENCE_FIELD_NOT_EDITABLE"),
])
def test_an_edit_that_cant_be_made_is_refused_and_records_nothing(tmp_path: Path, call, code):
    store = ensure_project(tmp_path)
    import_reference(store, HARDY)
    with pytest.raises(ProofMapError) as caught:
        call(store)
    assert caught.value.code == code
    assert get_reference(store, "hardy").year == 1938 and _edits(store) == []


def _git_repo(root: Path) -> Path:
    for args in (("init", "--quiet"), ("config", "user.name", "Ada Researcher"), ("config", "user.email", "ada@example.org")):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    return root


def test_a_researchers_import_meets_a_doi_rule_once_its_identifier_is_added(tmp_path: Path):
    store = ensure_project(_git_repo(tmp_path))
    import_reference(store, HARDY.model_copy(update={"created_by": "human"}))
    create_node(store, node_id="ref_thm", kind="imported_result", statement="every n is a sum of four squares",
                source_locator="Theorem 369", source_version="4th edition", reference_id="hardy")
    create_node(store, node_id="clm_1", kind="claim", statement="uses it", dependencies=["ref_thm"])
    researcher(store).declare_trust_rule("doi", conditions=[{"kind": "identifier_has_doi"}], rationale="resolvable sources")
    assert get_reference_review_state(store, "ref_thm") == "unreviewed"
    assert get_workflow_state(store, "clm_1") == "blocked"

    edit_reference(store, "hardy", {"identifier": "doi:10.1093/oso/9780199219858.001.0001"}, reason="add the DOI")

    assert get_reference_review_state(store, "ref_thm") == "trusted-by-rule"
    assert get_workflow_state(store, "clm_1") == "open"

    edit_reference(store, "hardy", {"identifier": "isbn:0-19-853171-0"}, reason="cite the ISBN instead")
    assert get_reference_review_state(store, "ref_thm") == "unreviewed"  # and stops meeting it, as under ADR-0014
