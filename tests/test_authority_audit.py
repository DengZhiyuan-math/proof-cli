"""Regression tests for the #35 audit's reproductions, sections A–F.

Every one of these went *around* the signature on the first cut of #35:
through the pin, the registry, tables outside the chains, an older decision,
another project, or a pre-ADR-0009 project's legacy rows.
"""

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from _authenticator import Researcher, SoftwareAuthenticator, enroll, researcher
from proof_cli.authority import (
    project_origin,
    AuthorityError,
    EnrollmentRequest,
    active_reviewer_keys,
    build_decision_payload,
    enroll_reviewer_key,
    revoke_reviewer_key,
    user_config_dir,
)
from proof_cli.collaboration import ReviewGovernanceState, record_review_decision
from proof_cli.domain import Challenge, ChallengeStatus, ProofMapNode, ProofMapNodeKind, utc_now
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    get_acceptance_state,
    get_integrity_state,
    get_node,
    decide_reference_review,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    list_integrity_warnings,
    open_challenge,
    prepare_decision,
    submit_candidate_proof,
)
from proof_cli.signing import DecisionKind, b64url_decode, b64url_encode, public_key_fingerprint
from proof_cli.storage import (
    ensure_project,
    insert_challenge,
    insert_proof_map_node,
    insert_reviewer_key_row,
    list_raw_chain_rows,
)


def _submit(store, node_id: str, *, session: str = "sess_1", content: str | None = None):
    _claim_token = claim_node(store, node_id, claimant_id="agent_a", session_id=session).claim_token
    return submit_candidate_proof(
        store, node_id, claimant_id="agent_a", session_id=session, scoping_rationale="scoped", content=content or f"proof of {node_id}", claim_token=_claim_token)


def _node(store, node_id: str = "clm_1", **fields):
    create_node(store, node_id=node_id, kind=fields.pop("kind", "claim"), statement=fields.pop("statement", f"stmt {node_id}"), **fields)
    return _submit(store, node_id)


def _codes(store) -> list[str]:
    return [warning.code for warning in list_integrity_warnings(store)]


def _raw(store, *statements: str, drop: tuple[str, ...] = ()) -> None:
    """What a same-user agent can do: open the database itself, drop triggers, edit anything."""
    conn = sqlite3.connect(store.db_path)
    for trigger in drop:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def _pins_file() -> Path:
    return user_config_dir() / "reviewer-pins.json"


def _enrollment(store, authenticator, *, signer=None, decision: str = "enroll", **payload_overrides) -> EnrollmentRequest:
    payload = build_decision_payload(
        store,
        DecisionKind.reviewer_enrollment,
        public_key_fingerprint(authenticator.public_key_spki),
        decision,
        credential_id=authenticator.credential_id,
    ).model_copy(update=payload_overrides)
    return EnrollmentRequest(
        credential_id=authenticator.credential_id,
        public_key_spki=b64url_encode(authenticator.public_key_spki),
        alg=authenticator.alg,
        display_name=authenticator.display_name,
        signed_decision=(signer or authenticator).sign(payload, origin=project_origin(store)),
    )


# -- A. an agent can't anchor trust, and nothing re-runs trust on first use --------


def test_a_missing_pin_next_to_a_registry_means_untrusted_and_no_re_tofu(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    _pins_file().unlink()  # the anchor is gone (or the project moved)

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "REVIEWER_PIN_MISSING" in _codes(store)
    agent = SoftwareAuthenticator(display_name="researcher")
    with pytest.raises(AuthorityError) as exc_info:
        enroll(store, agent)
    assert exc_info.value.code == "REGISTRY_NOT_TRUSTED"


def test_an_emptied_registry_with_a_pin_never_re_runs_tofu(tmp_path: Path):
    """The audit's sequence: delete every registry row, then enroll the agent's key."""
    store = ensure_project(tmp_path)
    researcher(store)
    _raw(store, "DELETE FROM reviewer_keys", drop=("reviewer_keys_no_delete",))

    assert "REVIEWER_REGISTRY_EMPTIED" in _codes(store)
    with pytest.raises(AuthorityError) as exc_info:
        enroll(store, SoftwareAuthenticator(display_name="agent"))
    assert exc_info.value.code == "REGISTRY_NOT_TRUSTED"
    assert active_reviewer_keys(store) == []


def test_an_unreadable_pin_file_means_untrusted(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    _pins_file().write_text("{ not json")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "PIN_FILE_UNREADABLE" in _codes(store)


# -- B. the newest decision is the one that counts ----------------------------------


def test_editing_a_rejected_proofs_text_never_brings_back_the_older_acceptance(tmp_path: Path):
    """Accept C1, challenge, reclaim, submit C2, reject C2, then edit C2's vault file."""
    store = ensure_project(tmp_path)
    _node(store)
    reviewer = researcher(store)
    reviewer.decide_acceptance("clm_1", "accept")
    open_challenge(store, "clm_1", opened_by="agent_b", rationale="?")
    c2 = _submit(store, "clm_1", session="sess_2", content="second attempt")
    reviewer.decide_acceptance("clm_1", "reject")

    path = store.root / c2.file_path
    path.write_text(path.read_text() + "x")

    assert get_acceptance_state(store, "clm_1") == "rejected"
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_3")
    assert exc_info.value.code == "NODE_REJECTED"


def test_an_unsigned_decision_can_never_be_added_to_a_signed_review(tmp_path: Path):
    """`record_review_decision(store, R2.id, ...)` with no signature, from plain Python."""
    store = ensure_project(tmp_path)
    _node(store)
    record = researcher(store).decide_acceptance("clm_1", "reject")

    with pytest.raises(AuthorityError) as exc_info:
        record_review_decision(store, record.id, ReviewGovernanceState.approved, reviewer_id="agent")
    assert exc_info.value.code == "HUMAN_REVIEW_REQUIRED"
    assert get_acceptance_state(store, "clm_1") == "rejected"


def test_an_unsigned_row_appended_to_a_signed_review_is_ignored(tmp_path: Path):
    from proof_cli.collaboration import ReviewRecord, _decision_row
    from proof_cli.storage import insert_review_history_row

    store = ensure_project(tmp_path)
    _node(store)
    record = researcher(store).decide_acceptance("clm_1", "accept")
    appended = ReviewRecord(**{**record.model_dump(), "decision": ReviewGovernanceState.revision_requested})
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    insert_review_history_row(
        conn, _decision_row(appended, ReviewGovernanceState.revision_requested, reviewer_id="agent", rationale="", created_at=utc_now())
    )
    conn.commit()
    conn.close()

    assert get_acceptance_state(store, "clm_1") == "accepted"


# -- C. tables outside the chains, and the interface, are checked against signed rows --


def test_editing_an_accepted_nodes_statement_voids_its_acceptance(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    _raw(store, "UPDATE proof_map_nodes SET data = json_set(data, '$.statement', 'P = NP') WHERE id = 'clm_1'")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "DECISION_NO_LONGER_APPLIES" in _codes(store)


def test_editing_an_imported_results_citation_voids_its_reference_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="ref_1", kind="imported_result", statement="Known lemma X", source_locator="doi:good", source_version="v1")
    researcher(store).decide_reference_review("ref_1")
    assert get_reference_review_state(store, "ref_1") == "reviewed"

    _raw(store, "UPDATE proof_map_nodes SET data = json_set(data, '$.source_locator', 'doi:bogus') WHERE id = 'ref_1'")

    assert get_reference_review_state(store, "ref_1") == "unverifiable"


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE challenges SET status = 'dismissed', created_at = '2000-01-01T00:00:00+00:00'",
        "DELETE FROM challenges",
    ],
)
def test_a_challenge_is_resolved_only_by_a_signed_decision_naming_it(tmp_path: Path, tamper: str):
    store = ensure_project(tmp_path)
    for node_id in ("n1", "n2"):
        _node(store, node_id)
    researcher(store).decide_acceptance("n1", "accept")
    earlier = researcher(store).decide_acceptance("n2", "accept")
    challenge = open_challenge(store, "n2", opened_by="agent_b", rationale="step 4?")

    _raw(store, tamper + f", resolution_review_id = '{earlier.id}'" if tamper.startswith("UPDATE") else tamper)

    assert get_integrity_state(store, "n2") == "challenged"
    assert [c.status for c in list_challenges(store, target_node_id="n2")] == [ChallengeStatus.open]
    assert "CHALLENGE_TABLE_MISMATCH" in _codes(store)
    researcher(store).dismiss_challenge(challenge.id, rationale="checked step 4")
    assert get_integrity_state(store, "n2") == "current"


def test_an_accepted_nodes_pins_are_the_signed_ones(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store, "lem_base", kind="lemma")
    researcher(store).decide_acceptance("lem_base", "accept")
    create_node(store, node_id="clm_1", kind="claim", statement="uses base", dependencies=["lem_base"])
    _submit(store, "clm_1")
    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_integrity_state(store, "clm_1") == "current"

    _raw(store, "UPDATE dependency_pins SET pinned_fingerprint = 'junk', pinned_version = 99")

    assert get_integrity_state(store, "clm_1") == "current"
    assert "DEPENDENCY_PIN_MISMATCH" in _codes(store)


def test_flipping_the_kind_column_changes_nothing(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    _raw(store, "UPDATE proof_map_nodes SET kind = 'lemma', data = json_set(data, '$.kind', 'lemma') WHERE id = 'clm_1'")

    assert get_node(store, "clm_1").kind == ProofMapNodeKind.claim
    assert "KIND_MISMATCH" in _codes(store)
    researcher(store).promote_to_lemma("clm_1")
    assert get_node(store, "clm_1").kind == ProofMapNodeKind.lemma


def test_pointing_review_record_id_at_an_old_acceptance_doesnt_cover_a_new_submission(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    record = researcher(store).decide_acceptance("clm_1", "accept")
    open_challenge(store, "clm_1", opened_by="agent_b", rationale="?")
    v2 = _submit(store, "clm_1", session="sess_2", content="unreviewed v2")

    _raw(store, f"UPDATE candidate_proofs SET review_record_id = '{record.id}' WHERE id = '{v2.id}'")

    assert get_workflow_state(store, "clm_1") == "review-needed"


# -- D. the registry --------------------------------------------------------------------


def _revocation(store, target, signer, **payload_overrides):
    payload = build_decision_payload(
        store, DecisionKind.reviewer_enrollment, public_key_fingerprint(target.public_key_spki), "revoke", credential_id=target.credential_id
    ).model_copy(update=payload_overrides)
    return signer.sign(payload, origin=project_origin(store))


def _insert_registry_row(store, request: EnrollmentRequest, *, entry: str = "enroll", credential_id: str | None = None, created_at=None):
    with store.transaction() as conn:
        insert_reviewer_key_row(
            conn,
            {
                "id": f"reviewer_key_raw_{credential_id or request.credential_id}_{entry}",
                "entry": entry,
                "credential_id": credential_id or request.credential_id,
                "public_key_spki": request.public_key_spki,
                "alg": request.alg,
                "fingerprint": public_key_fingerprint(b64url_decode(request.public_key_spki)),
                "display_name": request.display_name,
                "signed_decision": request.signed_decision.model_dump_json(),
                "created_at": (created_at or utc_now()).isoformat() if not isinstance(created_at, str) else created_at,
            },
        )


def test_replaying_an_enrollment_never_un_revokes_a_key(tmp_path: Path):
    store = ensure_project(tmp_path)
    k1, k2 = SoftwareAuthenticator(display_name="k1"), SoftwareAuthenticator(display_name="k2")
    enroll(store, k1)
    k2_enrollment = _enrollment(store, k2, signer=k1)
    enroll_reviewer_key(store, k2_enrollment)
    revoke_reviewer_key(store, _revocation(store, k2, k1))

    # the same signed enrollment, re-appended — once as is, once under a new credential id
    _insert_registry_row(store, k2_enrollment)
    _insert_registry_row(store, k2_enrollment, credential_id="another-credential")

    assert [key.display_name for key in active_reviewer_keys(store)] == ["k1"]
    assert _codes(store).count("INVALID_REGISTRY_ENTRY") == 2


def test_deleting_the_newest_revocation_is_detected(tmp_path: Path):
    store = ensure_project(tmp_path)
    k1, k2 = SoftwareAuthenticator(display_name="k1"), SoftwareAuthenticator(display_name="k2")
    enroll(store, k1)
    enroll(store, k2, signer=k1)
    revoke_reviewer_key(store, _revocation(store, k2, k1))

    last_seq = list_raw_chain_rows(store, "reviewer_keys")[-1]["seq"]
    _raw(store, f"DELETE FROM reviewer_keys WHERE seq = {last_seq}", drop=("reviewer_keys_no_delete",))

    assert "HISTORY_TRUNCATED" in _codes(store)
    assert active_reviewer_keys(store) == []


def test_a_revocation_cant_be_backdated_over_genuine_decisions(tmp_path: Path):
    store = ensure_project(tmp_path)
    k1, k2 = SoftwareAuthenticator(display_name="k1"), SoftwareAuthenticator(display_name="k2")
    enroll(store, k1)
    _node(store)
    Researcher(store, k1).decide_acceptance("clm_1", "accept")
    enroll(store, k2, signer=k1)

    backdated = _revocation(store, k1, k2, signed_at=utc_now() - timedelta(days=365))
    revoke_reviewer_key(store, backdated)

    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_junk_or_naive_registry_rows_never_crash_a_read(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    reviewer = researcher(store)
    reviewer.decide_acceptance("clm_1", "accept")
    junk = SoftwareAuthenticator(display_name="junk")
    request = _enrollment(store, junk, signer=reviewer.authenticator)
    _insert_registry_row(store, request, created_at="2026-01-01T00:00:00")  # naive
    raw = json.loads(request.signed_decision.model_dump_json())
    raw["payload"]["signed_at"] = "2026-01-01T00:00:00"  # naive, inside the signed payload
    _raw(
        store,
        "INSERT INTO reviewer_keys(id, entry, credential_id, public_key_spki, alg, fingerprint, display_name, signed_decision, prev_row_hash, created_at) "
        f"VALUES ('junk2', 'enroll', 'c', 'not-base64!', -7, 'f', 'x', '{json.dumps(raw)}', 'nope', 'not a date')",
    )

    assert get_acceptance_state(store, "clm_1") in {"accepted", "unverifiable"}  # no exception
    assert "INVALID_REGISTRY_ENTRY" in _codes(store)


def test_the_last_active_key_can_never_be_revoked(tmp_path: Path):
    store = ensure_project(tmp_path)
    k1, k2 = SoftwareAuthenticator(display_name="k1"), SoftwareAuthenticator(display_name="k2")
    enroll(store, k1)
    enroll(store, k2, signer=k1)
    revoke_reviewer_key(store, _revocation(store, k2, k1))

    with pytest.raises(AuthorityError) as exc_info:
        revoke_reviewer_key(store, _revocation(store, k1, k1))
    assert exc_info.value.code in {"LAST_REVIEWER_KEY", "NOT_ENROLLED"}
    assert [key.display_name for key in active_reviewer_keys(store)] == ["k1"]


# -- E. another project ------------------------------------------------------------------


def test_a_decision_signed_for_another_project_with_the_same_id_never_verifies(tmp_path: Path):
    """Same display id (`proj_alpha`), same node id, same key — a different project."""
    authenticator = SoftwareAuthenticator()
    a = ensure_project(tmp_path / "a")
    b = ensure_project(tmp_path / "b")
    for store in (a, b):
        create_node(store, node_id="ref_1", kind="imported_result", statement="Known lemma X", source_locator="doi:good", source_version="v1")
        Researcher(store, authenticator)

    signed_for_a = authenticator.sign(prepare_decision(a, "reference_review", "ref_1", "reference-review"), origin=project_origin(a))

    with pytest.raises(ProofMapError) as exc_info:
        decide_reference_review(b, "ref_1", "reference-review", signed_decision=signed_for_a)
    assert exc_info.value.code == "SIGNATURE_MISMATCH"
    assert exc_info.value.details["field"] == "project_instance"


# -- F. a pre-ADR-0009 project never reopens anything --------------------------------------


def test_a_pre_adr_0009_project_keeps_rejects_terminal_and_dismissals_closed(tmp_path: Path):
    """Legacy reject, accept, promote, dismissal and reference review, as a
    project built before #35 would hold them: nodes and Challenges with no
    ledger entry, decisions migrated from collaboration.json, unsigned."""
    from proof_cli.storage import collaboration_state_path

    store = ensure_project(tmp_path)
    for node_id, kind in (("rej", "claim"), ("acc", "lemma"), ("pro", "lemma"), ("ref", "imported_result")):
        insert_proof_map_node(
            store,
            ProofMapNode(
                id=node_id,
                kind=ProofMapNodeKind(kind),
                statement=f"stmt {node_id}",
                source_locator="doi:x" if kind == "imported_result" else None,
                source_version="v1" if kind == "imported_result" else None,
            ),
        )
    for node_id in ("rej", "acc", "pro"):
        _submit(store, node_id)
    legacy_challenge = Challenge(id="ch_legacy", target_node_id="acc", status=ChallengeStatus.dismissed, rationale="old", opened_by="x")
    insert_challenge(store, legacy_challenge)

    def legacy(review_id, node_id, kind, decision):
        return {
            "id": review_id,
            "object_type": "proof_map_node",
            "object_id": node_id,
            "reviewer_id": "researcher",
            "decision": decision,
            "kind": kind,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:01+00:00",
        }

    conn = store.connect()
    # a project built before #33/#35: nothing migrated, nothing adopted into the ledger
    conn.execute("DELETE FROM project_meta WHERE key IN ('review_history_migrated', 'ledger_adopted')")
    conn.commit()
    conn.close()
    collaboration_state_path(store).write_text(
        json.dumps(
            {
                "review_records": [
                    legacy("r_rej", "rej", "acceptance", "rejected"),
                    legacy("r_acc", "acc", "acceptance", "approved"),
                    legacy("r_pro", "pro", "acceptance", "approved"),
                    legacy("r_ref", "ref", "reference_review", "approved"),
                ]
            }
        )
    )

    # the legacy Reject stays terminal: never reopened, never re-decidable
    assert get_acceptance_state(store, "rej") == "rejected"
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "rej", claimant_id="agent", session_id="s")
    assert exc_info.value.code == "NODE_REJECTED"
    agent = Researcher(store, SoftwareAuthenticator(display_name="agent"))  # trust on first use, even
    with pytest.raises(ProofMapError) as exc_info:
        agent.decide_acceptance("rej", "accept")
    assert exc_info.value.code == "NODE_REJECTED"

    # legacy approvals no longer count, but nothing reopens them for an agent to reclaim
    assert get_acceptance_state(store, "acc") == "unverifiable"
    with pytest.raises(ProofMapError) as exc_info:
        claim_node(store, "acc", claimant_id="agent", session_id="s")
    assert exc_info.value.code == "NODE_UNVERIFIABLE"
    assert get_reference_review_state(store, "ref") == "unverifiable"

    # a legacy promote's kind stands; a legacy dismissal keeps its Challenge closed
    assert get_node(store, "pro").kind == ProofMapNodeKind.lemma
    assert [c.status for c in list_challenges(store, target_node_id="acc")] == [ChallengeStatus.dismissed]

    codes = _codes(store)
    assert "UNSIGNED_LEGACY_REJECT" in codes
    assert "UNSIGNED_LEGACY_DISMISSAL" in codes
    assert codes.count("UNSIGNED_DECISION") == 4


# -- second audit round: deleting the newest rows, forged timestamps -----------------------


def test_emptying_the_registry_and_deleting_the_pin_still_never_re_runs_tofu(tmp_path: Path):
    """The project's signed history proves it once had keys."""
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    _raw(store, "DELETE FROM reviewer_keys", drop=("reviewer_keys_no_delete",))
    _pins_file().unlink()

    with pytest.raises(AuthorityError) as exc_info:
        enroll(store, SoftwareAuthenticator(display_name="researcher"))
    assert exc_info.value.code == "REGISTRY_NOT_TRUSTED"
    assert get_acceptance_state(store, "clm_1") != "accepted"


def test_deleting_the_newest_decision_rows_is_detected_and_reopens_nothing(tmp_path: Path):
    """Accept, challenge, resubmit, reject — then delete the reject's rows (the newest in the history)."""
    store = ensure_project(tmp_path)
    _node(store)
    reviewer = researcher(store)
    reviewer.decide_acceptance("clm_1", "accept")
    open_challenge(store, "clm_1", opened_by="agent_b", rationale="?")
    _submit(store, "clm_1", session="sess_2", content="second attempt")
    reject = reviewer.decide_acceptance("clm_1", "reject")

    _raw(store, f"DELETE FROM review_history WHERE review_id = '{reject.id}'", drop=("review_history_no_delete",))

    assert "HISTORY_TRUNCATED" in _codes(store)
    assert get_acceptance_state(store, "clm_1") != "accepted"
    with pytest.raises(ProofMapError):
        claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_3")


def test_deleting_a_challenges_newest_ledger_row_is_detected(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    challenge = open_challenge(store, "clm_1", opened_by="agent_b", rationale="?")

    _raw(
        store,
        f"DELETE FROM proof_ledger WHERE object_id = '{challenge.id}'",
        f"DELETE FROM challenges WHERE id = '{challenge.id}'",
        drop=("proof_ledger_no_delete",),
    )

    assert "HISTORY_TRUNCATED" in _codes(store)
    assert not (get_acceptance_state(store, "clm_1") == "accepted" and get_integrity_state(store, "clm_1") == "current")


def test_deleting_a_middle_ledger_row_and_dismissing_the_row_keeps_the_challenge_open(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    challenge = open_challenge(store, "clm_1", opened_by="agent_b", rationale="?")
    create_node(store, node_id="clm_later", kind="claim", statement="appended after the challenge")

    _raw(
        store,
        f"DELETE FROM proof_ledger WHERE object_id = '{challenge.id}'",
        f"UPDATE challenges SET status = 'dismissed' WHERE id = '{challenge.id}'",
        drop=("proof_ledger_no_delete",),
    )

    assert get_integrity_state(store, "clm_1") == "challenged"
    codes = _codes(store)
    assert "HISTORY_CHAIN_BROKEN" in codes and "CHALLENGE_NOT_IN_LEDGER" in codes


def test_deleting_a_nodes_creation_entry_and_flipping_its_kind_is_flagged(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    _raw(
        store,
        "DELETE FROM proof_ledger WHERE entry = 'node_created' AND object_id = 'clm_1'",
        "UPDATE proof_map_nodes SET kind = 'lemma', data = json_set(data, '$.kind', 'lemma') WHERE id = 'clm_1'",
        drop=("proof_ledger_no_delete",),
    )

    codes = _codes(store)
    assert "NODE_NOT_IN_LEDGER" in codes
    assert "HISTORY_CHAIN_BROKEN" in codes or "HISTORY_TRUNCATED" in codes


def test_editing_an_accepted_nodes_dependency_list_voids_its_acceptance(tmp_path: Path):
    store = ensure_project(tmp_path)
    _node(store, "lem_base", kind="lemma")
    researcher(store).decide_acceptance("lem_base", "accept")
    create_node(store, node_id="clm_1", kind="claim", statement="uses base", dependencies=["lem_base"])
    _submit(store, "clm_1")
    researcher(store).decide_acceptance("clm_1", "accept")

    _raw(store, "UPDATE proof_map_nodes SET data = json_set(data, '$.dependencies', json('[]')) WHERE id = 'clm_1'")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "DECISION_NO_LONGER_APPLIES" in _codes(store)


def test_a_raw_revocation_with_a_forged_timestamp_cant_reach_back(tmp_path: Path):
    """k2 revokes k1 by a row inserted by hand, dated just after k2's enrollment:
    validity follows chain position, so k1's genuine later decision still counts."""
    store = ensure_project(tmp_path)
    k1, k2 = SoftwareAuthenticator(display_name="k1"), SoftwareAuthenticator(display_name="k2")
    enroll(store, k1)
    k2_key = enroll(store, k2, signer=k1)
    _node(store)
    Researcher(store, k1).decide_acceptance("clm_1", "accept")

    revocation = _revocation(store, k1, k2)
    with store.transaction() as conn:
        insert_reviewer_key_row(
            conn,
            {
                "id": "reviewer_key_forged_revoke",
                "entry": "revoke",
                "credential_id": k1.credential_id,
                "public_key_spki": b64url_encode(k1.public_key_spki),
                "alg": k1.alg,
                "fingerprint": public_key_fingerprint(k1.public_key_spki),
                "display_name": "k1",
                "signed_decision": revocation.model_dump_json(),
                "created_at": (k2_key.enrolled_at + timedelta(seconds=1)).isoformat(),
            },
        )

    assert [key.display_name for key in active_reviewer_keys(store)] == ["k2"]  # the revocation itself stands
    assert get_acceptance_state(store, "clm_1") == "accepted"
