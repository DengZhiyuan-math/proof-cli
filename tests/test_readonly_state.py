"""A `proof` command that cannot write the project's state says why, and what to do.

An agent's runtime runs `proof` outside Claude Code's sandbox only when every part of a Bash call is `proof`; joined with
anything else (`proof node list | head`, `cd … && proof …`) it runs inside, where `.proof/` is not writable. A read
on a fresh project failed there with INTERNAL_ERROR "attempt to write a readonly database": its first read ran a
one-time migration that only marks itself done. A brand-new project has nothing to migrate, so reads need no
write; what must write (a search is recorded, a fog item added) says why it can't, and what to do. Simulated here by
making `.proof/` read-only.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import create_node
from proof_cli.storage import ensure_project

runner = CliRunner()


@pytest.fixture
def read_only_state(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="A", kind="lemma", statement="Synthetic lemma A holds.")
    state = tmp_path / ".proof"
    files = list(state.iterdir())
    for path in files:
        path.chmod(0o444)
    state.chmod(0o555)
    yield tmp_path
    state.chmod(0o755)
    for path in files:
        path.chmod(0o644)


@pytest.mark.parametrize("args", [["node", "list"], ["node", "show", "A"], ["node", "progress", "A"]])
def test_a_read_of_a_fresh_project_needs_no_write(read_only_state, args):
    result = runner.invoke(app, [*args, "--root", str(read_only_state), "--json"])

    assert result.exit_code == 0 and json.loads(result.output)["ok"] is True, result.output


@pytest.mark.parametrize("args", [["fog", "add", "an open point", "--near", "A", "--created-by", "human"]])
def test_a_command_that_must_write_the_state_says_so_and_how_to_run_proof(read_only_state, args):
    result = runner.invoke(app, [*args, "--root", str(read_only_state), "--json"])

    envelope = json.loads(result.output)
    assert result.exit_code == 1 and envelope["ok"] is False
    assert envelope["error"]["code"] == "PROJECT_STATE_READ_ONLY", envelope
    message = envelope["error"]["message"]
    # a redirected command runs in the sandbox too: only a read may be redirected (a trial's `proof search … > file`)
    assert "a command of its own" in message and "no pipe, redirection" in message and "read may be redirected" in message, message
    assert "only a read" not in message   # a read that must first finish a one-time update of the state fails redirected too


def test_a_search_answers_from_a_read_only_state_and_only_its_history_entry_is_skipped(read_only_state):
    """A search is a read; it also logs itself in the project's session history. Under a read-only state (an agent's
    `proof search … > scratch/x.txt` runs in the sandbox) the search failed on that log alone."""
    result = runner.invoke(app, ["search", "Synthetic", "--root", str(read_only_state), "--json"])

    envelope = json.loads(result.output)
    assert result.exit_code == 0 and envelope["ok"] is True and "candidates" in envelope["data"], result.output
    from proof_cli.storage import ProjectStore, read_state

    assert not any(entry.startswith("search:") for entry in read_state(ProjectStore(read_only_state)).session_history)


def test_without_json_it_is_an_error_line_not_a_traceback(read_only_state):
    result = runner.invoke(app, ["fog", "add", "an open point", "--near", "A", "--created-by", "human", "--root", str(read_only_state)])

    assert result.exit_code == 1
    assert result.output.startswith("Error: ") and "a command of its own" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_a_folder_with_json_era_records_still_migrates_them_on_first_use(tmp_path: Path):
    """The marker is set at creation only where nothing can need moving: a folder holding a JSON-era collaboration.json
    first imports its records into review_history, and those still reach reviews.jsonl."""
    import sqlite3

    (tmp_path / ".proof").mkdir()
    (tmp_path / ".proof" / "collaboration.json").write_text('{"review_records": []}')
    ensure_project(tmp_path)

    with sqlite3.connect(tmp_path / ".proof" / "project.sqlite3") as conn:
        marked = conn.execute("SELECT 1 FROM project_meta WHERE key = 'reviews_jsonl_migrated'").fetchone()
    assert marked is None
