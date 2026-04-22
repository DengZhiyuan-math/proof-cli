from pathlib import Path

from proof_cli.domain import ProofObligation, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import set_current_context
from proof_cli.memory import track_symbol
from proof_cli.review import (
    approve_imported_result,
    change_trust_level,
    close_obligation_review,
    describe_verification_fragment,
    describe_verification_result_record,
    mark_verified,
    render_verification_output,
    resolve_blocker_review,
)
from proof_cli.storage import ensure_project, list_events
from proof_cli.theorems import add_theorem
from proof_cli.blockers import add_blocker
from proof_cli.domain import BlockerRecord
from proof_cli.verification_ir import (
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
    VerificationSourceKind,
    VerificationTranslationStatus,
)
from proof_cli.verification_results import VerificationResultRecord


def test_review_gate_requires_confirmation_and_logs(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="Imported Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.draft,
        trust_level=TrustLevel.temporary_admit,
    )

    blocked = approve_imported_result(store, "thm_1", confirmed=False)
    assert blocked.allowed is False
    approved = approve_imported_result(store, "thm_1", confirmed=True, rationale="source checked")
    assert approved.allowed is True

    trusted = change_trust_level(store, "thm_1", TrustLevel.project_verified, confirmed=True, rationale="locally checked")
    assert trusted.allowed is True
    verified = mark_verified(store, "thm_1", confirmed=True, rationale="proof checked")
    assert verified.allowed is True

    events = list_events(store)
    assert any(event.kind == "review_blocked" for event in events)
    assert any(event.kind == "review_approved" for event in events)
    assert any(event.payload.get("checker_context") for event in events if event.kind in {"review_blocked", "review_approved"})


def test_review_gate_controls_blockers_and_obligations(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_obligation(
        store,
        ProofObligation(
            id="obl_1",
            goal_statement="prove result",
            required_for="thm_1",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_1",
            scope="thm_1",
            description="missing lemma",
            failure_type="missing_lemma",
        ),
    )
    set_current_context(store, ["A"])

    blocked_close = close_obligation_review(store, "obl_1", confirmed=True)
    assert blocked_close.allowed is False

    approved_close = close_obligation_review(store, "obl_1", confirmed=True, proof_text="proved in appendix")
    assert approved_close.allowed is True

    resolved = resolve_blocker_review(store, "blk_1", confirmed=True, rationale="lemma added")
    assert resolved.allowed is True


def test_review_records_checker_context_for_imported_approval(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_imported",
        kind="theorem",
        name="Imported Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
    )
    set_current_context(store, ["A"])
    track_symbol(store, "A")
    track_symbol(store, "B")

    approved = approve_imported_result(store, "thm_imported", confirmed=True, rationale="source checked")
    assert approved.allowed is True

    events = list_events(store)
    review_event = next(event for event in events if event.kind == "review_approved" and event.entity_id == "thm_imported")
    checker_context = review_event.payload["checker_context"]
    assert any(check["name"] == "assumption_presence" and check["severity"] == "warn" for check in checker_context)
    assert any(check["name"] == "export_strength" and check["severity"] == "warn" for check in checker_context)


def test_verification_review_formatters_are_readable_and_session_ready() -> None:
    scope = VerificationScope(project_id="proj_1", theorem_id="thm_1", proof_step_id="step_1", route_id="route_1")
    fragment = VerificationFragment(
        source_type=VerificationSourceKind.proof_step,
        source_id="step_1",
        scope=scope,
        status=VerificationFragmentStatus.machine_checked,
        translation_status=VerificationTranslationStatus.translated,
        backend_target="lean4",
        provenance=VerificationProvenance(
            source_kind=VerificationSourceKind.proof_step,
            source_id="step_1",
            source_label="apply bridge",
            source_scope=scope,
            derived_from_ids=["step_1", "thm_1"],
            machine_path=["inspect state", "translate to ir"],
        ),
    )
    result = VerificationResult(
        fragment_id=fragment.id,
        backend="lean4",
        summary="machine check completed",
        review_status=VerificationReviewStatus.accepted_after_review,
        notes="accepted by reviewer",
    )
    record = VerificationResultRecord(
        result=result,
        result_status=fragment.status,
        review_status=result.review_status,
        source_kind=fragment.source_type,
        source_id=fragment.source_id,
        scope=scope,
        theorem_id=scope.theorem_id,
        proof_step_id=scope.proof_step_id,
        route_id=scope.route_id,
        effect="strengthening",
        notes="accepted by reviewer",
    )

    fragment_summary = describe_verification_fragment(fragment)
    record_summary = describe_verification_result_record(record)
    rendered = render_verification_output("verify run step_1", result.model_dump_json(indent=2))

    assert "step_1" in fragment_summary
    assert "machine_checked" in fragment_summary
    assert "accepted_after_review" in record_summary
    assert "Result:" in rendered
    assert "Details:" in rendered
