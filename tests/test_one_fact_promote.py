"""One fact in one place (#284), part 3: a node's kind is the kind it was made with, and a Promote is read from its line.

Promote used to rewrite the node's stored kind and record its decision as well, while a Promote arriving through git
left the row a `claim` and was read from its line alone (`_effective_kind`): two sources of "lemma". Now the row keeps
the kind the node was made with, every edit included, and the counted Promote line makes it a Lemma wherever the node
is read. Synthetic projects only."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli import storage
from proof_cli.cli import app
from proof_cli.exchange import bundle_to_json, export_exchange_bundle, import_exchange_bundle, parse_bundle
from proof_cli.proof_map import ProofMapError, add_dependency, create_node, get_node, list_nodes, open_challenge
from proof_cli.storage import ensure_project


def _accepted_claim(store, node_id: str = "C") -> None:
    create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} holds")
    submit_proof(store, node_id, claimant_id="claude-code", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, "accept")


def _stored_kind(store, node_id: str) -> str:
    return storage.get_proof_map_node(store, node_id).kind.value


def _promote_refused(store, node_id: str) -> str:
    with pytest.raises(ProofMapError) as refused:
        researcher(store).promote_to_lemma(node_id)
    return refused.value.code


def test_a_promoted_claim_reads_as_a_lemma_from_its_line_and_its_row_keeps_the_kind_it_was_made_with(tmp_path: Path):
    """The same reading as a Promote that arrived through git: the row says `claim`, the counted line says Lemma."""
    store = ensure_project(tmp_path)
    _accepted_claim(store)
    create_node(store, node_id="L2", kind="lemma", statement="L2 holds")

    assert researcher(store).promote_to_lemma("C").kind.value == "lemma"
    assert get_node(store, "C").kind.value == "lemma" and {n.id: n.kind.value for n in list_nodes(store)}["C"] == "lemma"
    shown = CliRunner().invoke(app, ["node", "show", "C", "--root", str(tmp_path), "--json"])
    assert '"kind": "lemma"' in shown.stdout and '"kind": "claim"' not in shown.stdout
    assert _promote_refused(store, "C") == "NOT_A_CLAIM"
    assert _stored_kind(store, "C") == "claim"

    open_challenge(store, "C", kind="proof", opened_by="claude-code", rationale="does step 2 use L2?")
    add_dependency(store, "C", "L2", edited_by="claude-code")   # an edit writes the node's row again
    assert get_node(store, "C").dependencies == ["L2"]
    assert get_node(store, "C").kind.value == "lemma"
    assert _stored_kind(store, "C") == "claim"


def test_a_promoted_node_moves_to_another_project_as_a_claim(tmp_path: Path):
    """No decision crosses over (core/exchange.py): neither the Acceptance a Promote needs nor the Promote itself."""
    source = ensure_project(tmp_path / "source")
    _accepted_claim(source)
    researcher(source).promote_to_lemma("C")
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, parse_bundle(bundle_to_json(export_exchange_bundle(source))))
    assert get_node(target, "C").kind.value == "claim"


def test_a_node_an_old_promote_rewrote_still_reads_as_a_lemma(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted_claim(store)
    researcher(store).promote_to_lemma("C")
    with contextlib.closing(sqlite3.connect(store.db_path)) as conn, conn:   # as a Promote before #284 left the row
        conn.execute("UPDATE proof_map_nodes SET kind = 'lemma', data = json_set(data, '$.kind', 'lemma') WHERE id = 'C'")
    assert get_node(store, "C").kind.value == "lemma"
    assert _promote_refused(store, "C") == "NOT_A_CLAIM"
    listed = json.loads(CliRunner().invoke(app, ["node", "list", "--root", str(tmp_path), "--json"]).stdout)["data"]
    assert [node["kind"] for node in listed if node["id"] == "C"] == ["lemma"]
