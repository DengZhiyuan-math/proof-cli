"""Free text from a file: the `--…-file` twin of each option or argument a Proof agent writes mathematics into.

A role's text reached `proof` as a shell argument, and the shell is no place for mathematics: zsh expands `$$` (to
its process id) and `$name` (to the variable's value, or nothing) inside double quotes, and Claude Code's Bash validator
refuses, however it is quoted, a command with `|=` before a letter or a backslash before a space, so a role's notes
were retried with their mathematics paraphrased. The file twin carries the text past the shell: read as UTF-8, taken as written, only its final line end
dropped (the file's, not the text's). A file that can't be read so is TEXT_FILE_UNREADABLE before anything is written;
the text given both ways is a usage error.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _researcher import researcher
from proof_cli.cli import app
from proof_cli.definitions import require_definition
from proof_cli.fog import require_fog
from proof_cli.proof_map import create_node, require_node, work_log
from proof_cli.storage import ensure_project, load_project
from proof_cli.vault import read_working_snapshot

runner = CliRunner()

# what the shell would have corrupted or refused: `$$`, `$name`, `|x|=y`, a backslash before a space, and quotes
TEXT = "Write $$x$$ here: for |x|=y the bound $name \\le 1$ holds, and a\\ b stays.\nA `second` line with 'single' and \"double\" quotes."
VERIFIER = {"PROOF_AGENT_ROLE": "verifier", "PROOF_AGENT_NAME": "claude-code"}
PROVER = {"PROOF_AGENT_ROLE": "prover", "PROOF_AGENT_NAME": "claude-code"}


def _run(root: Path, *args: str, env=None):
    return runner.invoke(app, [*args, "--root", str(root), "--json"], env=env or {})


def _data(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


def _error(result) -> dict:
    return json.loads(result.output)["error"]


def _file(folder: Path, name: str, text: str = TEXT) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")  # an editor's file ends with a line end; the text does not
    return str(path)


def _project(tmp_path: Path):
    root = tmp_path / "project"
    store = ensure_project(root)
    create_node(store, node_id="N", kind="lemma", statement="a lemma")
    return root, store


def test_a_verdicts_note_from_a_file_is_stored_as_written(tmp_path: Path):
    root, store = _project(tmp_path)
    note = _file(tmp_path / "scratch" / "verifier", "verdict.md")
    entry = _data(_run(root, "node", "progress", "N", "--verdict", "failed", "--note-file", note, "--objection-file", note, env=VERIFIER))
    assert entry["note"] == TEXT
    assert [e["note"] for e in work_log(load_project(root), "N") if e.get("kind") == "verdict"] == [TEXT]
    assert entry["objections"][0]["text"] == TEXT  # an objection from a file, as written too


def test_a_handoff_a_step_a_question_and_an_attempt_take_their_text_from_files(tmp_path: Path):
    root, _ = _project(tmp_path)
    handoff = _data(_run(root, "node", "progress", "N", "--handoff", "typesetter", "--note-file", _file(tmp_path, "handoff.md"), env=PROVER))
    step = _data(_run(root, "node", "progress", "N", "--step", "1", "--status", "done", "--note-file", _file(tmp_path, "step.md"), env=PROVER))
    question = _data(_run(root, "node", "progress", "N", "--question-file", _file(tmp_path, "question.md", "chose |x|=y; else $$x$$"), env=PROVER))
    attempt = _data(_run(root, "node", "progress", "N", "--attempt-file", _file(tmp_path, "goal.md", "bound $name$"),
                         "--method-file", _file(tmp_path, "method.md", "induction on |x|=y"),
                         "--failed-on-file", _file(tmp_path, "obstruction.md", "a\\ b fails"), env=PROVER))
    assert handoff["note"] == TEXT and step["note"] == TEXT and question["question"] == "chose |x|=y; else $$x$$"
    assert (attempt["goal"], attempt["method"], attempt["failed_on"]) == ("bound $name$", "induction on |x|=y", "a\\ b fails")


def test_statements_and_definitions_take_their_text_from_files(tmp_path: Path):
    root, store = _project(tmp_path)
    definition = _data(_run(root, "definition", "add", "unit", "--text-file", _file(tmp_path, "unit.md"), "--term", "Unit"))
    assert definition["text"] == TEXT
    node = _data(_run(root, "node", "create", "L", "lemma", "--statement-file", _file(tmp_path, "L.md"), "--definition", "unit",
                      "--assumption", "inline", "--assumption-file", _file(tmp_path, "assume.md", "$|x|=y$")))
    assert node["statement"] == TEXT and node["assumptions"] == ["inline", "$|x|=y$"]
    children = _data(_run(root, "node", "split", "N", "--child", "C1=inline $x$", "--child-file", f"C2={_file(tmp_path, 'C2.md')}"))
    assert [(child["id"], child["statement"]) for child in children] == [("C1", "inline $x$"), ("C2", TEXT)]
    restated = _data(_run(root, "node", "restate", "L", "--statement-file", _file(tmp_path, "L2.md", "now $$y$$ with |u|=v"),
                          "--assumption-file", _file(tmp_path, "assume2.md", "a\\ b"), "--reason", "clearer"))
    assert restated["statement"] == "now $$y$$ with |u|=v" and restated["assumptions"] == ["a\\ b"]
    edited = _data(_run(root, "definition", "edit", "unit", "--text-file", _file(tmp_path, "unit2.md", "$$u$$ |a|=b"), "--reason", "clearer"))
    assert edited["text"] == "$$u$$ |a|=b" and require_definition(load_project(root), "unit").text == "$$u$$ |a|=b"


def test_each_claim_of_a_split_gets_its_own_assumptions_and_none_of_its_parents(tmp_path: Path):
    """A condition only one Claim needs goes in its assumptions, and a Claim inherits none (#255): a split of several Claims
    gives each its own, inline or from a file, as `--child-definition` gives each its definitions."""
    root, store = _project(tmp_path)
    create_node(store, node_id="P", kind="lemma", statement="a lemma", assumptions=["the parent's own"])
    children = _data(_run(root, "node", "split", "P", "--child", "C1=one", "--child", "C2=two", "--child", "C3=three",
                          "--child-assumption", "C1=$f$ is continuous", "--child-assumption-file", f"C2={_file(tmp_path, 'C2a.md')}",
                          "--child-assumption", "C2=a second"))
    assert [child["assumptions"] for child in children] == [["$f$ is continuous"], ["a second", TEXT], []]  # inline ones first
    stray = _run(root, "node", "split", "P", "--child", "C4=four", "--child-assumption", "C9=x")
    assert _error(stray)["code"] == "INVALID_CHILD_SPEC" and "C9" in _error(stray)["message"]


def test_a_fog_item_a_memory_entry_and_a_challenges_rationale_take_their_text_from_files(tmp_path: Path):
    root, store = _project(tmp_path)
    fog = _data(_run(root, "fog", "add", "--text-file", _file(tmp_path, "fog.md"), "--near", "N"))
    assert require_fog(load_project(root), fog["id"]).text == TEXT
    memory = _data(_run(root, "memory", "add", "--node-id", "N", "--layer", "episodic", "--status", "failed", "--content-file", _file(tmp_path, "memory.md")))
    assert memory["content"] == TEXT
    create_node(store, node_id="imp", kind="imported_result", statement="a cited bound", source_locator="Thm 1", source_version="v1")
    researcher(store).decide_reference_review("imp")
    challenge = _data(_run(root, "challenge", "open", "imp", "--rationale-file", _file(tmp_path, "why.md")))
    assert challenge["rationale"] == TEXT


def test_a_relative_path_is_read_from_the_current_folder_as_an_agent_in_its_node_folder_writes_it(tmp_path: Path, monkeypatch):
    """A role runs in its node folder with PROOF_ROOT set: `--note-file scratch/verifier/x.md` is that folder's file. The
    file is no input of the proof: scratch/ is never frozen, so the verdict's digest is the folder's without it."""
    root, store = _project(tmp_path)
    folder = root / "proofs" / "N"
    before = read_working_snapshot(root, "N", require_node(store, "N").medium).digest()
    _file(folder / "scratch" / "verifier", "x.md")
    monkeypatch.chdir(folder)
    entry = _data(runner.invoke(app, ["node", "progress", "N", "--verdict", "failed", "--note-file", "scratch/verifier/x.md",
                                      "--objection-file", "scratch/verifier/x.md", "--json"],
                                env={**VERIFIER, "PROOF_ROOT": str(root)}))
    assert entry["note"] == TEXT and entry["inputs_sha256"] == before


def test_only_the_final_line_end_is_the_files(tmp_path: Path):
    root, _ = _project(tmp_path)
    path = tmp_path / "two.md"
    path.write_bytes("  first line\n\nsecond line  \n".encode("utf-8"))
    node = _data(_run(root, "node", "create", "T", "lemma", "--statement-file", str(path)))
    assert node["statement"] == "  first line\n\nsecond line  "
    path.write_bytes(b"no line end")
    assert _data(_run(root, "node", "create", "U", "lemma", "--statement-file", str(path)))["statement"] == "no line end"


@pytest.mark.parametrize("make", ["missing", "folder", "latin-1"])
def test_a_file_that_cannot_be_read_as_utf8_text_is_refused_and_nothing_is_written(tmp_path: Path, make):
    root, _ = _project(tmp_path)
    path = tmp_path / "note.md"
    if make == "folder":
        path.mkdir()
    elif make == "latin-1":
        path.write_bytes("caf\xe9 $x$".encode("latin-1"))
    refused = _run(root, "node", "progress", "N", "--verdict", "failed", "--note-file", str(path), env=VERIFIER)
    assert refused.exit_code == 1, refused.output
    error = _error(refused)
    assert error["code"] == "TEXT_FILE_UNREADABLE" and (error["option"], error["path"]) == ("--note-file", str(path))
    assert not [e for e in work_log(load_project(root), "N") if e.get("kind") == "verdict"]


def test_a_statement_file_that_is_missing_starts_no_project_and_creates_no_node(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    refused = _run(empty, "node", "create", "L", "lemma", "--statement-file", str(tmp_path / "nowhere.md"))
    assert refused.exit_code == 1 and _error(refused)["code"] == "TEXT_FILE_UNREADABLE"
    assert not (empty / ".proof").exists() and not (empty / "proofs").exists()
    root, _ = _project(tmp_path)
    refused = _run(root, "node", "split", "N", "--child-file", f"C1={tmp_path / 'nowhere.md'}")
    assert _error(refused)["code"] == "TEXT_FILE_UNREADABLE" and require_node(load_project(root), "N").dependencies == []
    malformed = _run(root, "node", "split", "N", "--child-file", "C1")
    assert _error(malformed)["code"] == "INVALID_CHILD_SPEC"


@pytest.mark.parametrize("args", [
    ["node", "progress", "N", "--step", "1", "--status", "done", "--note", "inline", "--note-file", "{file}"],
    ["node", "create", "L", "lemma", "inline", "--statement-file", "{file}"],
    ["definition", "add", "unit", "inline", "--text-file", "{file}", "--term", "Unit"],
    ["fog", "add", "inline", "--text-file", "{file}"],
])
def test_the_text_given_both_inline_and_from_a_file_is_a_usage_error(tmp_path: Path, args):
    root, _ = _project(tmp_path)
    path = _file(tmp_path, "text.md")
    refused = _run(root, *[arg.replace("{file}", path) for arg in args], env=PROVER if args[1] == "progress" else None)
    assert refused.exit_code == 2 and _error(refused)["code"] == "USAGE_ERROR", refused.output


def test_a_statement_given_neither_way_is_still_a_missing_argument(tmp_path: Path):
    root, _ = _project(tmp_path)
    refused = _run(root, "node", "create", "L", "lemma")
    assert refused.exit_code == 2 and _error(refused)["code"] == "USAGE_ERROR" and "STATEMENT" in _error(refused)["message"]
    assert _run(root, "definition", "add", "unit", "--term", "Unit").exit_code == 2
