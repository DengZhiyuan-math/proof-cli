from __future__ import annotations

from proof_cli.formalization_recommendations import (
    FormalizationRecommendation,
    rank_formalization_candidates,
    recommend_formalization_candidate,
)
from proof_cli.verification_ir import (
    VerificationAssumption,
    VerificationDependencyVersion,
    VerificationFragment,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationQuantifiedGoal,
    VerificationScope,
    VerificationSideCondition,
    VerificationSourceKind,
    VerificationTheoremApplication,
    VerificationTranslationStatus,
)


def _base_scope(fragment_name: str) -> VerificationScope:
    return VerificationScope(
        project_id="proj_phase4",
        theorem_id="thm_selective_bridge",
        goal_id="goal_selective_bridge",
        obligation_id=f"obl_{fragment_name}",
        proof_step_id=f"step_{fragment_name}",
        route_id="route_phase4",
        tags=["phase4", fragment_name],
    )


def _fragment(
    *,
    fragment_name: str,
    source_kind: VerificationSourceKind,
    source_id: str,
    status: VerificationFragmentStatus,
    theorem_application: VerificationTheoremApplication | None = None,
    side_conditions: list[VerificationSideCondition] | None = None,
    dependency_ids: list[str] | None = None,
    notes: str = "",
) -> VerificationFragment:
    scope = _base_scope(fragment_name)
    return VerificationFragment(
        source_type=source_kind,
        source_id=source_id,
        scope=scope,
        status=status,
        translation_status=VerificationTranslationStatus.translated,
        backend_target="proof_assistant",
        assumptions=[VerificationAssumption(statement="A")],
        quantified_goals=[VerificationQuantifiedGoal(statement="forall x, P x -> Q x", quantifiers=["forall x"], free_variables=["x"])],
        theorem_applications=[theorem_application] if theorem_application is not None else [],
        side_conditions=side_conditions or [],
        dependency_versions=[
            VerificationDependencyVersion(
                dependency_id=dependency_id,
                version=1,
                kind="theorem_contract" if dependency_id.startswith("thm_") else "proof_obligation",
                digest=f"sha256:{dependency_id}",
            )
            for dependency_id in dependency_ids or []
        ],
        provenance=VerificationProvenance(
            source_kind=source_kind,
            source_id=source_id,
            source_label=f"fragment {fragment_name}",
            source_scope=scope,
            derived_from_ids=[scope.theorem_id or "", scope.goal_id or ""],
            machine_path=["inspect state", "rank formalization candidates"],
            reviewed_by="researcher",
        ),
        notes=notes,
    )


def test_recommendations_rank_high_risk_fragments_first_and_keep_them_reviewable() -> None:
    fragile_fragment = _fragment(
        fragment_name="fragile_bridge",
        source_kind=VerificationSourceKind.theorem_application,
        source_id="step_fragile_bridge",
        status=VerificationFragmentStatus.queued_for_verification,
        theorem_application=VerificationTheoremApplication(
            theorem_id="thm_bridge",
            theorem_name="Bridge Lemma",
            statement="apply bridge lemma to a fragile goal",
            assumptions_used=["A"],
            side_conditions=["nonempty domain"],
            fragile=True,
            notes="fragile theorem application that should be escalated",
            reasoning_path=["goal_selective_bridge", "lemma_bridge", "step_fragile_bridge"],
        ),
        side_conditions=[
            VerificationSideCondition(
                statement="justify the compressed step",
                origin="expanded from a standard proof step",
                satisfied_by=["lemma_bridge"],
            )
        ],
        dependency_ids=["thm_bridge", "obl_bridge", "step_bridge"],
        notes="fragile proof step with explicit side conditions",
    )
    medium_fragment = _fragment(
        fragment_name="intermediate_step",
        source_kind=VerificationSourceKind.proof_step,
        source_id="step_intermediate",
        status=VerificationFragmentStatus.machine_checked,
        dependency_ids=["thm_support", "obl_support"],
        notes="intermediate proof step with moderate centrality",
    )
    low_fragment = _fragment(
        fragment_name="routine_obligation",
        source_kind=VerificationSourceKind.proof_obligation,
        source_id="obl_routine",
        status=VerificationFragmentStatus.accepted_after_review,
        dependency_ids=["thm_routine"],
        notes="routine obligation with low risk",
    )

    recommendations = rank_formalization_candidates(
        [low_fragment, medium_fragment, fragile_fragment],
        dependency_centrality={
            fragile_fragment.id: 0.95,
            "thm_bridge": 0.9,
            "step_fragile_bridge": 0.88,
            medium_fragment.id: 0.45,
            "thm_support": 0.4,
            low_fragment.id: 0.15,
        },
        failure_history={
            fragile_fragment.source_id: 3,
            medium_fragment.source_id: 1,
        },
    )

    assert [recommendation.fragment_id for recommendation in recommendations] == [
        fragile_fragment.id,
        medium_fragment.id,
        low_fragment.id,
    ]
    assert [recommendation.rank for recommendation in recommendations] == [1, 2, 3]

    top = recommendations[0]
    assert top.source_kind == VerificationSourceKind.theorem_application
    assert top.scope.theorem_id == "thm_selective_bridge"
    assert top.escalation_recommended is True
    assert top.manual_override_allowed is True
    assert top.suggested_backend == "proof_assistant"
    assert "fragile theorem application" in top.reason
    assert "dependency centrality" in top.reason
    assert "repeated failure history" in top.reason
    assert top.total_score > recommendations[1].total_score > recommendations[2].total_score

    low = recommendations[2]
    assert low.escalation_recommended is False
    assert low.review_status == "pending_review"
    assert low.suggested_backend == "smt"


def test_recommendation_serializes_and_supports_manual_override() -> None:
    fragment = _fragment(
        fragment_name="serialize_me",
        source_kind=VerificationSourceKind.proof_step,
        source_id="step_serialize",
        status=VerificationFragmentStatus.translation_failed,
        theorem_application=VerificationTheoremApplication(
            theorem_id="thm_serialized",
            theorem_name="Serialized Bridge",
            statement="translate this proof step",
            assumptions_used=["A"],
            side_conditions=["side condition"],
            fragile=True,
            notes="fragile proof step",
            reasoning_path=["goal_selective_bridge", "step_serialize"],
        ),
        side_conditions=[
            VerificationSideCondition(
                statement="side condition",
                origin="explicit proof-step side condition",
            )
        ],
        dependency_ids=["thm_serialized", "obl_serialized"],
        notes="translation failure should be escalated",
    )

    recommendation = recommend_formalization_candidate(
        fragment,
        dependency_centrality={fragment.source_id: 0.8, "thm_serialized": 0.7},
        failure_history={fragment.id: 2},
    )
    reloaded = FormalizationRecommendation.model_validate_json(recommendation.model_dump_json())

    assert reloaded == recommendation
    assert reloaded.confidence > 0
    assert reloaded.total_score > 0
    assert reloaded.review_status == "pending_review"

    accepted = recommendation.accept(notes="approved for escalation")
    overridden = recommendation.override(notes="keep as manual proof obligation")

    assert accepted.review_status == "accepted_after_review"
    assert accepted.notes == "approved for escalation"
    assert overridden.review_status == "overridden_by_human"
    assert overridden.notes == "keep as manual proof obligation"
