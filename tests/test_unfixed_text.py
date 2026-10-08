"""ADR-0021 point 6: text is unfixed until a Review decision relies on it.

A node's statement, assumptions and named definitions, and a Definition's text, may be restated until the first
Review decision on the node or on a node resting on it (an imported result: its Reference review). The researcher
may restate any unfixed text, an agent only text an agent created. A restatement is a work-log event and makes stale
every verdict on what rests on the text, and the snapshots awaiting a decision there read Potentially stale.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import ensure_key_ideas, submit_proof
from _researcher import researcher

from proof_cli import definitions as D
from proof_cli.cli import app
from proof_cli.proof_map import (
    ProofMapError,
    create_node,
    fixed_by,
    get_integrity_state,
    get_node,
    record_progress,
    request_review,
    restate_node,
    verdicts,
)
from proof_cli.storage import ensure_project, list_events
from proof_cli.vault import working_proof_path

runner = CliRunner()


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def _accepted(store, node_id: str) -> None:
    submit_proof(store, node_id, claimant_id="prover", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def test_an_agent_restates_the_statement_it_wrote_and_the_work_log_records_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="H", kind="lemma", statement="$h(x)=\\sup 1/\\operatorname{Im}$", created_by="reader-1")

    restated = restate_node(store, "H", statement="$h(x)=\\max 1/\\operatorname{Im}$", assumptions=["x in a Siegel set"], reason="the sup is infinite", by="reader-1")

    assert (restated.statement, restated.assumptions) == ("$h(x)=\\max 1/\\operatorname{Im}$", ["x in a Siegel set"])
    assert get_node(store, "H").statement == restated.statement
    [event] = [e for e in list_events(store) if e.kind == "proof_map_node_restated"]
    assert event.entity_id == "H"
    assert event.payload["by"] == "reader-1" and event.payload["reason"] == "the sup is infinite"
    assert event.payload["from"]["statement"] == "$h(x)=\\sup 1/\\operatorname{Im}$"
    assert event.payload["to"]["assumptions"] == ["x in a Siegel set"]


def test_an_agent_may_not_restate_the_researcher_s_text_but_the_researcher_may_restate_any_unfixed_text(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="MAIN", kind="theorem", statement="theirs")
    create_node(store, node_id="L", kind="lemma", statement="an agent's", created_by="reader-1")

    assert _code(lambda: restate_node(store, "MAIN", statement="mine now", reason="r", by="reader-1")) == "RESEARCHER_TEXT"
    assert restate_node(store, "MAIN", statement="better", reason="r", by="human").statement == "better"
    assert restate_node(store, "L", statement="corrected", reason="r", by="human").statement == "corrected"


def test_a_restatement_needs_a_reason_and_a_change(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="s", created_by="reader-1")
    assert _code(lambda: restate_node(store, "L", statement="t", reason=" ", by="reader-1")) == "RESTATE_REASON_REQUIRED"
    assert _code(lambda: restate_node(store, "L", reason="r", by="reader-1")) == "RESTATE_EMPTY"
    assert _code(lambda: restate_node(store, "L", definitions=["nowhere"], reason="r", by="reader-1")) == "DEFINITION_NOT_FOUND"


@pytest.mark.parametrize("decision", ["accept", "revision-requested", "reject"])
def test_the_first_review_decision_on_a_node_fixes_its_text(tmp_path: Path, decision):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="s", created_by="prover-1")
    assert fixed_by(store, "L") is None
    submit_proof(store, "L", claimant_id="prover-1", scoping_rationale="scoped", content="proof")
    record = researcher(store).decide_acceptance("L", decision)

    assert fixed_by(store, "L")["review_id"] == record.id
    with pytest.raises(ProofMapError) as caught:
        restate_node(store, "L", statement="t", reason="r", by="human")
    assert caught.value.code == "TEXT_FIXED"
    assert caught.value.details["fixed_by"]["node_id"] == "L"
    assert caught.value.details["fixed_by"]["review_id"] == record.id


def test_a_decision_on_a_node_resting_on_it_fixes_it_too(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="ref", kind="imported_result", statement="Known", source_locator="doi:x", source_version="v1", created_by="reader-1")
    create_node(store, node_id="L", kind="lemma", statement="s", dependencies=["ref"], created_by="reader-1")
    create_node(store, node_id="T", kind="theorem", statement="t", dependencies=["L"], created_by="reader-1")
    assert fixed_by(store, "ref") is None

    researcher(store).decide_reference_review("ref")  # an imported result: its Reference review fixes it
    assert fixed_by(store, "ref")["node_id"] == "ref"
    assert fixed_by(store, "L") is None

    _accepted(store, "L")
    assert fixed_by(store, "L")["node_id"] == "L"
    assert fixed_by(store, "T") is None


def test_a_definition_is_editable_while_unfixed_even_when_named_and_fixed_by_a_decision_on_a_node_naming_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "height", term="Height", text="$\\sup 1/\\operatorname{Im}$", created_by="reader-1")
    create_node(store, node_id="L", kind="lemma", statement="$h$ is proper", definitions=["height"], created_by="reader-1")
    create_node(store, node_id="T", kind="theorem", statement="t", dependencies=["L"])

    edited = D.edit_definition(store, "height", text="$\\max 1/\\operatorname{Im}$", edited_by="reader-1", reason="the sup is infinite")
    assert edited.text == "$\\max 1/\\operatorname{Im}$"
    [event] = [e for e in list_events(store) if e.kind == "definition_edited"]
    assert event.payload["reason"] == "the sup is infinite"
    assert D.fixed_by_definition(store, "height") is None

    _accepted(store, "L")

    with pytest.raises(ProofMapError) as caught:
        D.edit_definition(store, "height", text="anything", edited_by="human", reason="r")
    assert caught.value.code == "DEFINITION_FIXED"
    assert caught.value.details["fixed_by"]["node_id"] == "L"
    # still named, so never removable
    assert _code(lambda: D.remove_definition(store, "height")) == "DEFINITION_IN_USE"


def test_an_agent_may_not_edit_the_researcher_s_definition(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "unit", term="Unit", text="theirs")
    assert _code(lambda: D.edit_definition(store, "unit", text="mine", edited_by="reader-1", reason="r")) == "RESEARCHER_TEXT"
    assert D.edit_definition(store, "unit", text="better", edited_by="human").text == "better"


def _verified(store, node_id: str) -> dict:
    working_proof_path(store.root, node_id).write_text(f"proof of {node_id}", encoding="utf-8")
    ensure_key_ideas(store, node_id)
    return record_progress(store, node_id, role="verifier", by="v-1", verdict="passed")


def test_a_restatement_makes_stale_the_verdicts_on_the_node_and_on_what_rests_on_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "height", term="Height", text="h", created_by="reader-1")
    create_node(store, node_id="C", kind="claim", statement="c", definitions=["height"], created_by="reader-1")
    create_node(store, node_id="L", kind="lemma", statement="l", dependencies=["C"], created_by="reader-1")
    create_node(store, node_id="other", kind="lemma", statement="o", created_by="reader-1")
    for node_id in ("C", "L", "other"):
        _verified(store, node_id)
    assert not any(v["stale"] for node_id in ("C", "L", "other") for v in verdicts(store, node_id))

    restate_node(store, "C", statement="c'", reason="r", by="reader-1")

    assert verdicts(store, "C")[-1]["stale"] and verdicts(store, "L")[-1]["stale"]
    assert not verdicts(store, "other")[-1]["stale"]
    # a stale verdict opens no gate, though the files are the ones it read
    gate = verdicts(store, "L")[-1]["inputs_sha256"]
    assert _code(lambda: request_review(store, "L", requested_by="prover-1", rationale="scoped", gated_by=gate)) == "VERDICT_STALE"
    # a fresh verdict after the restatement does
    fresh = _verified(store, "L")
    assert not verdicts(store, "L")[-1]["stale"]
    request_review(store, "L", requested_by="prover-1", rationale="scoped", gated_by=fresh["inputs_sha256"])

    # a definition edit is a restatement of every node naming it, and of what rests on them
    _verified(store, "C")
    D.edit_definition(store, "height", text="h'", edited_by="reader-1", reason="r")
    assert verdicts(store, "C")[-1]["stale"]


def test_a_restatement_upstream_makes_a_snapshot_awaiting_a_decision_potentially_stale(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="C", kind="claim", statement="c", created_by="reader-1")
    create_node(store, node_id="L", kind="lemma", statement="l", dependencies=["C"], created_by="reader-1")
    submit_proof(store, "L", claimant_id="prover-1", scoping_rationale="scoped", content="proof")
    assert get_integrity_state(store, "L") == "current"

    restate_node(store, "C", statement="c'", reason="r", by="reader-1")

    assert get_integrity_state(store, "L") == "potentially-stale"
    assert get_integrity_state(store, "C") == "current"  # nothing of C's awaits a decision
    submit_proof(store, "L", claimant_id="prover-1", scoping_rationale="scoped", content="proof, reread")
    assert get_integrity_state(store, "L") == "current"


def test_the_cli_restates_and_edits_with_a_reason(tmp_path: Path):
    ensure_project(tmp_path)

    def run(*args: str, ok: bool = True) -> dict:
        result = runner.invoke(app, [*args, "--root", str(tmp_path), "--json"])
        envelope = json.loads(result.output)
        assert (result.exit_code == 0) == ok and envelope["ok"] == ok, result.output
        return envelope

    run("definition", "add", "unit", "u", "--term", "Unit", "--created-by", "reader-1")
    run("node", "create", "L", "lemma", "s", "--definition", "unit", "--created-by", "reader-1")
    restated = run("node", "restate", "L", "--statement", "s'", "--assumption", "a", "--reason", "clearer", "--by", "reader-1")["data"]
    assert (restated["statement"], restated["assumptions"], restated["fixed_by"]) == ("s'", ["a"], None)
    assert run("definition", "edit", "unit", "--text", "u'", "--reason", "clearer", "--by", "reader-1")["data"]["text"] == "u'"
    shown = run("node", "show", "L")["data"]
    assert shown["fixed_by"] is None
    run("node", "create", "M", "theorem", "theirs")
    assert run("node", "restate", "M", "--statement", "x", "--reason", "r", "--by", "reader-1", ok=False)["error"]["code"] == "RESEARCHER_TEXT"


def test_a_restatement_and_a_definition_edit_are_in_the_work_log_with_who_why_and_what_changed(tmp_path: Path):
    from proof_cli.proof_map import work_log
    from proof_cli.rendering import render_work_log

    store = ensure_project(tmp_path)
    D.add_definition(store, "height", term="Height", text="sup", created_by="reader-1")
    create_node(store, node_id="H", kind="lemma", statement="h is proper", definitions=["height"], created_by="reader-1")
    create_node(store, node_id="other", kind="lemma", statement="o", created_by="reader-1")

    restate_node(store, "H", statement="h is proper on a Siegel set", reason="not proper on all of X", by="reader-1")
    D.edit_definition(store, "height", text="max", edited_by="reader-1", reason="the sup is infinite")

    log = work_log(store, "H")
    restated, edited = [entry for entry in log if entry["kind"] in ("restated", "definition-edited")]
    assert (restated["by"], restated["reason"]) == ("reader-1", "not proper on all of X")
    assert (restated["from"], restated["to"]) == ({"statement": "h is proper"}, {"statement": "h is proper on a Siegel set"})
    assert (edited["by"], edited["definition_id"], edited["reason"]) == ("reader-1", "height", "the sup is infinite")
    assert (edited["from"], edited["to"]) == ({"text": "sup"}, {"text": "max"})
    assert not [entry for entry in work_log(store, "other") if entry["kind"] in ("restated", "definition-edited")]

    text = " ".join(render_work_log("H", log).split())  # as read, whatever the terminal's width
    assert "restated" in text and "not proper on all of X" in text and "h is proper → h is proper on a Siegel set" in text
    assert "definition height edited" in text and "sup → max" in text


def test_a_decision_fixes_only_what_the_decided_snapshot_rested_on_then(tmp_path: Path):
    from proof_cli.proof_map import split_node

    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="theorem", statement="t", created_by="reader-1")
    submit_proof(store, "T", claimant_id="prover-1", scoping_rationale="scoped", content="a first try")
    researcher(store).decide_acceptance("T", "revision-requested")

    split_node(store, "T", [{"id": "c1", "statement": "A"}], created_by="dec-1")

    # T's decision was made before c1 existed: it relied on nothing c1 says
    assert fixed_by(store, "c1") is None
    assert restate_node(store, "c1", statement="A, sharpened", reason="the split's first reading", by="dec-1").statement == "A, sharpened"
    assert fixed_by(store, "T")["node_id"] == "T"


def test_a_decision_on_a_dependent_fixes_a_definition_through_the_node_naming_it(tmp_path: Path):
    from proof_cli.references import ReferenceRecord, ReferenceSourceType
    from proof_cli.storage import import_reference

    store = ensure_project(tmp_path)
    import_reference(store, ReferenceRecord(id="rudin", title="Principles", authors=["W. Rudin"], year=1976, source_type=ReferenceSourceType.textbook))
    researcher(store).declare_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="standard")
    D.add_definition(store, "cont", term="Continuity", text="eps-delta", created_by="reader-1")
    # a rule-trusted citation has no decision of its own: its dependent's decision is the first to rely on its text.
    # The researcher's import, since an agent's meets no rule (ADR-0022); the definition it names is the agent's.
    create_node(store, node_id="ref", kind="imported_result", statement="Heine–Cantor", definitions=["cont"], source_locator="Thm 4.19",
                source_version="3rd", reference_id="rudin")
    create_node(store, node_id="L", kind="lemma", statement="l", dependencies=["ref"], created_by="reader-1")
    assert D.fixed_by_definition(store, "cont") is None

    _accepted(store, "L")

    assert fixed_by(store, "ref")["node_id"] == "L"
    assert D.fixed_by_definition(store, "cont")["node_id"] == "L"
    assert _code(lambda: D.edit_definition(store, "cont", text="anything", edited_by="reader-1", reason="r")) == "DEFINITION_FIXED"


def test_an_agent_may_not_edit_its_own_definition_once_the_researcher_s_text_names_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "height", term="Height", text="sup", created_by="reader-1")
    create_node(store, node_id="MAIN", kind="theorem", statement="h is proper", definitions=["height"])  # the researcher's

    with pytest.raises(ProofMapError) as caught:
        D.edit_definition(store, "height", text="max", edited_by="reader-1", reason="the sup is infinite")
    assert caught.value.code == "RESEARCHER_TEXT"
    assert caught.value.details["nodes"] == ["MAIN"]
    # the researcher may, while it is unfixed
    assert D.edit_definition(store, "height", text="max", edited_by="human", reason="the sup is infinite").text == "max"
