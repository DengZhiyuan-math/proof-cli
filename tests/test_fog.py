"""Proof fog (ADR-0008, spec #136): a flat list of difficulties not yet precise enough to be a Claim,
kept outside the proof map, with Experiments recorded against an item and Crystallize turning one
into a Claim. The service layer is the seam: these tests call it the way the CLI and the page do,
and assert only what is observable — the item read back, a node's state, the event log, error codes."""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.analysis import build_project_diagnostic_report
from proof_cli.fog import (
    add_fog,
    crystallize_fog,
    crystallized_from,
    drop_fog,
    edit_fog,
    fog_folder,
    fog_near,
    require_fog,
    list_experiments,
    list_fog,
    record_experiment,
    reopen_fog,
)
from proof_cli.proof_map import (
    ProofMapError,
    claim_node,
    create_node,
    get_acceptance_state,
    get_frontier,
    get_integrity_state,
    get_node,
    get_workflow_state,
)
from proof_cli.proof_state import record_failed_route
from proof_cli.storage import ensure_project, list_events


def _project(root: Path):
    store = ensure_project(root)
    create_node(store, node_id="L1", kind="lemma", statement="a lemma")
    create_node(store, node_id="C1", kind="claim", statement="a claim", dependencies=["L1"])
    create_node(store, node_id="I", kind="imported_result", statement="known", source_locator="Thm 1", source_version="v1")
    return store


def _axes(store, node_id):
    return (get_workflow_state(store, node_id), get_acceptance_state(store, node_id), get_integrity_state(store, node_id), [n.id for n in get_frontier(store)])


def _events(store, kind):
    return [event for event in list_events(store) if event.kind == kind]


# -- adding, editing, dropping, reopening -------------------------------------------------------------


def test_a_fog_item_is_added_with_its_text_notes_and_near_nodes_and_an_incrementing_id(tmp_path: Path):
    store = _project(tmp_path)

    first = add_fog(store, "the constant C is probably optimal, but 'optimal' is not yet a statement", near=["L1"], notes="try n ≤ 10^6 first", created_by="agent_a")
    second = add_fog(store, "maybe the whole thing has a variational characterisation")

    assert (first.id, first.status.value, first.near, first.notes, first.created_by) == ("fog-1", "open", ["L1"], "try n ≤ 10^6 first", "agent_a")
    assert (second.id, second.near, second.created_by) == ("fog-2", [], "human")
    assert [item.id for item in list_fog(store)] == ["fog-1", "fog-2"]
    assert require_fog(store, "fog-1").text == first.text
    assert [event.entity_id for event in _events(store, "proof_fog_added")] == ["fog-1", "fog-2"]


def test_ids_are_never_reused(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "one")
    drop_fog(store, "fog-1", reason="no", dropped_by="human")
    add_fog(store, "two")
    assert [item.id for item in list_fog(store, include_all=True)] == ["fog-1", "fog-2"]


@pytest.mark.parametrize("call, code", [
    (lambda s: add_fog(s, "   "), "FOG_TEXT_REQUIRED"),
    (lambda s: add_fog(s, "near nothing", near=["nope"]), "NODE_NOT_FOUND"),
    (lambda s: drop_fog(s, "fog-1", reason="   "), "FOG_REASON_REQUIRED"),
    (lambda s: drop_fog(s, "fog-9", reason="why"), "FOG_NOT_FOUND"),
    (lambda s: edit_fog(s, "fog-9", text="x"), "FOG_NOT_FOUND"),
])
def test_a_fog_operation_that_cannot_be_recorded_is_refused_with_its_code(tmp_path: Path, call, code):
    store = _project(tmp_path)
    add_fog(store, "one", near=["L1"])
    with pytest.raises(ProofMapError) as refused:
        call(store)
    assert refused.value.code == code
    assert [item.id for item in list_fog(store, include_all=True)] == ["fog-1"]  # nothing else landed


def test_near_may_point_at_any_kind_and_at_a_rejected_node_and_changes_no_axis(tmp_path: Path):
    store = _project(tmp_path)
    create_node(store, node_id="R", kind="claim", statement="an abandoned route")
    submit_proof(store, "R", claimant_id="agent_a", scoping_rationale="scoped", content="\\begin{proof}no.\\end{proof}\n")
    researcher(store).decide_acceptance("R", "reject", rationale="wrong")
    before = {node_id: _axes(store, node_id) for node_id in ("L1", "C1", "I", "R")}

    item = add_fog(store, "about several nodes", near=["L1", "I", "R"])

    assert item.near == ["L1", "I", "R"]
    assert {node_id: _axes(store, node_id) for node_id in ("L1", "C1", "I", "R")} == before  # each axis, and the frontier
    assert [n.id for n in get_frontier(store)] == ["L1"]
    assert get_node(store, "L1").dependencies == [] and "fog-1" not in get_node(store, "C1").dependencies


def test_editing_changes_text_notes_and_near_but_never_the_id(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "rough", near=["L1"])

    edited = edit_fog(store, "fog-1", text="sharper", near=["C1", "I"], notes="see the experiment", edited_by="agent_a")

    assert (edited.id, edited.text, edited.near, edited.notes) == ("fog-1", "sharper", ["C1", "I"], "see the experiment")
    assert edit_fog(store, "fog-1", near=[]).near == []  # near can be cleared
    assert require_fog(store, "fog-1").text == "sharper"  # a partial edit leaves the rest
    assert [e.payload["fields"] for e in _events(store, "proof_fog_edited")] == [["near", "notes", "text"], ["near"]]


def test_dropping_records_who_why_and_when_and_reopening_clears_it(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "generating functions by brute force")

    dropped = drop_fog(store, "fog-1", reason="the coefficients grow too fast to estimate", dropped_by="human")
    assert (dropped.status.value, dropped.dropped_by, dropped.reason) == ("dropped", "human", "the coefficients grow too fast to estimate")
    assert dropped.dropped_at is not None
    assert [item.id for item in list_fog(store)] == [] and [item.id for item in list_fog(store, include_all=True)] == ["fog-1"]
    with pytest.raises(ProofMapError) as refused:
        edit_fog(store, "fog-1", text="x")
    assert refused.value.code == "FOG_NOT_OPEN" and "reopen" in refused.value.message

    reopened = reopen_fog(store, "fog-1", by="agent_a")
    assert (reopened.status.value, reopened.dropped_by, reopened.dropped_at, reopened.reason) == ("open", None, None, None)
    assert [item.id for item in list_fog(store)] == ["fog-1"]
    assert reopen_fog(store, "fog-1").status.value == "open"  # reopening an open item changes nothing
    assert [e.entity_id for e in _events(store, "proof_fog_dropped")] == ["fog-1"] and [e.entity_id for e in _events(store, "proof_fog_reopened")] == ["fog-1"]


# -- Experiments ----------------------------------------------------------------------------------------


def test_an_experiment_is_recorded_against_an_open_item_and_never_changes_its_status(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "the constant is optimal", near=["L1"])
    script = store.root / "proofs" / "L1" / "scratch" / "constant.py"
    script.parent.mkdir(parents=True)
    script.write_text("print(1)\n")

    first = record_experiment(store, "fog-1", "supports", summary="checked n ≤ 10^6; the ratio tends to 1", run_by="agent_a", path="proofs/L1/scratch/constant.py")
    second = record_experiment(store, "fog-1", "refutes", summary="the p-adic case breaks", run_by="human")

    assert (first.seq, first.outcome.value, first.path) == (1, "supports", "proofs/L1/scratch/constant.py")
    assert (second.seq, second.outcome.value, second.path) == (2, "refutes", None)
    assert [e.seq for e in list_experiments(store, "fog-1")] == [1, 2]
    assert require_fog(store, "fog-1").status.value == "open"  # a refutes drops nothing; a supports crystallizes nothing
    assert [e.entity_id for e in _events(store, "proof_fog_experiment_recorded")] == ["fog-1", "fog-1"]


@pytest.mark.parametrize("kwargs, code", [
    ({"outcome": "supports", "summary": "s", "run_by": "  "}, "FOG_RUN_BY_REQUIRED"),
    ({"outcome": "supports", "summary": "  ", "run_by": "a"}, "FOG_SUMMARY_REQUIRED"),
    ({"outcome": "supports", "summary": "s", "run_by": "a", "path": "proofs"}, "FOG_EXPERIMENT_PATH_INVALID"),
    ({"outcome": "maybe", "summary": "s", "run_by": "a"}, "INVALID_OUTCOME"),
    ({"outcome": "supports", "summary": "s", "run_by": "a", "path": "proofs/L1/scratch/missing.py"}, "FOG_EXPERIMENT_PATH_INVALID"),
    ({"outcome": "supports", "summary": "s", "run_by": "a", "path": "../outside.py"}, "FOG_EXPERIMENT_PATH_INVALID"),
    ({"outcome": "supports", "summary": "s", "run_by": "a", "path": "README.md"}, "FOG_EXPERIMENT_PATH_INVALID"),
])
def test_an_experiment_that_cannot_be_recorded_is_refused(tmp_path: Path, kwargs, code):
    store = _project(tmp_path)
    add_fog(store, "one")
    (store.root / "README.md").write_text("not under proofs/")
    with pytest.raises(ProofMapError) as refused:
        record_experiment(store, "fog-1", kwargs.pop("outcome"), **kwargs)
    assert refused.value.code == code
    assert list_experiments(store, "fog-1") == []


def test_an_experiment_on_a_dropped_or_crystallized_item_is_refused(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "dropped one")
    drop_fog(store, "fog-1", reason="no")
    with pytest.raises(ProofMapError) as dropped:
        record_experiment(store, "fog-1", "supports", summary="s", run_by="a")
    assert dropped.value.code == "FOG_NOT_OPEN" and "reopen" in dropped.value.message
    add_fog(store, "stated one")
    crystallize_fog(store, "fog-2", "C2", "a precise statement", no_parent=True)
    with pytest.raises(ProofMapError) as crystallized:
        record_experiment(store, "fog-2", "supports", summary="s", run_by="a")
    assert crystallized.value.code == "FOG_NOT_OPEN" and "C2" in crystallized.value.message


def test_a_missing_experiment_file_is_marked_not_refused(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "one")
    folder = fog_folder(store.root, "fog-1")
    assert not folder.exists()  # reserved, created only when something is put there
    folder.mkdir(parents=True)
    (folder / "run.sage").write_text("1+1\n")
    record_experiment(store, "fog-1", "inconclusive", summary="ran out of memory", run_by="agent_a", path="proofs/fog/fog-1/run.sage")

    (folder / "run.sage").unlink()

    (experiment,) = list_experiments(store, "fog-1")
    assert experiment.path == "proofs/fog/fog-1/run.sage" and experiment.missing


# -- Crystallize --------------------------------------------------------------------------------------


def test_crystallize_creates_a_claim_under_the_single_near_node_as_a_split_would(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "the second half might follow from compactness", near=["L1"], notes="keep")
    record_experiment(store, "fog-1", "supports", summary="small cases work", run_by="agent_a")

    made = crystallize_fog(store, "fog-1", "C_new", "If X is compact then the second half holds", assumptions=["X compact"], created_by="agent_a")

    node = get_node(store, "C_new")
    assert node.kind.value == "claim" and node.statement == "If X is compact then the second half holds" and node.assumptions == ["X compact"]
    assert node.derived_from == "L1" and get_node(store, "L1").dependencies == ["C_new"]
    assert made.node.id == "C_new" and made.fog.status.value == "crystallized" and made.fog.node_id == "C_new"
    assert (made.fog.text, made.fog.notes, made.fog.near) == ("the second half might follow from compactness", "keep", ["L1"])
    assert [item.id for item in list_fog(store)] == [] and require_fog(store, "fog-1").status.value == "crystallized"
    assert [e.seq for e in list_experiments(store, "fog-1")] == [1]  # the experiments stay on the item
    assert crystallized_from(store, "C_new").id == "fog-1" and crystallized_from(store, "L1") is None
    (event,) = _events(store, "proof_fog_crystallized")
    assert event.entity_id == "fog-1" and event.payload["node_id"] == "C_new"
    assert get_workflow_state(store, "C_new") == "open"  # an ordinary new Claim, nothing more


def test_crystallize_resolves_the_parent_from_near_or_the_flags(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "near nothing")
    add_fog(store, "near two", near=["L1", "C1"])
    add_fog(store, "near one, kept free", near=["L1"])

    free = crystallize_fog(store, "fog-1", "F1", "free-standing")
    assert free.node.derived_from is None and free.node.dependencies == []
    with pytest.raises(ProofMapError) as ambiguous:
        crystallize_fog(store, "fog-2", "F2", "which parent?")
    assert ambiguous.value.code == "FOG_PARENT_AMBIGUOUS" and ambiguous.value.details["candidates"] == ["L1", "C1"]
    assert get_node(store, "F2") is None and require_fog(store, "fog-2").status.value == "open"
    chosen = crystallize_fog(store, "fog-2", "F2", "under C1", parent="C1")
    assert chosen.node.derived_from == "C1" and "F2" in get_node(store, "C1").dependencies
    detached = crystallize_fog(store, "fog-3", "F3", "deliberately free", no_parent=True)
    assert detached.node.derived_from is None and get_node(store, "L1").dependencies == []


def test_crystallize_keeps_every_split_rule_for_the_parent(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "under an imported result", near=["I"])
    with pytest.raises(ProofMapError) as imported:
        crystallize_fog(store, "fog-1", "X1", "s")
    assert imported.value.code == "IMMUTABLE_NODE"

    create_node(store, node_id="R", kind="claim", statement="route")
    submit_proof(store, "R", claimant_id="agent_a", scoping_rationale="scoped", content="\\begin{proof}no.\\end{proof}\n")
    researcher(store).decide_acceptance("R", "reject", rationale="wrong")
    add_fog(store, "under a rejected node", near=["R"])
    with pytest.raises(ProofMapError) as rejected:
        crystallize_fog(store, "fog-2", "X2", "s")
    assert rejected.value.code == "NODE_REJECTED"

    submit_proof(store, "L1", claimant_id="agent_a", scoping_rationale="scoped", content="\\begin{proof}ok.\\end{proof}\n")
    researcher(store).decide_acceptance("L1", "accept", rationale="fine")
    add_fog(store, "under an accepted node", near=["L1"])
    with pytest.raises(ProofMapError) as accepted:
        crystallize_fog(store, "fog-3", "X3", "s")
    assert accepted.value.code == "NODE_ACCEPTED" and get_acceptance_state(store, "L1") == "accepted"

    claim_node(store, "C1", claimant_id="agent_b", session_id="s")
    add_fog(store, "under someone else's node", near=["C1"])
    with pytest.raises(ProofMapError) as held:
        crystallize_fog(store, "fog-4", "X4", "s", created_by="agent_a")
    assert held.value.code == "NOT_CLAIMANT"
    taken = crystallize_fog(store, "fog-4", "X4", "s", created_by="agent_a", reassign=True)
    assert taken.node.derived_from == "C1"

    # every refusal left no node, no folder and the item open
    assert all(get_node(store, node_id) is None for node_id in ("X1", "X2", "X3"))
    assert all(not (store.root / "proofs" / node_id).exists() for node_id in ("X1", "X2", "X3"))
    assert [item.id for item in list_fog(store)] == ["fog-1", "fog-2", "fog-3"]


def test_crystallize_needs_an_open_item_and_a_free_node_id(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "dropped")
    drop_fog(store, "fog-1", reason="no")
    with pytest.raises(ProofMapError) as dropped:
        crystallize_fog(store, "fog-1", "X", "s", no_parent=True)
    assert dropped.value.code == "FOG_NOT_OPEN" and "reopen" in dropped.value.message
    add_fog(store, "twice")
    crystallize_fog(store, "fog-2", "Y", "s", no_parent=True)
    with pytest.raises(ProofMapError) as again:
        crystallize_fog(store, "fog-2", "Z", "s", no_parent=True)
    assert again.value.code == "FOG_NOT_OPEN" and "Y" in again.value.message
    with pytest.raises(ProofMapError) as no_reopen:
        reopen_fog(store, "fog-2")
    assert no_reopen.value.code == "FOG_NOT_OPEN"
    add_fog(store, "taken id")
    with pytest.raises(ProofMapError) as taken:
        crystallize_fog(store, "fog-3", "L1", "s", no_parent=True)
    assert taken.value.code == "NODE_ALREADY_EXISTS" and require_fog(store, "fog-3").status.value == "open"


def test_crystallize_notes_experiment_files_left_in_an_agents_scratch_folder(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "one", near=["L1"])
    script = store.root / "proofs" / "L1" / "scratch" / "run.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    record_experiment(store, "fog-1", "supports", summary="s", run_by="agent_a", path="proofs/L1/scratch/run.py")

    made = crystallize_fog(store, "fog-1", "C_new", "stated")

    assert "proofs/L1/scratch/" in made.reminder and "commit" in made.reminder
    assert script.exists()  # nothing moved


def test_a_crystallize_that_fails_after_the_node_is_made_leaves_no_node_folder_and_the_item_open(tmp_path: Path, monkeypatch):
    """The free-standing path writes proof.tex before the transaction commits: a failure afterwards takes the folder with the node."""
    import proof_cli.fog as fog_module

    store = _project(tmp_path)
    add_fog(store, "free-standing")
    real_append = fog_module.append_event

    def failing(store_, kind, *args, **kwargs):
        if kind == "proof_fog_crystallized":
            raise RuntimeError("the event log is full")
        return real_append(store_, kind, *args, **kwargs)

    monkeypatch.setattr(fog_module, "append_event", failing)
    with pytest.raises(RuntimeError):
        crystallize_fog(store, "fog-1", "C_free", "stated", no_parent=True)

    assert get_node(store, "C_free") is None and not (store.root / "proofs" / "C_free").exists()
    assert require_fog(store, "fog-1").status.value == "open"


def test_fog_is_not_a_node_id(tmp_path: Path):
    """`proofs/fog/` holds the fog items' folders: no node may take its place, in any letter case."""
    store = _project(tmp_path)
    for node_id in ("fog", "FOG"):
        with pytest.raises(ProofMapError) as refused:
            create_node(store, node_id=node_id, kind="claim", statement="squatting")
        assert refused.value.code == "INVALID_NODE_ID"
    add_fog(store, "one")
    with pytest.raises(ProofMapError) as crystallized:
        crystallize_fog(store, "fog-1", "Fog", "s", no_parent=True)
    assert crystallized.value.code == "INVALID_NODE_ID" and require_fog(store, "fog-1").status.value == "open"
    assert not (store.root / "proofs" / "fog").exists()


# -- what the map reads back -----------------------------------------------------------------------------


def test_the_fog_near_a_node_is_the_open_items_that_name_it(tmp_path: Path):
    store = _project(tmp_path)
    add_fog(store, "a", near=["L1"])
    add_fog(store, "b", near=["L1", "C1"])
    add_fog(store, "c", near=["L1"])
    drop_fog(store, "fog-3", reason="no")
    assert [item.id for item in fog_near(store, "L1")] == ["fog-1", "fog-2"]
    assert [item.id for item in fog_near(store, "C1")] == ["fog-2"] and fog_near(store, "I") == []


# -- analyze reads fog, failed_routes is legacy --------------------------------------------------------------


def test_analyze_takes_its_route_bottleneck_from_the_last_dropped_fog_and_falls_back_to_legacy_routes(tmp_path: Path):
    store = _project(tmp_path)
    record_failed_route(store, "the old literature route")  # a legacy writer, kept as is
    legacy = build_project_diagnostic_report(store)
    assert (legacy.bottleneck_kind, legacy.bottleneck_source) == ("route", "legacy") and "old literature route" in legacy.bottleneck_summary

    add_fog(store, "generating functions by brute force")
    add_fog(store, "still open")
    drop_fog(store, "fog-1", reason="the coefficients grow too fast")
    report = build_project_diagnostic_report(store)

    assert (report.bottleneck_kind, report.bottleneck_source) == ("route", "fog")
    assert "fog-1" in report.bottleneck_summary and "coefficients grow too fast" in report.bottleneck_summary
    assert "still open" not in report.bottleneck_summary  # open fog is the page's business, not analysis
    assert report.failed_routes == ["the old literature route"]  # the legacy field is still reported
