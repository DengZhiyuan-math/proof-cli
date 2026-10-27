"""What survives of the Acceptance preconditions (issue #19) once Acceptance is no decision (ADR-0025 point 24, #323).

The operation's own gates went with it: an old Acceptance is a line older versions wrote (`legacy_decisions`), read as
a verification. What stays: no other path writes an Acceptance, a decision on a snapshot that can't be read is refused,
and an exchange import doesn't reopen a node Accepted here.
"""

import json
from pathlib import Path

import pytest

from _researcher import researcher

from proof_cli.commands import cmd_proof_verify_run
from proof_cli.exchange import export_exchange_bundle, import_exchange_bundle
from proof_cli.proof_map import (
    ProofMapError,
    create_node,
    get_acceptance_state,
    get_workflow_state,
    split_node,
)
from proof_cli.storage import ensure_project, get_current_candidate_proof
from proof_cli.theorems import add_theorem
from _proofs import submit_proof


def _submit(store, node_id: str, *, session: str = "sess_1") -> None:
    submit_proof(  # needs no claim (ADR-0010)
        store, node_id, claimant_id="agent_a", session_id=session, scoping_rationale="scoped", content=f"proof text ({session})")


def _awaiting_review(store, node_id: str = "clm_1", **node_fields) -> None:
    create_node(store, node_id=node_id, kind=node_fields.pop("kind", "claim"), statement=f"stmt {node_id}", **node_fields)
    _submit(store, node_id)
    assert get_workflow_state(store, node_id) == "review-needed"


def _decide(store, node_id: str, decision: str):
    return researcher(store).decide_acceptance(node_id, decision)


# -- no other path writes acceptance_state -------------------------------------


def test_split_promote_verify_and_exchange_import_never_write_acceptance_state(tmp_path: Path):
    store = ensure_project(tmp_path / "local")
    create_node(store, node_id="clm_parent", kind="claim", statement="parent")
    split_node(store, "clm_parent", [{"id": "clm_child", "statement": "child"}])
    assert get_acceptance_state(store, "clm_parent") == "unreviewed"
    assert get_acceptance_state(store, "clm_child") == "unreviewed"

    # promote refuses an unaccepted claim rather than accepting it along the way
    with pytest.raises(ProofMapError) as exc_info:
        researcher(store).promote_to_lemma("clm_child")
    assert exc_info.value.code == "NOT_VERIFIED"
    assert get_acceptance_state(store, "clm_child") == "unreviewed"

    # the legacy theorem-contract verify path, on a contract sharing the node's id (the trust
    # commands themselves are gone, #37)
    add_theorem(store, theorem_id="clm_child", kind="lemma", name="child", statement="child")
    assert json.loads(cmd_proof_verify_run("clm_child", root=tmp_path / "local"))["machine_check_status"] == "queued_for_verification"
    assert get_acceptance_state(store, "clm_child") == "unreviewed"

    # exchange import of a project where the same node ids are Accepted
    foreign = ensure_project(tmp_path / "foreign")
    create_node(foreign, node_id="clm_foreign", kind="claim", statement="foreign")
    _submit(foreign, "clm_foreign")
    _decide(foreign, "clm_foreign", "accept")
    assert get_acceptance_state(foreign, "clm_foreign") == "accepted"
    import_exchange_bundle(store, export_exchange_bundle(foreign))
    assert get_acceptance_state(store, "clm_foreign") == "unreviewed"


def test_a_node_imported_without_its_snapshot_cannot_be_verified(tmp_path: Path):
    """#92: a Candidate proof indexed here whose snapshot is missing can't be decided on.
    Since #31 a bundle that doesn't carry the snapshot is refused whole, so the snapshot
    goes missing after the import here."""
    import shutil

    foreign = ensure_project(tmp_path / "foreign")
    _awaiting_review(foreign)
    local = ensure_project(tmp_path / "local")
    stripped = export_exchange_bundle(foreign)
    stripped.vault_files = []
    with pytest.raises(ProofMapError) as refused:
        import_exchange_bundle(local, stripped)
    assert refused.value.code == "VAULT_FILE_MISSING"

    import_exchange_bundle(local, export_exchange_bundle(foreign))
    shutil.rmtree(local.root / "proofs" / "clm_1" / "snapshots" / "v1")
    assert get_current_candidate_proof(local, "clm_1") is not None

    with pytest.raises(ProofMapError) as exc_info:
        researcher(local).verify("clm_1")

    assert exc_info.value.code == "SNAPSHOT_UNREADABLE"
    assert not (local.root / "proofs" / "clm_1" / "reviews.jsonl").exists()


def test_exchange_import_cannot_reopen_a_local_accepted_node_for_review(tmp_path: Path):
    """A hand-made bundle carrying only a newer Candidate proof for a node
    that's Accepted here would otherwise put it back in review-needed with
    no Challenge — a way around the one sanctioned re-decision route."""
    local = ensure_project(tmp_path / "local")
    _awaiting_review(local)
    _decide(local, "clm_1", "accept")

    foreign = ensure_project(tmp_path / "foreign")
    bundle = export_exchange_bundle(foreign)
    v1 = get_current_candidate_proof(local, "clm_1")
    bundle.candidate_proofs = [v1.model_copy(update={"id": "cp_foreign_v2", "version": 2, "review_record_id": None})]

    report = import_exchange_bundle(local, bundle)

    assert any("already exists here" in warning for warning in report.warnings)
    assert get_current_candidate_proof(local, "clm_1").id == v1.id
    assert get_workflow_state(local, "clm_1") == "open"
    assert get_acceptance_state(local, "clm_1") == "accepted"
