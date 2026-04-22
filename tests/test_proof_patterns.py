from __future__ import annotations

import pytest

from proof_cli.proof_patterns import (
    BlockerRepairPair,
    ProofPattern,
    ProofPatternKind,
    ProofPatternPayload,
    ProofPatternProvenance,
    ProofPatternReuseStatus,
    ProofPatternTrustLevel,
)
from proof_cli.reusable_assets import ReusableAssetKind


@pytest.mark.parametrize(
    (
        "kind",
        "reuse_status",
        "payload_kwargs",
        "expected_pattern_field",
        "expected_pattern_value",
        "expected_asset_kind",
        "expected_asset_field",
        "expected_asset_value",
    ),
    [
        (
            ProofPatternKind.proof_decomposition,
            ProofPatternReuseStatus.project_local,
            {
                "decomposition_steps": ["split the theorem", "reduce to local claims"],
                "notes": "decomposition draft",
                },
            "decomposition_steps",
            ["split the theorem", "reduce to local claims"],
            ReusableAssetKind.proof_pattern,
            "pattern_steps",
            ["split the theorem", "reduce to local claims"],
        ),
        (
            ProofPatternKind.theorem_application,
            ProofPatternReuseStatus.private_experimental,
            {
                "theorem_application_steps": ["check assumptions", "apply the lemma"],
                "notes": "application workflow",
                },
            "theorem_application_steps",
            ["check assumptions", "apply the lemma"],
            ReusableAssetKind.proof_pattern,
            "method_steps",
            ["check assumptions", "apply the lemma"],
        ),
        (
            ProofPatternKind.dangerous_omission,
            ProofPatternReuseStatus.domain_shared,
            {
                "omission_signals": ["hidden side condition", "compressed standard step"],
                "notes": "omission warning",
                },
            "omission_signals",
            ["hidden side condition", "compressed standard step"],
            ReusableAssetKind.bug_archetype,
            "bug_signals",
            ["hidden side condition", "compressed standard step"],
        ),
        (
            ProofPatternKind.blocker_repair_pair,
            ProofPatternReuseStatus.approved_reusable,
            {
                "blocker_signals": ["uniformity gap", "route stalls at the same estimate"],
                "repair_steps": ["separate the uniform bound", "prove the missing lemma"],
                "notes": "repair pattern draft",
            },
            "repair_steps",
            ["separate the uniform bound", "prove the missing lemma"],
            ReusableAssetKind.blocker_pattern,
            "repair_steps",
            [
                "separate the uniform bound",
                "prove the missing lemma",
                "derive a uniform bound",
                "revisit the theorem application",
            ],
        ),
        (
            ProofPatternKind.formalization_recommendation,
            ProofPatternReuseStatus.project_local,
            {
                "formalization_steps": ["encode the side conditions", "route to machine check"],
                "notes": "escalation advice",
                },
            "formalization_steps",
            ["encode the side conditions", "route to machine check"],
            ReusableAssetKind.method_card,
            "verification_targets",
            ["encode the side conditions", "route to machine check"],
        ),
        (
            ProofPatternKind.debug_workflow,
            ProofPatternReuseStatus.private_experimental,
            {
                "debug_steps": ["inspect the blocker", "try the boundary case", "record the repair"],
                "notes": "debug routine",
                },
            "debug_steps",
            ["inspect the blocker", "try the boundary case", "record the repair"],
            ReusableAssetKind.proof_pattern,
            "checklist_items",
            ["inspect the blocker", "try the boundary case", "record the repair"],
        ),
    ],
)
def test_proof_pattern_round_trips_and_publishes_to_reusable_assets(
    kind: ProofPatternKind,
    reuse_status: ProofPatternReuseStatus,
    payload_kwargs: dict[str, object],
    expected_pattern_field: str,
    expected_pattern_value: object,
    expected_asset_kind: ReusableAssetKind,
    expected_asset_field: str,
    expected_asset_value: object,
) -> None:
    repair_pair = BlockerRepairPair(
        id="repair_1",
        name="Nonuniformity repair pair",
        summary="Blocker-repair link for a uniformity failure",
        blocker_id="blk_1",
        blocker_summary="uniformity is not controlled",
        repair_strategy="split the uniformity claim from the pointwise argument",
        repair_steps=["derive a uniform bound", "revisit the theorem application"],
        linked_pattern_ids=["pattern_seed"],
        linked_contract_ids=["thm_seed"],
        provenance=ProofPatternProvenance(
            origin_project_id="proj_alpha",
            source_contract_ids=["thm_seed"],
            source_reference_ids=["ref_seed"],
            notes="captured from a successful repair loop",
        ),
        reuse_status=ProofPatternReuseStatus.project_local,
        trust_level=ProofPatternTrustLevel.temporary_admit,
    )
    pattern = ProofPattern(
        id=f"pattern_{kind.value}",
        kind=kind,
        name=f"Reusable {kind.value}",
        summary="Reusable proof intelligence asset",
        payload=ProofPatternPayload(**payload_kwargs),
        blocker_repair_pairs=[repair_pair],
        provenance=ProofPatternProvenance(
            origin_project_id="proj_alpha",
            origin_pattern_id="pattern_seed",
            source_contract_ids=["thm_1", "lemma_2"],
            source_reference_ids=["ref_1"],
            linked_blocker_ids=["blk_1"],
            linked_repair_ids=["repair_1"],
            linked_verification_fragment_ids=["vf_1"],
            derived_from_pattern_ids=["pattern_seed"],
            notes="mined from a validated workflow",
        ),
        reuse_status=reuse_status,
        trust_level=ProofPatternTrustLevel.project_verified,
        reviewed_by="researcher",
        review_notes="initial review",
    )

    reloaded = ProofPattern.model_validate_json(pattern.model_dump_json())
    asset = pattern.to_reusable_asset()

    assert reloaded == pattern
    assert reloaded.version == 1
    assert reloaded.blocker_repair_pairs[0] == repair_pair
    assert reloaded.provenance.origin_project_id == "proj_alpha"
    assert reloaded.provenance.source_contract_ids == ["thm_1", "lemma_2"]
    assert reloaded.reviewed_by == "researcher"
    assert reloaded.review_notes == "initial review"
    assert getattr(reloaded.payload, expected_pattern_field) == expected_pattern_value
    assert reloaded.is_local() is (reuse_status == ProofPatternReuseStatus.project_local)
    assert reloaded.is_private() is (reuse_status == ProofPatternReuseStatus.private_experimental)
    assert reloaded.is_shared() is (reuse_status == ProofPatternReuseStatus.domain_shared)
    assert reloaded.is_approved() is (reuse_status == ProofPatternReuseStatus.approved_reusable)
    assert reloaded.is_reusable() is (reuse_status in {ProofPatternReuseStatus.domain_shared, ProofPatternReuseStatus.approved_reusable})
    assert asset.kind == expected_asset_kind
    assert getattr(asset.payload, expected_asset_field) == expected_asset_value
    assert asset.provenance.origin_project_id == "proj_alpha"
    assert asset.provenance.source_contract_ids == ["thm_1", "lemma_2"]
    assert asset.provenance.linked_blocker_ids == ["blk_1"]
    assert asset.provenance.linked_repair_ids == ["repair_1"]
    assert asset.reuse_status.value == reuse_status.value
    assert asset.trust_level.value == ProofPatternTrustLevel.project_verified.value


def test_proof_pattern_publication_retains_provenance_through_reuse() -> None:
    pattern = ProofPattern(
        id="pattern_lifecycle",
        kind=ProofPatternKind.blocker_repair_pair,
        name="Uniformity-before-summation pattern",
        summary="A reusable proof-development pattern",
        payload=ProofPatternPayload(
            blocker_signals=["uniformity is not controlled"],
            repair_steps=["separate the uniformity claim", "close the local estimate"],
            debug_steps=["inspect the blocker", "split the proof route"],
        ),
        blocker_repair_pairs=[
            BlockerRepairPair(
                id="repair_2",
                name="Uniformity repair",
                summary="Repair a nonuniform theorem application",
                blocker_id="blk_uniformity",
                blocker_summary="uniformity is the missing ingredient",
                repair_strategy="derive a uniform estimate before the summation step",
                repair_steps=["prove the uniform estimate", "re-run the theorem application"],
                linked_contract_ids=["thm_uniformity"],
                provenance=ProofPatternProvenance(
                    origin_project_id="proj_alpha",
                    source_contract_ids=["thm_uniformity"],
                    source_reference_ids=["ref_uniformity"],
                    notes="extracted from a successful repair",
                ),
            )
        ],
        provenance=ProofPatternProvenance(
            origin_project_id="proj_alpha",
            source_contract_ids=["thm_uniformity"],
            source_reference_ids=["ref_uniformity"],
            linked_blocker_ids=["blk_uniformity"],
            linked_repair_ids=["repair_2"],
            notes="captured from a working proof session",
        ),
        reuse_status=ProofPatternReuseStatus.project_local,
        trust_level=ProofPatternTrustLevel.temporary_admit,
        reviewed_by="author",
        review_notes="draft",
    )

    private_pattern = pattern.move_to_private_experimental(
        reviewer="author",
        trust_level=ProofPatternTrustLevel.project_verified,
        notes="keep private while validating the pattern",
    )
    shared_pattern = private_pattern.publish_to_domain_shared(
        reviewer="reviewer",
        trust_level=ProofPatternTrustLevel.reviewed_reusable,
        notes="shared with the domain pack",
    )
    approved_pattern = shared_pattern.approve_for_reuse(
        reviewer="lead",
        trust_level=ProofPatternTrustLevel.domain_trusted,
        notes="approved for cross-project reuse",
    )
    reused_pattern = approved_pattern.reuse_for_project(
        project_id="proj_beta",
        reviewer="researcher",
        notes="applied to the beta project",
        linked_contract_ids=["thm_beta"],
        linked_blocker_ids=["blk_beta"],
        linked_repair_ids=["repair_beta"],
    )
    reusable_asset = reused_pattern.to_reusable_asset()

    assert pattern.reuse_status == ProofPatternReuseStatus.project_local
    assert pattern.version == 1
    assert private_pattern.reuse_status == ProofPatternReuseStatus.private_experimental
    assert private_pattern.version == 2
    assert private_pattern.supersedes_version == 1
    assert shared_pattern.reuse_status == ProofPatternReuseStatus.domain_shared
    assert shared_pattern.version == 3
    assert approved_pattern.reuse_status == ProofPatternReuseStatus.approved_reusable
    assert approved_pattern.is_reusable() is True
    assert approved_pattern.version == 4
    assert reused_pattern.version == 5
    assert reused_pattern.provenance.origin_project_id == "proj_alpha"
    assert reused_pattern.provenance.derived_from_pattern_ids == ["pattern_lifecycle"]
    assert reused_pattern.provenance.source_contract_ids == ["thm_uniformity", "thm_beta"]
    assert reused_pattern.provenance.linked_blocker_ids == ["blk_uniformity", "blk_beta"]
    assert reused_pattern.provenance.linked_repair_ids == ["repair_2", "repair_beta"]
    assert reused_pattern.reviewed_by == "researcher"
    assert reused_pattern.review_notes == "applied to the beta project"
    assert reusable_asset.provenance.origin_project_id == "proj_alpha"
    assert reusable_asset.provenance.derived_from_asset_ids == ["pattern_lifecycle"]
    assert reusable_asset.provenance.linked_blocker_ids == ["blk_uniformity", "blk_beta"]
    assert reusable_asset.provenance.linked_repair_ids == ["repair_2", "repair_beta"]
    assert reusable_asset.payload.repair_steps == [
        "separate the uniformity claim",
        "close the local estimate",
        "prove the uniform estimate",
        "re-run the theorem application",
    ]


def test_blocker_repair_pair_can_publish_as_a_first_class_asset() -> None:
    pair = BlockerRepairPair(
        id="pair_3",
        name="Boundary-case repair",
        summary="Repair a proof by checking the boundary case explicitly",
        blocker_id="blk_boundary",
        blocker_summary="the argument fails at the boundary",
        repair_strategy="split the proof into boundary and interior cases",
        repair_steps=["check the boundary case", "close the interior case"],
        linked_pattern_ids=["pattern_boundary"],
        linked_contract_ids=["thm_boundary"],
        provenance=ProofPatternProvenance(
            origin_project_id="proj_gamma",
            source_contract_ids=["thm_boundary"],
            source_reference_ids=["ref_boundary"],
            notes="extracted from a reusable repair loop",
        ),
        reuse_status=ProofPatternReuseStatus.project_local,
        trust_level=ProofPatternTrustLevel.temporary_admit,
        reviewed_by="author",
        review_notes="draft pair",
    )

    reloaded = BlockerRepairPair.model_validate_json(pair.model_dump_json())
    shared_pair = pair.publish_to_domain_shared(
        reviewer="reviewer",
        trust_level=ProofPatternTrustLevel.reviewed_reusable,
        notes="approved as a shared repair pair",
    )
    asset = shared_pair.to_reusable_asset()

    assert reloaded == pair
    assert reloaded.blocker_id == "blk_boundary"
    assert shared_pair.reuse_status == ProofPatternReuseStatus.domain_shared
    assert shared_pair.version == 2
    assert asset.kind == ReusableAssetKind.blocker_pattern
    assert asset.summary == "Repair a proof by checking the boundary case explicitly"
    assert asset.payload.repair_steps == ["check the boundary case", "close the interior case"]
    assert asset.provenance.origin_project_id == "proj_gamma"
    assert asset.provenance.linked_blocker_ids == ["blk_boundary"]
    assert asset.provenance.linked_repair_ids == ["pair_3"]
