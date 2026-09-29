"""The proof map page as the map's home, and prism-local coupled by files only (issue #55, ADR-0008, ADR-0010)."""

import os
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _researcher import researcher
from _review_client import DirectClient, decide
from proof_cli.cli import app as cli_app
from proof_cli.proof_map import claim_node, create_node, open_challenge, request_review
from proof_cli.storage import ensure_project
from proof_cli.webapp.server import RequestError


def _write(store, node_id: str, body: str) -> Path:
    working = store.root / "proofs" / node_id / "proof.tex"
    working.write_text(working.read_text().replace("% Write the proof here.", body))
    return working


def _map(client) -> dict:
    return {n["id"]: n for n in client.get("/api/map")[1]["data"]["nodes"]}


def test_the_map_carries_every_node_with_its_axes_assignee_and_frontier(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="thm", kind="theorem", statement="Main", dependencies=[])
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    create_node(store, node_id="clm", kind="claim", statement="Uses the lemma", dependencies=["lem"])
    create_node(store, node_id="ref", kind="imported_result", statement="Known", source_locator="doi:x", source_version="v1")
    claim_node(store, "thm", claimant_id="agent_a")
    client = DirectClient(store)

    nodes = _map(client)

    assert set(nodes) == {"thm", "lem", "clm", "ref"}
    assert (nodes["thm"]["assignee"], nodes["thm"]["frontier"]) == ("agent_a", False)
    assert nodes["lem"]["frontier"] is True
    assert (nodes["clm"]["workflow_state"], nodes["clm"]["blocked_reason"], nodes["clm"]["frontier"]) == ("blocked", "not-accepted", False)
    assert nodes["clm"]["dependencies"] == ["lem"]
    assert (nodes["ref"]["acceptance_state"], nodes["ref"]["frontier"]) == ("unreviewed", False)
    assert {"acceptance_state", "workflow_state", "integrity_state"} <= set(nodes["lem"])


def test_accepting_from_the_page_changes_the_map(tmp_path: Path):
    """The ticket's walk-through: open a node from the map, read its snapshot, accept it, see the map change."""
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    create_node(store, node_id="clm", kind="claim", statement="Uses the lemma", dependencies=["lem"])
    _write(store, "lem", "Direct.")
    request_review(store, "lem", requested_by="agent_a", rationale="scoped")
    client = DirectClient(store)
    assert _map(client)["lem"]["workflow_state"] == "review-needed"

    view = client.get("/api/node/lem")[1]["data"]
    status, outcome = decide(
        client, [{"kind": "acceptance", "target_id": "lem", "decision": "accept", "viewed_candidate_proof_sha256": view["candidate_proof"]["sha256"]}]
    )

    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome
    nodes = _map(client)
    assert nodes["lem"]["acceptance_state"] == "accepted"
    assert (nodes["clm"]["workflow_state"], nodes["clm"]["frontier"]) == ("open", True)  # unblocked, now pickable


def test_a_challenged_node_shows_on_the_map_as_such(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    _write(store, "lem", "Direct.")
    request_review(store, "lem", requested_by="agent_a", rationale="scoped")
    researcher(store).decide_acceptance("lem", "accept")
    open_challenge(store, "lem", opened_by="agent_b", rationale="step 2?")

    assert _map(DirectClient(store))["lem"]["integrity_state"] == "challenged"


# -- PDFs: archived with the snapshot, or prism-local's build ------------------------------


def _build_pdf(store, node_id: str) -> Path:
    """What prism-local's build leaves behind (default outdir: build)."""
    pdf = store.root / "proofs" / node_id / "build" / "proof.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.5 compiled\n")
    return pdf


def test_a_pdf_built_from_the_requested_text_is_archived_with_its_snapshot(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    _write(store, "lem", "Direct.")
    _build_pdf(store, "lem")

    snapshot = request_review(store, "lem", requested_by="agent_a", rationale="scoped")

    archived = tmp_path / "proofs" / "lem" / "snapshots" / f"v{snapshot.version}.pdf"  # beside the frozen folder
    assert archived.read_bytes() == b"%PDF-1.5 compiled\n"
    client = DirectClient(store)
    assert client.get("/api/node/lem")[1]["data"]["pdfs"] == {"snapshot": True, "build": True}
    assert client.app.pdf("lem", "snapshot") == b"%PDF-1.5 compiled\n"


def test_a_stale_build_is_not_archived(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    pdf = _build_pdf(store, "lem")
    old = time.time() - 60
    os.utime(pdf, (old, old))
    _write(store, "lem", "Edited after the last build.")

    snapshot = request_review(store, "lem", requested_by="agent_a", rationale="scoped")

    assert not (tmp_path / "proofs" / snapshot.node_id / "snapshots" / f"v{snapshot.version}.pdf").exists()
    assert DirectClient(store).get("/api/node/lem")[1]["data"]["pdfs"] == {"snapshot": False, "build": True}


def test_a_build_older_than_the_shared_preamble_is_not_archived(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    _write(store, "lem", "Direct.")
    pdf = _build_pdf(store, "lem")
    past = time.time() - 60
    os.utime(pdf, (past, past))
    os.utime(store.root / "proofs" / "lem" / "proof.tex", (past - 10, past - 10))
    (store.root / "proofs" / "preamble.tex").write_text("% a macro changed after the build\n")

    snapshot = request_review(store, "lem", requested_by="agent_a", rationale="scoped")

    assert not (tmp_path / "proofs" / snapshot.node_id / "snapshots" / f"v{snapshot.version}.pdf").exists()


def test_an_archived_pdf_is_committed_with_the_decision(tmp_path: Path):
    for args in (["init", "--quiet"], ["config", "user.name", "Ada"], ["config", "user.email", "ada@example.org"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    _write(store, "lem", "Direct.")
    _build_pdf(store, "lem")
    request_review(store, "lem", requested_by="agent_a", rationale="scoped")

    researcher(store).decide_acceptance("lem", "accept")

    committed = subprocess.run(["git", "-C", str(tmp_path), "show", "--name-only", "--format=", "HEAD"], capture_output=True, text=True).stdout.split()
    # the whole frozen snapshot (ADR-0011) and its archived PDF
    assert set(committed) == {"proofs/lem/reviews.jsonl", "proofs/lem/snapshots/v1/manifest.json", "proofs/lem/snapshots/v1/node/proof.tex", "proofs/lem/snapshots/v1/shared/preamble.tex", "proofs/lem/snapshots/v1.pdf"}
    assert (tmp_path / "proofs" / ".gitignore").read_text() == "*/build/\n"  # prism-local's build output stays out of git


def test_a_missing_pdf_or_unknown_node_is_an_error(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    client = DirectClient(store)
    with pytest.raises(RequestError):
        client.app.pdf("lem", "build")
    from proof_cli.proof_map import ProofMapError

    with pytest.raises(ProofMapError):
        client.app.pdf("../../etc", "build")


# -- prism-local: coupled by files only ---------------------------------------------------


def test_the_map_commands_are_proof_map_serve_and_open():
    result = CliRunner().invoke(cli_app, ["map", "--help"])
    assert result.exit_code == 0 and "serve" in result.output and "open" in result.output
    hidden = CliRunner().invoke(cli_app, ["review", "--help"]).output
    assert "serve" not in hidden.split("Commands")[-1]  # the old names work, but aren't advertised
