"""Verify, seal and unseal are the researcher's decisions in reviews.jsonl (ADR-0025 points 13-16, #279).

A verification is the researcher's "checked, and I believe it", for the version it read; a Seal is absolute belief,
sealing true everything the node rests on with it. Each is one line in the node's git-tracked reviews.jsonl, naming who,
when, which version and the note, made only on the researcher's click: no CLI command and no agent records one.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.definitions import add_definition, edit_definition
from proof_cli.node_states import node_states, seal_preview
from proof_cli.reviews import ReviewEntry
from proof_cli.proof_map import (
    ProofMapError,
    add_dependency,
    binding_digest,
    create_node,
    fixed_by,
    get_challenge,
    get_current_candidate_proof,
    open_challenge,
    prepare_decision,
    restate_node,
    seal_node,
    work_log,
)
from proof_cli.storage import ensure_project


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def _layers(store, node_id: str) -> tuple:
    states = node_states(store, node_id)
    return states.seal, states.proof_layer, states.conclusion


def _snapshot(store, node_id: str, text: str = "a proof"):
    return submit_proof(store, node_id, claimant_id="agent", scoping_rationale="scoped", content=f"{text} of {node_id}")


def test_a_verification_is_of_the_version_it_read_and_a_new_one_reads_unverified_with_no_action(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="dep", kind="lemma", statement="D")
    create_node(store, node_id="lem", kind="lemma", statement="L", dependencies=["dep"])
    assert _code(lambda: researcher(store).verify("lem")) == "VERIFY_NEEDS_SNAPSHOT"  # a version to verify: request review first
    _snapshot(store, "lem")
    researcher(store).verify("lem", rationale="checked step by step")
    assert _layers(store, "lem") == ("unsealed", "expert-verified", "uncertain")  # verified above an unverified dependency, capped
    assert fixed_by(store, "lem")["kind"] == "verification"  # it relied on the text, which is now fixed
    _snapshot(store, "lem", "a second proof")
    assert _layers(store, "lem")[1] == "incomplete"  # a new version, unverified, with no action


def _lines(root: Path, node_id: str) -> list[str]:
    path = root / "proofs" / node_id / "reviews.jsonl"
    return path.read_text().splitlines() if path.is_file() else []


def test_sealing_true_seals_what_it_rests_on_in_one_line_and_unsealing_releases_the_same(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="C", kind="lemma", statement="C")
    create_node(store, node_id="B", kind="lemma", statement="B", dependencies=["C"])
    create_node(store, node_id="A", kind="lemma", statement="A", dependencies=["B"])
    create_node(store, node_id="X", kind="lemma", statement="X")
    reviewer = researcher(store)
    assert _code(lambda: reviewer.seal("A", True, rationale=" ")) == "SEAL_NOTE_REQUIRED"  # a seal is explained
    reviewer.seal("A", True, rationale="a classical chain I know")
    assert [len(_lines(tmp_path, node_id)) for node_id in ("A", "B", "C")] == [1, 0, 0]  # only the sealed node is recorded
    assert [_layers(store, node_id) for node_id in ("A", "B", "C")] == [("sealed-true", "incomplete", "verified-true")] * 3
    assert _layers(store, "X")[0] == "unsealed"
    assert _code(lambda: reviewer.unseal("B")) == "NOT_SEALED"  # covered by A's seal: unsealing A releases it
    reviewer.unseal("A")
    assert [_layers(store, node_id)[0] for node_id in ("A", "B", "C")] == ["unsealed"] * 3
    reviewer.seal("B", False, rationale="the bound fails for n = 1")
    assert [_layers(store, node_id)[0] for node_id in ("A", "B", "C")] == ["unsealed", "sealed-false", "unsealed"]  # only the node
    assert _layers(store, "A")[2] == "uncertain"  # it needs a proof that does not use B


def test_an_imported_result_is_verified_for_its_statement_and_source(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="imp", kind="imported_result", statement="I", source_locator="Theorem 1", source_version="v1")
    assert _layers(store, "imp")[1:] == ("checks-passed", "true")
    researcher(store).verify("imp", rationale="read the source")
    assert _layers(store, "imp")[1:] == ("expert-verified", "verified-true")


def test_not_a_problem_on_an_agents_challenge_restores_the_verification_it_lapsed(tmp_path: Path):
    # ADR-0025 point 10: the researcher's click withdrawing an agent's Challenge on a verified proof, unchanged since
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    _snapshot(store, "lem")
    reviewer = researcher(store)
    reviewer.verify("lem", rationale="checked")
    gap = open_challenge(store, "lem", opened_by="agent_v", rationale="step 2 skips a case")
    assert _layers(store, "lem")[1] == "incomplete"  # lapsed at once
    reviewer.not_a_problem(gap.id, rationale="step 2 is case (b) of the lemma before")
    withdrawn = get_challenge(store, gap.id)
    assert (withdrawn.status.value, withdrawn.withdrawal_reason) == ("withdrawn", "step 2 is case (b) of the lemma before")
    assert _layers(store, "lem")[1:] == ("expert-verified", "verified-true")
    assert [line for line in _lines(tmp_path, "lem") if '"not_a_problem"' in line]  # a line of its own, in the node's file
    mine = open_challenge(store, "lem", opened_by="human", rationale="my own doubt")
    assert _code(lambda: reviewer.not_a_problem(mine.id)) == "NOTHING_TO_RESTORE"  # the researcher's own lapses nothing
    create_node(store, node_id="open", kind="lemma", statement="O")
    doubt = open_challenge(store, "open", opened_by="agent_v", rationale="a doubt")
    assert _code(lambda: reviewer.not_a_problem(doubt.id)) == "NOTHING_TO_RESTORE"  # nothing verified: withdraw it instead
    later = open_challenge(store, "lem", opened_by="agent_v", rationale="another doubt")
    _snapshot(store, "lem", "a second proof")
    assert _code(lambda: reviewer.not_a_problem(later.id)) == "NOTHING_TO_RESTORE"  # changed since: verify the new version


def test_each_line_round_trips_through_reviews_jsonl_and_the_state_is_read_from_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="B", kind="lemma", statement="B")
    create_node(store, node_id="A", kind="lemma", statement="A", dependencies=["B"])
    _snapshot(store, "A")
    reviewer = researcher(store)
    reviewer.verify("A", rationale="checked")
    gap = open_challenge(store, "A", opened_by="agent_v", rationale="a doubt")
    reviewer.not_a_problem(gap.id, rationale="not a problem")
    reviewer.seal("A", True, rationale="known")
    reviewer.unseal("A", rationale="reopened")
    reviewer.seal("B", False, rationale="fails at n = 1")
    lines = {node_id: [ReviewEntry.model_validate_json(line) for line in _lines(tmp_path, node_id)] for node_id in ("A", "B")}
    assert [(e.kind, e.payload.decision, e.rationale) for e in lines["A"]] == [
        ("verification", "verify", "checked"), ("not_a_problem", "not-a-problem", "not a problem"),
        ("seal", "seal-true", "known"), ("seal", "unseal", "reopened")]
    assert [(e.kind, e.payload.decision, e.rationale) for e in lines["B"]] == [("seal", "seal-false", "fails at n = 1")]
    assert all(e.reviewer == researcher(store).reviewer_id for e in lines["A"] + lines["B"])  # who
    assert lines["A"][0].payload.candidate_proof_id is not None  # which version
    assert node_states(store, "B").seal == "sealed-false"
    (tmp_path / "proofs" / "B" / "reviews.jsonl").write_text("")  # the file is the record: without its line, no seal
    assert node_states(store, "B").seal == "unsealed"


@pytest.mark.parametrize("env", [{}, {"PROOF_AGENT_ROLE": "verifier", "PROOF_AGENT_NAME": "agent_v"}])
def test_no_cli_command_and_no_agent_records_a_verification_or_a_seal(tmp_path: Path, env: dict):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    _snapshot(store, "lem")
    gap = open_challenge(store, "lem", opened_by="agent_v", rationale="a doubt")
    for args in (["node", "verify", "lem"], ["node", "seal", "lem", "true"], ["node", "seal", "lem", "false"], ["node", "unseal", "lem"],
                 ["challenge", "not-a-problem", gap.id]):
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"], env=env)
        assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "HUMAN_REVIEW_REQUIRED", args
    assert _lines(tmp_path, "lem") == [] and _layers(store, "lem") == ("unsealed", "incomplete", "uncertain")


def test_what_a_seal_would_do_is_listed_first_and_its_note_reaches_every_node_it_seals(tmp_path: Path):
    # ADR-0025 point 15: before every seal and unseal the system lists what it does, and never blocks
    store = ensure_project(tmp_path)
    create_node(store, node_id="C", kind="lemma", statement="C")
    create_node(store, node_id="B", kind="lemma", statement="B", dependencies=["C"])
    create_node(store, node_id="A", kind="lemma", statement="A", dependencies=["B"])
    _snapshot(store, "B")
    researcher(store).verify("B", rationale="checked")
    open_challenge(store, "C", kind="statement", opened_by="human", rationale="I doubt C")
    assert seal_preview(store, "A", "seal-true") == {"covers": ["A", "B", "C"], "unverified": ["A", "C"], "challenged": ["C"]}
    assert seal_preview(store, "B", "seal-false") == {"direct_users": ["A"], "verified": []}
    researcher(store).seal("A", True, rationale="a chain I know")
    assert seal_preview(store, "A", "unseal") == {"releases": ["A", "B", "C"]}

    def shown(node_id: str) -> dict:
        result = CliRunner().invoke(app, ["node", "show", node_id, "--root", str(tmp_path), "--json"])
        return json.loads(result.output)["data"]["seal_record"]

    covered = shown("C")
    assert (covered["seal"], covered["sealed_node"], covered["note"], covered["by"]) == ("sealed-true", "A", "a chain I know", researcher(store).reviewer_id)
    assert shown("A")["sealed_node"] == "A"
    (entry,) = [e for e in work_log(store, "A") if e["kind"] == "sealed"]  # the work log reads it from reviews.jsonl
    assert (entry["decision"], entry["note"]) == ("seal-true", "a chain I know")
    assert [e["kind"] for e in work_log(store, "B") if e["kind"] == "verified"] == ["verified"]


# -- review of #293 ------------------------------------------------------------------------------------------------------


def test_a_dependency_found_false_voids_the_verification_for_good(tmp_path: Path):
    # ADR-0025 point 13: if a dependency is later false, the verification is void; unsealing it restores nothing
    store = ensure_project(tmp_path)
    create_node(store, node_id="B", kind="imported_result", statement="B", source_locator="Theorem 1", source_version="v1")
    create_node(store, node_id="A", kind="lemma", statement="A", dependencies=["B"])
    reviewer = researcher(store)
    reviewer.verify("B", rationale="read the source")
    _snapshot(store, "A")
    reviewer.verify("A", rationale="checked")
    assert _layers(store, "A")[1:] == ("expert-verified", "verified-true")
    reviewer.seal("B", False, rationale="the source has an error")
    reviewer.unseal("B", rationale="a misreading after all")
    assert _layers(store, "B")[2] == "verified-true" and _layers(store, "A")[1:] == ("incomplete", "uncertain")
    reviewer.verify("A", rationale="checked again")
    assert _layers(store, "A")[1:] == ("expert-verified", "verified-true")


def test_a_true_seal_fixes_the_text_of_all_it_covers_and_a_false_one_only_its_own(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id, dependencies in (("C", []), ("B", ["C"]), ("A", ["B"]), ("N", []), ("M", ["N"])):
        create_node(store, node_id=node_id, kind="lemma", statement=node_id, dependencies=dependencies)
    reviewer = researcher(store)
    reviewer.seal("A", True, rationale="known")
    assert all(fixed_by(store, node_id) is not None for node_id in ("A", "B", "C"))
    assert _code(lambda: restate_node(store, "C", statement="C'", reason="a typo", by="human")) == "TEXT_FIXED"
    reviewer.seal("M", False, rationale="false")
    assert fixed_by(store, "M") is not None and fixed_by(store, "N") is None  # sealing M false says nothing of N's text


def test_a_preview_binds_the_whole_set_a_true_seal_covers(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id, dependencies in (("C", []), ("B", ["C"]), ("A", ["B"]), ("X", [])):
        create_node(store, node_id=node_id, kind="lemma", statement=node_id, dependencies=dependencies)
    viewed = binding_digest(prepare_decision(store, "seal", "A", "seal-true"))
    add_dependency(store, "B", "X", edited_by="human")  # the set changed after the page showed it
    with pytest.raises(ProofMapError) as caught:
        seal_node(store, "A", True, reviewer=researcher(store).reviewer_id, rationale="known", viewed_binding=viewed)
    assert caught.value.code == "STALE_VIEW" and _layers(store, "X")[0] == "unsealed"
    researcher(store).seal("A", True, rationale="known, X included")
    create_node(store, node_id="Y", kind="lemma", statement="Y")
    add_dependency(store, "C", "Y", edited_by="human")  # an edge under a sealed node, after the seal
    assert _layers(store, "X")[0] == "sealed-true" and _layers(store, "Y")[0] == "unsealed"  # a seal covers what it was shown


def test_unsealing_needs_no_readable_snapshot(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="L")
    _snapshot(store, "L")
    researcher(store).seal("L", True, rationale="known")
    snapshot = tmp_path / get_current_candidate_proof(store, "L").file_path
    snapshot.unlink()  # the manifest gone: the proof's bytes can't be read
    researcher(store).unseal("L", rationale="reopened")
    assert _layers(store, "L")[0] == "unsealed"


def test_not_a_problem_restores_something_or_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    _snapshot(store, "lem")
    reviewer = researcher(store)
    reviewer.verify("lem", rationale="checked")
    gap = open_challenge(store, "lem", opened_by="agent_v", rationale="a doubt")
    reviewer.not_a_problem(gap.id)
    assert _code(lambda: reviewer.not_a_problem(gap.id)) == "NOTHING_TO_RESTORE"  # once is enough
    create_node(store, node_id="old", kind="lemma", statement="O")
    _snapshot(store, "old")
    reviewer.decide_acceptance("old", "accept")  # a legacy Acceptance of v1
    doubt = open_challenge(store, "old", opened_by="agent_v", rationale="a doubt")
    _snapshot(store, "old", "a second proof")
    assert _code(lambda: reviewer.not_a_problem(doubt.id)) == "NOTHING_TO_RESTORE"  # v2 is verified by nobody


def test_an_unseal_preview_releases_only_what_no_other_seal_still_covers(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id, dependencies in (("N", []), ("A", ["N"]), ("B", ["N"])):
        create_node(store, node_id=node_id, kind="lemma", statement=node_id, dependencies=dependencies)
    researcher(store).seal("A", True, rationale="known")
    researcher(store).seal("B", True, rationale="known too")
    assert seal_preview(store, "A", "unseal") == {"releases": ["A"]}
    researcher(store).unseal("A", rationale="reopened")
    assert [_layers(store, node_id)[0] for node_id in ("A", "N")] == ["unsealed", "sealed-true"]


def test_a_preview_binds_the_statements_of_what_a_true_seal_covers(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id, dependencies in (("C", []), ("B", ["C"]), ("A", ["B"])):
        create_node(store, node_id=node_id, kind="lemma", statement=node_id, dependencies=dependencies)
    viewed = binding_digest(prepare_decision(store, "seal", "A", "seal-true"))
    restate_node(store, "C", statement="C, restated", reason="a sharper bound", by="human")  # what the page showed changed
    with pytest.raises(ProofMapError) as caught:
        seal_node(store, "A", True, reviewer=researcher(store).reviewer_id, rationale="known", viewed_binding=viewed)
    assert caught.value.code == "STALE_VIEW" and _layers(store, "C")[0] == "unsealed"


def test_an_unseal_preview_keeps_what_stays_sealed_false_by_an_older_review(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="imported_result", statement="N", source_locator="Theorem 1", source_version="v1")
    create_node(store, node_id="A", kind="lemma", statement="A", dependencies=["N"])
    researcher(store).decide_reference_review("N", "no-longer-callable")  # sealed false by a review from before seal lines
    researcher(store).seal("A", True, rationale="known")
    assert seal_preview(store, "A", "unseal") == {"releases": ["A"]}
    researcher(store).unseal("A", rationale="reopened")
    assert _layers(store, "N")[0] == "sealed-false"


@pytest.mark.parametrize("named_by", ["C", "A"])  # a covered node's Definition, and the sealed node's own
def test_a_preview_binds_the_text_of_the_definitions_what_it_seals_names(tmp_path: Path, named_by: str):
    store = ensure_project(tmp_path)
    add_definition(store, "D", term="Setting", text="X is compact.")
    for node_id, dependencies in (("C", []), ("B", ["C"]), ("A", ["B"])):
        create_node(store, node_id=node_id, kind="lemma", statement=node_id, dependencies=dependencies,
                    definitions=["D"] if node_id == named_by else [])
    viewed = binding_digest(prepare_decision(store, "seal", "A", "seal-true"))
    edit_definition(store, "D", text="X is compact and connected.", reason="a condition added", edited_by="human")
    with pytest.raises(ProofMapError) as caught:
        seal_node(store, "A", True, reviewer=researcher(store).reviewer_id, rationale="known", viewed_binding=viewed)
    assert caught.value.code == "STALE_VIEW"


def test_a_verification_preview_binds_the_text_of_its_definitions(tmp_path: Path):
    store = ensure_project(tmp_path)
    add_definition(store, "D", term="Setting", text="X is compact.")
    create_node(store, node_id="L", kind="lemma", statement="L", definitions=["D"])
    _snapshot(store, "L")
    viewed = binding_digest(prepare_decision(store, "verification", "L", "verify"))
    edit_definition(store, "D", text="X is compact and connected.", reason="a condition added", edited_by="human")
    from proof_cli.proof_map import verify_node
    with pytest.raises(ProofMapError) as caught:
        verify_node(store, "L", reviewer=researcher(store).reviewer_id, rationale="checked", viewed_binding=viewed)
    assert caught.value.code == "STALE_VIEW"


def test_unsealing_a_node_an_older_review_found_false_releases_nothing(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="N", kind="imported_result", statement="N", source_locator="Theorem 1", source_version="v1")
    researcher(store).decide_reference_review("N", "no-longer-callable")
    researcher(store).seal("N", True, rationale="the source is right after all")
    assert _layers(store, "N")[0] == "sealed-true"
    assert seal_preview(store, "N", "unseal") == {"releases": []}  # it falls back to sealed false
    researcher(store).unseal("N", rationale="reopened")
    assert _layers(store, "N")[0] == "sealed-false"
