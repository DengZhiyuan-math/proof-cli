"""Human Review authority is a passkey signature (ADR-0009, issue #35)."""

import importlib
import inspect
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

import proof_cli.proof_map as proof_map
from _authenticator import Researcher, SoftwareAuthenticator, enroll, researcher
from proof_cli.authority import (
    project_origin,
    AuthorityError,
    EnrollmentRequest,
    active_reviewer_keys,
    build_decision_payload,
    enroll_reviewer_key,
    list_reviewer_keys,
    pinned_first_fingerprint,
    revoke_reviewer_key,
    user_config_dir,
)
from proof_cli.cli import app
from proof_cli.collaboration import ReviewGovernanceState, ReviewRecordKind, list_review_records
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    decide_acceptance,
    decide_evidence_review,
    get_acceptance_state,
    get_integrity_state,
    get_node,
    get_reference_review_state,
    get_workflow_state,
    list_integrity_warnings,
    open_challenge,
    prepare_decision,
    record_evidence_check,
    submit_candidate_proof,
)
from proof_cli.signing import ALG_EDDSA, DecisionKind, b64url_encode, public_key_fingerprint
from proof_cli.storage import (
    ensure_project,
    get_active_claim,
    get_dependency_pin,
    upsert_dependency_pin,
)

runner = CliRunner()


def _submitted(store, node_id: str = "clm_1", *, session: str = "sess_1", **fields):
    if get_node(store, node_id) is None:
        create_node(store, node_id=node_id, kind=fields.pop("kind", "claim"), statement=f"stmt {node_id}", **fields)
    _claim_token = claim_node(store, node_id, claimant_id="agent_a", session_id=session).claim_token
    return submit_candidate_proof(
        store, node_id, claimant_id="agent_a", session_id=session, scoping_rationale="scoped", content=f"proof of {node_id}", claim_token=_claim_token)


def _codes(store) -> list[str]:
    return [warning.code for warning in list_integrity_warnings(store)]


# -- every human-only operation ------------------------------------------------------


def _setup_acceptance(store):
    _submitted(store)
    return "acceptance", "clm_1", "accept", {}


def _setup_reference_review(store):
    create_node(store, node_id="ref_1", kind="imported_result", statement="external", source_locator="doi:x", source_version="v1")
    return "reference_review", "ref_1", "reference-review", {}


def _setup_evidence_review(store):
    proof = _submitted(store)
    check = record_evidence_check(store, proof.id, "passed")
    return "evidence_review", check.id, "trusted", {}


def _setup_revalidation(store):
    create_node(store, node_id="lem_base", kind="lemma", statement="base")
    _submitted(store, "lem_base")
    researcher(store).decide_acceptance("lem_base", "accept")
    create_node(store, node_id="clm_1", kind="claim", statement="dependent", dependencies=["lem_base"])
    _submitted(store, "clm_1")
    pin = get_dependency_pin(store, "clm_1", "lem_base")
    upsert_dependency_pin(store, pin.model_copy(update={"pinned_version": 0}))
    return "dependency_revalidation", "clm_1", "reaffirmed", {"dependency_id": "lem_base"}


def _setup_challenge_resolution(store):
    _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    challenge = open_challenge(store, "clm_1", opened_by="agent_b", rationale="looks off")
    return "challenge_resolution", challenge.id, "dismissed", {}


def _setup_promote(store):
    _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    return "promote", "clm_1", "promote", {}


def _setup_force_release(store):
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim = claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")

    return "force_release", claim.id, "force-release", {}


_OPERATIONS = {
    "acceptance": _setup_acceptance,
    "reference_review": _setup_reference_review,
    "evidence_review": _setup_evidence_review,
    "dependency_revalidation": _setup_revalidation,
    "challenge_resolution": _setup_challenge_resolution,
    "promote": _setup_promote,
    "force_release": _setup_force_release,
}


def _perform(store, kind: str, target_id: str, decision: str, signed, **options):
    if kind == "acceptance":
        return proof_map.decide_acceptance(store, target_id, decision, signed_decision=signed)
    if kind == "reference_review":
        return proof_map.decide_reference_review(store, target_id, decision, signed_decision=signed)
    if kind == "evidence_review":
        return proof_map.decide_evidence_review(store, target_id, decision, signed_decision=signed)
    if kind == "dependency_revalidation":
        return proof_map.revalidate_dependency(store, target_id, options["dependency_id"], signed_decision=signed)
    if kind == "challenge_resolution":
        return proof_map.dismiss_challenge(store, target_id, signed_decision=signed)
    if kind == "promote":
        return proof_map.promote_to_lemma(store, target_id, signed_decision=signed)
    if kind == "force_release":
        return proof_map.release_node(store, "clm_1", claimant_id="x", session_id="y", force=True, signed_decision=signed)
    raise AssertionError(kind)


def _observable_state(store) -> dict:
    """Every derived axis and gated fact a human-only operation could move."""
    state = {"records": [(r.id, r.decision.value) for r in list_review_records(store) if r.kind is not None]}
    for node_id in ("clm_1", "ref_1", "lem_base"):
        if get_node(store, node_id) is None:
            continue
        state[node_id] = (
            get_node(store, node_id).kind.value,
            get_workflow_state(store, node_id),
            get_integrity_state(store, node_id),
            get_acceptance_state(store, node_id) if node_id != "ref_1" else get_reference_review_state(store, node_id),
            get_active_claim(store, node_id) is not None,
        )
    pin = get_dependency_pin(store, "clm_1", "lem_base") if get_node(store, "lem_base") else None
    state["pin"] = pin.pinned_version if pin else None
    return state


@pytest.mark.parametrize("operation", sorted(_OPERATIONS))
def test_a_human_only_operation_needs_a_signed_decision(tmp_path: Path, operation: str):
    store = ensure_project(tmp_path)
    kind, target_id, decision, options = _OPERATIONS[operation](store)
    before = _observable_state(store)

    with pytest.raises(ProofMapError) as exc_info:
        _perform(store, kind, target_id, decision, None, **options)

    assert exc_info.value.code == "HUMAN_REVIEW_REQUIRED"
    assert _observable_state(store) == before


@pytest.mark.parametrize("operation", sorted(_OPERATIONS))
def test_a_decision_signed_by_an_unenrolled_key_changes_nothing(tmp_path: Path, operation: str):
    store = ensure_project(tmp_path)
    kind, target_id, decision, options = _OPERATIONS[operation](store)
    researcher(store)  # a real reviewer is enrolled; the agent's key is not
    before = _observable_state(store)
    agent_key = SoftwareAuthenticator(display_name="agent")
    payload = prepare_decision(store, kind, target_id, decision, rationale="trust me", dependency_id=options.get("dependency_id"))

    with pytest.raises(ProofMapError) as exc_info:
        _perform(store, kind, target_id, decision, agent_key.sign(payload, origin=project_origin(store)), **options)

    assert exc_info.value.code == "UNKNOWN_REVIEWER_KEY"
    assert _observable_state(store) == before


@pytest.mark.parametrize("operation", sorted(_OPERATIONS))
def test_a_properly_signed_decision_goes_through_and_is_recorded_as_signed(tmp_path: Path, operation: str):
    store = ensure_project(tmp_path)
    kind, target_id, decision, options = _OPERATIONS[operation](store)
    signed = researcher(store).sign(kind, target_id, decision, rationale="checked", dependency_id=options.get("dependency_id"))

    _perform(store, kind, target_id, decision, signed, **options)

    recorded = [record for record in list_review_records(store) if record.kind is not None and record.kind.value == kind]
    assert recorded[-1].signed and recorded[-1].reviewer_id == researcher(store).reviewer_id
    assert recorded[-1].rationale == "checked"
    assert _codes(store) == []


def test_no_service_function_accepts_confirmed():
    human_only = [
        proof_map.decide_acceptance,
        proof_map.decide_reference_review,
        proof_map.decide_evidence_review,
        proof_map.revalidate_dependency,
        proof_map.dismiss_challenge,
        proof_map.promote_to_lemma,
        proof_map.release_node,
    ]
    for function in human_only:
        parameters = inspect.signature(function).parameters
        assert "confirmed" not in parameters, function.__name__
        assert "signed_decision" in parameters, function.__name__
    # nothing anywhere in the package still takes the old flag (#37)
    import pkgutil

    import proof_cli

    takes_flag = []
    for module_info in pkgutil.walk_packages(proof_cli.__path__, "proof_cli."):
        module = importlib.import_module(module_info.name)
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ == module.__name__ and {"confirmed", "confirm"} & set(inspect.signature(function).parameters):
                takes_flag.append(f"{module.__name__}.{name}")
    assert not takes_flag


# -- the signature binds to exactly what was decided ---------------------------------


def test_a_signature_for_a_different_decision_or_target_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted(store, "clm_1")
    _submitted(store, "clm_2")
    reviewer = researcher(store)

    for signed_for, used_as in (
        (("clm_1", "accept"), ("clm_1", "reject")),
        (("clm_2", "accept"), ("clm_1", "accept")),
    ):
        signed = reviewer.sign("acceptance", *signed_for)
        with pytest.raises(ProofMapError) as exc_info:
            decide_acceptance(store, *used_as, signed_decision=signed)
        assert exc_info.value.code == "SIGNATURE_MISMATCH"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_a_signature_over_different_candidate_proof_text_is_rejected(tmp_path: Path):
    """The reviewer signed the text they read; if it changes before the
    decision is recorded, the decision is refused."""
    store = ensure_project(tmp_path)
    proof = _submitted(store)
    signed = researcher(store).sign("acceptance", "clm_1", "accept")
    path = store.root / proof.file_path
    path.write_text(path.read_text() + "\nan extra line slipped in after review\n")

    with pytest.raises(ProofMapError) as exc_info:
        decide_acceptance(store, "clm_1", "accept", signed_decision=signed)

    assert exc_info.value.code == "SIGNATURE_MISMATCH"
    assert exc_info.value.details["field"] == "candidate_proof_sha256"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_editing_accepted_proof_text_afterwards_voids_the_acceptance(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"

    path = store.root / proof.file_path
    original = path.read_text()
    path.write_text(original.replace("proof of clm_1", "a quite different proof"))

    # never falls back to "unreviewed" (which would let an agent reclaim it): it's unverifiable
    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "DECISION_NO_LONGER_APPLIES" in _codes(store)

    path.write_text(original)
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_signed_decision_cannot_be_recorded_twice(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted(store)
    check = record_evidence_check(store, proof.id, "passed")
    signed = researcher(store).sign("evidence_review", check.id, "trusted")
    decide_evidence_review(store, check.id, "trusted", signed_decision=signed)

    with pytest.raises(ProofMapError) as exc_info:
        decide_evidence_review(store, check.id, "trusted", signed_decision=signed)
    assert exc_info.value.code == "DECISION_ALREADY_RECORDED"


def test_a_decision_signed_before_a_later_one_on_the_same_target_is_stale(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof = _submitted(store)
    check = record_evidence_check(store, proof.id, "passed")
    reviewer = researcher(store)
    first = reviewer.sign("evidence_review", check.id, "trusted")
    second = reviewer.sign("evidence_review", check.id, "unusable")
    decide_evidence_review(store, check.id, "trusted", signed_decision=first)

    with pytest.raises(ProofMapError) as exc_info:
        decide_evidence_review(store, check.id, "unusable", signed_decision=second)
    assert exc_info.value.code == "STALE_DECISION"


def test_an_assertion_without_user_verification_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted(store)
    reviewer = researcher(store)
    payload = prepare_decision(store, "acceptance", "clm_1", "accept")

    with pytest.raises(ProofMapError) as exc_info:
        decide_acceptance(store, "clm_1", "accept", signed_decision=reviewer.authenticator.sign(payload, flags=0x01, origin=project_origin(store)))
    assert exc_info.value.code == "USER_NOT_VERIFIED"


def test_one_tap_signs_a_batch_of_decisions(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id in ("clm_1", "clm_2", "clm_3"):
        _submitted(store, node_id)
    reviewer = researcher(store)
    payloads = [prepare_decision(store, "acceptance", node_id, "accept") for node_id in ("clm_1", "clm_2", "clm_3")]
    batch = reviewer.authenticator.sign_batch(payloads, origin=project_origin(store))

    for node_id, signed in zip(("clm_1", "clm_2", "clm_3"), batch):
        decide_acceptance(store, node_id, "accept", signed_decision=signed)

    assert {get_acceptance_state(store, node_id) for node_id in ("clm_1", "clm_2", "clm_3")} == {"accepted"}
    assert _codes(store) == []


# -- tampering ------------------------------------------------------------------------


def _tamper(store, *statements: str) -> None:
    """What an agent with file access can do: drop the triggers and edit rows."""
    conn = sqlite3.connect(store.db_path)
    for trigger in ("review_history_no_update", "review_history_no_delete", "reviewer_keys_no_update", "reviewer_keys_no_delete"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def test_editing_a_history_row_breaks_the_chain_and_voids_the_decision(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted(store)
    record = researcher(store).decide_acceptance("clm_1", "reject")
    _submitted(store, "clm_2")
    researcher(store).decide_acceptance("clm_2", "accept")

    _tamper(store, f"UPDATE review_history SET decision = 'approved' WHERE review_id = '{record.id}' AND entry = 'decision'")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"  # neither the forged accept nor the real reject counts
    codes = _codes(store)
    assert "HISTORY_CHAIN_BROKEN" in codes
    assert "UNVERIFIABLE_REVIEW_RECORD" in codes


@pytest.mark.parametrize("statement", [
    "UPDATE review_history SET rationale = 'rewritten' WHERE seq = 1",
    "DELETE FROM review_history WHERE seq = 2",
])
def test_any_edit_or_deletion_in_the_history_is_surfaced(tmp_path: Path, statement: str):
    store = ensure_project(tmp_path)
    for node_id in ("clm_1", "clm_2"):
        _submitted(store, node_id)
        researcher(store).decide_acceptance(node_id, "accept")

    _tamper(store, statement)

    assert "HISTORY_CHAIN_BROKEN" in _codes(store)


def test_a_forged_unsigned_decision_row_never_counts(tmp_path: Path):
    """The service layer refuses an unsigned trust-bearing decision outright;
    one appended straight into SQLite, perfectly linked, still counts for nothing."""
    from proof_cli.collaboration import ReviewRecord, _decision_row, _request_row, record_decided_review
    from proof_cli.domain import utc_now
    from proof_cli.storage import insert_review_history_row

    store = ensure_project(tmp_path)
    _submitted(store)
    researcher(store)
    with pytest.raises(AuthorityError) as exc_info:
        record_decided_review(
            store, "proof_map_node", "clm_1", ReviewGovernanceState.approved, reviewer_id="agent", kind=ReviewRecordKind.acceptance
        )
    assert exc_info.value.code == "HUMAN_REVIEW_REQUIRED"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"

    forged = ReviewRecord(object_type="proof_map_node", object_id="clm_1", reviewer_id="agent", kind=ReviewRecordKind.acceptance)
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    insert_review_history_row(conn, _request_row(forged))
    insert_review_history_row(
        conn, _decision_row(forged, ReviewGovernanceState.approved, reviewer_id="agent", rationale="", created_at=utc_now())
    )
    conn.commit()
    conn.close()

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "UNSIGNED_DECISION" in _codes(store)
    assert "HISTORY_CHAIN_BROKEN" not in _codes(store)  # the chain is intact; the row just isn't authority


def test_a_replayed_decision_cannot_override_a_later_one(tmp_path: Path):
    """Re-appending an old, genuinely-signed decision after a later reject."""
    store = ensure_project(tmp_path)
    _submitted(store)
    reviewer = researcher(store)
    reviewer.decide_acceptance("clm_1", "revision-requested")
    old = next(r for r in list_review_records(store) if r.kind == ReviewRecordKind.acceptance)
    from proof_cli.collaboration import list_review_history
    from proof_cli.signing import SignedDecision

    old_signed = SignedDecision.model_validate_json(
        next(row.signed_decision for row in list_review_history(store, review_id=old.id) if row.entry == "decision")
    )
    _submitted(store, session="sess_2")
    reviewer.decide_acceptance("clm_1", "reject")
    assert get_acceptance_state(store, "clm_1") == "rejected"

    # an agent writing straight into SQLite, triggers dropped on its own
    # connection: a fresh review id, the genuine old signed payload, correctly
    # chain-linked — only the "signed without seeing the later decision" rule stops it
    from proof_cli.collaboration import ReviewRecord, _decision_row, _request_row
    from proof_cli.domain import utc_now
    from proof_cli.storage import insert_review_history_row

    replay = ReviewRecord(
        object_type="proof_map_node", object_id="clm_1", reviewer_id="researcher", kind=ReviewRecordKind.acceptance
    )
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("DROP TRIGGER review_history_no_overwrite_v2")
    insert_review_history_row(conn, _request_row(replay))
    insert_review_history_row(
        conn,
        _decision_row(
            replay,
            ReviewGovernanceState.revision_requested,
            reviewer_id="researcher",
            rationale="",
            created_at=utc_now(),
            signed_decision=old_signed,
        ),
    )
    conn.commit()
    conn.close()

    assert get_acceptance_state(store, "clm_1") == "rejected"
    assert "UNVERIFIABLE_REVIEW_RECORD" in _codes(store)


def test_a_tampered_rationale_or_reviewer_voids_that_decision_itself(tmp_path: Path):
    """What users read off a row — rationale, who decided — must be what was signed."""
    store = ensure_project(tmp_path)
    _submitted(store)
    record = researcher(store).decide_acceptance("clm_1", "accept", rationale="checked every step")

    _tamper(store, f"UPDATE review_history SET rationale = 'skimmed it' WHERE review_id = '{record.id}' AND entry = 'decision'")
    assert get_acceptance_state(store, "clm_1") == "unverifiable"

    _tamper(
        store,
        f"UPDATE review_history SET rationale = 'checked every step', reviewer_id = 'someone-else' "
        f"WHERE review_id = '{record.id}' AND entry = 'decision'",
    )
    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "UNVERIFIABLE_REVIEW_RECORD" in _codes(store)


def test_a_dismissal_pointing_at_an_unrelated_signed_decision_resolves_nothing(tmp_path: Path):
    """A dismissal must rest on a decision about *this* Challenge (or its
    target, after it was opened) — not on any genuinely signed record."""
    from proof_cli.domain import utc_now
    from proof_cli.storage import mark_challenge_dismissed

    store = ensure_project(tmp_path)
    for node_id in ("n1", "n2"):
        _submitted(store, node_id)
    unrelated = researcher(store).decide_acceptance("n1", "accept")
    earlier = researcher(store).decide_acceptance("n2", "accept")
    challenge = open_challenge(store, "n2", opened_by="agent_b", rationale="step 4?")

    for forged_link in (unrelated.id, earlier.id):  # another node's decision; one that predates the Challenge
        mark_challenge_dismissed(
            store, challenge.id, resolved_by="agent", resolved_at=utc_now(), resolution_review_id=forged_link, reopened=True
        )
        assert get_integrity_state(store, "n2") == "challenged"

    researcher(store).dismiss_challenge(challenge.id, rationale="checked step 4")
    assert get_integrity_state(store, "n2") == "current"


def test_an_edit_in_place_is_seen_by_a_long_running_process(tmp_path: Path):
    """No stale 'trusted' view survives an edit that leaves the row counts alone."""
    store = ensure_project(tmp_path)
    _submitted(store)
    record = researcher(store).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"  # the verified view is now cached

    _tamper(store, f"UPDATE review_history SET decision = 'rejected' WHERE review_id = '{record.id}' AND entry = 'decision'")

    # a Reject row, however it got there, keeps the node terminal — at worst
    # a forged one is denial of service, never an escalation — and is flagged
    assert get_acceptance_state(store, "clm_1") == "rejected"
    assert "UNSIGNED_LEGACY_REJECT" in _codes(store)
    # the newest row: nothing links after it, so it's the signature check that catches it
    assert "UNVERIFIABLE_REVIEW_RECORD" in _codes(store)


# -- the Reviewer key registry -----------------------------------------------------------


def test_the_first_key_is_trust_on_first_use_and_pinned_in_user_config(tmp_path: Path):
    store = ensure_project(tmp_path)
    key = enroll(store, SoftwareAuthenticator(ALG_EDDSA))

    assert [k.fingerprint for k in active_reviewer_keys(store)] == [key.fingerprint]
    assert pinned_first_fingerprint(store) == key.fingerprint
    assert (user_config_dir() / "reviewer-pins.json").exists()


def test_a_first_enrollment_must_be_signed_by_the_key_itself(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(AuthorityError) as exc_info:
        enroll(store, SoftwareAuthenticator(), signer=SoftwareAuthenticator())
    assert exc_info.value.code == "ENROLLMENT_REFUSED"
    assert list_reviewer_keys(store) == []


def test_enrolling_a_second_key_needs_a_signature_from_an_enrolled_one(tmp_path: Path):
    store = ensure_project(tmp_path)
    first = SoftwareAuthenticator(display_name="researcher")
    enroll(store, first)
    laptop = SoftwareAuthenticator(display_name="researcher-laptop")

    with pytest.raises(AuthorityError) as exc_info:
        enroll(store, laptop)  # self-signed, as a first key would be
    assert exc_info.value.code == "ENROLLMENT_REFUSED"
    with pytest.raises(AuthorityError):
        enroll(store, laptop, signer=SoftwareAuthenticator())  # signed by a stranger

    enroll(store, laptop, signer=first)
    assert {key.display_name for key in active_reviewer_keys(store)} == {"researcher", "researcher-laptop"}

    # and the laptop key can now make decisions itself
    _submitted(store)
    Researcher(store, laptop).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_backdated_self_signed_enrollment_cannot_sneak_in_first(tmp_path: Path):
    from datetime import timedelta

    store = ensure_project(tmp_path)
    enroll(store, SoftwareAuthenticator())
    intruder = SoftwareAuthenticator(display_name="agent")
    payload = build_decision_payload(
        store, DecisionKind.reviewer_enrollment, public_key_fingerprint(intruder.public_key_spki), "enroll"
    )
    payload = payload.model_copy(update={"signed_at": payload.signed_at - timedelta(days=3650)})
    request = EnrollmentRequest(
        credential_id=intruder.credential_id,
        public_key_spki=b64url_encode(intruder.public_key_spki),
        alg=intruder.alg,
        display_name="agent",
        signed_decision=intruder.sign(payload, origin=project_origin(store)),
    )
    with pytest.raises(AuthorityError):
        enroll_reviewer_key(store, request)


def test_concurrent_first_enrollments_let_exactly_one_key_in(tmp_path: Path):
    store = ensure_project(tmp_path)
    candidates = [SoftwareAuthenticator(display_name=f"key{index}") for index in range(4)]
    barrier = threading.Barrier(len(candidates))
    outcomes: list[str] = []

    def _enroll(authenticator):
        barrier.wait()
        try:
            enroll(store, authenticator)
            outcomes.append("ok")
        except AuthorityError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=_enroll, args=(candidate,)) for candidate in candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert outcomes.count("ok") == 1
    assert set(outcomes) - {"ok"} <= {"ENROLLMENT_REFUSED", "REGISTRY_NOT_TRUSTED"}
    assert len(active_reviewer_keys(store)) == 1


def test_a_registry_row_inserted_behind_the_services_back_is_not_trusted(tmp_path: Path):
    store = ensure_project(tmp_path)
    reviewer = researcher(store)
    intruder = SoftwareAuthenticator(display_name="agent")
    payload = build_decision_payload(
        store, DecisionKind.reviewer_enrollment, public_key_fingerprint(intruder.public_key_spki), "enroll"
    )
    from proof_cli.storage import insert_reviewer_key_row

    with store.transaction() as conn:
        insert_reviewer_key_row(
            conn,
            {
                "id": "reviewer_key_forged",
                "entry": "enroll",
                "credential_id": intruder.credential_id,
                "public_key_spki": b64url_encode(intruder.public_key_spki),
                "alg": intruder.alg,
                "fingerprint": public_key_fingerprint(intruder.public_key_spki),
                "display_name": "agent",
                "signed_decision": intruder.sign(payload, origin=project_origin(store)).model_dump_json(),
                "created_at": payload.signed_at.isoformat(),
            },
        )

    assert [key.display_name for key in active_reviewer_keys(store)] == ["researcher"]
    assert "INVALID_REGISTRY_ENTRY" in _codes(store)
    _submitted(store)
    with pytest.raises(ProofMapError) as exc_info:
        # the agent's key never made it into the registry, so its signature counts for nothing
        decide_acceptance(store, "clm_1", "accept", signed_decision=intruder.sign(prepare_decision(store, "acceptance", "clm_1", "accept"), origin=project_origin(store)))
    assert exc_info.value.code == "UNKNOWN_REVIEWER_KEY"
    reviewer.decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_registry_that_disagrees_with_the_user_config_pin_is_not_trusted(tmp_path: Path):
    store = ensure_project(tmp_path)
    _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"

    pins_path = user_config_dir() / "reviewer-pins.json"
    pins = json.loads(pins_path.read_text())
    pins["projects"][str(store.root.resolve())]["first_key_fingerprint"] = "f" * 64
    pins_path.write_text(json.dumps(pins))

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "REVIEWER_REGISTRY_MISMATCH" in _codes(store)
    assert active_reviewer_keys(store) == []


def test_a_revoked_key_can_no_longer_decide_and_the_last_key_cannot_be_revoked(tmp_path: Path):
    store = ensure_project(tmp_path)
    old, new = SoftwareAuthenticator(display_name="old"), SoftwareAuthenticator(display_name="new")
    enroll(store, old)

    def _revocation(target, signer):
        payload = build_decision_payload(
            store,
            DecisionKind.reviewer_enrollment,
            public_key_fingerprint(target.public_key_spki),
            "revoke",
            credential_id=target.credential_id,
        )
        return signer.sign(payload, origin=project_origin(store))

    with pytest.raises(AuthorityError) as exc_info:
        revoke_reviewer_key(store, _revocation(old, old))
    assert exc_info.value.code == "LAST_REVIEWER_KEY"

    enroll(store, new, signer=old)
    revoke_reviewer_key(store, _revocation(old, new))
    assert [key.display_name for key in active_reviewer_keys(store)] == ["new"]

    _submitted(store)
    with pytest.raises(ProofMapError) as exc_info:
        Researcher(store, old).decide_acceptance("clm_1", "accept")
    assert exc_info.value.code == "UNKNOWN_REVIEWER_KEY"
    Researcher(store, new).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"


# -- existing projects ------------------------------------------------------------


def test_a_pre_adr_0009_database_gains_the_chain_columns(tmp_path: Path):
    store = ensure_project(tmp_path)
    conn = sqlite3.connect(store.db_path)
    for trigger in ("review_history_no_overwrite_v2",):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    conn.execute("DROP INDEX IF EXISTS idx_review_history_payload_hash")
    for column in ("prev_row_hash", "signed_decision", "payload_hash"):
        conn.execute(f"ALTER TABLE review_history DROP COLUMN {column}")
    conn.execute("ALTER TABLE challenges DROP COLUMN resolution_review_id")
    conn.commit()
    conn.close()

    _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert _codes(store) == []


def test_an_unsigned_challenge_dismissal_reads_as_open_again(tmp_path: Path):
    """A pre-ADR-0009 `challenge dismiss --confirm` left no signature; that
    dismissal no longer counts, and a signed decision can resolve it again."""
    from proof_cli.domain import utc_now
    from proof_cli.storage import mark_challenge_dismissed

    store = ensure_project(tmp_path)
    _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    challenge = open_challenge(store, "clm_1", opened_by="agent_b", rationale="?")
    mark_challenge_dismissed(store, challenge.id, resolved_by="someone", resolved_at=utc_now())

    assert get_integrity_state(store, "clm_1") == "challenged"
    researcher(store).dismiss_challenge(challenge.id, rationale="checked, fine")
    assert get_integrity_state(store, "clm_1") == "current"


# -- CLI --------------------------------------------------------------------------


@pytest.mark.parametrize("json_output", [True, False])
def test_cli_human_review_required_without_a_signed_decision(tmp_path: Path, json_output: bool):
    store = ensure_project(tmp_path)
    _submitted(store)
    args = ["node", "review", "clm_1", "accept", "--root", str(tmp_path)] + (["--json"] if json_output else [])

    result = runner.invoke(app, args)

    assert result.exit_code == 1
    if json_output:
        assert json.loads(result.stdout)["error"]["code"] == "HUMAN_REVIEW_REQUIRED"
    else:
        assert "review app" in result.output and "http://localhost:" in result.output
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_cli_confirm_flag_is_gone(tmp_path: Path):
    ensure_project(tmp_path)
    result = runner.invoke(app, ["node", "review", "clm_1", "accept", "--root", str(tmp_path), "--confirm"])
    assert result.exit_code != 0
    assert "No such option" in result.output


def test_no_cli_command_enrolls_a_reviewer_key(tmp_path: Path):
    """Enrollment happens only in the web app's registration ceremony (#36):
    a CLI path is exactly what let an agent enroll itself first (#35 A)."""
    ensure_project(tmp_path)
    result = runner.invoke(app, ["reviewer", "enroll", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


@pytest.mark.parametrize("json_output", [True, False])
def test_cli_reviewer_list_and_warnings(tmp_path: Path, json_output: bool):
    store = ensure_project(tmp_path)
    key = enroll(store, SoftwareAuthenticator(display_name="researcher"))
    flag = ["--json"] if json_output else []

    listed = runner.invoke(app, ["reviewer", "list", "--root", str(tmp_path), *flag])
    warnings = runner.invoke(app, ["review", "warnings", "--root", str(tmp_path), *flag])

    assert listed.exit_code == warnings.exit_code == 0
    if json_output:
        assert [entry["fingerprint"] for entry in json.loads(listed.stdout)["data"]] == [key.fingerprint]
        assert json.loads(warnings.stdout)["data"] == []
    else:
        assert key.fingerprint in listed.output
        assert "No authority warnings" in warnings.output
