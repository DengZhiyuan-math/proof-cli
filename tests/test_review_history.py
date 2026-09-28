"""Human Review history as an append-only SQLite table (issue #33)."""

import contextvars
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from _authenticator import researcher

import proof_cli.collaboration as collaboration_module
from proof_cli.collaboration import (
    Contributor,
    ReviewGovernanceState,
    ReviewRecordKind,
    list_review_history,
    list_review_history_integrity_warnings,
    list_review_records,
    load_collaboration,
    record_review_decision,
    record_review_request,
    save_collaboration,
    upsert_contributor,
)
from proof_cli.authority import list_authority_warnings
from proof_cli.commands import cmd_review_decide, cmd_review_request
from proof_cli.exchange import export_exchange_bundle, import_exchange_bundle
from proof_cli.proof_map import (
    claim_node,
    create_node,
    get_acceptance_state,
    get_workflow_state,
    open_challenge,
    record_evidence_check,
    submit_candidate_proof,
)
from proof_cli.storage import (
    REVIEW_HISTORY_MIGRATED_KEY,
    ProjectStore,
    active_transaction,
    collaboration_state_path,
    ensure_project,
    list_events,
)

SRC = Path(__file__).resolve().parents[1] / "src"


def _submitted_claim(store, node_id: str):
    create_node(store, node_id=node_id, kind="claim", statement=f"statement of {node_id}")
    claim_node(store, node_id, claimant_id="agent_a", session_id="sess_1")
    return submit_candidate_proof(
        store, node_id, claimant_id="agent_a", session_id="sess_1", scoping_rationale="scoped", content="proof text")


def _accepted_then_resubmitted(store, node_id: str = "clm_1") -> None:
    """An Accepted node with a fresh submission awaiting a new decision —
    the Challenge-driven reclaim, the one way an Accepted node is re-decided."""
    _submitted_claim(store, node_id)
    researcher(store).decide_acceptance(node_id, "accept")
    open_challenge(store, node_id, opened_by="agent_b", rationale="second look")
    claim_node(store, node_id, claimant_id="agent_a", session_id="sess_2")
    submit_candidate_proof(
        store, node_id, claimant_id="agent_a", session_id="sess_2", scoping_rationale="scoped", content="revised proof")
    assert get_workflow_state(store, node_id) == "review-needed"


def _run_python(code: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), *args], env=env, capture_output=True, text=True, timeout=120
    )


# -- concurrency -------------------------------------------------------------


# The parent process holds the passkey and signs; each child only submits
# already-signed decisions, the way an agent or the web app's server would.
_DECIDER = """
import json, sys
from proof_cli.collaboration import Contributor, upsert_contributor
from proof_cli.proof_map import decide_acceptance
from proof_cli.signing import SignedDecision
from proof_cli.storage import load_project

store = load_project(sys.argv[1])
for node_id, raw in json.loads(open(sys.argv[2]).read()).items():
    decide_acceptance(store, node_id, "accept", signed_decision=SignedDecision.model_validate_json(raw))
    # interleave a JSON-backed collaboration write: it used to rewrite the
    # whole file, review records included, and erase other processes' decisions
    upsert_contributor(store, Contributor(display_name=f"reviewer for {node_id}"))
"""


def test_concurrent_decisions_from_several_processes_are_all_kept(tmp_path: Path):
    store = ensure_project(tmp_path)
    node_ids = [f"clm_{index}" for index in range(30)]
    for node_id in node_ids:
        _submitted_claim(store, node_id)
    signed = {node_id: researcher(store).sign("acceptance", node_id, "accept").model_dump_json() for node_id in node_ids}
    batch_files = []
    for offset in range(3):
        batch_file = tmp_path / f"batch_{offset}.json"
        batch_file.write_text(json.dumps({node_id: signed[node_id] for node_id in node_ids[offset::3]}))
        batch_files.append(batch_file)

    env = {**os.environ, "PYTHONPATH": str(SRC)}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", _DECIDER, str(tmp_path), str(batch_file)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for batch_file in batch_files
    ]
    for process in processes:
        _, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, stderr

    assert [get_acceptance_state(store, node_id) for node_id in node_ids] == ["accepted"] * 30
    acceptance_records = [record for record in list_review_records(store) if record.kind == ReviewRecordKind.acceptance]
    assert len(acceptance_records) == 30
    assert all(record.decision == ReviewGovernanceState.approved for record in acceptance_records)


# -- interrupted decisions ----------------------------------------------------


def test_a_decision_failing_after_its_request_leaves_prior_acceptance_unchanged(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    _accepted_then_resubmitted(store)
    rows_before = list_review_history(store)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash between request and decision")

    monkeypatch.setattr(collaboration_module, "record_review_decision", _boom)
    with pytest.raises(RuntimeError):
        researcher(store).decide_acceptance("clm_1", "reject")

    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert get_workflow_state(store, "clm_1") == "review-needed"
    assert list_review_history(store) == rows_before


def test_a_process_killed_between_request_and_decision_leaves_prior_acceptance_unchanged(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted_then_resubmitted(store)
    rows_before = list_review_history(store)
    signed_file = tmp_path / "reject.json"
    signed_file.write_text(researcher(store).sign("acceptance", "clm_1", "reject").model_dump_json())

    result = _run_python(
        """
        import os, sys
        from pathlib import Path
        import proof_cli.collaboration as collaboration
        from proof_cli.proof_map import decide_acceptance
        from proof_cli.signing import SignedDecision
        from proof_cli.storage import load_project

        # die hard, mid-transaction, the instant the request row is written
        collaboration.record_review_decision = lambda *args, **kwargs: os._exit(17)
        signed = SignedDecision.model_validate_json(Path(sys.argv[2]).read_text())
        decide_acceptance(load_project(sys.argv[1]), "clm_1", "reject", signed_decision=signed)
        """,
        str(tmp_path),
        str(signed_file),
    )
    assert result.returncode == 17, result.stderr

    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert list_review_history(store) == rows_before


def test_a_pending_request_never_counts_as_the_latest_decision(tmp_path: Path):
    """An unsigned trust-bearing request is refused at the service layer;
    and even one appended by hand (a request row, no decision) doesn't
    revoke an Acceptance."""
    from proof_cli.authority import AuthorityError
    from proof_cli.collaboration import ReviewRecord, _request_row
    from proof_cli.storage import insert_review_history_row

    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_1")
    researcher(store).decide_acceptance("clm_1", "accept")

    with pytest.raises(AuthorityError):
        record_review_request(store, "proof_map_node", "clm_1", reviewer_id="agent", kind=ReviewRecordKind.acceptance)
    with store.transaction() as conn:
        insert_review_history_row(
            conn,
            _request_row(ReviewRecord(object_type="proof_map_node", object_id="clm_1", reviewer_id="agent", kind=ReviewRecordKind.acceptance)),
        )

    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert get_workflow_state(store, "clm_1") == "open"


# -- append-only --------------------------------------------------------------


def _history_conn(store) -> sqlite3.Connection:
    return store.connect()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE review_history SET decision = 'rejected'",
        "UPDATE review_history SET rationale = 'rewritten' WHERE entry = 'request'",
        "DELETE FROM review_history",
        "DELETE FROM review_history WHERE entry = 'decision'",
    ],
)
def test_review_history_rows_can_never_be_updated_or_deleted(tmp_path: Path, statement: str):
    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_1")
    researcher(store).decide_acceptance("clm_1", "accept")
    rows_before = list_review_history(store)

    conn = _history_conn(store)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(statement)
    conn.rollback()
    conn.close()

    assert list_review_history(store) == rows_before
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_insert_or_replace_cannot_overwrite_a_review_history_row(tmp_path: Path):
    """`INSERT OR REPLACE` resolves a conflict by deleting the old row, which
    wouldn't fire the DELETE trigger — so a colliding insert is refused too."""
    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_1")
    record = researcher(store).decide_acceptance("clm_1", "accept")
    decision_row = next(row for row in list_review_history(store) if row.review_id == record.id and row.entry == "decision")

    conn = _history_conn(store)
    for column, value in (("id", decision_row.id), ("seq", decision_row.seq)):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(
                f"""
                INSERT OR REPLACE INTO review_history({'seq, ' if column == 'seq' else ''}id, review_id, entry,
                  object_type, object_id, kind, decision, reviewer_id, rationale, authorship, provenance_notes, created_at)
                VALUES ({'?, ' if column == 'seq' else ''}?, ?, 'decision', 'proof_map_node', 'clm_1', 'acceptance',
                  'rejected', 'forger', '', '[]', '', '2030-01-01T00:00:00+00:00')
                """,
                ([value] if column == "seq" else []) + [decision_row.id if column == "id" else "decision_forged", record.id],
            )
    conn.rollback()
    conn.close()

    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_decision_row_must_reference_an_existing_request_for_the_same_object(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_1")
    create_node(store, node_id="clm_2", kind="claim", statement="t")
    record = researcher(store).decide_acceptance("clm_1", "reject")

    conn = _history_conn(store)
    for review_id, object_id in (("review_missing", "clm_2"), (record.id, "clm_2")):
        with pytest.raises(sqlite3.DatabaseError, match="existing request"):
            conn.execute(
                """
                INSERT INTO review_history(id, review_id, entry, object_type, object_id, kind, decision,
                  reviewer_id, rationale, authorship, provenance_notes, created_at)
                VALUES (?, ?, 'decision', 'proof_map_node', ?, 'acceptance', 'approved', 'forger', '', '[]', '',
                  '2030-01-01T00:00:00+00:00')
                """,
                (f"decision_{object_id}_{review_id}", review_id, object_id),
            )
    conn.rollback()
    conn.close()

    assert get_acceptance_state(store, "clm_2") == "unreviewed"


def test_redeciding_a_generic_review_appends_rather_than_edits(tmp_path: Path):
    store = ensure_project(tmp_path)
    request = record_review_request(store, "theorem_contract", "thm_main", reviewer_id="advisor", rationale="check it")
    record_review_decision(store, request.id, ReviewGovernanceState.disputed, reviewer_id="advisor", rationale="gap")
    final = record_review_decision(store, request.id, ReviewGovernanceState.approved, reviewer_id="advisor")

    rows = list_review_history(store, review_id=request.id)
    assert [(row.entry, row.decision.value) for row in rows] == [
        ("request", "proposed_for_review"),
        ("decision", "disputed"),
        ("decision", "approved"),
    ]
    assert rows[0].rationale == "check it"
    assert final.decision == ReviewGovernanceState.approved
    assert final.rationale == "gap"  # an empty rationale keeps the last one given
    assert list_review_records(store) == [final]


def test_there_is_no_way_to_delete_a_review_record(tmp_path: Path):
    assert not hasattr(collaboration_module, "delete_review_record")


def test_saving_collaboration_state_cannot_touch_review_history(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted_claim(store, "clm_1")
    researcher(store).decide_acceptance("clm_1", "accept")

    state = load_collaboration(store)
    assert len(state.review_records) == 1
    state.review_records = []
    save_collaboration(store, state)

    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert "review_records" not in json.loads(collaboration_state_path(store).read_text())


# -- generic `proof review` commands can't reach trust-bearing reviews --------


def test_generic_review_decide_refuses_evidence_and_revalidation_records(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted_claim(store, "clm_1")
    check = record_evidence_check(store, proof.id, "passed")
    evidence_review = researcher(store).decide_evidence_review(check.id, "trusted")
    # any genuine signature gets past the service-layer guard; the point here
    # is only that the generic command can't touch the record afterwards
    signature = researcher(store).sign("evidence_review", check.id, "unusable")
    revalidation = collaboration_module.record_decided_review(
        store,
        "proof_map_node",
        "clm_1",
        ReviewGovernanceState.reaffirmed,
        reviewer_id="researcher",
        kind=ReviewRecordKind.dependency_revalidation,
        signed_decision=signature,
    )

    for record in (evidence_review, revalidation):
        with pytest.raises(ValueError, match="can't be re-decided"):
            cmd_review_decide(record.id, "unusable", root=tmp_path)
    assert [row.decision.value for row in list_review_history(store, review_id=evidence_review.id)] == [
        "proposed_for_review",
        "trusted",
    ]

    with pytest.raises(ValueError, match="review app"):
        cmd_review_request("evidence_check", check.id, root=tmp_path)


# -- exchange -----------------------------------------------------------------


def test_exchange_import_never_revokes_or_forges_a_local_decision(tmp_path: Path):
    local = ensure_project(tmp_path / "local")
    _submitted_claim(local, "clm_1")
    researcher(local).decide_acceptance("clm_1", "accept")

    foreign = ensure_project(tmp_path / "foreign")
    bundle = export_exchange_bundle(foreign)
    forged = collaboration_module.ReviewRecord(
        object_type="proof_map_node",
        object_id="clm_1",
        reviewer_id="some-agent",
        decision=ReviewGovernanceState.rejected,
        kind=ReviewRecordKind.acceptance,
    )
    generic = collaboration_module.ReviewRecord(
        object_type="theorem_contract",
        object_id="thm_main",
        reviewer_id="advisor",
        decision=ReviewGovernanceState.disputed,
    )
    bundle.collaboration.review_records = [forged, generic]

    report = import_exchange_bundle(local, bundle)

    assert get_acceptance_state(local, "clm_1") == "accepted"
    assert forged.id not in {record.id for record in list_review_records(local)}
    assert any("not imported" in warning for warning in report.warnings)
    imported_generic = next(record for record in list_review_records(local) if record.id == generic.id)
    assert imported_generic.decision == ReviewGovernanceState.disputed


# -- migration ----------------------------------------------------------------


def _migrated_but_unsigned(store, node_id: str, review_id: str, decision: ReviewGovernanceState) -> None:
    """A JSON-era decision survives the migration intact. Unsigned, an
    approval no longer counts (ADR-0009 point 7) — the node reads
    `unverifiable`, not reopened — while a legacy Reject keeps the node
    terminal (#35 F). Either way it's surfaced to be re-signed."""
    record = next(record for record in list_review_records(store) if record.id == review_id)
    assert (record.object_id, record.decision, record.signed) == (node_id, decision, False)
    expected = "rejected" if decision == ReviewGovernanceState.rejected else "unverifiable"
    assert get_acceptance_state(store, node_id) == expected
    assert any(
        warning.code == "UNSIGNED_DECISION" and warning.details["review_id"] == review_id
        for warning in list_authority_warnings(store)
    )


def _as_pre_review_history_project(store) -> None:
    """Make a fresh test project look like one created before #33, whose
    one-shot migration hasn't run yet."""
    conn = store.connect()
    conn.execute("DELETE FROM project_meta WHERE key = ?", (REVIEW_HISTORY_MIGRATED_KEY,))
    conn.commit()
    conn.close()


def _forged_acceptance(node_id: str, review_id: str = "review_forged") -> dict:
    return {
        "id": review_id,
        "object_type": "proof_map_node",
        "object_id": node_id,
        "reviewer_id": "agent-x",
        "decision": "approved",
        "kind": "acceptance",
    }


def test_legacy_collaboration_json_review_records_migrate_without_loss(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    create_node(store, node_id="clm_2", kind="claim", statement="t")
    project_id = load_collaboration(store).project_id
    _as_pre_review_history_project(store)

    legacy_records = [
        {
            "id": "review_accept1",
            "object_type": "proof_map_node",
            "object_id": "clm_1",
            "reviewer_id": "researcher",
            "decision": "approved",
            "kind": "acceptance",
            "rationale": "checked",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:01+00:00",
        },
        {
            "id": "review_reject2",
            "object_type": "proof_map_node",
            "object_id": "clm_2",
            "reviewer_id": "researcher",
            "decision": "rejected",
            "kind": "acceptance",
            "created_at": "2026-01-02T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:01+00:00",
        },
        {
            "id": "review_pending3",
            "object_type": "theorem_contract",
            "object_id": "thm_main",
            "reviewer_id": "advisor",
            "decision": "proposed_for_review",
            "authorship": ["alice"],
            "provenance_notes": "from the seminar",
            "created_at": "2026-01-03T00:00:00+00:00",
            "updated_at": "2026-01-03T00:00:00+00:00",
        },
    ]
    path = collaboration_state_path(store)
    path.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "contributors": [{"id": "contrib_alice", "display_name": "Alice"}],
                "review_records": legacy_records,
            }
        )
    )

    _migrated_but_unsigned(store, "clm_1", "review_accept1", ReviewGovernanceState.approved)
    _migrated_but_unsigned(store, "clm_2", "review_reject2", ReviewGovernanceState.rejected)
    records = {record.id: record for record in list_review_records(store)}
    assert set(records) == {"review_accept1", "review_reject2", "review_pending3"}
    assert records["review_accept1"].rationale == "checked"
    assert records["review_pending3"].decision == ReviewGovernanceState.proposed_for_review
    assert records["review_pending3"].authorship == ["alice"]
    assert records["review_pending3"].provenance_notes == "from the seminar"

    migrated = json.loads(path.read_text())
    assert "review_records" not in migrated
    assert migrated["contributors"][0]["display_name"] == "Alice"
    assert [event.kind for event in list_events(store)].count("collaboration_review_history_migrated") == 1

    # the same legacy file turning up again (say, restored from a backup)
    # appends nothing twice, and isn't mistaken for an injection either
    rows = list_review_history(store)
    path.write_text(json.dumps({"project_id": project_id, "review_records": legacy_records}))
    assert list_review_history(store) == rows
    upsert_contributor(store, Contributor(display_name="Bob"))
    assert list_review_history(store) == rows
    assert list_review_history_integrity_warnings(store) == []


def test_a_legacy_migration_interrupted_before_the_json_strip_finishes_quietly(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    _as_pre_review_history_project(store)
    path = collaboration_state_path(store)
    path.write_text(json.dumps({"review_records": [_forged_acceptance("clm_1", "review_legacy")]}))

    def _crash(*args, **kwargs):
        raise RuntimeError("simulated crash after the migration committed")

    monkeypatch.setattr(collaboration_module, "_strip_legacy_review_records", _crash)
    with pytest.raises(RuntimeError):
        list_review_records(store)
    monkeypatch.undo()

    _migrated_but_unsigned(store, "clm_1", "review_legacy", ReviewGovernanceState.approved)
    assert "review_records" not in json.loads(path.read_text())
    assert list_review_history_integrity_warnings(store) == []


@pytest.mark.parametrize("pre_existing_json", [False, True])
def test_review_records_injected_into_json_after_migration_are_ignored(tmp_path: Path, pre_existing_json: bool):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_x", kind="claim", statement="s")
    path = collaboration_state_path(store)
    if pre_existing_json:
        # a project that went through the real one-shot migration
        _as_pre_review_history_project(store)
        upsert_contributor(store, Contributor(display_name="Alice"))
        assert get_acceptance_state(store, "clm_x") == "unreviewed"
    rows_before = list_review_history(store)

    data = json.loads(path.read_text()) if path.exists() else {}
    data["review_records"] = [_forged_acceptance("clm_x")]
    path.write_text(json.dumps(data))

    assert get_acceptance_state(store, "clm_x") == "unreviewed"
    assert list_review_history(store) == rows_before
    warnings = list_review_history_integrity_warnings(store)
    assert len(warnings) == 1
    assert warnings[0].payload["records"][0]["reviewer_id"] == "agent-x"

    # the injected records are stripped, so the warning is raised once, not on every read
    assert "review_records" not in json.loads(path.read_text())
    if pre_existing_json:
        assert [contributor.display_name for contributor in load_collaboration(store).contributors] == ["Alice"]
    get_acceptance_state(store, "clm_x")
    assert len(list_review_history_integrity_warnings(store)) == 1


@pytest.mark.parametrize("pre_review_history", [False, True])
def test_a_malformed_review_record_in_json_is_warned_about_not_fatal(tmp_path: Path, pre_review_history: bool):
    """Before or after the one-shot migration, a record that doesn't even
    validate must not wedge every read that derives Human Review state."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    if pre_review_history:
        _as_pre_review_history_project(store)
    legitimate = {**_forged_acceptance("clm_1", "review_legacy"), "reviewer_id": "researcher"}
    bad = {"id": "rv_bad", "decision": "approved"}
    path = collaboration_state_path(store)
    path.write_text(
        json.dumps({"review_records": [bad, legitimate] if pre_review_history else [bad]})
    )

    # the legitimate legacy approval migrates, and (unsigned) reads unverifiable
    expected = "unverifiable" if pre_review_history else "unreviewed"
    assert get_acceptance_state(store, "clm_1") == expected
    assert get_acceptance_state(store, "clm_1") == expected
    if pre_review_history:
        _migrated_but_unsigned(store, "clm_1", "review_legacy", ReviewGovernanceState.approved)

    warnings = list_review_history_integrity_warnings(store)
    assert len(warnings) == 1
    assert warnings[0].payload["malformed"] == [bad]
    assert warnings[0].payload["records"] == []
    assert "review_records" not in json.loads(path.read_text())
    assert "rv_bad" not in {row.review_id for row in list_review_history(store)}


def test_a_non_list_review_records_value_is_warned_about_not_fatal(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    path = collaboration_state_path(store)
    path.write_text(json.dumps({"review_records": {"id": "rv_bad"}}))

    assert get_acceptance_state(store, "clm_1") == "unreviewed"
    assert len(list_review_history_integrity_warnings(store)) == 1
    assert "review_records" not in json.loads(path.read_text())


# -- nested transactions ----------------------------------------------------------


def test_a_legacy_migration_first_triggered_inside_a_decision_joins_it(tmp_path: Path):
    """A decision's precondition reads run while it holds the write lock. If
    one of them triggers the one-shot migration, the migration must join
    that transaction rather than wait on it until the busy timeout."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_old", kind="claim", statement="s")
    _submitted_claim(store, "clm_1")
    _as_pre_review_history_project(store)
    path = collaboration_state_path(store)
    path.write_text(json.dumps({"review_records": [{**_forged_acceptance("clm_old", "review_legacy"), "reviewer_id": "researcher"}]}))

    errors: list[BaseException] = []

    def _decide() -> None:
        try:
            researcher(store).decide_acceptance("clm_1", "accept")
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    worker = threading.Thread(target=_decide)
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive(), "decision deadlocked on its own write lock"
    assert errors == []

    assert get_acceptance_state(store, "clm_1") == "accepted"
    _migrated_but_unsigned(store, "clm_old", "review_legacy", ReviewGovernanceState.approved)
    assert "review_records" not in json.loads(path.read_text())
    assert list_review_history_integrity_warnings(store) == []


def test_a_nested_transaction_rolls_back_with_the_outer_one(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(RuntimeError):
        with store.transaction():
            with store.transaction() as inner:
                record_review_request(store, "theorem_contract", "thm_main", reviewer_id="advisor", conn=inner)
            # a write helper called without `conn` joins the open transaction too
            record_review_request(store, "theorem_contract", "thm_other", reviewer_id="advisor")
            raise RuntimeError("abort the outer transaction")

    assert list_review_history(store) == []


def test_a_nested_transaction_that_raises_undoes_only_its_own_writes(tmp_path: Path):
    store = ensure_project(tmp_path)
    with store.transaction() as outer:
        record_review_request(store, "theorem_contract", "thm_kept", reviewer_id="advisor", conn=outer)
        with pytest.raises(RuntimeError):
            with store.transaction() as inner:
                record_review_request(store, "theorem_contract", "thm_undone", reviewer_id="advisor", conn=inner)
                raise RuntimeError("inner block fails, caller carries on")

    assert [row.object_id for row in list_review_history(store)] == ["thm_kept"]


def test_a_differently_spelled_root_joins_the_same_transaction(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    relative = ProjectStore(Path(tmp_path.name))
    with store.transaction() as conn:
        assert active_transaction(relative) is conn


def test_another_thread_never_joins_this_threads_transaction(tmp_path: Path):
    """A worker that copies this context (as asyncio.to_thread does) must not
    pick up a connection that belongs to another thread."""
    store = ensure_project(tmp_path)
    seen: list[object] = []
    with store.transaction():
        context = contextvars.copy_context()
        worker = threading.Thread(target=lambda: seen.append(context.run(active_transaction, store)))
        worker.start()
        worker.join(timeout=10)
    assert seen == [None]
