"""Issue #227: an event names the agent turn that wrote it, from one explicit context, never a hidden global.

`storage.acting_as(node, role)` marks the writes made inside it as that turn's. The CLI enters it once per invocation
from the agent runtime's PROOF_AGENT_NODE / PROOF_AGENT_ROLE and leaves it when the invocation ends; the host that
records a run's work wraps those writes in it. Outside it nothing is marked: the researcher's own commands and
anything the host writes for itself.
"""

import json
import threading
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.fog import add_fog
from proof_cli.proof_map import create_node
from proof_cli.storage import ACTING_TURN, acting_as, acting_turn, ensure_project, list_events

runner = CliRunner()
AGENT = "claude-code"


def _fog_events(store) -> dict[str, dict | None]:
    return {e.payload["text"]: e.payload.get(ACTING_TURN) for e in list_events(store) if e.kind == "proof_fog_added"}


def _store(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node in ("A", "B"):
        create_node(store, node_id=node, kind="lemma", statement=f"lemma {node}")
    return store


def test_a_write_inside_acting_as_names_the_turn_and_one_outside_it_names_none(tmp_path: Path):
    store = _store(tmp_path)
    with acting_as("A", "verifier"):
        assert acting_turn() == {"node": "A", "role": "verifier"}
        add_fog(store, "the host records the run's item", near=["A"], created_by=AGENT)
    add_fog(store, "the host's own item", near=["A"], created_by=AGENT)

    assert acting_turn() is None
    assert _fog_events(store) == {"the host records the run's item": {"node": "A", "role": "verifier"}, "the host's own item": None}


def test_consecutive_cli_invocations_in_one_process_do_not_carry_a_turn_over(tmp_path: Path):
    store = _store(tmp_path)
    runtime = {"PROOF_AGENT_NAME": AGENT, "PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NODE": "B"}
    for text, env in (("B's prover", runtime), ("the researcher's", {}), ("the map's agent", {"PROOF_AGENT_NAME": AGENT})):
        result = runner.invoke(app, ["fog", "add", text, "--near", "B", "--root", str(tmp_path), "--json"], env=env)
        assert result.exit_code == 0, result.output
        assert acting_turn() is None  # left when the invocation ended

    assert _fog_events(store) == {"B's prover": {"node": "B", "role": "prover"}, "the researcher's": None,
                                  "the map's agent": {"node": None, "role": None}}


def test_turns_acting_at_once_in_two_threads_never_cross(tmp_path: Path):
    store = _store(tmp_path)
    both_inside = threading.Barrier(2)
    failures: list[BaseException] = []

    def work(node: str, role: str):
        try:
            with acting_as(node, role):
                both_inside.wait(timeout=10)
                for i in range(5):
                    add_fog(store, f"{node} {i}", near=[node], created_by=AGENT)
        except BaseException as exc:  # noqa: BLE001 — reported below
            failures.append(exc)

    threads = [threading.Thread(target=work, args=args) for args in (("A", "verifier"), ("B", "prover"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == []
    marks = _fog_events(store)
    assert {text: mark for text, mark in marks.items() if text.startswith("A ")} == {f"A {i}": {"node": "A", "role": "verifier"} for i in range(5)}
    assert {text: mark for text, mark in marks.items() if text.startswith("B ")} == {f"B {i}": {"node": "B", "role": "prover"} for i in range(5)}
