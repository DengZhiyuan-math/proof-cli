"""An imported result links to its ReferenceRecord (issue #91, ADR-0012 point 4).

The link is an optional, immutable `reference_id`, set when the node is created and
valid only on an imported_result naming an existing reference. The node's page, the
review card and `node show` show the citation. A Reference review binds the link, not
the citation's text: deleting the linked reference makes the review unverifiable,
editing its text doesn't.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _researcher import researcher
from _review_client import DirectClient
from proof_cli import proof_map
from proof_cli.cli import app
from proof_cli.exchange import export_exchange_bundle, import_exchange_bundle
from proof_cli.proof_map import ProofMapError, create_node, get_node, get_reference_review_state
from proof_cli.references import ReferenceRecord
from proof_cli.storage import ensure_project, get_reference, import_reference, store_reference

runner = CliRunner()

BW = ReferenceRecord(id="rudin", title="Principles of Mathematical Analysis", authors=["Walter Rudin"], year=1976, identifier="isbn:0-07-054235-X")


def _project(root: Path):
    store = ensure_project(root)
    import_reference(store, BW)
    return store


def _imported(store, node_id="ref_bw", **extra):
    return create_node(
        store, node_id=node_id, kind="imported_result", statement="Every bounded sequence in R^n has a convergent subsequence",
        source_locator="Theorem 3.6", source_version="3rd edition", **extra,
    )


def _delete_reference(store, reference_id):
    with store.connect() as conn:
        conn.execute("DELETE FROM reference_records WHERE id = ?", (reference_id,))
        conn.commit()


def _cli(*args):
    return runner.invoke(app, list(args))


# -- creating the link -------------------------------------------------------------------


def test_an_imported_result_can_link_an_existing_reference(tmp_path):
    store = _project(tmp_path)
    node = _imported(store, reference_id="rudin")
    assert node.reference_id == "rudin" and get_node(store, "ref_bw").reference_id == "rudin"


def test_a_node_without_a_reference_id_works_as_before(tmp_path):
    store = _project(tmp_path)
    node = _imported(store)
    assert node.reference_id is None
    assert proof_map.node_citation(store, node) is None
    # its binding is spelled exactly as before the link existed, so old reviews still count
    assert proof_map._interface_of(node) == proof_map._digest(
        ["imported_result", proof_map._normalize_whitespace(node.statement), node.source_locator, node.source_version]
    )
    researcher(store).decide_reference_review("ref_bw")
    assert get_reference_review_state(store, "ref_bw") == "reviewed"


def test_a_reference_id_on_a_local_node_is_refused(tmp_path):
    store = _project(tmp_path)
    for kind in ("theorem", "lemma", "claim"):
        with pytest.raises(ProofMapError) as refused:
            create_node(store, node_id=f"n_{kind}", kind=kind, statement="S", reference_id="rudin")
        assert refused.value.code == "REFERENCE_ID_NOT_IMPORTED_RESULT"
        assert get_node(store, f"n_{kind}") is None


def test_a_reference_id_naming_no_reference_is_refused(tmp_path):
    store = _project(tmp_path)
    with pytest.raises(ProofMapError) as refused:
        _imported(store, reference_id="nope")
    assert refused.value.code == "REFERENCE_NOT_FOUND"
    assert get_node(store, "ref_bw") is None


def test_the_cli_creates_the_link_and_refuses_with_stable_codes(tmp_path):
    _project(tmp_path)
    root = str(tmp_path)
    made = _cli("node", "create", "ref_bw", "imported_result", "Bolzano-Weierstrass", "--root", root,
                "--source-locator", "Theorem 3.6", "--source-version", "3rd edition", "--reference-id", "rudin", "--json")
    assert made.exit_code == 0, made.output
    assert json.loads(made.output)["data"]["reference_id"] == "rudin"

    local = _cli("node", "create", "lem", "lemma", "L", "--root", root, "--reference-id", "rudin", "--json")
    assert local.exit_code == 1 and json.loads(local.output)["error"]["code"] == "REFERENCE_ID_NOT_IMPORTED_RESULT"
    missing = _cli("node", "create", "ref_x", "imported_result", "X", "--root", root,
                   "--source-locator", "p. 1", "--source-version", "v1", "--reference-id", "nope", "--json")
    assert missing.exit_code == 1 and json.loads(missing.output)["error"]["code"] == "REFERENCE_NOT_FOUND"


def test_the_link_is_immutable(tmp_path):
    """No command edits it: `node` has no update, and the in-place write paths leave it alone."""
    store = _project(tmp_path)
    _imported(store, reference_id="rudin")
    commands = _cli("node", "--help").output
    assert not [name for name in ("update", "edit", "set", "link") if f" {name} " in commands]
    # correcting the citation is a new node, as for any imported result (#20)
    import_reference(store, BW.model_copy(update={"id": "rudin_4th", "title": "Principles, 4th ed."}))
    _imported(store, node_id="ref_bw_2", reference_id="rudin_4th")
    assert get_node(store, "ref_bw").reference_id == "rudin"


# -- showing the citation ----------------------------------------------------------------


def test_node_show_prints_the_citation(tmp_path):
    store = _project(tmp_path)
    _imported(store, reference_id="rudin")
    shown = _cli("node", "show", "ref_bw", "--root", str(tmp_path))
    assert shown.exit_code == 0, shown.output
    for text in ("rudin", "Principles of Mathematical Analysis", "Walter Rudin", "Theorem 3.6", "3rd edition"):
        assert text in shown.output

    data = json.loads(_cli("node", "show", "ref_bw", "--root", str(tmp_path), "--json").output)["data"]
    assert data["reference_id"] == "rudin"
    citation = data["citation"]
    assert citation["reference_id"] == "rudin" and citation["missing"] is False
    assert (citation["title"], citation["authors"], citation["locator"], citation["version"]) == (
        "Principles of Mathematical Analysis", ["Walter Rudin"], "Theorem 3.6", "3rd edition")


def test_node_show_says_when_the_citation_is_missing(tmp_path):
    store = _project(tmp_path)
    _imported(store, reference_id="rudin")
    _delete_reference(store, "rudin")
    shown = _cli("node", "show", "ref_bw", "--root", str(tmp_path))
    assert "citation missing" in shown.output
    data = json.loads(_cli("node", "show", "ref_bw", "--root", str(tmp_path), "--json").output)["data"]
    assert data["citation"]["missing"] is True and data["citation"]["title"] is None


def test_node_show_of_a_node_without_a_link_has_no_citation(tmp_path):
    store = _project(tmp_path)
    _imported(store)
    data = json.loads(_cli("node", "show", "ref_bw", "--root", str(tmp_path), "--json").output)["data"]
    assert data["reference_id"] is None and data["citation"] is None


# -- the Reference review binds the link, not the text ------------------------------------


def test_deleting_the_linked_reference_makes_the_review_unverifiable(tmp_path):
    store = _project(tmp_path)
    _imported(store, reference_id="rudin")
    researcher(store).decide_reference_review("ref_bw")
    assert get_reference_review_state(store, "ref_bw") == "reviewed"
    _delete_reference(store, "rudin")
    assert get_reference_review_state(store, "ref_bw") == "unverifiable"


def test_editing_the_citations_text_leaves_the_review_standing(tmp_path):
    store = _project(tmp_path)
    _imported(store, reference_id="rudin")
    researcher(store).decide_reference_review("ref_bw")
    store_reference(store, get_reference(store, "rudin").model_copy(update={"title": "Principles (corrected typo)", "authors": ["W. Rudin"], "year": 1977}))
    assert get_reference_review_state(store, "ref_bw") == "reviewed"


def test_the_binding_names_the_reference_id(tmp_path):
    store = _project(tmp_path)
    linked = _imported(store, reference_id="rudin")
    plain = _imported(store, node_id="ref_plain")
    # same statement and source, different link: different bindings
    assert proof_map._interface_of(linked) != proof_map._interface_of(plain.model_copy(update={"id": "ref_bw"}))


def test_a_reference_review_is_refused_while_the_citation_is_missing(tmp_path):
    store = _project(tmp_path)
    _imported(store, reference_id="rudin")
    _delete_reference(store, "rudin")
    with pytest.raises(ProofMapError) as refused:
        researcher(store).decide_reference_review("ref_bw")
    assert refused.value.code == "REFERENCE_NOT_FOUND"
    # finding it no longer callable still can be recorded
    researcher(store).decide_reference_review("ref_bw", "no-longer-callable")
    assert get_reference_review_state(store, "ref_bw") == "no-longer-callable"


# -- the proof map page ------------------------------------------------------------------


@pytest.fixture
def page(tmp_path: Path):
    store = _project(tmp_path)
    client = DirectClient(store)
    yield store, client
    client.app.close()


def _ok(response):
    status, body = response
    assert status == 200 and body["ok"], body
    return body["data"]


def _refused(response):
    status, body = response
    assert status >= 400 and not body["ok"], body
    return body["error"]["code"]


def test_the_pages_create_request_carries_the_link(page):
    store, client = page
    made = _ok(client.post("/api/nodes", {"node_id": "ref_bw", "kind": "imported_result", "statement": "BW",
                                          "source_locator": "Theorem 3.6", "source_version": "3rd", "reference_id": "rudin"}))
    assert made["reference_id"] == "rudin" and get_node(store, "ref_bw").reference_id == "rudin"
    assert _refused(client.post("/api/nodes", {"node_id": "lem", "kind": "lemma", "statement": "L", "reference_id": "rudin"})) == "REFERENCE_ID_NOT_IMPORTED_RESULT"
    assert _refused(client.post("/api/nodes", {"node_id": "ref_x", "kind": "imported_result", "statement": "X",
                                               "source_locator": "p", "source_version": "v", "reference_id": "nope"})) == "REFERENCE_NOT_FOUND"


def test_the_imported_results_page_and_its_review_card_carry_the_citation(page):
    store, client = page
    _imported(store, reference_id="rudin")
    view = _ok(client.get("/api/node/ref_bw"))
    assert view["citation"]["title"] == "Principles of Mathematical Analysis" and view["citation"]["missing"] is False
    (card,) = [item for item in _ok(client.get("/api/state"))["pending"] if item["node_id"] == "ref_bw"]
    assert card["citation"] == view["citation"]

    _delete_reference(store, "rudin")
    assert _ok(client.get("/api/node/ref_bw"))["citation"]["missing"] is True


def test_a_node_without_a_link_shows_no_citation_on_the_page(page):
    store, client = page
    _imported(store)
    assert _ok(client.get("/api/node/ref_bw"))["citation"] is None
    (card,) = _ok(client.get("/api/state"))["pending"]
    assert card["citation"] is None


# -- exchange ----------------------------------------------------------------------------


def test_exchange_round_trips_the_link(tmp_path):
    source = _project(tmp_path / "source")
    _imported(source, reference_id="rudin")
    bundle = export_exchange_bundle(source)
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, bundle)
    assert get_node(target, "ref_bw").reference_id == "rudin"
    assert proof_map.node_citation(target, get_node(target, "ref_bw"))["missing"] is False


def test_exchange_import_tolerates_a_missing_local_reference(tmp_path):
    source = _project(tmp_path / "source")
    _imported(source, reference_id="rudin")
    bundle = export_exchange_bundle(source).model_copy(update={"references": [], "reference_reviews": []})
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, bundle)
    node = get_node(target, "ref_bw")
    assert node.reference_id == "rudin"
    assert proof_map.node_citation(target, node)["missing"] is True
