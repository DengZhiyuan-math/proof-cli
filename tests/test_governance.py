from __future__ import annotations

import json
from pathlib import Path

from proof_cli.automation import AutomationActionType, AutomationExecutionMode, AutomationTaskType, build_action
from proof_cli.automation_eval import AutomationEvaluationMode, build_automation_evaluation_record
from proof_cli.commands import (
    cmd_proof_asset_list,
    cmd_proof_asset_publish,
    cmd_proof_automate_plan,
    cmd_proof_automate_review,
    cmd_proof_automate_run,
    cmd_proof_automate_trace,
    cmd_proof_benchmark_run,
    cmd_proof_pack_install,
    cmd_proof_policy_list,
    cmd_proof_policy_set,
    cmd_proof_recommend,
    cmd_proof_reuse_show,
)
from proof_cli.domain_packs import DomainPack, DomainPackCompatibility, DomainPackContent, DomainPackReviewStatus, DomainPackTrustLevel
from proof_cli.governance import (
    list_automation_records,
    list_benchmark_records,
    list_domain_pack_records,
    list_policy_records,
    list_recommendation_records,
    list_reusable_asset_records,
    list_reuse_records,
    record_reuse_outcome,
)
from proof_cli.reusable_assets import (
    ReusableAsset,
    ReusableAssetKind,
    ReusableAssetPayload,
    ReusableAssetProvenance,
    ReusableAssetReuseStatus,
    ReusableAssetTrustLevel,
)
from proof_cli.automation_policy import build_policy_profile
from proof_cli.storage import ensure_project


def _asset(asset_id: str, project_id: str, *, trust_level: ReusableAssetTrustLevel, reuse_status: ReusableAssetReuseStatus, notes: str) -> ReusableAsset:
    return ReusableAsset(
        id=asset_id,
        kind=ReusableAssetKind.proof_pattern,
        name="Uniformity-before-summation pattern",
        summary="Reusable proof-development pattern",
        payload=ReusableAssetPayload(
            pattern_steps=["inspect uniformity", "separate the sum", "close the route"],
            notes=notes,
        ),
        provenance=ReusableAssetProvenance(
            origin_project_id=project_id,
            source_contract_ids=["thm_uniformity"],
            source_reference_ids=["ref_uniformity"],
            notes=notes,
        ),
        reuse_status=reuse_status,
        trust_level=trust_level,
        reviewed_by="researcher",
        review_notes=notes,
    )


def _pack(pack_id: str, project_id: str) -> DomainPack:
    return DomainPack(
        id=pack_id,
        name="Spectral-Analysis-Pack",
        version="0.1.0",
        summary="Reusable spectral workflow pack",
        content=DomainPackContent(
            theorem_templates=["spectral decomposition theorem template"],
            method_templates=["retrieve known result first", "check side conditions explicitly"],
            omission_rules=["expand all standard estimates into explicit side conditions"],
            bug_patterns=["hidden uniformity gap"],
            formalization_preferences=["escalate fragile theorem applications"],
            debug_task_templates=["test the boundary parameter regime"],
            notation_conventions=["use lambda for eigenvalue parameters"],
            notes="pack contents should remain inspectable",
        ),
        compatibility=DomainPackCompatibility(
            required_project_tags=["spectral", "analysis"],
            required_asset_ids=["asset_shared_uniformity"],
            required_asset_kinds=["proof_pattern"],
            required_notation_profile="spectral_default",
            allowed_pack_versions=["0.1.0"],
            notes="compatible with the spectral workflow family",
        ),
        review_status=DomainPackReviewStatus.approved,
        trust_level=DomainPackTrustLevel.reviewed_reusable,
        reviewed_by="reviewer",
        review_notes="approved for cross-project installation",
        origin_project_id=project_id,
        source_asset_ids=["asset_shared_uniformity"],
        notes="domain pack for repeated spectral proof workflows",
    )


def test_governance_workflow_compounds_across_multiple_projects(tmp_path: Path) -> None:
    project_alpha = ensure_project(tmp_path / "alpha")
    project_beta = ensure_project(tmp_path / "beta")
    project_gamma = ensure_project(tmp_path / "gamma")

    asset_local = _asset(
        "asset_local_uniformity",
        "proj_alpha",
        trust_level=ReusableAssetTrustLevel.project_verified,
        reuse_status=ReusableAssetReuseStatus.project_local,
        notes="local draft workflow",
    )
    asset_shared = _asset(
        "asset_shared_uniformity",
        "proj_alpha",
        trust_level=ReusableAssetTrustLevel.reviewed_reusable,
        reuse_status=ReusableAssetReuseStatus.approved_reusable,
        notes="approved for cross-project reuse",
    )
    asset_prior = _asset(
        "asset_prior_boundary",
        "proj_gamma",
        trust_level=ReusableAssetTrustLevel.temporary_admit,
        reuse_status=ReusableAssetReuseStatus.private_experimental,
        notes="prior project boundary case",
    )
    pack = _pack("pack_spectral_analysis", "proj_alpha")

    asset_payload = cmd_proof_asset_publish(asset_shared.model_dump_json(), root=tmp_path / "alpha", review_action="approve", reviewer="lead", notes="approved reusable asset")
    assert "asset_shared_uniformity" in asset_payload
    assert "approved_reusable" in asset_payload
    cmd_proof_asset_publish(asset_local.model_dump_json(), root=tmp_path / "alpha", review_action="publish", reviewer="researcher", notes="local asset published")
    cmd_proof_asset_publish(asset_prior.model_dump_json(), root=tmp_path / "gamma", review_action="private", reviewer="researcher", notes="private experimental reuse")

    cmd_proof_pack_install(
        pack.model_dump_json(),
        root=tmp_path / "alpha",
        installed_by="reviewer",
        project_tags=["spectral", "analysis"],
        available_asset_ids=["asset_shared_uniformity", "asset_local_uniformity"],
        available_asset_kinds=["proof_pattern"],
        notation_profile="spectral_default",
        notes="installed in alpha",
    )
    cmd_proof_pack_install(
        pack.model_dump_json(),
        root=tmp_path / "beta",
        installed_by="reviewer",
        project_tags=["spectral", "analysis", "functional"],
        available_asset_ids=["asset_shared_uniformity"],
        available_asset_kinds=["proof_pattern"],
        notation_profile="spectral_default",
        notes="installed in beta",
    )

    policy_profile = build_policy_profile(
        project_id="proj_alpha",
        allowed_actions=[
            AutomationActionType.inspect_state,
            AutomationActionType.retrieve_assets,
            AutomationActionType.check_policy,
            AutomationActionType.generate_plan,
            AutomationActionType.request_review,
            AutomationActionType.execute_task,
            AutomationActionType.record_trace,
            AutomationActionType.publish_reusable_outcome,
            AutomationActionType.rollback,
            AutomationActionType.interrupt,
        ],
        approval_required_for=[],
        forbidden_actions=[AutomationActionType.publish_reusable_outcome, AutomationActionType.rollback],
        notes="bounded local reasoning",
    )
    policy_payload = cmd_proof_policy_set(policy_profile.model_dump_json(), root=tmp_path / "alpha", reviewer="lead", notes="alpha policy")
    assert "bounded local reasoning" in policy_payload
    assert "proj_alpha" in cmd_proof_policy_list(root=tmp_path / "alpha")

    recommendation_payload = cmd_proof_recommend(
        root=tmp_path / "alpha",
        query="uniformity before summation",
        current_project_id="proj_alpha",
        current_project_assets_json=[asset_local.model_dump_json()],
        shared_assets_json=[asset_shared.model_dump_json()],
        prior_project_assets_json=[asset_prior.model_dump_json()],
        domain_packs_json=[pack.model_dump_json()],
        prior_usefulness_json=json.dumps(
            {
                asset_shared.id: 0.95,
                asset_prior.id: 0.35,
                pack.id: 0.82,
            }
        ),
        limit=5,
    )
    assert "asset_shared_uniformity" in recommendation_payload
    assert "pack_spectral_analysis" in recommendation_payload

    record_reuse_outcome(project_alpha, asset_id=asset_shared.id, used_in_project="proj_beta", outcome="helpful", notes="reduced duplicate search", reviewed_by_human=True)
    reuse_payload = cmd_proof_reuse_show(root=tmp_path / "alpha", asset_id=asset_shared.id)
    assert "asset_shared_uniformity" in reuse_payload
    assert "helpful" in reuse_payload

    plan_payload = cmd_proof_automate_plan(
        root=tmp_path / "alpha",
        scope="theorem_7",
        task_type=AutomationTaskType.theorem_application_checks.value,
        action_json=[
            json.dumps(
                {
                    "action_type": "inspect_state",
                    "description": "inspect local theorem state",
                    "risk_level": "low",
                    "reversible": True,
                }
            ),
            json.dumps(
                {
                    "action_type": "publish_reusable_outcome",
                    "description": "publish reusable proof outcome",
                    "risk_level": "trust_sensitive",
                    "reversible": False,
                }
            ),
        ],
        policy_json=policy_profile.model_dump_json(),
        execution_mode=AutomationExecutionMode.supervised.value,
        notes="bounded automation for the alpha project",
    )
    plan_record = json.loads(plan_payload)
    run_id = plan_record["run"]["id"]
    action_id = plan_record["run"]["planned_actions"][0]["id"]
    assert plan_record["run"]["status"] == "planned"

    run_payload = cmd_proof_automate_run(run_id, root=tmp_path / "alpha", notes="run the planned sequence")
    run_record = json.loads(run_payload)
    assert run_record["run"]["planned_actions"][0]["status"] == "completed"
    assert run_record["run"]["planned_actions"][1]["status"] == "rejected"

    trace_payload = cmd_proof_automate_trace(run_id, root=tmp_path / "alpha")
    assert "action_completed" in trace_payload
    assert "action_rejected" in trace_payload

    review_payload = cmd_proof_automate_review(run_id, action_id, root=tmp_path / "alpha", decision="approve", reviewer="lead", rationale="safe to retain")
    assert "accepted_after_review" in review_payload

    assisted_record = build_automation_evaluation_record(
        benchmark_name="phase5-compounding",
        scenario_id="scenario_uniformity",
        project_id="proj_alpha",
        task_type="theorem_application_checks",
        mode=AutomationEvaluationMode.assisted,
        time_spent_minutes=10.0,
        obligations_resolved=4,
        false_positives=1,
        review_burden_minutes=2.0,
        stale_automation_count=0,
        repeated_error_reduction_count=2,
        reuse_hits=3,
        accepted_actions=4,
        rejected_actions=0,
    )
    baseline_record = build_automation_evaluation_record(
        benchmark_name="phase5-compounding",
        scenario_id="scenario_uniformity",
        project_id="proj_beta",
        task_type="theorem_application_checks",
        mode=AutomationEvaluationMode.non_assisted,
        time_spent_minutes=18.0,
        obligations_resolved=2,
        false_positives=3,
        review_burden_minutes=4.0,
        stale_automation_count=2,
        repeated_error_reduction_count=0,
        reuse_hits=1,
        accepted_actions=2,
        rejected_actions=2,
    )
    benchmark_payload = cmd_proof_benchmark_run(
        root=tmp_path / "alpha",
        benchmark_name="phase5-compounding",
        scenario_id="scenario_uniformity",
        record_json=[assisted_record.model_dump_json(), baseline_record.model_dump_json()],
        notes="multi-project benchmark replay",
    )
    assert "phase5-compounding" in benchmark_payload
    assert "assisted_better" in benchmark_payload

    assert "asset_shared_uniformity" in cmd_proof_asset_list(root=tmp_path / "alpha")
    assert "pack_spectral_analysis" in cmd_proof_pack_install(pack.model_dump_json(), root=tmp_path / "gamma", installed_by="reviewer", project_tags=["spectral", "analysis"], available_asset_ids=["asset_shared_uniformity"], available_asset_kinds=["proof_pattern"], notation_profile="spectral_default")

    alpha_assets = list_reusable_asset_records(project_alpha)
    alpha_packs = list_domain_pack_records(project_alpha)
    alpha_policies = list_policy_records(project_alpha)
    alpha_recommendations = list_recommendation_records(project_alpha)
    alpha_runs = list_automation_records(project_alpha)
    alpha_reuse = list_reuse_records(project_alpha, asset_id=asset_shared.id)
    alpha_benchmarks = list_benchmark_records(project_alpha)

    assert any(record.asset.id == asset_shared.id for record in alpha_assets)
    assert alpha_packs[-1].pack.id == pack.id
    assert alpha_policies[-1].profile.name == "bounded_local_reasoning"
    assert alpha_recommendations[-1].report.recommendations[0].candidate_id == asset_shared.id
    assert alpha_runs[-1].run.planned_actions[0].status.value == "completed"
    assert alpha_reuse[-1].outcome.outcome == "helpful"
    assert alpha_benchmarks[-1].replay.comparison is not None
    assert alpha_benchmarks[-1].replay.comparison.overall_interpretation == "assisted_better"
