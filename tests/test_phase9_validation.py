import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.blockers import add_blocker, record_failed_route
from proof_cli.cli import app
from proof_cli.commands import cmd_exchange_export, cmd_exchange_import, cmd_project_analyze, cmd_proof_retrieve
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremStatus, TrustLevel
from proof_cli.memory import record_memory
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import set_current_context, set_current_theorem
from proof_cli.retrieval import retrieve_candidates
from proof_cli.snapshot import create_snapshot, restore_snapshot
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem

runner = CliRunner()


def _seed_alpha_cluster(tmp_path: Path):
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_alpha_main",
        kind="theorem",
        name="Alpha Main Result",
        statement="The sample alpha section closes once the Beta bridge and base extension align.",
        assumptions=["Beta bridge", "base-to-general extension"],
        exports=["alpha conclusion"],
        status=TheoremStatus.blocked,
        trust_level=TrustLevel.temporary_admit,
        dependencies=["lem_alpha_bridge", "lem_general_support", "thm_beta_gap", "thm_base_extension"],
    )
    add_theorem(
        store,
        theorem_id="thm_beta_gap",
        kind="theorem",
        name="Beta Reduction Gap",
        statement="The reduction step needs an explicit bridge before the main theorem can finish.",
        assumptions=["Beta reduction"],
        exports=["explicit reduction bridge"],
        status=TheoremStatus.blocked,
        trust_level=TrustLevel.temporary_admit,
        dependencies=["lem_alpha_bridge"],
    )
    add_theorem(
        store,
        theorem_id="thm_base_extension",
        kind="theorem",
        name="Base Extension Step",
        statement="The base-to-general extension needs the support lemma to stay stable.",
        assumptions=["base extension", "general support"],
        exports=["generalized extension"],
        status=TheoremStatus.blocked,
        trust_level=TrustLevel.temporary_admit,
        dependencies=["lem_general_support"],
    )
    add_theorem(
        store,
        theorem_id="lem_alpha_bridge",
        kind="lemma",
        name="Alpha Bridge Lemma",
        statement="A local bridge turns the reduction gap into a named step.",
        assumptions=["alpha consistency"],
        exports=["bridge step"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="lem_general_support",
        kind="lemma",
        name="General Support Lemma",
        statement="A support lemma controls the base-to-general extension.",
        assumptions=["general stability"],
        exports=["support estimate"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )

    set_current_theorem(store, "thm_alpha_main")
    set_current_context(store, ["Beta", "reduction", "base", "general", "bridge"])

    add_obligation(
        store,
        ProofObligation(
            id="obl_beta_gap",
            goal_statement="close the Beta reduction gap",
            required_for="thm_alpha_main",
            blocking_reason="the reduction bridge is still implicit",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_base_extension",
            scope="thm_alpha_main",
            description="base-to-general extension stalls without the bridge",
            failure_type="missing_bridge",
            related_contracts=["thm_base_extension"],
        ),
    )
    record_failed_route(
        store,
        "try the base extension before closing the Beta bridge",
        target_kind="obligation",
        target_id="obl_beta_gap",
        notes="the extension becomes brittle until the reduction gap is named",
    )
    record_memory(
        store,
        "working",
        "the alpha section is easier once the proof is split by bridge and extension",
        theorem_id="thm_alpha_main",
    )
    record_memory(
        store,
        "semantic",
        "the Beta bridge looks like the first explicit gap",
        theorem_id="thm_alpha_main",
        importance="high",
    )
    record_memory(
        store,
        "episodic",
        "the base extension stalled until the bridge was isolated",
        theorem_id="thm_alpha_main",
        route_id="route_base_extension",
    )
    record_memory(
        store,
        "procedural",
        "organize the section by proof logic and complexity",
        theorem_id="thm_alpha_main",
    )

    return store


def test_alpha_cluster_validation_slice_is_structure_first(tmp_path: Path):
    store = _seed_alpha_cluster(tmp_path)

    report = retrieve_candidates(store, query="Beta reduction base general bridge")
    assert report.candidates[0].id == "thm_alpha_main"
    assert report.project_context.current_theorem == "thm_alpha_main"
    assert "theorem:thm_alpha_main" in report.project_context.explicit_neighborhood
    assert "obligation:obl_beta_gap" in report.project_context.explicit_neighborhood
    assert "blocker:blk_base_extension" in report.project_context.explicit_neighborhood

    retrieve_json = json.loads(cmd_proof_retrieve("Beta reduction base general bridge", tmp_path, limit=5))
    assert retrieve_json["project_context"]["current_theorem"] == "thm_alpha_main"
    assert "theorem:thm_alpha_main" in retrieve_json["project_context"]["explicit_neighborhood"]
    assert "obligation:obl_beta_gap" in retrieve_json["project_context"]["explicit_neighborhood"]
    assert "blocker:blk_base_extension" in retrieve_json["project_context"]["explicit_neighborhood"]

    analyze_json = json.loads(cmd_project_analyze(tmp_path, limit=5))
    assert analyze_json["current_theorem"] == "thm_alpha_main"
    assert analyze_json["bottleneck_kind"] in {"blocker", "obligation"}
    assert "obl_beta_gap" in analyze_json["bottleneck_summary"] or "blk_base_extension" in analyze_json["bottleneck_summary"]
    assert analyze_json["promising_next_steps"]
    assert any("thm_alpha_main" in step or "blk_base_extension" in step or "obl_beta_gap" in step for step in analyze_json["promising_next_steps"])


def test_alpha_cluster_snapshot_and_exchange_round_trip_preserve_diagnostics(tmp_path: Path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    store = _seed_alpha_cluster(source_root)

    snapshot = create_snapshot(store, note="handoff on the alpha cluster")
    restored = restore_snapshot(store)
    assert snapshot.latest_diagnostic_report is not None
    assert snapshot.latest_diagnostic_report["current_theorem"] == "thm_alpha_main"
    assert restored is not None
    assert restored.project_snapshot.active_theorem == "thm_alpha_main"
    assert restored.project_snapshot.latest_diagnostic_report is not None
    assert restored.project_snapshot.latest_diagnostic_report["current_theorem"] == "thm_alpha_main"
    assert restored.handoff_note == "handoff on the alpha cluster"
    assert "obl_beta_gap" in restored.project_snapshot.open_obligations
    assert "blk_base_extension" in restored.project_snapshot.active_blockers

    bundle_json = cmd_exchange_export(source_root, note="handoff on the alpha cluster")
    bundle_payload = json.loads(bundle_json)
    assert bundle_payload["latest_snapshot"]["latest_diagnostic_report"] is not None
    assert bundle_payload["handoff_snapshot"]["latest_diagnostic_report"] is not None

    import_report = json.loads(cmd_exchange_import(bundle_json, root=target_root))
    assert "latest_snapshot" in import_report["imported_sections"]
    assert "handoff_snapshot" in import_report["imported_sections"]

    round_tripped = json.loads(cmd_exchange_export(target_root, note="after import"))
    assert round_tripped["latest_snapshot"]["latest_diagnostic_report"] is not None
    assert round_tripped["handoff_snapshot"]["latest_diagnostic_report"] is not None
    assert round_tripped["project_state"]["current_theorem"] == "thm_alpha_main"


def test_codex_e2e_workflow_on_radial_style_cluster(tmp_path: Path):
    root = tmp_path / "radial-codex"

    init_result = runner.invoke(app, ["codex", "init", "--root", str(root)])
    assert init_result.exit_code == 0
    assert "Initialization root:" in init_result.stdout
    assert "Persisted proof state: changed" in init_result.stdout
    assert "Initialized proof project" in init_result.stdout

    doctor = runner.invoke(app, ["codex", "doctor"])
    assert doctor.exit_code == 0
    assert "Proof Codex Diagnostics" in doctor.stdout
    assert "Canonical skill: ~/.codex/skills/proof/SKILL.md" in doctor.stdout

    initial_status = runner.invoke(app, ["codex", "status", "--root", str(root)])
    assert initial_status.exit_code == 0
    assert "Project" in initial_status.stdout

    theorem_result = runner.invoke(
        app,
        [
            "codex",
            "theorem",
            "add",
            "thm_radial_cluster",
            "Radial Cluster Main Step",
            "The local radial cluster closes once the Jacquet bridge and scalar lift are tracked explicitly.",
            "--root",
            str(root),
            "--assumption",
            'Beta bridge',
            "--assumption",
            'base extension',
            "--export",
            "radial closure",
            "--notes",
            "Codex validation theorem cluster",
        ],
    )
    assert theorem_result.exit_code == 0
    assert "Mutation: theorem add" in theorem_result.stdout
    assert "Persisted proof state: changed" in theorem_result.stdout
    theorem_payload = json.loads(theorem_result.stdout.split("Result:\n", 1)[1])
    assert theorem_payload["id"] == "thm_radial_cluster"
    assert theorem_payload["exports"] == ["radial closure"]

    obligation_result = runner.invoke(
        app,
        [
            "codex",
            "obligation",
            "add",
            "make the Jacquet bridge explicit before the scalar lift",
            "--root",
            str(root),
            "--required-for",
            "thm_radial_cluster",
        ],
    )
    assert obligation_result.exit_code == 0
    assert "Root source: explicit --root" in obligation_result.stdout
    obligation_payload = json.loads(obligation_result.stdout.split("Result:\n", 1)[1])
    assert obligation_payload["required_for"] == "thm_radial_cluster"

    blocker_result = runner.invoke(
        app,
        [
            "codex",
            "blocker",
            "add",
            "scalar-to-vector lift is ambiguous until the Jacquet bridge is named",
            "--root",
            str(root),
            "--scope",
            "thm_radial_cluster",
            "--failure-type",
            "missing_bridge",
        ],
    )
    assert blocker_result.exit_code == 0
    blocker_payload = json.loads(blocker_result.stdout.split("Result:\n", 1)[1])
    assert blocker_payload["scope"] == "thm_radial_cluster"

    retrieve_result = runner.invoke(app, ["codex", "retrieve", "Jacquet bridge scalar lift", "--root", str(root)])
    assert retrieve_result.exit_code == 0
    retrieve_payload = json.loads(retrieve_result.stdout)
    assert retrieve_payload["project_context"]["open_obligations"]
    assert retrieve_payload["project_context"]["blockers"]

    snapshot_result = runner.invoke(app, ["codex", "snapshot", "--root", str(root), "--note", "radial codex checkpoint"])
    assert snapshot_result.exit_code == 0
    assert "Mutation: snapshot" in snapshot_result.stdout
    snapshot_payload = json.loads(snapshot_result.stdout.split("Result:\n", 1)[1])
    assert snapshot_payload["handoff_note"] == "radial codex checkpoint"
    assert snapshot_payload["open_obligations"]
    assert snapshot_payload["active_blockers"]

    final_status = runner.invoke(app, ["codex", "status", "--root", str(root)])
    assert final_status.exit_code == 0
    assert "thm_radial_cluster" in final_status.stdout
