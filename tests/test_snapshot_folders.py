"""A Review snapshot freezes every input of the proof (ADR-0011 point 5, #71).

A snapshot is `snapshots/v<N>/`: the node's working sources and the shared preamble, with a
manifest of each file's SHA-256. The snapshot's SHA-256, which decisions bind, is that of the
manifest, recomputed from the stored files. Older single-file snapshots read as before.
"""

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from _proofs import ensure_key_ideas

from _researcher import researcher
from proof_cli.authority import candidate_proof_sha256
from proof_cli.proof_map import (
    ProofMapError,
    create_node,
    get_acceptance_state,
    get_workflow_state,
    list_candidate_proofs,
    list_integrity_warnings,
    request_review,
)
from proof_cli.storage import ensure_project, insert_candidate_proof
from proof_cli.domain import CandidateProofRecord

MAIN = "\\documentclass{amsart}\n\\input{../preamble}\n\\begin{document}\n\\input{body}\n\\end{document}\n"


def _node(tmp_path: Path, node_id: str = "clm_1"):
    store = ensure_project(tmp_path)
    create_node(store, node_id=node_id, kind="claim", statement="s")
    folder = store.root / "proofs" / node_id
    (folder / "proof.tex").write_text(MAIN)
    (folder / "body.tex").write_text("By the lemma, $x > 0$.\n")
    ensure_key_ideas(store, node_id)
    return store, folder


def _request(store, node_id="clm_1"):
    return request_review(store, node_id, requested_by="agent_a", rationale="scoped")


# -- what a snapshot holds ------------------------------------------------------------


def test_a_snapshot_is_a_folder_of_every_input_with_a_manifest_whose_hash_is_the_records(tmp_path: Path):
    store, folder = _node(tmp_path)
    (folder / "refs.bib").write_text("@article{k, title={T}}\n")
    for outside in ("build/proof.aux", "scratch/check.py", ".DS_Store"):
        (folder / outside).parent.mkdir(exist_ok=True)
        (folder / outside).write_text("not an input\n")

    record = _request(store)

    snapshot = folder / "snapshots" / "v1"
    assert record.file_path == "proofs/clm_1/snapshots/v1/manifest.json"
    stored = sorted(p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file())
    assert stored == ["manifest.json", "node/body.tex", "node/key-ideas.md", "node/proof.tex", "node/refs.bib", "shared/preamble.tex"]
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert manifest["files"] == {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("body.tex", "key-ideas.md", "proof.tex", "refs.bib")
    } | {"../preamble.tex": hashlib.sha256((store.root / "proofs" / "preamble.tex").read_bytes()).hexdigest()}
    canonical = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()
    assert record.sha256 == hashlib.sha256(canonical).hexdigest() == candidate_proof_sha256(store, record.id)


def test_a_snapshot_is_never_overwritten_and_an_edit_to_it_breaks_its_hash(tmp_path: Path):
    store, folder = _node(tmp_path)
    record = _request(store)
    (folder / "snapshots" / "v1" / "node" / "body.tex").write_text("tampered\n")
    assert candidate_proof_sha256(store, record.id) != record.sha256

    (folder / "body.tex").write_text("a second argument\n")
    second = _request(store)
    assert second.version == 2 and (folder / "snapshots" / "v1" / "node" / "body.tex").read_text() == "tampered\n"


# -- a change to any input is a new version -------------------------------------------


@pytest.mark.parametrize("change", ["body", "preamble"])
def test_changing_only_an_input_file_or_the_preamble_is_a_new_version_to_review(tmp_path: Path, change):
    """PR #71 / audit reproduction: editing `body.tex` (or a macro in the preamble) left the node
    'unchanged' and its Acceptance counting for a proof it no longer had."""
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"

    if change == "body":
        (folder / "body.tex").write_text("A different argument.\n")
    else:
        preamble = store.root / "proofs" / "preamble.tex"
        preamble.write_text(preamble.read_text() + "\\newcommand{\\R}{\\mathbb{R}}\n")

    second = _request(store)
    assert second.version == 2
    assert get_workflow_state(store, "clm_1") == "review-needed"  # the researcher looks at v2


def test_nothing_changed_is_still_refused(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    (folder / "scratch").mkdir()
    (folder / "scratch" / "notes.py").write_text("print(1)\n")  # scratch is not an input
    with pytest.raises(ProofMapError) as refused:
        _request(store)
    assert refused.value.code == "WORKING_PROOF_UNCHANGED"


# -- the archived PDF follows every frozen input ---------------------------------------


def _build(folder: Path, *, later_than: Path | None = None):
    pdf = folder / "build" / "proof.pdf"
    pdf.parent.mkdir(exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 built\n")
    stamp = time.time() + 5
    os.utime(pdf, (stamp, stamp))
    return pdf


def test_a_current_build_is_archived_and_a_stale_one_is_not(tmp_path: Path):
    store, folder = _node(tmp_path)
    _build(folder)
    first = _request(store)
    assert (folder / "snapshots" / "v1.pdf").read_bytes() == b"%PDF-1.4 built\n"

    (folder / "body.tex").write_text("changed after the build\n")  # the build no longer matches
    stamp = time.time() + 10
    os.utime(folder / "body.tex", (stamp, stamp))
    second = _request(store)
    assert not (folder / "snapshots" / f"v{second.version}.pdf").exists()
    assert first.version == 1


# -- old single-file snapshots ---------------------------------------------------------


def test_an_old_single_file_snapshot_and_its_decision_read_as_before(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="old", kind="claim", statement="s")
    text = b"\\documentclass{amsart}\\begin{document}old\\end{document}\n"
    path = store.root / "proofs" / "old" / "snapshots" / "v1.tex"
    path.parent.mkdir(parents=True)
    path.write_bytes(text)
    record = CandidateProofRecord(
        id="cp-old", node_id="old", version=1, file_path="proofs/old/snapshots/v1.tex",
        submitted_by="agent_a", scoping_rationale="scoped", sha256=hashlib.sha256(text).hexdigest(),
    )
    insert_candidate_proof(store, record)

    assert candidate_proof_sha256(store, "cp-old") == record.sha256
    researcher(store).decide_acceptance("old", "accept")
    assert get_acceptance_state(store, "old") == "accepted"

    # the next request freezes the whole source set as v2, next to the old file
    (store.root / "proofs" / "old" / "proof.tex").write_text("new text\n")
    ensure_key_ideas(store, "old")  # a new snapshot needs its summary; the old one never had one (ADR-0013)
    second = request_review(store, "old", requested_by="agent_a", rationale="scoped")
    assert second.version == 2 and second.file_path.endswith("snapshots/v2/manifest.json")
    assert [p.version for p in list_candidate_proofs(store, "old")] == [1, 2]


# -- orphans --------------------------------------------------------------------------


def test_an_orphan_snapshot_folder_is_skipped_and_reported(tmp_path: Path):
    store, folder = _node(tmp_path)
    orphan = folder / "snapshots" / "v1"
    orphan.mkdir(parents=True)
    (orphan / "proof.tex").write_text("left behind by a crash\n")

    record = _request(store)

    assert record.version == 2
    assert (orphan / "proof.tex").read_text() == "left behind by a crash\n"
    (warning,) = [w for w in list_integrity_warnings(store) if w.code == "ORPHAN_SNAPSHOT"]
    assert warning.details == {"node_id": "clm_1", "file_path": "proofs/clm_1/snapshots/v1"}


def test_a_failed_request_leaves_no_snapshot_folder(tmp_path: Path, monkeypatch):
    from proof_cli import proof_map

    store, folder = _node(tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("crash after the snapshot was written")

    monkeypatch.setattr(proof_map, "pin_dependencies", fail)
    with pytest.raises(RuntimeError):
        _request(store)
    assert not (folder / "snapshots" / "v1").exists()
    assert list_candidate_proofs(store, "clm_1") == []



# -- PR #78 review: a node's own files never collide with the snapshot's; a broken one still shows --


def test_a_nodes_files_named_like_the_snapshots_own_are_frozen_without_colliding(tmp_path: Path):
    store, folder = _node(tmp_path)
    (folder / "manifest.json").write_text('{"a node file": "not the snapshot manifest"}\n')
    for trap in ("_shared/preamble.tex", "shared/preamble.tex"):
        (folder / trap).parent.mkdir(exist_ok=True)
        (folder / trap).write_text(f"a node file at {trap}\n")

    record = _request(store)

    snapshot = folder / "snapshots" / "v1"
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert set(manifest["files"]) == {"proof.tex", "body.tex", "key-ideas.md", "manifest.json", "_shared/preamble.tex", "shared/preamble.tex", "../preamble.tex"}
    assert (snapshot / "node" / "manifest.json").read_text() == (folder / "manifest.json").read_text()
    assert (snapshot / "node" / "shared" / "preamble.tex").read_text() == "a node file at shared/preamble.tex\n"
    assert (snapshot / "shared" / "preamble.tex").read_bytes() == (store.root / "proofs" / "preamble.tex").read_bytes()
    assert candidate_proof_sha256(store, record.id) == record.sha256


def test_a_broken_snapshot_still_shows_its_node_page_and_the_warning(tmp_path: Path):
    from _review_client import DirectClient

    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    (folder / "snapshots" / "v1" / "manifest.json").write_text("{ not json")

    status, body = DirectClient(store).get("/api/node/clm_1")

    assert status == 200, body
    view = body["data"]
    assert view["candidate_proof"]["unreadable"] is True and view["candidate_proof"]["sha256"] is None
    assert view["acceptance_state"] == "unverifiable"
    assert any(w["code"] == "DECISION_NO_LONGER_APPLIES" for w in view["warnings"])


# -- #92: a missing or unreadable snapshot binds nothing (None is never a match) ---------------


def _lose(folder: Path, how: str) -> None:
    snapshot = folder / "snapshots" / "v1"
    if how == "deleted":
        shutil.rmtree(snapshot)
    else:
        (snapshot / "manifest.json").write_text("{ not json")


@pytest.mark.parametrize("how", ["deleted", "unreadable"])
@pytest.mark.parametrize("decision", ["accept", "revision-requested", "reject"])
def test_no_decision_is_made_on_a_missing_or_unreadable_snapshot(tmp_path: Path, how, decision):
    store, folder = _node(tmp_path)
    _request(store)
    _lose(folder, how)

    with pytest.raises(ProofMapError) as refused:
        researcher(store).decide_acceptance("clm_1", decision)

    assert refused.value.code == "SNAPSHOT_UNREADABLE"
    assert not (folder / "reviews.jsonl").exists()
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_an_old_single_file_snapshot_that_is_gone_is_refused_too(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="old", kind="claim", statement="s")
    insert_candidate_proof(store, CandidateProofRecord(
        id="cp-old", node_id="old", version=1, file_path="proofs/old/snapshots/v1.tex",
        submitted_by="agent_a", scoping_rationale="scoped", sha256="0" * 64,
    ))
    with pytest.raises(ProofMapError) as refused:
        researcher(store).decide_acceptance("old", "accept")
    assert refused.value.code == "SNAPSHOT_UNREADABLE"


def test_an_acceptance_whose_snapshot_is_then_deleted_stops_counting_and_blocks_its_dependents(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    create_node(store, node_id="user", kind="claim", statement="uses clm_1", dependencies=["clm_1"])
    assert get_workflow_state(store, "user") == "open"

    shutil.rmtree(folder / "snapshots" / "v1")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert get_workflow_state(store, "user") == "blocked"
    assert any(w.code == "DECISION_NO_LONGER_APPLIES" for w in list_integrity_warnings(store))


@pytest.mark.parametrize("snapshot", ["present", "deleted"])
def test_a_decision_line_naming_no_snapshot_hash_reads_unverifiable(tmp_path: Path, snapshot):
    """The audit's reproduction (#92): a recorded `candidate_proof_sha256: null` matched a missing snapshot's None."""
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    reviews = folder / "reviews.jsonl"
    (line,) = [json.loads(text) for text in reviews.read_text().splitlines()]
    line["payload"]["candidate_proof_sha256"] = None
    reviews.write_text(json.dumps(line) + "\n")
    if snapshot == "deleted":
        shutil.rmtree(folder / "snapshots" / "v1")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"


def test_the_page_offers_no_decision_on_an_unreadable_snapshot_and_says_why_one_is_refused(tmp_path: Path):
    from _review_client import DirectClient

    store, folder = _node(tmp_path)
    _request(store)
    client = DirectClient(store)
    offered = client.get("/api/node/clm_1")[1]["data"]
    accept = next(d for d in offered["decisions"] if d["decision"] == "accept")
    shutil.rmtree(folder / "snapshots" / "v1")

    view = client.get("/api/node/clm_1")[1]["data"]
    assert view["candidate_proof"]["unreadable"] is True
    assert not [d for d in view["decisions"] if d["kind"] == "acceptance"]
    (pending,) = [item for item in client.get("/api/state")[1]["data"]["pending"] if item["node_id"] == "clm_1"]
    assert pending["decisions"] == []

    # an Accept the page offered before the snapshot went is refused, with the reason
    (result,) = client.post("/api/decide", {"decisions": [accept]})[1]["data"]["results"]
    assert result["ok"] is False and result["error"]["code"] == "SNAPSHOT_UNREADABLE"
    assert not (folder / "reviews.jsonl").exists()


# -- PR #95 review: a snapshot file the process can't read is unreadable, not a crash ----------

needs_permissions = pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a chmod 000 file")


@pytest.fixture
def unreadable():
    """Make a file unreadable (chmod 000) for the test, and readable again after it."""
    made: list[Path] = []

    def make(path: Path) -> None:
        path.chmod(0)
        made.append(path)

    yield make
    for path in made:
        path.chmod(0o644)


def _old_snapshot(store, text: bytes = b"\\documentclass{amsart}\\begin{document}old\\end{document}\n") -> Path:
    create_node(store, node_id="old", kind="claim", statement="s")
    path = store.root / "proofs" / "old" / "snapshots" / "v1.tex"
    path.parent.mkdir(parents=True)
    path.write_bytes(text)
    insert_candidate_proof(store, CandidateProofRecord(
        id="cp-old", node_id="old", version=1, file_path="proofs/old/snapshots/v1.tex",
        submitted_by="agent_a", scoping_rationale="scoped", sha256=hashlib.sha256(text).hexdigest(),
    ))
    return path


@needs_permissions
def test_an_old_single_file_snapshot_that_cant_be_read_is_refused_and_voids_its_decision(tmp_path: Path, unreadable):
    store = ensure_project(tmp_path)
    path = _old_snapshot(store)
    unreadable(path)

    assert candidate_proof_sha256(store, "cp-old") is None
    with pytest.raises(ProofMapError) as refused:
        researcher(store).decide_acceptance("old", "accept")
    assert refused.value.code == "SNAPSHOT_UNREADABLE"

    path.chmod(0o644)
    researcher(store).decide_acceptance("old", "accept")
    unreadable(path)
    assert get_acceptance_state(store, "old") == "unverifiable"


@needs_permissions
def test_a_folder_snapshot_file_that_cant_be_read_is_refused_and_its_page_still_shows(tmp_path: Path, unreadable):
    from _review_client import DirectClient

    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    unreadable(folder / "snapshots" / "v1" / "node" / "body.tex")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    status, body = DirectClient(store).get("/api/node/clm_1")
    assert status == 200, body
    assert body["data"]["candidate_proof"]["sha256"] is None


# -- #99: a lost snapshot is re-snapshotted from an unchanged working proof ----------------


@pytest.mark.parametrize("how", ["deleted", "unreadable"])
def test_after_a_snapshot_is_lost_an_unchanged_proof_is_re_snapshotted_for_review(tmp_path: Path, how):
    from typer.testing import CliRunner

    from proof_cli.cli import app
    from proof_cli.storage import list_events

    store, folder = _node(tmp_path)
    _request(store)
    _lose(folder, how)

    result = CliRunner().invoke(
        app, ["node", "request-review", "clm_1", "--root", str(tmp_path), "--requested-by", "agent_a", "--rationale", "scoped"]
    )

    assert result.exit_code == 0, result.stdout
    assert "re-snapshot after loss" in result.stdout
    (first, second) = list_candidate_proofs(store, "clm_1")
    assert (first.version, second.version) == (1, 2) and second.is_current
    assert candidate_proof_sha256(store, second.id) == second.sha256
    assert get_workflow_state(store, "clm_1") == "review-needed"
    (event,) = [e for e in list_events(store) if e.kind == "proof_map_review_requested" and e.payload["version"] == 2]
    assert "re-snapshot after loss" in event.message
    assert event.payload["resnapshot_after_loss"] == 1


def test_an_intact_snapshot_with_an_unchanged_proof_is_still_refused_even_after_a_decision(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    with pytest.raises(ProofMapError) as refused:
        _request(store)

    assert refused.value.code == "WORKING_PROOF_UNCHANGED"
    assert [p.version for p in list_candidate_proofs(store, "clm_1")] == [1]


def test_the_re_snapshot_needs_a_fresh_acceptance_and_the_old_decision_never_revives(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    shutil.rmtree(folder / "snapshots" / "v1")

    record = _request(store)

    assert record.version == 2 and record.resnapshot_after_loss == 1
    assert get_acceptance_state(store, "clm_1") == "unverifiable"  # the Accept on v1 doesn't carry over to v2
    assert get_workflow_state(store, "clm_1") == "review-needed"

    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"

    # the v2 snapshot then being lost voids its own Accept; v1's is never read again
    shutil.rmtree(folder / "snapshots" / "v2")
    assert get_acceptance_state(store, "clm_1") == "unverifiable"


def test_the_refusal_on_a_lost_snapshot_says_how_to_recover(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    _lose(folder, "deleted")

    with pytest.raises(ProofMapError) as refused:
        researcher(store).decide_acceptance("clm_1", "accept")

    assert "request review again" in str(refused.value)


@pytest.mark.parametrize("how", ["deleted", "unreadable"])
def test_a_lost_snapshot_whose_dependencies_also_changed_is_a_new_version_not_a_re_snapshot(tmp_path: Path, how):
    from proof_cli.proof_map import add_dependency
    from proof_cli.storage import list_events

    store, folder = _node(tmp_path)
    create_node(store, node_id="lem", kind="claim", statement="a lemma")
    _request(store)
    _lose(folder, how)
    add_dependency(store, "clm_1", "lem")  # a reason for a new version on its own (#96)

    record = _request(store)

    assert record.version == 2 and record.resnapshot_after_loss is None
    assert record.dependencies == ["lem"]
    assert candidate_proof_sha256(store, record.id) == record.sha256
    (event,) = [e for e in list_events(store) if e.kind == "proof_map_review_requested" and e.payload["version"] == 2]
    assert "re-snapshot after loss" not in event.message
    assert event.payload["resnapshot_after_loss"] is None
