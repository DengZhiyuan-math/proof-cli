from pathlib import Path

from proof_cli.domain import ProofObligation, TheoremStatus, TrustLevel
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import load_state
from proof_cli.review import (
    describe_verification_fragment,
    describe_verification_result_record,
    publication_review_summary,
    publication_verification_summary,
    render_verification_output,
)
from proof_cli.publication import list_release_records, record_release_approval, record_release_withdrawal, summarize_publication_release
from proof_cli.collaboration import ReviewGovernanceState, record_decided_review
from proof_cli.storage import ensure_project
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
from proof_cli.verification_results import record_verification_result


def test_publication_review_summaries_and_release_audit_are_selective(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_pub",
        kind="theorem",
        name="Publication Theorem",
        statement="A -> C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_obligation(
        store,
        ProofObligation(
            id="obl_pub",
            goal_statement="close publication gap",
            required_for="thm_pub",
        ),
    )

    scope = VerificationScope(project_id=load_state(store).project_id, theorem_id="thm_pub")
    fragment = VerificationFragment(
        source_type=VerificationSourceKind.theorem_contract,
        source_id="thm_pub",
        scope=scope,
        status=VerificationFragmentStatus.machine_checked,
        translation_status=VerificationTranslationStatus.translated,
        backend_target="lean4",
        provenance=VerificationProvenance(
            source_kind=VerificationSourceKind.theorem_contract,
            source_id="thm_pub",
            source_label="publication theorem",
            source_scope=scope,
            derived_from_ids=["thm_pub"],
            machine_path=["check publication theorem"],
        ),
    )
    result = VerificationResult(
        fragment_id=fragment.id,
        backend="lean4",
        summary="publication verification complete",
        review_status=VerificationReviewStatus.accepted_after_review,
        notes="accepted for publication",
    )
    record_verification_result(store, fragment, result, theorem_id="thm_pub", notes="accepted for publication")
    # an ordinary (non-trust-bearing) review of the contract, as the old `mark_verified` used to leave behind
    record_decided_review(store, "theorem_contract", "thm_pub", ReviewGovernanceState.approved, reviewer_id="editor")

    review_lines = publication_review_summary(store, object_type="theorem_contract", object_id="thm_pub")
    verification_lines = publication_verification_summary(store, theorem_id="thm_pub")
    release = record_release_approval(store, "bundle_pub", approved_by=["editor"], notes="paper ready")
    withdrawn = record_release_withdrawal(store, "bundle_pub", withdrawn_by=["editor"], reason="correction issued")

    assert review_lines
    assert verification_lines
    assert "thm_pub" in review_lines[0]
    assert "publication verification complete" in verification_lines[0]
    assert release.status.value == "approved"
    assert withdrawn.status.value == "withdrawn"
    assert summarize_publication_release(withdrawn).startswith("bundle_pub")
    assert list_release_records(store, bundle_id="bundle_pub")


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
