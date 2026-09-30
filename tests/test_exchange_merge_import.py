"""Issue #31: exchange moves a whole proof map, Proof vault files included, as a merge.

Import validates the whole bundle first and then writes it in one SQLite
transaction; a failure writes nothing. Local records win; nothing a bundle
carries counts as a local decision or local trust.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.collaboration import list_comment_threads, list_comments
from proof_cli.commands import cmd_comment_add, cmd_goal_set, cmd_memory_add, cmd_publication_set
from proof_cli.domain import TheoremProvenanceKind, TheoremReviewState, TheoremStatus, TrustLevel
from proof_cli.exchange import (
    VaultFile,
    bundle_to_json,
    export_exchange_bundle,
    import_exchange_bundle,
    inspect_exchange_bundle,
    parse_bundle,
)
from proof_cli.governance import list_domain_pack_records, list_policy_records, list_reusable_asset_records, set_policy_profile
from proof_cli.memory import load_memory
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    get_acceptance_state,
    list_candidate_proofs,
    list_nodes,
)
from proof_cli.proof_state import load_state
from proof_cli.publication import load_publication_workspace
from proof_cli.references import ReferenceRecord, ReferenceReviewStatus, ReferenceSourceType, ReferenceTrustLevel
from proof_cli.storage import (
    import_reference,
    ensure_project,
    get_active_claim,
    get_reference,
    list_all_claims,
    list_all_dependency_pins,
    list_blockers,
    list_challenges,
    list_obligations,
    list_reference_reviews,
    list_references,
    read_latest_snapshot,
    store_reference,
)
from proof_cli.theorems import add_theorem, list_theorems, theorem_callability
from proof_cli.vault import archived_pdf_path, node_folder, working_proof_path
from proof_cli.webapp.server import ReviewApp

runner = CliRunner()


def _accepted_l_and_m(root: Path):
    """L → M: L Accepted, M awaiting review, both with snapshots; an archived PDF beside L's."""
    store = ensure_project(root)
    create_node(store, node_id="L", kind="lemma", statement="L holds")
    submit_proof(store, "L", claimant_id="agent_a", scoping_rationale="small", content="\\documentclass{amsart}\\begin{document}L proof\\end{document}\n")
    researcher(store).decide_acceptance("L", "accept")
    create_node(store, node_id="M", kind="claim", statement="M holds", dependencies=["L"])
    submit_proof(store, "M", claimant_id="agent_b", scoping_rationale="small", content="\\documentclass{amsart}\\begin{document}M proof\\end{document}\n")
    archived_pdf_path(root, "L", 1).write_bytes(b"%PDF-1.4 fake")
    return store


def _node_ids(store) -> set[str]:
    return {node.id for node in list_nodes(store)}


def _files_under(root: Path) -> set[str]:
    base = root / "proofs"
    return {p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file()} if base.exists() else set()


# -- acceptance 1: the proof map moves, files included, and arrives unreviewed ------


def test_an_accepted_map_moves_to_an_empty_project_with_its_files_and_arrives_unreviewed(tmp_path: Path) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    assert get_acceptance_state(source, "L") == "accepted"
    bundle = parse_bundle(bundle_to_json(export_exchange_bundle(source)))
    assert not any(file.path.endswith("reviews.jsonl") for file in bundle.vault_files)

    target_root = tmp_path / "target"
    target = ensure_project(target_root)
    report = import_exchange_bundle(target, bundle)

    assert _node_ids(target) == {"L", "M"}
    assert get_acceptance_state(target, "L") == "unreviewed"
    assert get_acceptance_state(target, "M") == "unreviewed"
    # the node page shows M's snapshot, rather than crashing on a missing file
    page = ReviewApp(target).node("M")
    assert page["candidate_proof"]["unreadable"] is False
    assert "M proof" in page["candidate_proof"]["text"]
    assert working_proof_path(target_root, "M").read_text().endswith("M proof\\end{document}\n")
    assert archived_pdf_path(target_root, "L", 1).read_bytes() == b"%PDF-1.4 fake"
    # the source's decisions don't travel as a file that would count here
    assert not (node_folder(target_root, "L") / "reviews.jsonl").exists()
    assert "vault_files" in report.imported_sections
    # imported candidate proofs carry no foreign decision's traces
    (l_proof,) = list_candidate_proofs(target, "L")
    assert l_proof.review_record_id is None and l_proof.interface_fingerprint is None


def test_reimporting_the_same_bundle_is_idempotent(tmp_path: Path) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, bundle)
    files = _files_under(tmp_path / "target")

    report = import_exchange_bundle(target, bundle)

    assert _node_ids(target) == {"L", "M"}
    assert _files_under(tmp_path / "target") == files
    assert report.kept_local["proof_map_nodes"] == 2


# -- acceptance 2: a path outside the node's folder rejects the whole bundle ---------


@pytest.mark.parametrize("bad_path", ["proofs/M/../../../etc/hosts", "/etc/hosts", "proofs/L/snapshots/v1/manifest.json", "notes/M.tex"])
def test_a_candidate_proof_path_outside_its_node_folder_rejects_the_whole_bundle(tmp_path: Path, bad_path: str) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    bundle.candidate_proofs = [
        proof.model_copy(update={"file_path": bad_path}) if proof.node_id == "M" else proof for proof in bundle.candidate_proofs
    ]
    target = ensure_project(tmp_path / "target")

    with pytest.raises(ProofMapError) as exc_info:
        import_exchange_bundle(target, bundle)

    assert exc_info.value.code == "INVALID_VAULT_PATH"
    assert _node_ids(target) == set()
    assert _files_under(tmp_path / "target") == set()


@pytest.mark.parametrize("bad_path", ["proofs/M/../L/proof.tex", "/tmp/evil.tex", "proofs/M/reviews.jsonl", "proofs/nobody/x.tex", "proofs\\M\\x.tex", "proofs/trust-rules.jsonl"])
def test_a_vault_file_outside_an_imported_node_folder_rejects_the_whole_bundle(tmp_path: Path, bad_path: str) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    data = b"sneaky"
    bundle.vault_files.append(VaultFile(path=bad_path, sha256=hashlib.sha256(data).hexdigest(), content_base64=base64.b64encode(data).decode()))
    target = ensure_project(tmp_path / "target")

    with pytest.raises(ProofMapError) as exc_info:
        import_exchange_bundle(target, bundle)

    assert exc_info.value.code == "INVALID_VAULT_PATH"
    assert _node_ids(target) == set()
    assert _files_under(tmp_path / "target") == set()


def test_a_vault_file_that_does_not_match_the_index_rejects_the_whole_bundle(tmp_path: Path) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    tampered = b"\\documentclass{amsart}\\begin{document}a different proof\\end{document}\n"
    for index, file in enumerate(bundle.vault_files):
        if file.path == "proofs/M/snapshots/v1/node/proof.tex":
            # consistent with itself, but no longer what M's index says was frozen
            bundle.vault_files[index] = VaultFile(path=file.path, sha256=hashlib.sha256(tampered).hexdigest(), content_base64=base64.b64encode(tampered).decode())
    target = ensure_project(tmp_path / "target")

    with pytest.raises(ProofMapError) as exc_info:
        import_exchange_bundle(target, bundle)

    assert exc_info.value.code == "VAULT_HASH_MISMATCH"
    assert _node_ids(target) == set()


def test_a_missing_snapshot_file_rejects_the_whole_bundle(tmp_path: Path) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    bundle.vault_files = [file for file in bundle.vault_files if not file.path.startswith("proofs/M/snapshots/")]
    target = ensure_project(tmp_path / "target")

    with pytest.raises(ProofMapError) as exc_info:
        import_exchange_bundle(target, bundle)

    assert exc_info.value.code == "VAULT_FILE_MISSING"
    assert _node_ids(target) == set()


def test_a_failed_file_write_rolls_the_import_back_and_removes_what_it_wrote(tmp_path: Path, monkeypatch) -> None:
    import proof_cli.exchange as exchange_module

    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    target_root = tmp_path / "target"
    target = ensure_project(target_root)
    cmd_goal_set("local goal", root=target_root)
    real_write = exchange_module._write_vault_file
    calls = {"n": 0}

    def failing(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        real_write(path, data)

    monkeypatch.setattr(exchange_module, "_write_vault_file", failing)
    with pytest.raises(OSError):
        import_exchange_bundle(target, bundle)

    assert calls["n"] == 3
    assert _node_ids(target) == set()
    assert list_all_claims(target) == []
    assert _files_under(target_root) == set()
    assert load_state(target).open_goals == ["local goal"]


def test_a_record_id_already_used_here_rejects_the_whole_bundle(tmp_path: Path) -> None:
    target = ensure_project(tmp_path / "target")
    create_node(target, node_id="X", kind="claim", statement="local X")
    local_claim = claim_node(target, "X", claimant_id="me")

    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    bundle.claims.append(local_claim.model_copy(update={"node_id": "M", "claimant_id": "someone"}))

    with pytest.raises(ProofMapError) as exc_info:
        import_exchange_bundle(target, bundle)

    assert exc_info.value.code == "IMPORT_ID_CONFLICT"
    assert _node_ids(target) == {"X"}


# -- acceptance 3: a second Theorem rejects the whole bundle, and changes nothing ----


def test_a_second_theorem_rejects_the_bundle_and_leaves_every_local_record(tmp_path: Path) -> None:
    root = tmp_path / "local"
    local = ensure_project(root, project_id="proj_local")
    create_node(local, node_id="T_local", kind="theorem", statement="the local theorem")
    cmd_goal_set("local goal", root=root)
    cmd_memory_add("local memory note", root=root)
    cmd_comment_add("proof_map_node", "T_local", "a local comment", root=root, author_id="me")
    before = (load_state(local).model_dump(), load_memory(local).model_dump(), [c.content for c in list_comments(local)])

    foreign = ensure_project(tmp_path / "foreign", project_id="proj_foreign")
    create_node(foreign, node_id="T_foreign", kind="theorem", statement="another theorem")
    create_node(foreign, node_id="C", kind="claim", statement="c")
    cmd_goal_set("foreign goal", root=tmp_path / "foreign")

    with pytest.raises(ProofMapError) as exc_info:
        import_exchange_bundle(local, export_exchange_bundle(foreign))

    assert exc_info.value.code == "DUPLICATE_THEOREM"
    assert _node_ids(local) == {"T_local"}
    after = (load_state(local).model_dump(), load_memory(local).model_dump(), [c.content for c in list_comments(local)])
    assert after == before
    assert load_state(local).project_id == "proj_local"


# -- acceptance 4: merge, never overwrite --------------------------------------------


def test_an_unrelated_bundle_keeps_the_local_goal_comments_memory_and_publication(tmp_path: Path) -> None:
    root = tmp_path / "local"
    local = ensure_project(root, project_id="proj_local")
    add_theorem(local, theorem_id="thm_local", kind="lemma", name="Local", statement="A")
    cmd_goal_set("local goal", root=root)
    cmd_memory_add("local memory note", root=root)
    cmd_comment_add("theorem_contract", "thm_local", "a local comment", root=root, author_id="me")
    cmd_publication_set("thm_local", "collaborator_ready", root=root, title="Local claim", object_type="theorem_contract")

    foreign_root = tmp_path / "foreign"
    foreign = ensure_project(foreign_root, project_id="proj_foreign")
    add_theorem(foreign, theorem_id="thm_foreign", kind="lemma", name="Foreign", statement="B")
    add_theorem(foreign, theorem_id="thm_local", kind="lemma", name="Their copy", statement="A")
    cmd_goal_set("foreign goal", root=foreign_root)
    cmd_memory_add("foreign memory note", root=foreign_root)
    cmd_comment_add("theorem_contract", "thm_local", "a foreign comment on the same object", root=foreign_root, author_id="them")
    cmd_publication_set("thm_local", "internal_draft", root=foreign_root, title="Foreign claim on the same object", object_type="theorem_contract")
    cmd_publication_set("thm_foreign", "internal_draft", root=foreign_root, title="Foreign claim", object_type="theorem_contract")

    import_exchange_bundle(local, export_exchange_bundle(foreign))

    state = load_state(local)
    assert state.project_id == "proj_local"
    assert state.open_goals[0] == "local goal" and "foreign goal" in state.open_goals
    contents = [artifact.content for layer in ("working", "semantic", "episodic", "procedural") for artifact in getattr(load_memory(local), layer)]
    assert "local memory note" in contents and "foreign memory note" in contents
    assert {c.content for c in list_comments(local)} == {"a local comment", "a foreign comment on the same object"}
    assert len(list_comment_threads(local, object_type="theorem_contract", object_id="thm_local")) == 1
    claims = {claim.object_id: claim for claim in load_publication_workspace(local).claims}
    assert claims["thm_local"].title == "Local claim"  # the local declaration wins
    assert "thm_foreign" in claims
    assert {c.id for c in list_theorems(local)} == {"thm_local", "thm_foreign"}


# -- acceptance 5: claims arrive released ------------------------------------------


def test_an_imported_active_claim_arrives_released_and_is_reported(tmp_path: Path) -> None:
    source = ensure_project(tmp_path / "source")
    create_node(source, node_id="K", kind="claim", statement="k")
    claim = claim_node(source, "K", claimant_id="agent_far_away", session_id="s1")
    target = ensure_project(tmp_path / "target")

    report = import_exchange_bundle(target, export_exchange_bundle(source))

    assert get_active_claim(target, "K") is None
    (imported,) = list_all_claims(target)
    assert imported.id == claim.id and imported.released_at is not None
    assert report.released_claims == [{"claim_id": claim.id, "node_id": "K", "claimant_id": "agent_far_away"}]


# -- acceptance 6: what inspect calls preserved, import writes ----------------------


def _rich_source(root: Path):
    from test_governance import _asset, _pack
    from proof_cli.automation import default_policy_profile
    from proof_cli.governance import install_domain_pack, publish_reusable_asset
    from proof_cli.reusable_assets import ReusableAssetReuseStatus, ReusableAssetTrustLevel
    from proof_cli.domain import BlockerRecord, ProofObligation
    from proof_cli.storage import store_blocker, store_obligation
    from proof_cli.snapshot import create_snapshot

    store = _accepted_l_and_m(root)
    open_challenge_on = "L"
    from proof_cli.proof_map import open_challenge

    open_challenge(store, open_challenge_on, opened_by="agent_c", rationale="check")
    create_node(store, node_id="K", kind="claim", statement="k")
    claim_node(store, "K", claimant_id="agent_k")
    add_theorem(store, theorem_id="thm_x", kind="lemma", name="X", statement="X")
    store_obligation(store, ProofObligation(id="obl_x", goal_statement="show X"))
    store_blocker(store, BlockerRecord(id="blk_x", scope="X", description="stuck", failure_type="gap"))
    store_reference(store, ReferenceRecord(id="ref_x", title="Ref", year=2020))
    from proof_cli.storage import import_reference

    import_reference(store, ReferenceRecord(id="ref_y", title="Ref Y", year=2021))
    publish_reusable_asset(
        store,
        _asset("asset_x", "proj_alpha", trust_level=ReusableAssetTrustLevel.temporary_admit, reuse_status=ReusableAssetReuseStatus.private_experimental, notes="n"),
    )
    install_domain_pack(
        store,
        _pack("pack_x", "proj_alpha"),
        installed_by="me",
        project_tags=["spectral", "analysis"],
        available_asset_ids=["asset_shared_uniformity"],
        available_asset_kinds=["proof_pattern"],
        notation_profile="spectral_default",
    )
    set_policy_profile(store, default_policy_profile(name="policy_x"))
    cmd_goal_set("goal_x", root=root)
    cmd_memory_add("memory_x", root=root)
    cmd_comment_add("proof_map_node", "L", "comment_x", root=root, author_id="me")
    cmd_publication_set("thm_x", "internal_draft", root=root, title="X claim", object_type="theorem_contract")
    create_snapshot(store, note="handoff")
    return store


_WRITTEN = {
    "project_state": lambda s: "goal_x" in load_state(s).open_goals,
    "memory": lambda s: any(a.content == "memory_x" for a in load_memory(s).working),
    "collaboration": lambda s: any(c.content == "comment_x" for c in list_comments(s)),
    "theorem_contracts": lambda s: "thm_x" in {c.id for c in list_theorems(s)},
    "obligations": lambda s: "obl_x" in {o.id for o in list_obligations(s)},
    "blockers": lambda s: "blk_x" in {b.id for b in list_blockers(s)},
    "references": lambda s: {"ref_x", "ref_y"} <= {r.id for r in list_references(s)},
    "reference_reviews": lambda s: any(r.reference_id == "ref_y" for r in list_reference_reviews(s)),
    "reusable_assets": lambda s: "asset_x" in {r.asset.id for r in list_reusable_asset_records(s)},
    "domain_packs": lambda s: "pack_x" in {r.pack.id for r in list_domain_pack_records(s)},
    "policies": lambda s: "policy_x" in {r.profile.name for r in list_policy_records(s)},
    "proof_map_nodes": lambda s: _node_ids(s) == {"L", "M", "K"},
    "claims": lambda s: [claim.node_id for claim in list_all_claims(s)] == ["K"],
    "candidate_proofs": lambda s: len(list_candidate_proofs(s, "M")) == 1,
    "dependency_pins": lambda s: len(list_all_dependency_pins(s)) == 1,
    "challenges": lambda s: len(list_challenges(s)) == 1,
    "evidence_checks": lambda s: True,  # none in the source; checked by count below
    "vault_files": lambda s: working_proof_path(s.root, "L").is_file(),
    "publication_workspace": lambda s: any(c.object_id == "thm_x" for c in load_publication_workspace(s).claims),
    "latest_snapshot": lambda s: read_latest_snapshot(s) is not None,
    "handoff_snapshot": lambda s: bool(load_memory(s).handoff_snapshots),
}


def test_every_section_inspect_reports_preserved_is_written_by_import(tmp_path: Path) -> None:
    source = _rich_source(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    inspection = inspect_exchange_bundle(bundle)
    target = ensure_project(tmp_path / "target")

    report = import_exchange_bundle(target, bundle)

    unknown = set(inspection.preserved) - set(_WRITTEN)
    assert not unknown, f"no check for preserved section(s) {unknown}"
    not_written = [section for section in inspection.preserved if not _WRITTEN[section](target)]
    assert not not_written, not_written
    assert set(inspection.preserved) <= set(report.imported_sections)
    assert inspection.section_counts["evidence_checks"] == 0


# -- acceptance 7: legacy trust is reset ---------------------------------------------


def test_an_approved_external_reference_contract_arrives_uncallable_and_without_the_false_notice(tmp_path: Path) -> None:
    foreign = ensure_project(tmp_path / "foreign")
    add_theorem(
        foreign,
        theorem_id="thm_ext",
        kind="lemma",
        name="External",
        statement="E",
        status=TheoremStatus.imported,
        trust_level=TrustLevel.external_reference,
        provenance_kind=TheoremProvenanceKind.imported,
        review_state=TheoremReviewState.approved,
    )
    assert theorem_callability(foreign, "thm_ext")[0] is True
    store_reference(
        foreign,
        ReferenceRecord(
            id="ref_ok",
            title="Std",
            year=2020,
            source_type=ReferenceSourceType.standard_reference,
            review_status=ReferenceReviewStatus.approved,
            trust_level=ReferenceTrustLevel.standard_reference,
            is_callable=True,
        ),
    )
    local = ensure_project(tmp_path / "local")

    report = import_exchange_bundle(local, export_exchange_bundle(foreign))

    assert theorem_callability(local, "thm_ext")[0] is False
    (contract,) = list_theorems(local)
    assert contract.trust_level == TrustLevel.temporary_admit
    assert contract.review_state != TheoremReviewState.approved
    reference = get_reference(local, "ref_ok")
    assert (reference.review_status, reference.trust_level, reference.is_callable) == (
        ReferenceReviewStatus.candidate,
        ReferenceTrustLevel.tentative_source,
        False,
    )
    assert not any("afresh" in warning for warning in report.warnings)


def test_a_bundle_carrying_legacy_notice_keys_imports(tmp_path: Path) -> None:
    foreign = ensure_project(tmp_path / "foreign")
    add_theorem(foreign, theorem_id="thm_n", kind="lemma", name="N", statement="N")
    data = json.loads(bundle_to_json(export_exchange_bundle(foreign)))
    notice = "legacy — not a trust source; what can be called is answered by the proof map"
    data["legacy_notice"] = notice
    data["theorem_contracts"][0]["legacy_notice"] = notice
    local = ensure_project(tmp_path / "local")

    import_exchange_bundle(local, parse_bundle(json.dumps(data)))

    assert [c.id for c in list_theorems(local)] == ["thm_n"]


# -- the project id and the envelope -------------------------------------------------


def test_import_never_rewrites_the_local_project_id(tmp_path: Path) -> None:
    foreign = ensure_project(tmp_path / "foreign", project_id="proj_foreign")
    create_node(foreign, node_id="C", kind="claim", statement="c")
    local = ensure_project(tmp_path / "local", project_id="proj_local")

    report = import_exchange_bundle(local, export_exchange_bundle(foreign))

    assert load_state(local).project_id == "proj_local"
    assert (report.project_id, report.source_project_id) == ("proj_local", "proj_foreign")


def test_parse_bundle_accepts_an_export_envelope_and_names_malformed_input(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    bundle = export_exchange_bundle(store)
    envelope = {"schema_version": 1, "ok": True, "command": "exchange.export", "data": json.loads(bundle_to_json(bundle))}
    assert parse_bundle(json.dumps(envelope)).id == bundle.id
    for text in ["not json", "[]", json.dumps({"project_id": "p"})]:
        with pytest.raises(ProofMapError) as exc_info:
            parse_bundle(text)
        assert exc_info.value.code == "MALFORMED_BUNDLE"


# -- acceptance 8: the CLI, human and --json -----------------------------------------


def test_cli_export_and_import_through_a_file_under_json(tmp_path: Path) -> None:
    _accepted_l_and_m(tmp_path / "source")
    bundle_file = tmp_path / "bundle.json"
    exported = runner.invoke(app, ["exchange", "export", "--root", str(tmp_path / "source"), "--output", str(bundle_file), "--json"])
    assert exported.exit_code == 0, exported.output
    envelope = json.loads(exported.stdout)
    assert (envelope["ok"], envelope["command"]) == (True, "exchange.export")
    assert envelope["data"]["path"] == str(bundle_file)
    assert bundle_file.is_file()

    imported = runner.invoke(app, ["exchange", "import", str(bundle_file), "--root", str(tmp_path / "target"), "--json"])
    assert imported.exit_code == 0, imported.output
    envelope = json.loads(imported.stdout)
    assert (envelope["ok"], envelope["command"]) == (True, "exchange.import")
    assert "proof_map_nodes" in envelope["data"]["imported_sections"]
    assert (tmp_path / "target" / "proofs" / "M" / "proof.tex").is_file()


def test_cli_export_json_without_output_carries_the_bundle(tmp_path: Path) -> None:
    _accepted_l_and_m(tmp_path / "source")
    exported = runner.invoke(app, ["exchange", "export", "--root", str(tmp_path / "source"), "--json"])
    assert exported.exit_code == 0, exported.output
    envelope = json.loads(exported.stdout)
    assert {node["id"] for node in envelope["data"]["proof_map_nodes"]} == {"L", "M"}

    # the envelope itself can be piped back in, through stdin
    imported = runner.invoke(app, ["exchange", "import", "-", "--root", str(tmp_path / "target")], input=exported.stdout)
    assert imported.exit_code == 0, imported.output
    assert "Imported" in imported.stdout and "proof_map_nodes" in imported.stdout


def test_cli_human_export_prints_the_bundle_and_import_reads_stdin(tmp_path: Path) -> None:
    source = ensure_project(tmp_path / "source")
    create_node(source, node_id="K", kind="claim", statement="k")
    claim_node(source, "K", claimant_id="agent_far_away")
    exported = runner.invoke(app, ["exchange", "export", "--root", str(tmp_path / "source")])
    assert exported.exit_code == 0
    assert json.loads(exported.stdout)["proof_map_nodes"][0]["id"] == "K"

    imported = runner.invoke(app, ["exchange", "import", "--root", str(tmp_path / "target")], input=exported.stdout)
    assert imported.exit_code == 0, imported.output
    assert "Released claim" in imported.stdout and "agent_far_away" in imported.stdout


@pytest.mark.parametrize("payload", ["{not json", json.dumps({"id": "b"})])
def test_cli_a_malformed_bundle_under_json_is_one_error_envelope(tmp_path: Path, payload: str) -> None:
    ensure_project(tmp_path)
    result = runner.invoke(app, ["exchange", "import", "-", "--root", str(tmp_path), "--json"], input=payload)
    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert (envelope["ok"], envelope["command"], envelope["error"]["code"]) == (False, "exchange.import", "MALFORMED_BUNDLE")
    assert "Traceback" not in result.output


def test_cli_a_malformed_bundle_without_json_is_a_plain_error(tmp_path: Path) -> None:
    ensure_project(tmp_path)
    result = runner.invoke(app, ["exchange", "import", "-", "--root", str(tmp_path)], input="{not json")
    assert result.exit_code == 1
    assert result.stdout.startswith("Error:") and "Traceback" not in result.output


def test_cli_a_rejected_import_under_json_names_every_problem(tmp_path: Path) -> None:
    source = _accepted_l_and_m(tmp_path / "source")
    bundle = export_exchange_bundle(source)
    bundle.candidate_proofs = [proof.model_copy(update={"file_path": "../../escape"}) for proof in bundle.candidate_proofs]
    bundle_file = tmp_path / "bad.json"
    bundle_file.write_text(bundle_to_json(bundle))

    result = runner.invoke(app, ["exchange", "import", str(bundle_file), "--root", str(tmp_path / "target"), "--json"])

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "INVALID_VAULT_PATH"
    assert len(error["problems"]) == 2


def test_cli_an_unreadable_bundle_file_is_a_stable_error(tmp_path: Path) -> None:
    ensure_project(tmp_path)
    result = runner.invoke(app, ["exchange", "import", str(tmp_path / "nope.json"), "--root", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "BUNDLE_UNREADABLE"


def test_cli_handoff_inspect_human_and_json(tmp_path: Path) -> None:
    _accepted_l_and_m(tmp_path / "source")
    bundle_file = tmp_path / "bundle.json"
    runner.invoke(app, ["exchange", "export", "--root", str(tmp_path / "source"), "--output", str(bundle_file)])

    as_json = runner.invoke(app, ["handoff", "inspect", str(bundle_file), "--json"])
    assert as_json.exit_code == 0, as_json.output
    envelope = json.loads(as_json.stdout)
    assert envelope["command"] == "handoff.inspect"
    assert envelope["data"]["section_counts"]["proof_map_nodes"] == 2

    human = runner.invoke(app, ["handoff", "inspect", str(bundle_file)])
    assert human.exit_code == 0
    assert "preserved" in human.stdout and "proof_map_nodes=2" in human.stdout

    local = runner.invoke(app, ["handoff", "inspect", "--root", str(tmp_path / "source"), "--json"])
    assert json.loads(local.stdout)["data"]["section_counts"]["proof_map_nodes"] == 2

    malformed = runner.invoke(app, ["handoff", "inspect", "-", "--json"], input="nope")
    assert malformed.exit_code == 1
    assert json.loads(malformed.stdout)["error"]["code"] == "MALFORMED_BUNDLE"


# -- Trust rules stay home (ADR-0014) -----------------------------------------------------------


def test_trust_rules_never_travel_in_a_bundle_either_way(tmp_path: Path) -> None:
    """A rule is the researcher's own standing declaration: exported bundles leave it out, and importing one
    into a project with rules leaves those rules exactly as they were."""
    from proof_cli.trust_rules import list_trust_rules

    source = _accepted_l_and_m(tmp_path / "source")
    researcher(source).declare_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="mine")
    bundle = export_exchange_bundle(source)
    assert not any(f.path.endswith("trust-rules.jsonl") for f in bundle.vault_files)
    assert not any(row.get("kind") == "trust_rule" for row in bundle.review_decisions)

    target = ensure_project(tmp_path / "target")
    researcher(target).declare_trust_rule("arxiv", conditions=[{"kind": "identifier_has_arxiv"}], rationale="theirs")
    import_exchange_bundle(target, bundle)

    assert [rule.name for rule in list_trust_rules(target)] == ["arxiv"]
    assert not (tmp_path / "target" / "proofs" / "trust-rules.jsonl").read_text().count("textbooks")


def test_an_imported_citation_that_meets_a_rule_here_is_on_record_from_the_import(tmp_path: Path) -> None:
    from proof_cli.proof_map import get_reference_review_state, trust_rule_events

    source = ensure_project(tmp_path / "source")
    import_reference(source, ReferenceRecord(id="book", title="A Book", authors=["B"], year=2000, source_type=ReferenceSourceType.textbook))
    create_node(source, node_id="ref_book", kind="imported_result", statement="K", source_locator="Thm 1", source_version="v1", reference_id="book")
    target = ensure_project(tmp_path / "target")
    researcher(target).declare_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="mine")

    import_exchange_bundle(target, export_exchange_bundle(source))

    assert get_reference_review_state(target, "ref_book") == "trusted-by-rule"
    assert [(e.entity_id, e.payload["rule"]) for e in trust_rule_events(target)] == [("ref_book", "textbooks")]
