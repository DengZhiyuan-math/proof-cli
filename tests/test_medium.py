"""The Medium of a node (spec #145, decided in #141): what its candidate proof is made of.

`latex` is a standalone LaTeX document, `computation` a program (`run.sh`, its outputs in `out/`)
whose run is meant to establish the statement. Medium is a node attribute, never a kind: it
changes what the studio shows and what a node folder holds, never how the node is claimed,
reviewed or Accepted. These tests drive the service layer and assert only what is observable:
the node as read back, the files in its folder, the error codes, the events.
"""

import os
from pathlib import Path

import pytest

from _proofs import submit_proof, write_key_ideas
from _researcher import researcher
from proof_cli.exchange import bundle_to_json, export_exchange_bundle, import_exchange_bundle, parse_bundle
from proof_cli.fog import add_fog, crystallize_fog
from proof_cli.proof_map import ProofMapError, create_node, get_acceptance_state, get_node, request_review, set_medium
from proof_cli.storage import ensure_project, list_events
from proof_cli.vault import snapshot_folder_files


def _claim(store, node_id="c1", **kwargs):
    return create_node(store, node_id=node_id, kind="claim", statement=f"statement of {node_id}", **kwargs)


def _imported(store, node_id="i1", **kwargs):
    return create_node(store, node_id=node_id, kind="imported_result", statement="known", source_locator="Thm 1", source_version="v1", **kwargs)


# -- creating a node with a medium ----------------------------------------------------------------


def test_a_node_defaults_to_the_latex_medium_with_its_proof_tex(tmp_path: Path):
    store = ensure_project(tmp_path)
    node = _claim(store)
    assert node.medium.value == "latex" and get_node(store, "c1").medium.value == "latex"
    assert (tmp_path / "proofs" / "c1" / "proof.tex").is_file()
    assert not (tmp_path / "proofs" / "c1" / "run.sh").exists()


def test_a_computation_node_gets_a_run_script_and_no_proof_tex(tmp_path: Path):
    store = ensure_project(tmp_path)
    node = _claim(store, medium="computation")
    assert node.medium.value == "computation" and get_node(store, "c1").medium.value == "computation"
    run = tmp_path / "proofs" / "c1" / "run.sh"
    assert run.is_file() and os.access(run, os.X_OK)
    assert "out/" in run.read_text()  # the skeleton says where to write
    assert not (tmp_path / "proofs" / "c1" / "proof.tex").exists()


def test_a_computation_node_gets_a_key_ideas_skeleton_with_hints_for_a_computation(tmp_path: Path):
    store = ensure_project(tmp_path)
    _claim(store, medium="computation")
    text = (tmp_path / "proofs" / "c1" / "key-ideas.md").read_text()
    assert all(heading in text for heading in ("## 核心思路", "## 主要步骤", "## 难点", "## 未覆盖"))  # the four headings, unchanged
    assert "算了什么" in text and "out/" in text  # the hints speak of a computation, not a written proof


def test_an_unknown_medium_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as caught:
        _claim(store, medium="notebook")
    assert caught.value.code == "INVALID_MEDIUM"


def test_a_medium_on_an_imported_result_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    with pytest.raises(ProofMapError) as caught:
        _imported(store, medium="computation")
    assert caught.value.code == "MEDIUM_NOT_APPLICABLE"


def test_an_imported_result_has_no_medium(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert _imported(store).medium is None  # it has no candidate proof


# -- review -----------------------------------------------------------------------------------------


def _computation_ready(store, node_id="c1"):
    """A computation node with a run script, an output and a filled key-ideas summary: ready for review."""
    _claim(store, node_id, medium="computation")
    folder = store.root / "proofs" / node_id
    (folder / "run.sh").write_text("#!/usr/bin/env bash\npython3 check.py > out/table.csv\n")
    (folder / "check.py").write_text("print('n,ratio')\n")
    (folder / "out").mkdir()
    (folder / "out" / "table.csv").write_text("n,ratio\n10000,0.9999\n")
    write_key_ideas(store, node_id)
    return folder


def test_requesting_review_of_a_computation_node_freezes_its_program_and_outputs_and_needs_no_proof_tex(tmp_path: Path):
    store = ensure_project(tmp_path)
    _computation_ready(store)
    proof = request_review(store, "c1", requested_by="agent_a", rationale="the computation covers every case")
    frozen = snapshot_folder_files(tmp_path / "proofs" / "c1" / "snapshots" / f"v{proof.version}")
    assert {"run.sh", "check.py", "out/table.csv", "key-ideas.md"} <= set(frozen)
    assert "proof.tex" not in frozen


def test_a_computation_node_without_its_run_script_cannot_request_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    folder = _computation_ready(store)
    (folder / "run.sh").unlink()
    with pytest.raises(ProofMapError) as caught:
        request_review(store, "c1", requested_by="agent_a", rationale="ready")
    assert caught.value.code == "RUN_SCRIPT_MISSING"


# -- switching ---------------------------------------------------------------------------------------


def _accepted_latex_claim(store):
    _claim(store)
    submit_proof(store, "c1", claimant_id="agent_a", scoping_rationale="scoped", content="\\begin{proof}ok\\end{proof}\n")
    researcher(store).decide_acceptance("c1", "accept", rationale="fine")


def test_switching_medium_keeps_the_files_and_scaffolds_the_missing_entry(tmp_path: Path):
    store = ensure_project(tmp_path)
    _claim(store)
    switched = set_medium(store, "c1", "computation", edited_by="human")
    assert switched.medium.value == "computation" and get_node(store, "c1").medium.value == "computation"
    folder = tmp_path / "proofs" / "c1"
    assert (folder / "proof.tex").is_file() and (folder / "run.sh").is_file()  # nothing removed, the entry added
    assert set_medium(store, "c1", "latex", edited_by="human").medium.value == "latex"


def test_switching_medium_leaves_an_acceptance_standing(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted_latex_claim(store)
    set_medium(store, "c1", "computation", edited_by="human")
    assert get_acceptance_state(store, "c1") == "accepted"  # the medium is not part of the interface


def test_switching_medium_is_recorded_once_and_a_no_op_switch_records_nothing(tmp_path: Path):
    store = ensure_project(tmp_path)
    _claim(store)
    set_medium(store, "c1", "computation", edited_by="human")
    set_medium(store, "c1", "computation", edited_by="human")
    switches = [e for e in list_events(store) if e.kind == "proof_map_node_medium_set" and e.entity_id == "c1"]
    assert len(switches) == 1 and switches[0].payload == {"from": "latex", "to": "computation", "by": "human"}


def test_switching_to_an_unknown_medium_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _claim(store)
    with pytest.raises(ProofMapError) as caught:
        set_medium(store, "c1", "notebook", edited_by="human")
    assert caught.value.code == "INVALID_MEDIUM"


def test_switching_the_medium_of_an_imported_result_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _imported(store)
    with pytest.raises(ProofMapError) as caught:
        set_medium(store, "i1", "computation", edited_by="human")
    assert caught.value.code == "MEDIUM_NOT_APPLICABLE"


# -- crystallize and exchange ----------------------------------------------------------------------


def test_a_fog_item_crystallizes_into_a_computation_node(tmp_path: Path):
    store = ensure_project(tmp_path)
    item = add_fog(store, "n ≤ 10^4 can be checked by machine", created_by="human")
    made = crystallize_fog(store, item.id, "c-check", "For every n ≤ 10^4 the inequality holds", medium="computation", created_by="human")
    assert made.node.medium.value == "computation"
    assert (tmp_path / "proofs" / "c-check" / "run.sh").is_file() and not (tmp_path / "proofs" / "c-check" / "proof.tex").exists()


def test_the_medium_travels_with_an_exchange_bundle(tmp_path: Path):
    source = ensure_project(tmp_path / "source")
    _claim(source, "c-check", medium="computation")
    _claim(source, "c-plain")
    bundle = parse_bundle(bundle_to_json(export_exchange_bundle(source)))
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, bundle)
    assert get_node(target, "c-check").medium.value == "computation"
    assert get_node(target, "c-plain").medium.value == "latex"
