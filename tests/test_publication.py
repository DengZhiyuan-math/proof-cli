from __future__ import annotations

import json
from pathlib import Path

from proof_cli.domain import TheoremStatus, TrustLevel
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
from proof_cli.theorems import add_theorem


def test_publication_state_and_exports_round_trip(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)

    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Publication Claim",
        statement="A implies C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_supp",
        kind="lemma",
        name="Supplement Claim",
        statement="B implies C",
        assumptions=["B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    add_theorem(
        store,
        theorem_id="thm_internal",
        kind="lemma",
        name="Internal Claim",
        statement="C implies D",
        assumptions=["C"],
        exports=["D"],
        status=TheoremStatus.draft,
        trust_level=TrustLevel.temporary_admit,
    )

    set_publication_claim(
        store,
        "thm_main",
        readiness=PublicationReadiness.paper_ready,
        display_name="Main Publication Claim",
        title="A implies C",
        section_placement="Section 3",
        citation_kind=PublicationCitationKind.project_original,
    )
    set_publication_claim(
        store,
        "thm_supp",
        readiness=PublicationReadiness.supplement_ready,
        display_name="Supplement Claim",
        title="B implies C",
        section_placement="Appendix A",
        citation_kind=PublicationCitationKind.imported_reference,
    )
    set_publication_claim(
        store,
        "thm_internal",
        readiness=PublicationReadiness.internal_draft,
        display_name="Internal Claim",
        title="C implies D",
        internal_only=True,
    )

    record_citation_provenance(
        store,
        "thm_main",
        "ref_1",
        usage_type=PublicationCitationKind.project_original,
        citation_note="project-original contribution",
    )
    record_verification_summary(
        store,
        "thm_main",
        included_fragments=["frag_1"],
        summary="machine-checked support",
    )
    record_editorial_note(store, "thm_main", "tighten wording", section_label="Section 3")
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
