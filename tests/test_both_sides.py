"""A statement challenged as false is checked from both sides (ADR-0025 point 7; zeqome/proof-agents#49).

An agent's Challenge against a statement links its counterexample, an ordinary node whose statement gives its scope.
Both sides are worked: the counterexample's proof, and the challenged statement's proof, whose Verifier must say where
the counterexample fails. Whichever passes its check first decides: the counterexample's makes the statement false;
the statement's ends the Challenge as fixed. A counterexample decides only while its own statement is unchallenged, so
counterexamples that contradict each other in a cycle all stay uncertain. The two sides are worked while the rest of the
branch waits. Synthetic projects only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import checked_lines, proved
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.node_states import node_states, stopped_by
from proof_cli.proof_map import (
    RESEARCHER,
    ProofMapError,
    add_dependency,
    create_node,
    get_challenge,
    get_node,
    open_challenge,
    record_progress,
)
from proof_cli.storage import ensure_project
from proof_cli.vault import working_proof_path

AGENT = "claude-code"


def _refused(call) -> str:
    with pytest.raises(ProofMapError) as refused:
        call()
    return refused.value.code


def _passes(store, node_id: str, **fixed: str) -> dict:
    """The node's Verifier passes its proof, written with its complete Uses of dependencies when it has any."""
    if get_node(store, node_id).dependencies:
        working_proof_path(store.root, node_id).write_text(proved(store, node_id), encoding="utf-8")
    return record_progress(store, node_id, role="verifier", by=AGENT, verdict="passed", note="holds", fixed=dict(fixed) or None,
                           application_lines=checked_lines(store, node_id) or None)


def _layers(store, node_id: str) -> tuple[str, str, str]:
    states = node_states(store, node_id)
    return states.statement_layer, states.proof_layer, states.conclusion


@pytest.fixture
def branch(tmp_path: Path):
    """U rests on N and S; an agent challenges N's statement, with its counterexample X made in the same step."""
    store = ensure_project(tmp_path)
    for node_id in ("N", "S"):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds for every $n \\geq 1$")
    create_node(store, node_id="U", kind="lemma", statement="U holds", dependencies=["N", "S"])
    challenge = open_challenge(store, "N", kind="statement", opened_by=AGENT, rationale="N fails for n = 1",
                               counterexample="X", counterexample_statement="For $n = 1$, N fails: take the trivial group.")
    return store, challenge


def test_a_statement_challenge_made_with_its_counterexample_stops_the_branch_but_not_its_two_sides(branch):
    store, challenge = branch
    assert (get_node(store, "X").kind.value, get_node(store, "X").created_by) == ("claim", AGENT)
    assert get_challenge(store, challenge.id).counterexample_id == "X"
    assert _layers(store, "N") == ("challenged-as-false", "incomplete", "uncertain")
    assert stopped_by(store, "U") == ["N"] and stopped_by(store, "S") == ["N"]
    assert stopped_by(store, "N") == [] and stopped_by(store, "X") == []   # the two sides, worked while the branch waits


def test_the_counterexample_passing_first_makes_the_statement_false_until_its_check_stops_counting(branch):
    store, challenge = branch
    _passes(store, "X")
    assert _layers(store, "N") == ("false", "incomplete", "false")
    assert stopped_by(store, "U") == []   # a false dependency stops nothing: U needs a proof that does not use it
    assert node_states(store, "U").conclusion == "uncertain"
    assert _refused(lambda: _passes(store, "N", **{challenge.id: "the trivial group is excluded"})) == "INVALID_ENDING"

    open_challenge(store, "X", kind="proof", opened_by=AGENT, rationale="step 1 of X divides by zero")
    assert _layers(store, "N")[0] == "challenged-as-false" and stopped_by(store, "U") == ["N"]


def test_the_statement_passing_first_says_where_the_counterexample_fails_and_ends_the_challenge(branch):
    store, challenge = branch
    assert _refused(lambda: _passes(store, "N")) == "ENDINGS_REQUIRED"   # its Verifier must say where X fails
    _passes(store, "N", **{challenge.id: "X takes n = 1 in the trivial group, where N's hypothesis already fails"})
    assert get_challenge(store, challenge.id).status.value == "fixed"
    assert _layers(store, "N") == ("unchallenged", "checks-passed", "true") and stopped_by(store, "U") == []
    _passes(store, "X")   # too late: the statement's side decided first
    assert _layers(store, "N")[0] == "unchallenged"


def test_counterexamples_that_contradict_each_other_in_a_cycle_stay_uncertain_until_one_passes_saying_where_the_other_fails(tmp_path: Path):
    """Each is the other's counterexample, so each is challenged and neither decides; neither proof passes without its
    Verifier saying where the other fails, and the first that does decides, as on any statement Challenge."""
    store = ensure_project(tmp_path)
    for node_id in ("A", "B"):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds")
    on_a = open_challenge(store, "A", kind="statement", opened_by=AGENT, rationale="B contradicts A", counterexample="B")
    open_challenge(store, "B", kind="statement", opened_by=AGENT, rationale="A contradicts B", counterexample="A")
    assert [_layers(store, node_id)[0::2] for node_id in ("A", "B")] == [("challenged-as-false", "uncertain")] * 2
    assert _refused(lambda: _passes(store, "A")) == "ENDINGS_REQUIRED" and _refused(lambda: _passes(store, "B")) == "ENDINGS_REQUIRED"
    _passes(store, "A", **{on_a.id: "B's construction needs a prime the statement of A excludes"})
    assert (_layers(store, "A"), _layers(store, "B")[0::2]) == (("unchallenged", "checks-passed", "true"), ("false", "false"))


def test_a_counterexample_that_rests_on_its_target_or_is_made_twice_is_refused(branch):
    store, _ = branch
    create_node(store, node_id="Y", kind="claim", statement="Y", dependencies=["S"])
    assert _refused(lambda: open_challenge(store, "S", kind="statement", opened_by=AGENT, rationale="r", counterexample="Y")) == "COUNTEREXAMPLE_RESTS_ON_TARGET"
    assert _refused(lambda: open_challenge(store, "S", kind="statement", opened_by=AGENT, rationale="r", counterexample="X",
                                           counterexample_statement="again")) == "NODE_ALREADY_EXISTS"


def test_an_agent_raises_one_with_its_counterexample_in_one_command(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N holds")
    (tmp_path / "cx.md").write_text("For $n = 1$, N fails.", encoding="utf-8")
    result = CliRunner().invoke(app, ["challenge", "open", "N", "--kind", "statement", "--counterexample", "X", "--counterexample-statement-file",
                                      str(tmp_path / "cx.md"), "--opened-by", AGENT, "--rationale", "N fails for n = 1", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["counterexample_id"] == "X" and get_node(store, "X").statement == "For $n = 1$, N fails."


def test_a_statement_that_passed_its_check_before_the_challenge_is_worked_again_until_a_side_decides(tmp_path: Path):
    """Its old Verdict said nothing of the counterexample, so its proof's side is incomplete again, and so worked."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N holds")
    _passes(store, "N")
    challenge = open_challenge(store, "N", kind="statement", opened_by=AGENT, rationale="N fails for n = 1", counterexample="X",
                               counterexample_statement="For $n = 1$, N fails.")
    assert _layers(store, "N") == ("challenged-as-false", "incomplete", "uncertain")
    _passes(store, "N", **{challenge.id: "X's n = 1 is outside N's hypothesis"})
    assert _layers(store, "N") == ("unchallenged", "checks-passed", "true")


def test_what_the_two_sides_rest_on_is_worked_with_them_though_the_waiting_branch_uses_it_too(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id in ("D", "E", "S"):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds")
    create_node(store, node_id="N", kind="claim", statement="N holds", dependencies=["D"])
    create_node(store, node_id="X", kind="claim", statement="For $n = 1$, N fails.", dependencies=["E"])
    create_node(store, node_id="U", kind="lemma", statement="U holds", dependencies=["N", "D", "E", "S"])
    open_challenge(store, "N", kind="statement", opened_by=AGENT, rationale="N fails for n = 1", counterexample="X")
    assert stopped_by(store, "U") == ["N"] and stopped_by(store, "S") == ["N"]
    assert [stopped_by(store, node_id) for node_id in ("N", "D", "X", "E")] == [[], [], [], []]


def test_a_counterexample_decides_only_once_what_it_rests_on_holds(branch):
    store, _ = branch
    create_node(store, node_id="D", kind="claim", statement="D holds")
    add_dependency(store, "X", "D", edited_by="human")
    _passes(store, "X")
    assert _layers(store, "N")[0] == "challenged-as-false"   # X's conclusion is uncertain while D's is
    _passes(store, "D")
    assert _layers(store, "N")[0] == "false"


def test_a_counterexample_that_comes_to_rest_on_its_target_no_longer_decides(branch):
    """Sealed true, its conclusion is the researcher's absolute belief; resting on N, it could contradict N only by
    assuming N."""
    store, _ = branch
    create_node(store, node_id="Y", kind="claim", statement="Y holds")
    add_dependency(store, "X", "Y", edited_by="human")
    researcher(store).seal("X", True)
    assert _layers(store, "N")[0] == "false"
    add_dependency(store, "Y", "N", edited_by="human")
    assert _layers(store, "N")[0] == "challenged-as-false"


def test_counterexamples_resting_on_each_other_s_targets_leave_both_undecided(tmp_path: Path):
    """X, against A, rests on B; Y, against B, rests on A: each waits on the other's target, so neither decides."""
    store = ensure_project(tmp_path)
    for node_id in ("A", "B"):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds")
    for node_id, dependency in (("X", "B"), ("Y", "A")):
        create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds", dependencies=[dependency])
    open_challenge(store, "A", kind="statement", opened_by=AGENT, rationale="X contradicts A", counterexample="X")
    open_challenge(store, "B", kind="statement", opened_by=AGENT, rationale="Y contradicts B", counterexample="Y")
    _passes(store, "X")
    _passes(store, "Y")
    assert [_layers(store, node_id)[0::2] for node_id in ("A", "B")] == [("challenged-as-false", "uncertain")] * 2


def test_the_researcher_s_own_challenge_on_the_node_keeps_it_stopped_for_the_researcher(branch):
    store, _ = branch
    open_challenge(store, "N", kind="statement", opened_by=RESEARCHER, rationale="I doubt N for small n")
    assert stopped_by(store, "N") == ["N"] and stopped_by(store, "U") == ["N"]
