from pathlib import Path

from proof_cli.domain import ProofObligation, TheoremStatus, TrustLevel
from proof_cli.obligations import add_obligation
from proof_cli.proof_state import set_current_context
from proof_cli.review import approve_imported_result, close_obligation_review, mark_verified, resolve_blocker_review, change_trust_level
from proof_cli.storage import ensure_project, list_events
from proof_cli.theorems import add_theorem
from proof_cli.blockers import add_blocker
from proof_cli.domain import BlockerRecord


def test_review_gate_requires_confirmation_and_logs(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="thm_1",
        kind="theorem",
        name="Imported Result",
        statement="A -> B",
        assumptions=["A"],
        exports=["B"],
        status=TheoremStatus.draft,
        trust_level=TrustLevel.temporary_admit,
    )

    blocked = approve_imported_result(store, "thm_1", confirmed=False)
    assert blocked.allowed is False
    approved = approve_imported_result(store, "thm_1", confirmed=True, rationale="source checked")
    assert approved.allowed is True

    trusted = change_trust_level(store, "thm_1", TrustLevel.project_verified, confirmed=True, rationale="locally checked")
    assert trusted.allowed is True
    verified = mark_verified(store, "thm_1", confirmed=True, rationale="proof checked")
    assert verified.allowed is True

    events = list_events(store)
    assert any(event.kind == "review_blocked" for event in events)
    assert any(event.kind == "review_approved" for event in events)


def test_review_gate_controls_blockers_and_obligations(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_obligation(
        store,
        ProofObligation(
            id="obl_1",
            goal_statement="prove result",
            required_for="thm_1",
        ),
    )
    add_blocker(
        store,
        BlockerRecord(
            id="blk_1",
            scope="thm_1",
            description="missing lemma",
            failure_type="missing_lemma",
        ),
    )
    set_current_context(store, ["A"])

    blocked_close = close_obligation_review(store, "obl_1", confirmed=True)
    assert blocked_close.allowed is False

    approved_close = close_obligation_review(store, "obl_1", confirmed=True, proof_text="proved in appendix")
    assert approved_close.allowed is True

    resolved = resolve_blocker_review(store, "blk_1", confirmed=True, rationale="lemma added")
    assert resolved.allowed is True
