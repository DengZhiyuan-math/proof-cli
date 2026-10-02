"""Run and Open in VS Code in a computation node's studio (spec #145, part 2; decided in #141, #143).

Run executes the node's `run.sh` through the studio's own program runner (stoppable, timed out,
its output for the Output panel) and records each run as an Evidence check on the node's current
candidate proof — exit 0 passed, otherwise failed, a run that could not start error — never a
decision. Open in VS Code hands the node folder to the editor: `vscode://file/<folder>` unless
`proof.toml` names an `[studio] open_command`, which the studio's server runs. Driven through
`StudioHub.request`, so no socket is needed.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from _proofs import write_key_ideas
from proof_cli.proof_map import create_node, list_evidence_checks, request_review
from proof_cli.storage import ensure_project, get_current_candidate_proof
from proof_cli.webapp.studios import StudioHub


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def hub(tmp_path: Path):
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Ada Researcher")
    _git(tmp_path, "config", "user.email", "ada@example.org")
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="claim", statement="for every n ≤ 10^4 it holds", medium="computation")
    create_node(store, node_id="L", kind="claim", statement="a written claim")
    hub = StudioHub(store)
    yield store, hub
    hub.close()


def _post(hub, path, body=None):
    answer = hub.request("POST", path, "", body or {}, cross_site=False)
    return answer.status, json.loads(answer.body)


def _get(hub, path):
    answer = hub.request("GET", path, "", None, cross_site=False)
    return answer.status, json.loads(answer.body)


def _script(store, node_id, body: str) -> Path:
    run = store.root / "proofs" / node_id / "run.sh"
    run.write_text("#!/usr/bin/env bash\n" + body)
    run.chmod(run.stat().st_mode | 0o111)
    return run


def _reviewed(store, node_id="N"):
    """A snapshot to hang Evidence checks on: a review request of the node as it stands."""
    write_key_ideas(store, node_id)
    return request_review(store, node_id, requested_by="agent_a", rationale="scoped")


# -- Run ------------------------------------------------------------------------------------------


def test_run_executes_run_sh_in_the_node_folder_and_records_a_passed_evidence_check(hub):
    store, hub = hub
    _script(store, "N", "mkdir -p out\necho 'n,ratio' > out/table.csv\necho checked every n\nexit 0\n")
    (store.root / "proofs" / "N" / "out").mkdir()
    (store.root / "proofs" / "N" / "out" / "table.csv").write_text("n,ratio\n")  # the output the program rewrites, frozen with it
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200
    assert result["exit"] == 0 and "checked every n" in result["output"] and result["seconds"] >= 0
    assert (store.root / "proofs" / "N" / "out" / "table.csv").is_file()
    assert result["evidence"]["outcome"] == "passed" and result["evidence"]["run_by"] == "Ada Researcher <ada@example.org>"
    (check,) = list_evidence_checks(store, proof.id)
    assert check.outcome.value == "passed" and check.run_by == "Ada Researcher <ada@example.org>"


def test_a_failing_run_records_a_failed_evidence_check(hub):
    store, hub = hub
    _script(store, "N", "echo 'counterexample at n = 7' >&2\nexit 3\n")
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 3 and "counterexample" in result["output"]
    (check,) = list_evidence_checks(store, proof.id)
    assert check.outcome.value == "failed" and "exit 3" in check.notes


def test_a_run_that_cannot_start_records_an_error(hub):
    store, hub = hub
    (store.root / "proofs" / "N" / "run.sh").unlink()  # and so no review could be requested either
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] is None and "run.sh" in result["output"]
    assert result["evidence"] is None  # nothing to record it against yet


def test_a_run_before_any_snapshot_records_nothing_and_says_so(hub):
    store, hub = hub
    _script(store, "N", "exit 0\n")
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0
    assert result["evidence"] is None and "snapshot" in result["note"]
    assert get_current_candidate_proof(store, "N") is None


def test_run_is_refused_on_a_latex_node(hub):
    store, hub = hub
    status, result = _post(hub, "/studio/L/api/run")
    assert status == 409 and result["code"] == "NOT_A_COMPUTATION" and "computation" in result["error"]  # the run-refusal shape


def test_a_run_is_stopped_from_another_request(hub):
    import threading
    import time

    store, hub = hub
    _script(store, "N", "sleep 30\n")
    proof = _reviewed(store)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(result=_post(hub, "/studio/N/api/run")[1]))
    worker.start()
    for _ in range(100):
        if _post(hub, "/studio/N/api/run/stop")[1]["stopped"]:
            break
        time.sleep(0.05)
    worker.join(timeout=10)
    result = outcome["result"]
    assert result["cancelled"] is True and result["evidence"] is None  # a stopped run establishes nothing (Evidence rule 3)
    assert "stopped" in result["note"] and "not recorded" in result["note"] and "not recorded" in result["output"]
    assert list_evidence_checks(store, proof.id) == []


# -- Open in VS Code --------------------------------------------------------------------------------


def test_config_tells_the_page_the_folder_the_medium_and_how_to_open_it(hub):
    store, hub = hub
    status, config = _get(hub, "/studio/N/api/config")
    assert status == 200
    assert config["folder"] == str((store.root / "proofs" / "N").resolve()) and config["medium"] == "computation"
    assert config["open"] == {"kind": "scheme", "url": f"vscode://file/{(store.root / 'proofs' / 'N').resolve()}"}
    assert _get(hub, "/studio/L/api/config")[1]["medium"] == "latex"


def test_a_configured_open_command_is_run_by_the_server_with_the_folder_filled_in(hub):
    store, hub = hub
    marker = store.root / "opened.txt"
    (store.root / "proof.toml").write_text(f'[studio]\nopen_command = "sh -c \'echo {{folder}} > {marker}\'"\n')
    status, config = _get(hub, "/studio/N/api/config")
    assert config["open"]["kind"] == "command" and "{folder}" in config["open"]["command"]
    status, result = _post(hub, "/studio/N/api/open")
    assert status == 200 and result["ok"] is True
    assert marker.read_text().strip() == str((store.root / "proofs" / "N").resolve())


def test_opening_without_a_command_tells_the_page_to_use_the_scheme(hub):
    store, hub = hub
    status, result = _post(hub, "/studio/N/api/open")
    assert status == 200 and result == {"ok": True, "kind": "scheme", "url": f"vscode://file/{(store.root / 'proofs' / 'N').resolve()}"}


def test_a_run_that_outlives_the_time_limit_is_timed_out_not_stopped_and_records_nothing(hub, monkeypatch):
    from proof_cli.studio import server as studio_server

    store, hub = hub
    monkeypatch.setattr(studio_server, "RUN_TIMEOUT", 1.0)
    _script(store, "N", "sleep 20\n")
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["timed_out"] is True and result["cancelled"] is False and result["exit"] is None
    assert "longer than 1 seconds" in result["output"]
    assert result["evidence"] is None and "timed out" in result["note"] and "not recorded" in result["note"]
    assert list_evidence_checks(store, proof.id) == []  # a timed-out run records nothing (Evidence rule 3)


def test_a_computation_nodes_studio_lists_and_edits_its_program_and_data_while_a_latex_nodes_does_not(hub):
    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / "check.py").write_text("print(1)\n")
    (folder / "out").mkdir()
    (folder / "out" / "table.csv").write_text("n,ratio\n")
    listed = {f["path"] for f in _get(hub, "/studio/N/api/tree")[1]["files"]}
    assert {"run.sh", "check.py", "key-ideas.md", "out/table.csv"} <= listed
    (store.root / "proofs" / "L" / "helper.py").write_text("print(1)\n")
    assert "helper.py" not in {f["path"] for f in _get(hub, "/studio/L/api/tree")[1]["files"]}
    status, _ = _post(hub, "/studio/N/api/file", {"path": "check.py", "content": "print(2)\n", "base_mtime": None, "force": True})
    assert status == 200 and (folder / "check.py").read_text() == "print(2)\n"


def test_a_file_opens_at_its_line_by_scheme_or_through_the_command(hub):
    store, hub = hub
    (store.root / "proofs" / "N" / "check.py").write_text("print(1)\n")
    status, result = _post(hub, "/studio/N/api/open", {"file": "check.py", "line": 40})
    assert result == {"ok": True, "kind": "scheme", "url": f"vscode://file/{(store.root / 'proofs' / 'N' / 'check.py').resolve()}:40"}
    assert _post(hub, "/studio/N/api/open", {"file": "../L/proof.tex"})[1]["code"] == "NOT_A_NODE_FILE"
    marker = store.root / "opened.txt"
    (store.root / "proof.toml").write_text(f'[studio]\nopen_command = "sh -c \'echo {{file}} > {marker}\'"\n')
    assert _post(hub, "/studio/N/api/open", {"file": "check.py", "line": 40})[1]["ok"] is True
    assert marker.read_text().strip() == str((store.root / "proofs" / "N" / "check.py").resolve())


# -- a run is evidence about the snapshot it matches, never about a folder that drifted (audit S1) -------


def test_a_run_of_a_program_that_differs_from_the_snapshot_is_recorded_against_nothing(hub):
    store, hub = hub
    _script(store, "N", "exit 7\n")
    proof = _reviewed(store)  # v1 freezes a failing program
    _script(store, "N", "exit 0\n")  # the working copy now passes — v1 did not
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0
    assert result["evidence"] is None and "inputs differ from snapshot v1" in result["note"] and "not recorded" in result["note"]
    assert "inputs differ from snapshot v1" in result["output"]  # said where the researcher reads the run, too
    assert list_evidence_checks(store, proof.id) == []


def test_the_first_run_after_a_snapshot_with_an_empty_out_records_evidence(hub):
    """Evidence rule 1: only the inputs are compared. The snapshot froze no output; the run writes one; it still counts."""
    store, hub = hub
    (store.root / "proofs" / "N" / "out").mkdir(exist_ok=True)
    _script(store, "N", "mkdir -p out\necho 'n,ratio' > out/table.csv\nexit 0\n")
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["evidence"]["outcome"] == "passed" and result["note"] == ""
    (check,) = list_evidence_checks(store, proof.id)
    assert check.outcome.value == "passed"


def test_a_non_deterministic_output_still_records(hub):
    store, hub = hub
    _script(store, "N", "mkdir -p out\ndate +%s%N > out/stamp.txt\necho $$ >> out/stamp.txt\nexit 0\n")
    _post(hub, "/studio/N/api/run")  # an output to freeze
    proof = _reviewed(store)
    frozen = (store.root / "proofs" / "N" / "out" / "stamp.txt").read_text()
    for _ in range(2):
        assert _post(hub, "/studio/N/api/run")[1]["evidence"]["outcome"] == "passed"
    assert (store.root / "proofs" / "N" / "out" / "stamp.txt").read_text() != frozen  # the output moved; the check stands
    assert [c.outcome.value for c in list_evidence_checks(store, proof.id)] == ["passed", "passed"]


def test_a_python_run_that_writes_pycache_still_records(hub):
    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / "helper.py").write_text("VALUE = 1\n")
    _script(store, "N", f"unset PYTHONDONTWRITEBYTECODE\n'{sys.executable}' -c 'import helper, sys; sys.exit(0 if helper.VALUE == 1 else 1)'\n")
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert result["exit"] == 0 and (folder / "__pycache__").is_dir()  # the run wrote byte code beside its input
    assert result["evidence"]["outcome"] == "passed"
    assert _post(hub, "/studio/N/api/run")[1]["evidence"]["outcome"] == "passed"  # and again, with the cache now there
    assert len(list_evidence_checks(store, proof.id)) == 2


def test_an_input_edited_before_the_run_records_nothing_but_the_run_still_executes(hub):
    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / "data.csv").write_text("n\n1\n")
    _script(store, "N", "mkdir -p out\ncp data.csv out/copy.csv\nexit 0\n")
    proof = _reviewed(store)
    (folder / "data.csv").write_text("n\n2\n")  # the data changed since v1 froze it
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0 and (folder / "out" / "copy.csv").read_text() == "n\n2\n"  # it ran
    assert result["evidence"] is None and "inputs differ from snapshot v1" in result["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_only_a_hidden_root_file_differing_from_the_snapshot_records_nothing(hub):
    """A hidden environment file at the node root (`.python-version`) is an input the snapshot froze (#146)."""
    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / ".python-version").write_text("3.11\n")
    _script(store, "N", "exit 0\n")
    proof = _reviewed(store)
    (folder / ".python-version").write_text("3.12\n")
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0
    assert result["evidence"] is None and "inputs differ from snapshot v1" in result["note"]
    assert list_evidence_checks(store, proof.id) == []
    (folder / ".python-version").write_text("3.11\n")  # put back as frozen: the next run counts
    assert _post(hub, "/studio/N/api/run")[1]["evidence"]["outcome"] == "passed"


def test_an_unreadable_input_records_nothing_and_does_not_crash(hub):
    store, hub = hub
    folder = store.root / "proofs" / "N"
    _script(store, "N", "exit 0\n")
    (folder / "data.csv").write_text("n\n1\n")
    proof = _reviewed(store)
    (folder / "data.csv").chmod(0)
    try:
        status, result = _post(hub, "/studio/N/api/run")
    finally:
        (folder / "data.csv").chmod(0o644)
    assert status == 200 and result["exit"] == 0
    assert result["evidence"] is None and "could not be read" in result["note"] and "not recorded" in result["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_the_evidence_record_binds_the_snapshot_hash(hub):
    from proof_cli.authority import candidate_proof_sha256

    store, hub = hub
    _script(store, "N", "exit 0\n")
    proof = _reviewed(store)
    result = _post(hub, "/studio/N/api/run")[1]
    digest = candidate_proof_sha256(store, proof.id)
    assert digest and result["evidence"]["candidate_proof_sha256"] == digest
    (check,) = list_evidence_checks(store, proof.id)
    assert check.candidate_proof_sha256 == digest


# -- an exchanged computation node still runs (audit S2) -----------------------------------------------


def test_an_imported_computation_node_keeps_a_runnable_entry(hub, tmp_path):
    from proof_cli.exchange import bundle_to_json, export_exchange_bundle, import_exchange_bundle, parse_bundle

    store, hub = hub
    _script(store, "N", "exit 0\n")
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(store))))
    run = target.root / "proofs" / "N" / "run.sh"
    assert run.is_file() and os.access(run, os.X_OK)  # the entry's execute bit survives the bundle
    other = StudioHub(target)
    try:
        status, result = _post(other, "/studio/N/api/run")
        assert status == 200 and result["exit"] == 0
    finally:
        other.close()


def test_an_input_edited_during_the_run_and_put_back_is_still_not_the_snapshot_that_ran(hub):
    """Audit R-S1: the helper is changed while the program runs and restored before it ends — content as frozen, but
    not what ran. A touched input is seen by its stamp, and nothing is recorded."""
    import threading

    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / "scratch").mkdir()
    _script(store, "N", "touch scratch/started\nwhile [ ! -f scratch/go ]; do sleep 0.02; done\n"
                        f"'{sys.executable}' check.py\nrc=$?\ntouch scratch/checked\nwhile [ ! -f scratch/end ]; do sleep 0.02; done\nexit \"$rc\"\n")
    failing = "import sys\nsys.exit(7)\n"
    (folder / "check.py").write_text(failing)
    proof = _reviewed(store)  # v1 freezes the failing helper

    def _until(path: Path) -> None:
        deadline = time.monotonic() + 10
        while not path.exists():
            assert time.monotonic() < deadline, f"{path} never appeared"
            time.sleep(0.01)

    answer: dict = {}
    worker = threading.Thread(target=lambda: answer.update(_post(hub, "/studio/N/api/run")[1]))
    worker.start()
    _until(folder / "scratch" / "started")
    (folder / "check.py").write_text("import sys\nsys.exit(0)\n")  # edited while the program waits
    (folder / "scratch" / "go").touch()
    _until(folder / "scratch" / "checked")
    (folder / "check.py").write_text(failing)  # and undone before it ends
    (folder / "scratch" / "end").touch()
    worker.join(15)

    assert answer["exit"] == 0  # what ran was the edited helper
    assert answer["evidence"] is None and "changed during the run" in answer["note"] and "not recorded" in answer["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_a_passing_run_still_counts_when_only_its_outputs_were_written(hub):
    """The program writes out/ itself; that is not a touched input. Written again identically, the folder is still v2."""
    store, hub = hub
    _script(store, "N", "mkdir -p out\nprintf 'n,ratio\\n' > out/table.csv\nexit 0\n")
    _post(hub, "/studio/N/api/run")
    proof = _reviewed(store)
    time.sleep(0.02)
    status, result = _post(hub, "/studio/N/api/run")
    assert result["evidence"]["outcome"] == "passed" and list_evidence_checks(store, proof.id)[0].outcome.value == "passed"


def test_a_non_executable_entry_runs_by_the_interpreter_its_shebang_names(hub):
    """Audit R-S2: an entry that lost its execute bit is run as written — by its `#!` line — not forced through sh."""
    store, hub = hub
    run = store.root / "proofs" / "N" / "run.sh"
    run.write_text(f"#!{sys.executable}\nprint('computed by python')\n")
    run.chmod(0o644)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0 and "computed by python" in result["output"]
    run.write_text("echo computed by sh\n")  # no shebang: sh, as before
    assert "computed by sh" in _post(hub, "/studio/N/api/run")[1]["output"]


# -- the review of PR #147: refusals in the run-refusal shape, an encoded link, a capped output ----------------


def test_a_vscode_link_percent_encodes_the_path(hub):
    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / "a #1 ?.py").write_text("print(1)\n")
    status, result = _post(hub, "/studio/N/api/open", {"file": "a #1 ?.py", "line": 3})
    assert status == 200 and result["url"].endswith("/a%20%231%20%3F.py:3")
    assert "#" not in result["url"] and "?" not in result["url"] and " " not in result["url"]
    from urllib.parse import unquote
    assert unquote(result["url"].removeprefix("vscode://file/").rsplit(":", 1)[0]) == str((folder / "a #1 ?.py").resolve())


@pytest.mark.parametrize("line", ["forty", "4.5", -1, 0, True, [3], "²", "٣x"])
def test_a_bad_line_is_a_400_with_a_registered_code(hub, line):
    from proof_cli.errors import ERROR_CODES

    store, hub = hub
    (store.root / "proofs" / "N" / "check.py").write_text("print(1)\n")
    status, result = _post(hub, "/studio/N/api/open", {"file": "check.py", "line": line})
    assert status == 400 and result["code"] == "INVALID_LINE" and result["code"] in ERROR_CODES and result["error"]


def test_open_refusals_use_the_run_refusal_shape(hub):
    from proof_cli.errors import ERROR_CODES

    store, hub = hub
    status, result = _post(hub, "/studio/N/api/open", {"file": "../L/proof.tex"})
    assert status == 400 and result["code"] == "NOT_A_NODE_FILE" and "../L/proof.tex" in result["error"]
    (store.root / "proof.toml").write_text('[studio]\nopen_command = "sh -c \'exit 4\'"\n')
    status, result = _post(hub, "/studio/N/api/open")
    assert status == 502 and result["code"] == "OPEN_FAILED" and "exit 4" in result["error"]
    for code in ("NOT_A_COMPUTATION", "NOT_A_NODE_FILE", "OPEN_FAILED", "INVALID_LINE", "STUDIO_CLOSED", "NO_STUDIO", "CROSS_SITE"):
        assert code in ERROR_CODES, code


def test_a_closed_studio_refuses_a_run_in_the_run_refusal_shape(hub):
    store, hub = hub
    studio = hub.studio("N")
    studio.close()
    answer = studio.post("/api/run", {})
    assert answer.status == 503 and json.loads(answer.body) == {"error": "The studio is closed.", "code": "STUDIO_CLOSED"}


def test_a_chatty_run_keeps_only_the_tail_of_its_output(hub, monkeypatch):
    from proof_cli.studio import server as studio_server

    store, hub = hub
    monkeypatch.setattr(studio_server, "RUN_OUTPUT_LIMIT", 10_000)
    _script(store, "N", f"'{sys.executable}' -c \"import sys; [sys.stdout.write('line %d\\n' % i) for i in range(20000)]\"\necho LAST\n")
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0
    printed = result["output"].split("\n\n[no snapshot yet")[0]  # what the program printed, before the Evidence note
    assert printed.rstrip().endswith("LAST") and "line 0\n" not in printed
    assert "earlier output dropped" in result["output"] and len(result["output"]) < 11_000


# -- the second review round: why a run was not recorded, one error shape, a linear output cap -------------


def test_a_run_against_a_snapshot_that_cannot_be_read_says_so(hub):
    import shutil

    store, hub = hub
    _script(store, "N", "exit 0\n")
    proof = _reviewed(store)
    shutil.rmtree(store.root / "proofs" / "N" / "snapshots" / "v1")
    result = _post(hub, "/studio/N/api/run")[1]
    assert result["exit"] == 0 and result["evidence"] is None
    assert "snapshot v1 can't be read" in result["note"] and "differ" not in result["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_a_run_that_writes_outside_out_names_the_path(hub):
    store, hub = hub
    _script(store, "N", "mkdir -p results\necho 1 > results/table.csv\nexit 0\n")
    proof = _reviewed(store)
    result = _post(hub, "/studio/N/api/run")[1]
    assert result["evidence"] is None
    assert "the run wrote outside out/ (results/table.csv), which changed its inputs" in result["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_the_run_binds_the_hash_it_compared_against(hub, monkeypatch):
    """The bound hash is the one read with the frozen inputs, handed to the record (and checked there)."""
    from proof_cli import proof_map

    store, hub = hub
    _script(store, "N", "exit 0\n")
    proof = _reviewed(store)
    seen = {}
    real = proof_map.record_evidence_check

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(proof_map, "record_evidence_check", spy)
    result = _post(hub, "/studio/N/api/run")[1]
    assert seen["snapshot_sha256"] == result["evidence"]["candidate_proof_sha256"] == proof.sha256


def test_the_output_cap_keeps_the_tail_of_many_small_chunks_in_linear_time():
    from proof_cli.studio.build import _Tail

    class Chunks:
        def __init__(self, n, size):
            self.left, self.size, self.i = n, size, 0

        def read(self, _):
            if not self.left:
                return b""
            self.left -= 1
            self.i += 1
            return (b"%09d" % self.i).ljust(self.size, b".")

    limit, n, size = 8 * 1024 * 1024, 60_000, 1024  # 60 MB through the 8 MB bound, a kilobyte at a time
    tail = _Tail(limit)
    t0 = time.monotonic()
    tail.drain(Chunks(n, size))
    out = tail.text()
    assert time.monotonic() - t0 < 5  # trimming the front of one big buffer per chunk would take minutes
    assert tail.dropped == n * size - limit
    body = out.split("]\n", 1)[1]
    assert len(body) == limit and body.endswith((b"%09d" % n).ljust(size, b".").decode())
    assert out.startswith(f"[… {n * size - limit} bytes of earlier output dropped")


def test_a_closed_hub_answers_in_the_one_studio_error_shape(hub):
    store, hub = hub
    hub.close()
    status, body = _post(hub, "/studio/N/api/run")
    assert status == 503 and body == {"error": "the proof map's server is shutting down", "code": "STUDIO_CLOSED"}


def test_every_code_a_studio_answers_with_is_registered():
    import ast
    import re

    from proof_cli.errors import ERROR_CODES

    src = Path(__file__).resolve().parents[1] / "src" / "proof_cli"
    found = {}
    for path in (src / "studio" / "server.py", src / "webapp" / "studios.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) if isinstance(node, ast.Call) else None
            if name in ("_err", "_Refused", "_error", "NoStudio"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", arg.value):
                        found[arg.value] = f"{path.name}:{node.lineno}"
    assert len(found) > 10 and not {code: at for code, at in found.items() if code not in ERROR_CODES}


def test_a_studio_error_is_one_shape(hub):
    store, hub = hub
    for status, body in (_get(hub, "/studio/N/api/nothing-here"), _get(hub, "/studio/N/api/file"),
                         _post(hub, "/studio/N/api/agent/stop", {}), _get(hub, "/studio/N/pdf")):
        assert status >= 400 and set(body) == {"error", "code"}, body


# -- after #146's roles: the summary and secrets are no inputs; a link is no crash -------------------------


def test_a_key_ideas_only_edit_after_the_snapshot_does_not_block_recording(hub):
    store, hub = hub
    _script(store, "N", "exit 0\n")
    proof = _reviewed(store)
    summary = store.root / "proofs" / "N" / "key-ideas.md"
    summary.write_text(summary.read_text() + "\nA sharper sentence about the main step.\n")  # role "summary", not "input"
    result = _post(hub, "/studio/N/api/run")[1]
    assert result["evidence"]["outcome"] == "passed" and result["note"] == ""
    assert [c.outcome.value for c in list_evidence_checks(store, proof.id)] == ["passed"]


def test_a_dotenv_file_is_never_frozen_and_never_moves_the_inputs_digest(hub):
    from proof_cli.domain import Medium
    from proof_cli.vault import working_inputs_digest

    store, hub = hub
    folder = store.root / "proofs" / "N"
    _script(store, "N", "exit 0\n")
    before = working_inputs_digest(store.root, "N", Medium.computation)
    (folder / ".env").write_text("API_TOKEN=secret\n")
    assert working_inputs_digest(store.root, "N", Medium.computation) == before
    proof = _reviewed(store)
    assert not list((store.root / proof.file_path).parent.rglob(".env"))  # never frozen
    (folder / ".env").write_text("API_TOKEN=another\n")  # and changing it changes no input
    assert _post(hub, "/studio/N/api/run")[1]["evidence"]["outcome"] == "passed"


def test_a_symlink_appearing_during_the_run_records_nothing_and_does_not_crash(hub):
    store, hub = hub
    _script(store, "N", "ln -s run.sh alias.sh\nexit 0\n")
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["exit"] == 0 and result["evidence"] is None
    assert "alias.sh" in result["note"] and "symbolic link" in result["note"] and "not recorded" in result["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_frozen_digests_agree_with_the_vaults_own(hub):
    from proof_cli.vault import frozen_digests, frozen_inputs_digest, snapshot_folder_digest

    store, hub = hub
    folder = store.root / "proofs" / "N"
    (folder / "out").mkdir()
    (folder / "out" / "t.csv").write_text("n\n")
    (folder / ".python-version").write_text("3.11\n")
    _script(store, "N", "exit 0\n")
    snapshot = (store.root / _reviewed(store).file_path).parent
    assert frozen_digests(snapshot) == (snapshot_folder_digest(snapshot), frozen_inputs_digest(snapshot))
