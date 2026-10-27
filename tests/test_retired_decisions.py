"""Acceptance, Reference review and a Challenge's dismissal are no decisions any more (ADR-0025 point 24; #323, part 3 of
#283).

The researcher verifies and seals, and a Challenge is withdrawn or answered "not a problem". The page's one entry point
refuses the three, and core keeps no service function or gate of theirs; their old lines stay readable, as point 26
reads them. Only request-review writes a dependency pin. Synthetic projects only.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from proof_cli import proof_map
from proof_cli.errors import ERROR_CODES
from proof_cli.node_states import node_states
from proof_cli.proof_map import (ProofMapError, apply_decision, create_node, get_challenge, get_dependency_pin, open_challenge,
                                  prepare_decision)
from proof_cli.storage import ensure_project


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def test_the_page_s_entry_point_refuses_the_three_and_names_what_replaced_them(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L")
    submit_proof(store, "L", claimant_id="agent", scoping_rationale="scoped", content="a proof of L")
    create_node(store, node_id="I", kind="imported_result", statement="I", source_locator="Theorem 1", source_version="v1")
    challenge = open_challenge(store, "L", opened_by="agent", rationale="step 2")
    for kind, target, decision, replaced_by in (("acceptance", "L", "accept", "verifies"), ("reference_review", "I", "reference-review", "verifies"),
                                                ("challenge_resolution", challenge.id, "dismissed", "withdrawn")):
        with pytest.raises(ProofMapError) as refused:
            apply_decision(store, kind, target, decision, reviewer="Researcher <r@example.org>")
        assert refused.value.code == "RETIRED_DECISION" and replaced_by in refused.value.message, kind
        assert _code(lambda: prepare_decision(store, kind, target, decision)) == "RETIRED_DECISION"   # nor is one previewed
    assert not (tmp_path / "proofs" / "L" / "reviews.jsonl").exists() and not (tmp_path / "proofs" / "I" / "reviews.jsonl").exists()


def test_no_service_function_gate_or_error_code_of_the_three_remains():
    for name in ("decide_acceptance", "decide_reference_review", "dismiss_challenge", "AcceptanceDecision",
                 "_require_awaiting_acceptance_review", "_pins_accepted_against", "REFERENCE_REVIEW_DECISIONS"):
        assert not hasattr(proof_map, name), name
    for code in ("NODE_BLOCKED", "NOT_REVIEW_NEEDED", "NODE_REJECTED", "REFERENCE_NOT_CALLABLE", "NOT_IMPORTED_RESULT"):
        assert code not in ERROR_CODES, code


def test_old_lines_stay_readable_as_point_26_reads_them(tmp_path: Path):
    store = ensure_project(tmp_path)
    old = researcher(store)   # writes the lines an older version wrote (`legacy_decisions`)
    create_node(store, node_id="ACC", kind="lemma", statement="an accepted lemma")
    submit_proof(store, "ACC", claimant_id="agent", scoping_rationale="scoped", content="a proof of ACC")
    old.decide_acceptance("ACC", "accept")
    create_node(store, node_id="IMP", kind="imported_result", statement="a reviewed import", source_locator="Theorem 1", source_version="v1")
    old.decide_reference_review("IMP")
    create_node(store, node_id="GONE", kind="imported_result", statement="an import found wanting", source_locator="Theorem 2", source_version="v1")
    old.decide_reference_review("GONE", "no-longer-callable", rationale="retracted")
    challenge = open_challenge(store, "ACC", opened_by="human", rationale="does it hold for n = 1?")
    old.dismiss_challenge(challenge.id, rationale="it does")

    assert node_states(store, "ACC").proof_layer == "expert-verified"
    assert node_states(store, "IMP").proof_layer == "expert-verified"
    assert node_states(store, "GONE").seal == "sealed-false"
    assert get_challenge(store, challenge.id).status.value == "dismissed"


def test_an_old_acceptance_writes_no_pin(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="D", kind="lemma", statement="D")
    create_node(store, node_id="N", kind="lemma", statement="N", dependencies=["D"])
    submit_proof(store, "N", claimant_id="agent", scoping_rationale="scoped", content="a proof of N")   # pins D as Provisional
    submit_proof(store, "D", claimant_id="agent", scoping_rationale="scoped", content="a proof of D")
    researcher(store).decide_acceptance("D", "accept")
    taken = get_dependency_pin(store, "N", "D")

    researcher(store).decide_acceptance("N", "accept")

    pin = get_dependency_pin(store, "N", "D")   # only request-review writes a pin (#284's check 2)
    assert (pin.id, pin.pinned_version, pin.pinned_fingerprint) == (taken.id, None, taken.pinned_fingerprint)


def test_rows_from_before_reviews_jsonl_still_move_into_it_and_read_as_point_26_says(tmp_path: Path):
    """The one-time move of pre-ADR-0010 review rows binds an old Reference review and dismissal itself, now that no
    decision of theirs is bound (`authority._legacy_payload`)."""
    from datetime import datetime, timezone

    from proof_cli import authority
    from proof_cli.collaboration import ReviewGovernanceState, ReviewRecord, ReviewRecordKind, _decision_row, _request_row
    from proof_cli.storage import insert_review_history_row

    store = ensure_project(tmp_path)
    create_node(store, node_id="IMP", kind="imported_result", statement="imp", source_locator="T1", source_version="v1")
    create_node(store, node_id="GONE", kind="imported_result", statement="gone", source_locator="T2", source_version="v1")
    create_node(store, node_id="L", kind="lemma", statement="L")
    submit_proof(store, "L", claimant_id="agent", scoping_rationale="scoped", content="a proof of L")
    challenge = open_challenge(store, "L", opened_by="agent", rationale="step 2")
    now = datetime.now(timezone.utc)
    with store.transaction() as conn:
        for object_type, object_id, kind, decision in (
                ("proof_map_node", "IMP", ReviewRecordKind.reference_review, ReviewGovernanceState.approved),
                ("proof_map_node", "GONE", ReviewRecordKind.reference_review, ReviewGovernanceState.rejected),
                ("proof_map_node", "L", ReviewRecordKind.acceptance, ReviewGovernanceState.approved),
                ("challenge", challenge.id, ReviewRecordKind.challenge_resolution, ReviewGovernanceState.dismissed)):
            record = ReviewRecord(object_type=object_type, object_id=object_id, reviewer_id="Old <o@example.org>", kind=kind)
            insert_review_history_row(conn, _request_row(record))
            insert_review_history_row(conn, _decision_row(record, decision, reviewer_id=record.reviewer_id, rationale="old", created_at=now))
        conn.execute("DELETE FROM project_meta WHERE key = ?", (authority._MIGRATED_KEY,))
    authority._MIGRATED.clear()

    authority._migrate_review_history(store)

    assert (node_states(store, "IMP").proof_layer, node_states(store, "GONE").seal, node_states(store, "L").proof_layer) == (
        "expert-verified", "sealed-false", "expert-verified")
    assert get_challenge(store, challenge.id).status.value == "dismissed"
