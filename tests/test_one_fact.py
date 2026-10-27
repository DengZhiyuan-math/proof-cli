"""One fact in one place (#284, ADR-0025 check 2): what can be computed is not stored again, and each fact has one writer.

A stored copy of a fact another record holds can only disagree with it, and every reader then has to know which one to
believe. Each test here writes through the ordinary core functions and reads the fact back from the one place it
lives; old projects, whose rows still carry the copies, read as before. Synthetic projects only."""

from pathlib import Path

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.authority import list_decisions
from proof_cli.proof_map import create_node, get_acceptance_state
from proof_cli.storage import ensure_project, get_candidate_proof


def test_an_acceptance_lives_in_its_decision_line_and_is_not_copied_onto_the_snapshot(tmp_path: Path):
    """The line in reviews.jsonl names the snapshot it decided and the interface it accepted; the snapshot's row kept a
    copy of each (`review_record_id`, `interface_fingerprint`), which nothing read but an export."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="a claim")
    proof = submit_proof(store, "N", claimant_id="claude-code", scoping_rationale="scoped", content="proof of N")
    researcher(store).decide_acceptance("N", "accept")
    row = get_candidate_proof(store, proof.id)
    assert (row.review_record_id, row.interface_fingerprint) == (None, None)
    (line,) = [d for d in list_decisions(store) if d["kind"] == "acceptance"]
    assert line["payload"].candidate_proof_id == proof.id and line["payload"].interface_fingerprint
    assert get_acceptance_state(store, "N") == "accepted"   # read from the line, as before


def test_whether_an_answer_kept_the_choice_is_read_from_its_redirect(tmp_path: Path):
    """An answer is a redirect or none (ADR-0021 point 8): its `keep` and its `answer` repeated what `redirect` says. The
    work-log entry records the redirect alone; the reading says whether the choice stands, for old entries too."""
    from proof_cli.proof_map import PROGRESS_EVENT, answer_question, questions, record_progress, work_log
    from proof_cli.rendering import render_work_log_entry
    from proof_cli.storage import append_event

    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="theorem", statement="T")
    for _ in range(3):
        record_progress(store, "T", role="prover", by="prover-1", question="read H as the best constant; or any constant")
    kept, redirected, old = (q["id"] for q in questions(store, "T"))
    answer_question(store, "T", kept, keep=True)
    answer_question(store, "T", redirected, answer="any constant that works")
    append_event(store, PROGRESS_EVENT, "an answer from before", entity_id="T",   # as an older version wrote it
                 payload={"kind": "answer", "role": None, "by": "human", "question_id": old, "keep": True, "answer": None, "redirect": None})
    entries = [e for e in work_log(store, "T") if e.get("kind") == "answer"]
    assert [sorted(k for k in ("keep", "answer") if k in e) for e in entries[:2]] == [[], []]   # stored once: the redirect
    answers = {q["id"]: q["answer"] for q in questions(store, "T")}
    assert (answers[kept]["keep"], answers[kept]["redirect"]) == (True, None)
    assert (answers[redirected]["keep"], answers[redirected]["answer"]) == (False, "any constant that works")
    assert answers[old]["keep"] is True
    endings = ["the choice stands", "redirect — any constant that works", "the choice stands"]
    assert all(render_work_log_entry("T", e).endswith(f": {ending}") for e, ending in zip(entries, endings))


def test_the_creation_record_says_what_was_created_and_copies_none_of_the_node(tmp_path: Path):
    """The node's row is the node; its creation record says what happened — which node, of which kind, made by whom —
    and no longer repeats the row (its trust level, who last edited it, its source version), which nothing read."""
    from proof_cli.storage import list_events_of_kind

    store = ensure_project(tmp_path)
    create_node(store, node_id="I", kind="imported_result", statement="cited", source_locator="Theorem 1", source_version="v1",
                created_by="reader-1")
    (event,) = list_events_of_kind(store, "proof_map_node_created")
    assert event.payload == {"node_id": "I", "kind": "imported_result", "created_by": "reader-1"}


def test_who_last_edited_a_node_is_its_edits_record_and_not_a_field_of_the_node(tmp_path: Path):
    """Each edit of a node — a restatement, a dependency added, its medium, a Promote — records who made it; the node's
    `updated_by` repeated the newest of them. It is no longer stored, and a row from before that carries it still loads."""
    import json

    from typer.testing import CliRunner

    from proof_cli.cli import app
    from proof_cli.proof_map import add_dependency, get_node, restate_node

    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L")
    create_node(store, node_id="N", kind="claim", statement="N", created_by="claude-code")
    restate_node(store, "N", statement="N, restated", reason="clearer", by="claude-code")
    add_dependency(store, "N", "L", edited_by="claude-code")
    shown = json.loads(CliRunner().invoke(app, ["node", "show", "N", "--root", str(tmp_path), "--json"]).output)["data"]
    assert "updated_by" not in shown
    with store.connect() as conn:
        (data,) = conn.execute("SELECT data FROM proof_map_nodes WHERE id = 'N'").fetchone()
        assert "updated_by" not in json.loads(data)
        conn.execute("UPDATE proof_map_nodes SET data = json_set(data, '$.updated_by', 'someone') WHERE id = 'N'")   # a row from before
        conn.commit()
    assert get_node(store, "N").statement == "N, restated"


def test_a_claim_a_release_and_an_evidence_check_are_written_with_their_records_or_not_at_all(tmp_path: Path, monkeypatch):
    """A claim's row and its record, a release and its record, an Evidence check and its record were separate commits: a
    failure between them left a claim no record names, or a record of a claim that was never made. Each is one
    transaction now (#284): the record fails, nothing is written."""
    import pytest

    import proof_cli.proof_map as proof_map
    from proof_cli.proof_map import claim_node, list_evidence_checks, record_evidence_check, release_node
    from proof_cli.storage import get_active_claim

    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N")
    proof = submit_proof(store, "N", claimant_id="claude-code", scoping_rationale="scoped", content="proof of N")
    written = proof_map.append_event

    def records_fail(store, kind, *args, **kwargs):
        if kind in ("proof_map_node_claimed", "proof_map_claim_reassigned", "proof_map_claim_released", "proof_map_evidence_check_recorded"):
            raise OSError("disk full")
        return written(store, kind, *args, **kwargs)

    monkeypatch.setattr(proof_map, "append_event", records_fail)
    with pytest.raises(OSError):
        claim_node(store, "N", claimant_id="agent-a")
    assert get_active_claim(store, "N") is None
    monkeypatch.setattr(proof_map, "append_event", written)
    claim_node(store, "N", claimant_id="agent-a")
    monkeypatch.setattr(proof_map, "append_event", records_fail)
    for fails in (lambda: claim_node(store, "N", claimant_id="agent-b", reassign=True), lambda: release_node(store, "N", claimant_id="agent-a"),
                  lambda: record_evidence_check(store, proof.id, "passed", run_by="checker-1")):
        with pytest.raises(OSError):
            fails()
    assert get_active_claim(store, "N").claimant_id == "agent-a" and list_evidence_checks(store, proof.id) == []
