from pathlib import Path

from proof_cli.references import (
    ReferenceRecord,
    ReferenceReviewStatus,
    ReferenceSourceType,
    ReferenceTrustLevel,
)
from proof_cli.storage import (
    approve_reference,
    defer_reference,
    ensure_project,
    import_reference,
    list_events,
    list_reference_reviews,
    list_references,
    reject_reference,
)


def test_reference_record_round_trips_provenance_and_review_state():
    record = ReferenceRecord(
        id="ref_standard_1",
        title="Spectral Expansion Estimate",
        authors=["A. Researcher", "B. Analyst"],
        year=2024,
        source_type=ReferenceSourceType.standard_reference,
        origin="zbmath",
        bibliographic_source="zbmath",
        identifier="zb:2024.12345",
        url="https://example.test/spectral-expansion",
        notes="Classical estimate used as a reference lemma.",
        review_status=ReferenceReviewStatus.approved,
        trust_level=ReferenceTrustLevel.standard_reference,
        is_callable=True,
    )

    payload = record.model_dump(mode="json")
    reloaded = ReferenceRecord.model_validate_json(record.model_dump_json())

    assert payload["title"] == "Spectral Expansion Estimate"
    assert payload["authors"] == ["A. Researcher", "B. Analyst"]
    assert payload["year"] == 2024
    assert payload["source_type"] == "standard_reference"
    assert payload["origin"] == "zbmath"
    assert payload["bibliographic_source"] == "zbmath"
    assert payload["identifier"] == "zb:2024.12345"
    assert payload["url"] == "https://example.test/spectral-expansion"
    assert payload["notes"] == "Classical estimate used as a reference lemma."
    assert payload["review_status"] == "approved"
    assert payload["trust_level"] == "standard_reference"
    assert payload["is_callable"] is True
    assert reloaded == record


def test_reference_import_review_flow_persists_all_states_and_audit_trail(tmp_path: Path):
    store = ensure_project(tmp_path)

    candidate = import_reference(
        store,
        ReferenceRecord(
            id="ref_candidate",
            title="Candidate Lemma",
            authors=["C. Mathematician"],
            year=2022,
            source_type=ReferenceSourceType.research_paper,
            origin="arxiv",
            bibliographic_source="arxiv",
            identifier="arXiv:2201.00001",
            url="https://example.test/candidate",
            notes="Imported for review but not yet callable.",
        ),
    )

    approved_source = import_reference(
        store,
        ReferenceRecord(
            id="ref_approved",
            title="Standard Result",
            authors=["D. Expert"],
            year=2018,
            source_type=ReferenceSourceType.standard_reference,
            origin="springer",
            bibliographic_source="springer",
            identifier="doi:10.1000/standard",
            url="https://example.test/approved",
            notes="A standard reference for later use.",
        ),
    )
    approved = approve_reference(store, approved_source.id, confirmed=True, rationale="trusted standard result")
    assert approved.allowed is True

    rejected_source = import_reference(
        store,
        ReferenceRecord(
            id="ref_rejected",
            title="Irrelevant Result",
            authors=["E. Scientist"],
            year=2016,
            source_type=ReferenceSourceType.research_paper,
            origin="journal",
            bibliographic_source="journal",
            identifier="doi:10.1000/rejected",
            url="https://example.test/rejected",
            notes="Looks related but does not support the current theorem.",
        ),
    )
    rejected = reject_reference(store, rejected_source.id, confirmed=True, rationale="does not match the proof route")
    assert rejected.allowed is True

    deferred_source = import_reference(
        store,
        ReferenceRecord(
            id="ref_deferred",
            title="Promising but Unchecked",
            authors=["F. Scholar"],
            year=2020,
            source_type=ReferenceSourceType.research_paper,
            origin="preprint",
            bibliographic_source="arxiv",
            identifier="arXiv:2001.00002",
            url="https://example.test/deferred",
            notes="Potentially useful, but the assumptions still need manual checking.",
        ),
    )
    deferred = defer_reference(store, deferred_source.id, confirmed=True, rationale="needs assumption matching")
    assert deferred.allowed is True

    references = {reference.id: reference for reference in list_references(store)}
    assert references["ref_candidate"].review_status == ReferenceReviewStatus.candidate
    assert references["ref_candidate"].is_callable is False
    assert references["ref_approved"].review_status == ReferenceReviewStatus.approved
    assert references["ref_approved"].is_callable is True
    assert references["ref_approved"].trust_level == ReferenceTrustLevel.standard_reference
    assert references["ref_rejected"].review_status == ReferenceReviewStatus.rejected
    assert references["ref_rejected"].is_callable is False
    assert references["ref_deferred"].review_status == ReferenceReviewStatus.deferred
    assert references["ref_deferred"].is_callable is False

    reviews = list_reference_reviews(store)
    review_states = {review.review_status for review in reviews}
    assert ReferenceReviewStatus.candidate in review_states
    assert ReferenceReviewStatus.approved in review_states
    assert ReferenceReviewStatus.rejected in review_states
    assert ReferenceReviewStatus.deferred in review_states

    event_kinds = {event.kind for event in list_events(store)}
    assert "reference_imported" in event_kinds
    assert "reference_review_approved" in event_kinds
    assert "reference_review_rejected" in event_kinds
    assert "reference_review_deferred" in event_kinds

