"""One fact in one place (#284): a Challenge's ending (who closed it, when, why) is read from the decision that closed
it, and nothing copies it onto the Challenge's own row."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from proof_cli import storage
from proof_cli.proof_map import ProofMapError, claim_node, create_node, get_challenge, open_challenge
from proof_cli.storage import ensure_project


def _accepted(store, node_id: str) -> None:
    create_node(store, node_id=node_id, kind="lemma", statement=f"{node_id} holds")
    submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="first", content="proof text")
    researcher(store).decide_acceptance(node_id, "accept")


def _decided_at(root: Path, node_id: str, review_id: str) -> datetime:
    """When the decision line `review_id` in the node's reviews.jsonl says it was made."""
    lines = (root / "proofs" / node_id / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    return next(datetime.fromisoformat(line["decided_at"]) for line in map(json.loads, lines) if line["id"] == review_id)


def _row_untouched(store, challenge_id: str) -> None:
    row = storage.get_challenge(store, challenge_id)
    assert (row.status.value, row.resolved_by, row.resolved_at, row.resolution_review_id) == ("open", None, None, None)


def test_each_ending_is_read_from_the_decision_that_closed_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    who = researcher(store).reviewer_id

    _accepted(store, "L")
    dismissed = open_challenge(store, "L", opened_by="agent_a", rationale="a gap?")
    record = researcher(store).dismiss_challenge(dismissed.id, rationale="no gap: line 3 covers it")
    ended = get_challenge(store, dismissed.id)
    assert (ended.status.value, ended.resolved_by, ended.resolution_review_id, ended.resolution_rationale) == (
        "dismissed", who, record.resolution_review_id, "no gap: line 3 covers it")
    assert ended.resolved_at == _decided_at(tmp_path, "L", ended.resolution_review_id)
    _row_untouched(store, dismissed.id)

    revised = open_challenge(store, "L", opened_by="agent_a", rationale="step 2 is wrong")
    claim_node(store, "L", claimant_id="agent_b", session_id="s2")
    submit_proof(store, "L", claimant_id="agent_b", session_id="s2", scoping_rationale="fixed step 2", content="revised proof")
    acceptance = researcher(store).decide_acceptance("L", "accept")
    ended = get_challenge(store, revised.id)
    assert (ended.status.value, ended.resolved_by, ended.resolution_review_id) == ("resolved-by-revision", who, acceptance.id)
    assert ended.resolved_at == _decided_at(tmp_path, "L", acceptance.id)
    _row_untouched(store, revised.id)

    create_node(store, node_id="R", kind="imported_result", statement="An external theorem", source_locator="doi:10.1/x", source_version="v1")
    researcher(store).decide_reference_review("R", "reference-review")
    reaffirmed = open_challenge(store, "R", opened_by="agent_a", rationale="retracted?")
    review = researcher(store).decide_reference_review("R", "reference-review", rationale="still stands")
    ended = get_challenge(store, reaffirmed.id)
    assert (ended.status.value, ended.resolved_by, ended.resolution_review_id, ended.resolution_rationale) == (
        "dismissed", who, review.id, "still stands")
    assert ended.resolved_at == _decided_at(tmp_path, "R", review.id)
    _row_untouched(store, reaffirmed.id)


def test_a_challenge_closed_on_its_row_before_researcher_decisions_had_lines_still_reads_closed(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store, "L")
    old = open_challenge(store, "L", opened_by="agent_a")
    with contextlib.closing(sqlite3.connect(store.db_path)) as conn, conn:  # as a project from before ADR-0010 kept it
        conn.execute("UPDATE challenges SET status = 'dismissed', resolved_by = 'alice', resolved_at = '2025-01-01T00:00:00+00:00' WHERE id = ?", (old.id,))

    assert get_challenge(store, old.id).status.value == "dismissed"
    with pytest.raises(ProofMapError) as refused:
        researcher(store).dismiss_challenge(old.id)
    assert refused.value.code == "CHALLENGE_NOT_OPEN"


def test_of_two_researcher_decisions_racing_to_close_one_challenge_only_one_is_recorded(tmp_path: Path, monkeypatch):
    first = ensure_project(tmp_path)
    _accepted(first, "L")
    challenge = open_challenge(first, "L", opened_by="agent_a")
    second = ensure_project(tmp_path)
    taking_the_lock = first.transaction

    @contextlib.contextmanager
    def after_the_other_lands():  # the other decision lands between this one's first read and its write lock
        researcher(second).dismiss_challenge(challenge.id, rationale="the other one")
        with taking_the_lock() as conn:
            yield conn

    monkeypatch.setattr(first, "transaction", after_the_other_lands)
    with pytest.raises(ProofMapError) as refused:
        researcher(first).dismiss_challenge(challenge.id, rationale="this one")
    assert refused.value.code == "CHALLENGE_NOT_OPEN"
    monkeypatch.undo()
    assert get_challenge(first, challenge.id).resolution_rationale == "the other one"
    lines = (tmp_path / "proofs" / "L" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["kind"] for line in lines].count("challenge_resolution") == 1
