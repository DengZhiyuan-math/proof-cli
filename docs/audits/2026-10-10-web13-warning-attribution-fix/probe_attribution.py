"""Independent source-warning attribution checks for de96466."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).parent
METADATA = json.loads((HERE / "manifest.json").read_text())
WEB = Path(METADATA["web_archive"])
CORE = Path(METADATA["dependencies"]["core"]["path"])
AGENTS = Path(METADATA["dependencies"]["agents"]["path"])
sys.path[:0] = [str(path) for path in (
    WEB / "src", AGENTS / "src", CORE / "src", CORE / "packages/latex-agent/src",
    WEB / "tests", CORE / "tests",
)]

from proof_cli.storage import ensure_project
from proof_cli.proof_map import create_node, add_dependency, record_evidence_check
from proof_web import review_queue
from proof_web.review_queue import source_marks
from _proofs import submit_proof

assert hashlib.sha256(Path(review_queue.__file__).read_bytes()).hexdigest() == METADATA["review_queue_sha256"]

def _imports(store):
    for node_id in ("R", "R2"):
        create_node(store, node_id=node_id, kind="imported_result", statement=node_id,
                    source_locator=f"source {node_id}", source_version="v1", created_by="reader")


def _checked(store, note, text="proof"):
    proof = submit_proof(store, "L", claimant_id="prover", scoping_rationale="scoped", content=text)
    record_evidence_check(store, proof.id, "passed", run_by="verifier", notes=note)
    return proof


def test_an_explicit_other_import_excludes_the_single_import_fallback(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader")
    _checked(store, "R2: unchecked against the source")
    actual = source_marks(store, "R")
    assert actual == [], actual


def test_an_unchecked_mark_is_not_assigned_to_an_import_only_named_as_checked(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader")
    _checked(store, "R: checked against the source.\nR2: unchecked against the source; source unavailable.")
    actual = source_marks(store, "R")
    assert actual == [], actual
    assert len(source_marks(store, "R2")) == 1


def test_a_superseded_snapshots_single_import_mark_survives_an_added_import(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader")
    old = _checked(store, "unchecked against the source; source unavailable", "old proof")
    assert old.dependencies == ["R"]
    add_dependency(store, "L", "R2")
    _checked(store, "sources checked", "new proof")
    actual = source_marks(store, "R")
    assert [(m["dependent"], m["snapshot"], m["current"]) for m in actual] == [("L", 1, False)], actual
    assert source_marks(store, "R2") == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main(["-q", str(Path(__file__).resolve())]))
