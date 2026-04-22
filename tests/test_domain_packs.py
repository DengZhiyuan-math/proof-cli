from __future__ import annotations

import pytest

from proof_cli.domain_packs import (
    DomainPack,
    DomainPackCompatibility,
    DomainPackContent,
    DomainPackInstallation,
    DomainPackLifecycleStatus,
    DomainPackReviewStatus,
    DomainPackTrustLevel,
)


def _domain_pack() -> DomainPack:
    return DomainPack(
        id="pack_spectral_analysis",
        name="Spectral-Analysis-Pack",
        version="0.1.0",
        summary="Reusable spectral analysis workflow",
        content=DomainPackContent(
            theorem_templates=[
                "spectral decomposition theorem template",
                "adjoint operator lemma template",
            ],
            method_templates=[
                "retrieve known result first",
                "check side conditions explicitly",
                "split uniformity from pointwise arguments",
            ],
            omission_rules=[
                "expand all standard estimates into explicit side conditions",
            ],
            bug_patterns=[
                "hidden uniformity gap",
                "illegal interchange of limit and sum",
            ],
            formalization_preferences=[
                "escalate fragile theorem applications",
                "prefer explicit dependency chains",
            ],
            debug_task_templates=[
                "test the proof at the boundary parameter regime",
                "compare with the imported spectral lemma",
            ],
            notation_conventions=[
                "use lambda for eigenvalue parameters",
                "write inner products explicitly",
            ],
            notes="pack contents should remain inspectable",
        ),
        compatibility=DomainPackCompatibility(
            required_project_tags=["spectral", "analysis"],
            required_asset_ids=["asset_uniformity", "asset_spectral_lemma"],
            required_asset_kinds=["proof_pattern", "theorem_contract"],
            required_notation_profile="spectral_default",
            allowed_pack_versions=["0.1.0", "0.1.1", "0.2.0"],
            notes="compatible with the spectral workflow family",
        ),
        review_status=DomainPackReviewStatus.approved,
        trust_level=DomainPackTrustLevel.reviewed_reusable,
        reviewed_by="reviewer",
        review_notes="approved for cross-project installation",
        origin_project_id="proj_alpha",
        source_asset_ids=["asset_uniformity", "asset_spectral_lemma"],
        notes="domain pack for repeated spectral proof workflows",
    )


def test_domain_pack_round_trip_preserves_contents_and_explicit_compatibility() -> None:
    pack = _domain_pack()

    reloaded = DomainPack.model_validate_json(pack.model_dump_json())

    assert reloaded == pack
    assert reloaded.version == "0.1.0"
    assert reloaded.review_status == DomainPackReviewStatus.approved
    assert reloaded.trust_level == DomainPackTrustLevel.reviewed_reusable
    assert reloaded.compatibility.required_project_tags == ["spectral", "analysis"]
    assert reloaded.compatibility.required_asset_ids == [
        "asset_uniformity",
        "asset_spectral_lemma",
    ]
    assert reloaded.compatibility.required_asset_kinds == ["proof_pattern", "theorem_contract"]
    assert reloaded.compatibility.required_notation_profile == "spectral_default"
    assert reloaded.content.theorem_templates == [
        "spectral decomposition theorem template",
        "adjoint operator lemma template",
    ]
    assert reloaded.content.method_templates[0] == "retrieve known result first"
    assert reloaded.content.omission_rules == [
        "expand all standard estimates into explicit side conditions",
    ]
    assert reloaded.content.bug_patterns == [
        "hidden uniformity gap",
        "illegal interchange of limit and sum",
    ]
    assert reloaded.content.formalization_preferences == [
        "escalate fragile theorem applications",
        "prefer explicit dependency chains",
    ]
    assert reloaded.content.debug_task_templates == [
        "test the proof at the boundary parameter regime",
        "compare with the imported spectral lemma",
    ]
    assert reloaded.content.notation_conventions == [
        "use lambda for eigenvalue parameters",
        "write inner products explicitly",
    ]


def test_domain_pack_installation_preserves_review_status_and_compatibility_snapshot() -> None:
    pack = _domain_pack()

    installation = pack.install(
        project_id="proj_beta",
        installed_by="researcher",
        project_tags=["spectral", "analysis", "functional"],
        available_asset_ids=["asset_uniformity", "asset_spectral_lemma", "asset_extra"],
        available_asset_kinds=["proof_pattern", "theorem_contract", "repair_strategy"],
        notation_profile="spectral_default",
        notes="installed into the beta project",
    )

    reloaded = DomainPackInstallation.model_validate_json(installation.model_dump_json())

    assert reloaded == installation
    assert reloaded.status == DomainPackLifecycleStatus.installed
    assert reloaded.pack_id == "pack_spectral_analysis"
    assert reloaded.pack_version == "0.1.0"
    assert reloaded.project_id == "proj_beta"
    assert reloaded.review_status == DomainPackReviewStatus.approved
    assert reloaded.trust_level == DomainPackTrustLevel.reviewed_reusable
    assert reloaded.compatibility == pack.compatibility
    assert reloaded.compatibility_check.compatible is True
    assert reloaded.compatibility_check.version_allowed is True
    assert reloaded.content_snapshot.theorem_templates == pack.content.theorem_templates
    assert reloaded.content_snapshot.method_templates == pack.content.method_templates
    assert reloaded.content_snapshot.debug_task_templates == pack.content.debug_task_templates
    assert reloaded.project_tags == ["spectral", "analysis", "functional"]
    assert reloaded.available_asset_ids == [
        "asset_uniformity",
        "asset_spectral_lemma",
        "asset_extra",
    ]
    assert reloaded.available_asset_kinds == ["proof_pattern", "theorem_contract", "repair_strategy"]
    assert reloaded.notation_profile == "spectral_default"
    assert reloaded.source_pack_review_status == DomainPackReviewStatus.approved
    assert reloaded.source_pack_trust_level == DomainPackTrustLevel.reviewed_reusable


def test_domain_pack_upgrade_preserves_compatibility_and_reuses_installation_context() -> None:
    pack = _domain_pack()
    upgraded_pack = pack.upgrade(
        version="0.2.0",
        notes="upgrade with additional method coverage",
    )

    assert upgraded_pack.version == "0.2.0"
    assert upgraded_pack.supersedes_version == "0.1.0"
    assert upgraded_pack.review_status == pack.review_status
    assert upgraded_pack.trust_level == pack.trust_level
    assert upgraded_pack.compatibility == pack.compatibility
    assert upgraded_pack.content == pack.content
    assert upgraded_pack.notes == "upgrade with additional method coverage"

    installation = pack.install(
        project_id="proj_beta",
        installed_by="researcher",
        project_tags=["spectral", "analysis"],
        available_asset_ids=["asset_uniformity", "asset_spectral_lemma"],
        available_asset_kinds=["proof_pattern", "theorem_contract"],
        notation_profile="spectral_default",
    )
    upgraded_installation = installation.upgrade_from_pack(
        upgraded_pack,
        installed_by="lead",
        notes="rolled forward to the newer pack version",
    )

    assert upgraded_installation.status == DomainPackLifecycleStatus.upgraded
    assert upgraded_installation.pack_version == "0.2.0"
    assert upgraded_installation.project_id == "proj_beta"
    assert upgraded_installation.review_status == installation.review_status
    assert upgraded_installation.trust_level == installation.trust_level
    assert upgraded_installation.compatibility == installation.compatibility
    assert upgraded_installation.compatibility_check.compatible is True
    assert upgraded_installation.content_snapshot == upgraded_pack.content
    assert upgraded_installation.supersedes_installation_id == installation.id
    assert upgraded_installation.installed_by == "lead"
    assert upgraded_installation.notes == "rolled forward to the newer pack version"


def test_domain_pack_compatibility_exposes_missing_requirements_and_blocks_installation() -> None:
    pack = _domain_pack()

    compatibility_check = pack.compatibility.evaluate(
        pack_version="0.1.0",
        project_id="proj_gamma",
        project_tags=["spectral"],
        available_asset_ids=["asset_uniformity"],
        available_asset_kinds=["proof_pattern"],
        notation_profile="other_profile",
    )

    assert compatibility_check.compatible is False
    assert compatibility_check.version_allowed is True
    assert compatibility_check.missing_project_tags == ["analysis"]
    assert compatibility_check.missing_asset_ids == ["asset_spectral_lemma"]
    assert compatibility_check.missing_asset_kinds == ["theorem_contract"]
    assert compatibility_check.notation_profile_match is False
    assert "missing required project tag(s): analysis" in compatibility_check.reason
    assert "missing required asset id(s): asset_spectral_lemma" in compatibility_check.reason
    assert "missing required asset kind(s): theorem_contract" in compatibility_check.reason
    assert "notation profile other_profile does not match required profile spectral_default" in compatibility_check.reason

    with pytest.raises(ValueError, match="not compatible with project proj_gamma"):
        pack.install(
            project_id="proj_gamma",
            installed_by="researcher",
            project_tags=["spectral"],
            available_asset_ids=["asset_uniformity"],
            available_asset_kinds=["proof_pattern"],
            notation_profile="other_profile",
        )
