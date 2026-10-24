"""What the Coordinator records of the researcher's words (ADR-0025 points 16-22; zeqome/proof-agents#47).

The Coordinator parses what the researcher says. What takes effect when said is recorded with the researcher's words
and its reading of them ("I read this as …"); an instruction for a node's agent is a redirect its next turn is briefed
with; a decision only the researcher's click makes is only proposed. A Challenge from before Challenges had a kind is
given one, once, as the Coordinator reads it. Synthetic projects only."""

from __future__ import annotations

from pathlib import Path

import pytest

from _proofs import submit_proof
from proof_cli.domain import Challenge
from proof_cli.node_states import node_states, stopped_by
from proof_cli.proof_map import (ProofMapError, classify_challenge, create_node, get_challenge, record_proposal, record_reading,
                                 record_redirect, record_redirects_given, work_log)
from proof_cli.rendering import _work_log_body
from proof_cli.storage import ensure_project, insert_challenge

GAP = "L5 第 2 步有漏洞，换成用归纳法"


def _refused(call) -> str:
    with pytest.raises(ProofMapError) as refused:
        call()
    return refused.value.code


def test_a_reading_a_redirect_and_a_proposal_show_in_the_nodes_log_with_the_researchers_words(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L5", kind="lemma", statement="L5 holds")
    submit_proof(store, "L5", claimant_id="claude-code", scoping_rationale="scoped", content="proof of L5")
    states = node_states(store, "L5")

    record_reading(store, "L5", by="coordinator", words=GAP, reading="我理解为：L5 的证明第 2 步有漏洞，只重做 L5")
    record_redirect(store, "L5", by="coordinator", words=GAP, text="第 2 步改用归纳法")
    record_proposal(store, "L5", by="coordinator", words="这个引理我信", reading="你相信 L5：验证要你在页面上点", kind="verification", decision="verify")

    entries = [e for e in work_log(store, "L5") if e["kind"] in ("reading", "redirect", "proposal")]
    assert [(e["kind"], e["by"], e["words"], e["role"]) for e in entries] == [
        ("reading", "coordinator", GAP, None), ("redirect", "coordinator", GAP, None), ("proposal", "coordinator", "这个引理我信", None)]
    assert (entries[1]["text"], entries[2]["decision_kind"], entries[2]["decision"], entries[2]["target_id"]) == (
        "第 2 步改用归纳法", "verification", "verify", "L5")
    redirect_id = entries[1]["id"]
    record_redirects_given(store, "L5", [redirect_id], turn="t1", role="prover", by="claude-code")
    (given,) = [e for e in work_log(store, "L5") if e["kind"] == "redirect-given"]
    assert (given["ids"], given["turn"], given["role"], _work_log_body(given)) == (
        [redirect_id], "t1", "prover", f"given the researcher's redirect ({redirect_id})")
    assert [_work_log_body(e) for e in entries] == [
        f"coordinator read “{GAP}” as: 我理解为：L5 的证明第 2 步有漏洞，只重做 L5",
        "coordinator: for the next turn — 第 2 步改用归纳法",
        "coordinator proposes verify (verification), for your click — 你相信 L5：验证要你在页面上点"]
    assert node_states(store, "L5") == states   # a proposal changes nothing: only the researcher's click does


def test_what_the_coordinator_records_is_refused_without_its_words_or_as_a_decision_it_cannot_propose(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L5", kind="lemma", statement="L5 holds")
    assert _refused(lambda: record_reading(store, "L5", by="coordinator", words=" ", reading="x")) == "COORDINATOR_WORDS_REQUIRED"
    assert _refused(lambda: record_redirect(store, "L5", by="coordinator", words=GAP, text=" ")) == "REDIRECT_EMPTY"
    assert _refused(lambda: record_proposal(store, "L5", by="coordinator", words="w", reading="r", kind="seal",
                                            decision="seal-maybe")) == "INVALID_PROPOSAL"
    assert _refused(lambda: record_proposal(store, "L5", by="coordinator", words="w", reading="r", kind="acceptance",
                                            decision="accept")) == "INVALID_PROPOSAL"
    assert _refused(lambda: record_reading(store, "NOPE", by="coordinator", words=GAP, reading="x")) == "NODE_NOT_FOUND"


def test_a_challenge_with_no_kind_is_given_one_once_and_its_node_reads_it(tmp_path: Path):
    """A Challenge from before kinds reads as against the statement, so the branch using its node waits (ADR-0025
    point 26); once the Coordinator reads it as against the proof, only its node is reworked."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="DOUBT", kind="claim", statement="DOUBT holds")
    create_node(store, node_id="USER", kind="lemma", statement="USER holds", dependencies=["DOUBT"])
    insert_challenge(store, Challenge(id="old-1", target_node_id="DOUBT", opened_by="claude-code", rationale="the bound in step 3 is off"))
    assert stopped_by(store, "USER") == ["DOUBT"]

    said = "old-1 说的是证明第 3 步，命题本身没问题"
    assert classify_challenge(store, "old-1", kind="proof", by="coordinator", words=said, reading="我理解为：针对证明").kind == "proof"
    assert get_challenge(store, "old-1").kind == "proof" and stopped_by(store, "USER") == []
    assert (node_states(store, "DOUBT").statement_layer, node_states(store, "DOUBT").proof_layer) == ("unchallenged", "incomplete")
    (entry,) = [e for e in work_log(store, "DOUBT") if e["kind"] == "challenge-classified"]
    assert (entry["challenge_id"], entry["against"], entry["words"], entry["by"]) == ("old-1", "proof", said, "coordinator")

    assert _refused(lambda: classify_challenge(store, "old-1", kind="statement", by="coordinator", words=said, reading="r")) == "CHALLENGE_KIND_SET"
    assert _refused(lambda: classify_challenge(store, "old-1", kind="maybe", by="coordinator", words=said, reading="r")) == "INVALID_CHALLENGE_KIND"
