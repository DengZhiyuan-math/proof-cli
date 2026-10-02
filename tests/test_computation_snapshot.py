"""What a computation node's Review snapshot freezes (spec #145, review of PR #146).

The researcher's rule (2026-10-02): a computation's snapshot freezes its inputs — its scripts, its
hidden environment files, its data — and its outputs in `out/`; `out/` and `__pycache__` are not
inputs. A later Run counts as Evidence only when its inputs match the frozen ones (#147), so the
snapshot must freeze the inputs completely and faithfully, executable bits included, and say
which frozen paths are inputs. A LaTeX snapshot is frozen and hashed exactly as before.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof, write_key_ideas
from proof_cli import errors
from proof_cli.authority import candidate_proof_sha256
from proof_cli.cli import app
from proof_cli.domain import Medium
from proof_cli.exchange import bundle_to_json, export_exchange_bundle, import_exchange_bundle, parse_bundle
from proof_cli.proof_map import ProofMapError, create_node, request_review
from proof_cli.storage import ensure_project, list_all_candidate_proofs
from proof_cli.vault import (
    frozen_inputs_digest,
    frozen_role,
    manifest_digest,
    snapshot_folder_digest,
    snapshot_folder_files,
    working_inputs_digest,
)

runner = CliRunner()
as_root = pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a mode-000 file")


def _computation(store, node_id="c1"):
    """A computation node with a program, an output and a filled key-ideas summary: ready for review."""
    create_node(store, node_id=node_id, kind="claim", statement=f"statement of {node_id}", medium="computation")
    folder = store.root / "proofs" / node_id
    (folder / "run.sh").write_text("#!/usr/bin/env bash\npython3 check.py > out/table.csv\n")
    (folder / "check.py").write_text("print('n,ratio')\n")
    (folder / "out").mkdir()
    (folder / "out" / "table.csv").write_text("n,ratio\n10000,0.9999\n")
    write_key_ideas(store, node_id)
    return folder


def _review(store, node_id="c1"):
    return request_review(store, node_id, requested_by="agent_a", rationale="every case is covered")


def _snapshot(store, proof) -> Path:
    return (store.root / proof.file_path).parent


def _manifest(store, proof) -> dict:
    return json.loads((store.root / proof.file_path).read_text())


# -- an unreadable file is refused, and nothing is written -------------------------------------------


@as_root
@pytest.mark.parametrize("where", ["out/locked.bin", "check.py"])
def test_an_unreadable_file_in_the_node_folder_is_refused_and_nothing_is_written(tmp_path: Path, where: str):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    locked = folder / where
    locked.write_bytes(b"secret")
    locked.chmod(0)
    try:
        with pytest.raises(ProofMapError) as caught:
            _review(store)
    finally:
        locked.chmod(0o644)
    assert caught.value.code == "WORKING_FILE_UNREADABLE"
    assert caught.value.details["path"] == f"proofs/c1/{where}"
    assert not (folder / "snapshots").exists() and list_all_candidate_proofs(store) == []


@as_root
def test_an_unreadable_folder_in_the_node_folder_is_refused_rather_than_skipped(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "data").mkdir()
    (folder / "data" / "cases.txt").write_text("1\n2\n")
    (folder / "data").chmod(0)
    try:
        with pytest.raises(ProofMapError) as caught:
            _review(store)
    finally:
        (folder / "data").chmod(0o755)
    assert caught.value.code == "WORKING_FILE_UNREADABLE" and caught.value.details["path"] == "proofs/c1/data"
    assert not (folder / "snapshots").exists()


@as_root
def test_the_cli_answers_an_unreadable_file_with_its_code_not_an_internal_error(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "out" / "locked.bin").write_bytes(b"x")
    (folder / "out" / "locked.bin").chmod(0)
    try:
        result = runner.invoke(app, ["node", "request-review", "c1", "--rationale", "r", "--root", str(tmp_path), "--json"])
    finally:
        (folder / "out" / "locked.bin").chmod(0o644)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "WORKING_FILE_UNREADABLE"
    assert "WORKING_FILE_UNREADABLE" in errors.ERROR_CODES


# -- the inputs, frozen completely ---------------------------------------------------------------------


def test_hidden_environment_files_at_the_node_root_are_frozen(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    for name in (".python-version", ".envrc", ".tool-versions"):
        (folder / name).write_text("3.11\n")
    frozen = snapshot_folder_files(_snapshot(store, _review(store)))
    assert {".python-version", ".envrc", ".tool-versions"} <= set(frozen)


def test_vcs_folders_tool_caches_and_bytecode_are_never_frozen(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    for rel in (".git/HEAD", ".pytest_cache/v/cache", ".venv/bin/python", "__pycache__/check.cpython-311.pyc",
                "lib/__pycache__/util.cpython-311.pyc", "out/__pycache__/x.pyc", "lib/stale.pyc", ".DS_Store"):
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(b"cache")
    (folder / "lib" / "util.py").write_text("X = 1\n")
    frozen = snapshot_folder_files(_snapshot(store, _review(store)))
    assert set(frozen) == {"run.sh", "check.py", "lib/util.py", "out/table.csv", "key-ideas.md"}


def test_a_computation_snapshot_does_not_freeze_the_shared_preamble(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="t1", kind="claim", statement="a written proof")  # makes proofs/preamble.tex
    _computation(store)
    proof = _review(store)
    assert "../preamble.tex" not in snapshot_folder_files(_snapshot(store, proof))
    # so a preamble edit is no new program version
    (tmp_path / "proofs" / "preamble.tex").write_text("% edited\n")
    with pytest.raises(ProofMapError) as caught:
        _review(store)
    assert caught.value.code == "WORKING_PROOF_UNCHANGED"


def test_a_latex_snapshot_still_freezes_the_preamble_and_no_hidden_file(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="t1", kind="claim", statement="a written proof")
    (tmp_path / "proofs" / "t1" / ".latexmkrc").write_text("$pdf_mode = 1;\n")
    proof = submit_proof(store, "t1", claimant_id="agent_a", scoping_rationale="r", content="\\begin{proof}ok\\end{proof}\n")
    assert set(snapshot_folder_files(_snapshot(store, proof))) == {"proof.tex", "key-ideas.md", "../preamble.tex"}


# -- the executable bit ---------------------------------------------------------------------------------


def test_the_executable_bit_of_a_script_is_frozen_recorded_and_hashed(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "run.sh").chmod(0o755)
    (folder / "check.py").chmod(0o644)
    proof = _review(store)
    stored = _snapshot(store, proof) / "node"
    assert os.access(stored / "run.sh", os.X_OK) and not os.access(stored / "check.py", os.X_OK)
    assert _manifest(store, proof)["executable"] == ["run.sh"]
    # the mode is part of the hash: losing it is a new version, not an unchanged proof
    (folder / "run.sh").chmod(0o644)
    assert _review(store).sha256 != proof.sha256


def test_editing_a_snapshots_recorded_modes_breaks_its_hash(tmp_path: Path):
    store = ensure_project(tmp_path)
    _computation(store)
    proof = _review(store)
    manifest_path = store.root / proof.file_path
    manifest = json.loads(manifest_path.read_text())
    manifest["executable"] = []
    manifest_path.write_text(json.dumps(manifest))
    assert candidate_proof_sha256(store, proof.id) != proof.sha256


def test_an_exchanged_computation_snapshot_verifies_and_keeps_its_hidden_files_and_modes(tmp_path: Path):
    source = ensure_project(tmp_path / "source")
    folder = _computation(source)
    (folder / ".python-version").write_text("3.11\n")
    proof = _review(source)
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(source))))
    assert candidate_proof_sha256(target, proof.id) == proof.sha256
    assert os.access(target.root / "proofs" / "c1" / "run.sh", os.X_OK)
    assert os.access(_snapshot(target, proof) / "node" / "run.sh", os.X_OK)
    assert (target.root / "proofs" / "c1" / ".python-version").is_file()


# -- a LaTeX snapshot, and a snapshot from before, verify as they did -------------------------------------


def test_a_latex_snapshot_is_hashed_as_before(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="t1", kind="claim", statement="a written proof")
    proof_tex = tmp_path / "proofs" / "t1" / "proof.tex"
    proof_tex.chmod(0o755)  # an executable bit on a LaTeX source means nothing, and is not recorded
    proof = submit_proof(store, "t1", claimant_id="agent_a", scoping_rationale="r", content="\\begin{proof}ok\\end{proof}\n")
    files = snapshot_folder_files(_snapshot(store, proof))
    assert proof.sha256 == manifest_digest({rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()})
    assert _manifest(store, proof).get("executable", []) == []


def test_a_snapshot_with_a_format_1_manifest_still_verifies(tmp_path: Path):
    folder = tmp_path / "v1"
    (folder / "node").mkdir(parents=True)
    (folder / "node" / "proof.tex").write_bytes(b"old proof")
    entries = {"proof.tex": hashlib.sha256(b"old proof").hexdigest()}
    (folder / "manifest.json").write_text(json.dumps({"format": 1, "files": entries}))
    assert snapshot_folder_digest(folder) == manifest_digest(entries)


# -- inputs and outputs ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "role"),
    [("run.sh", "input"), ("check.py", "input"), (".python-version", "input"), ("data/cases.txt", "input"),
     ("key-ideas.md", "input"), ("outline.txt", "input"), ("out/table.csv", "output"), ("out/fig/a.png", "output")],
)
def test_each_frozen_path_is_an_input_or_an_output(path: str, role: str):
    assert frozen_role(path) == role


def test_the_inputs_digest_ignores_out_and_sees_every_input_and_its_mode(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    snapshot = _snapshot(store, _review(store))
    frozen = frozen_inputs_digest(snapshot)
    assert frozen == working_inputs_digest(tmp_path, "c1", Medium.computation)
    (folder / "out" / "table.csv").write_text("n,ratio\n10000,0.5\n")  # a later run's output
    (folder / "out" / "extra.log").write_text("ran\n")
    assert working_inputs_digest(tmp_path, "c1", Medium.computation) == frozen
    (folder / "run.sh").chmod(0o644)
    assert working_inputs_digest(tmp_path, "c1", Medium.computation) != frozen
    (folder / "run.sh").chmod(0o755)
    (folder / "check.py").write_text("print('changed')\n")
    assert working_inputs_digest(tmp_path, "c1", Medium.computation) != frozen


# -- a large out/ is a notice, never a refusal ----------------------------------------------------------------


def _request_review_json(root: Path) -> dict:
    result = runner.invoke(app, ["node", "request-review", "c1", "--rationale", "covered", "--root", str(root), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["data"]


def test_a_large_frozen_out_folder_is_a_registered_notice_with_a_configurable_threshold(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "out" / "data.bin").write_bytes(b"x" * 4096)
    (tmp_path / "proof.toml").write_text("[snapshot]\nlarge_output_mb = 0.002\n")  # 2097 bytes
    data = _request_review_json(tmp_path)
    assert data["version"] == 1
    (notice,) = data["notices"]
    frozen = sum(len(b) for rel, b in snapshot_folder_files(folder / "snapshots" / "v1").items() if rel.startswith("out/"))
    assert notice["code"] == "SNAPSHOT_LARGE_OUTPUT" and notice["output_bytes"] == frozen
    assert notice["threshold_bytes"] == int(0.002 * 1024 * 1024)
    assert "SNAPSHOT_LARGE_OUTPUT" in errors.NOTICE_CODES


def test_what_is_not_frozen_does_not_count_toward_a_large_output(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "out" / "__pycache__").mkdir()
    (folder / "out" / "__pycache__" / "big.pyc").write_bytes(b"x" * 8192)  # never frozen
    (tmp_path / "proof.toml").write_text("[snapshot]\nlarge_output_mb = 0.002\n")
    assert _request_review_json(tmp_path)["notices"] == []


def test_the_large_output_notice_defaults_to_50_mb_and_prints_in_text_mode(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "out" / "data.bin").write_bytes(b"x" * 4096)
    assert _request_review_json(tmp_path)["notices"] == []  # under 50 MB
    (folder / "out" / "more.bin").write_bytes(b"y" * 4096)
    (tmp_path / "proof.toml").write_text("[snapshot]\nlarge_output_mb = 0.002\n")
    result = runner.invoke(app, ["node", "request-review", "c1", "--rationale", "covered", "--root", str(tmp_path)])
    assert result.exit_code == 0 and "SNAPSHOT_LARGE_OUTPUT" in result.output
