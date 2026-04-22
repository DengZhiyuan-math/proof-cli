from __future__ import annotations

import pytest

from proof_cli.reusable_assets import (
    ReusableAsset,
    ReusableAssetKind,
    ReusableAssetPayload,
    ReusableAssetProvenance,
    ReusableAssetReuseStatus,
    ReusableAssetTrustLevel,
)


@pytest.mark.parametrize(
    ("kind", "reuse_status", "payload_kwargs", "expected_field", "expected_value", "expected_flag"),
    [
        (
            ReusableAssetKind.theorem_contract,
            ReusableAssetReuseStatus.project_local,
            {
                "statement": "forall x, P(x) -> Q(x)",
                "assumptions": ["A"],
                "exports": ["B"],
            },
            "statement",
            "forall x, P(x) -> Q(x)",
            "local",
        ),
        (
            ReusableAssetKind.imported_reference_contract,
            ReusableAssetReuseStatus.approved_reusable,
            {
                "statement": "imported lemma with explicit scope",
                "assumptions": ["C"],
                "exports": ["D"],
                "notes": "reviewed imported reference",
            },
            "notes",
            "reviewed imported reference",
            "approved",
        ),
        (
            ReusableAssetKind.proof_pattern,
            ReusableAssetReuseStatus.private_experimental,
            {
                "pattern_steps": ["inspect state", "reuse known lemma", "close obligation"],
                "notes": "private pattern while iterating",
            },
            "pattern_steps",
            ["inspect state", "reuse known lemma", "close obligation"],
            "private",
        ),
        (
            ReusableAssetKind.blocker_pattern,
            ReusableAssetReuseStatus.domain_shared,
            {
                "pattern_steps": ["identify the blocker", "split the dependency", "recheck assumptions"],
                "notes": "shared blocker-handling workflow",
            },
            "pattern_steps",
            ["identify the blocker", "split the dependency", "recheck assumptions"],
            "shared",
        ),
        (
            ReusableAssetKind.repair_strategy,
            ReusableAssetReuseStatus.approved_reusable,
            {
                "repair_steps": ["weaken the conclusion", "add a boundary lemma"],
                "notes": "approved repair sequence",
            },
            "repair_steps",
            ["weaken the conclusion", "add a boundary lemma"],
            "approved",
        ),
        (
            ReusableAssetKind.bug_archetype,
            ReusableAssetReuseStatus.project_local,
            {
                "bug_signals": ["missing side condition", "silent strengthening"],
                "notes": "local bug archetype",
            },
            "bug_signals",
            ["missing side condition", "silent strengthening"],
            "local",
        ),
        (
            ReusableAssetKind.verification_fragment,
            ReusableAssetReuseStatus.private_experimental,
            {
                "verification_targets": ["lean4", "smt"],
                "notes": "machine-check fragment",
            },
            "verification_targets",
            ["lean4", "smt"],
            "private",
        ),
        (
            ReusableAssetKind.method_card,
            ReusableAssetReuseStatus.domain_shared,
            {
                "method_steps": ["retrieve first", "check assumptions", "apply known result"],
                "notes": "shared method card",
            },
            "method_steps",
            ["retrieve first", "check assumptions", "apply known result"],
            "shared",
        ),
        (
            ReusableAssetKind.domain_checklist,
            ReusableAssetReuseStatus.project_local,
            {
                "checklist_items": ["record blocker", "capture provenance", "note unresolved debt"],
                "notes": "domain checklist",
            },
            "checklist_items",
            ["record blocker", "capture provenance", "note unresolved debt"],
            "local",
        ),
    ],
)
def test_reusable_asset_round_trips_with_provenance_trust_and_versioning(
    kind: ReusableAssetKind,
    reuse_status: ReusableAssetReuseStatus,
    payload_kwargs: dict[str, object],
    expected_field: str,
    expected_value: object,
    expected_flag: str,
) -> None:
    asset = ReusableAsset(
        id=f"asset_{kind.value}",
        kind=kind,
        name=f"Reusable {kind.value}",
        summary="Reusable proof intelligence asset",
        payload=ReusableAssetPayload(**payload_kwargs),
        provenance=ReusableAssetProvenance(
            origin_project_id="proj_alpha",
            origin_asset_id="asset_seed",
            source_contract_ids=["thm_1", "lemma_2"],
            source_reference_ids=["ref_1"],
            derived_from_asset_ids=["asset_seed"],
            linked_blocker_ids=["blocker_1"],
            linked_repair_ids=["repair_1"],
            linked_verification_fragment_ids=["vf_1"],
            notes="captured from a validated workflow",
        ),
        reuse_status=reuse_status,
        trust_level=ReusableAssetTrustLevel.project_verified,
        reviewed_by="researcher",
        review_notes="initial review",
    )

    reloaded = ReusableAsset.model_validate_json(asset.model_dump_json())

    assert reloaded == asset
    assert reloaded.version == 1
    assert reloaded.supersedes_version is None
    assert reloaded.provenance.origin_project_id == "proj_alpha"
    assert reloaded.provenance.source_contract_ids == ["thm_1", "lemma_2"]
    assert reloaded.provenance.source_reference_ids == ["ref_1"]
    assert reloaded.provenance.derived_from_asset_ids == ["asset_seed"]
    assert getattr(reloaded.payload, expected_field) == expected_value
    assert reloaded.reviewed_by == "researcher"
    assert reloaded.review_notes == "initial review"

    if expected_flag == "local":
        assert reloaded.is_local() is True
        assert reloaded.is_private() is False
        assert reloaded.is_shared() is False
        assert reloaded.is_approved() is False
    elif expected_flag == "private":
        assert reloaded.is_local() is False
        assert reloaded.is_private() is True
        assert reloaded.is_shared() is False
        assert reloaded.is_approved() is False
    elif expected_flag == "shared":
        assert reloaded.is_local() is False
        assert reloaded.is_private() is False
        assert reloaded.is_shared() is True
        assert reloaded.is_approved() is False
    elif expected_flag == "approved":
        assert reloaded.is_local() is False
        assert reloaded.is_private() is False
        assert reloaded.is_shared() is False
        assert reloaded.is_approved() is True
    else:
        raise AssertionError(f"unexpected expected_flag: {expected_flag}")


def test_reusable_asset_lifecycle_tracks_scope_trust_and_version_chain() -> None:
    asset = ReusableAsset(
        id="asset_lifecycle",
        kind=ReusableAssetKind.proof_pattern,
        name="Uniformity-before-summation pattern",
        summary="A reusable proof-development pattern",
        payload=ReusableAssetPayload(
            pattern_steps=["inspect uniformity", "separate the sum", "close the route"],
        ),
        provenance=ReusableAssetProvenance(
            origin_project_id="proj_beta",
            source_contract_ids=["thm_uniformity"],
            source_reference_ids=["ref_uniformity"],
            notes="extracted from a successful session",
        ),
        reuse_status=ReusableAssetReuseStatus.project_local,
        trust_level=ReusableAssetTrustLevel.temporary_admit,
        reviewed_by="author",
        review_notes="draft",
    )

    private_asset = asset.move_to_private_experimental(
        reviewer="author",
        trust_level=ReusableAssetTrustLevel.project_verified,
        notes="keep private while validating the pattern",
    )
    shared_asset = private_asset.publish_to_domain_shared(
        reviewer="reviewer",
        trust_level=ReusableAssetTrustLevel.reviewed_reusable,
        notes="shared with the domain pack",
    )
    approved_asset = shared_asset.approve_for_reuse(
        reviewer="lead",
        trust_level=ReusableAssetTrustLevel.domain_trusted,
        notes="approved for cross-project reuse",
    )
    rejected_asset = asset.reject_reuse(
        reviewer="reviewer",
        notes="not enough provenance for reuse",
    )
    deprecated_asset = approved_asset.deprecate(
        reviewer="lead",
        notes="superseded by a stricter version",
    )

    assert asset.reuse_status == ReusableAssetReuseStatus.project_local
    assert asset.version == 1
    assert private_asset.reuse_status == ReusableAssetReuseStatus.private_experimental
    assert private_asset.is_private() is True
    assert private_asset.version == 2
    assert private_asset.supersedes_version == 1
    assert shared_asset.reuse_status == ReusableAssetReuseStatus.domain_shared
    assert shared_asset.is_shared() is True
    assert shared_asset.version == 3
    assert shared_asset.supersedes_version == 2
    assert approved_asset.reuse_status == ReusableAssetReuseStatus.approved_reusable
    assert approved_asset.is_approved() is True
    assert approved_asset.is_reusable() is True
    assert approved_asset.version == 4
    assert approved_asset.supersedes_version == 3
    assert approved_asset.trust_level == ReusableAssetTrustLevel.domain_trusted
    assert approved_asset.reviewed_by == "lead"
    assert approved_asset.review_notes == "approved for cross-project reuse"
    assert approved_asset.reviewed_at is not None
    assert rejected_asset.reuse_status == ReusableAssetReuseStatus.rejected
    assert rejected_asset.version == 2
    assert rejected_asset.supersedes_version == 1
    assert rejected_asset.reviewed_by == "reviewer"
    assert rejected_asset.review_notes == "not enough provenance for reuse"
    assert deprecated_asset.reuse_status == ReusableAssetReuseStatus.deprecated
    assert deprecated_asset.version == 5
    assert deprecated_asset.supersedes_version == 4
    assert deprecated_asset.is_reusable() is False
    assert deprecated_asset.provenance == approved_asset.provenance
    assert asset.provenance.origin_project_id == "proj_beta"
    assert asset.payload.pattern_steps == ["inspect uniformity", "separate the sum", "close the route"]

