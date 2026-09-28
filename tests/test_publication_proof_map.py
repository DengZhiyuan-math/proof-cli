from _researcher import researcher
"""Issue #30: publication tracks two orthogonal states for a ProofMapNode —
the node's own acceptance_state/integrity_state, read live from the core
model, and a separate editorial readiness track that only a human editor
ever advances. Neither is derived from the other.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import claim_node, create_node, submit_candidate_proof
from proof_cli.publication import (
    PublicationAudience,
    PublicationReadiness,
    build_publication_view,
    get_publication_claim,
    list_publication_claims,
    node_acceptance_and_integrity,
    set_publication_claim,
)
from proof_cli.storage import ensure_project, load_project

runner = CliRunner()


def _accept(store, node_id, *, claimant="agent_a", session="sess_1"):
    claim_node(store, node_id, claimant_id=claimant, session_id=session)
    submit_candidate_proof(
        store, node_id, claimant_id=claimant, session_id=session,
        scoping_rationale="scoped correctly", content="proof text")
    return researcher(store).decide_acceptance(node_id, "accept")


def test_fresh_node_gets_a_default_internal_draft_claim_regardless_of_acceptance(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A claim")
    _accept(store, "clm_1")

    claims = {c.object_id: c for c in list_publication_claims(store, object_type="proof_map_node")}
    assert claims["clm_1"].readiness == PublicationReadiness.internal_draft


def test_paper_ready_is_never_derived_from_accepted_and_requires_an_explicit_call(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A claim")
    _accept(store, "clm_1")

    # accepted, but nobody made an editorial decision yet
    acceptance_state, _ = node_acceptance_and_integrity(store, "proof_map_node", "clm_1")
    assert acceptance_state == "accepted"
    claim = get_publication_claim(store, "clm_1", object_type="proof_map_node")
    assert claim.readiness == PublicationReadiness.internal_draft

    # an explicit human editorial action is the only way to reach paper_ready
    set_publication_claim(store, "clm_1", object_type="proof_map_node", readiness=PublicationReadiness.paper_ready)
    claim = get_publication_claim(store, "clm_1", object_type="proof_map_node")
    assert claim.readiness == PublicationReadiness.paper_ready


def test_acceptance_and_integrity_are_read_live_not_stored_on_the_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A claim")
    set_publication_claim(store, "clm_1", object_type="proof_map_node", readiness=PublicationReadiness.paper_ready)

    # not accepted yet: readiness (editorial) is paper_ready, acceptance is not
    acceptance_state, _ = node_acceptance_and_integrity(store, "proof_map_node", "clm_1")
    assert acceptance_state == "unreviewed"

    # accept afterward, with no further publication call at all
    _accept(store, "clm_1")

    # the same read call now reflects the new acceptance state immediately —
    # nothing needed to be re-synced or re-derived on the publication side
    acceptance_state, _ = node_acceptance_and_integrity(store, "proof_map_node", "clm_1")
    assert acceptance_state == "accepted"
    claim = get_publication_claim(store, "clm_1", object_type="proof_map_node")
    assert claim.readiness == PublicationReadiness.paper_ready


def test_theorem_contract_claims_have_no_acceptance_or_integrity_axis(tmp_path: Path):
    store = ensure_project(tmp_path)
    acceptance_state, integrity_state = node_acceptance_and_integrity(store, "theorem_contract", "thm_main")
    assert acceptance_state is None
    assert integrity_state is None


def test_publication_view_selection_carries_live_acceptance_and_integrity(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="clm_1", kind="claim", statement="A claim")
    _accept(store, "clm_1")
    set_publication_claim(store, "clm_1", object_type="proof_map_node", readiness=PublicationReadiness.paper_ready)

    view = build_publication_view(store, PublicationAudience.paper)
    selection = next(s for s in view.selections if s.claim.object_id == "clm_1")
    assert selection.visible is True
    assert selection.acceptance_state == "accepted"
    assert selection.integrity_state == "current"


def test_no_derived_readiness_function_remains(tmp_path: Path):
    import proof_cli.publication as publication_module

    assert not hasattr(publication_module, "_derived_readiness")


def test_cli_publication_set_and_show_for_a_proof_map_node(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "A claim", "--root", str(tmp_path)])

    set_result = runner.invoke(
        app,
        [
            "publication", "set", "clm_1", "paper_ready", "--root", str(tmp_path),
            "--object-type", "proof_map_node",
        ],
    )
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["publication", "show", "clm_1", "--root", str(tmp_path)])
    assert show_result.exit_code == 0
    payload = json.loads(show_result.stdout)
    assert payload[0]["readiness"] == "paper_ready"


def test_cli_publication_export_bundle_carries_live_acceptance_state(tmp_path: Path):
    runner.invoke(app, ["node", "create", "clm_1", "claim", "A claim", "--root", str(tmp_path)])
    runner.invoke(app, ["node", "claim", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a", "--json"])
    runner.invoke(
        app,
        [
            "node", "submit", "clm_1", "--root", str(tmp_path), "--claimant", "agent_a", "--content", "proof text", "--rationale", "scoped correctly",
        ],
    )
    researcher(load_project(tmp_path)).decide_acceptance("clm_1", "accept")  # in the review app
    runner.invoke(
        app,
        [
            "publication", "set", "clm_1", "paper_ready", "--root", str(tmp_path),
            "--object-type", "proof_map_node",
        ],
    )

    export_result = runner.invoke(app, ["publication", "export", "--root", str(tmp_path), "--format", "bundle"])
    assert export_result.exit_code == 0
    bundle = json.loads(export_result.stdout)
    selections = bundle["view"]["selections"]
    clm_1_selection = next(s for s in selections if s["claim"]["object_id"] == "clm_1")
    assert clm_1_selection["acceptance_state"] == "accepted"
    assert clm_1_selection["integrity_state"] == "current"
