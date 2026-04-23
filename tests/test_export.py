import json
from pathlib import Path

from proof_cli.automation import AutomationActionType, AutomationExecutionMode, AutomationTaskType
from proof_cli.automation_eval import AutomationEvaluationMode, build_automation_evaluation_record
from proof_cli.blockers import add_blocker
from proof_cli.commands import (
    cmd_proof_asset_publish,
    cmd_publication_export,
    cmd_publication_set,
    cmd_export,
    cmd_proof_automate_plan,
    cmd_proof_automate_run,
    cmd_proof_automate_trace,
    cmd_proof_benchmark_run,
    cmd_proof_bug_scan,
    cmd_proof_debug_generate,
    cmd_proof_evidence_show,
    cmd_proof_reason,
    cmd_proof_repair_mark,
    cmd_proof_review_suspicion,
    cmd_proof_pack_install,
    cmd_proof_policy_set,
    cmd_proof_recommend,
    cmd_proof_reuse_show,
    cmd_theorem_ground,
)
from proof_cli.automation_policy import build_policy_profile
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.domain_packs import DomainPack, DomainPackCompatibility, DomainPackContent, DomainPackReviewStatus, DomainPackTrustLevel
from proof_cli.formal_bridge import FormalBridgeProofStep, translate_proof_step
from proof_cli.governance import record_reuse_outcome
from proof_cli.memory import load_memory, record_memory, record_verification_lifecycle, record_verification_staleness
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import load_state, record_theorem_usage, set_current_context, set_current_theorem
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.snapshot import create_snapshot
from proof_cli.storage import approve_reference, ensure_project, import_reference, list_references, read_latest_snapshot
from proof_cli.reusable_assets import ReusableAsset, ReusableAssetKind, ReusableAssetPayload, ReusableAssetProvenance, ReusableAssetReuseStatus, ReusableAssetTrustLevel
from proof_cli.theorems import add_theorem, list_theorems
from proof_cli.verification_ir import (
    VerificationAssumption,
    VerificationFragmentStatus,
    VerificationProvenance,
    VerificationResult,
    VerificationReviewStatus,
    VerificationScope,
    VerificationSideCondition,
    VerificationSourceKind,
    VerificationTheoremApplication,
    VerificationTranslationStatus,
)
from proof_cli.verification_results import record_verification_result


def _seed_real_project(tmp_path: Path) -> tuple[str, str]:
    store = ensure_project(tmp_path)

    standard_reference = import_reference(
        store,
        ReferenceRecord(
            id="ref_std",
            title="Standard Estimate",
            authors=["E. Analyst"],
            year=2023,
            source_type=ReferenceSourceType.standard_reference,
            origin="zbmath",
            bibliographic_source="zbmath",
            identifier="zb:2023.001",
            url="https://example.test/std",
            notes="Callable standard result.",
        ),
    )
    approve_reference(store, standard_reference.id, confirmed=True, rationale="standard reference is trusted")

    add_theorem(
        store,
        theorem_id="thm_blackbox",
        kind="theorem",
        name="Black Box Estimate",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
        grounded_reference_ids=[standard_reference.id],
        notes="Imported result used as a black box.",
    )
    cmd_theorem_ground("thm_blackbox", [standard_reference.id], root=tmp_path, notes="grounded black box theorem")

    add_theorem(
        store,
        theorem_id="thm_aux",
        kind="lemma",
        name="Auxiliary Lemma",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_aux2",
        kind="lemma",
        name="Propagation Lemma",
        statement="B implies C",
        assumptions=["B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_aux", "thm_blackbox"],
    )
    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="A implies C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_aux", "thm_aux2", "thm_blackbox"],
    )

    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A"])
    record_theorem_usage(store, "thm_blackbox")
    record_theorem_usage(store, "thm_aux")
    record_theorem_usage(store, "thm_aux2")

    add_obligation(
        store,
        ProofObligation(
            id="obl_main",
            goal_statement="compressed reasoning hides a standard bridge step",
            required_for="thm_main",
            blocking_reason="omitted standard step",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_main",
            scope="thm_main",
            description="fragile blocker around the black-box handoff",
            failure_type="fragile_dependency",
            related_contracts=["thm_blackbox"],
        ),
    )
    record_memory(store, "working", "checking the black-box handoff", theorem_id="thm_main")
    record_memory(store, "semantic", "the black-box theorem is imported and grounded", theorem_id="thm_main", importance="high")
    record_memory(store, "episodic", "compressed reasoning hid a bridge step", theorem_id="thm_main", route_id="route_gap")
    record_memory(store, "procedural", "inspect bugs before reuse", theorem_id="thm_main")

    cmd_proof_reason("thm_main", root=tmp_path, notes="derive local obligations")
    cmd_theorem_ground("thm_main", [standard_reference.id], root=tmp_path, notes="grounded by standard estimate")

    return standard_reference.id, "thm_main"


def test_export_includes_grounded_imported_reasoning_and_repair_state(tmp_path: Path):
    standard_reference_id, theorem_id = _seed_real_project(tmp_path)

    cmd_publication_set(
        theorem_id,
        "paper_ready",
        root=tmp_path,
        title="Main Publication Claim",
        section_placement="Section 3",
        reason="paper-facing claim",
        release_status="approved",
    )
    cmd_publication_set(
        "thm_aux2",
        "supplement_ready",
        root=tmp_path,
        title="Supplement Publication Claim",
        section_placement="Supplement A",
        reason="technical detail retained for supplement",
    )
    cmd_publication_set(
        "thm_blackbox",
        "internal_draft",
        root=tmp_path,
        title="Internal Publication Claim",
        reason="keep internal only",
        internal_only=True,
    )

    scan_payload = json.loads(cmd_proof_bug_scan(theorem_id, root=tmp_path))
    bug_ids = {report["bug_type"]: report["id"] for report in scan_payload["reports"]}
    assumption_bug_id = bug_ids["assumption_mismatch"]

    debug_payload = cmd_proof_debug_generate(theorem_id, root=tmp_path)
    assert assumption_bug_id in debug_payload

    review_payload = cmd_proof_review_suspicion(assumption_bug_id, "confirmed", root=tmp_path, rationale="confirmed by reviewer")
    assert '"bug_status": "confirmed"' in review_payload

    repair_payload = cmd_proof_repair_mark(assumption_bug_id, "repaired", root=tmp_path, note="fixed by making the assumption explicit")
    assert '"bug_status": "repaired"' in repair_payload

    evidence_payload = cmd_proof_evidence_show(assumption_bug_id, root=tmp_path)
    assert '"review_recommendation": "accept"' in evidence_payload

    store = ensure_project(tmp_path)
    project_id = load_state(store).project_id
    bridge_step = FormalBridgeProofStep(
        id="step_bridge",
        statement="standard bridge step from A and B to C",
        theorem_id=theorem_id,
        goal_id="goal_bridge",
        assumptions=["A", "B"],
        dependencies=["thm_aux"],
        side_conditions=["domain is inhabited"],
        fragile=True,
        notes="fragile theorem application escalated for machine checking",
        route_id="route_bridge",
    )
    translation = translate_proof_step(bridge_step, project_id=project_id, route_id="route_bridge", backend_target="lean4")
    assert translation.ok is True
    fragment = translation.fragment
    assert fragment is not None
    machine_checked_fragment = fragment.record_machine_check(result_id="vchk_bridge", backend_target="lean4")
    accepted_result = VerificationResult(
        fragment_id=machine_checked_fragment.id,
        backend="lean4",
        summary="machine check completed for the bridge step",
        review_status=VerificationReviewStatus.accepted_after_review,
        notes="accepted after review",
    )
    result_record = record_verification_result(
        store,
        machine_checked_fragment,
        accepted_result,
        theorem_id=theorem_id,
        obligation_id="obl_main",
        blocker_id="blk_main",
        proof_step_id=bridge_step.id,
        route_id="route_bridge",
        notes="accepted after review",
    )
    record_verification_lifecycle(
        store,
        machine_checked_fragment,
        result=accepted_result,
        result_record=result_record,
        notes="machine-checked bridge step",
    )
    stale_fragment = machine_checked_fragment.mark_stale_after_change(reason="dependency changed after acceptance")
    record_verification_staleness(
        store,
        stale_fragment,
        result=accepted_result,
        result_record=result_record,
        notes="dependency changed after acceptance",
    )

    create_snapshot(ensure_project(tmp_path), note="handoff after reasoning")

    export_one = cmd_export(root=tmp_path)
    reopened_store = ensure_project(tmp_path)
    export_two = cmd_export(root=tmp_path)
    publication_paper = cmd_publication_export(root=tmp_path, format="paper")
    publication_supplement = cmd_publication_export(root=tmp_path, format="supplement")
    publication_bundle = json.loads(cmd_publication_export(root=tmp_path, format="bundle"))

    assert export_one == export_two
    assert "Proof Export" in export_one
    assert "Goals: thm_main" in export_one
    assert "Assumed: A" in export_one
    assert "Open obligations:" in export_one
    assert "Proved: thm_blackbox, thm_aux, thm_aux2" in export_one
    assert "Standard Estimate" in export_one
    assert "Grounded theorems:" in export_one
    assert "thm_blackbox: Black Box Estimate <- ref_std" in export_one
    assert "thm_main: Main Result <- ref_std" in export_one
    assert "Reasoning:" in export_one
    assert "Bug reports:" in export_one
    assert "assumption_mismatch" in export_one
    assert "omitted_side_condition" in export_one
    assert "Verification support:" in export_one
    assert "Heuristic recommendations:" in export_one
    assert "Machine-checked results:" in export_one
    assert "Accepted verification results:" in export_one
    assert "Rejected verification results:" in export_one
    assert "Stale verification fragments:" in export_one
    assert "Collaboration:" in export_one
    assert "Contributors:" in export_one
    assert "Review records:" in export_one
    assert "Failed verification fragments:" in export_one
    assert "step_bridge" in export_one
    assert "accepted_after_review" in export_one
    assert "stale_after_change" in export_one
    assert "Evidence chains:" in export_one
    assert "recommendation=accept" in export_one
    assert "Debug tasks:" in export_one
    assert "Repair state:" in export_one
    assert "status=repaired" in export_one
    assert "Memory layers: working=1, semantic=1, episodic=1, procedural=1, handoffs=1" in export_one
    assert standard_reference_id in export_one
    assert "Main Publication Claim" in publication_paper
    assert "Internal Publication Claim" not in publication_paper
    assert "Supplement Publication Claim" in publication_supplement
    assert publication_bundle["publication_state"]["states"]
    assert publication_bundle["bundle_snapshots"]

    stateful_references = {reference.id for reference in list_references(reopened_store)}
    assert standard_reference_id in stateful_references

    assert [theorem.id for theorem in list_theorems(reopened_store)] == ["thm_aux", "thm_aux2", "thm_blackbox", "thm_main"]

    memory = load_memory(reopened_store)
    assert memory.handoff_snapshots[-1].handoff_note == "handoff after reasoning"
    assert memory.working[0].content == "checking the black-box handoff"

    assert read_latest_snapshot(reopened_store) is not None


def test_export_summarizes_phase_five_governance_across_related_projects(tmp_path: Path):
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    gamma = tmp_path / "gamma"
    ensure_project(alpha)
    ensure_project(beta)
    ensure_project(gamma)

    shared_asset = ReusableAsset(
        id="asset_shared_uniformity",
        kind=ReusableAssetKind.proof_pattern,
        name="Uniformity-before-summation pattern",
        summary="Reusable proof-development pattern",
        payload=ReusableAssetPayload(pattern_steps=["inspect uniformity", "separate the sum", "close the route"]),
        provenance=ReusableAssetProvenance(
            origin_project_id="proj_alpha",
            source_contract_ids=["thm_uniformity"],
            source_reference_ids=["ref_uniformity"],
            notes="approved for cross-project reuse",
        ),
        reuse_status=ReusableAssetReuseStatus.approved_reusable,
        trust_level=ReusableAssetTrustLevel.reviewed_reusable,
        reviewed_by="lead",
        review_notes="approved for cross-project reuse",
    )
    local_asset = ReusableAsset(
        id="asset_local_uniformity",
        kind=ReusableAssetKind.proof_pattern,
        name="Local uniformity route",
        summary="Project-local proof-development pattern",
        payload=ReusableAssetPayload(pattern_steps=["inspect local context", "reuse known lemma"]),
        provenance=ReusableAssetProvenance(origin_project_id="proj_alpha", notes="local route"),
        reuse_status=ReusableAssetReuseStatus.project_local,
        trust_level=ReusableAssetTrustLevel.project_verified,
        reviewed_by="researcher",
        review_notes="local route",
    )
    prior_asset = ReusableAsset(
        id="asset_prior_boundary",
        kind=ReusableAssetKind.proof_pattern,
        name="Boundary repair route",
        summary="Prior project repair pattern",
        payload=ReusableAssetPayload(pattern_steps=["check the boundary case", "close the interior case"]),
        provenance=ReusableAssetProvenance(origin_project_id="proj_gamma", notes="prior route"),
        reuse_status=ReusableAssetReuseStatus.private_experimental,
        trust_level=ReusableAssetTrustLevel.temporary_admit,
        reviewed_by="researcher",
        review_notes="prior route",
    )
    pack = DomainPack(
        id="pack_spectral_analysis",
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
        ),
        compatibility=DomainPackCompatibility(
            required_project_tags=["spectral", "analysis"],
            required_asset_ids=["asset_shared_uniformity"],
            required_asset_kinds=["proof_pattern"],
            required_notation_profile="spectral_default",
            allowed_pack_versions=["0.1.0"],
        ),
        review_status=DomainPackReviewStatus.approved,
        trust_level=DomainPackTrustLevel.reviewed_reusable,
        reviewed_by="reviewer",
        review_notes="approved for cross-project installation",
        origin_project_id="proj_alpha",
        source_asset_ids=["asset_shared_uniformity"],
    )

    cmd_proof_asset_publish(shared_asset.model_dump_json(), root=alpha, review_action="approve", reviewer="lead", notes="publish shared asset")
    cmd_proof_asset_publish(local_asset.model_dump_json(), root=alpha, review_action="publish", reviewer="researcher", notes="publish local asset")
    cmd_proof_asset_publish(prior_asset.model_dump_json(), root=gamma, review_action="private", reviewer="researcher", notes="private experimental asset")
    cmd_proof_pack_install(
        pack.model_dump_json(),
        root=alpha,
        installed_by="reviewer",
        project_tags=["spectral", "analysis"],
        available_asset_ids=["asset_shared_uniformity", "asset_local_uniformity"],
        available_asset_kinds=["proof_pattern"],
        notation_profile="spectral_default",
        notes="alpha install",
    )
    cmd_proof_pack_install(
        pack.model_dump_json(),
        root=beta,
        installed_by="reviewer",
        project_tags=["spectral", "analysis", "functional"],
        available_asset_ids=["asset_shared_uniformity"],
        available_asset_kinds=["proof_pattern"],
        notation_profile="spectral_default",
        notes="beta install",
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
    cmd_proof_policy_set(policy_profile.model_dump_json(), root=alpha, reviewer="lead", notes="alpha policy")
    recommendation_payload = cmd_proof_recommend(
        root=alpha,
        query="uniformity before summation",
        current_project_id="proj_alpha",
        current_project_assets_json=[local_asset.model_dump_json()],
        shared_assets_json=[shared_asset.model_dump_json()],
        prior_project_assets_json=[prior_asset.model_dump_json()],
        domain_packs_json=[pack.model_dump_json()],
        prior_usefulness_json=json.dumps(
            {
                shared_asset.id: 0.95,
                prior_asset.id: 0.35,
                pack.id: 0.82,
            }
        ),
        limit=5,
    )
    assert "asset_shared_uniformity" in recommendation_payload

    record_reuse_outcome(ensure_project(alpha), asset_id=shared_asset.id, used_in_project="proj_beta", outcome="helpful", notes="reduced duplicate search", reviewed_by_human=True)
    reuse_payload = cmd_proof_reuse_show(root=alpha, asset_id=shared_asset.id)
    assert "helpful" in reuse_payload

    plan_payload = cmd_proof_automate_plan(
        root=alpha,
        scope="theorem_7",
        task_type=AutomationTaskType.theorem_application_checks.value,
        action_json=[
            json.dumps({"action_type": "inspect_state", "description": "inspect local theorem state", "risk_level": "low", "reversible": True}),
            json.dumps({"action_type": "publish_reusable_outcome", "description": "publish reusable proof outcome", "risk_level": "trust_sensitive", "reversible": False}),
        ],
        policy_json=policy_profile.model_dump_json(),
        execution_mode=AutomationExecutionMode.supervised.value,
        notes="bounded automation for the alpha project",
    )
    plan_record = json.loads(plan_payload)
    run_id = plan_record["run"]["id"]
    run_payload = cmd_proof_automate_run(run_id, root=alpha, notes="run the planned sequence")
    run_record = json.loads(run_payload)
    assert run_record["run"]["planned_actions"][0]["status"] == "completed"
    assert run_record["run"]["planned_actions"][1]["status"] == "rejected"
    assert "action_completed" in cmd_proof_automate_trace(run_id, root=alpha)

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
        root=alpha,
        benchmark_name="phase5-compounding",
        scenario_id="scenario_uniformity",
        record_json=[assisted_record.model_dump_json(), baseline_record.model_dump_json()],
        notes="multi-project benchmark replay",
    )
    assert "assisted_better" in benchmark_payload

    export = cmd_export(root=alpha)
    assert "Reusable assets:" in export
    assert "asset_shared_uniformity" in export
    assert "Domain packs:" in export
    assert "Policy profiles:" in export
    assert "Automation runs:" in export
    assert "Automation traces:" in export
    assert "Recommendations:" in export
    assert "Reuse outcomes:" in export
    assert "Benchmarks:" in export
    assert "phase5-compounding" in export
