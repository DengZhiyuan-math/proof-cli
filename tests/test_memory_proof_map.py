from _researcher import researcher
"""Issue #29: memory records can reference the unified ProofMapNode id,
plus a specific Candidate proof or Human Review decision, without losing
the older split id fields the frozen bug/debug system still relies on.
"""
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.memory import list_memory_artifacts, record_memory
from proof_cli.proof_map import claim_node, create_node, decide_acceptance, submit_candidate_proof
from proof_cli.storage import ensure_project

runner = CliRunner()


def test_record_memory_links_to_a_proof_map_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A claim worth remembering something about")

    record_memory(store, "semantic", "this claim depends on a subtle case split", node_id="clm_1", importance="high")

    artifacts = list_memory_artifacts(store, node_id="clm_1")
    assert len(artifacts) == 1
    assert artifacts[0].scope.node_id == "clm_1"
    assert artifacts[0].linked_proof_state.node_id == "clm_1"


def test_record_memory_links_to_a_specific_candidate_proof_and_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="sess_1")
    proof = submit_candidate_proof(
        store,
        "clm_1",
        claimant_id="agent_a",
        session_id="sess_1",
        scoping_rationale="scoped correctly",
        content="proof text")
    review = researcher(store).decide_acceptance("clm_1", "accept")

    record_memory(
        store,
        "episodic",
        "this submission needed a second look before acceptance",
        node_id="clm_1",
        candidate_proof_id=proof.id,
        review_id=review.id,
    )

    artifacts = list_memory_artifacts(store, node_id="clm_1")
    assert artifacts[0].scope.candidate_proof_id == proof.id
    assert artifacts[0].scope.review_id == review.id
    assert artifacts[0].linked_proof_state.candidate_proof_id == proof.id
    assert artifacts[0].linked_proof_state.review_id == review.id


def test_node_id_filter_does_not_pick_up_unrelated_old_style_records(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    record_memory(store, "semantic", "about the new node model", node_id="clm_1")
    record_memory(store, "semantic", "about an old-model theorem", theorem_id="thm_legacy")

    node_scoped = list_memory_artifacts(store, node_id="clm_1")
    assert len(node_scoped) == 1
    assert node_scoped[0].content == "about the new node model"

    theorem_scoped = list_memory_artifacts(store, theorem_id="thm_legacy")
    assert len(theorem_scoped) == 1
    assert theorem_scoped[0].content == "about an old-model theorem"


def test_older_split_id_fields_still_work_unchanged(tmp_path: Path):
    """The frozen bug/debug system's multi-reference records (e.g. a single
    memory entry citing both an obligation and a blocker) must keep working
    exactly as before — this is why the four fields were kept, not replaced."""
    store = ensure_project(tmp_path)

    record_memory(
        store,
        "semantic",
        "bug touches both an obligation and a blocker",
        theorem_id="thm_legacy",
        obligation_id="obl_1",
        blocker_id="blk_1",
    )

    artifacts = list_memory_artifacts(store, theorem_id="thm_legacy")
    assert len(artifacts) == 1
    assert artifacts[0].scope.obligation_id == "obl_1"
    assert artifacts[0].scope.blocker_id == "blk_1"
    assert artifacts[0].scope.node_id is None


def test_cli_memory_add_and_list_by_node_id(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "stmt", "--root", str(tmp_path)])

    add_result = runner.invoke(
        app,
        [
            "memory", "add", "worth remembering", "--root", str(tmp_path),
            "--layer", "semantic", "--node-id", "clm_1", "--importance", "high",
        ],
    )
    assert add_result.exit_code == 0

    list_result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path), "--node-id", "clm_1"])
    assert list_result.exit_code == 0
    assert "worth remembering" in list_result.stdout
