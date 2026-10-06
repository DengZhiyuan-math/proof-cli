"""The project list (ADR-0017) under several writers at once: the Home, `proof init` and `proof map open` in
other processes. Each change is one locked transaction, so none is lost (review of ADR-0018)."""

import json
import subprocess
import sys
import time
from pathlib import Path

import proof_cli
from proof_cli.projects import forget_project, list_registered, project_key, projects_file, register_project

CORE_SRC = Path(proof_cli.__file__).resolve().parents[1]
WRITER = """
import sys, time
from proof_cli.projects import register_project
start, who, n = float(sys.argv[1]), sys.argv[2], int(sys.argv[3])
time.sleep(max(0.0, start - time.time()))
for k in range(n):
    register_project(f"/projects/{who}/{k}", opened=(k % 2 == 0))
"""


def test_registrations_from_many_processes_at_once_are_all_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(CORE_SRC))
    writers, per_writer = 8, 6
    start = time.time() + 0.5
    procs = [subprocess.Popen([sys.executable, "-c", WRITER, str(start), f"w{i}", str(per_writer)]) for i in range(writers)]
    for proc in procs:
        assert proc.wait(60) == 0

    listed = {entry["path"] for entry in list_registered()}
    assert listed == {project_key(f"/projects/w{i}/{k}") for i in range(writers) for k in range(per_writer)}
    assert json.loads(projects_file().read_text())["projects"]  # one well-formed file, no stray temporary files beside it
    assert [p.name for p in projects_file().parent.iterdir() if p.suffix == ".tmp"] == []


def test_a_registration_and_a_forget_in_this_process_keep_the_rest(tmp_path):
    for k in range(3):
        register_project(f"/projects/local/{k}")
    assert forget_project("/projects/local/1") and not forget_project("/projects/local/1")
    assert {e["path"] for e in list_registered()} == {project_key("/projects/local/0"), project_key("/projects/local/2")}
