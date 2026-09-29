"""Issue #45: memory and handoff read the proof map.

Memory written against a node is validated against the map, a node's
recovery and handoff carry everything scoped to it (its own entries, its
Candidate proofs' and Review decisions', and its derived_from parent's), and
the handoff's accepted list is exactly the nodes `get_acceptance_state`
calls accepted (ADR-0010), with the legacy verify/usage lists labelled as
legacy (ADR-0012).
"""

import json
from pathlib import Path

import pytest

from _proofs import ensure_key_ideas
from typer.testing import CliRunner

from _researcher import researcher
from proof_cli.cli import app
from proof_cli.memory import (
    ProofDebugScope,
    build_handoff_snapshot,
    list_memory_artifacts,
    load_memory,
    node_scope_memory,
    record_memory,
    record_proof_debug_record,
)
from proof_cli.proof_map import ProofMapError, create_node, get_acceptance_state, list_nodes, request_review, split_node
from proof_cli.snapshot import create_snapshot, restore_snapshot
from proof_cli.storage import ensure_project

runner = CliRunner()


def _reviewed(store, node_id: str, *, accept: bool = True):
    """A claim with one snapshot under review and, if `accept`, an Acceptance on it."""
    create_node(store, node_id=node_id, kind="claim", statement=f"statement of {node_id}")
    working = store.root / "proofs" / node_id / "proof.tex"
    working.write_text(working.read_text().replace("% Write the proof here.", f"A proof of {node_id}."))
    ensure_key_ideas(store, node_id)
    proof = request_review(store, node_id, requested_by="agent_a", rationale="small enough")
    review = researcher(store).decide_acceptance(node_id, "accept") if accept else None
    return proof, review


def _all_memory(store) -> list:
    memory = load_memory(store)
    return [*memory.working, *memory.semantic, *memory.episodic, *memory.procedural]


# -- writes are validated against the proof map ----------------------------------------


def test_memory_on_a_node_that_does_not_exist_is_refused_and_not_written(tmp_path: Path):
    store = ensure_project(tmp_path)

    with pytest.raises(ProofMapError) as raised:
        record_memory(store, "semantic", "about a ghost", node_id="clm_ghost")

    assert raised.value.code == "NODE_NOT_FOUND"
    assert _all_memory(store) == []


def test_a_candidate_proof_of_another_node_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    other_proof, _ = _reviewed(store, "clm_other", accept=False)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as raised:
        record_memory(store, "episodic", "wrong proof", node_id="clm_1", candidate_proof_id=other_proof.id)

    assert raised.value.code == "NOT_THIS_NODE"
    assert _all_memory(store) == []


def test_an_unknown_candidate_proof_or_review_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as proof_raised:
        record_memory(store, "episodic", "no such proof", node_id="clm_1", candidate_proof_id="cp_missing")
    with pytest.raises(ProofMapError) as review_raised:
        record_memory(store, "episodic", "no such review", node_id="clm_1", review_id="rev_missing")

    assert proof_raised.value.code == "CANDIDATE_PROOF_NOT_FOUND"
    assert review_raised.value.code == "REVIEW_NOT_FOUND"
    assert _all_memory(store) == []


def test_a_review_of_another_node_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _, other_review = _reviewed(store, "clm_other")
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    with pytest.raises(ProofMapError) as raised:
        record_memory(store, "episodic", "wrong review", node_id="clm_1", review_id=other_review.id)

    assert raised.value.code == "NOT_THIS_NODE"
    assert _all_memory(store) == []


def test_a_candidate_proof_or_review_alone_scopes_the_entry_to_its_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof, review = _reviewed(store, "clm_1")

    record_memory(store, "episodic", "about the proof", candidate_proof_id=proof.id)
    record_memory(store, "episodic", "about the review", review_id=review.id)

    assert {artifact.scope.node_id for artifact in _all_memory(store)} == {"clm_1"}


@pytest.mark.parametrize(
    ("flags", "code"),
    [
        (["--node-id", "clm_ghost"], "NODE_NOT_FOUND"),
        (["--node-id", "clm_1", "--candidate-proof-id", "OTHER_PROOF"], "NOT_THIS_NODE"),
        (["--node-id", "clm_1", "--review-id", "OTHER_REVIEW"], "NOT_THIS_NODE"),
    ],
)
def test_cli_memory_add_refuses_a_bad_scope_as_a_json_error_envelope(tmp_path: Path, flags: list[str], code: str):
    store = ensure_project(tmp_path)
    other_proof, other_review = _reviewed(store, "clm_other")
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    flags = [{"OTHER_PROOF": other_proof.id, "OTHER_REVIEW": other_review.id}.get(flag, flag) for flag in flags]

    result = runner.invoke(app, ["memory", "add", "misplaced", "--root", str(tmp_path), "--json", *flags])

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "memory.add"
    assert envelope["error"]["code"] == code
    assert _all_memory(store) == []


def test_cli_memory_add_no_longer_writes_legacy_scope_fields(tmp_path: Path):
    """theorem/goal/obligation/blocker ids are read-only legacy scope (ADR-0012): new writes are node-scoped."""
    ensure_project(tmp_path)
    for flag in ("--theorem-id", "--goal-id", "--obligation-id", "--blocker-id"):
        result = runner.invoke(app, ["memory", "add", "legacy", "--root", str(tmp_path), flag, "x"])
        assert result.exit_code == 2, flag


def test_cli_memory_add_json_envelope_on_success(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")

    result = runner.invoke(app, ["memory", "add", "fine", "--root", str(tmp_path), "--node-id", "clm_1", "--json"])

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True and envelope["command"] == "memory.add"
    assert envelope["data"]["scope"]["node_id"] == "clm_1"


# -- memory list ------------------------------------------------------------------------


def test_memory_list_filters_by_candidate_proof_and_review_and_shows_the_scope(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof, review = _reviewed(store, "clm_1")
    record_memory(store, "semantic", "about the node", node_id="clm_1")
    record_memory(store, "episodic", "about the proof", node_id="clm_1", candidate_proof_id=proof.id)
    record_memory(store, "episodic", "about the review", node_id="clm_1", review_id=review.id)

    assert [a.content for a in list_memory_artifacts(store, candidate_proof_id=proof.id)] == ["about the proof"]
    assert [a.content for a in list_memory_artifacts(store, review_id=review.id)] == ["about the review"]

    by_proof = runner.invoke(app, ["memory", "list", "--root", str(tmp_path), "--candidate-proof-id", proof.id])
    by_review = runner.invoke(app, ["memory", "list", "--root", str(tmp_path), "--review-id", review.id])
    by_node = runner.invoke(app, ["memory", "list", "--root", str(tmp_path), "--node-id", "clm_1"])

    assert by_proof.exit_code == 0 and "about the proof" in by_proof.stdout and "about the review" not in by_proof.stdout
    assert f"candidate_proof={proof.id}" in by_proof.stdout
    assert by_review.exit_code == 0 and "about the review" in by_review.stdout and "about the proof" not in by_review.stdout
    assert f"review={review.id}" in by_review.stdout
    assert "node=clm_1" in by_node.stdout
    assert "project-scope" not in by_node.stdout


def test_memory_list_json_envelope_lists_only_the_entries_of_that_proof_or_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    proof, review = _reviewed(store, "clm_1")
    record_memory(store, "semantic", "about the node", node_id="clm_1")
    record_memory(store, "episodic", "about the proof", node_id="clm_1", candidate_proof_id=proof.id)
    record_memory(store, "episodic", "about the review", node_id="clm_1", review_id=review.id)

    for flag, value, expected in (
        ("--candidate-proof-id", proof.id, "about the proof"),
        ("--review-id", review.id, "about the review"),
    ):
        result = runner.invoke(app, ["memory", "list", "--root", str(tmp_path), flag, value, "--json"])
        assert result.exit_code == 0, result.stdout
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True and envelope["command"] == "memory.list"
        (artifact,) = envelope["data"]["memory"]
        assert artifact["content"] == expected


# -- node-scoped recovery and handoff ---------------------------------------------------


def _seed_node_and_noise(store):
    proof, review = _reviewed(store, "clm_1")
    record_memory(store, "working", "own: working on the case split", node_id="clm_1")
    record_memory(store, "semantic", "own: the lemma is reusable", node_id="clm_1")
    record_memory(store, "episodic", "proof: v1 skipped a boundary case", node_id="clm_1", candidate_proof_id=proof.id)
    record_memory(store, "procedural", "review: the reviewer wanted the constant explicit", node_id="clm_1", review_id=review.id)
    for index in range(12):
        node_id = f"clm_noise_{index}"
        create_node(store, node_id=node_id, kind="claim", statement=f"noise {index}")
        for layer in ("working", "semantic", "episodic", "procedural"):
            record_memory(store, layer, f"noise {index} {layer}", node_id=node_id)
    return proof, review


NODE_ENTRIES = {
    "own: working on the case split",
    "own: the lemma is reusable",
    "proof: v1 skipped a boundary case",
    "review: the reviewer wanted the constant explicit",
}


def test_node_recovery_carries_its_own_proof_and_review_memory_despite_other_nodes(tmp_path: Path):
    store = ensure_project(tmp_path)
    _seed_node_and_noise(store)
    assert len(_all_memory(store)) >= 10 + len(NODE_ENTRIES)

    assert {artifact.content for artifact in node_scope_memory(store, "clm_1")} == NODE_ENTRIES

    create_snapshot(store, note="handoff", node_id="clm_1")
    restored = restore_snapshot(store, node_id="clm_1")

    assert restored is not None
    assert restored.node_id == "clm_1"
    assert {artifact.content for artifact in restored.node_memory} == NODE_ENTRIES
    assert "own: working on the case split" in restored.working_context
    assert "own: the lemma is reusable" in restored.stable_facts
    assert "proof: v1 skipped a boundary case" in restored.failed_routes
    assert "review: the reviewer wanted the constant explicit" in restored.procedural_tactics
    for text in (*restored.working_context, *restored.stable_facts, *restored.failed_routes, *restored.procedural_tactics, *restored.recent_attempts):
        assert not text.startswith("noise"), text


def test_node_handoff_is_recorded_with_its_node_memory(tmp_path: Path):
    store = ensure_project(tmp_path)
    _seed_node_and_noise(store)

    create_snapshot(store, note="handoff", node_id="clm_1")

    recorded = load_memory(store).handoff_snapshots[-1]
    assert recorded.node_id == "clm_1"
    assert {artifact.content for artifact in recorded.node_memory} == NODE_ENTRIES


def test_cli_handoff_create_takes_a_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    _seed_node_and_noise(store)

    result = runner.invoke(app, ["handoff", "create", "--root", str(tmp_path), "--node-id", "clm_1"])

    assert result.exit_code == 0, result.stdout
    bundle = json.loads(result.stdout)
    assert bundle["handoff_snapshot"]["node_id"] == "clm_1"
    assert {entry["content"] for entry in bundle["handoff_snapshot"]["node_memory"]} == NODE_ENTRIES


def test_cli_handoff_create_refuses_an_unknown_node(tmp_path: Path):
    ensure_project(tmp_path)
    result = runner.invoke(app, ["handoff", "create", "--root", str(tmp_path), "--node-id", "clm_ghost"])
    assert result.exit_code == 1
    assert "clm_ghost" in result.stdout


def test_a_split_child_recovers_its_parents_memory(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_parent", kind="claim", statement="the whole thing")
    record_memory(store, "semantic", "parent: the key estimate is uniform in n", node_id="clm_parent")
    split_node(store, "clm_parent", [{"id": "clm_child", "statement": "one piece"}])
    record_memory(store, "working", "child: starting on the piece", node_id="clm_child")
    create_node(store, node_id="clm_unrelated", kind="claim", statement="unrelated")
    record_memory(store, "semantic", "unrelated", node_id="clm_unrelated")

    assert {a.content for a in node_scope_memory(store, "clm_child")} == {
        "parent: the key estimate is uniform in n",
        "child: starting on the piece",
    }
    create_snapshot(store, node_id="clm_child")
    restored = restore_snapshot(store, node_id="clm_child")
    assert "parent: the key estimate is uniform in n" in restored.stable_facts
    # the parent doesn't inherit its children's memory
    assert {a.content for a in node_scope_memory(store, "clm_parent")} == {"parent: the key estimate is uniform in n"}


def test_node_scope_memory_of_an_unknown_node_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as raised:
        node_scope_memory(store, "clm_ghost")
    assert raised.value.code == "NODE_NOT_FOUND"


def test_project_wide_handoff_still_reads_recent_memory(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    record_memory(store, "working", "project-wide note")

    create_snapshot(store)
    restored = restore_snapshot(store)

    assert restored.node_id is None
    assert restored.working_context == ["project-wide note"]


# -- ProofDebugScope --------------------------------------------------------------------


def test_proof_debug_scope_has_a_node_id_and_node_handoffs_read_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="stmt")
    create_node(store, node_id="clm_2", kind="claim", statement="stmt 2")

    assert "node_id" in ProofDebugScope.model_fields
    record = record_proof_debug_record(store, "failure_motif", "circular use of the main estimate", node_id="clm_1", motif="circularity")
    record_proof_debug_record(store, "failure_motif", "elsewhere", node_id="clm_2", motif="other")
    assert record.scope.node_id == "clm_1"

    create_snapshot(store, node_id="clm_1")
    restored = restore_snapshot(store, node_id="clm_1")
    assert [r.summary for r in restored.proof_debug_history] == ["circular use of the main estimate"]
    assert restored.failure_motifs == ["circularity"]

    with pytest.raises(ProofMapError):
        record_proof_debug_record(store, "failure_motif", "ghost", node_id="clm_ghost")


# -- the proof map section of the handoff -----------------------------------------------


def test_handoff_accepted_list_is_exactly_the_accepted_nodes(tmp_path: Path):
    store = ensure_project(tmp_path)
    accepted_proof, _ = _reviewed(store, "clm_accepted")
    _reviewed(store, "clm_also_accepted")
    _reviewed(store, "clm_pending", accept=False)
    create_node(store, node_id="clm_open", kind="claim", statement="not started")
    _reviewed(store, "clm_rejected", accept=False)
    researcher(store).decide_acceptance("clm_rejected", "reject")

    snapshot = create_snapshot(store)
    handoff = build_handoff_snapshot(store, snapshot)

    expected = sorted(node.id for node in list_nodes(store) if get_acceptance_state(store, node.id) == "accepted")
    assert expected == ["clm_accepted", "clm_also_accepted"]
    assert [entry.node_id for entry in handoff.proof_map.accepted] == expected
    assert handoff.proof_map.unverifiable == []

    # the accepted snapshot changes on disk: the decision no longer counts
    (tmp_path / accepted_proof.file_path).write_text("a different proof")
    assert get_acceptance_state(store, "clm_accepted") == "unverifiable"

    handoff = build_handoff_snapshot(store, create_snapshot(store))
    assert [entry.node_id for entry in handoff.proof_map.accepted] == ["clm_also_accepted"]
    assert [entry.node_id for entry in handoff.proof_map.unverifiable] == ["clm_accepted"]
    assert handoff.proof_map.unverifiable[0].reason


def test_legacy_trust_lists_are_labelled_legacy(tmp_path: Path):
    store = ensure_project(tmp_path)
    handoff = build_handoff_snapshot(store, create_snapshot(store))

    assert "legacy" in handoff.legacy_notice
    assert "accepted_verification_results" in handoff.legacy_notice
    assert "validated_results" in handoff.legacy_notice
    assert "proof_map" in handoff.legacy_notice
