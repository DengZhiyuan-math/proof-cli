from __future__ import annotations

from proof_cli.verification_ir import (
    FormalizationRecommendation,
    VerificationArtifact,
    VerificationAssumption,
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationQuantifiedGoal,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
    VerificationSideCondition,
    VerificationSourceKind,
    VerificationTheoremApplication,
    VerificationTranslationStatus,
)


def _sample_fragment() -> VerificationFragment:
    scope = VerificationScope(
        project_id="proj_1",
        theorem_id="thm_main",
        goal_id="goal_main",
        obligation_id="obl_bridge",
        blocker_id="blk_fragile",
        proof_step_id="step_apply_bridge",
        route_id="route_1",
        tags=["phase4", "bridge"],
    )
    return VerificationFragment(
        source_type=VerificationSourceKind.theorem_application,
        source_id="step_apply_bridge",
        scope=scope,
        ir_version=1,
        status=VerificationFragmentStatus.queued_for_verification,
        translation_status=VerificationTranslationStatus.pending,
        backend_target="lean4",
        assumptions=[
            VerificationAssumption(statement="A", source_id="ctx_A"),
            VerificationAssumption(statement="B", source_id="ctx_B"),
        ],
        quantified_goals=[
            VerificationQuantifiedGoal(
                statement="forall x, P x -> Q x",
                quantifiers=["forall x"],
                free_variables=["x"],
            )
        ],
        theorem_applications=[
            VerificationTheoremApplication(
                theorem_id="thm_bridge",
                theorem_name="Bridge Lemma",
                statement="bridge theorem application",
                assumptions_used=["A"],
                side_conditions=["nonempty domain"],
                fragile=True,
                notes="fragile theorem application escalated for machine checking",
                reasoning_path=["goal_main", "lemma_bridge", "step_apply_bridge"],
            )
        ],
        side_conditions=[
            VerificationSideCondition(
                statement="n is nonzero",
                origin="standard step converted into an explicit obligation",
                satisfied_by=["lemma_bridge"],
            )
        ],
        dependency_versions=[
            VerificationDependencyVersion(
                dependency_id="thm_bridge",
                version=3,
                kind="theorem_contract",
                digest="sha256:abc123",
            ),
            VerificationDependencyVersion(
                dependency_id="obl_bridge",
                version=2,
                kind="proof_obligation",
                digest="sha256:def456",
            ),
        ],
        provenance=VerificationProvenance(
            source_kind=VerificationSourceKind.theorem_application,
            source_id="step_apply_bridge",
            source_label="apply bridge lemma",
            source_scope=scope,
            derived_from_ids=["goal_main", "lemma_bridge"],
            machine_path=["inspect state", "translate to ir", "queue for backend"],
            reviewed_by="researcher",
        ),
        notes="escalated from a fragile theorem application",
    )


def test_verification_fragment_round_trips_with_metadata() -> None:
    fragment = _sample_fragment()

    reloaded = VerificationFragment.model_validate_json(fragment.model_dump_json())

    assert reloaded == fragment
    assert reloaded.source_type == VerificationSourceKind.theorem_application
    assert reloaded.source_id == "step_apply_bridge"
    assert reloaded.scope.project_id == "proj_1"
    assert reloaded.scope.theorem_id == "thm_main"
    assert reloaded.scope.goal_id == "goal_main"
    assert reloaded.scope.obligation_id == "obl_bridge"
    assert reloaded.scope.blocker_id == "blk_fragile"
    assert reloaded.scope.route_id == "route_1"
    assert reloaded.scope.tags == ["phase4", "bridge"]
    assert [item.statement for item in reloaded.assumptions] == ["A", "B"]
    assert reloaded.quantified_goals[0].quantifiers == ["forall x"]
    assert reloaded.theorem_applications[0].fragile is True
    assert reloaded.theorem_applications[0].side_conditions == ["nonempty domain"]
    assert reloaded.side_conditions[0].origin == "standard step converted into an explicit obligation"
    assert [dep.version for dep in reloaded.dependency_versions] == [3, 2]
    assert reloaded.provenance.source_id == "step_apply_bridge"
    assert reloaded.provenance.source_scope == fragment.scope
    assert reloaded.provenance.derived_from_ids == ["goal_main", "lemma_bridge"]


def test_verification_fragment_status_transitions_cover_success_failure_and_staleness() -> None:
    fragment = _sample_fragment()

    queued = fragment.queue_for_verification(backend_target="coq")
    translated = queued.record_translation_success(backend_target="coq")
    checked = translated.record_machine_check(result_id="vchk_123", backend_target="coq")
    stale = checked.mark_stale_after_change(
        changed_dependency_versions=[
            VerificationDependencyVersion(
                dependency_id="thm_bridge",
                version=4,
                kind="theorem_contract",
                digest="sha256:updated",
            )
        ],
        reason="dependency version changed after a proof update",
    )
    backend_failed = stale.record_backend_failure("backend timeout", backend_target="coq")
    rejected = backend_failed.reject_by_human(result_id="vchk_123", notes="needs follow-up review")
    accepted = rejected.accept_after_review(result_id="vchk_123", notes="approved after stronger checking")

    assert queued.status == VerificationFragmentStatus.queued_for_verification
    assert queued.translation_status == VerificationTranslationStatus.pending
    assert translated.translation_status == VerificationTranslationStatus.translated
    assert checked.status == VerificationFragmentStatus.machine_checked
    assert checked.result_id == "vchk_123"
    assert stale.status == VerificationFragmentStatus.stale_after_change
    assert stale.dependency_versions[0].version == 4
    assert backend_failed.status == VerificationFragmentStatus.backend_failed
    assert "backend timeout" in backend_failed.notes
    assert rejected.status == VerificationFragmentStatus.rejected_by_human
    assert accepted.status == VerificationFragmentStatus.accepted_after_review
    assert accepted.result_id == "vchk_123"


def test_verification_result_round_trips_and_tracks_review_state() -> None:
    result = VerificationResult(
        fragment_id="vfrag_1",
        backend="lean4",
        summary="machine check succeeded for the bridge fragment",
        artifacts=[
            VerificationArtifact(
                kind="trace",
                uri="file:///tmp/vchk_lean4_trace.json",
                description="backend trace for review",
            )
        ],
        metadata={"backend_version": "4.0.0", "check_mode": "proof_fragment"},
    )

    accepted = result.accept(notes="reviewed and accepted")
    rejected = result.reject(notes="reviewed and rejected")
    reloaded = VerificationResult.model_validate_json(result.model_dump_json())

    assert reloaded == result
    assert result.review_status == VerificationReviewStatus.pending_review
    assert accepted.review_status == VerificationReviewStatus.accepted_after_review
    assert accepted.notes == "reviewed and accepted"
    assert rejected.review_status == VerificationReviewStatus.rejected_by_human
    assert rejected.notes == "reviewed and rejected"
    assert reloaded.artifacts[0].uri == "file:///tmp/vchk_lean4_trace.json"
    assert reloaded.metadata["backend_version"] == "4.0.0"


def test_formalization_recommendation_is_serializable() -> None:
    recommendation = FormalizationRecommendation(
        fragment_id="vfrag_1",
        rank=1,
        reason="fragile theorem application with explicit side conditions",
        confidence=0.91,
        suggested_backend="lean4",
    )

    reloaded = FormalizationRecommendation.model_validate_json(recommendation.model_dump_json())

    assert reloaded == recommendation
    assert reloaded.suggested_backend == "lean4"
