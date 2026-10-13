"""Attribution probes rerun at 83dbc43."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).parent
WEB = Path("/private/tmp/claude-502/-Volumes-Codex-Workspace-live-home-zhdeng-proof-cli/a1dcf6b7-5a7e-4737-9c30-60241cd19074/scratchpad/web-e4a123a")
CORE = Path("/private/tmp/proof-web9-dependencies-l3osbhij/core/DengZhiyuan-math-proof-cli-ad479f6")
AGENTS = Path("/private/tmp/proof-web9-dependencies-l3osbhij/agents/zeqome-proof-agents-9558fd0caf6eef2f80401c503a0a4549f4bbaa6f")
sys.path[:0] = [str(path) for path in (
    WEB / "src", AGENTS / "src", CORE / "src", CORE / "packages/latex-agent/src",
    WEB / "tests", CORE / "tests",
)]

from proof_cli.storage import ensure_project
from proof_cli.proof_map import create_node, add_dependency, remove_dependency, record_evidence_check
from proof_web import review_queue
from proof_web.review_queue import source_marks
from _proofs import submit_proof

print("review_queue", review_queue.__file__, hashlib.sha256(Path(review_queue.__file__).read_bytes()).hexdigest())

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


# -- edge probes, new at e4a123a ------------------------------------------------------------


def test_edge_a_removed_edge_keeps_the_historical_mark(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader")
    _checked(store, "R: unchecked against the source.", "old proof")
    remove_dependency(store, "L", "R")
    _checked(store, "sources checked", "new proof")
    actual = source_marks(store, "R")
    assert [(m["dependent"], m["snapshot"], m["current"]) for m in actual] == [("L", 1, False)], actual


def test_edge_a_mark_names_no_import_and_the_snapshot_rests_on_two(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader")
    _checked(store, "unchecked against the source; source unavailable")
    assert source_marks(store, "R") == [] and source_marks(store, "R2") == []


def test_edge_semicolon_clause_naming_another_import(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader")
    _checked(store, "R2: unchecked against the source; R checked against the source.")
    actual = source_marks(store, "R")
    assert actual == [], actual


def test_edge_abbreviation_splits_the_sentence(tmp_path):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader")
    _checked(store, "Unchecked against the source, e.g. R2 could not be opened.")
    actual = source_marks(store, "R")
    assert actual == [], actual


# -- 85653cc: does the clause split drop a warning it used to keep? -------------------------


def _two(store):
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader")


def test_lost_unnamed_mark_then_named_import_after_semicolon(tmp_path):
    store = ensure_project(tmp_path)
    _two(store)
    _checked(store, "Unchecked against the source; R2's paper could not be opened.")
    assert len(source_marks(store, "R2")) == 1, "the warning about R2 is lost"
    assert source_marks(store, "R") == []


def test_lost_named_import_then_mark_after_semicolon(tmp_path):
    store = ensure_project(tmp_path)
    _two(store)
    _checked(store, "R2's statement differs from the cited version; unchecked against the source.")
    assert len(source_marks(store, "R2")) == 1, "the warning about R2 is lost"


def test_short_checked_then_comma_unchecked(tmp_path):
    store = ensure_project(tmp_path)
    _two(store)
    _checked(store, "R: checked, R2: unchecked against the source.")
    assert source_marks(store, "R") == [], source_marks(store, "R")
    assert len(source_marks(store, "R2")) == 1


def test_ambiguous_sentence_fallback_reaches_the_import_named_checked(tmp_path):
    store = ensure_project(tmp_path)
    _two(store)
    _checked(store, "R: checked against the source; unchecked against the source for the other import.")
    assert source_marks(store, "R") == [], source_marks(store, "R")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main(["-q", str(Path(__file__).resolve())]))
