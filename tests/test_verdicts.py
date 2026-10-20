"""A Verdict has an id and numbered objections, and each objection's ending is recorded (ADR-0025 points 8–9, #278).

A Verifier's objection is a proof Challenge, numbered within its Verdict. It ends fixed (a passing Verdict says where and
why), withdrawn (with a reason) or superseded by a restatement; a passing Verdict that leaves one out is refused, so no
objection is silently dropped. An audit records no endings. What checked a proof is a structured mark, never notes.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from proof_cli.cli import app
from proof_cli.node_states import node_states
from _researcher import researcher
from proof_cli.proof_map import ProofMapError, create_node, get_challenge, list_challenges, open_challenge, record_evidence_check, record_progress, withdraw_challenge, work_log
from proof_cli.storage import append_event, ensure_project
from proof_cli.vault import working_proof_path


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def _verdict(store, node_id: str, outcome: str, **given) -> dict:
    return record_progress(store, node_id, role="verifier", by="agent_v", verdict=outcome, **given)


def test_a_failed_verdict_has_an_id_and_its_objections_are_numbered_proof_challenges(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    verdict = _verdict(store, "lem", "failed", note="two gaps", objections=["step 2: the bound needs n >= 1", "line 5 cites the wrong lemma"])
    assert verdict["id"].startswith("v_") and verdict["checker"] == "verifier" and verdict["inputs_sha256"]
    first, second = list_challenges(store, target_node_id="lem")
    assert [(c.kind, c.opened_by, c.verdict_id, c.objection, c.rationale) for c in (first, second)] == [
        ("proof", "agent_v", verdict["id"], 1, "step 2: the bound needs n >= 1"),
        ("proof", "agent_v", verdict["id"], 2, "line 5 cites the wrong lemma")]
    assert [(o["n"], o["challenge_id"]) for o in verdict["objections"]] == [(1, first.id), (2, second.id)]
    assert node_states(store, "lem").proof_layer == "incomplete"
    assert _code(lambda: _verdict(store, "lem", "failed", note="it looks wrong")) == "OBJECTIONS_REQUIRED"  # structured, not a note


def test_a_passing_verdict_ends_each_open_objection_or_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    failed = _verdict(store, "lem", "failed", objections=["step 2: the bound needs n >= 1", "line 5 cites the wrong lemma", "the constant"])
    one, two, three = (objection["challenge_id"] for objection in failed["objections"])
    withdraw_challenge(store, three, by="agent_p", reason="the constant is never used")  # withdrawn: no ending needed
    doubt = open_challenge(store, "lem", opened_by="agent_p", rationale="the case n = 0").id  # any open proof Challenge
    with pytest.raises(ProofMapError) as caught:
        _verdict(store, "lem", "passed", fixed={one: "step 2 now assumes n >= 1 (line 3)"})
    assert caught.value.code == "ENDINGS_REQUIRED" and caught.value.details["missing"] == sorted([two, doubt])
    assert _code(lambda: _verdict(store, "lem", "passed", fixed={one: "x", two: "y", doubt: "z", "nope": "w"})) == "INVALID_ENDING"
    assert _code(lambda: _verdict(store, "lem", "passed", fixed={one: " ", two: "y", doubt: "z"})) == "INVALID_ENDING"  # where and why
    passed = _verdict(store, "lem", "passed", fixed={one: "step 2 now assumes n >= 1 (line 3)", two: "line 5 now cites the right lemma",
                                                    doubt: "n = 0 is the base case, line 1"})
    fixed = get_challenge(store, one)
    assert (fixed.status.value, fixed.fixed_by, fixed.fix) == ("fixed", passed["id"], "step 2 now assumes n >= 1 (line 3)")
    assert [ending["challenge_id"] for ending in passed["fixed"]] == [one, two, doubt]
    assert get_challenge(store, three).status.value == "withdrawn"


def _proof_layer(store, node_id: str) -> tuple[str, str]:
    states = node_states(store, node_id)
    return states.proof_layer, states.conclusion


def test_checks_passed_is_read_only_off_a_structured_passing_verdict_on_the_inputs_as_they_stand(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    passed = _verdict(store, "lem", "passed")
    assert _proof_layer(store, "lem") == ("checks-passed", "true")
    working_proof_path(tmp_path, "lem").write_text(working_proof_path(tmp_path, "lem").read_text() + "\n% an edit\n")
    assert _proof_layer(store, "lem") == ("incomplete", "uncertain")  # the verdict read other inputs
    _verdict(store, "lem", "passed")
    assert _proof_layer(store, "lem") == ("checks-passed", "true")
    create_node(store, node_id="old", kind="lemma", statement="O")
    structured = _verdict(store, "old", "passed")
    assert _proof_layer(store, "old")[0] == "checks-passed"
    # newer, on the same inputs, as a verdict was recorded before #278: no id, so no check under the new rules (point 26)
    legacy = {key: structured[key] for key in ("kind", "role", "by", "outcome", "note", "inputs_sha256")}
    append_event(store, "agent_progress", "verifier on old: verdict passed", entity_id="old", payload=legacy)
    assert _proof_layer(store, "old") == ("incomplete", "uncertain")
    assert passed["inputs_sha256"] != structured["inputs_sha256"]


def test_an_audit_reads_afresh_and_records_no_endings(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    (objection,) = _verdict(store, "lem", "failed", objections=["step 2: a gap"])["objections"]
    audited = _verdict(store, "lem", "passed", audit=True)  # no ending asked of it
    assert audited["checker"] == "audit" and "fixed" not in audited
    assert get_challenge(store, objection["challenge_id"]).status.value == "open"  # left to the next ordinary Verifier
    assert _proof_layer(store, "lem")[0] == "incomplete"
    assert _code(lambda: _verdict(store, "lem", "passed", audit=True, fixed={objection["challenge_id"]: "fixed"})) == "AUDIT_RECORDS_NO_ENDINGS"


def test_an_evidence_check_says_what_checked_it_in_a_mark_not_its_notes(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    proof = submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof of lem")
    audit = record_evidence_check(store, proof.id, "passed", run_by="agent_v/verifier", notes="read afresh", checker="audit")
    external = record_evidence_check(store, proof.id, "passed", run_by="sage", notes="numerics agree")
    assert (audit.checker, external.checker) == ("audit", None)  # an outside checker names itself in run_by
    assert _code(lambda: record_evidence_check(store, proof.id, "passed", run_by="x", checker="oracle")) == "INVALID_CHECKER"


def test_the_cli_records_objections_and_endings_and_node_show_lists_each_with_its_ending(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    (tmp_path / "second.md").write_text("line 5: it cites the wrong lemma\n")
    (tmp_path / "fix.md").write_text("line 5 now cites the lemma before\n")

    def run(*args: str, ok: bool = True, env: dict | None = None) -> dict:
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"], env=env)
        envelope = json.loads(result.output)
        assert (result.exit_code == 0) == ok, result.output
        return envelope["data"] if ok else envelope["error"]

    verifier = ("node", "progress", "lem", "--role", "verifier", "--by", "agent_v")
    failed = run(*verifier, "--verdict", "failed", "--objection", "step 2: a gap at n = 0", "--objection-file", str(tmp_path / "second.md"))
    one, two = (objection["challenge_id"] for objection in failed["objections"])
    assert [objection["text"] for objection in failed["objections"]] == ["step 2: a gap at n = 0", "line 5: it cites the wrong lemma"]
    assert run(*verifier, "--verdict", "passed", "--fixed", f"{one}=n = 0 is the base case", ok=False)["missing"] == [two]
    audited = run(*verifier, "--verdict", "passed", env={"PROOF_AGENT_AUDIT": "1"})
    assert audited["checker"] == "audit" and "fixed" not in audited
    run(*verifier, "--verdict", "passed", "--fixed", f"{one}=n = 0 is the base case", "--fixed-file", f"{two}={tmp_path / 'fix.md'}")
    shown = " ".join(CliRunner().invoke(app, ["node", "progress", "lem", "--root", str(tmp_path)]).output.split())
    assert f"objection 1 of verdict {failed['id']}" in shown and "objections: 1. step 2: a gap at n = 0" in shown and "fixed 2 objection(s)" in shown
    objections = run("node", "show", "lem")["objections"]
    assert [(o["verdict_id"], o["objection"], o["status"], o["fix"]) for o in objections] == [
        (failed["id"], 1, "fixed", "n = 0 is the base case"), (failed["id"], 2, "fixed", "line 5 now cites the lemma before")]
    proof = submit_proof(store, "lem", claimant_id="agent", scoping_rationale="scoped", content="proof of lem")
    assert run("node", "evidence", "record", proof.id, "passed", "--run-by", "agent_v/verifier", "--checker", "audit")["checker"] == "audit"


def test_an_audit_is_shown_no_earlier_verdicts_objections(tmp_path: Path):
    # ADR-0024 point 13: an audit reads the proof afresh; an objection is an earlier verdict's
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    _verdict(store, "lem", "failed", objections=["step 2: a gap"])
    open_challenge(store, "lem", opened_by="agent_p", rationale="a doubt of the Prover's")
    audit = {"PROOF_AGENT_AUDIT": "1"}

    def data(*args: str, env: dict | None = None):
        result = CliRunner().invoke(app, [*args, "--root", str(tmp_path), "--json"], env=env)
        assert result.exit_code == 0, result.output
        return json.loads(result.output)["data"]

    assert len(data("node", "show", "lem")["objections"]) == 1
    shown = data("node", "show", "lem", env=audit)
    assert shown["objections"] == [] and "audit" in shown["objections_withheld"]
    assert [c["rationale"] for c in data("challenge", "list", "--target-id", "lem", env=audit)] == ["a doubt of the Prover's"]
    assert len(data("challenge", "list", "--target-id", "lem")) == 2


def test_a_verdict_raises_no_objection_on_a_sealed_node_and_writes_nothing(tmp_path: Path):
    # ADR-0025 point 14: the agents never challenge or audit a sealed node; an objection is a Challenge
    store = ensure_project(tmp_path)
    create_node(store, node_id="imp", kind="imported_result", statement="I", source_locator="Theorem 1", source_version="v1")
    researcher(store).decide_reference_review("imp", "no-longer-callable")  # sealed false, until seal lines exist (#279)
    assert _code(lambda: _verdict(store, "imp", "failed", objections=["the source has a gap", "and a second"])) == "NODE_SEALED"
    assert list_challenges(store, target_node_id="imp") == [] and not [e for e in work_log(store, "imp") if e["kind"] == "verdict"]


def test_an_audit_withdraws_no_objection(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="lem", kind="lemma", statement="L")
    (objection,) = _verdict(store, "lem", "failed", objections=["step 2: a gap"])["objections"]
    result = CliRunner().invoke(app, ["challenge", "withdraw", objection["challenge_id"], "--reason", "not a gap", "--by", "agent_v",
                                      "--root", str(tmp_path), "--json"], env={"PROOF_AGENT_AUDIT": "1"})
    assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] == "AUDIT_RECORDS_NO_ENDINGS"
    assert get_challenge(store, objection["challenge_id"]).status.value == "open"
