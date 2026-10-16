"""Issue #227: an event names the agent turn that wrote it, from one explicit context, never a hidden global.

`storage.acting_as(node, role)` marks the writes made inside it as that turn's. The CLI enters it once per invocation
from the agent runtime's PROOF_AGENT_NODE / PROOF_AGENT_ROLE and leaves it when the invocation ends; the host that
records a run's work wraps those writes in it. Outside it nothing is marked: the researcher's own commands and
anything the host writes for itself.
"""

import contextvars
import threading
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.fog import add_fog
from proof_cli.proof_map import create_node
from proof_cli.storage import ACTING_TURN_FIELD, acting_as, ensure_project, list_events

runner = CliRunner()
AGENT = "claude-code"


def _fog_events(store) -> dict[str, dict | None]:
    return {e.payload["text"]: e.payload.get(ACTING_TURN_FIELD) for e in list_events(store) if e.kind == "proof_fog_added"}


def _store(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node in ("A", "B"):
        create_node(store, node_id=node, kind="lemma", statement=f"lemma {node}")
    return store


def test_a_write_inside_acting_as_names_the_turn_and_one_outside_it_names_none(tmp_path: Path):
    store = _store(tmp_path)
    with acting_as("A", "verifier"):
        add_fog(store, "the host records the run's item", near=["A"], created_by=AGENT)
    add_fog(store, "the host's own item", near=["A"], created_by=AGENT)

    assert _fog_events(store) == {"the host records the run's item": {"node": "A", "role": "verifier"}, "the host's own item": None}


def test_consecutive_cli_invocations_in_one_process_do_not_carry_a_turn_over(tmp_path: Path):
    store = _store(tmp_path)
    runtime = {"PROOF_AGENT_NAME": AGENT, "PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NODE": "B"}
    for text, env in (("B's prover", runtime), ("the researcher's", {}), ("the map's agent", {"PROOF_AGENT_NAME": AGENT})):
        result = runner.invoke(app, ["fog", "add", text, "--near", "B", "--root", str(tmp_path), "--json"], env=env)
        assert result.exit_code == 0, result.output
    add_fog(store, "written after them", near=["B"], created_by=AGENT)  # the last invocation's turn is left behind

    assert _fog_events(store) == {"B's prover": {"node": "B", "role": "prover"}, "the researcher's": None,
                                  "the map's agent": {"node": None, "role": None}, "written after them": None}


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


def test_a_cli_invocation_outside_an_agents_runtime_names_no_turn_even_inside_an_outer_acting_as(tmp_path: Path):
    store = _store(tmp_path)
    with acting_as("A", "verifier"):
        result = runner.invoke(app, ["fog", "add", "the researcher's command", "--near", "A", "--root", str(tmp_path), "--json"], env={})
        assert result.exit_code == 0, result.output
        add_fog(store, "the host's write for A's turn", near=["A"], created_by=AGENT)  # the outer block is back

    assert _fog_events(store) == {"the researcher's command": None, "the host's write for A's turn": {"node": "A", "role": "verifier"}}


def test_a_cli_invocation_in_one_thread_never_takes_the_turn_another_thread_acts_as(tmp_path: Path):
    store = _store(tmp_path)
    holding, invoked = threading.Event(), threading.Event()
    failures: list[BaseException] = []

    def host():
        try:
            with acting_as("A", "verifier"):
                holding.set()
                assert invoked.wait(timeout=30)
                add_fog(store, "the host's write", near=["A"], created_by=AGENT)
        except BaseException as exc:  # noqa: BLE001 — reported below
            failures.append(exc)

    def command():
        try:
            assert holding.wait(timeout=30)
            result = runner.invoke(app, ["fog", "add", "a command meanwhile", "--near", "A", "--root", str(tmp_path), "--json"], env={})
            assert result.exit_code == 0, result.output
        except BaseException as exc:  # noqa: BLE001 — reported below
            failures.append(exc)
        finally:
            invoked.set()

    threads = [threading.Thread(target=host), threading.Thread(target=command)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert failures == []
    assert _fog_events(store) == {"a command meanwhile": None, "the host's write": {"node": "A", "role": "verifier"}}


def test_a_cli_invocation_in_a_thread_that_inherited_an_acting_context_names_no_turn(tmp_path: Path):
    """A thread can start with a copy of a context in which a turn acts: the CLI's edge must say "not acting" itself."""
    store = _store(tmp_path)
    with acting_as("A", "verifier"):
        inherited = contextvars.copy_context()
    failures: list[BaseException] = []

    def command():
        try:
            result = runner.invoke(app, ["fog", "add", "a command in an inherited context", "--near", "A", "--root", str(tmp_path), "--json"], env={})
            assert result.exit_code == 0, result.output
            add_fog(store, "the thread's own write after it", near=["A"], created_by=AGENT)  # the inherited turn is back
        except BaseException as exc:  # noqa: BLE001 — reported below
            failures.append(exc)

    thread = threading.Thread(target=inherited.run, args=(command,))
    thread.start()
    thread.join(timeout=60)

    assert failures == []
    assert _fog_events(store) == {"a command in an inherited context": None,
                                  "the thread's own write after it": {"node": "A", "role": "verifier"}}
