from pathlib import Path

from proof_cli.references import (
    ReferenceRecord,
    ReferenceReviewStatus,
    ReferenceSourceType,
    ReferenceTrustLevel,
)
from proof_cli.storage import (
    ensure_project,
    import_reference,
    list_events,
    list_reference_reviews,
    list_references,
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


def test_references_arrive_as_candidates_and_nothing_agent_reachable_approves_them(tmp_path: Path):
    """Reference approval is retired (ADR-0001, #37): an imported reference is a
    candidate, and a source is trusted by Reference-reviewing its imported_result node."""
    from proof_cli import storage

    store = ensure_project(tmp_path)
    imported = import_reference(
        store,
        ReferenceRecord(id="ref_new", title="Some Lemma", authors=["A"], year=2024, source_type=ReferenceSourceType.research_paper, origin="arxiv"),
    )
    assert imported.review_status == ReferenceReviewStatus.candidate and not imported.is_callable
    for retired in ("review_reference", "approve_reference", "reject_reference", "defer_reference"):
        assert not hasattr(storage, retired)
