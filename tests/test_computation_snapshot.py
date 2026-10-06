"""What a computation node's Review snapshot freezes (spec #145, review of PR #146).

The researcher's rule (2026-10-02): a computation's snapshot freezes its inputs — its scripts, its
hidden environment files, its data — and its outputs in `out/`; `out/` and `__pycache__` are not
inputs. A later Run counts as Evidence only when its inputs match the frozen ones (#147), so the
snapshot must freeze the inputs completely and faithfully, executable bits included, and say
which frozen paths are inputs. A LaTeX snapshot is frozen and hashed exactly as before.
"""

import ast
import base64
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
    HIDDEN_INPUTS,
    frozen_inputs_digest,
    frozen_role,
    manifest_digest,
    snapshot_folder_digest,
    snapshot_folder_files,
    working_inputs_digest,
)

runner = CliRunner()
needs_posix_modes = pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not Windows ACLs")
needs_permissions = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="chmod 000 needs POSIX permissions and a non-root reader",
)


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


@needs_permissions
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


@needs_permissions
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


@needs_permissions
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


@pytest.mark.parametrize("name", sorted(HIDDEN_INPUTS))
def test_each_allowlisted_environment_file_at_the_node_root_is_frozen(tmp_path: Path, name: str):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / name).write_text("3.11\n")
    assert name in snapshot_folder_files(_snapshot(store, _review(store)))


def test_the_allowlist_is_exactly_the_researchers(tmp_path: Path):
    assert HIDDEN_INPUTS == {".python-version", ".tool-versions", ".nvmrc", ".node-version", ".ruby-version"}


SECRET = "MARKER-7f3a9c-do-not-leak"


def _plant_secrets(folder: Path) -> None:
    for name in (".env", ".env.local", ".envrc", ".netrc", ".foo"):
        (folder / name).write_text(f"TOKEN={SECRET}\n")
    (folder / "lib").mkdir(exist_ok=True)
    (folder / "lib" / ".python-version").write_text("3.11\n")  # allowlisted only at the root


def test_secrets_and_unknown_dotfiles_are_not_frozen_and_only_their_paths_are_reported(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    _plant_secrets(folder)
    (folder / ".cache" / "deep").mkdir(parents=True)
    (folder / ".cache" / "deep" / "x").write_text(SECRET)
    result = runner.invoke(app, ["node", "request-review", "c1", "--rationale", "r", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert SECRET not in result.stdout
    data = json.loads(result.stdout)["data"]
    frozen = snapshot_folder_files(folder / "snapshots" / "v1")
    assert not {".env", ".env.local", ".envrc", ".netrc", ".foo", "lib/.python-version"} & set(frozen)
    assert not any(rel.startswith(".cache") for rel in frozen)
    (notice,) = [n for n in data["notices"] if n["code"] == "SNAPSHOT_SKIPPED_HIDDEN"]
    assert notice["paths"] == [".cache/", ".env", ".env.local", ".envrc", ".foo", ".netrc", "lib/.python-version"]
    assert all(SECRET not in json.dumps(n) for n in data["notices"])


def test_skipped_hidden_paths_are_printed_in_text_mode(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / ".env").write_text(f"TOKEN={SECRET}\n")
    result = runner.invoke(app, ["node", "request-review", "c1", "--rationale", "r", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "SNAPSHOT_SKIPPED_HIDDEN" in result.output and ".env" in result.output and SECRET not in result.output


@pytest.mark.parametrize("name", [".env", ".env.production", ".envrc", ".netrc"])
def test_a_secret_is_denied_even_if_it_were_allowlisted(tmp_path: Path, monkeypatch, name: str):
    from proof_cli import vault

    monkeypatch.setattr(vault, "HIDDEN_INPUTS", vault.HIDDEN_INPUTS | {name})
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / name).write_text(SECRET)
    assert name not in snapshot_folder_files(_snapshot(store, _review(store)))
    bundle = bundle_to_json(export_exchange_bundle(store))
    assert SECRET not in bundle and base64.b64encode(SECRET.encode()).decode() not in bundle


def test_a_latex_node_freezes_no_hidden_file_either(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="t1", kind="claim", statement="a written proof")
    (tmp_path / "proofs" / "t1" / ".python-version").write_text("3.11\n")
    proof = submit_proof(store, "t1", claimant_id="agent_a", scoping_rationale="r", content="\\begin{proof}ok\\end{proof}\n")
    assert ".python-version" not in snapshot_folder_files(_snapshot(store, proof))


# -- a snapshot frozen before the allowlist: its secrets never leave in an export ---------------------------


def _old_snapshot_with_secrets(store, monkeypatch):
    """A computation snapshot frozen by the rule before the allowlist, which froze every root dotfile."""
    from proof_cli import vault

    folder = _computation(store)
    (folder / ".env").write_text(f"API_KEY={SECRET}\n")
    (folder / ".netrc").write_text(f"machine example.org password {SECRET}\n")
    (folder / ".python-version").write_text("3.11\n")
    with monkeypatch.context() as old:
        old.setattr(vault, "is_secret_path", lambda rel: False)
        old.setattr(vault, "HIDDEN_INPUTS", frozenset({".env", ".netrc", ".python-version"}))
        proof = _review(store)
    assert {".env", ".netrc"} <= set(snapshot_folder_files(_snapshot(store, proof)))
    (folder / ".env").unlink()
    (folder / ".netrc").unlink()
    return proof


def test_exporting_an_old_snapshot_leaves_its_secrets_out_and_says_it_no_longer_verifies(tmp_path: Path, monkeypatch):
    source = ensure_project(tmp_path / "source")
    proof = _old_snapshot_with_secrets(source, monkeypatch)
    raw = bundle_to_json(export_exchange_bundle(source))
    assert SECRET not in raw and base64.b64encode(SECRET.encode()).decode()[:16] not in raw
    bundle = parse_bundle(raw)
    assert not any(Path(f.path).name in (".env", ".netrc") for f in bundle.vault_files)
    assert any(f.path.endswith("/node/.python-version") for f in bundle.vault_files)
    (notice,) = bundle.notices
    assert notice["code"] == "SNAPSHOT_EXPORTED_UNVERIFIABLE" and notice["node_id"] == "c1" and notice["version"] == proof.version
    assert "SNAPSHOT_EXPORTED_UNVERIFIABLE" in errors.NOTICE_CODES


def test_importing_a_bundle_with_a_withheld_snapshot_reads_it_unverifiable_and_does_not_crash(tmp_path: Path, monkeypatch):
    source = ensure_project(tmp_path / "source")
    proof = _old_snapshot_with_secrets(source, monkeypatch)
    target = ensure_project(tmp_path / "target")
    report = import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(source))))
    assert candidate_proof_sha256(target, proof.id) is None  # unverifiable here, as a lost snapshot is
    assert any("c1" in warning and "unverifiable" in warning for warning in report.warnings)
    assert not (target.root / "proofs" / "c1" / "snapshots" / f"v{proof.version}" / "node" / ".env").exists()


def test_a_bundle_whose_snapshot_misses_a_file_it_did_not_declare_withheld_is_still_refused(tmp_path: Path):
    source = ensure_project(tmp_path / "source")
    _computation(source)
    _review(source)
    raw = json.loads(bundle_to_json(export_exchange_bundle(source)))
    raw["vault_files"] = [f for f in raw["vault_files"] if not f["path"].endswith("/node/check.py")]
    target = ensure_project(tmp_path / "target")
    with pytest.raises(ProofMapError) as caught:
        import_exchange_bundle(target, raw)
    assert caught.value.code == "VAULT_FILE_MISSING"


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


@needs_posix_modes
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
    manifest["executable"] = ["check.py"]
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
     ("key-ideas.md", "summary"), ("notes/key-ideas.md", "input"), ("outline.txt", "input"),
     ("out/table.csv", "output"), ("out/fig/a.png", "output"), ("../preamble.tex", "input")],
)
def test_each_frozen_path_is_an_input_an_output_or_the_summary(path: str, role: str):
    assert frozen_role(path) == role


def test_a_summary_only_edit_leaves_the_inputs_digest_unchanged(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    frozen = frozen_inputs_digest(_snapshot(store, _review(store)))
    (folder / "key-ideas.md").write_text((folder / "key-ideas.md").read_text() + "\nOne more remark.\n")
    assert working_inputs_digest(tmp_path, "c1", Medium.computation) == frozen


@needs_posix_modes
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


# -- an export walks the node folder as a snapshot does ------------------------------------------------------


def test_an_export_carries_no_tool_cache_or_bytecode(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "check.cpython-311.pyc").write_bytes(b"\0")
    (folder / "lib.pyc").write_bytes(b"\0")
    _review(store)
    paths = [f.path for f in export_exchange_bundle(store).vault_files]
    assert not any("__pycache__" in path or path.endswith(".pyc") for path in paths)
    assert "proofs/c1/run.sh" in paths and "proofs/c1/out/table.csv" in paths


@needs_permissions
def test_an_export_reports_an_unreadable_folder_rather_than_skipping_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (folder / "data").mkdir()
    (folder / "data").chmod(0)
    try:
        with pytest.raises(ProofMapError) as caught:
            export_exchange_bundle(store)
    finally:
        (folder / "data").chmod(0o755)
    assert caught.value.code == "WORKING_FILE_UNREADABLE" and caught.value.details["path"] == "proofs/c1/data"


# -- symbolic links: refused, in a snapshot and an export alike ---------------------------------------------


@pytest.mark.parametrize("dangling", [False, True], ids=["link", "dangling-link"])
def test_a_symbolic_link_in_the_node_folder_is_refused_by_review_and_export(tmp_path: Path, dangling: bool):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    target = tmp_path / ("missing.txt" if dangling else "elsewhere.txt")
    if not dangling:
        target.write_text("outside the node folder\n")
    (folder / "data.txt").symlink_to(target)
    with pytest.raises(ProofMapError) as caught:
        _review(store)
    assert caught.value.code == "NODE_FOLDER_SYMLINK"
    (link,) = caught.value.details["links"]
    assert link["path"] == "proofs/c1/data.txt" and link["dangling"] is dangling
    assert not (folder / "snapshots").exists()
    with pytest.raises(ProofMapError) as exported:
        export_exchange_bundle(store)
    assert exported.value.code == "NODE_FOLDER_SYMLINK"
    assert "NODE_FOLDER_SYMLINK" in errors.ERROR_CODES


def test_a_linked_folder_in_the_node_folder_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation(store)
    (tmp_path / "shared-data").mkdir()
    (folder / "data").symlink_to(tmp_path / "shared-data", target_is_directory=True)
    with pytest.raises(ProofMapError) as caught:
        _review(store)
    assert caught.value.code == "NODE_FOLDER_SYMLINK" and caught.value.details["links"][0]["path"] == "proofs/c1/data"


# -- verification checks the manifest's format and the stored modes ----------------------------------------


@pytest.mark.parametrize("fmt", [None, 0, 3, "2"])
def test_a_manifest_of_an_unknown_format_is_unverifiable(tmp_path: Path, fmt):
    store = ensure_project(tmp_path)
    _computation(store)
    proof = _review(store)
    manifest_path = store.root / proof.file_path
    manifest = json.loads(manifest_path.read_text())
    if fmt is None:
        del manifest["format"]
    else:
        manifest["format"] = fmt
    manifest_path.write_text(json.dumps(manifest))
    assert candidate_proof_sha256(store, proof.id) is None


@needs_posix_modes
def test_a_stored_script_that_lost_its_executable_bit_is_unverifiable(tmp_path: Path):
    store = ensure_project(tmp_path)
    _computation(store)
    proof = _review(store)
    assert candidate_proof_sha256(store, proof.id) == proof.sha256
    (_snapshot(store, proof) / "node" / "run.sh").chmod(0o644)
    assert candidate_proof_sha256(store, proof.id) is None


@needs_posix_modes
def test_import_sets_an_executable_bit_only_where_the_file_is_readable(tmp_path: Path):
    source = ensure_project(tmp_path / "source")
    _computation(source)
    proof = _review(source)
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(source))))
    for path in (target.root / "proofs" / "c1" / "run.sh", _snapshot(target, proof) / "node" / "run.sh"):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & stat.S_IXUSR
        assert bool(mode & stat.S_IXGRP) == bool(mode & stat.S_IRGRP)
        assert bool(mode & stat.S_IXOTH) == bool(mode & stat.S_IROTH)
        assert not mode & (stat.S_IWGRP | stat.S_IWOTH)


# -- every notice code emitted is registered ---------------------------------------------------------------


def test_every_notice_code_the_code_emits_is_registered():
    src = Path(errors.__file__).parent
    emitted: dict[str, str] = {}
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) == "notice":
                first = node.args[0] if node.args else None
                assert isinstance(first, ast.Constant), f"{path.name}:{node.lineno}: a notice's code is a literal"
                emitted[first.value] = f"{path.name}:{node.lineno}"
            elif isinstance(node, ast.Dict):
                # a hand-written {"code": X, …} is a notice too (an error is raised or carried under "error")
                fields = {key.value: value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant)}
                code = fields.get("code")
                if isinstance(code, ast.Constant) and isinstance(code.value, str) and "error" not in fields:
                    emitted[code.value] = f"{path.name}:{node.lineno}"
    assert {"SNAPSHOT_LARGE_OUTPUT", "SNAPSHOT_SKIPPED_HIDDEN", "SNAPSHOT_EXPORTED_UNVERIFIABLE"} <= set(emitted)
    unregistered = {code: where for code, where in emitted.items() if code not in errors.NOTICE_CODES}
    assert not unregistered, unregistered


def test_an_unregistered_notice_code_cannot_be_emitted():
    with pytest.raises(KeyError):
        errors.notice("NOT_A_NOTICE", "nothing")


# -- a withheld file leaves no content and no hash in an export (Q41) ----------------------------------------


def _traces(store) -> list[str]:
    """Every string that would betray the withheld secrets of `_old_snapshot_with_secrets`: their text, their
    SHA-256 (hex, and base64 of hex and of the raw digest), the secret in base64 at each alignment."""
    env = f"API_KEY={SECRET}\n".encode()
    netrc = f"machine example.org password {SECRET}\n".encode()
    traces = [SECRET]
    for data in (env, netrc):
        digest = hashlib.sha256(data)
        traces += [digest.hexdigest(), base64.b64encode(digest.digest()).decode(), base64.b64encode(digest.hexdigest().encode()).decode()[:40]]
    for pad in ("", "x", "xy"):
        traces.append(base64.b64encode((pad + SECRET).encode()).decode()[4:24])
    return traces


def _assert_no_trace(text: str, store, proof) -> None:
    for trace in _traces(store):
        assert trace not in text, trace
    assert proof.sha256 not in text  # the snapshot's own digest would let a guess at the secret be checked


def test_an_export_of_an_old_snapshot_carries_no_content_and_no_hash_of_what_it_withholds(tmp_path: Path, monkeypatch):
    source = ensure_project(tmp_path / "source")
    proof = _old_snapshot_with_secrets(source, monkeypatch)
    raw = bundle_to_json(export_exchange_bundle(source))
    _assert_no_trace(raw, source, proof)
    bundle = parse_bundle(raw)
    (manifest,) = [f for f in bundle.vault_files if f.path.endswith(f"/v{proof.version}/manifest.json")]
    carried = json.loads(base64.b64decode(manifest.content_base64))
    assert not {".env", ".netrc"} & set(carried["files"]) and not {".env", ".netrc"} & set(carried.get("executable", []))
    assert carried["unverifiable"]  # says why it can't verify
    assert {"proofs/c1/snapshots/v1/node/.env", "proofs/c1/snapshots/v1/node/.netrc"} <= set(bundle.withheld_files)  # paths only


@pytest.mark.parametrize("flags", [["--json"], ["--output", "bundle.json"], ["--output", "bundle.json", "--json"]], ids=["json", "output", "output-json"])
def test_the_cli_export_carries_no_trace_of_a_withheld_secret(tmp_path: Path, monkeypatch, flags):
    source = ensure_project(tmp_path / "source")
    proof = _old_snapshot_with_secrets(source, monkeypatch)
    flags = [str(tmp_path / f) if f.endswith(".json") else f for f in flags]
    result = runner.invoke(app, ["exchange", "export", "--root", str(source.root), *flags])
    assert result.exit_code == 0, result.output
    _assert_no_trace(result.output, source, proof)
    if "--output" in flags:
        _assert_no_trace((tmp_path / "bundle.json").read_text(), source, proof)


# -- the exec bits travel with the snapshot, whatever the node's medium is now --------------------------------


def test_a_computation_snapshot_survives_a_medium_change_and_an_exchange_verified(tmp_path: Path):
    from proof_cli.proof_map import set_medium

    source = ensure_project(tmp_path / "source")
    _computation(source)
    proof = _review(source)
    set_medium(source, "c1", "latex", edited_by="human")
    target = ensure_project(tmp_path / "target")
    report = import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(source))))
    assert candidate_proof_sha256(target, proof.id) == proof.sha256
    assert os.access(_snapshot(target, proof) / "node" / "run.sh", os.X_OK)
    assert not report.warnings


@pytest.mark.parametrize("name", ["run.sh", "check.py"])
def test_a_bundle_whose_executable_flags_disagree_with_its_manifest_reads_unverifiable_with_a_warning(tmp_path: Path, name: str):
    source = ensure_project(tmp_path / "source")
    _computation(source)
    proof = _review(source)
    raw = json.loads(bundle_to_json(export_exchange_bundle(source)))
    (stored,) = [f for f in raw["vault_files"] if f["path"] == f"proofs/c1/snapshots/v{proof.version}/node/{name}"]
    stored["executable"] = not stored["executable"]
    target = ensure_project(tmp_path / "target")
    report = import_exchange_bundle(target, raw)
    assert candidate_proof_sha256(target, proof.id) is None
    assert any("executable" in warning and proof.id in warning for warning in report.warnings)


def test_a_format_1_latex_snapshot_exchanges_unchanged(tmp_path: Path):
    source = ensure_project(tmp_path / "source")
    create_node(source, node_id="t1", kind="claim", statement="a written proof")
    proof = submit_proof(source, "t1", claimant_id="agent_a", scoping_rationale="r", content="\\begin{proof}ok\\end{proof}\n")
    manifest_path = source.root / proof.file_path
    old = {"format": 1, "files": json.loads(manifest_path.read_text())["files"]}  # as written before format 2
    manifest_path.write_text(json.dumps(old, indent=1, sort_keys=True) + "\n")
    assert candidate_proof_sha256(source, proof.id) == proof.sha256
    target = ensure_project(tmp_path / "target")
    report = import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(source))))
    assert candidate_proof_sha256(target, proof.id) == proof.sha256 and not report.warnings
    assert (target.root / proof.file_path).read_bytes() == manifest_path.read_bytes()


# -- set_executable adds x where r is set, and nothing else ---------------------------------------------------


@pytest.mark.parametrize(("before", "after"), [(0o444, 0o555), (0o644, 0o755), (0o600, 0o700), (0o640, 0o750), (0o666, 0o777)])
@needs_posix_modes
def test_set_executable_adds_x_only_where_r_is_set_and_never_write(tmp_path: Path, before: int, after: int):
    from proof_cli.vault import set_executable

    path = tmp_path / "script"
    path.write_text("x")
    path.chmod(before)
    set_executable(path)
    assert stat.S_IMODE(path.stat().st_mode) == after
