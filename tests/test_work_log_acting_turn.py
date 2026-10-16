"""Issue #227: what an agent does through `proof` keeps the turn it came from, whichever node's log shows it.

Several runs may act under one agent name at once (Pursue keeps two going). A shared action — a fog item near two
nodes, an Experiment on it, a Definition both name — shows in each of their work logs; its role must be the role of
the turn that did it, never the role of the turn running on the node being viewed. The agent's runtime names its
node and role (PROOF_AGENT_NODE, PROOF_AGENT_ROLE); `proof` writes them into the event. History written before
says nothing of it, nor does what the host writes outside `acting_as`: such an entry takes a role only when a
record ties it to one turn — it is about the viewed node and that node's turn is the only one running under the name.
A shared one, or one several running turns could have written, reads unknown; one whose actor no turn runs as, none.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import create_node, record_agent_turn, work_log
from proof_cli.storage import ensure_project

runner = CliRunner()
AGENT = "claude-code"


def _run(root: Path, *args: str, env=None):
    result = runner.invoke(app, [*args, "--root", str(root), "--json"], env=env or {})
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


def _turn(store, node: str, role: str, phase: str, turn: str):
    extra = {"job": 1, "session_id": f"s-{turn}"} if phase == "ended" else {}
    record_agent_turn(store, node, phase=phase, turn=turn, role=role, by=AGENT, provider="claude", **extra)


def _runtime(node: str, role: str) -> dict:
    return {"PROOF_AGENT_NAME": AGENT, "PROOF_AGENT_ROLE": role, "PROOF_AGENT_NODE": node}


def _two_nodes(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="lemma", statement="lemma A")
    create_node(store, node_id="B", kind="lemma", statement="lemma B")
    return store


def _fog(store, node: str) -> list[dict]:
    return [entry for entry in work_log(store, node) if entry["kind"] == "fog"]


def test_a_fog_item_one_turn_adds_near_two_nodes_carries_that_turns_role_in_both_logs(tmp_path: Path):
    store = _two_nodes(tmp_path)
    _turn(store, "A", "verifier", "started", "ta")
    _turn(store, "B", "prover", "started", "tb")
    _run(tmp_path, "fog", "add", "the two estimates may need the same constant", "--near", "A", "--near", "B", env=_runtime("B", "prover"))

    [in_a] = _fog(store, "A")
    [in_b] = _fog(store, "B")
    assert (in_a["by"], in_a["role"], in_a["from_node"]) == (AGENT, "prover", "B")
    assert (in_b["by"], in_b["role"]) == (AGENT, "prover") and "from_node" not in in_b


def test_a_shared_entry_naming_no_turn_reads_unknown_in_every_log_whenever_a_running_turn_acts_under_its_name(tmp_path: Path):
    from proof_cli.fog import add_fog

    store = _two_nodes(tmp_path)
    _turn(store, "A", "verifier", "started", "ta")
    add_fog(store, "only A's turn runs", near=["A"], created_by=AGENT)  # written before #227: no turn named
    _turn(store, "B", "prover", "started", "tb")
    add_fog(store, "both turns run", near=["A", "B"], created_by=AGENT)
    add_fog(store, "the researcher's hunch", near=["A", "B"], created_by="ada")

    shown = {node: [(e["text"], e["role"], e.get("role_unknown", False)) for e in _fog(store, node)] for node in ("A", "B")}
    assert shown["A"] == [("only A's turn runs", None, True), ("both turns run", None, True), ("the researcher's hunch", None, False)]
    assert shown["B"] == [("both turns run", None, True), ("the researcher's hunch", None, False)]


def test_an_experiment_and_a_definition_edit_by_one_turn_keep_its_role_in_every_log_that_shows_them(tmp_path: Path):
    from proof_cli.definitions import add_definition
    from proof_cli.fog import add_fog

    store = ensure_project(tmp_path)
    add_definition(store, "D", term="height", text="$\\operatorname{ht}(z)$", created_by=AGENT)
    create_node(store, node_id="A", kind="lemma", statement="lemma A", definitions=["D"], created_by=AGENT)
    create_node(store, node_id="B", kind="lemma", statement="lemma B", definitions=["D"], created_by=AGENT)
    fog = add_fog(store, "is the constant uniform?", near=["A", "B"], created_by="ada")
    _turn(store, "A", "verifier", "started", "ta")
    _turn(store, "B", "numerics", "started", "tb")
    _run(tmp_path, "fog", "experiment", "record", fog.id, "supports", "--summary", "checked up to 10^4", "--run-by", AGENT,
         env=_runtime("B", "numerics"))
    _run(tmp_path, "definition", "edit", "D", "--text", "$\\sup_\\gamma \\operatorname{Im}(\\gamma z)$", "--reason", "the sup was of the wrong quantity",
         env=_runtime("B", "numerics"))

    for node, from_node in (("A", "B"), ("B", None)):
        log = work_log(store, node)
        shared = [entry for entry in log if entry["kind"] in ("experiment", "definition-edited")]
        assert [(e["kind"], e["role"], e.get("from_node")) for e in shared] == [
            ("experiment", "numerics", from_node), ("definition-edited", "numerics", from_node)]


def test_the_acting_turn_stays_when_turns_end_the_same_agent_works_again_or_the_logs_are_read_in_another_order(tmp_path: Path):
    store = _two_nodes(tmp_path)
    _turn(store, "A", "verifier", "started", "ta")
    _turn(store, "B", "prover", "started", "tb")
    _run(tmp_path, "fog", "add", "a gap both proofs share", "--near", "A", "--near", "B", env=_runtime("B", "prover"))
    first = (_fog(store, "B"), _fog(store, "A"))
    _turn(store, "B", "prover", "ended", "tb")
    _turn(store, "A", "verifier", "ended", "ta")
    _turn(store, "A", "prover", "started", "ta2")  # the same agent, on A, in another role

    later = (_fog(store, "B"), _fog(store, "A"))
    assert later == first and (_fog(store, "A"), _fog(store, "B")) == (first[1], first[0])
    assert [(e["role"], e.get("from_node")) for e in later[1]] == [("prover", "B")]


def test_a_shared_entry_naming_no_turn_reads_unknown_even_when_only_another_nodes_turn_has_its_name(tmp_path: Path):
    from proof_cli.fog import add_fog

    store = _two_nodes(tmp_path)
    record_agent_turn(store, "A", phase="started", turn="ta", role="verifier", by="codex", provider="codex")
    _turn(store, "B", "prover", "started", "tb")
    add_fog(store, "written by the claude-code run", near=["A", "B"], created_by=AGENT)

    in_a, in_b = (_fog(store, node) for node in ("A", "B"))
    assert in_a == in_b and [(e["role"], e.get("role_unknown", False)) for e in in_a] == [(None, True)]


def test_the_researchers_own_commands_name_no_turn(tmp_path: Path):
    from proof_cli.storage import list_events

    store = _two_nodes(tmp_path)
    _turn(store, "B", "prover", "started", "tb")
    _run(tmp_path, "fog", "add", "the researcher's hunch", "--near", "A", "--near", "B")

    [event] = [e for e in list_events(store) if e.kind == "proof_fog_added"]
    assert "from_turn" not in event.payload
    assert [(e["by"], e["role"]) for e in _fog(store, "B")] == [("human", None)]


def test_the_maps_agent_or_the_reader_under_the_runs_name_is_never_taken_for_the_running_turn(tmp_path: Path):
    store = _two_nodes(tmp_path)
    _turn(store, "B", "prover", "started", "tb")
    _run(tmp_path, "fog", "add", "from the map's discussion", "--near", "B", env={"PROOF_AGENT_NAME": AGENT})
    _run(tmp_path, "fog", "add", "a departure the Reader found", "--near", "B", env={"PROOF_AGENT_NAME": AGENT, "PROOF_AGENT_ROLE": "reader"})

    assert [(e["text"], e["role"], e.get("from_node")) for e in _fog(store, "B")] == [
        ("from the map's discussion", None, None), ("a departure the Reader found", "reader", None)]


def _about_a(store) -> dict:
    return {e["kind"]: (e["role"], e.get("role_unknown", False)) for e in work_log(store, "A") if e["kind"] in ("claimed", "evidence")}


def _a_with_a_proof(tmp_path: Path):
    from _proofs import submit_proof

    store = _two_nodes(tmp_path)
    return store, submit_proof(store, "A", claimant_id=AGENT, scoping_rationale="scoped", content="proof of A")


def test_an_entry_about_the_node_naming_no_turn_is_its_turns_when_that_turn_alone_runs_under_the_name(tmp_path: Path):
    from proof_cli.proof_map import claim_node, record_evidence_check

    store, proof = _a_with_a_proof(tmp_path)
    _turn(store, "A", "verifier", "started", "ta")
    claim_node(store, "A", claimant_id=AGENT)  # the host's writes outside acting_as: no turn named
    record_evidence_check(store, proof.id, "passed", run_by=AGENT, notes="no objections")

    assert _about_a(store) == {"claimed": ("verifier", False), "evidence": ("verifier", False)}


def test_an_entry_about_the_node_naming_no_turn_reads_unknown_while_another_turn_runs_under_the_name(tmp_path: Path):
    from proof_cli.proof_map import claim_node, record_evidence_check

    store, proof = _a_with_a_proof(tmp_path)
    _turn(store, "A", "verifier", "started", "ta")
    _turn(store, "B", "prover", "started", "tb")
    claim_node(store, "A", claimant_id=AGENT)
    record_evidence_check(store, proof.id, "passed", run_by=AGENT, notes="no objections")

    assert _about_a(store) == {"claimed": (None, True), "evidence": (None, True)}


def test_an_entry_about_the_node_naming_no_turn_reads_unknown_when_only_another_nodes_turn_has_the_name(tmp_path: Path):
    from proof_cli.proof_map import claim_node

    store, _ = _a_with_a_proof(tmp_path)
    _turn(store, "B", "prover", "started", "tb")
    claim_node(store, "A", claimant_id=AGENT)

    assert _about_a(store) == {"claimed": (None, True)}


def test_what_the_host_records_inside_acting_as_is_that_turns_beside_a_same_named_turn(tmp_path: Path):
    from proof_cli.proof_map import claim_node, record_evidence_check
    from proof_cli.storage import acting_as

    store, proof = _a_with_a_proof(tmp_path)
    _turn(store, "A", "verifier", "started", "ta")
    _turn(store, "B", "prover", "started", "tb")
    with acting_as("A", "verifier"):
        claim_node(store, "A", claimant_id=AGENT)
        record_evidence_check(store, proof.id, "passed", run_by=AGENT, notes="no objections")

    assert _about_a(store) == {"claimed": ("verifier", False), "evidence": ("verifier", False)}


def test_a_running_reader_turn_is_a_running_turn_for_an_entry_that_names_none(tmp_path: Path):
    from proof_cli import pursuit
    from proof_cli.fog import add_fog
    from proof_cli.proof_map import claim_node

    store = _two_nodes(tmp_path)
    pursuit_id = pursuit.record_pursuit(store, "start", provider="claude").payload["pursuit_id"]
    pursuit.record_reader_turn(store, phase="started", turn="r1", by=AGENT, pursuit_id=pursuit_id)
    add_fog(store, "while the Reader reads", near=["A"], created_by=AGENT)  # no turn named
    _turn(store, "A", "verifier", "started", "ta")
    claim_node(store, "A", claimant_id=AGENT)  # about A, but the Reader runs under the same name too
    pursuit.record_reader_turn(store, phase="ended", turn="r1", by=AGENT, pursuit_id=pursuit_id, outcome="ok", events=[])
    add_fog(store, "after the Reader ended", near=["A"], created_by=AGENT)

    shown = {e.get("text") or e["kind"]: (e["role"], e.get("role_unknown", False)) for e in work_log(store, "A") if e["kind"] in ("fog", "claimed")}
    assert shown == {"while the Reader reads": (None, True), "claimed": (None, True), "after the Reader ended": (None, True)}
