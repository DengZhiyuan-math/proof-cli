from __future__ import annotations

from proof_cli.domain_packs import (
    DomainPack,
    DomainPackCompatibility,
    DomainPackContent,
    DomainPackReviewStatus,
    DomainPackTrustLevel,
)
from proof_cli.recommendations import CrossProjectRecommendationReport, recommend_cross_project_assets
from proof_cli.retrieval import CrossProjectSourceKind, retrieve_cross_project_assets
from proof_cli.reusable_assets import (
    ReusableAsset,
    ReusableAssetKind,
    ReusableAssetPayload,
    ReusableAssetProvenance,
    ReusableAssetReuseStatus,
    ReusableAssetTrustLevel,
)


def _current_asset() -> ReusableAsset:
    return ReusableAsset(
        id="asset_local_uniformity",
        kind=ReusableAssetKind.proof_pattern,
        name="Uniformity sketch",
        summary="Local notes about a proof route that mentions uniformity and summation",
        payload=ReusableAssetPayload(
            pattern_steps=["inspect uniformity", "summation route", "close the local gap"],
        ),
        provenance=ReusableAssetProvenance(
            origin_project_id="proj_beta",
            notes="captured from the current project",
        ),
        reuse_status=ReusableAssetReuseStatus.project_local,
        trust_level=ReusableAssetTrustLevel.temporary_admit,
    )


def _shared_asset() -> ReusableAsset:
    return ReusableAsset(
        id="asset_shared_uniformity",
        kind=ReusableAssetKind.proof_pattern,
        name="Uniformity-before-summation pattern",
        summary="Approved reusable workflow for uniformity and summation arguments",
        payload=ReusableAssetPayload(
            pattern_steps=["retrieve known result first", "check uniformity explicitly", "split the sum"],
            method_steps=["reuse known result", "verify assumptions", "record provenance"],
        ),
        provenance=ReusableAssetProvenance(
            origin_project_id="proj_alpha",
            source_contract_ids=["thm_uniformity"],
            source_reference_ids=["ref_uniformity"],
            derived_from_asset_ids=["asset_seed"],
            linked_blocker_ids=["blk_uniformity"],
            linked_repair_ids=["repair_uniformity"],
            notes="approved for cross-project reuse",
        ),
        reuse_status=ReusableAssetReuseStatus.approved_reusable,
        trust_level=ReusableAssetTrustLevel.domain_trusted,
        reviewed_by="lead",
        review_notes="approved for cross-project reuse",
    )


def _prior_asset() -> ReusableAsset:
    return ReusableAsset(
        id="asset_prior_boundary",
        kind=ReusableAssetKind.repair_strategy,
        name="Boundary-case repair strategy",
        summary="A prior-project repair for fragile boundary arguments",
        payload=ReusableAssetPayload(
            repair_steps=["check the boundary case", "weaken the conclusion if needed"],
        ),
        provenance=ReusableAssetProvenance(
            origin_project_id="proj_gamma",
            source_contract_ids=["thm_boundary"],
            linked_blocker_ids=["blk_boundary"],
            notes="used in an earlier project",
        ),
        reuse_status=ReusableAssetReuseStatus.private_experimental,
        trust_level=ReusableAssetTrustLevel.project_verified,
    )


def _domain_pack() -> DomainPack:
    return DomainPack(
        id="pack_spectral_analysis",
        name="Spectral-Analysis-Pack",
        version="0.1.0",
        summary="Reusable spectral workflow pack with explicit reuse signals",
        content=DomainPackContent(
            theorem_templates=["uniformity theorem template", "spectral decomposition theorem template"],
            method_templates=["retrieve known result first", "check assumptions explicitly"],
            omission_rules=["expand standard estimates into side conditions"],
            bug_patterns=["hidden uniformity gap"],
            formalization_preferences=["prefer explicit dependency chains"],
            debug_task_templates=["test boundary parameters"],
            notation_conventions=["use explicit summation notation"],
            notes="pack contents should be inspectable",
        ),
        compatibility=DomainPackCompatibility(
            required_project_tags=["spectral", "analysis"],
            required_asset_ids=["asset_shared_uniformity"],
            required_asset_kinds=["proof_pattern", "repair_strategy"],
            required_notation_profile="spectral_default",
            allowed_pack_versions=["0.1.0"],
            notes="compatible with repeated spectral workflows",
        ),
        review_status=DomainPackReviewStatus.approved,
        trust_level=DomainPackTrustLevel.reviewed_reusable,
        reviewed_by="reviewer",
        review_notes="approved for repeated use across projects",
        origin_project_id="proj_alpha",
        source_asset_ids=["asset_shared_uniformity"],
        notes="domain pack for repeated spectral workflows",
    )


def test_cross_project_retrieval_surfaces_all_source_kinds_and_provenance() -> None:
    report = retrieve_cross_project_assets(
        current_project_id="proj_beta",
        query="uniformity summation boundary",
        current_project_assets=[_current_asset()],
        shared_assets=[_shared_asset()],
        prior_project_assets=[_prior_asset()],
        domain_packs=[_domain_pack()],
        prior_usefulness={
            "asset_local_uniformity": 0.12,
            "asset_shared_uniformity": 0.94,
            "asset_prior_boundary": 0.62,
            "pack_spectral_analysis": 0.81,
        },
        limit=10,
    )

    reloaded = type(report).model_validate_json(report.model_dump_json())

    assert reloaded == report
    assert [trace.source_kind for trace in report.trace] == [
        CrossProjectSourceKind.project_local,
        CrossProjectSourceKind.shared_domain,
        CrossProjectSourceKind.prior_project,
        CrossProjectSourceKind.domain_pack,
    ]
    assert {candidate.source_kind for candidate in report.candidates} == {
        CrossProjectSourceKind.project_local,
        CrossProjectSourceKind.shared_domain,
        CrossProjectSourceKind.prior_project,
        CrossProjectSourceKind.domain_pack,
    }
    assert any(candidate.origin_project_id == "proj_alpha" for candidate in report.candidates)
    assert any("originated in project proj_alpha" in reason for candidate in report.candidates for reason in candidate.provenance_reasons)


def test_cross_project_recommendations_rank_by_trust_usefulness_and_provenance() -> None:
    report = recommend_cross_project_assets(
        current_project_id="proj_beta",
        query="uniformity summation boundary",
        current_project_assets=[_current_asset()],
        shared_assets=[_shared_asset()],
        prior_project_assets=[_prior_asset()],
        domain_packs=[_domain_pack()],
        prior_usefulness={
            "asset_local_uniformity": 0.10,
            "asset_shared_uniformity": 0.96,
            "asset_prior_boundary": 0.55,
            "pack_spectral_analysis": 0.44,
        },
        limit=10,
    )

    top = report.recommendations[0]
    reloaded = CrossProjectRecommendationReport.model_validate_json(report.model_dump_json())

    assert reloaded == report
    assert top.candidate_id == "asset_shared_uniformity"
    assert top.source_kind == CrossProjectSourceKind.shared_domain
    assert top.total_score > report.recommendations[1].total_score
    assert top.prior_usefulness_score == 0.96
    assert "prior usefulness score 0.96" in top.reason
    assert "origin project proj_alpha" in top.provenance_summary
    assert "approved for cross-project reuse" in top.reason
    assert top.review_status == "pending_review"


def test_cross_project_recommendation_report_serializes_with_nested_retrieval_data() -> None:
    report = recommend_cross_project_assets(
        current_project_id="proj_beta",
        query="uniformity summation",
        current_project_assets=[_current_asset()],
        shared_assets=[_shared_asset()],
        prior_project_assets=[_prior_asset()],
        domain_packs=[_domain_pack()],
        prior_usefulness={
            "asset_local_uniformity": 0.08,
            "asset_shared_uniformity": 0.91,
            "asset_prior_boundary": 0.47,
            "pack_spectral_analysis": 0.65,
        },
        limit=5,
    )

    payload = report.model_dump(mode="json")

    assert payload["retrieval_report"]["current_project_id"] == "proj_beta"
    assert payload["recommendations"][0]["candidate_id"] == "asset_shared_uniformity"
    assert payload["recommendations"][0]["payload"]["provenance"]["origin_project_id"] == "proj_alpha"
