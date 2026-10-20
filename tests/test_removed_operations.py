"""Lightweight re-review, Dependent migration and Evidence review are gone (ADR-0025 point 24, #280).

A pin follows an unchanged interface by itself, dependents move by ordinary dependency edits, and an Evidence check is
a record nobody judges. With them go the pin-lag reading behind Potentially stale, and Unverifiable: a verification
counts only for its own version, so a decision that no longer counts reads as none. Their old records stay as history,
and nothing reads them.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli import proof_map
from proof_cli.authority import list_authority_warnings
from proof_cli.cli import app
from proof_cli.collaboration import list_review_records
from proof_cli.errors import ERROR_CODES
from proof_cli.node_states import node_states
from proof_cli.proof_map import (
    create_node,
    dependency_details,
    get_acceptance_state,
    get_current_candidate_proof,
    get_integrity_state,
    get_reference_review_state,
    get_workflow_state,
    list_integrity_warnings,
)
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.reviews import DecisionKind, DecisionPayload, ReviewEntry, append_line, new_review_id, next_seq, reviews_path
from proof_cli.storage import ensure_project, import_reference


def _delete_reference(store, reference_id: str) -> None:
    """A citation record gone (deleted by hand, or not carried by an exchange bundle): no service deletes one."""
    with store.connect() as conn:
        conn.execute("DELETE FROM reference_records WHERE id = ?", (reference_id,))
        conn.commit()


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
    before = node_states(store, "M")
    for kind, decision, recorded, object_type, object_id in (
        (DecisionKind.dependency_revalidation, "reaffirmed", "reaffirmed", "proof_map_node", "M"),
        (DecisionKind.dependent_migration, "superseded", "superseded", "proof_map_node", "M"),
        (DecisionKind.evidence_review, "trusted", "trusted", "evidence_check", "check-1"),
    ):  # as the removed operations wrote them
        payload = DecisionPayload(kind=kind, target_id=object_id, decision=decision, rationale="from before ADR-0025")
        append_line(reviews_path(tmp_path, "M"), ReviewEntry(seq=next_seq(tmp_path), id=new_review_id(), object_type=object_type,
                                                              object_id=object_id, kind=kind.value, decision=recorded,
                                                              reviewer="Researcher <r@example.org>", rationale=payload.rationale,
                                                              payload=payload))
    history = [record.kind.value for record in list_review_records(store) if record.rationale == "from before ADR-0025"]
    assert history == ["dependency_revalidation", "dependent_migration", "evidence_review"]  # history, as it was
    assert "REVIEW_LINE_UNREADABLE" not in [warning.code for warning in list_authority_warnings(store)]
    assert node_states(store, "M") == before  # and nothing reads them
