"""The sample proof map of spec #14, read end to end the way the proof map page reads it (issue #98, ADR-0008)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from _researcher import researcher
from _review_client import DirectClient
from fixtures.build_sample_proof_map import build_sample_proof_map
from proof_cli.proof_map import ProofMapError, claim_node, get_frontier, get_node, list_challenges

TREE_HARNESS = Path(__file__).resolve().parent / "js" / "tree_harness.js"

# every node's axes as /api/map reports them: (workflow_state, blocked_reason, acceptance_state, integrity_state, frontier)
WITH_THE_CHALLENGE_OPEN = {
    "T": ("blocked", "dependency-challenged", "unreviewed", "current", False),
    "L1": ("open", None, "accepted", "challenged", True),  # an open Challenge invites a revision (ADR-0005 Rule 4)
    "L2": ("open", None, "accepted", "current", False),
    "C1": ("open", None, "accepted", "current", False),
    "C2": ("open", None, "accepted", "current", False),
    "I": ("open", None, "reviewed", "current", False),  # an imported result's acceptance axis is its Reference review
    "I2": ("open", None, "trusted-by-rule", "current", False),  # or the Trust rule its citation meets (ADR-0014)
    "R": ("open", None, "rejected", "current", False),
    "N": ("open", None, "accepted", "current", False),  # the computation claim, accepted on its program (spec #145)
}
AFTER_THE_DISMISSAL = {
    **WITH_THE_CHALLENGE_OPEN,
    "T": ("open", None, "unreviewed", "current", True),  # unblocked: the theorem itself is now the work
    "L1": ("open", None, "accepted", "current", False),
}


@pytest.fixture
def sample(tmp_path: Path):
    return build_sample_proof_map(tmp_path)


def _map(store) -> dict:
    return {n["id"]: n for n in DirectClient(store).get("/api/map")[1]["data"]["nodes"]}


def _axes(nodes: dict) -> dict:
    keys = ("workflow_state", "blocked_reason", "acceptance_state", "integrity_state", "frontier")
    return {node_id: tuple(n[k] for k in keys) for node_id, n in nodes.items()}


def _dismiss(sample) -> None:
    (challenge_id,) = sample.challenges
    researcher(sample.store).dismiss_challenge(challenge_id, rationale="the hypothesis is met: see step 3")


def test_the_sample_has_the_shape_of_spec_14(sample):
    nodes = _map(sample.store)
    assert {node_id: n["kind"] for node_id, n in nodes.items()} == {
        "T": "theorem", "L1": "lemma", "L2": "lemma", "C1": "claim", "C2": "claim", "I": "imported_result", "I2": "imported_result", "R": "claim",
        "N": "claim",
    }
    assert nodes["T"]["dependencies"] == ["L1", "L2"]
    assert nodes["L1"]["dependencies"] == ["C1", "C2"]
    assert nodes["L2"]["dependencies"] == ["C2"]
    assert (get_node(sample.store, "C1").derived_from, get_node(sample.store, "C2").derived_from) == ("L1", "L1")
    assert get_node(sample.store, "R").derived_from == "T"
    assert "R" not in nodes["T"]["dependencies"]  # an abandoned route, not a premise
    (challenge,) = list_challenges(sample.store, status="open")
    assert challenge.target_node_id == "L1" and challenge.id == sample.challenges[0]


def test_c1_rests_on_the_reference_reviewed_imported_result(sample):
    """A split child can carry its own dependency (#106): C1 rests on I, whose Reference review unblocks it."""
    nodes = _map(sample.store)
    assert nodes["C1"]["dependencies"] == ["I"]
    assert nodes["I"]["dependencies"] == []
    assert sorted(node_id for node_id, n in nodes.items() if "I" in n["dependencies"]) == ["C1"]


def test_every_node_reads_its_three_axes_and_blocked_reason(sample):
    assert _axes(_map(sample.store)) == WITH_THE_CHALLENGE_OPEN


def test_the_frontier_is_what_the_map_marks_ready(sample):
    assert {n.id for n in get_frontier(sample.store)} == {"L1"}
    assert {node_id for node_id, n in _map(sample.store).items() if n["frontier"]} == {"L1"}


def test_the_shared_claim_is_one_node_in_the_dag_with_two_parents(sample):
    nodes = _map(sample.store)
    assert list(nodes).count("C2") == 1 and len(nodes) == 9
    assert sorted(node_id for node_id, n in nodes.items() if "C2" in n["dependencies"]) == ["L1", "L2"]


def _tree(nodes: list[dict], root: str) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("needs node")
    done = subprocess.run(["node", str(TREE_HARNESS), json.dumps({"nodes": nodes, "root": root})], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _walk(items: list[dict], path: tuple = ()):
    for item in items:
        yield path + (item["id"],), item
        yield from _walk(item["children"], path + (item["id"],))


def test_the_tree_view_shows_the_shared_claim_under_each_parent(sample):
    """The page's own tree view (ADR-0008): C2 is drawn in full at both places it's used, marked shared."""
    nodes = DirectClient(sample.store).get("/api/map")[1]["data"]["nodes"]

    drawn = list(_walk(_tree(nodes, "T")))

    at_c2 = [(path, item) for path, item in drawn if item["id"] == "C2"]
    assert [path for path, _ in at_c2] == [("T", "L1", "C2"), ("T", "L2", "C2")]
    assert [item["shared_by"] for _, item in at_c2] == [2, 2]
    assert all(item["shared_by"] == 0 for _, item in drawn if item["id"] != "C2")
    assert sorted(path for path, _ in drawn) == sorted(
        [("T",), ("T", "L1"), ("T", "L1", "C1"), ("T", "L1", "C2"), ("T", "L2"), ("T", "L2", "C2"), ("T", "L1", "C1", "I")]
    )  # R, derived from T but not a premise, isn't part of how T is proved


def test_the_rejected_route_reads_rejected_and_never_joins_the_frontier(sample):
    assert _map(sample.store)["R"]["acceptance_state"] == "rejected"
    assert "R" not in {n.id for n in get_frontier(sample.store)}
    with pytest.raises(ProofMapError) as refused:
        claim_node(sample.store, "R", claimant_id="agent_c")
    assert refused.value.code == "NODE_REJECTED"

    _dismiss(sample)  # nor once the map moves on

    assert _map(sample.store)["R"]["acceptance_state"] == "rejected"
    assert "R" not in {n.id for n in get_frontier(sample.store)}


def test_dismissing_the_challenge_clears_every_stale_mark(sample):
    _dismiss(sample)

    nodes = _map(sample.store)
    assert _axes(nodes) == AFTER_THE_DISMISSAL
    assert all(n["integrity_state"] == "current" and n["blocked_reason"] != "dependency-challenged" for n in nodes.values())
    assert list_challenges(sample.store, status="open") == []
    assert {n.id for n in get_frontier(sample.store)} == {"T"}


def test_the_second_citation_of_the_reviewed_source_is_trusted_by_rule_and_listed_apart(sample):
    """I2 cites what I was reviewed for, at the same version: the sample's Trust rule covers it (ADR-0014)."""
    nodes = _map(sample.store)
    assert nodes["I2"]["acceptance_state"] == "trusted-by-rule" and nodes["I2"]["trust_rule"] == ["same-source"]
    assert nodes["I"]["trust_rule"] == []  # the explicit review counts; nothing rests on a rule-trusted node
    state = DirectClient(sample.store).get("/api/state")[1]["data"]
    assert [item["node_id"] for item in state["trusted_by_rule"]] == ["I2"]
    assert "I2" not in [item["node_id"] for item in state["pending"]]


def test_the_fog_is_outside_the_graph_and_reads_back_with_its_experiment(sample):
    """Fog items are never nodes (ADR-0008): the map is unchanged by them, and the page's fog list has them."""
    nodes = _map(sample.store)
    assert "fog-1" not in nodes and nodes["L1"]["dependencies"] == ["C1", "C2"]
    listed = DirectClient(sample.store).get("/api/fog")[1]["data"]["items"]
    (item,) = listed
    assert item["id"] == "fog-1" and item["near"] == ["L1"] and item["latest_experiment"]["outcome"] == "supports" and not item["latest_experiment"]["missing"]
    everything = DirectClient(sample.store).get("/api/fog?all=1")[1]["data"]["items"]
    assert [(i["id"], i["status"]) for i in everything] == [("fog-1", "open"), ("fog-2", "dropped")]
    lemma = DirectClient(sample.store).get("/api/node/L1")[1]["data"]
    assert [f["id"] for f in lemma["fog_near"]] == ["fog-1"]


def test_the_builder_scales_for_a_performance_baseline(tmp_path: Path):
    scaled = build_sample_proof_map(tmp_path, copies=3)

    nodes = _map(scaled.store)
    assert len(nodes) == 1 + 3 * 8
    assert nodes["T"]["dependencies"] == ["L1", "L2", "L1-2", "L2-2", "L1-3", "L2-3"]
    assert nodes["L2-3"]["dependencies"] == ["C2-3"]
    assert nodes["C1-3"]["dependencies"] == ["I-3"]
    assert {node_id for node_id, n in nodes.items() if n["frontier"]} == set(scaled.ids("L1"))
    assert len(scaled.challenges) == 3


def test_the_computation_claim_is_accepted_on_its_program_and_a_passed_run(sample):
    """N's medium is computation (spec #145): run.sh and out/ are its candidate proof, a run its Evidence check."""
    from proof_cli.proof_map import list_candidate_proofs, list_evidence_checks

    nodes = _map(sample.store)
    assert nodes["N"]["medium"] == "computation" and nodes["N"]["acceptance_state"] == "accepted"
    assert nodes["L1"]["medium"] == "latex" and nodes["I"]["medium"] is None
    folder = sample.store.root / "proofs" / "N"
    assert (folder / "run.sh").is_file() and (folder / "out" / "table.csv").is_file() and not (folder / "proof.tex").exists()
    (proof,) = list_candidate_proofs(sample.store, "N")
    (check,) = list_evidence_checks(sample.store, proof.id)
    assert check.outcome.value == "passed"
