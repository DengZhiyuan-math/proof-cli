"""A node's proof is a standalone LaTeX document; review is of an immutable snapshot (#51, ADR-0010)."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    get_active_claim,
    get_workflow_state,
    list_candidate_proofs,
    list_integrity_warnings,
    request_review,
)
from proof_cli.storage import ensure_project, list_all_claims

runner = CliRunner()


def _working(store, node_id: str) -> Path:
    return store.root / "proofs" / node_id / "proof.tex"


def _write_proof(store, node_id: str, body: str) -> None:
    path = _working(store, node_id)
    path.write_text(path.read_text().replace("% Write the proof here.", body))


def test_a_local_node_gets_a_standalone_latex_working_file(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement=r"$(f * g) * h = f * (g * h)$")

    text = _working(store, "clm_1").read_text()
    assert text.startswith(r"\documentclass")
    assert r"\input{../preamble}" in text
    assert r"$(f * g) * h = f * (g * h)$" in text
    assert (store.root / "proofs" / "preamble.tex").is_file()
    # prism-local takes the only top-level .tex as the folder's main file
    assert [p.name for p in (store.root / "proofs" / "clm_1").glob("*.tex")] == ["proof.tex"]


def test_an_imported_result_gets_no_working_file(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="ref_1", kind="imported_result", statement="known", source_locator="doi:x", source_version="v1")
    assert not (store.root / "proofs" / "ref_1").exists()


def test_an_existing_working_file_is_never_overwritten(tmp_path: Path):
    store = ensure_project(tmp_path)
    path = _working(store, "clm_1")
    path.parent.mkdir(parents=True)
    path.write_text("mine")
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    assert path.read_text() == "mine"


@pytest.mark.parametrize("node_id", ["../escape", "/tmp/x", "", " ", ".hidden", "a/b"])
def test_node_ids_that_arent_safe_folder_names_are_refused(tmp_path: Path, node_id: str):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as exc_info:
        create_node(store, node_id=node_id, kind="claim", statement="s")
    assert exc_info.value.code == "INVALID_NODE_ID"


def test_requesting_review_snapshots_the_working_file(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    _write_proof(store, "clm_1", r"Take $x$; then $- x^2 \le 0$.")

    record = request_review(store, "clm_1", requested_by="agent_a", rationale="small enough to prove directly")

    snapshot = store.root / record.file_path
    assert record.file_path == "proofs/clm_1/snapshots/v1.tex"
    assert snapshot.read_bytes() == _working(store, "clm_1").read_bytes()
    assert record.sha256 == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert get_workflow_state(store, "clm_1") == "review-needed"
    # still exactly one top-level .tex: snapshots live in their own folder
    assert [p.name for p in (store.root / "proofs" / "clm_1").glob("*.tex")] == ["proof.tex"]


def test_an_unchanged_working_file_is_not_snapshotted_again(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    _write_proof(store, "clm_1", "first attempt")
    first = request_review(store, "clm_1", requested_by="agent_a", rationale="r")

    with pytest.raises(ProofMapError) as exc_info:
        request_review(store, "clm_1", requested_by="agent_a", rationale="r")
    assert exc_info.value.code == "WORKING_PROOF_UNCHANGED"

    before = (store.root / first.file_path).read_bytes()
    _working(store, "clm_1").write_text(_working(store, "clm_1").read_text() + "% revised\n")
    second = request_review(store, "clm_1", requested_by="agent_a", rationale="r")
    assert (second.version, second.file_path) == (2, "proofs/clm_1/snapshots/v2.tex")
    assert (store.root / first.file_path).read_bytes() == before
    assert [p.is_current for p in list_candidate_proofs(store, "clm_1")] == [False, True]


def test_requesting_review_needs_a_rationale_and_a_working_file(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    with pytest.raises(ProofMapError) as exc_info:
        request_review(store, "clm_1", requested_by="agent_a", rationale=" ")
    assert exc_info.value.code == "SCOPING_RATIONALE_REQUIRED"

    _working(store, "clm_1").unlink()
    with pytest.raises(ProofMapError) as exc_info:
        request_review(store, "clm_1", requested_by="agent_a", rationale="r")
    assert exc_info.value.code == "WORKING_PROOF_MISSING"


def test_writing_and_requesting_review_need_no_claim_and_end_one(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    _write_proof(store, "clm_1", "unclaimed work")
    request_review(store, "clm_1", requested_by="agent_a", rationale="r")  # no claim at all

    create_node(store, node_id="clm_2", kind="claim", statement="t")
    claim_node(store, "clm_2", claimant_id="agent_b", session_id="s")
    _write_proof(store, "clm_2", "claimed work")
    request_review(store, "clm_2", requested_by="agent_b", rationale="r")
    assert get_active_claim(store, "clm_2") is None

    create_node(store, node_id="clm_3", kind="claim", statement="u")
    claim_node(store, "clm_3", claimant_id="agent_b", session_id="s")
    _write_proof(store, "clm_3", "someone else's request")
    with pytest.raises(ProofMapError) as exc_info:
        request_review(store, "clm_3", requested_by="agent_c", rationale="r")
    assert exc_info.value.code == "NOT_CLAIMANT"  # a node someone holds is theirs to hand over
    assert get_active_claim(store, "clm_3").claimant_id == "agent_b"


def test_a_reassignment_racing_a_request_waits_for_it_rather_than_being_overridden(tmp_path: Path, monkeypatch):
    # issue #18: A passes the holder check, the node is reassigned to B, and A's request must not
    # go on to snapshot and hand over a node B now holds. The check and the writes are one
    # transaction, so B's reassignment waits until A's request has committed.
    import threading

    from proof_cli import proof_map

    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="s")
    _write_proof(store, "clm_1", "A's work")

    original = proof_map.write_snapshot
    reassigner = threading.Thread(target=lambda: claim_node(store, "clm_1", claimant_id="agent_b", session_id="s", reassign=True))

    def write_after_a_reassignment(path, content):
        reassigner.start()
        reassigner.join(timeout=0.5)  # never finishes while A holds the write lock
        original(path, content)

    monkeypatch.setattr(proof_map, "write_snapshot", write_after_a_reassignment)
    request_review(store, "clm_1", requested_by="agent_a", rationale="r")
    reassigner.join()

    a_claim, b_claim = sorted(list_all_claims(store), key=lambda claim: claim.claimed_at)
    assert (a_claim.claimant_id, a_claim.released_by, a_claim.release_reason) == ("agent_a", "agent_a", "review requested")
    assert b_claim.claimant_id == "agent_b" and b_claim.released_at is None  # B's claim came after A's hand-over
    assert get_workflow_state(store, "clm_1") == "claimed"
    assert len(list_candidate_proofs(store, "clm_1")) == 1


def test_a_failed_request_leaves_no_snapshot_and_no_row(tmp_path: Path, monkeypatch):
    from proof_cli import proof_map

    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    claim_node(store, "clm_1", claimant_id="agent_a", session_id="s")
    _write_proof(store, "clm_1", "work")

    def fail(*_args, **_kwargs):
        raise RuntimeError("crash after the snapshot was written")

    monkeypatch.setattr(proof_map, "pin_dependencies", fail)
    with pytest.raises(RuntimeError):
        request_review(store, "clm_1", requested_by="agent_a", rationale="r")

    assert not (store.root / "proofs" / "clm_1" / "snapshots" / "v1.tex").exists()
    assert list_candidate_proofs(store, "clm_1") == []
    assert get_active_claim(store, "clm_1").claimant_id == "agent_a"


def test_an_orphan_snapshot_is_skipped_and_reported_not_a_permanent_block(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    orphan = store.root / "proofs" / "clm_1" / "snapshots" / "v1.tex"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("left behind by a crash")  # between the file write and the index insert
    _write_proof(store, "clm_1", "work")

    record = request_review(store, "clm_1", requested_by="agent_a", rationale="r")

    assert record.version == 2
    assert record.file_path == "proofs/clm_1/snapshots/v2.tex"
    assert orphan.read_text() == "left behind by a crash"  # never overwritten or adopted
    (warning,) = [w for w in list_integrity_warnings(store) if w.code == "ORPHAN_SNAPSHOT"]
    assert warning.details == {"node_id": "clm_1", "file_path": "proofs/clm_1/snapshots/v1.tex"}

    result = runner.invoke(app, ["review", "warnings", "--root", str(tmp_path)])
    assert "ORPHAN_SNAPSHOT" in result.output


def test_a_pdf_copy_that_fails_partway_leaves_no_pdf_behind(tmp_path: Path, monkeypatch):
    # PR #61 review: the PDF only counted as written once the copy finished
    from proof_cli import proof_map

    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    _write_proof(store, "clm_1", "work")

    def partial_copy(_src, dst):
        Path(dst).write_bytes(b"%PDF half")
        raise OSError("no space left on device")

    monkeypatch.setattr(proof_map, "build_is_current", lambda *_: True)
    monkeypatch.setattr(proof_map.shutil, "copyfile", partial_copy)
    with pytest.raises(OSError):
        request_review(store, "clm_1", requested_by="agent_a", rationale="r")

    assert list((store.root / "proofs" / "clm_1" / "snapshots").iterdir()) == []


def test_a_stray_pdf_is_never_adopted_by_a_new_snapshot(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="s")
    stray = store.root / "proofs" / "clm_1" / "snapshots" / "v1.pdf"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"%PDF of some other text")
    _write_proof(store, "clm_1", "work")  # and no current build

    record = request_review(store, "clm_1", requested_by="agent_a", rationale="r")

    assert record.version == 2
    assert not (store.root / record.file_path).with_suffix(".pdf").exists()
    (warning,) = [w for w in list_integrity_warnings(store) if w.code == "ORPHAN_SNAPSHOT"]
    assert warning.details == {"node_id": "clm_1", "file_path": "proofs/clm_1/snapshots/v1.pdf"}


def test_an_imported_result_has_nothing_to_review_this_way(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="ref_1", kind="imported_result", statement="known", source_locator="doi:x", source_version="v1")
    with pytest.raises(ProofMapError) as exc_info:
        request_review(store, "ref_1", requested_by="agent_a", rationale="r")
    assert exc_info.value.code == "IMMUTABLE_NODE"


def _local_tex() -> list[str] | None:
    """The first LaTeX compiler installed here, as prism-local would pick one: a TeX distribution, else Tectonic."""
    for engine in ("pdflatex", "xelatex", "lualatex"):
        if shutil.which(engine):
            return [engine, "-interaction=nonstopmode", "-halt-on-error", "-output-directory=build", "proof.tex"]
    if shutil.which("tectonic"):
        return ["tectonic", "--outdir", "build", "proof.tex"]
    return None


def _compile(folder: Path) -> subprocess.CompletedProcess:
    (folder / "build").mkdir(exist_ok=True)
    return subprocess.run(_local_tex(), cwd=folder, capture_output=True, text=True, timeout=600)


needs_tex = pytest.mark.skipif(_local_tex() is None, reason="needs a local LaTeX compiler (pdflatex, xelatex, lualatex or tectonic)")


@needs_tex
def test_the_working_file_compiles_standalone(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement=r"$(f * g) * h = f * (g * h)$")
    folder = store.root / "proofs" / "clm_1"
    result = _compile(folder)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
    assert (folder / "build" / "proof.pdf").read_bytes().startswith(b"%PDF")


@needs_tex
def test_a_real_build_is_archived_with_the_snapshot(tmp_path: Path):
    """The whole loop with a real compiler: write the proof, build it as prism-local would, request review."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem_1", kind="lemma", statement=r"$\|f * g\|_1 \le \|f\|_1 \|g\|_1$")
    _write_proof(store, "lem_1", r"By Fubini, $\int |f * g| \le \int\int |f(x-y)||g(y)|\,dy\,dx = \|f\|_1\|g\|_1$.")
    folder = store.root / "proofs" / "lem_1"
    result = _compile(folder)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]

    snapshot = request_review(store, "lem_1", requested_by="agent_a", rationale="one estimate")

    archived = (tmp_path / snapshot.file_path).with_suffix(".pdf")
    assert archived.read_bytes() == (folder / "build" / "proof.pdf").read_bytes()
    assert archived.read_bytes().startswith(b"%PDF")


def test_request_review_and_show_on_the_cli(tmp_path: Path):
    store = ensure_project(tmp_path)
    root = str(tmp_path)
    assert runner.invoke(app, ["node", "create", "clm_1", "claim", "s", "--root", root, "--json"]).exit_code == 0
    _write_proof(store, "clm_1", "cli work")

    result = runner.invoke(app, ["node", "request-review", "clm_1", "--rationale", "r", "--requested-by", "agent_a", "--root", root, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)["data"]
    assert (payload["version"], payload["file_path"]) == (1, "proofs/clm_1/snapshots/v1.tex")

    again = runner.invoke(app, ["node", "request-review", "clm_1", "--rationale", "r", "--root", root, "--json"])
    assert again.exit_code == 1
    assert json.loads(again.stdout)["error"]["code"] == "WORKING_PROOF_UNCHANGED"

    shown = json.loads(runner.invoke(app, ["node", "show", "clm_1", "--root", root, "--json"]).stdout)["data"]
    assert shown["working_proof"] == "proofs/clm_1/proof.tex"
    assert [s["file_path"] for s in shown["snapshots"]] == ["proofs/clm_1/snapshots/v1.tex"]
    assert shown["snapshots"][0]["sha256"] == payload["sha256"]

    human = runner.invoke(app, ["node", "show", "clm_1", "--root", root])
    assert "proofs/clm_1/proof.tex" in human.stdout and "snapshots/v1.tex" in human.stdout
