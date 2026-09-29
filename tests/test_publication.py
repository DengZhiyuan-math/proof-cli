from __future__ import annotations

import json
from pathlib import Path

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.proof_map import claim_node, create_node
from proof_cli.publication import (
    PublicationAudience,
    PublicationCitationKind,
    PublicationReadiness,
    build_publication_view,
    load_publication_state,
    publication_bundle_export,
    publication_manifest_export,
    publication_paper_export,
    publication_supplement_export,
    record_citation_provenance,
    record_editorial_note,
    record_publication_bundle_snapshot,
    record_publication_release,
    record_verification_summary,
    set_publication_claim,
)
from proof_cli.storage import ensure_project


def _accepted_node(store, node_id: str, statement: str) -> None:
    create_node(store, node_id=node_id, kind="claim", statement=statement)
    claim_node(store, node_id, claimant_id="agent_a", session_id="s")
    submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def _step_to(store, node_id: str, target: PublicationReadiness, **details) -> None:
    order = [PublicationReadiness.collaborator_ready, PublicationReadiness.supplement_ready, PublicationReadiness.paper_ready]
    for step in order[: order.index(target) + 1]:
        set_publication_claim(store, node_id, object_type="proof_map_node", readiness=step, **details)


def test_publication_state_and_exports_round_trip(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    _accepted_node(store, "clm_main", "A implies C")
    _accepted_node(store, "clm_supp", "B implies C")
    create_node(store, node_id="clm_internal", kind="claim", statement="C implies D")

    _step_to(
        store, "clm_main", PublicationReadiness.paper_ready,
        display_name="Main Publication Claim", title="A implies C", section_placement="Section 3",
        citation_kind=PublicationCitationKind.project_original,
    )
    _step_to(
        store, "clm_supp", PublicationReadiness.supplement_ready,
        display_name="Supplement Claim", title="B implies C", section_placement="Appendix A",
        citation_kind=PublicationCitationKind.imported_reference,
    )
    set_publication_claim(
        store, "clm_internal", object_type="proof_map_node", readiness=PublicationReadiness.internal_draft,
        display_name="Internal Claim", title="C implies D", internal_only=True,
    )

    record_citation_provenance(
        store,
        "clm_main",
        "ref_1",
        usage_type=PublicationCitationKind.project_original,
        citation_note="project-original contribution",
    )
    record_verification_summary(
        store,
        "clm_main",
        included_fragments=["frag_1"],
        summary="machine-checked support",
    )
    record_editorial_note(store, "clm_main", "tighten wording", section_label="Section 3")
    record_publication_release(store, audience=PublicationAudience.paper, approved_by=["alice"], rationale="ready", note="release note")
    record_publication_bundle_snapshot(store, PublicationAudience.paper, note="handoff snapshot")

    paper = publication_paper_export(store)
    supplement = publication_supplement_export(store)
    bundle = json.loads(publication_bundle_export(store))
    manifest = json.loads(publication_manifest_export(store))
    view = build_publication_view(store, PublicationAudience.paper)

    assert view.audience == PublicationAudience.paper
    assert any(selection.visible for selection in view.selections)
    assert "Main Publication Claim" in paper
    assert "Supplement Claim" not in paper
    assert "Internal Claim" not in paper
    assert "Supplement Claim" in supplement
    assert "Internal Claim" not in supplement
    assert bundle["publication_state"]["states"]
    assert bundle["bundle_snapshots"]
    assert manifest["claim_count"] >= 2
    assert manifest["release_count"] >= 1

    reopened = ensure_project(tmp_path)
    restored = load_publication_state(reopened)
    assert len(restored.claims) == 3
    assert len(restored.release_history) >= 1
    assert len(restored.bundle_snapshots) >= 1
