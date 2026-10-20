"""Challenges carry a kind, take effect at once, and are withdrawn with a reason (ADR-0025 B, #277).

A Challenge is against a node's proof (its Proof layer goes back to incomplete; only that node is reworked) or against its
statement (its Statement layer becomes challenged as false; work stops under every node that uses it directly). Anyone
may raise one on any unsealed node, and nobody reviews it first.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.node_states import node_states, stopped_by
from proof_cli.proof_map import ProofMapError, create_node, get_challenge, get_node, open_challenge, restate_node, withdraw_challenge, work_log
from proof_cli.storage import ensure_project, update_proof_map_node


def _accepted(store, node_id: str) -> None:
    submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def _layers(store, node_id: str) -> tuple:
    states = node_states(store, node_id)
    return states.statement_layer, states.proof_layer, states.conclusion


def test_a_proof_challenge_is_raised_on_any_node_at_once_and_sends_its_proof_back(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    _accepted(store, "lem")
    challenge = open_challenge(store, "lem", kind="proof", opened_by="agent_v", rationale="step 2 skips a case")
    assert (challenge.kind, challenge.opened_by, challenge.version, challenge.rationale) == ("proof", "agent_v", 1, "step 2 skips a case")
    assert _layers(store, "lem") == ("unchallenged", "incomplete", "uncertain")  # the verification lapses at once
    create_node(store, node_id="clm", kind="claim", statement="C")  # never Accepted, never reviewed: still challengeable
    assert open_challenge(store, "clm", opened_by="agent_v", rationale="no proof yet covers n = 0").kind == "proof"  # the default


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def test_a_statement_challenge_makes_it_challenged_as_false_and_an_agents_links_a_counterexample(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="mono", kind="lemma", statement="Every continuous f on [0,1] is monotone")
    create_node(store, node_id="cx", kind="claim", statement="f(x)=x(1-x) is continuous on [0,1] and not monotone")
    assert _code(lambda: open_challenge(store, "mono", kind="statement", opened_by="agent_v", rationale="false in general")) == "COUNTEREXAMPLE_REQUIRED"
    assert _code(lambda: open_challenge(store, "mono", kind="statement", counterexample="mono", opened_by="agent_v", rationale="r")) == "INVALID_COUNTEREXAMPLE"
    challenge = open_challenge(store, "mono", kind="statement", counterexample="cx", opened_by="agent_v", rationale="x(1-x) rises then falls")
    assert (challenge.kind, challenge.counterexample_id) == ("statement", "cx")
    assert _layers(store, "mono") == ("challenged-as-false", "incomplete", "uncertain")
    assert _layers(store, "cx")[0] == "unchallenged"  # an ordinary proposition, checked as one
    create_node(store, node_id="other", kind="lemma", statement="O")
    mine = open_challenge(store, "other", kind="statement", opened_by="human", rationale="I doubt the bound")  # the researcher's needs none
    assert (mine.kind, mine.counterexample_id) == ("statement", None)
    assert _code(lambda: open_challenge(store, "other", kind="both", opened_by="human")) == "INVALID_CHALLENGE_KIND"


def test_a_sealed_node_refuses_a_challenge(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="imp", kind="imported_result", statement="I", source_locator="Theorem 1", source_version="v1")
    researcher(store).decide_reference_review("imp", "no-longer-callable")  # sealed false, until seal lines exist (#279)
    assert _code(lambda: open_challenge(store, "imp", opened_by="agent_v", rationale="the source has a gap")) == "NODE_SEALED"


def test_who_may_withdraw_a_challenge_and_its_reason_is_in_the_work_log(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    theirs = open_challenge(store, "lem", opened_by="agent_v", rationale="step 2 skips a case")
    mine = open_challenge(store, "lem", kind="statement", opened_by="human", rationale="I doubt it for n = 1")
    assert _code(lambda: withdraw_challenge(store, mine.id, by="agent_p", reason="n = 1 is covered")) == "RESEARCHERS_CHALLENGE"
    assert _code(lambda: withdraw_challenge(store, theirs.id, by="agent_p", reason=" ")) == "WITHDRAW_REASON_REQUIRED"
    withdrawn = withdraw_challenge(store, theirs.id, by="agent_p", reason="step 2 is case (b) of the lemma before")
    assert (withdrawn.status.value, withdrawn.withdrawn_by, withdrawn.withdrawal_reason) == ("withdrawn", "agent_p", "step 2 is case (b) of the lemma before")
    assert _code(lambda: withdraw_challenge(store, theirs.id, by="agent_p", reason="again")) == "CHALLENGE_NOT_OPEN"
    assert _layers(store, "lem")[0] == "challenged-as-false"  # the researcher's still stands
    (entry,) = [e for e in work_log(store, "lem") if e["kind"] == "challenge-withdrawn"]  # what the next briefing reads
    assert (entry["by"], entry["challenge_id"], entry["reason"]) == ("agent_p", theirs.id, "step 2 is case (b) of the lemma before")
    raised = [e for e in work_log(store, "lem") if e["kind"] == "challenge"]
    assert [(e["by"], e["against"]) for e in raised] == [("agent_v", "proof"), ("human", "statement")]
    withdraw_challenge(store, mine.id, by="human", reason="I checked n = 1")
    assert _layers(store, "lem")[0] == "unchallenged"
    other = open_challenge(store, "lem", opened_by="agent_v", rationale="the constant looks off")
    assert withdraw_challenge(store, other.id, by="human", reason="not a problem: the constant is never used").status.value == "withdrawn"


def test_a_restatement_supersedes_a_proof_gap_and_a_statement_challenge_follows_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="For every n >= 0, P(n)", created_by="agent_p")
    create_node(store, node_id="cx", kind="claim", statement="P(0) fails")
    gap = open_challenge(store, "lem", opened_by="agent_v", rationale="n = 0 is not covered")
    doubt = open_challenge(store, "lem", kind="statement", counterexample="cx", opened_by="agent_v", rationale="P(0) fails")
    restate_node(store, "lem", statement="For every n >= 1, P(n)", reason="n = 0 is false", by="agent_p")
    assert get_challenge(store, gap.id).status.value == "superseded"  # computed: the proof it was about is of the old statement
    assert get_challenge(store, doubt.id).status.value == "open"  # it follows the statement to the new version
    assert _layers(store, "lem")[0] == "challenged-as-false"
    later = open_challenge(store, "lem", opened_by="agent_v", rationale="n = 1 is not covered either")
    assert get_challenge(store, later.id).status.value == "open"  # raised after the restatement: about this version


def test_a_statement_challenge_stops_the_branch_under_each_direct_user_and_nothing_beside_it(tmp_path: Path):
    # ADR-0025 point 6: A uses U1 and U2, and U1 uses N and S; N challenged as false stops all of U1's branch, S
    # included; U2 goes on; A is uncertain and waits
    store = ensure_project(tmp_path)
    for node_id, dependencies in (("N", []), ("S", []), ("U1", ["N", "S"]), ("U2", []), ("A", ["U1", "U2"])):
        create_node(store, node_id=node_id, kind="theorem" if node_id == "A" else "claim", statement=node_id, dependencies=dependencies)
    create_node(store, node_id="cx", kind="claim", statement="a counterexample to N")
    open_challenge(store, "S", opened_by="agent_v", rationale="a gap in S's proof")  # against a proof: only S is reworked
    assert all(stopped_by(store, node_id) == [] for node_id in ("A", "U1", "U2", "N", "S"))
    open_challenge(store, "N", kind="statement", counterexample="cx", opened_by="agent_v", rationale="cx refutes N")
    assert {node_id: stopped_by(store, node_id) for node_id in ("A", "U1", "U2", "N", "S", "cx")} == {
        "A": [], "U1": ["N"], "U2": [], "N": ["N"], "S": ["N"], "cx": []}
    assert node_states(store, "A").conclusion == "uncertain"


def test_the_cli_raises_either_kind_withdraws_one_and_says_what_a_challenge_stops(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="N")
    create_node(store, node_id="U1", kind="claim", statement="U1", dependencies=["N"])
    create_node(store, node_id="cx", kind="claim", statement="a counterexample to N")

    def run(*args: str, ok: bool = True) -> dict:
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"])
        envelope = json.loads(result.output)
        assert (result.exit_code == 0) == ok, result.output
        return envelope["data"] if ok else envelope["error"]

    refused = run("challenge", "open", "N", "--kind", "statement", "--opened-by", "agent_v", "--rationale", "r", ok=False)
    assert refused["code"] == "COUNTEREXAMPLE_REQUIRED"
    raised = run("challenge", "open", "N", "--kind", "statement", "--counterexample", "cx", "--opened-by", "agent_v", "--rationale", "cx refutes N")
    assert (raised["kind"], raised["counterexample_id"], raised["status"]) == ("statement", "cx", "open")
    assert run("node", "show", "U1")["stopped_by"] == ["N"]
    assert {node["id"]: node["stopped_by"] for node in run("node", "list")} == {"N": ["N"], "U1": ["N"], "cx": []}
    assert run("challenge", "open", "U1", "--opened-by", "agent_v", "--rationale", "a gap")["kind"] == "proof"
    withdrawn = run("challenge", "withdraw", raised["id"], "--reason", "cx misreads N's hypothesis", "--by", "agent_p")
    assert (withdrawn["status"], withdrawn["withdrawn_by"], withdrawn["withdrawal_reason"]) == ("withdrawn", "agent_p", "cx misreads N's hypothesis")
    assert run("node", "show", "U1")["stopped_by"] == []


def test_an_agents_challenge_lapses_a_verification_for_good_and_withdrawing_it_restores_nothing(tmp_path: Path):
    # ADR-0025 point 13: the verification lapses at once; it comes back only by the researcher's click (#279) or a new one
    store = ensure_project(tmp_path)
    for node_id in ("L", "M", "R", "D"):
        create_node(store, node_id=node_id, kind="lemma", statement=node_id)
        _accepted(store, node_id)
    gap = open_challenge(store, "L", opened_by="agent_v", rationale="step 2 skips a case")
    withdraw_challenge(store, gap.id, by="agent_p", reason="step 2 is case (b)")
    assert _layers(store, "L") == ("unchallenged", "incomplete", "uncertain")
    create_node(store, node_id="cx", kind="claim", statement="a counterexample to M")
    open_challenge(store, "M", kind="statement", counterexample="cx", opened_by="agent_v", rationale="cx refutes M")
    assert _layers(store, "M") == ("challenged-as-false", "incomplete", "uncertain")
    mine = open_challenge(store, "R", opened_by="human", rationale="I want to recheck the constant")  # the researcher's own doubt
    withdraw_challenge(store, mine.id, by="human", reason="the constant is fine")
    assert _layers(store, "R") == ("unchallenged", "expert-verified", "verified-true")
    dismissed = open_challenge(store, "D", opened_by="agent_v", rationale="a doubt")
    researcher(store).dismiss_challenge(dismissed.id, rationale="not a problem")  # the researcher's click on the page
    assert _layers(store, "D") == ("unchallenged", "expert-verified", "verified-true")


def test_a_reviewed_imported_result_an_agent_challenged_is_checks_passed_again_not_verified(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="imp", kind="imported_result", statement="I", source_locator="Theorem 1", source_version="v1")
    researcher(store).decide_reference_review("imp")
    doubt = open_challenge(store, "imp", opened_by="agent_v", rationale="the source assumes more")
    withdraw_challenge(store, doubt.id, by="agent_p", reason="it does not")
    assert _layers(store, "imp") == ("unchallenged", "checks-passed", "true")


def test_an_unrelated_cycle_in_a_hand_edited_map_never_breaks_a_healthy_nodes_read(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="good", kind="claim", statement="G")
    create_node(store, node_id="a", kind="claim", statement="a")
    create_node(store, node_id="b", kind="claim", statement="b", dependencies=["a"])
    update_proof_map_node(store, get_node(store, "a").model_copy(update={"dependencies": ["b"]}))  # a <- b <- a
    open_challenge(store, "a", kind="statement", opened_by="human", rationale="a doubt on the cycle")

    def run(*args: str) -> tuple[int, dict]:
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"])
        return result.exit_code, json.loads(result.output)

    code, shown = run("node", "show", "good")
    assert code == 0 and shown["data"]["stopped_by"] == [] and shown["data"]["conclusion"] == "uncertain"
    code, refused = run("node", "show", "a")
    assert code == 1 and refused["error"]["code"] == "DEPENDENCY_CYCLE" and refused["error"]["cycle"] == ["a", "b", "a"]
