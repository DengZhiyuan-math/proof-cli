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


def _seed_radial_cluster(tmp_path: Path):
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_radial_main",
        kind="theorem",
        name="Radial Main Result",
        statement="The higher-rank radial section closes once the Jacquet bridge and scalar lift align.",
        assumptions=["Jacquet bridge", "scalar-to-vector lift"],
        exports=["radial conclusion"],
        status=TheoremStatus.blocked,
        trust_level=TrustLevel.temporary_admit,
        dependencies=["lem_radial_bridge", "lem_vector_support", "thm_jacquet_gap", "thm_scalar_lift"],
    )
    add_theorem(
        store,
        theorem_id="thm_jacquet_gap",
        kind="theorem",
        name="Jacquet Compression Gap",
        statement="The compression step needs an explicit bridge before the main theorem can finish.",
        assumptions=["Jacquet compression"],
        exports=["explicit compression bridge"],
        status=TheoremStatus.blocked,
        trust_level=TrustLevel.temporary_admit,
        dependencies=["lem_radial_bridge"],
    )
    add_theorem(
        store,
        theorem_id="thm_scalar_lift",
        kind="theorem",
        name="Scalar Lift Step",
        statement="The scalar-to-vector lift needs the support lemma to stay stable.",
        assumptions=["scalar lift", "vector support"],
        exports=["vectorized lift"],
        status=TheoremStatus.blocked,
        trust_level=TrustLevel.temporary_admit,
        dependencies=["lem_vector_support"],
    )
    add_theorem(
        store,
        theorem_id="lem_radial_bridge",
        kind="lemma",
        name="Radial Bridge Lemma",
        statement="A local bridge reduces the compression gap to a named step.",
        assumptions=["radial consistency"],
        exports=["bridge step"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="lem_vector_support",
        kind="lemma",
        name="Vector Support Lemma",
        statement="A support lemma controls the scalar-to-vector lift.",
        assumptions=["vector stability"],
        exports=["support estimate"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )

    set_current_theorem(store, "thm_radial_main")
    set_current_context(store, ["Jacquet", "compression", "scalar", "vector", "bridge"])

    add_obligation(
        store,
        ProofObligation(
            id="obl_jacquet_gap",
            goal_statement="close the Jacquet compression gap",
            required_for="thm_radial_main",
            blocking_reason="the compression bridge is still implicit",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_scalar_lift",
            scope="thm_radial_main",
            description="scalar-to-vector lift stalls without the bridge",
            failure_type="missing_bridge",
            related_contracts=["thm_scalar_lift"],
        ),
    )
    record_failed_route(
        store,
        "try the scalar lift before closing the Jacquet bridge",
        target_kind="obligation",
        target_id="obl_jacquet_gap",
        notes="the lift becomes brittle until the compression gap is named",
    )
    record_memory(
        store,
        "working",
        "the radial section is easier once the proof is split by bridge and lift",
        theorem_id="thm_radial_main",
    )
    record_memory(
        store,
        "semantic",
        "the Jacquet bridge looks like the first explicit gap",
        theorem_id="thm_radial_main",
        importance="high",
    )
    record_memory(
        store,
        "episodic",
        "the scalar lift stalled until the bridge was isolated",
        theorem_id="thm_radial_main",
        route_id="route_scalar_lift",
    )
    record_memory(
        store,
        "procedural",
        "organize the section by proof logic and complexity",
        theorem_id="thm_radial_main",
    )

    return store


def test_radial_cluster_validation_slice_is_structure_first(tmp_path: Path):
    store = _seed_radial_cluster(tmp_path)

    report = retrieve_candidates(store, query="Jacquet compression scalar vector bridge")
    assert report.candidates[0].id == "thm_radial_main"
    assert report.project_context.current_theorem == "thm_radial_main"
    assert "theorem:thm_radial_main" in report.project_context.explicit_neighborhood
    assert "obligation:obl_jacquet_gap" in report.project_context.explicit_neighborhood
    assert "blocker:blk_scalar_lift" in report.project_context.explicit_neighborhood

    retrieve_json = json.loads(cmd_proof_retrieve("Jacquet compression scalar vector bridge", tmp_path, limit=5))
    assert retrieve_json["project_context"]["current_theorem"] == "thm_radial_main"
    assert "theorem:thm_radial_main" in retrieve_json["project_context"]["explicit_neighborhood"]
    assert "obligation:obl_jacquet_gap" in retrieve_json["project_context"]["explicit_neighborhood"]
    assert "blocker:blk_scalar_lift" in retrieve_json["project_context"]["explicit_neighborhood"]

    analyze_json = json.loads(cmd_project_analyze(tmp_path, limit=5))
    assert analyze_json["current_theorem"] == "thm_radial_main"
    assert analyze_json["bottleneck_kind"] in {"blocker", "obligation"}
    assert "obl_jacquet_gap" in analyze_json["bottleneck_summary"] or "blk_scalar_lift" in analyze_json["bottleneck_summary"]
    assert analyze_json["promising_next_steps"]
    assert any("thm_radial_main" in step or "blk_scalar_lift" in step or "obl_jacquet_gap" in step for step in analyze_json["promising_next_steps"])


def test_radial_cluster_snapshot_and_exchange_round_trip_preserve_diagnostics(tmp_path: Path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    store = _seed_radial_cluster(source_root)

    snapshot = create_snapshot(store, note="handoff on the radial cluster")
    restored = restore_snapshot(store)
    assert snapshot.latest_diagnostic_report is not None
    assert snapshot.latest_diagnostic_report["current_theorem"] == "thm_radial_main"
    assert restored is not None
    assert restored.project_snapshot.active_theorem == "thm_radial_main"
    assert restored.project_snapshot.latest_diagnostic_report is not None
    assert restored.project_snapshot.latest_diagnostic_report["current_theorem"] == "thm_radial_main"
    assert restored.handoff_note == "handoff on the radial cluster"
    assert "obl_jacquet_gap" in restored.project_snapshot.open_obligations
    assert "blk_scalar_lift" in restored.project_snapshot.active_blockers

    bundle_json = cmd_exchange_export(source_root, note="handoff on the radial cluster")
    bundle_payload = json.loads(bundle_json)
    assert bundle_payload["latest_snapshot"]["latest_diagnostic_report"] is not None
    assert bundle_payload["handoff_snapshot"]["latest_diagnostic_report"] is not None

    import_report = json.loads(cmd_exchange_import(bundle_json, root=target_root))
    assert "latest_snapshot" in import_report["imported_sections"]
    assert "handoff_snapshot" in import_report["imported_sections"]

    round_tripped = json.loads(cmd_exchange_export(target_root, note="after import"))
    assert round_tripped["latest_snapshot"]["latest_diagnostic_report"] is not None
    assert round_tripped["handoff_snapshot"]["latest_diagnostic_report"] is not None
    assert round_tripped["project_state"]["current_theorem"] == "thm_radial_main"


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
            "Jacquet bridge",
            "--assumption",
            "scalar lift",
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
