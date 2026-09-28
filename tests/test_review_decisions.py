"""Review decisions as git-tracked text, reviewed by a git identity (issues #53/#54, ADR-0010)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from _researcher import Researcher, researcher
from proof_cli.authority import list_decisions
from proof_cli.domain import ProofMapNodeKind
from proof_cli.proof_map import (
    create_node,
    get_acceptance_state,
    get_integrity_state,
    get_node,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    list_integrity_warnings,
    request_review,
)
from proof_cli.storage import ensure_project, load_project

FIXTURE = Path(__file__).parent / "fixtures" / "pre_adr_0009_project"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Ada Researcher")
    _git(tmp_path, "config", "user.email", "ada@example.org")
    return tmp_path


def _awaiting_review(store, node_id: str = "clm_1"):
    create_node(store, node_id=node_id, kind="claim", statement=r"$(f * g) * h = f * (g * h)$")
    working = store.root / "proofs" / node_id / "proof.tex"
    working.write_text(working.read_text().replace("% Write the proof here.", "By associativity of the integral."))
    return request_review(store, node_id, requested_by="agent_a", rationale="small enough")


def _codes(store) -> list[str]:
    return [warning.code for warning in list_integrity_warnings(store)]


def test_a_decision_is_a_line_in_the_nodes_reviews_jsonl(tmp_path: Path):
    store = ensure_project(tmp_path)
    snapshot = _awaiting_review(store)

    record = researcher(store).decide_acceptance("clm_1", "accept", rationale="checked every step")

    lines = (tmp_path / "proofs" / "clm_1" / "reviews.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert (entry["id"], entry["kind"], entry["decision"], entry["rationale"]) == (record.id, "acceptance", "approved", "checked every step")
    assert entry["reviewer"] == "Researcher <researcher@example.org>"
    assert entry["payload"]["candidate_proof_sha256"] == snapshot.sha256
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_decision_is_committed_with_its_snapshot_as_the_reviewers_git_identity(tmp_path: Path):
    root = _repo(tmp_path)
    store = ensure_project(root)
    _awaiting_review(store)
    (root / "unrelated.txt").write_text("staged, not part of the decision")
    _git(root, "add", "unrelated.txt")

    Researcher(store, reviewer_id=None).decide_acceptance("clm_1", "accept", rationale="checked")

    assert _git(root, "log", "-1", "--format=%an <%ae>").strip() == "Ada Researcher <ada@example.org>"
    committed = set(_git(root, "show", "--name-only", "--format=", "HEAD").split())
    assert committed == {"proofs/clm_1/reviews.jsonl", "proofs/clm_1/snapshots/v1/manifest.json", "proofs/clm_1/snapshots/v1/proof.tex", "proofs/clm_1/snapshots/v1/_shared/preamble.tex"}  # the whole frozen snapshot (ADR-0011)
    assert "review: acceptance accept on clm_1" in _git(root, "log", "-1", "--format=%B")
    assert "A  unrelated.txt" in _git(root, "status", "--porcelain")  # still staged, never swept into the decision
    assert json.loads((root / "proofs" / "clm_1" / "reviews.jsonl").read_text())["reviewer"] == "Ada Researcher <ada@example.org>"
    assert "REVIEWS_NOT_COMMITTED" not in _codes(store)


def test_outside_a_git_repo_a_decision_is_still_recorded(tmp_path: Path):
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert [row["kind"] for row in list_decisions(store)] == ["acceptance"]


def test_a_decision_git_doesnt_have_yet_is_warned_about(tmp_path: Path):
    root = _repo(tmp_path)
    store = ensure_project(root)
    _awaiting_review(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    path = root / "proofs" / "clm_1" / "reviews.jsonl"
    path.write_text(path.read_text() + path.read_text().splitlines()[0].replace('"approved"', '"approved"') + "\n")

    assert "REVIEWS_NOT_COMMITTED" in _codes(store)


def test_editing_the_snapshot_after_acceptance_makes_the_node_unverifiable(tmp_path: Path):
    store = ensure_project(tmp_path)
    snapshot = _awaiting_review(store)
    researcher(store).decide_acceptance("clm_1", "accept")

    (tmp_path / snapshot.file_path).write_text("a different proof")

    assert get_acceptance_state(store, "clm_1") == "unverifiable"
    assert "DECISION_NO_LONGER_APPLIES" in _codes(store)


def test_an_unreadable_line_is_warned_about_and_ignored(tmp_path: Path):
    store = ensure_project(tmp_path)
    _awaiting_review(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    path = tmp_path / "proofs" / "clm_1" / "reviews.jsonl"
    path.write_text(path.read_text() + "{not json\n")

    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert "REVIEW_LINE_UNREADABLE" in _codes(store)


def test_a_pre_adr_0010_project_reads_as_it_did_before_any_signature(tmp_path: Path):
    """The fixture was built before #35: every decision in it is unsigned. Signatures
    no longer matter, so after the move into reviews.jsonl it reads exactly as that
    code read it — no re-sign step, a legacy Reject still terminal."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    store = load_project(root)

    axes = {}
    for node_id in ("acc", "pro", "rej", "rev", "ref", "dis", "dep"):
        node = get_node(store, node_id)
        axes[node_id] = {
            "kind": node.kind.value,
            "acceptance": get_reference_review_state(store, node_id) if node.kind == ProofMapNodeKind.imported_result else get_acceptance_state(store, node_id),
            "workflow": get_workflow_state(store, node_id),
            "integrity": get_integrity_state(store, node_id),
        }
    axes["challenges"] = {challenge.id: challenge.status.value for challenge in list_challenges(store)}

    assert axes == json.loads((FIXTURE / "master_axes.json").read_text())
    assert all(row["migrated"] for row in list_decisions(store))
    assert list_decisions(store)  # moved, once


@pytest.mark.parametrize("reviewer", [None, "Someone <s@example.org>"])
def test_the_reviewer_is_the_git_identity_unless_given(tmp_path: Path, reviewer):
    root = _repo(tmp_path)
    store = ensure_project(root)
    _awaiting_review(store)
    Researcher(store, reviewer_id=reviewer).decide_acceptance("clm_1", "accept")
    assert list_decisions(store)[0]["reviewer_id"] == (reviewer or "Ada Researcher <ada@example.org>")
