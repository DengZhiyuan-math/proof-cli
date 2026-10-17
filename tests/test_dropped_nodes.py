"""ADR-0023 point 4: a local node a dependency removal left with nothing resting on it is a historical route, as a
detached split Claim is. Core says which nodes those are, and which removal dropped each; Project Pursue's coverage
reads it through the host, so a Prover changing its route does not leave the Reader's Lemma blocking every Start."""

from pathlib import Path

from proof_cli.proof_map import add_dependency, create_node, dropped_nodes, remove_dependency
from proof_cli.storage import acting_as, ensure_project


def _map(tmp_path: Path):
    """thm → mid → lem, the Reader's Lemmas, and a proposal nothing ever rested on."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L", created_by="reader")
    create_node(store, node_id="mid", kind="lemma", statement="M", dependencies=["lem"], created_by="reader")
    create_node(store, node_id="thm", kind="theorem", statement="T", dependencies=["mid"], created_by="reader")
    create_node(store, node_id="proposal", kind="lemma", statement="P", created_by="reader")
    return store


def test_a_lemma_a_provers_turn_drops_is_named_with_the_removal_that_dropped_it(tmp_path: Path):
    store = _map(tmp_path)
    with acting_as("mid", "prover"):
        remove_dependency(store, "mid", "lem", edited_by="claude-code")

    dropped = dropped_nodes(store)

    assert set(dropped) == {"lem"}  # never the proposal: nothing ever rested on it
    assert {key: dropped["lem"][key] for key in ("from", "by", "role")} == {"from": "mid", "by": "claude-code", "role": "prover"}
    assert dropped["lem"]["at"]


def test_the_researchers_removal_outside_any_turn_names_no_role(tmp_path: Path):
    store = _map(tmp_path)
    remove_dependency(store, "mid", "lem")

    assert {key: dropped_nodes(store)["lem"][key] for key in ("from", "by", "role")} == {"from": "mid", "by": "human", "role": None}


def test_a_node_something_still_rests_on_is_not_dropped(tmp_path: Path):
    store = _map(tmp_path)
    create_node(store, node_id="other", kind="lemma", statement="O", dependencies=["lem"], created_by="reader")
    remove_dependency(store, "mid", "lem", edited_by="claude-code")
    assert dropped_nodes(store) == {}

    remove_dependency(store, "other", "lem", edited_by="claude-code")
    assert dropped_nodes(store)["lem"]["from"] == "other"  # the newest removal is the one that dropped it

    add_dependency(store, "mid", "lem", edited_by="claude-code")  # wired again: no longer a historical route
    assert dropped_nodes(store) == {}


def test_an_imported_result_is_never_dropped_coverage_never_counts_it(tmp_path: Path):
    store = _map(tmp_path)
    create_node(store, node_id="src", kind="imported_result", statement="S", source_locator="Thm 1", source_version="v1", created_by="reader")
    add_dependency(store, "mid", "src", edited_by="claude-code")
    remove_dependency(store, "mid", "src", edited_by="claude-code")
    assert dropped_nodes(store) == {}
