from __future__ import annotations

import json
from pathlib import Path

from proof_cli.commands import (
    cmd_branch_create,
    cmd_comment_add,
    cmd_comment_list,
    cmd_contributor_list,
    cmd_exchange_export,
    cmd_exchange_import,
    cmd_handoff_create,
    cmd_handoff_inspect,
    cmd_publication_set,
    cmd_publication_view,
    cmd_proof_asset_publish,
    cmd_review_decide,
    cmd_review_list,
    cmd_review_request,
    cmd_export,
)
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.reusable_assets import (
    ReusableAsset,
    ReusableAssetKind,
    ReusableAssetPayload,
    ReusableAssetProvenance,
    ReusableAssetReuseStatus,
    ReusableAssetTrustLevel,
)
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem


def test_exchange_round_trips_collaboration_state_across_two_users(tmp_path: Path) -> None:
    source_root = tmp_path / "alice"
    target_root = tmp_path / "bob"
    store = ensure_project(source_root)

    add_theorem(
        store,
        theorem_id="thm_family",
        kind="lemma",
        name="Imported Family Lemma",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        created_by="alice",
        updated_by="alice",
        contributors=["alice"],
    )
    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Section Target",
        statement="A implies C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_family"],
        created_by="alice",
        updated_by="alice",
        contributors=["alice", "bob"],
    )

    review_request = cmd_review_request("theorem_contract", "thm_main", root=source_root, reviewer_id="advisor", rationale="check the bridge")
    review_id = json.loads(review_request)["id"]
    cmd_review_decide(review_id, "disputed", root=source_root, reviewer_id="advisor", rationale="need a better lift")
    cmd_comment_add("theorem_contract", "thm_main", "This route still needs the scalar-to-vector lift.", root=source_root, author_id="bob")
    cmd_branch_create("theorem_contract", "scalar_route", root=source_root, created_by="alice", downstream_asset_id=["asset_family"])

    asset = ReusableAsset(
        id="asset_family_bridge",
        kind=ReusableAssetKind.proof_pattern,
        name="Family bridge pattern",
        summary="Shared team pattern for lifting family lemmas",
        team_scope="team_radial",
        payload=ReusableAssetPayload(pattern_steps=["inspect family lemma", "lift scalar case", "bridge to vector case"]),
        provenance=ReusableAssetProvenance(origin_project_id="proj_alpha", source_contract_ids=["thm_family", "thm_main"], notes="published by alice"),
        reuse_status=ReusableAssetReuseStatus.project_local,
        trust_level=ReusableAssetTrustLevel.project_verified,
        reviewed_by="alice",
        review_notes="published after collaborative review",
    )
    cmd_proof_asset_publish(asset.model_dump_json(), root=source_root, review_action="approve", reviewer="alice", notes="approved for team use")
    cmd_publication_set(
        "thm_main",
        "paper_ready",
        root=source_root,
        title="Publication Claim",
        section_placement="Section 1",
        reason="ready for paper export",
        release_status="approved",
    )

    handoff_bundle = cmd_handoff_create(root=source_root, note="alice pauses after a disputed route")
    inspection = json.loads(cmd_handoff_inspect(handoff_bundle))
    assert "project_state" in inspection["preserved"]
    assert "collaboration" in inspection["preserved"]
    assert "publication_workspace" in inspection["preserved"]

    import_report = json.loads(cmd_exchange_import(handoff_bundle, root=target_root))
    assert "project_state" in import_report["imported_sections"]
    assert "collaboration" in import_report["imported_sections"]
    assert "latest_snapshot" in import_report["imported_sections"]
    assert "handoff_snapshot" in import_report["imported_sections"]
    assert "publication_workspace" in import_report["imported_sections"]

    assert "alice" in cmd_contributor_list(root=target_root)
    assert "theorem_contract/thm_main" in cmd_review_list(root=target_root, object_type="theorem_contract", object_id="thm_main")
    assert "This route still needs the scalar-to-vector lift." in cmd_comment_list(root=target_root, object_type="theorem_contract", object_id="thm_main")
    assert "scalar_route" in cmd_export(root=target_root)
    assert "Publication workspace:" in cmd_publication_view(root=target_root)

    cmd_comment_add("theorem_contract", "thm_main", "Bob can continue from the imported handoff.", root=target_root, author_id="bob")
    handoff_after_import = json.loads(cmd_handoff_inspect(root=target_root))
    assert "project_state" in handoff_after_import["preserved"]
    assert handoff_after_import["section_counts"]["comments"] >= 1

    exchange_bundle = json.loads(cmd_exchange_export(root=target_root))
    assert exchange_bundle["project_id"] == "proj_alpha"
    assert exchange_bundle["collaboration"]["comment_threads"]
    assert exchange_bundle["publication_workspace"]["states"]
