"""ADR-0022 point 3 on the page (proof-web#9): an agent's imported result meets no Trust rule, so it waits in the review
queue as unreviewed; its own Reference review is made cheap. Beside it the page shows each rule it would meet had the
researcher imported it, and every "unchecked against the source" mark a Verifier left on what rests on it, naming the
dependent, its snapshot and whether that snapshot is current. The rationale is prefilled from the rules."""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _review_client import DirectClient
from proof_cli.proof_map import add_dependency, create_node, decide_trust_rule, remove_dependency, get_reference_review_state, record_evidence_check
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference
from proof_web.review_queue import source_marks

DOI = ReferenceRecord(id="paper", title="A bound", year=2020, source_type=ReferenceSourceType.research_paper, identifier="10.1000/example")
MARK = "R: unchecked against the source; the cited work cannot be reached"


@pytest.fixture
def store(tmp_path: Path):
    store = ensure_project(tmp_path)
    import_reference(store, DOI)
    decide_trust_rule(store, "dois", "declare", conditions=[{"kind": "identifier_has_doi"}],
                      reviewer="Researcher <researcher@example.org>", rationale="a DOI is a published source")
    return store


def _checked(store, node_id, note, version_text="proof"):
    proof = submit_proof(store, node_id, claimant_id="prover-1", scoping_rationale="scoped", content=f"{version_text} of {node_id}")
    record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", notes=note)
    return proof


def test_a_reader_import_under_a_doi_rule_waits_unreviewed_with_the_rule_it_would_meet_and_its_dependents_marks(store):
    create_node(store, node_id="R", kind="imported_result", statement="Bound", reference_id="paper", source_locator="Theorem 1",
                source_version="v1", created_by="reader-1")
    create_node(store, node_id="R2", kind="imported_result", statement="Other", source_locator="arXiv:other", source_version="v1", created_by="reader-1")
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader-1")
    create_node(store, node_id="M", kind="lemma", statement="M", dependencies=["R", "R2"], created_by="reader-1")
    _checked(store, "L", MARK)                       # snapshot v1, superseded below
    _checked(store, "L", "no objections", "again")   # snapshot v2, current: no mark
    _checked(store, "M", "R2: unchecked against the source")   # M rests on two imports: the note names R2, not R
    assert get_reference_review_state(store, "R") == "unreviewed"
    client = DirectClient(store)
    try:
        state = client.get("/api/state")[1]["data"]
        card = next(item for item in state["pending"] if item["node_id"] == "R")
        assert "R" not in [item["node_id"] for item in state["trusted_by_rule"]]
        expected = {"would_meet_trust_rule": ["dois"],
                    "unchecked": [{"dependent": "L", "snapshot": 1, "current": False, "evidence_check": card["unchecked"][0]["evidence_check"],
                                   "outcome": "passed", "note": MARK}],
                    "rationale": "would meet trust rule dois had the researcher imported it; read against the source"}
        assert {key: card[key] for key in expected} == expected
        queued = next(item for item in client.get("/api/review-queue")[1]["data"]["items"] if (item["kind"], item.get("node_id")) == ("imported", "R"))
        assert {key: queued[key] for key in expected} == expected
        assert client.get("/api/node/R")[1]["data"]["import_review"] == expected
        other = client.get("/api/node/R2")[1]["data"]["import_review"]
        assert [(m["dependent"], m["current"]) for m in other["unchecked"]] == [("M", True)] and other["would_meet_trust_rule"] == []
    finally:
        client.app.close()


def test_a_researchers_rule_trusted_import_stays_in_the_rule_trusted_section(store):
    create_node(store, node_id="R", kind="imported_result", statement="Bound", reference_id="paper", source_locator="Theorem 1", source_version="v1")
    client = DirectClient(store)
    try:
        state = client.get("/api/state")[1]["data"]
        assert [item["node_id"] for item in state["trusted_by_rule"]] == ["R"] and all(item["node_id"] != "R" for item in state["pending"])
        assert client.get("/api/node/R")[1]["data"]["import_review"]["would_meet_trust_rule"] == []
    finally:
        client.app.close()


def _two_imports(store):
    for node_id in ("R", "R2"):
        create_node(store, node_id=node_id, kind="imported_result", statement=node_id, source_locator=f"source {node_id}",
                    source_version="v1", created_by="reader-1")


def _marked(store, node_id):
    return [(m["dependent"], m["snapshot"], m["current"]) for m in source_marks(store, node_id)]


def test_a_mark_is_read_sentence_by_sentence_and_one_naming_another_import_is_not_this_ones(store):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader-1")
    create_node(store, node_id="M", kind="lemma", statement="M", dependencies=["R", "R2"], created_by="reader-1")
    _checked(store, "L", "R2: unchecked against the source")    # L rests on R alone, but the mark names R2
    _checked(store, "M", "R: checked against the source.\nR2: unchecked against the source; source unavailable.")
    assert _marked(store, "R") == []
    assert _marked(store, "R2") == [("M", 1, True)]


@pytest.mark.parametrize("note", [
    "R2: unchecked against the source; R checked against the source.",
    "R: checked against the source; R2: unchecked against the source.",
])
def test_a_semicolon_keeps_each_imports_source_check_separate(store, note):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader-1")
    _checked(store, "L", note)
    assert _marked(store, "R") == []
    assert _marked(store, "R2") == [("L", 1, True)]


@pytest.mark.parametrize("note", [
    "R: checked against the source, whereas R2: unchecked against the source.",
    "R: checked against the source, but R2: unchecked against the source.",
    "R2: unchecked against the source, while R checked against the source.",
    "R: checked against the source, R2: unchecked against the source.",
    "R2: unchecked against the source, R checked against the source.",
])
def test_a_comma_keeps_each_imports_source_check_separate(store, note):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader-1")
    _checked(store, "L", note)
    assert _marked(store, "R") == []
    assert _marked(store, "R2") == [("L", 1, True)]


@pytest.mark.parametrize("abbreviation", ["e.g.", "i.e."])
def test_an_abbreviation_keeps_the_named_import_with_its_mark(store, abbreviation):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader-1")
    create_node(store, node_id="M", kind="lemma", statement="M", dependencies=["R2"], created_by="reader-1")
    for node_id in ("L", "M"):
        _checked(store, node_id, f"Unchecked against the source, {abbreviation} R2 could not be opened.")
    assert _marked(store, "R") == []
    assert _marked(store, "R2") == [("M", 1, True)]


def test_a_comma_between_import_names_keeps_the_joint_mark(store):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader-1")
    _checked(store, "L", "R, R2: unchecked against the source.")
    assert _marked(store, "R") == [("L", 1, True)]
    assert _marked(store, "R2") == [("L", 1, True)]


def test_a_snapshot_is_read_against_the_dependencies_it_froze_not_the_maps_current_edges(store):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader-1")
    create_node(store, node_id="M", kind="lemma", statement="M", dependencies=["R"], created_by="reader-1")
    _checked(store, "L", "unchecked against the source; source unavailable", "old")   # v1 rested on R alone
    add_dependency(store, "L", "R2")
    _checked(store, "L", "sources checked", "new")
    _checked(store, "M", "unchecked against the source", "old")                        # M v1 rested on R ...
    remove_dependency(store, "M", "R")                                                 # ... which M no longer does
    assert _marked(store, "R") == [("L", 1, False), ("M", 1, True)]
    assert _marked(store, "R2") == []


def test_a_snapshot_from_before_dependencies_were_frozen_is_read_against_the_nodes_current_ones(store):
    _two_imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader-1")
    _checked(store, "L", "unchecked against the source")
    with store.transaction() as conn:
        conn.execute("UPDATE candidate_proofs SET dependencies = NULL WHERE node_id = 'L'")
    assert _marked(store, "R") == [("L", 1, True)]
    add_dependency(store, "L", "R2")
    assert _marked(store, "R") == []    # unnamed, and the node now rests on two imports: no attribution


REVIEW = {"would_meet_trust_rule": ["dois"],
          "unchecked": [{"dependent": "lem_bound", "snapshot": 1, "current": False, "evidence_check": "ec_1", "outcome": "passed", "note": "ref_bw: unchecked against the source"},
                        {"dependent": "thm_main", "snapshot": 2, "current": True, "evidence_check": "ec_2", "outcome": "passed", "note": "unchecked against the source; no access"}],
          "rationale": "would meet trust rule dois had the researcher imported it; read against the source"}


def test_the_card_the_queue_and_the_node_page_show_the_rules_and_the_marks_and_prefill_the_rationale():
    from test_map_home import CITATION, PENDING, _home, _imported_page, _state
    from test_review_queue_page import MAP, _page

    card = {**PENDING[1], "citation": CITATION, **REVIEW}
    page = {**_imported_page(CITATION), "import_review": REVIEW,
            "decisions": [{"kind": "reference_review", "target_id": "ref_bw", "decision": "reference-review"}]}
    home, shown = _home(state=_state([card]), steps=[{"open": "ref_bw"}], nodes={"ref_bw": page})
    for text in (home["pendingRows"][0], shown["nodeSource"]):
        assert "would meet trust rule dois had you imported it" in text and "unchecked against the source by the Verifier of:" in text
        assert "lem_bound, snapshot v1 (superseded): ref_bw: unchecked against the source" in text
        assert "thm_main, snapshot v2: unchecked against the source; no access" in text
    assert shown["nodeDecisionRationales"] == [REVIEW["rationale"]]
    queue = {"departures": None, "items": [{"kind": "imported", "node_id": "R", "node_kind": "imported_result", "statement": "Bound", "depth": 0,
                                            "citation": None, **REVIEW}]}
    (listed,) = _page(map_nodes=MAP, queue=queue)
    assert "would meet trust rule dois" in listed["queue"][0]["text"] and "lem_bound, snapshot v1 (superseded)" in listed["queue"][0]["text"]
