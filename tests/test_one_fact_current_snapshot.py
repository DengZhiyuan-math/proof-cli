"""One fact in one place (#284): a node's current snapshot is its highest version, read from the versions themselves
rather than from a flag each new snapshot has to reset on the others."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from _proofs import submit_proof
from proof_cli.cli import app
from proof_cli.exchange import bundle_to_json, export_exchange_bundle, import_exchange_bundle, parse_bundle
from proof_cli.proof_map import create_node, get_current_candidate_proof, list_candidate_proofs
from proof_cli.storage import ensure_project


def _two_snapshots(root: Path):
    store = ensure_project(root)
    create_node(store, node_id="N", kind="claim", statement="N holds")
    submit_proof(store, "N", claimant_id="agent_a", scoping_rationale="first", content="v1 attempt")
    submit_proof(store, "N", claimant_id="agent_a", scoping_rationale="second", content="v2 attempt")
    return store


def test_a_bundle_whose_snapshots_come_newest_first_still_imports_its_newest_as_current(tmp_path: Path):
    bundle = parse_bundle(bundle_to_json(export_exchange_bundle(_two_snapshots(tmp_path / "source"))))
    bundle.candidate_proofs = list(reversed(bundle.candidate_proofs))
    target = ensure_project(tmp_path / "target")

    import_exchange_bundle(target, bundle)

    assert get_current_candidate_proof(target, "N").version == 2
    assert [(r.version, r.is_current) for r in list_candidate_proofs(target, "N")] == [(1, False), (2, True)]
    shown = CliRunner().invoke(app, ["node", "show", "N", "--root", str(tmp_path / "target"), "--json"])
    assert shown.exit_code == 0, shown.output
    assert '"is_current": true' in shown.output and '"is_current": false' in shown.output


def test_an_exported_bundle_still_says_which_snapshot_is_current(tmp_path: Path):
    bundle = export_exchange_bundle(_two_snapshots(tmp_path))
    assert [(r.version, r.is_current) for r in bundle.candidate_proofs] == [(1, False), (2, True)]
