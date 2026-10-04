"""A Review snapshot carries a key-ideas summary (ADR-0013, issue #103).

Each node keeps a working `key-ideas.md` (核心思路 and 主要步骤 required, 难点 and 未覆盖
optional). Requesting review freezes it with the proof, under the manifest and its SHA-256,
and refuses without it (KEY_IDEAS_REQUIRED). A change to the summary alone is a new version.
The page shows the summary; an older snapshot without one is still reviewed as before.
"""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import KEY_IDEAS, write_key_ideas
from _researcher import researcher
from _review_client import DirectClient
from proof_cli import key_ideas
from proof_cli.authority import candidate_proof_sha256, list_decisions
from proof_cli.cli import app
from proof_cli.domain import CandidateProofRecord
from proof_cli.errors import ERROR_CODES
from proof_cli.proof_map import (
    ProofMapError,
    record_key_ideas_draft,
    create_node,
    get_acceptance_state,
    get_workflow_state,
    list_candidate_proofs,
    request_review,
)
from proof_cli.storage import ensure_project, insert_candidate_proof
from proof_cli.vault import build_is_current

PROOF = "\\documentclass{amsart}\n\\input{../preamble}\n\\begin{document}\nBy compactness.\n\\end{document}\n"


def _node(tmp_path: Path, node_id: str = "clm", *, summary: str | None = KEY_IDEAS):
    store = ensure_project(tmp_path)
    create_node(store, node_id=node_id, kind="claim", statement="s")
    folder = store.root / "proofs" / node_id
    (folder / "proof.tex").write_text(PROOF)
    if summary is not None:
        write_key_ideas(store, node_id, summary)
    return store, folder


def _request(store, node_id="clm"):
    return request_review(store, node_id, requested_by="agent_a", rationale="scoped")


def _cli(tmp_path: Path, *extra: str):
    return CliRunner().invoke(
        app, ["node", "request-review", "clm", "--root", str(tmp_path), "--requested-by", "agent_a", "--rationale", "scoped", *extra]
    )


# -- the file and its fields ---------------------------------------------------------------


def test_the_four_fields_are_read_from_their_headings():
    parsed = key_ideas.parse(KEY_IDEAS)
    assert parsed.fields["core_idea"] == "The bound follows from compactness of $[0, 1]$."
    assert parsed.fields["main_steps"].startswith("1. Cover the interval (uses lem_cover).")
    assert parsed.fields["difficulties"].startswith("The subcover's size")
    assert parsed.fields["not_covered"] == "无"
    assert parsed.missing == []


def test_a_template_with_only_its_prompts_leaves_both_required_fields_empty():
    assert key_ideas.parse(key_ideas.TEMPLATE).missing == ["核心思路", "主要步骤"]
    assert key_ideas.parse("## 核心思路\nWhy.\n").missing == ["主要步骤"]
    # the optional fields may be left out altogether
    assert key_ideas.parse("# 核心思路\nWhy.\n### 主要步骤\n1. a\n").missing == []


OLD_MARKER = "<!-- key-ideas drafted-by: studio-agent -->"


def test_a_summary_with_the_old_drafted_marker_still_parses():
    """An earlier draft of ADR-0013 wrote this first line; it is now just a comment."""
    parsed = key_ideas.parse(OLD_MARKER + "\n" + KEY_IDEAS)
    assert parsed.missing == [] and parsed.fields == key_ideas.parse(KEY_IDEAS).fields


def test_provenance_compares_the_frozen_summary_with_the_recorded_draft():
    draft = KEY_IDEAS.encode()
    assert key_ideas.provenance(draft, None) == key_ideas.AUTHOR
    assert key_ideas.provenance(draft, key_ideas.digest(draft)) == key_ideas.AGENT_CONFIRMED
    assert key_ideas.provenance(draft + b"edited\n", key_ideas.digest(draft)) == key_ideas.AGENT_EDITED


# -- request_review needs it ---------------------------------------------------------------


def test_the_error_code_is_registered():
    assert "KEY_IDEAS_REQUIRED" in ERROR_CODES


@pytest.mark.parametrize("summary, missing", [
    (None, ["key-ideas.md"]),
    (key_ideas.TEMPLATE, ["核心思路", "主要步骤"]),
    ("## 核心思路\nBy compactness.\n\n## 主要步骤\n\n## 难点\n无\n", ["主要步骤"]),
])
def test_a_missing_summary_or_an_empty_required_field_is_refused(tmp_path: Path, summary, missing):
    store, folder = _node(tmp_path, summary=summary)
    with pytest.raises(ProofMapError) as refused:
        _request(store)
    assert refused.value.code == "KEY_IDEAS_REQUIRED"
    assert refused.value.details["missing"] == missing
    assert refused.value.details["path"] == "proofs/clm/key-ideas.md"
    assert list_candidate_proofs(store, "clm") == [] and not (folder / "snapshots").exists()


def test_the_cli_refuses_without_a_summary_in_json_and_in_text(tmp_path: Path):
    _node(tmp_path, summary=None)

    as_json = _cli(tmp_path, "--json")
    assert as_json.exit_code == 1
    envelope = json.loads(as_json.stdout)
    assert envelope["ok"] is False and envelope["error"]["code"] == "KEY_IDEAS_REQUIRED"
    assert envelope["error"]["missing"] == ["key-ideas.md"] and envelope["error"]["path"] == "proofs/clm/key-ideas.md"

    as_text = _cli(tmp_path)
    assert as_text.exit_code == 1
    assert "KEY_IDEAS_REQUIRED" in as_text.stdout and "key-ideas.md" in as_text.stdout and "核心思路" in as_text.stdout


def test_the_cli_names_the_empty_required_field(tmp_path: Path):
    _node(tmp_path, summary="## 核心思路\nBy compactness.\n")
    as_text = _cli(tmp_path)
    assert as_text.exit_code == 1 and "KEY_IDEAS_REQUIRED" in as_text.stdout and "主要步骤" in as_text.stdout


def test_the_page_refuses_the_same_way(tmp_path: Path):
    store, _ = _node(tmp_path, summary=None)
    client = DirectClient(store)
    try:
        status, body = client.post("/api/node/clm/request-review", {"rationale": "scoped"})
    finally:
        client.app.close()
    assert status == 400 and body["error"]["code"] == "KEY_IDEAS_REQUIRED"


# -- it is frozen with the proof, and counts toward the snapshot's hash ---------------------------


def test_the_summary_is_frozen_in_the_manifest_and_hashed(tmp_path: Path):
    store, folder = _node(tmp_path)
    record = _request(store)

    snapshot = folder / "snapshots" / "v1"
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert manifest["files"]["key-ideas.md"] == hashlib.sha256(KEY_IDEAS.encode()).hexdigest()
    assert (snapshot / "node" / "key-ideas.md").read_text() == KEY_IDEAS
    assert candidate_proof_sha256(store, record.id) == record.sha256

    # the same proof with another summary is another snapshot hash
    other_store, other_folder = _node(tmp_path / "other", summary=KEY_IDEAS.replace("compactness", "completeness"))
    assert _request(other_store).sha256 != record.sha256


def test_editing_the_frozen_summary_after_an_accept_makes_the_decision_unverifiable(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm", "accept")
    assert get_acceptance_state(store, "clm") == "accepted"

    frozen = folder / "snapshots" / "v1" / "node" / "key-ideas.md"
    frozen.write_text(frozen.read_text().replace("compactness", "a different idea"))

    assert get_acceptance_state(store, "clm") == "unverifiable"


def test_changing_only_the_summary_is_a_new_version_back_in_review(tmp_path: Path):
    store, folder = _node(tmp_path)
    _request(store)
    researcher(store).decide_acceptance("clm", "accept")

    write_key_ideas(store, "clm", KEY_IDEAS.replace("无", "The case $n = 0$."))
    second = _request(store)

    assert second.version == 2
    assert get_workflow_state(store, "clm") == "review-needed"
    # and an unchanged summary with an unchanged proof is still refused
    with pytest.raises(ProofMapError) as refused:
        _request(store)
    assert refused.value.code == "WORKING_PROOF_UNCHANGED"


def test_editing_the_summary_does_not_make_the_pdf_stale(tmp_path: Path):
    """The PDF is compiled from the LaTeX, not from the summary: a build stays current across a summary edit."""
    import os
    import time

    store, folder = _node(tmp_path)
    pdf = folder / "build" / "proof.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4\n")
    later = time.time() + 5
    os.utime(pdf, (later, later))
    assert build_is_current(store.root, "clm")
    summary = folder / "key-ideas.md"
    os.utime(summary, (later + 5, later + 5))
    assert build_is_current(store.root, "clm")
    (folder / "proof.tex").touch()
    os.utime(folder / "proof.tex", (later + 5, later + 5))
    assert not build_is_current(store.root, "clm")


# -- the page shows it ----------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path):
    store, folder = _node(tmp_path)
    client = DirectClient(store)
    yield store, folder, client
    client.app.close()


def _data(response):
    status, body = response
    assert status == 200 and body["ok"], body
    return body["data"]


def test_the_node_view_carries_the_frozen_summary(client):
    store, folder, client = client
    _request(store)
    write_key_ideas(store, "clm", "## 核心思路\nA newer working idea.\n")  # the working file moves on; the view shows the frozen one

    view = _data(client.get("/api/node/clm"))
    summary = view["candidate_proof"]["key_ideas"]
    assert summary["fields"]["core_idea"] == "The bound follows from compactness of $[0, 1]$."
    assert summary["fields"]["difficulties"].startswith("The subcover's size")
    assert summary["drafted_by"] == key_ideas.AUTHOR
    # the working summary is shown apart, so the panel knows whether one must still be written
    assert view["key_ideas_working"] == {"exists": True, "missing": ["主要步骤"]}


def test_the_node_view_says_when_there_is_no_working_summary(tmp_path: Path):
    store, _ = _node(tmp_path, summary=None)
    client = DirectClient(store)
    try:
        view = _data(client.get("/api/node/clm"))
    finally:
        client.app.close()
    assert view["key_ideas_working"] == {"exists": False, "missing": ["key-ideas.md"]}
    assert view["candidate_proof"] is None


def test_the_review_card_carries_the_summary(client):
    store, folder, client = client
    _request(store)
    (card,) = _data(client.get("/api/state"))["pending"]
    fields = card["candidate_proof"]["key_ideas"]["fields"]
    assert fields["core_idea"].startswith("The bound follows") and fields["difficulties"].startswith("The subcover's size")


def test_the_map_carries_each_nodes_core_idea(client):
    store, folder, client = client
    create_node(store, node_id="open", kind="claim", statement="not yet reviewed")
    _request(store)
    nodes = {n["id"]: n for n in _data(client.get("/api/map"))["nodes"]}
    assert nodes["clm"]["core_idea"] == "The bound follows from compactness of $[0, 1]$."
    assert nodes["open"]["core_idea"] is None


# -- an older snapshot without a summary is reviewed as before ---------------------------------------


def _old_snapshot(store, node_id="old"):
    """A single-file snapshot from before ADR-0013 (and ADR-0011): no summary anywhere."""
    text = b"\\documentclass{amsart}\\begin{document}old\\end{document}\n"
    create_node(store, node_id=node_id, kind="claim", statement="s")
    path = store.root / "proofs" / node_id / "snapshots" / "v1.tex"
    path.parent.mkdir(parents=True)
    path.write_bytes(text)
    insert_candidate_proof(store, CandidateProofRecord(
        id="cp-old", node_id=node_id, version=1, file_path=f"proofs/{node_id}/snapshots/v1.tex",
        submitted_by="agent_a", scoping_rationale="scoped", sha256=hashlib.sha256(text).hexdigest(),
    ))


def test_an_old_snapshot_without_a_summary_is_still_reviewable(tmp_path: Path):
    store = ensure_project(tmp_path)
    _old_snapshot(store)
    client = DirectClient(store)
    try:
        view = _data(client.get("/api/node/old"))
        assert view["candidate_proof"]["key_ideas"] is None
        accept = next(d for d in view["decisions"] if d["decision"] == "accept")
        result = _data(client.post("/api/decide", {"decisions": [{**accept, "viewed_candidate_proof_sha256": view["candidate_proof"]["sha256"]}]}))
        pending = [c for c in _data(client.get("/api/state"))["pending"] if c["node_id"] == "old"]
    finally:
        client.app.close()
    assert result["results"][0]["ok"], result
    assert get_acceptance_state(store, "old") == "accepted"
    assert pending == []  # decided: no longer awaiting review


# -- who wrote it: recorded in project state, not in the file ----------------------------------------


def _draft(store, text: str = KEY_IDEAS, node_id: str = "clm"):
    """The proof agent writes the working summary, and the studio records it."""
    write_key_ideas(store, node_id, text)
    record_key_ideas_draft(store, node_id, agent="studio-agent", content=text.encode())


def _accept_and_read(store, folder):
    researcher(store).decide_acceptance("clm", "accept")
    (decision,) = [row for row in list_decisions(store) if row["kind"] == "acceptance"]
    line = json.loads((folder / "reviews.jsonl").read_text().splitlines()[-1])
    return decision, line


def test_an_untouched_agent_draft_is_the_agents_confirmed_by_the_author(tmp_path: Path):
    store, folder = _node(tmp_path, summary=None)
    _draft(store)

    record = _request(store)
    assert record.key_ideas_drafted_by == key_ideas.AGENT_CONFIRMED
    assert list_candidate_proofs(store, "clm")[0].key_ideas_drafted_by == key_ideas.AGENT_CONFIRMED  # on the snapshot's record

    decision, line = _accept_and_read(store, folder)
    assert line["key_ideas_drafted_by"] == key_ideas.AGENT_CONFIRMED
    assert line["payload"]["key_ideas_drafted_by"] == key_ideas.AGENT_CONFIRMED  # in what the binding covers
    assert decision["payload"].key_ideas_drafted_by == key_ideas.AGENT_CONFIRMED

    client = DirectClient(store)
    try:
        view = _data(client.get("/api/node/clm"))
    finally:
        client.app.close()
    assert view["candidate_proof"]["key_ideas"]["drafted_by"] == key_ideas.AGENT_CONFIRMED
    (history,) = [r for r in view["history"] if r.get("kind") == "acceptance"]
    assert history["key_ideas_drafted_by"] == key_ideas.AGENT_CONFIRMED


def test_an_agent_draft_the_author_edited_says_so(tmp_path: Path):
    store, folder = _node(tmp_path, summary=None)
    _draft(store)
    write_key_ideas(store, "clm", KEY_IDEAS.replace("compactness", "compactness and continuity"))
    assert _request(store).key_ideas_drafted_by == key_ideas.AGENT_EDITED


def test_a_summary_only_the_author_wrote_is_the_authors(tmp_path: Path):
    store, folder = _node(tmp_path)
    assert _request(store).key_ideas_drafted_by == key_ideas.AUTHOR
    decision, line = _accept_and_read(store, folder)
    assert line["key_ideas_drafted_by"] == key_ideas.AUTHOR and line["payload"]["key_ideas_drafted_by"] == key_ideas.AUTHOR


def test_the_old_marker_line_no_longer_decides_the_provenance(tmp_path: Path):
    # a marker line with no recorded draft: the author's
    store, folder = _node(tmp_path, summary=OLD_MARKER + "\n" + KEY_IDEAS)
    assert _request(store).key_ideas_drafted_by == key_ideas.AUTHOR
    # a recorded draft whose marker line the author then deletes: still the agent's draft, edited
    other, _ = _node(tmp_path / "other", summary=None)
    _draft(other, OLD_MARKER + "\n" + KEY_IDEAS)
    write_key_ideas(other, "clm", KEY_IDEAS)
    assert _request(other).key_ideas_drafted_by == key_ideas.AGENT_EDITED


def test_every_decision_on_a_snapshot_carries_its_provenance(tmp_path: Path):
    from proof_cli.proof_map import record_evidence_check

    store, folder = _node(tmp_path, summary=None)
    _draft(store)
    record = _request(store)
    check = record_evidence_check(store, record.id, "passed", notes="lean", run_by="lean")
    researcher(store).decide_evidence_review(check.id, "trusted")
    researcher(store).decide_acceptance("clm", "revision-requested")
    lines = [json.loads(line) for line in (folder / "reviews.jsonl").read_text().splitlines()]
    assert [line["kind"] for line in lines] == ["evidence_review", "acceptance"]
    assert all(line["key_ideas_drafted_by"] == key_ideas.AGENT_CONFIRMED for line in lines)
    assert all(line["payload"]["key_ideas_drafted_by"] == key_ideas.AGENT_CONFIRMED for line in lines)


def test_changing_the_recorded_provenance_after_an_accept_makes_it_unverifiable(tmp_path: Path):
    store, folder = _node(tmp_path, summary=None)
    _draft(store)
    record = _request(store)
    researcher(store).decide_acceptance("clm", "accept")
    assert get_acceptance_state(store, "clm") == "accepted"

    with store.transaction() as conn:
        conn.execute("UPDATE candidate_proofs SET key_ideas_drafted_by = ? WHERE id = ?", (key_ideas.AUTHOR, record.id))

    assert get_acceptance_state(store, "clm") == "unverifiable"
