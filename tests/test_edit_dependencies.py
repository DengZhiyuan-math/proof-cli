"""Editing a node's dependencies after it exists: add, remove, move an edge (story 38, issue #96).

A structural operation like Split: ungated, agent-reachable, the claimant's
unless taken over with `reassign`, and on an Accepted node only while an open
Challenge invites a revision. Pins are re-captured at the next request-review.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.proof_map import (
    ProofMapError,
    add_dependency,
    claim_node,
    create_node,
    get_acceptance_state,
    get_active_claim,
    get_blocked_reason,
    get_dependency_pin,
    get_frontier,
    get_node,
    get_workflow_state,
    list_challenges,
    move_dependency,
    open_challenge,
    remove_dependency,
    request_review,
)
from proof_cli.storage import ensure_project, list_events


def _accepted(store, node_id, **kwargs):
    create_node(store, node_id=node_id, kind="lemma", statement=node_id.upper(), **kwargs)
    submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


@pytest.fixture
def store(tmp_path: Path):
    return ensure_project(tmp_path)


def _frontier(store) -> set[str]:
    return {node.id for node in get_frontier(store)}


# -- add ----------------------------------------------------------------------------


def test_adding_a_dependency_appends_the_edge_and_records_an_event(store):
    create_node(store, node_id="a", kind="claim", statement="A")
    create_node(store, node_id="lem", kind="lemma", statement="L")
    assert "a" in _frontier(store)

    edit = add_dependency(store, "a", "lem", edited_by="agent_a")

    assert (edit.op, edit.dependency_id, edit.to) == ("add", "lem", None)
    assert get_node(store, "a").dependencies == ["lem"] == edit.node.dependencies
    # the new lemma isn't Accepted yet, so the node now waits on it
    assert get_workflow_state(store, "a") == "blocked" and "a" not in _frontier(store)
    event = list_events(store)[-1]
    assert (event.kind, event.entity_id) == ("proof_map_dependency_added", "a")
    assert event.payload["dependency_id"] == "lem" and event.payload["edited_by"] == "agent_a"
    assert event.payload["dependencies"] == {"before": [], "after": ["lem"]}


def test_adding_an_imported_result_as_a_dependency_is_fine(store):
    create_node(store, node_id="a", kind="claim", statement="A")
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    add_dependency(store, "a", "ref")
    assert get_node(store, "a").dependencies == ["ref"]


def test_adding_is_refused_for_a_missing_target_a_repeat_or_a_missing_node(store):
    create_node(store, node_id="a", kind="claim", statement="A")
    create_node(store, node_id="b", kind="claim", statement="B")
    assert _code(lambda: add_dependency(store, "a", "nope")) == "DEPENDENCY_NOT_FOUND"
    assert _code(lambda: add_dependency(store, "nope", "a")) == "NODE_NOT_FOUND"
    add_dependency(store, "a", "b")
    assert _code(lambda: add_dependency(store, "a", "b")) == "ALREADY_A_DEPENDENCY"
    assert get_node(store, "a").dependencies == ["b"]


def test_an_edge_that_would_close_a_cycle_is_refused(store):
    create_node(store, node_id="c", kind="claim", statement="C")
    create_node(store, node_id="b", kind="claim", statement="B", dependencies=["c"])
    create_node(store, node_id="a", kind="claim", statement="A", dependencies=["b"])

    with pytest.raises(ProofMapError) as caught:
        add_dependency(store, "c", "a")
    assert caught.value.code == "DEPENDENCY_CYCLE"
    assert caught.value.details["cycle"] == ["c", "a", "b", "c"]
    assert _code(lambda: add_dependency(store, "a", "a")) == "DEPENDENCY_CYCLE"
    assert get_node(store, "c").dependencies == []


def test_an_imported_result_takes_no_dependencies(store):
    create_node(store, node_id="a", kind="claim", statement="A")
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    assert _code(lambda: add_dependency(store, "ref", "a")) == "IMPORTED_RESULT_HAS_NO_DEPENDENCIES"
    assert _code(lambda: remove_dependency(store, "ref", "a")) == "IMPORTED_RESULT_HAS_NO_DEPENDENCIES"
    assert get_node(store, "ref").dependencies == []


# -- remove -------------------------------------------------------------------------


def test_removing_a_dependency_drops_the_edge_and_its_pin(store):
    create_node(store, node_id="lem", kind="lemma", statement="L")
    create_node(store, node_id="a", kind="claim", statement="A", dependencies=["lem"])
    submit_proof(store, "a", claimant_id="agent", scoping_rationale="scoped", content="uses lem")
    assert get_dependency_pin(store, "a", "lem") is not None
    assert get_workflow_state(store, "a") == "blocked"

    edit = remove_dependency(store, "a", "lem", edited_by="agent_a")

    assert edit.op == "remove" and get_node(store, "a").dependencies == []
    assert get_dependency_pin(store, "a", "lem") is None
    assert get_workflow_state(store, "a") == "review-needed"
    assert list_events(store)[-1].kind == "proof_map_dependency_removed"
    assert _code(lambda: remove_dependency(store, "a", "lem")) == "NOT_A_DEPENDENCY"


# -- move ---------------------------------------------------------------------------


def test_moving_a_parents_dependency_onto_its_child(store):
    _accepted(store, "x")
    create_node(store, node_id="y", kind="lemma", statement="Y")  # not Accepted
    create_node(store, node_id="p", kind="claim", statement="P", dependencies=["x", "y"])
    create_node(store, node_id="c", kind="claim", statement="C", derived_from="p")
    add_dependency(store, "p", "c")
    assert get_workflow_state(store, "p") == "blocked"
    assert {"c", "y"} <= _frontier(store)

    moved = move_dependency(store, "p", "x", to="c", edited_by="agent_a")
    assert (moved.op, moved.dependency_id, moved.to.id) == ("move", "x", "c")
    assert get_node(store, "p").dependencies == ["y", "c"] and get_node(store, "c").dependencies == ["x"]
    # x is Accepted: the child stays on the frontier, the parent still waits on its child
    assert "c" in _frontier(store) and get_workflow_state(store, "c") == "open"
    assert get_workflow_state(store, "p") == "blocked"

    move_dependency(store, "p", "y", to="c")
    # y isn't Accepted: now the child waits on it, and comes off the frontier
    assert get_node(store, "p").dependencies == ["c"] and get_node(store, "c").dependencies == ["x", "y"]
    assert get_workflow_state(store, "c") == "blocked" and get_blocked_reason(store, "c") == "not-accepted"
    assert "c" not in _frontier(store) and "p" not in _frontier(store)
    event = list_events(store)[-1]
    assert (event.kind, event.entity_id, event.payload["to"]) == ("proof_map_dependency_moved", "p", "c")
    assert event.payload["to_dependencies"] == {"before": ["x"], "after": ["x", "y"]}


def test_a_move_is_refused_unless_both_ends_are_dependencies_and_no_cycle_results(store):
    create_node(store, node_id="c", kind="claim", statement="C")
    create_node(store, node_id="x", kind="claim", statement="X", dependencies=["c"])
    create_node(store, node_id="other", kind="claim", statement="O")
    create_node(store, node_id="p", kind="claim", statement="P", dependencies=["x", "c"])

    assert _code(lambda: move_dependency(store, "p", "other", to="c")) == "NOT_A_DEPENDENCY"
    assert _code(lambda: move_dependency(store, "p", "x", to="other")) == "NOT_A_DEPENDENCY"
    assert _code(lambda: move_dependency(store, "p", "x", to="nope")) == "NODE_NOT_FOUND"
    assert _code(lambda: move_dependency(store, "p", "x", to="x")) == "SAME_NODE"
    # x already rests on c: c resting on x would be a cycle
    assert _code(lambda: move_dependency(store, "p", "x", to="c")) == "DEPENDENCY_CYCLE"
    assert get_node(store, "p").dependencies == ["x", "c"] and get_node(store, "c").dependencies == []


def test_a_move_onto_an_imported_result_is_refused(store):
    create_node(store, node_id="x", kind="claim", statement="X")
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    create_node(store, node_id="p", kind="claim", statement="P", dependencies=["x", "ref"])
    assert _code(lambda: move_dependency(store, "p", "x", to="ref")) == "IMPORTED_RESULT_HAS_NO_DEPENDENCIES"
    assert get_node(store, "p").dependencies == ["x", "ref"]


# -- whose edit it is ---------------------------------------------------------------


def test_a_node_someone_else_holds_is_theirs_to_edit_unless_taken_over(store):
    create_node(store, node_id="lem", kind="lemma", statement="L")
    create_node(store, node_id="a", kind="claim", statement="A")
    claim_node(store, "a", claimant_id="agent_b")

    assert _code(lambda: add_dependency(store, "a", "lem", edited_by="agent_a")) == "NOT_CLAIMANT"
    assert get_node(store, "a").dependencies == []
    add_dependency(store, "a", "lem", edited_by="agent_a", reassign=True)
    assert get_node(store, "a").dependencies == ["lem"]
    assert get_active_claim(store, "a").claimant_id == "agent_a"
    remove_dependency(store, "a", "lem", edited_by="agent_a")  # the holder's own edit


def test_a_move_onto_a_child_someone_else_holds_needs_reassign(store):
    create_node(store, node_id="x", kind="claim", statement="X")
    create_node(store, node_id="c", kind="claim", statement="C")
    create_node(store, node_id="p", kind="claim", statement="P", dependencies=["x", "c"])
    claim_node(store, "c", claimant_id="agent_b")
    assert _code(lambda: move_dependency(store, "p", "x", to="c", edited_by="agent_a")) == "NOT_CLAIMANT"
    assert get_node(store, "p").dependencies == ["x", "c"]
    move_dependency(store, "p", "x", to="c", edited_by="agent_a", reassign=True)
    assert get_active_claim(store, "c").claimant_id == "agent_a"


# -- Accepted and Rejected nodes ----------------------------------------------------


def test_an_accepted_node_is_edited_only_under_an_open_challenge(store):
    create_node(store, node_id="lem", kind="lemma", statement="L")
    _accepted(store, "a")

    assert _code(lambda: add_dependency(store, "a", "lem")) == "NODE_ACCEPTED"
    assert get_node(store, "a").dependencies == [] and get_acceptance_state(store, "a") == "accepted"

    challenge = open_challenge(store, "a", opened_by="agent_x", rationale="uses L without saying so")
    add_dependency(store, "a", "lem", edited_by="agent_a")
    # the Acceptance was made on other dependencies, so it stops counting until the revision is decided
    assert get_acceptance_state(store, "a") == "unverifiable"
    remove_dependency(store, "a", "lem")  # still under the Challenge: further edits allowed
    add_dependency(store, "a", "lem")

    submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof of lem")
    researcher(store).decide_acceptance("lem", "accept")
    # pins are captured at the next request-review, even when the proof text itself is unchanged
    request_review(store, "a", requested_by="agent_a", rationale="now cites L")
    assert get_dependency_pin(store, "a", "lem").pinned_version == 1
    researcher(store).decide_acceptance("a", "accept")
    assert get_acceptance_state(store, "a") == "accepted"
    assert list_challenges(store, target_node_id="a")[0].id == challenge.id
    assert list_challenges(store, target_node_id="a")[0].status.value != "open"


def test_a_rejected_node_is_not_edited(store):
    create_node(store, node_id="lem", kind="lemma", statement="L")
    create_node(store, node_id="r", kind="claim", statement="R")
    submit_proof(store, "r", claimant_id="agent", scoping_rationale="scoped", content="bad")
    researcher(store).decide_acceptance("r", "reject")
    assert _code(lambda: add_dependency(store, "r", "lem")) == "NODE_REJECTED"


def test_a_snapshot_awaiting_review_is_decided_only_against_the_dependencies_it_pinned(store):
    _accepted(store, "lem")
    create_node(store, node_id="a", kind="claim", statement="A")
    submit_proof(store, "a", claimant_id="agent", scoping_rationale="scoped", content="proof")
    add_dependency(store, "a", "lem")
    assert get_workflow_state(store, "a") == "review-needed"

    assert _code(lambda: researcher(store).decide_acceptance("a", "accept")) == "DEPENDENCIES_CHANGED"
    request_review(store, "a", requested_by="agent", rationale="re-pinned")
    researcher(store).decide_acceptance("a", "accept")
    assert get_acceptance_state(store, "a") == "accepted"


def test_a_challenged_accepted_node_with_a_dependency_removed_can_be_re_reviewed(store):
    """PR #106 review (a): removing the edge also drops its pin, so the pins alone can't tell that it changed."""
    _accepted(store, "lem")
    _accepted(store, "a", dependencies=["lem"])
    open_challenge(store, "a", opened_by="agent_x", rationale="doesn't need L")
    remove_dependency(store, "a", "lem")
    assert get_acceptance_state(store, "a") == "unverifiable"

    snapshot = request_review(store, "a", requested_by="agent", rationale="proved without L")
    assert snapshot.version == 2 and snapshot.dependencies == []
    researcher(store).decide_acceptance("a", "accept")
    assert get_acceptance_state(store, "a") == "accepted"


def test_a_snapshot_awaiting_review_is_not_decided_once_a_dependency_is_removed(store):
    """PR #106 review (b): the old snapshot was made on the removed edge, so it can't be Accepted as it stands."""
    _accepted(store, "lem")
    create_node(store, node_id="a", kind="claim", statement="A", dependencies=["lem"])
    first = submit_proof(store, "a", claimant_id="agent", scoping_rationale="scoped", content="uses L")
    assert first.dependencies == ["lem"]
    remove_dependency(store, "a", "lem")

    assert _code(lambda: researcher(store).decide_acceptance("a", "accept")) == "DEPENDENCIES_CHANGED"
    request_review(store, "a", requested_by="agent", rationale="re-pinned")
    researcher(store).decide_acceptance("a", "accept")
    assert get_acceptance_state(store, "a") == "accepted"


def test_moving_a_dependency_away_also_needs_a_new_snapshot_of_the_parent(store):
    _accepted(store, "x")
    create_node(store, node_id="c", kind="claim", statement="C")
    create_node(store, node_id="p", kind="claim", statement="P", dependencies=["x", "c"])
    submit_proof(store, "p", claimant_id="agent", scoping_rationale="scoped", content="p")
    move_dependency(store, "p", "x", to="c")
    # the parent's snapshot was made on x directly; a new one is requested even with the same text
    assert request_review(store, "p", requested_by="agent", rationale="x now via c").version == 2


# -- a split child's own dependencies (PR #104) -------------------------------------


def test_a_split_child_keeps_the_dependencies_its_spec_names(store):
    from proof_cli.proof_map import split_node

    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    create_node(store, node_id="p", kind="claim", statement="P")
    (child,) = split_node(store, "p", [{"id": "c1", "statement": "C1", "dependencies": ["ref"]}])
    assert child.dependencies == ["ref"] == get_node(store, "c1").dependencies

    # validated like any dependency, and all or nothing
    assert _code(lambda: split_node(store, "p", [{"id": "c2", "statement": "C2", "dependencies": ["ghost"]}])) == "DEPENDENCY_NOT_FOUND"
    assert _code(lambda: split_node(store, "p", [{"id": "c3", "statement": "C3", "dependencies": ["p"]}])) == "DEPENDENCY_CYCLE"
    create_node(store, node_id="q", kind="claim", statement="Q", dependencies=["p"])
    assert _code(lambda: split_node(store, "p", [{"id": "c4", "statement": "C4", "dependencies": ["q"]}])) == "DEPENDENCY_CYCLE"
    assert get_node(store, "c2") is None and get_node(store, "c3") is None and get_node(store, "c4") is None
    assert get_node(store, "p").dependencies == ["c1"]


# -- the CLI: `proof node depend` ---------------------------------------------------

import json

from typer.testing import CliRunner

from _review_client import DirectClient
from proof_cli.cli import app

runner = CliRunner()


def _depend(root: Path, node_id: str, *args: str, json_output: bool = True):
    return runner.invoke(app, ["node", "depend", node_id, *args, "--root", str(root), *(["--json"] if json_output else [])])


def test_cli_add_remove_and_move_under_json(store):
    root = store.root
    for node_id in ("x", "c", "p"):
        create_node(store, node_id=node_id, kind="claim", statement=node_id.upper())

    added = _depend(root, "p", "--add", "x", "--by", "agent_a")
    assert added.exit_code == 0, added.output
    envelope = json.loads(added.stdout)
    assert (envelope["ok"], envelope["command"]) == (True, "node.depend")
    assert envelope["data"]["op"] == "add" and envelope["data"]["dependency_id"] == "x"
    assert envelope["data"]["node"]["dependencies"] == ["x"] and envelope["data"]["to"] is None

    _depend(root, "p", "--add", "c")
    moved = json.loads(_depend(root, "p", "--move", "x", "--to", "c").stdout)
    assert moved["data"]["op"] == "move"
    assert moved["data"]["node"]["dependencies"] == ["c"] and moved["data"]["to"]["dependencies"] == ["x"]

    removed = json.loads(_depend(root, "c", "--remove", "x").stdout)
    assert removed["data"]["op"] == "remove" and removed["data"]["node"]["dependencies"] == []


def test_cli_human_readable_output(store):
    create_node(store, node_id="x", kind="claim", statement="X")
    create_node(store, node_id="c", kind="claim", statement="C")
    create_node(store, node_id="p", kind="claim", statement="P", dependencies=["x", "c"])

    moved = _depend(store.root, "p", "--move", "x", "--to", "c", json_output=False)
    assert moved.exit_code == 0, moved.output
    assert "moved dependency x of p onto c" in moved.output
    refused = _depend(store.root, "p", "--remove", "x", json_output=False)
    assert refused.exit_code == 1 and "Error:" in refused.output and "not a dependency" in refused.output


@pytest.mark.parametrize("json_output", [True, False])
def test_cli_refusals_carry_stable_codes(store, json_output):
    create_node(store, node_id="b", kind="claim", statement="B")
    create_node(store, node_id="a", kind="claim", statement="A", dependencies=["b"])
    _accepted(store, "acc")
    claim_node(store, "b", claimant_id="agent_b")
    cases = [
        (("b", "--add", "a", "--reassign"), "DEPENDENCY_CYCLE"),
        (("a", "--add", "ghost"), "DEPENDENCY_NOT_FOUND"),
        (("acc", "--add", "a"), "NODE_ACCEPTED"),
        (("b", "--add", "acc", "--by", "agent_a"), "NOT_CLAIMANT"),
    ]
    for args, code in cases:
        result = _depend(store.root, *args, json_output=json_output)
        assert result.exit_code == 1, (args, result.output)
        if json_output:
            assert json.loads(result.stdout)["error"]["code"] == code
        else:
            assert "Error:" in result.output


def test_cli_names_exactly_one_edit(store):
    create_node(store, node_id="a", kind="claim", statement="A")
    for args in ((), ("--add", "x", "--remove", "y"), ("--move", "x")):
        result = _depend(store.root, "a", *args)
        assert result.exit_code == 2, args
        assert json.loads(result.stdout)["error"]["code"] == "USAGE_ERROR"


# -- the node panel: /api/node/<id>/depend ------------------------------------------


def test_the_node_panel_edits_dependencies_through_the_same_service(store):
    client = DirectClient(store)
    try:
        for node_id in ("x", "c", "p"):
            create_node(store, node_id=node_id, kind="claim", statement=node_id.upper())
        status, body = client.post("/api/node/p/depend", {"op": "add", "dependency": "x"})
        assert status == 200 and body["data"]["node"]["dependencies"] == ["x"], body
        client.post("/api/node/p/depend", {"op": "add", "dependency": "c"})
        status, body = client.post("/api/node/p/depend", {"op": "move", "dependency": "x", "to": "c"})
        assert status == 200 and get_node(store, "c").dependencies == ["x"], body
        status, body = client.post("/api/node/c/depend", {"op": "add", "dependency": "p"})
        assert status >= 400 and body["error"]["code"] == "DEPENDENCY_CYCLE"
        status, body = client.post("/api/node/c/depend", {"op": "frob", "dependency": "p"})
        assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
        create_node(store, node_id="held", kind="claim", statement="H")
        claim_node(store, "held", claimant_id="agent_b")
        status, body = client.post("/api/node/held/depend", {"op": "add", "dependency": "x"})
        assert body["error"]["code"] == "NOT_CLAIMANT"
        status, body = client.post("/api/node/held/depend", {"op": "add", "dependency": "x", "reassign": True})
        assert status == 200 and get_node(store, "held").dependencies == ["x"]
        status, body = client.post("/api/node/p/depend", {"op": "remove", "dependency": "c"})
        assert status == 200 and get_node(store, "p").dependencies == []
    finally:
        client.app.close()
