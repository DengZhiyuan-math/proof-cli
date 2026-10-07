"""ADR-0021 points 7–8: a choice is made and recorded, not asked; the Decomposer adds the edges between its own Claims.

A role that would stop for a judgement call picks a reading and records it as a Standing question, open until the
researcher answers it; an answer that differs from the choice is a redirect. A Decomposer may make one of the Claims
its Split created rest on another, while both are unaccepted, without holding either.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher

from proof_cli.cli import app
from proof_cli.proof_map import (
    ProofMapError,
    add_dependency,
    answer_question,
    claim_node,
    create_node,
    get_node,
    questions,
    record_progress,
    split_node,
    work_log,
)
from proof_cli.storage import ensure_project

runner = CliRunner()


def _ask(store, node_id: str = "thm", text: str = "read H as the sup over the cusp; the alternative: over a compact set"):
    return record_progress(store, node_id, role="prover", by="prover-1", question=text)


def test_a_question_is_recorded_in_the_work_log_and_stays_open(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="T")

    entry = _ask(store)

    assert entry["kind"] == "question" and entry["id"].startswith("q_")
    [question] = questions(store, "thm")
    assert (question["id"], question["state"], question["answer"]) == (entry["id"], "open", None)
    assert question["question"].startswith("read H as")
    assert [e["kind"] for e in work_log(store, "thm")] == ["question"]


def test_an_empty_question_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="T")
    with pytest.raises(ProofMapError) as exc_info:
        record_progress(store, "thm", role="prover", by="prover-1", question="  ")
    assert exc_info.value.code == "PROGRESS_EMPTY"


def test_keeping_the_choice_answers_the_question_without_a_redirect(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="T")
    asked = _ask(store)

    answered = answer_question(store, "thm", asked["id"], keep=True)

    assert answered["redirect"] is None
    [question] = questions(store, "thm")
    assert question["state"] == "answered" and question["answer"]["keep"] is True


def test_an_answer_that_differs_is_a_redirect(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="T")
    asked = _ask(store)

    answered = answer_question(store, "thm", asked["id"], answer="over a compact set: the cusp is handled in Lemma 3", by="researcher")

    assert answered["redirect"] == "over a compact set: the cusp is handled in Lemma 3"
    [question] = questions(store, "thm")
    assert question["answer"]["by"] == "researcher" and question["answer"]["keep"] is False


def test_a_question_is_answered_once_and_must_exist(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="T")
    asked = _ask(store)
    answer_question(store, "thm", asked["id"], keep=True)

    with pytest.raises(ProofMapError) as exc_info:
        answer_question(store, "thm", asked["id"], keep=True)
    assert exc_info.value.code == "QUESTION_ANSWERED"
    with pytest.raises(ProofMapError) as exc_info:
        answer_question(store, "thm", "q_nothere", keep=True)
    assert exc_info.value.code == "QUESTION_NOT_FOUND"
    with pytest.raises(ProofMapError) as exc_info:
        answer_question(store, "thm", _ask(store)["id"])
    assert exc_info.value.code == "ANSWER_REQUIRED"


def test_the_cli_records_a_question_answers_it_and_node_show_lists_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="T")
    root = str(tmp_path)

    asked = runner.invoke(app, ["node", "progress", "thm", "--role", "decomposer", "--by", "dec-1", "--question", "split at n=2; the alternative: n=3", "--root", root, "--json"])
    assert asked.exit_code == 0, asked.stdout
    question_id = json.loads(asked.stdout)["data"]["id"]

    shown = json.loads(runner.invoke(app, ["node", "show", "thm", "--root", root, "--json"]).stdout)["data"]
    assert [(q["id"], q["state"]) for q in shown["questions"]] == [(question_id, "open")]

    refused = runner.invoke(app, ["node", "answer", "thm", question_id, "--keep", "--root", root, "--json"], env={"PROOF_AGENT_ROLE": "prover"})
    assert refused.exit_code == 1 and json.loads(refused.stdout)["error"]["code"] == "ANSWER_IS_THE_RESEARCHERS"

    answered = runner.invoke(app, ["node", "answer", "thm", question_id, "--answer", "n=3", "--root", root])
    assert answered.exit_code == 0, answered.stdout
    assert "redirect" in answered.stdout
    shown = json.loads(runner.invoke(app, ["node", "show", "thm", "--root", root, "--json"]).stdout)["data"]
    assert shown["questions"][0]["state"] == "answered"


# -- the Decomposer's own edges


def _split_and_hold(store, created_by: str = "dec-1"):
    create_node(store, node_id="thm", kind="theorem", statement="T")
    split_node(store, "thm", [{"id": "c1", "statement": "A"}, {"id": "c2", "statement": "B"}], created_by=created_by)
    claim_node(store, "c2", claimant_id="prover-2")  # a run is working c2
    return store


def test_the_decomposer_adds_an_edge_between_its_own_claims_without_holding_them(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path))

    edit = add_dependency(store, "c2", "c1", edited_by="dec-1")

    assert edit.node.dependencies == ["c1"]
    assert get_node(store, "c2").dependencies == ["c1"]
    from proof_cli.storage import get_active_claim
    assert get_active_claim(store, "c2").claimant_id == "prover-2"  # nobody's claim was taken over


def test_another_agent_still_needs_the_claim(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path))
    with pytest.raises(ProofMapError) as exc_info:
        add_dependency(store, "c2", "c1", edited_by="dec-2")
    assert exc_info.value.code == "NOT_CLAIMANT"


def test_an_edge_onto_a_node_the_split_did_not_create_still_needs_the_claim(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path))
    create_node(store, node_id="lem", kind="lemma", statement="L", created_by="dec-1")
    with pytest.raises(ProofMapError) as exc_info:
        add_dependency(store, "c2", "lem", edited_by="dec-1")
    assert exc_info.value.code == "NOT_CLAIMANT"


def test_an_accepted_claim_takes_no_decomposer_edge_without_its_claim(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path))
    submit_proof(store, "c1", claimant_id="prover-1", scoping_rationale="scoped", content="proof")
    researcher(store).decide_acceptance("c1", "accept")

    with pytest.raises(ProofMapError) as exc_info:
        add_dependency(store, "c2", "c1", edited_by="dec-1")  # onto an Accepted Claim: the target is not unaccepted
    assert exc_info.value.code == "NOT_CLAIMANT"


def test_claims_of_different_parents_take_no_decomposer_edge_without_the_claim(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path))
    create_node(store, node_id="other", kind="lemma", statement="O")
    split_node(store, "other", [{"id": "d1", "statement": "D"}], created_by="dec-1")

    with pytest.raises(ProofMapError) as exc_info:
        add_dependency(store, "c2", "d1", edited_by="dec-1")  # the same agent's Claims, but of two Splits
    assert exc_info.value.code == "NOT_CLAIMANT"


def test_the_researcher_s_own_split_takes_no_edge_past_a_run_s_claim(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path), created_by="human")
    with pytest.raises(ProofMapError) as exc_info:
        add_dependency(store, "c2", "c1", edited_by="human")  # the researcher edits as anyone does: --reassign
    assert exc_info.value.code == "NOT_CLAIMANT"


def test_a_decomposer_edge_that_would_close_a_cycle_is_refused(tmp_path: Path):
    store = _split_and_hold(ensure_project(tmp_path))
    add_dependency(store, "c2", "c1", edited_by="dec-1")

    with pytest.raises(ProofMapError) as exc_info:
        add_dependency(store, "c1", "c2", edited_by="dec-1")
    assert exc_info.value.code == "DEPENDENCY_CYCLE"
