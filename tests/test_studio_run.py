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
    assert status == 409 and result["error"] == "NOT_A_COMPUTATION"


def test_a_run_is_stopped_from_another_request(hub):
    import threading
    import time

    store, hub = hub
    _script(store, "N", "sleep 30\n")
    _reviewed(store)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(result=_post(hub, "/studio/N/api/run")[1]))
    worker.start()
    for _ in range(100):
        if _post(hub, "/studio/N/api/run/stop")[1]["stopped"]:
            break
        time.sleep(0.05)
    worker.join(timeout=10)
    assert outcome["result"]["cancelled"] is True and outcome["result"]["evidence"]["outcome"] == "error"


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


def test_a_run_that_outlives_the_time_limit_is_recorded_as_an_error_not_as_stopped(hub, monkeypatch):
    from proof_cli.studio import server as studio_server

    store, hub = hub
    monkeypatch.setattr(studio_server, "RUN_TIMEOUT", 1.0)
    _script(store, "N", "sleep 20\n")
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert status == 200 and result["timed_out"] is True and result["cancelled"] is False and result["exit"] is None
    assert "longer than 1 seconds" in result["output"]
    (check,) = list_evidence_checks(store, proof.id)
    assert check.outcome.value == "error" and "timed out" in check.notes


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
    assert _post(hub, "/studio/N/api/open", {"file": "../L/proof.tex"})[1]["ok"] is False
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
    assert result["evidence"] is None and "differs from snapshot v1" in result["note"]
    assert list_evidence_checks(store, proof.id) == []


def test_a_run_counts_only_when_the_folder_matches_the_snapshot_before_and_after(hub):
    store, hub = hub
    _script(store, "N", "mkdir -p out\necho 'n,ratio' > out/table.csv\nexit 0\n")  # writes an output the snapshot did not hold
    proof = _reviewed(store)
    status, result = _post(hub, "/studio/N/api/run")
    assert result["evidence"] is None and "changed during the run" in result["note"]  # out/table.csv appeared: the folder is no longer v1
    assert list_evidence_checks(store, proof.id) == []
    proof2 = request_review(store, "N", requested_by="agent_a", rationale="with its output")
    status, again = _post(hub, "/studio/N/api/run")  # the same output is written again: the folder still matches v2
    assert again["evidence"]["outcome"] == "passed"
    (check,) = list_evidence_checks(store, proof2.id)
    assert check.outcome.value == "passed"


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
