import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.blockers import add_blocker
from proof_cli.commands import cmd_proof_formalize_recommend, cmd_theorem_ground
from proof_cli.cli import app
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.memory import list_memory_artifacts, record_memory
from proof_cli.obligations import add_obligation, list_obligations
from proof_cli.proof_state import load_state, record_theorem_usage, set_current_context, set_current_theorem
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
    assert "retrieve" in result.stdout
    assert "theorem" in result.stdout
    assert "project" in result.stdout


def test_phase_two_cli_paths_are_reachable_and_readable(tmp_path: Path):
    reference_id, paper_reference_id, memory_id = _seed_phase_two_project(tmp_path)

    result = runner.invoke(app, ["search", "Auxiliary Lemma", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "query: Auxiliary Lemma" in result.stdout
    assert "sources:" in result.stdout
    assert "thm_aux" in result.stdout

    result = runner.invoke(app, ["retrieve", "Auxiliary Lemma", "--root", str(tmp_path)])
    assert result.exit_code == 0
    retrieve_payload = json.loads(result.stdout)
    assert retrieve_payload["project_context"]["current_theorem"] == "thm_main"
    assert "explicit_neighborhood" in retrieve_payload["project_context"]
    assert retrieve_payload["candidates"][0]["structural_score"] >= retrieve_payload["candidates"][0]["lexical_score"]

    result = runner.invoke(app, ["project", "analyze", "--root", str(tmp_path)])
    assert result.exit_code == 0
    project_payload = json.loads(result.stdout)
    assert project_payload["current_theorem"] == "thm_main"
    assert project_payload["bottleneck_kind"] in {"blocker", "obligation"}
    assert project_payload["promising_next_steps"]

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


def test_cli_exposes_publication_workflows(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    theorem_id = "thm_pub"
    add_theorem(
        store,
        theorem_id=theorem_id,
        kind="theorem",
        name="Publication Bridge",
        statement="A implies B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    cmd_proof_formalize_recommend(theorem_id, root=tmp_path, backend_target="lean4")

    result = runner.invoke(app, ["publication", "--help"])
    assert result.exit_code == 0
    assert "publication" in result.stdout.lower()
    assert "view" in result.stdout.lower()
    assert "export" in result.stdout.lower()


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


def test_phase_six_cli_surface_routes_to_collaboration_workflows(tmp_path: Path) -> None:
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "contributor" in help_result.stdout
    assert "role" in help_result.stdout
    assert "comment" in help_result.stdout
    assert "branch" in help_result.stdout
    assert "exchange" in help_result.stdout
    assert "handoff" in help_result.stdout

    contributor_result = runner.invoke(app, ["contributor", "list", "--root", str(tmp_path)])
    assert contributor_result.exit_code == 0
    assert "No contributors" in contributor_result.stdout or "human" in contributor_result.stdout

    review_result = runner.invoke(app, ["review", "list", "--root", str(tmp_path)])
    assert review_result.exit_code == 0
    assert "No review records" in review_result.stdout or "review" in review_result.stdout.lower()

    comment_result = runner.invoke(app, ["comment", "list", "--root", str(tmp_path)])
    assert comment_result.exit_code == 0
    assert "No comments" in comment_result.stdout or "Comment threads" in comment_result.stdout

    branch_result = runner.invoke(app, ["branch", "list", "--root", str(tmp_path)])
    assert branch_result.exit_code == 0
    assert "No branches" in branch_result.stdout or "branch" in branch_result.stdout.lower()

    exchange_result = runner.invoke(app, ["exchange", "export", "--root", str(tmp_path)])
    assert exchange_result.exit_code == 0
    assert "\"project_id\"" in exchange_result.stdout


def test_codex_surface_shows_guided_catalog_and_discovers_workspace_root(tmp_path: Path, monkeypatch) -> None:
    ensure_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["codex"])

    assert result.exit_code == 0
    assert "Proof Codex Surface" in result.stdout
    assert f"Selected root: {tmp_path}" in result.stdout
    assert "Readiness:" in result.stdout
    assert "proof codex status" in result.stdout
    assert "proof codex snapshot" in result.stdout
    assert "proof codex doctor" in result.stdout
    assert "proof codex obligation resolve" in result.stdout


def test_codex_surface_routes_real_read_only_commands(tmp_path: Path) -> None:
    _seed_phase_two_project(tmp_path)

    status_result = runner.invoke(app, ["codex", "status", "--root", str(tmp_path)])
    assert status_result.exit_code == 0
    assert "Current theorem" in status_result.stdout
    assert "thm_main" in status_result.stdout

    theorem_result = runner.invoke(app, ["codex", "theorem", "list", "--root", str(tmp_path)])
    assert theorem_result.exit_code == 0
    assert "Main Result" in theorem_result.stdout
    assert "Auxiliary Lemma" in theorem_result.stdout

    obligation_result = runner.invoke(app, ["codex", "obligation", "list", "--root", str(tmp_path)])
    assert obligation_result.exit_code == 0
    assert "bridge A to C" in obligation_result.stdout

    blocker_result = runner.invoke(app, ["codex", "blocker", "list", "--root", str(tmp_path)])
    assert blocker_result.exit_code == 0
    assert "paper route needs grounding" in blocker_result.stdout


def test_codex_surface_preserves_json_outputs_for_retrieval_and_analysis(tmp_path: Path) -> None:
    _seed_phase_two_project(tmp_path)

    retrieve_result = runner.invoke(app, ["codex", "retrieve", "bridge lemma", "--root", str(tmp_path)])
    assert retrieve_result.exit_code == 0
    retrieve_payload = json.loads(retrieve_result.stdout)
    assert retrieve_payload["query"] == "bridge lemma"
    assert retrieve_payload["project_context"]["current_theorem"] == "thm_main"

    analyze_result = runner.invoke(app, ["codex", "project", "analyze", "--root", str(tmp_path), "--query", "bridge"])
    assert analyze_result.exit_code == 0
    analyze_payload = json.loads(analyze_result.stdout)
    assert analyze_payload["query"] == "bridge"
    assert analyze_payload["current_theorem"] == "thm_main"


def test_codex_surface_exposes_guided_mutation_entry_points(tmp_path: Path) -> None:
    ensure_project(tmp_path)

    theorem_add_result = runner.invoke(app, ["codex", "theorem", "add", "--root", str(tmp_path)])
    assert theorem_add_result.exit_code == 0
    assert "Mutation: theorem add" in theorem_add_result.stdout
    assert "Missing details: theorem_id, name, statement" in theorem_add_result.stdout
    assert "proof codex theorem add" in theorem_add_result.stdout

    new_theorem_result = runner.invoke(app, ["codex", "new", "theorem", "--root", str(tmp_path)])
    assert new_theorem_result.exit_code == 0
    assert "Mutation: new theorem" in new_theorem_result.stdout
    assert f"Selected root: {tmp_path}" in new_theorem_result.stdout


def test_codex_surface_runs_mutations_through_wrapper(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)

    theorem_result = runner.invoke(
        app,
        [
            "codex",
            "theorem",
            "add",
            "thm_tiny",
            "Tiny theorem",
            "A implies B",
            "--root",
            str(tmp_path),
            "--assumption",
            "A",
            "--export",
            "B",
        ],
    )
    assert theorem_result.exit_code == 0
    assert "Persisted proof state: changed" in theorem_result.stdout
    theorem_payload = json.loads(theorem_result.stdout.split("Result:\n", 1)[1])
    assert theorem_payload["id"] == "thm_tiny"
    assert theorem_payload["assumptions"] == ["A"]

    obligation_result = runner.invoke(
        app,
        ["codex", "obligation", "add", "bridge the theorem", "--root", str(tmp_path), "--required-for", "thm_tiny"],
    )
    assert obligation_result.exit_code == 0
    obligation_payload = json.loads(obligation_result.stdout.split("Result:\n", 1)[1])
    assert obligation_payload["required_for"] == "thm_tiny"

    resolve_result = runner.invoke(
        app,
        [
            "codex",
            "obligation",
            "resolve",
            obligation_payload["id"],
            "--root",
            str(tmp_path),
            "--rationale",
            "proved explicitly",
        ],
    )
    assert resolve_result.exit_code == 0
    assert "Persisted proof state: changed" in resolve_result.stdout
    resolved_payload = json.loads(resolve_result.stdout.split("Result:\n", 1)[1])
    assert resolved_payload["status"] == "resolved"
    assert list_obligations(store)[-1].status.value == "resolved"
    assert obligation_payload["id"] not in load_state(store).open_obligations

    blocker_result = runner.invoke(
        app,
        ["codex", "blocker", "add", "stuck on normalization", "--root", str(tmp_path), "--scope", "thm_tiny", "--failure-type", "gap"],
    )
    assert blocker_result.exit_code == 0
    blocker_payload = json.loads(blocker_result.stdout.split("Result:\n", 1)[1])
    assert blocker_payload["scope"] == "thm_tiny"

    snapshot_result = runner.invoke(app, ["codex", "snapshot", "--root", str(tmp_path), "--note", "checkpoint"])
    assert snapshot_result.exit_code == 0
    snapshot_payload = json.loads(snapshot_result.stdout.split("Result:\n", 1)[1])
    assert snapshot_payload["handoff_note"] == "checkpoint"


def test_obligation_resolve_is_available_on_the_base_cli(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    add_obligation(
        store,
        ProofObligation(
            id="obl_base_resolve",
            goal_statement="bridge A to C",
            required_for="thm_tiny",
        ),
    )

    result = runner.invoke(
        app,
        ["obligation", "resolve", "obl_base_resolve", "--root", str(tmp_path), "--rationale", "proved explicitly"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "resolved"
    assert list_obligations(store)[0].status.value == "resolved"
    assert load_state(store).open_obligations == []


def test_codex_surface_honors_root_precedence_for_mutations(tmp_path: Path, monkeypatch) -> None:
    explicit_root = tmp_path / "explicit"
    env_root = tmp_path / "env"
    ensure_project(explicit_root)
    ensure_project(env_root)
    monkeypatch.setenv("PROOF_ROOT", str(env_root))

    result = runner.invoke(
        app,
        ["codex", "theorem", "add", "thm_explicit", "Explicit theorem", "A implies B", "--root", str(explicit_root)],
    )
    assert result.exit_code == 0
    assert f"Selected root: {explicit_root.resolve()}" in result.stdout
    assert "Root source: explicit --root" in result.stdout

    env_result = runner.invoke(app, ["codex", "theorem", "add", "thm_env", "Env theorem", "B implies C"])
    assert env_result.exit_code == 0
    assert f"Selected root: {env_root.resolve()}" in env_result.stdout
    assert "Root source: $PROOF_ROOT" in env_result.stdout


def test_codex_surface_guides_when_mutation_target_is_unsafe(tmp_path: Path, monkeypatch) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    monkeypatch.chdir(unsafe)
    monkeypatch.delenv("PROOF_ROOT", raising=False)

    result = runner.invoke(app, ["codex", "snapshot"])

    assert result.exit_code == 0
    assert "does not look like a Proof workspace" in result.stdout
    assert "Provide --root explicitly" in result.stdout


def test_codex_surface_reports_degraded_command_readiness(monkeypatch) -> None:
    monkeypatch.setattr("proof_cli.codex_router.shutil.which", lambda _: None)

    result = runner.invoke(app, ["codex", "doctor"])

    assert result.exit_code == 0
    assert "Status: degraded" in result.stdout
    assert "`proof` is not available on PATH." in result.stdout
    assert "`proof-codex` is not available on PATH." in result.stdout
    assert 'python -m pip install -e ".[dev]"' in result.stdout
    assert "global ~/.codex/skills/proof/ skill" in result.stdout


def test_codex_surface_reports_ready_command_readiness() -> None:
    result = runner.invoke(app, ["codex", "doctor"])

    assert result.exit_code == 0
    assert "Proof Codex Diagnostics" in result.stdout
    assert "Canonical skill: ~/.codex/skills/proof/SKILL.md" in result.stdout
    assert "Project-local skills: debugging and development helpers only" in result.stdout
