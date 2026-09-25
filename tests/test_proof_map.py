from pathlib import Path

import pytest

from proof_cli.domain import ProofMapNodeKind
from proof_cli.proof_map import ProofMapError, create_node, get_node, list_nodes, require_node
from proof_cli.storage import ensure_project


def test_create_and_get_node(tmp_path: Path):
    store = ensure_project(tmp_path)

    node = create_node(
        store,
        node_id="thm_main",
        kind=ProofMapNodeKind.theorem,
        statement="A implies B",
        assumptions=["A"],
    )

    assert node.kind == ProofMapNodeKind.theorem
    fetched = get_node(store, "thm_main")
    assert fetched is not None
    assert fetched.statement == "A implies B"
    assert fetched.assumptions == ["A"]


def test_get_node_missing_returns_none(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert get_node(store, "does_not_exist") is None


def test_require_node_missing_raises_node_not_found(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        require_node(store, "does_not_exist")
    assert exc_info.value.code == "NODE_NOT_FOUND"


def test_exactly_one_theorem_node_per_project(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm_one", kind="theorem", statement="First theorem")

    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="thm_two", kind="theorem", statement="Second theorem")
    assert exc_info.value.code == "DUPLICATE_THEOREM"

    # The rejected attempt must not have been persisted.
    assert get_node(store, "thm_two") is None


def test_multiple_lemmas_and_claims_are_allowed(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement="Lemma one")
    create_node(store, node_id="lem_2", kind="lemma", statement="Lemma two")
    create_node(store, node_id="clm_1", kind="claim", statement="Claim one")

    nodes = list_nodes(store)
    assert {node.id for node in nodes} == {"lem_1", "lem_2", "clm_1"}


def test_creating_duplicate_node_id_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="First attempt")

    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="clm_1", kind="claim", statement="Second attempt")
    assert exc_info.value.code == "NODE_ALREADY_EXISTS"


def test_display_label_has_no_effect_on_kind_or_identity(tmp_path: Path):
    store = ensure_project(tmp_path)
    labeled = create_node(
        store,
        node_id="lem_labeled",
        kind="lemma",
        statement="A labeled lemma",
        display_label="Proposition",
    )
    unlabeled = create_node(
        store,
        node_id="lem_unlabeled",
        kind="lemma",
        statement="An unlabeled lemma",
    )

    assert labeled.kind == unlabeled.kind == ProofMapNodeKind.lemma
    assert labeled.display_label == "Proposition"
    assert unlabeled.display_label == ""


def test_dependencies_are_stored_as_bare_edges(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_base", kind="lemma", statement="Base lemma")
    node = create_node(
        store,
        node_id="clm_dependent",
        kind="claim",
        statement="Depends on the base lemma",
        dependencies=["lem_base"],
    )
    assert node.dependencies == ["lem_base"]


def test_invalid_kind_raises_proof_map_error_not_a_bare_value_error(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id="clm_1", kind="proposition", statement="stmt")
    assert exc_info.value.code == "INVALID_KIND"
    assert get_node(store, "clm_1") is None


def test_dependency_on_nonexistent_node_is_rejected(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        create_node(
            store,
            node_id="clm_1",
            kind="claim",
            statement="Depends on a ghost",
            dependencies=["ghost_node"],
        )
    assert exc_info.value.code == "DEPENDENCY_NOT_FOUND"
    assert get_node(store, "clm_1") is None
