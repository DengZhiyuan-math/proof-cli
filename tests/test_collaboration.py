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
import pytest

from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.proof_map import claim_node, create_node, decide_acceptance, submit_candidate_proof
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


def test_review_request_on_proof_map_node_is_rejected(tmp_path: Path) -> None:
    """The generic `proof review request` command must not accept a
    proof_map_node target: it would create a ReviewRecord with kind=None
    that get_acceptance_state silently ignores, letting a researcher believe
    a node was reviewed when acceptance_state never moved."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ValueError, match="proof node review"):
        cmd_review_request("proof_map_node", "clm_1", root=tmp_path, reviewer_id="researcher")


def test_review_decide_on_proof_map_node_review_is_rejected(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    submit_candidate_proof(
        store, "clm_1", claimant_id="agent_a", session_id="sess_1",
        scoping_rationale="scoped correctly", content="proof text",
    )
    record = decide_acceptance(store, "clm_1", "accept", reviewer_id="researcher", confirmed=True)

    with pytest.raises(ValueError, match="proof node review"):
        cmd_review_decide(record.id, "rejected", root=tmp_path, reviewer_id="researcher")


def test_review_decide_invalid_decision_raises_clean_value_error(tmp_path: Path) -> None:
    """A bad decision string (e.g. the hyphenated vocabulary `proof node
    review` teaches) must fail with a catchable ValueError, not a bare
    Python traceback from the ReviewGovernanceState(...) constructor."""
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="A result",
        statement="A implies B",
    )
    review_request = cmd_review_request("theorem_contract", "thm_1", root=tmp_path, reviewer_id="reviewer_1")
    review_id = json.loads(review_request)["id"]

    with pytest.raises(ValueError, match="not a valid review decision"):
        cmd_review_decide(review_id, "revision-requested", root=tmp_path, reviewer_id="reviewer_1")


def test_summarize_review_record_includes_kind_when_present() -> None:
    from proof_cli.collaboration import ReviewGovernanceState, ReviewRecord, ReviewRecordKind, summarize_review_record

    with_kind = ReviewRecord(
        object_type="proof_map_node", object_id="clm_1", reviewer_id="researcher",
        decision=ReviewGovernanceState.approved, kind=ReviewRecordKind.acceptance,
    )
    without_kind = ReviewRecord(
        object_type="theorem_contract", object_id="thm_1", reviewer_id="researcher",
        decision=ReviewGovernanceState.approved,
    )
    assert "kind=acceptance" in summarize_review_record(with_kind)
    assert "kind=" not in summarize_review_record(without_kind)
