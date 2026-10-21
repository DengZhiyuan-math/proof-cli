"""Lightweight re-review, Dependent migration and Evidence review are gone (ADR-0025 point 24, #280).

A pin follows an unchanged interface by itself, dependents move by ordinary dependency edits, and an Evidence check is
a record nobody judges. With them go the pin-lag reading behind Potentially stale, and Unverifiable: a verification
counts only for its own version, so a decision that no longer counts reads as none. Their old records stay as history,
and nothing reads them.
"""

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli import proof_map
from proof_cli.authority import list_authority_warnings, list_decisions, verify_decision_row
from proof_cli.cli import app
from proof_cli.collaboration import list_review_records
from proof_cli.errors import ERROR_CODES
from proof_cli.node_states import node_states
from proof_cli.proof_map import (
    add_dependency,
    create_node,
    dependency_details,
    dependency_pin_is_current,
    get_acceptance_state,
    get_current_candidate_proof,
    get_dependency_pin,
    get_integrity_state,
    get_reference_review_state,
    get_workflow_state,
    is_provisional,
    list_integrity_warnings,
    record_evidence_check,
    remove_dependency,
    snapshot_with_changed_dependencies,
)
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.reviews import (
    DecisionKind,
    DecisionPayload,
    PinnedDependency,
    ReviewEntry,
    append_line,
    new_review_id,
    next_seq,
    reviews_path,
)
from proof_cli.storage import ensure_project, import_reference, load_project

PRE_ADR_0010_PROJECT = Path(__file__).parent / "fixtures" / "pre_adr_0009_project"


def _delete_reference(store, reference_id: str) -> None:
    """A citation record gone (deleted by hand, or not carried by an exchange bundle): no service deletes one."""
    with store.connect() as conn:
        conn.execute("DELETE FROM reference_records WHERE id = ?", (reference_id,))
        conn.commit()


def _old_line(root: Path, node_id: str, kind: DecisionKind, decision: str, object_type: str, object_id: str, **made_on) -> None:
    """A line in `node_id`'s reviews.jsonl as one of the three removed operations wrote it, before ADR-0025."""
    payload = DecisionPayload(kind=kind, target_id=object_id, decision=decision, rationale="from before ADR-0025", **made_on)
    append_line(reviews_path(root, node_id), ReviewEntry(seq=next_seq(root), id=new_review_id(), object_type=object_type,
                                                         object_id=object_id, kind=kind.value, decision=decision,
                                                         reviewer="Researcher <r@example.org>", rationale=payload.rationale,
                                                         payload=payload))


def _accept(store, node_id: str, content: str) -> None:
    submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=content)
    researcher(store).decide_acceptance(node_id, "accept")


def test_no_command_service_function_or_error_code_of_the_three_operations_remains(tmp_path: Path):
    for name in ("revalidate_dependency", "migrate_dependents", "list_migratable_dependents", "decide_evidence_review",
                 "EvidenceTrustDecision", "dependency_pin_lags"):
        assert not hasattr(proof_map, name), name
    for code in ("TARGET_NOT_ACCEPTED", "PIN_NOT_LAGGING", "INTERFACE_CHANGED", "NO_DEPENDENCY_PIN", "DEPENDENCY_REQUIRED",
                 "REFERENCE_STILL_CALLABLE", "REPLACEMENT_REQUIRED", "REPLACEMENT_NOT_IMPORTED_RESULT", "REPLACEMENT_NOT_CALLABLE",
                 "NO_DEPENDENTS", "NODE_UNVERIFIABLE"):
        assert code not in ERROR_CODES, code
    ensure_project(tmp_path)
    for args in (["node", "revalidate", "M", "L"], ["node", "migrate-dependents", "I", "J"], ["node", "evidence", "review", "x", "trusted"]):
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"])
        assert result.exit_code != 0 and json.loads(result.output)["error"]["code"] == "USAGE_ERROR", args


def test_a_dependency_revised_with_its_statement_unchanged_leaves_its_dependent_as_it_was(tmp_path: Path):
    # a pin follows an unchanged interface by itself: nothing to re-review
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L holds")
    _accept(store, "L", "proof of L, v1")
    create_node(store, node_id="M", kind="claim", statement="M holds, given L", dependencies=["L"])
    _accept(store, "M", "proof of M")
    _accept(store, "L", "proof of L, v2, shorter")
    assert get_integrity_state(store, "M") == "current"
    assert (node_states(store, "M").proof_layer, node_states(store, "M").conclusion) == ("expert-verified", "verified-true")
    (detail,) = dependency_details(store, "M")
    assert not {"remedy", "accepted_version"} & set(detail) and (detail["node_id"], detail["current"]) == ("L", True)


def test_a_decision_that_no_longer_counts_reads_as_none_never_unverifiable(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C")
    _accept(store, "clm", "proof of clm")
    (tmp_path / get_current_candidate_proof(store, "clm").file_path).write_text("a different proof")  # the snapshot changed
    assert (get_acceptance_state(store, "clm"), get_workflow_state(store, "clm")) == ("unreviewed", "review-needed")
    import_reference(store, ReferenceRecord(id="rudin", title="Analysis", authors=["W. Rudin"], year=1976,
                                            source_type=ReferenceSourceType.textbook, identifier="isbn:0"))
    create_node(store, node_id="imp", kind="imported_result", statement="I", source_locator="Theorem 1", source_version="v1", reference_id="rudin")
    researcher(store).decide_reference_review("imp")
    _delete_reference(store, "rudin")  # the citation it was reviewed on is gone
    assert get_reference_review_state(store, "imp") == "unreviewed"
    assert "DECISION_NO_LONGER_APPLIES" not in [warning.code for warning in list_integrity_warnings(store)]


def test_old_records_of_the_three_load_and_show_as_history_only(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L")
    create_node(store, node_id="M", kind="claim", statement="M", dependencies=["L"])
    _old_line(tmp_path, "M", DecisionKind.dependency_revalidation, "reaffirmed", "proof_map_node", "M")
    _old_line(tmp_path, "M", DecisionKind.dependent_migration, "superseded", "proof_map_node", "M")
    _old_line(tmp_path, "M", DecisionKind.evidence_review, "trusted", "evidence_check", "check-1")

    history = [record.kind.value for record in list_review_records(store) if record.rationale == "from before ADR-0025"]
    assert history == ["dependency_revalidation", "dependent_migration", "evidence_review"]  # history, as it was
    assert "REVIEW_LINE_UNREADABLE" not in [warning.code for warning in list_authority_warnings(store)]
    # that nothing acts on them: one test each below, set up as the removed readers would have read them


def test_a_verification_whose_snapshot_is_gone_or_changed_reads_as_none_and_is_warned_about(tmp_path: Path):
    # a lost or edited Review snapshot is no new version: the decision on it reads as none, and the warning says why
    store = ensure_project(tmp_path)
    for node_id in ("acc", "ver", "edt"):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds")
        submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance("acc", "accept")
    researcher(store).verify("ver")
    researcher(store).decide_acceptance("edt", "accept")
    snapshot = {node_id: get_current_candidate_proof(store, node_id).file_path for node_id in ("acc", "ver", "edt")}
    shutil.rmtree((tmp_path / snapshot["acc"]).parent)  # gone
    shutil.rmtree((tmp_path / snapshot["ver"]).parent)
    (tmp_path / snapshot["edt"]).parent.joinpath("node", "proof.tex").write_text("a different proof")  # edited since

    assert {node_id: node_states(store, node_id).proof_layer for node_id in snapshot} == dict.fromkeys(snapshot, "incomplete")
    assert get_acceptance_state(store, "acc") == "unreviewed"
    warned = {warning.details["node_id"]: warning for warning in list_integrity_warnings(store) if warning.code == "SNAPSHOT_NO_LONGER_AS_DECIDED"}
    assert set(warned) == {"acc", "ver", "edt"}
    folder = snapshot["acc"].rsplit("/", 1)[0]
    assert folder in warned["acc"].message and warned["acc"].details["file_path"] == folder
    assert "missing" in warned["acc"].message and "changed" in warned["edt"].message


def test_an_old_projects_evidence_review_moves_into_reviews_jsonl_as_the_history_it_was(tmp_path: Path):
    # the fixture's decisions predate reviews.jsonl; moving them binds each to what it was made on, once
    root = tmp_path / "project"
    shutil.copytree(PRE_ADR_0010_PROJECT, root)
    store = load_project(root)

    (row,) = [row for row in list_decisions(store) if row["kind"] == "evidence_review"]
    assert (row["decision"], verify_decision_row(store, row["id"]).status) == ("trusted", "verified")


def test_an_old_lightweight_re_review_re_pins_nothing(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L holds")
    _accept(store, "L", "proof of L")
    create_node(store, node_id="M", kind="claim", statement="M holds, given L", dependencies=["L"])
    _accept(store, "M", "proof of M")
    before = node_states(store, "M")

    _old_line(tmp_path, "M", DecisionKind.dependency_revalidation, "reaffirmed", "proof_map_node", "M",
              dependency_pins=[PinnedDependency(target_node_id="L", pinned_version=7, pinned_fingerprint="re-pinned elsewhere")])

    pin = get_dependency_pin(store, "M", "L")
    assert (pin.pinned_version, dependency_pin_is_current(store, pin)) == (1, True)  # the Acceptance's pin, as it was
    assert node_states(store, "M") == before


def test_an_old_dependent_migration_leaves_its_dependents_requesting_review_again(tmp_path: Path):
    # the snapshot was made resting on I; the dependent rests on its correction now, and its decision is refused
    store = ensure_project(tmp_path)
    create_node(store, node_id="I", kind="lemma", statement="I holds")
    create_node(store, node_id="I2", kind="lemma", statement="I holds, corrected")
    create_node(store, node_id="J", kind="claim", statement="J holds, given I", dependencies=["I"])
    submit_proof(store, "J", claimant_id="agent", scoping_rationale="scoped", content="proof of J")
    add_dependency(store, "J", "I2")
    remove_dependency(store, "J", "I")

    _old_line(tmp_path, "I", DecisionKind.dependent_migration, "superseded", "proof_map_node", "I",
              dependency_pins=[PinnedDependency(target_node_id="I2")], migrated_dependents=["J"])

    assert snapshot_with_changed_dependencies(store, "J") is not None  # DEPENDENCIES_CHANGED: request review again


def test_an_old_evidence_review_finding_a_verifier_pass_unusable_no_longer_keeps_a_node_from_provisional(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C holds")
    proof = submit_proof(store, "clm", claimant_id="agent", scoping_rationale="scoped", content="proof of clm")
    check = record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", notes="no objections")

    _old_line(tmp_path, "clm", DecisionKind.evidence_review, "unusable", "evidence_check", check.id, candidate_proof_id=proof.id)

    assert is_provisional(store, "clm")
