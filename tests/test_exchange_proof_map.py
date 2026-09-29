from _researcher import researcher
"""Issue #31: exchange carries the new ProofMapNode model, and none of its
reads/writes bypass the storage layer with direct SQL anymore. The merge
import itself is tested in test_exchange_merge_import.py.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.exchange import (
    bundle_from_json,
    bundle_to_json,
    export_exchange_bundle,
    import_exchange_bundle,
    inspect_exchange_bundle,
)
from proof_cli.proof_map import (
    claim_node,
    create_node,
    decide_acceptance,
    get_node,
    get_workflow_state,
    list_candidate_proofs,
    open_challenge,
)
from proof_cli.storage import ensure_project, get_active_claim, get_dependency_pin
from _proofs import submit_proof

runner = CliRunner()


def _build_source_project(root: Path) -> None:
    store = ensure_project(root)
    create_node(store, node_id="lem_1", kind="lemma", statement="A base lemma")
    claim_node(store, "lem_1", claimant_id="agent_a", session_id="sess_1")
    submit_proof(
        store, "lem_1", claimant_id="agent_a", session_id="sess_1",
        scoping_rationale="scoped correctly", content="proof text")
    researcher(store).decide_acceptance("lem_1", "accept")

    create_node(store, node_id="clm_1", kind="claim", statement="Depends on lem_1", dependencies=["lem_1"])
    claim_node(store, "clm_1", claimant_id="agent_c", session_id="sess_c")
    submit_proof(
        store, "clm_1", claimant_id="agent_c", session_id="sess_c",
        scoping_rationale="scoped correctly", content="proof text")
    claim_node(store, "clm_1", claimant_id="agent_d", session_id="sess_d")
    # after the claims: the Challenge leaves clm_1 Blocked, and a Blocked node can't be claimed
    open_challenge(store, "lem_1", opened_by="agent_b", rationale="double check this")
def test_exchange_round_trips_the_full_proof_map_graph(tmp_path: Path) -> None:
    source_root = tmp_path / "alice"
    target_root = tmp_path / "bob"
    _build_source_project(source_root)

    source_store = ensure_project(source_root)
    bundle = export_exchange_bundle(source_store, note="handoff")

    assert len(bundle.proof_map_nodes) == 2
    assert len(bundle.claims) == 3  # lem_1 + clm_1's first (released on submit) + clm_1's second (active)
    assert len(bundle.candidate_proofs) == 2
    assert len(bundle.dependency_pins) == 1
    assert len(bundle.challenges) == 1

    bundle_json = bundle_to_json(bundle)
    restored_bundle = bundle_from_json(bundle_json)

    target_store = ensure_project(target_root)
    report = import_exchange_bundle(target_store, restored_bundle)

    assert "proof_map_nodes" in report.imported_sections
    assert "claims" in report.imported_sections
    assert "candidate_proofs" in report.imported_sections
    assert "dependency_pins" in report.imported_sections
    assert "challenges" in report.imported_sections

    lem_1 = get_node(target_store, "lem_1")
    assert lem_1 is not None
    assert lem_1.kind.value == "lemma"
    assert lem_1.statement == "A base lemma"

    clm_1 = get_node(target_store, "clm_1")
    assert clm_1.dependencies == ["lem_1"]
    # blocked, not claimed: lem_1 (its dependency) has an open Challenge —
    # this is the correct, imported state, not a round-trip artifact
    assert get_workflow_state(target_store, "clm_1") == "blocked"
    # an assignee in the source project isn't working here: the claim arrives released (#31)
    assert get_active_claim(target_store, "clm_1") is None
    assert [claim["claimant_id"] for claim in report.released_claims] == ["agent_d"]

    proofs = list_candidate_proofs(target_store, "lem_1")
    assert len(proofs) == 1
    assert proofs[0].scoping_rationale == "scoped correctly"

    pin = get_dependency_pin(target_store, "clm_1", "lem_1")
    assert pin is not None
    assert pin.pinned_version == 1


def test_inspect_reports_the_new_sections(tmp_path: Path) -> None:
    _build_source_project(tmp_path)
    store = ensure_project(tmp_path)
    bundle = export_exchange_bundle(store)

    report = inspect_exchange_bundle(bundle)

    assert "proof_map_nodes" in report.preserved
    assert "claims" in report.preserved
    assert "candidate_proofs" in report.preserved
    assert "dependency_pins" in report.preserved
    assert "challenges" in report.preserved
    assert report.section_counts["proof_map_nodes"] == 2
    assert report.section_counts["challenges"] == 1


def test_no_direct_sql_bypass_remains_in_exchange_module() -> None:
    import inspect

    import proof_cli.exchange as exchange_module

    source = inspect.getsource(exchange_module)
    assert "conn.execute" not in source
    assert "store.connect()" not in source


def test_cli_exchange_export_and_import_round_trip_proof_map_nodes(tmp_path: Path) -> None:
    source_root = tmp_path / "alice"
    target_root = tmp_path / "bob"
    _build_source_project(source_root)

    export_result = runner.invoke(app, ["exchange", "export", "--root", str(source_root)])
    assert export_result.exit_code == 0

    runner.invoke(app, ["init", "--root", str(target_root)])
    bundle_file = tmp_path / "bundle.json"
    bundle_file.write_text(export_result.stdout)
    import_result = runner.invoke(
        app,
        ["exchange", "import", str(bundle_file), "--root", str(target_root), "--json"],
    )
    assert import_result.exit_code == 0, import_result.output
    payload = json.loads(import_result.stdout)["data"]
    assert "proof_map_nodes" in payload["imported_sections"]

    show_result = runner.invoke(app, ["node", "show", "lem_1", "--root", str(target_root), "--json"])
    assert show_result.exit_code == 0
    assert json.loads(show_result.stdout)["data"]["statement"] == "A base lemma"
