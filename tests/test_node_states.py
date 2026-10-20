"""A node's states and its conclusion (ADR-0025): one reading, from the records that hold them, never kept.

Seal, Statement layer, Proof layer and Assignee are read off their records, and the conclusion follows from them by
ADR-0025's table, never above the node's weakest dependency. Until the records later tickets add exist, today's
records are read as ADR-0025 point 26 maps them, read-only (#276).
"""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.node_states import conclusion, node_states
from proof_cli.proof_map import claim_node, create_node, get_acceptance_state, open_challenge, record_evidence_check
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference

RUDIN = ReferenceRecord(id="rudin", title="Principles of Mathematical Analysis", authors=["Walter Rudin"], year=1976,
                        source_type=ReferenceSourceType.textbook, identifier="isbn:0-07-054235-X")
TEXTBOOKS = [{"kind": "source_type_in", "values": ["textbook", "monograph", "standard_reference"]}]

TABLE = [
    # (seal, statement layer, proof layer) -> conclusion, ADR-0025 point 2
    (("sealed-true", "unchallenged", "incomplete"), "verified-true"),
    (("sealed-true", "challenged-as-false", "incomplete"), "verified-true"),
    (("sealed-false", "unchallenged", "expert-verified"), "false"),
    (("unsealed", "false", "expert-verified"), "false"),
    (("unsealed", "challenged-as-false", "expert-verified"), "uncertain"),
    (("unsealed", "unchallenged", "incomplete"), "uncertain"),
    (("unsealed", "unchallenged", "checks-passed"), "true"),
    (("unsealed", "unchallenged", "expert-verified"), "verified-true"),
]


@pytest.mark.parametrize(("states", "expected"), TABLE)
def test_each_row_of_the_conclusion_table(states, expected):
    assert conclusion(*states) == expected


def test_a_conclusion_is_never_above_its_weakest_dependency_and_a_false_one_makes_it_uncertain():
    verified = ("unsealed", "unchallenged", "expert-verified")
    assert conclusion(*verified, dependencies=["verified-true", "verified-true"]) == "verified-true"
    assert conclusion(*verified, dependencies=["verified-true", "true"]) == "true"
    assert conclusion(*verified, dependencies=["true", "uncertain"]) == "uncertain"
    assert conclusion(*verified, dependencies=["false"]) == "uncertain"  # it needs a proof that does not use it
    assert conclusion("unsealed", "false", "incomplete", dependencies=["verified-true"]) == "false"  # its own statement is false
    assert conclusion("sealed-true", "unchallenged", "incomplete", dependencies=["uncertain"]) == "verified-true"  # the seal covers what it rests on
    assert conclusion("sealed-false", "unchallenged", "incomplete", dependencies=["verified-true"]) == "false"


# -- the reading, over today's records (#276) ---------------------------------------------------------------------------


def _files(root: Path) -> dict[str, str]:
    """Every file of the project but SQLite's journal: what a read must leave as it was."""
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() and not path.name.endswith(("-wal", "-shm"))}


def _states(store, node_id: str) -> tuple:
    states = node_states(store, node_id)
    return states.seal, states.statement_layer, states.proof_layer, states.conclusion


def test_a_legacy_passed_verdict_alone_is_not_a_check_and_reading_writes_nothing(tmp_path: Path):
    # ADR-0025 point 26: a Verdict from before the switch is not a check under the new rules
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C")
    proof = submit_proof(store, "clm", claimant_id="agent", scoping_rationale="scoped", content="proof of clm")
    record_evidence_check(store, proof.id, "passed", run_by="prover-1/verifier", notes="no objections")
    before = _files(tmp_path)
    assert _states(store, "clm") == ("unsealed", "unchallenged", "incomplete", "uncertain")
    assert _files(tmp_path) == before


def test_the_assignee_is_whoever_holds_the_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm", kind="claim", statement="C")
    assert node_states(store, "clm").assignee is None
    claim_node(store, "clm", claimant_id="agent_a")
    assert node_states(store, "clm").assignee == "agent_a"


def _accepted(store, node_id: str) -> None:
    submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def test_a_verified_parent_rises_and_falls_with_its_dependency_with_no_action_on_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    import_reference(store, RUDIN)
    reviewer = researcher(store)
    create_node(store, node_id="imp", kind="imported_result", statement="Bolzano-Weierstrass",
                source_locator="Theorem 3.6", source_version="3rd edition", reference_id="rudin")
    create_node(store, node_id="thm", kind="theorem", statement="T", dependencies=["imp"])
    assert _states(store, "imp") == ("unsealed", "unchallenged", "checks-passed", "true")  # imported, not yet verified
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    _accepted(store, "thm")
    assert _states(store, "thm") == ("unsealed", "unchallenged", "expert-verified", "verified-true")

    reviewer.retire_trust_rule("textbooks", rationale="each citation reviewed after all")
    assert _states(store, "imp")[2:] == ("checks-passed", "true")
    assert _states(store, "thm") == ("unsealed", "unchallenged", "expert-verified", "true")  # capped by its dependency

    reviewer.decide_reference_review("imp")
    assert _states(store, "thm")[3] == "verified-true"  # it rose with no action on it

    reviewer.decide_reference_review("imp", "no-longer-callable")
    sealed = node_states(store, "imp")
    assert (sealed.seal, sealed.conclusion) == ("sealed-false", "false")
    assert _states(store, "thm")[3] == "uncertain"  # it needs a proof that does not use it


def test_an_open_legacy_challenge_and_a_rejection_read_challenged_as_false(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    create_node(store, node_id="clm", kind="claim", statement="C")
    _accepted(store, "lem")
    open_challenge(store, "lem", opened_by="agent", rationale="step 2 looks wrong")
    assert _states(store, "lem") == ("unsealed", "challenged-as-false", "expert-verified", "uncertain")
    submit_proof(store, "clm", claimant_id="agent", scoping_rationale="scoped", content="proof of clm")
    researcher(store).decide_acceptance("clm", "reject")
    assert _states(store, "clm") == ("unsealed", "challenged-as-false", "incomplete", "uncertain")


def test_node_show_node_list_and_frontier_give_the_states_beside_the_old_fields(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="held", kind="claim", statement="H")
    create_node(store, node_id="free", kind="claim", statement="F")
    claim_node(store, "held", claimant_id="agent_a")

    def run(*args: str) -> list | dict:
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)["data"]

    shown = run("node", "show", "held")
    assert {key: shown[key] for key in ("seal", "statement_layer", "proof_layer", "assignee", "conclusion")} == {
        "seal": "unsealed", "statement_layer": "unchallenged", "proof_layer": "incomplete", "assignee": "agent_a", "conclusion": "uncertain"}
    assert shown["workflow_state"] == "claimed"  # the old fields stay for their readers until #283 and #284
    listed = {node["id"]: node for node in run("node", "list")}
    assert listed["held"]["assignee"] == "agent_a" and listed["free"]["conclusion"] == "uncertain" and "workflow_state" in listed["free"]
    (ready,) = run("frontier")
    assert ready["id"] == "free" and (ready["proof_layer"], ready["assignee"]) == ("incomplete", None)


def test_a_verification_counts_for_its_own_version_only(tmp_path: Path):
    # ADR-0025 point 13: verified true is the researcher's word on that version; a newer one nobody verified is not
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    create_node(store, node_id="thm", kind="theorem", statement="T", dependencies=["lem"])
    _accepted(store, "lem")
    assert _states(store, "lem")[2:] == ("expert-verified", "verified-true")
    submit_proof(store, "lem", claimant_id="agent", scoping_rationale="a second proof", content="another proof of lem")
    assert get_acceptance_state(store, "lem") == "accepted"  # the legacy reading is unchanged
    assert _states(store, "lem")[2:] == ("incomplete", "uncertain")
    assert _states(store, "thm")[3] == "uncertain"


def test_a_chain_deeper_than_pythons_recursion_limit_is_read(tmp_path: Path):
    store = ensure_project(tmp_path)
    depth = 1500
    create_node(store, node_id="n0", kind="lemma", statement="base")
    for i in range(1, depth):
        create_node(store, node_id=f"n{i}", kind="lemma", statement=f"stmt {i}", dependencies=[f"n{i - 1}"])
    for args in (["node", "show", f"n{depth - 1}"], ["node", "list"]):
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"])
        assert result.exit_code == 0, result.output[-400:]
    assert node_states(store, f"n{depth - 1}").conclusion == "uncertain"
