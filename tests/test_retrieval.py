from pathlib import Path

from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.proof_state import set_current_context, set_current_theorem
from proof_cli.retrieval import RetrievalSourceKind, retrieve_candidates
from proof_cli.services import workspace_retrieval
from proof_cli.storage import ensure_project
from proof_cli.theorems import add_theorem


def test_retrieval_orders_project_local_before_external(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="local_1",
        kind="theorem",
        name="Project Lemma",
        statement="alpha implies beta",
        assumptions=["alpha"],
        exports=["beta"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        source_ref="internal/project",
    )
    add_theorem(
        store,
        theorem_id="imported_1",
        kind="theorem",
        name="Imported Lemma",
        statement="alpha implies gamma",
        assumptions=["alpha"],
        exports=["gamma"],
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        source_ref="doi:10.1000/imported",
    )
    set_current_theorem(store, "local_1")
    set_current_context(store, ["alpha"])

    report = retrieve_candidates(
        store,
        query="alpha gamma",
        external_candidates=[
            {
                "id": "ext_1",
                "title": "External Lemma",
                "summary": "A standard result about alpha and gamma.",
                "bibliographic_source": "zbmath",
            }
        ],
    )

    assert [step.source_kind for step in report.trace] == [
        RetrievalSourceKind.project_local,
        RetrievalSourceKind.imported_reference,
        RetrievalSourceKind.external_bibliographic,
    ]
    assert report.candidates[0].source_kind == RetrievalSourceKind.project_local
    assert report.candidates[-1].source_kind == RetrievalSourceKind.external_bibliographic
    assert report.candidates[0].rank == 1
    assert report.candidates[0].source_priority == 0
    assert report.candidates[-1].source_priority == 2
    assert report.candidates[0].payload["id"] == "local_1"


def test_workspace_retrieval_uses_current_context_and_serializes_payload(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_theorem(
        store,
        theorem_id="local_2",
        kind="lemma",
        name="Context Lemma",
        statement="A and B imply C",
        assumptions=["A", "B"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
        source_ref="internal/project",
    )
    set_current_theorem(store, "local_2")
    set_current_context(store, ["A", "B"])

    report = workspace_retrieval(
        tmp_path,
        external_candidates=[
            {
                "id": "ext_2",
                "title": "Context Lemma",
                "summary": "Matches the current project context.",
                "url": "https://example.test/ref",
            }
        ],
    )

    assert report.project_context.current_theorem == "local_2"
    assert report.project_context.current_context == ["A", "B"]

    payload = report.model_dump(mode="json")
    assert payload["source_order"] == [
        "project_local",
        "imported_reference",
        "external_bibliographic",
    ]
    assert payload["candidates"][0]["source_kind"] == "project_local"
    assert payload["trace"][2]["source_kind"] == "external_bibliographic"
