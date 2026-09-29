"""Every command the agent skill names answers `--json` with the ADR-0006 envelope (issue #97).

The skill's retrieval-first reads (`search`, `retrieve`, `reference list`, `memory list`)
emit `{schema_version, ok, command, data}`, failures included. `node list` carries the
three state axes, and `node show` what the node page shows of its dependencies: each one's
pin, whether it is current, and the remedy a lagging or changed pin needs.
"""

import json
import re
from pathlib import Path

import click
import pytest
import typer
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.envelope import SCHEMA_VERSION
from proof_cli.proof_map import claim_node, create_node, open_challenge
from proof_cli.references import ReferenceRecord
from proof_cli.storage import ensure_project, import_reference
from proof_cli.theorems import LEGACY_TRUST_NOTICE, add_theorem

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / ".agents" / "skills" / "proof-cli" / "SKILL.md"


def _seed(root: Path) -> None:
    store = ensure_project(root)
    add_theorem(
        store,
        theorem_id="thm_main",
        kind="theorem",
        name="Main Result",
        statement="A implies C",
        assumptions=["A"],
        exports=["C"],
        status=TheoremStatus.verified,
        trust_level=TrustLevel.project_verified,
    )
    import_reference(store, ReferenceRecord(id="ref_std", title="Standard Estimate", year=2023))
    runner.invoke(app, ["memory", "add", "try the Main Result route", "--root", str(root)])


def _json(root: Path, *args: str):
    result = runner.invoke(app, [*args, "--root", str(root), "--json"])
    return result, json.loads(result.stdout)


# -- the retrieval-first reads --------------------------------------------------------

RETRIEVAL_READS = [
    ("search", ["search", "Main"]),
    ("retrieve", ["retrieve", "Main"]),
    ("reference.list", ["reference", "list"]),
    ("memory.list", ["memory", "list"]),
]
_IDS = [" ".join(args) for _, args in RETRIEVAL_READS]


@pytest.mark.parametrize(("name", "args"), RETRIEVAL_READS, ids=_IDS)
def test_a_retrieval_read_answers_with_one_envelope(tmp_path: Path, name, args):
    _seed(tmp_path)
    result, envelope = _json(tmp_path, *args)
    assert result.exit_code == 0, result.output
    assert (envelope["schema_version"], envelope["ok"], envelope["command"]) == (SCHEMA_VERSION, True, name)


@pytest.mark.parametrize(("name", "args"), RETRIEVAL_READS, ids=_IDS)
def test_a_retrieval_read_on_a_missing_project_fails_in_an_envelope(tmp_path: Path, name, args):
    missing = tmp_path / "typo"
    result, envelope = _json(missing, *args)
    assert result.exit_code == 1
    assert envelope["ok"] is False and envelope["command"] == name
    assert envelope["error"]["code"] == "PROJECT_NOT_FOUND"
    assert not missing.exists()


def test_search_under_json_lists_the_ranked_candidates_with_the_legacy_notice(tmp_path: Path):
    _seed(tmp_path)
    _, envelope = _json(tmp_path, "search", "Main")
    data = envelope["data"]
    assert data["legacy_notice"] == LEGACY_TRUST_NOTICE  # a candidate carries a legacy trust level
    assert "thm_main" in [candidate["id"] for candidate in data["candidates"]]


def test_search_and_retrieve_rank_the_same_candidates(tmp_path: Path):
    _seed(tmp_path)
    _, searched = _json(tmp_path, "search", "Main")
    _, retrieved = _json(tmp_path, "retrieve", "Main")
    ids = lambda envelope: [c["id"] for c in envelope["data"]["candidates"]]  # noqa: E731
    assert ids(searched) == ids(retrieved)


def test_reference_list_under_json_lists_the_references_with_the_legacy_notice(tmp_path: Path):
    _seed(tmp_path)
    _, envelope = _json(tmp_path, "reference", "list")
    assert envelope["data"]["legacy_notice"] == LEGACY_TRUST_NOTICE
    assert [reference["id"] for reference in envelope["data"]["references"]] == ["ref_std"]


def test_memory_list_under_json_lists_the_artifacts(tmp_path: Path):
    _seed(tmp_path)
    _, envelope = _json(tmp_path, "memory", "list")
    (artifact,) = envelope["data"]["memory"]
    assert artifact["content"] == "try the Main Result route" and artifact["layer"] == "working"


def test_memory_list_under_json_filters_like_the_text(tmp_path: Path):
    _seed(tmp_path)
    _, envelope = _json(tmp_path, "memory", "list", "--layer", "semantic")
    assert envelope["data"]["memory"] == []


def test_memory_list_with_an_unknown_layer_is_invalid_input(tmp_path: Path):
    _seed(tmp_path)
    result, envelope = _json(tmp_path, "memory", "list", "--layer", "bogus")
    assert result.exit_code == 1
    assert (envelope["ok"], envelope["error"]["code"]) == (False, "INVALID_INPUT")


# -- node list and node show ----------------------------------------------------------


def test_node_list_under_json_carries_the_three_state_axes(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="c1", kind="claim", statement="C1")
    create_node(store, node_id="c2", kind="claim", statement="C2")
    claim_node(store, "c2", claimant_id="agent_a", session_id="s")

    _, envelope = _json(tmp_path, "node", "list")

    states = {n["id"]: (n["workflow_state"], n["acceptance_state"], n["integrity_state"]) for n in envelope["data"]}
    assert states["c1"][0] == "open" and states["c2"][0] == "claimed"
    assert all(axes[1] and axes[2] for axes in states.values())


def _accepted(store, node_id, dependencies=()):
    create_node(store, node_id=node_id, kind="claim", statement=f"stmt {node_id}", dependencies=list(dependencies))
    submit_proof(store, node_id, claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content=f"proof {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def test_node_show_under_json_carries_each_dependencys_pin_and_remedy(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store, "lem")
    _accepted(store, "uses", ["lem"])
    open_challenge(store, "lem", opened_by="agent_b", rationale="?")  # an Accepted node is reclaimed only once challenged
    claim_node(store, "lem", claimant_id="agent_a", session_id="s2")
    submit_proof(store, "lem", claimant_id="agent_a", session_id="s2", scoping_rationale="scoped", content="v2")
    researcher(store).decide_acceptance("lem", "accept")  # v2, same interface: the pin on v1 lags

    result, envelope = _json(tmp_path, "node", "show", "uses")

    assert result.exit_code == 0, result.output
    data = envelope["data"]
    assert data["dependencies"] == ["lem"]  # the node's own field, unchanged
    (dependency,) = data["dependency_details"]
    assert dependency["node_id"] == "lem" and dependency["kind"] == "claim"
    assert (dependency["pin"]["pinned_version"], dependency["accepted_version"]) == (1, 2)
    assert (dependency["current"], dependency["remedy"]) == (True, "lightweight-re-review")


def test_node_show_under_json_says_a_node_without_dependencies_has_none(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="c1", kind="claim", statement="C1")
    _, envelope = _json(tmp_path, "node", "show", "c1")
    assert envelope["data"]["dependency_details"] == []


def test_node_show_under_json_matches_what_the_node_page_shows(tmp_path: Path):
    from _review_client import DirectClient

    store = ensure_project(tmp_path)
    _accepted(store, "lem")
    create_node(store, node_id="uses", kind="claim", statement="U", dependencies=["lem"])
    submit_proof(store, "uses", claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content="u")

    _, envelope = _json(tmp_path, "node", "show", "uses")
    page = DirectClient(store).get("/api/node/uses")[1]["data"]

    assert envelope["data"]["dependency_details"] == page["dependencies"]


# -- every command the agent skill names ----------------------------------------------


def _skill_commands() -> set[tuple[str, ...]]:
    """Each `proof …` command SKILL.md names, as its path in the command tree."""
    tree = typer.main.get_command(app)
    found: set[tuple[str, ...]] = set()
    for span in re.findall(r"`proof ([^`]+)`", SKILL.read_text()):
        command, path = tree, []
        for word in span.split():
            if not isinstance(command, click.Group) or word not in command.commands:
                break
            command = command.commands[word]
            path.append(word)
        assert path and not isinstance(command, click.Group), f"`proof {span}` names no command"
        found.add(tuple(path))
    return found


def test_the_skill_names_the_retrieval_first_reads():
    named = _skill_commands()
    for path in (("search",), ("retrieve",), ("reference", "list"), ("memory", "list"), ("node", "show")):
        assert path in named, path


def test_every_command_the_skill_names_accepts_json():
    tree = typer.main.get_command(app)
    missing = []
    for path in sorted(_skill_commands()):
        command = tree
        for word in path:
            command = command.commands[word]
        if not any("--json" in p.opts for p in command.params if isinstance(p, click.Option)):
            missing.append(" ".join(path))
    assert not missing, missing
