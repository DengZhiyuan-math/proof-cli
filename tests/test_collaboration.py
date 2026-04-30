import json
from pathlib import Path

from proof_cli.commands import (
    cmd_branch_compare,
    cmd_branch_create,
    cmd_branch_list,
    cmd_branch_merge,
    cmd_comment_add,
    cmd_comment_list,
    cmd_contributor_list,
    cmd_export,
    cmd_review_decide,
    cmd_review_list,
    cmd_review_request,
    cmd_role_show,
    cmd_proof_asset_publish,
)
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.reusable_assets import ReusableAsset, ReusableAssetKind, ReusableAssetPayload, ReusableAssetProvenance, ReusableAssetReuseStatus, ReusableAssetTrustLevel
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem


def test_collaboration_records_persist_authorship_review_comments_and_branches(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_collab",
        kind="theorem",
        name="Collaborative Result",
        statement="A implies C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        created_by="alice",
        updated_by="alice",
        contributors=["alice", "bob"],
    )

    contributor_payload = cmd_contributor_list(root=tmp_path)
    assert "alice" in contributor_payload

    role_payload = cmd_role_show("alice", root=tmp_path)
    assert "alice" in role_payload

    review_request = cmd_review_request("theorem_contract", "thm_collab", root=tmp_path, reviewer_id="reviewer_1", rationale="check the bridge")
    review_id = json.loads(review_request)["id"]
    review_decision = cmd_review_decide(review_id, "approved", root=tmp_path, reviewer_id="reviewer_1", rationale="approved")
    assert '"decision": "approved"' in review_decision
    review_list = cmd_review_list(root=tmp_path, object_type="theorem_contract", object_id="thm_collab")
    assert "theorem_contract/thm_collab" in review_list

    comment = cmd_comment_add("theorem_contract", "thm_collab", "This route needs a bridge lemma.", root=tmp_path, author_id="bob")
    assert "thread_" in comment
    comment_list = cmd_comment_list(root=tmp_path, object_type="theorem_contract", object_id="thm_collab")
    assert "This route needs a bridge lemma." in comment_list

    branch_one = cmd_branch_create("theorem_contract", "direct_route", root=tmp_path, created_by="alice", downstream_asset_id=["asset_alpha"])
    branch_one_id = json.loads(branch_one)["id"]
    branch_two = cmd_branch_create(
        "theorem_contract",
        "compressed_route",
        root=tmp_path,
        created_by="bob",
        derived_from=branch_one_id,
        downstream_asset_id=["asset_alpha", "asset_beta"],
    )
    branch_two_id = json.loads(branch_two)["id"]
    branch_list = cmd_branch_list(root=tmp_path, scope="theorem_contract")
    assert "direct_route" in branch_list
    comparison = cmd_branch_compare(branch_one_id, branch_two_id, root=tmp_path)
    comparison_payload = json.loads(comparison)
    assert comparison_payload["shared_downstream_asset_ids"] == ["asset_alpha"]
    merged = cmd_branch_merge(branch_two_id, root=tmp_path, into_branch_id=branch_one_id, reviewer_id="reviewer_1", rationale="consolidated")
    assert '"status": "merged"' in merged

    asset = ReusableAsset(
        id="asset_collab",
        kind=ReusableAssetKind.proof_pattern,
        name="Bridge pattern",
        summary="Reusable collaboration asset",
        payload=ReusableAssetPayload(pattern_steps=["inspect", "bridge", "close"]),
        provenance=ReusableAssetProvenance(origin_project_id="proj_alpha", source_contract_ids=["thm_collab"], notes="published from review"),
        reuse_status=ReusableAssetReuseStatus.project_local,
        trust_level=ReusableAssetTrustLevel.project_verified,
        reviewed_by="alice",
        review_notes="initial draft",
    )
    cmd_proof_asset_publish(asset.model_dump_json(), root=tmp_path, review_action="approve", reviewer="alice", notes="approved for team use")

    export_text = cmd_export(root=tmp_path)
    assert "Collaboration:" in export_text
    assert "Contributors:" in export_text
    assert "Review records:" in export_text
    assert "Comment threads:" in export_text
    assert "Branches:" in export_text
    assert "Shared publications:" in export_text
    assert "Bridge pattern" in export_text
