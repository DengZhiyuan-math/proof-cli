"""How a run ended is a record, not a value of its state (ADR-0025 point 1, zeqome/proof-agents#46).

A node run's state is only running, paused or not running. How it ended — done, stuck, budget, needs-human, released,
release-failed — and why, is one entry in the node's work log, written as it ends, so a page started afresh reads the
same ending from the record alone, and no reader parses a closing note's words for it. An audit run's ending says it was
an audit, and why its verdict was not recorded on the snapshot when it was not; the audit's outcome itself is the Evidence
check, whose work-log entry carries the checker's mark.

A Coordinator holds no node and takes no turn; where it sets a node aside — parked, held for the researcher, interrupted
by the end of the Pursue's total, or not tried again after its launches failed — that is one record on the node, with
why, which a page started afresh reads as the live Coordinator showed it, parsing no note.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from proof_cli.errors import ERROR_CODES
from proof_cli.proof_map import ASIDE, RUN_ENDINGS, ProofMapError, create_node, record_evidence_check, record_progress, work_log
from proof_cli.rendering import render_work_log_entry
from proof_cli.storage import ensure_project


def _node(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C holds")
    return store


def _endings(store) -> list[dict]:
    return [entry for entry in work_log(store, "clm") if entry["kind"] == "ending"]


def test_a_runs_ending_is_its_own_entry_in_the_work_log(tmp_path: Path):
    store = _node(tmp_path)

    record_progress(store, "clm", role="prover", by="agent", ending="budget", note="this run's cap of 3 turn(s) is spent")

    (entry,) = _endings(store)
    assert (entry["role"], entry["by"], entry["how"], entry["reason"], entry["audit"]) == (
        "prover", "agent", "budget", "this run's cap of 3 turn(s) is spent", False)
    assert "step" not in entry and "status" not in entry  # no step of the role's: the ending is the run's


def test_every_way_a_run_ends_is_recorded_as_it_is(tmp_path: Path):
    store = _node(tmp_path)

    for how in ("done", "stuck", "budget", "needs-human", "released", "release-failed"):
        record_progress(store, "clm", role="prover", by="agent", ending=how, note=f"ended {how}")

    assert RUN_ENDINGS == ("done", "stuck", "budget", "needs-human", "released", "release-failed")
    assert [(entry["how"], entry["reason"]) for entry in _endings(store)] == [(how, f"ended {how}") for how in RUN_ENDINGS]


def test_an_audit_runs_ending_says_so_and_why_its_verdict_was_not_recorded(tmp_path: Path):
    store = _node(tmp_path)

    record_progress(store, "clm", role="verifier", by="agent", ending="done", note="audit failed", audit=True,
                    unrecorded="no snapshot awaits the researcher's review")

    (entry,) = _endings(store)
    assert (entry["audit"], entry["unrecorded"]) == (True, "no snapshot awaits the researcher's review")


def test_a_run_stopped_during_a_turn_names_the_turn_whose_record_comes_after(tmp_path: Path):
    store = _node(tmp_path)

    record_progress(store, "clm", role="prover", by="agent", ending="released", note="stopped and released by the researcher", turn="t1")

    (entry,) = _endings(store)
    assert entry["turn"] == "t1"


@pytest.mark.parametrize("bad", [{"ending": "parked"}, {"ending": "interrupted"}, {"ending": "done", "unrecorded": "why"},
                                 {"ending": "done", "note": " "}, {"ending": "done", "verdict": "passed"},
                                 {"ending": "done", "coordinator": "parked"}, {"ending": "done", "question": "A; B"}])
def test_an_ending_is_one_of_six_with_why_in_an_entry_of_its_own(tmp_path: Path, bad):
    store = _node(tmp_path)

    with pytest.raises(ProofMapError) as refused:
        record_progress(store, "clm", role="prover", by="agent", **{"note": "why", **bad})

    assert refused.value.code == "INVALID_RUN_ENDING" and "INVALID_RUN_ENDING" in ERROR_CODES
    assert _endings(store) == []


def test_an_evidence_check_in_the_work_log_carries_its_checkers_mark(tmp_path: Path):
    store = _node(tmp_path)
    proof = submit_proof(store, "clm", claimant_id="agent", scoping_rationale="scoped", content="proof of clm")

    record_evidence_check(store, proof.id, "failed", run_by="agent/verifier", checker="audit", notes="step 2 has a gap")
    record_evidence_check(store, proof.id, "passed", run_by="an outside checker")

    assert [(entry["outcome"], entry["checker"]) for entry in work_log(store, "clm") if entry["kind"] == "evidence"] == [
        ("failed", "audit"), ("passed", None)]


def test_the_cli_shows_how_a_run_ended_and_why(tmp_path: Path):
    store = _node(tmp_path)
    record_progress(store, "clm", role="prover", by="agent", ending="budget", note="this run's cap of 3 turn(s) is spent")
    record_progress(store, "clm", role="verifier", by="agent", ending="done", note="the Verifier read the snapshot", audit=True,
                    unrecorded="no snapshot awaits the researcher's review")

    first, audit = (render_work_log_entry("clm", entry) for entry in _endings(store))

    assert "run budget — this run's cap of 3 turn(s) is spent" in first
    assert "run done (audit) — the Verifier read the snapshot; its verdict was not recorded on the snapshot: no snapshot awaits" in audit


def test_a_node_the_coordinator_set_aside_is_one_record_on_it_with_why(tmp_path: Path):
    store = _node(tmp_path)

    for how in ("parked", "held", "interrupted", "launch-failed"):
        record_progress(store, "clm", role=None, by="claude-code/coordinator", aside=how, note=f"{how}: why")

    assert ASIDE == ("parked", "held", "interrupted", "launch-failed")
    entries = [entry for entry in work_log(store, "clm") if entry["kind"] == "aside"]
    assert [(entry["how"], entry["reason"], entry["by"], entry["role"]) for entry in entries] == [
        (how, f"{how}: why", "claude-code/coordinator", None) for how in ASIDE]


@pytest.mark.parametrize("bad", [{"aside": "stuck", "note": "why"}, {"aside": "parked", "note": "  "}])
def test_a_node_is_set_aside_one_of_four_ways_and_always_with_why(tmp_path: Path, bad):
    store = _node(tmp_path)

    with pytest.raises(ProofMapError) as refused:
        record_progress(store, "clm", role=None, by="claude-code/coordinator", **bad)

    assert refused.value.code == "INVALID_ASIDE" and "INVALID_ASIDE" in ERROR_CODES
