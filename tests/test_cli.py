import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.blockers import add_blocker
from proof_cli.commands import cmd_theorem_ground
from proof_cli.cli import app
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.memory import list_memory_artifacts, record_memory
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import record_theorem_usage, set_current_context, set_current_theorem
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import approve_reference, defer_reference, ensure_project, import_reference
from proof_cli.theorems import add_theorem


runner = CliRunner()


def _seed_phase_two_project(tmp_path: Path) -> tuple[str, str, str]:
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="A implies C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_aux",
        kind="lemma",
        name="Auxiliary Lemma",
        statement="A and B imply C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A", "B"])

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

    paper_reference = import_reference(
        store,
        ReferenceRecord(
            id="ref_paper",
            title="Paper Lemma",
            authors=["R. Researcher"],
            year=2021,
            source_type=ReferenceSourceType.research_paper,
            origin="arxiv",
            bibliographic_source="arxiv",
            identifier="arXiv:2101.00001",
            url="https://example.test/paper",
            notes="Needs manual review before reuse.",
        ),
    )
    defer_reference(store, paper_reference.id, confirmed=True, rationale="assumptions still need checking")

    add_obligation(
        store,
        ProofObligation(
            id="obl_main",
            goal_statement="bridge A to C",
            required_for="thm_main",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_main",
            scope="thm_main",
            description="paper route needs grounding",
            failure_type="assumption_mismatch",
        ),
    )

    record_memory(store, "working", "searching for the bridge lemma", theorem_id="thm_main")
    record_memory(
        store,
        "semantic",
        "standard estimate is callable in context",
        theorem_id="thm_main",
        importance="high",
    )
    record_memory(store, "episodic", "paper route failed assumption match", theorem_id="thm_main", route_id="route_paper")
    record_memory(store, "procedural", "review imported results before reuse", theorem_id="thm_main")

    semantic_memory = next(
        artifact for artifact in list_memory_artifacts(store) if artifact.content == "standard estimate is callable in context"
    )
    return standard_reference.id, paper_reference.id, semantic_memory.id


def _seed_phase_three_project(tmp_path: Path) -> str:
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
        theorem_id="thm_lemma_a",
        kind="lemma",
        name="Bridge Lemma",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_lemma_b",
        kind="lemma",
        name="Propagation Lemma",
        statement="B implies C",
        assumptions=["B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_lemma_a", "thm_blackbox"],
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
        dependencies=["thm_lemma_a", "thm_lemma_b", "thm_blackbox"],
    )

    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A"])
    record_theorem_usage(store, "thm_blackbox")
    record_theorem_usage(store, "thm_lemma_a")
    record_theorem_usage(store, "thm_lemma_b")

    add_obligation(
        store,
        ProofObligation(
            id="obl_gap",
            goal_statement="compressed reasoning hides a standard bridge step",
            required_for="thm_main",
            blocking_reason="omitted standard step",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_fragile",
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
    return standard_reference.id


def _seed_phase_four_project(tmp_path: Path) -> tuple[str, str]:
    store = ensure_project(tmp_path)

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
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="A and B imply C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        dependencies=["thm_aux"],
        notes="fragile theorem application with explicit side condition",
    )
    add_theorem(
        store,
        theorem_id="thm_reject",
        kind="theorem",
        name="Rejected Result",
        statement="B implies D",
        assumptions=["B"],
        exports=["D"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_obligation(
        store,
        ProofObligation(
            id="obl_main",
            goal_statement="standard bridge step requires an explicit side condition",
            required_for="thm_main",
            blocking_reason="standard bridge step",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_main",
            scope="thm_main",
            description="bridge step is fragile until machine-checked",
            failure_type="missing_verification",
        ),
    )
    set_current_theorem(store, "thm_main")
    set_current_context(store, ["A", "B"])
    return "thm_main", "thm_reject"


def test_help_lists_phase_two_commands(tmp_path: Path):
    _seed_phase_two_project(tmp_path)

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "reference" in result.stdout
    assert "memory" in result.stdout
    assert "provenance" in result.stdout
    assert "search" in result.stdout
    assert "theorem" in result.stdout


def test_phase_two_cli_paths_are_reachable_and_readable(tmp_path: Path):
    reference_id, paper_reference_id, memory_id = _seed_phase_two_project(tmp_path)

    result = runner.invoke(app, ["search", "Auxiliary Lemma", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "query: Auxiliary Lemma" in result.stdout
    assert "sources:" in result.stdout
    assert "thm_aux" in result.stdout

    result = runner.invoke(app, ["reference", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "References:" in result.stdout
    assert "Standard Estimate" in result.stdout
    assert "Paper Lemma" in result.stdout

    result = runner.invoke(app, ["reference", "show", reference_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"title": "Standard Estimate"' in result.stdout
    assert '"review_status": "approved"' in result.stdout

    result = runner.invoke(
        app,
        [
            "reference",
            "review",
            paper_reference_id,
            "defer",
            "--root",
            str(tmp_path),
            "--rationale",
            "still needs checking",
        ],
    )
    assert result.exit_code == 0
    assert f"review:{paper_reference_id}:deferred" in result.stdout

    result = runner.invoke(app, ["theorem", "extract", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"callable": true' in result.stdout

    result = runner.invoke(
        app,
        ["theorem", "ground", "thm_main", "--reference-id", reference_id, "--root", str(tmp_path), "--notes", "grounded by standard estimate"],
    )
    assert result.exit_code == 0
    assert f"ground:thm_main:{reference_id}" in result.stdout

    result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Memory:" in result.stdout
    assert "standard estimate is callable in context" in result.stdout

    result = runner.invoke(app, ["memory", "show", memory_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"layer": "semantic"' in result.stdout

    result = runner.invoke(app, ["provenance", "show", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"kind": "theorem"' in result.stdout
    assert '"callable": true' in result.stdout


def test_phase_three_cli_paths_cover_reasoning_bug_review_and_repair(tmp_path: Path):
    _seed_phase_three_project(tmp_path)

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for expected in ["reason", "bug", "debug", "review", "repair", "trace", "evidence", "explain", "obligation"]:
        assert expected in result.stdout

    result = runner.invoke(app, ["reason", "thm_main", "--root", str(tmp_path), "--notes", "derive local obligations"])
    assert result.exit_code == 0
    assert "adequacy_check" in result.stdout
    assert "derived_obligations" in result.stdout

    result = runner.invoke(app, ["obligation", "derive", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "reasoning_path" in result.stdout

    scan_result = runner.invoke(app, ["bug", "scan", "thm_main", "--root", str(tmp_path)])
    assert scan_result.exit_code == 0
    scan_payload = json.loads(scan_result.stdout)
    bug_reports = scan_payload["reports"]
    assert len(bug_reports) >= 2
    bug_ids = {report["bug_type"]: report["id"] for report in bug_reports}
    assert "assumption_mismatch" in bug_ids
    assert "omitted_side_condition" in bug_ids

    bug_id = bug_ids["assumption_mismatch"]

    result = runner.invoke(app, ["bug", "list", "--root", str(tmp_path), "--theorem-id", "thm_main"])
    assert result.exit_code == 0
    assert bug_id in result.stdout
    assert "suspected" in result.stdout

    result = runner.invoke(app, ["bug", "show", bug_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert bug_id in result.stdout
    assert '"review_state": "unreviewed"' in result.stdout

    result = runner.invoke(app, ["evidence", "show", bug_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"review_recommendation": "block"' in result.stdout
    assert '"reasoning_path"' in result.stdout

    result = runner.invoke(app, ["debug", "generate", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"task_type"' in result.stdout
    assert bug_id in result.stdout

    result = runner.invoke(app, ["debug", "list", "--root", str(tmp_path), "--theorem-id", "thm_main"])
    assert result.exit_code == 0
    assert "bug=" in result.stdout
    assert bug_id in result.stdout

    result = runner.invoke(app, ["review", "suspicion", bug_id, "--status", "confirmed", "--root", str(tmp_path), "--rationale", "confirmed by reviewer"])
    assert result.exit_code == 0
    assert '"bug_status": "confirmed"' in result.stdout

    result = runner.invoke(app, ["repair", "mark", bug_id, "--status", "repaired", "--root", str(tmp_path), "--note", "fixed by making the assumption explicit"])
    assert result.exit_code == 0
    assert '"bug_status": "repaired"' in result.stdout

    result = runner.invoke(app, ["bug", "list", "--root", str(tmp_path), "--theorem-id", "thm_main"])
    assert result.exit_code == 0
    assert "repaired" in result.stdout

    result = runner.invoke(app, ["trace", "dependency", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"dependency_ids": [' in result.stdout
    assert '"thm_blackbox"' in result.stdout

    result = runner.invoke(app, ["explain", "apply", "thm_main", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert '"callable": false' in result.stdout
    assert '"missing_assumptions": [' in result.stdout


def test_phase_four_cli_paths_cover_formal_bridge_workflows(tmp_path: Path):
    theorem_id, reject_id = _seed_phase_four_project(tmp_path)

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "formalize" in result.stdout
    assert "verify" in result.stdout
    assert "revalidate" in result.stdout

    result = runner.invoke(
        app,
        [
            "formalize",
            "recommend",
            theorem_id,
            "--root",
            str(tmp_path),
            "--backend-target",
            "lean4",
            "--notes",
            "fragile bridge",
        ],
    )
    assert result.exit_code == 0
    assert f"formalize recommend {theorem_id}" in result.stdout
    assert "Fragment:" in result.stdout
    assert "Recommendation:" in result.stdout
    assert '"source_id": "thm_main"' in result.stdout

    result = runner.invoke(
        app,
        [
            "verify",
            "queue",
            theorem_id,
            "--root",
            str(tmp_path),
            "--backend-target",
            "lean4",
            "--route-id",
            "route_bridge",
            "--notes",
            "queued for machine checking",
        ],
    )
    assert result.exit_code == 0
    assert f"verify queue {theorem_id}" in result.stdout
    assert "Fragment:" in result.stdout
    assert "queued_for_verification" in result.stdout

    result = runner.invoke(
        app,
        [
            "verify",
            "run",
            theorem_id,
            "--root",
            str(tmp_path),
            "--backend-target",
            "lean4",
            "--notes",
            "run after queue",
        ],
    )
    assert result.exit_code == 0
    assert "Result:" in result.stdout
    assert "machine_checked" in result.stdout

    result = runner.invoke(app, ["verify", "accept", theorem_id, "--root", str(tmp_path), "--notes", "accepted after review"])
    assert result.exit_code == 0
    assert "accepted_after_review" in result.stdout
    assert "Verification record:" in result.stdout

    result = runner.invoke(app, ["verify", "status", theorem_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Additional results:" in result.stdout
    assert "accepted_after_review" in result.stdout

    result = runner.invoke(app, ["verify", "result", theorem_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "accepted_after_review" in result.stdout

    result = runner.invoke(app, ["trace", "machine-check", theorem_id, "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Trace: machine-check-trace" in result.stdout
    assert "verification://" in result.stdout

    result = runner.invoke(
        app,
        [
            "verify",
            "stale",
            theorem_id,
            "--root",
            str(tmp_path),
            "--reason",
            "dependency changed",
            "--dependency",
            "thm_aux",
        ],
    )
    assert result.exit_code == 0
    assert "Stale fragment:" in result.stdout
    assert "stale_after_change" in result.stdout

    result = runner.invoke(
        app,
        [
            "revalidate",
            theorem_id,
            "--root",
            str(tmp_path),
            "--backend-target",
            "lean4",
            "--notes",
            "recheck after dependency change",
        ],
    )
    assert result.exit_code == 0
    assert "Revalidated fragment:" in result.stdout
    assert "queued_for_verification" in result.stdout

    result = runner.invoke(
        app,
        [
            "verify",
            "queue",
            reject_id,
            "--root",
            str(tmp_path),
            "--backend-target",
            "lean4",
            "--notes",
            "queued for review",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "verify",
            "run",
            reject_id,
            "--root",
            str(tmp_path),
            "--backend-target",
            "lean4",
            "--notes",
            "run for reject path",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["verify", "reject", reject_id, "--root", str(tmp_path), "--notes", "needs more work"])
    assert result.exit_code == 0
    assert "rejected_by_human" in result.stdout


def test_phase_five_cli_surface_routes_to_governance_workflows(tmp_path: Path) -> None:
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "asset" in help_result.stdout
    assert "pack" in help_result.stdout
    assert "policy" in help_result.stdout
    assert "recommend" in help_result.stdout
    assert "reuse" in help_result.stdout
    assert "automate" in help_result.stdout
    assert "benchmark" in help_result.stdout

    asset_result = runner.invoke(app, ["asset", "list", "--root", str(tmp_path)])
    assert asset_result.exit_code == 0
    assert "No reusable assets" in asset_result.stdout

    policy_result = runner.invoke(app, ["policy", "list", "--root", str(tmp_path)])
    assert policy_result.exit_code == 0
    assert "bounded_local_reasoning" in policy_result.stdout or "project_id" in policy_result.stdout

    recommend_result = runner.invoke(app, ["recommend", "--root", str(tmp_path)])
    assert recommend_result.exit_code == 0
    assert "query" in recommend_result.stdout

    benchmark_result = runner.invoke(app, ["benchmark", "run", "--root", str(tmp_path), "--scenario-id", "smoke"])
    assert benchmark_result.exit_code == 0
    assert "smoke" in benchmark_result.stdout
