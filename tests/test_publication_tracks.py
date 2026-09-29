"""Issue #30: publication's two tracks.

- The **mathematical track** is the node's own acceptance and integrity, read
  live from the counted Human Review decisions. Publication never writes it.
- The **editorial track** (`internal_draft → collaborator_ready →
  supplement_ready → paper_ready → withdrawn`) is set by anyone through the
  CLI, agents included, and is labelled editorial everywhere: it is not a
  Human Review decision. A node may only be put at supplement_ready or
  paper_ready while it is `accepted · current`, and an export withholds and
  flags a ready claim that no longer is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.collaboration import ReviewGovernanceState, record_decided_review
from proof_cli.domain import TheoremStatus, TrustLevel
from proof_cli.proof_map import ProofMapError, claim_node, create_node, open_challenge
from proof_cli.publication import (
    ALLOWED_TRANSITIONS,
    PublicationAudience,
    PublicationClaim,
    PublicationReadiness,
    build_publication_bundle,
    build_publication_view,
    get_publication_claim,
    load_publication_state,
    publication_paper_export,
    publication_supplement_export,
    record_publication_release,
    save_publication_state,
    set_publication_claim,
)
from proof_cli.storage import ensure_project, load_project
from proof_cli.theorems import add_theorem

runner = CliRunner()


def _review(store, node_id: str, decision: str) -> None:
    claim_node(store, node_id, claimant_id="agent_a", session_id="s")
    submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="scoped", content=f"proof of {node_id}")
    researcher(store).decide_acceptance(node_id, decision)


def _accepted(store, node_id: str = "L") -> None:
    create_node(store, node_id=node_id, kind="claim", statement=f"statement {node_id}")
    _review(store, node_id, "accept")


def _to_ready(store, node_id: str, target: str = "paper_ready") -> None:
    order = ["collaborator_ready", "supplement_ready", "paper_ready"]
    for step in order[: order.index(target) + 1]:
        set_publication_claim(store, node_id, object_type="proof_map_node", readiness=step)


def _theorem(store, theorem_id: str = "thm_legacy") -> None:
    add_theorem(
        store, theorem_id=theorem_id, kind="theorem", name="Legacy", statement="A implies B",
        assumptions=["A"], exports=["B"], status=TheoremStatus.verified, trust_level=TrustLevel.project_verified,
    )


def _envelope(result) -> dict:
    return json.loads(result.stdout)


# -- 1. the write gate --------------------------------------------------------------------


def test_an_accepted_current_node_steps_up_to_paper_ready(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store)
    _to_ready(store, "L")
    assert get_publication_claim(store, "L", object_type="proof_map_node").readiness == PublicationReadiness.paper_ready


def _gate_code(store, node_id: str, *, object_type: str = "proof_map_node", target: str = "paper_ready") -> str:
    with pytest.raises(ProofMapError) as excinfo:
        set_publication_claim(store, node_id, object_type=object_type, readiness=target)
    return excinfo.value.code


@pytest.mark.parametrize("target", ["supplement_ready", "paper_ready"])
def test_an_unreviewed_node_cannot_be_made_ready(tmp_path: Path, target):
    store = ensure_project(tmp_path)
    create_node(store, node_id="T", kind="claim", statement="t")
    # walk up as far as the gate allows, so only the gate can refuse
    set_publication_claim(store, "T", object_type="proof_map_node", readiness="collaborator_ready")
    if target == "paper_ready":
        state = load_publication_state(store)
        state.claims[0].readiness = PublicationReadiness.supplement_ready
        save_publication_state(store, state)
    assert _gate_code(store, "T", target=target) == "PUBLICATION_NOT_ACCEPTED"


def test_a_rejected_node_cannot_be_made_ready(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="R", kind="claim", statement="r")
    _review(store, "R", "reject")
    set_publication_claim(store, "R", object_type="proof_map_node", readiness="collaborator_ready")
    with pytest.raises(ProofMapError) as excinfo:
        set_publication_claim(store, "R", object_type="proof_map_node", readiness="supplement_ready")
    assert excinfo.value.code == "PUBLICATION_NOT_ACCEPTED"
    assert excinfo.value.details["acceptance_state"] == "rejected"


def test_a_challenged_node_cannot_be_made_ready(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store)
    open_challenge(store, "L", opened_by="agent_b", rationale="missing assumption")
    set_publication_claim(store, "L", object_type="proof_map_node", readiness="collaborator_ready")
    with pytest.raises(ProofMapError) as excinfo:
        set_publication_claim(store, "L", object_type="proof_map_node", readiness="supplement_ready")
    assert excinfo.value.code == "PUBLICATION_NOT_ACCEPTED"
    assert excinfo.value.details["integrity_state"] == "challenged"


def test_a_missing_node_is_refused_and_creates_no_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert _gate_code(store, "ghost", target="internal_draft") == "NODE_NOT_FOUND"
    assert load_publication_state(store).claims == []


def test_a_theorem_contract_claim_cannot_be_made_ready(tmp_path: Path):
    store = ensure_project(tmp_path)
    _theorem(store)
    set_publication_claim(store, "thm_legacy", object_type="theorem_contract", readiness="collaborator_ready")
    assert _gate_code(store, "thm_legacy", object_type="theorem_contract", target="supplement_ready") == "PUBLICATION_NO_ACCEPTANCE_AXIS"


def test_a_missing_theorem_contract_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    assert _gate_code(store, "thm_ghost", object_type="theorem_contract", target="internal_draft") == "THEOREM_NOT_FOUND"


def test_dependencies_are_not_written_into_supporting_theorem_ids(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store, "D")
    create_node(store, node_id="P", kind="claim", statement="p", dependencies=["D"])
    assert get_publication_claim(store, "P", object_type="proof_map_node").supporting_theorem_ids == []


# -- 3. the editorial track ---------------------------------------------------------------


def test_the_editorial_track_has_five_states():
    assert [state.value for state in PublicationReadiness] == [
        "internal_draft", "collaborator_ready", "supplement_ready", "paper_ready", "withdrawn",
    ]


def test_every_state_has_documented_transitions():
    assert set(ALLOWED_TRANSITIONS) == set(PublicationReadiness)
    context = (Path(__file__).resolve().parents[1] / "CONTEXT.md").read_text()
    assert "**Editorial readiness**" in context
    for state in PublicationReadiness:
        assert state.value in context


def test_jumping_straight_to_paper_ready_is_refused(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store)
    with pytest.raises(ProofMapError) as excinfo:
        set_publication_claim(store, "L", object_type="proof_map_node", readiness="paper_ready")
    assert excinfo.value.code == "INVALID_READINESS_TRANSITION"
    assert excinfo.value.details["allowed"] == ["internal_draft", "collaborator_ready", "withdrawn"]


def test_withdrawn_restarts_at_internal_draft_only(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store)
    _to_ready(store, "L")
    set_publication_claim(store, "L", object_type="proof_map_node", readiness="withdrawn")
    with pytest.raises(ProofMapError):
        set_publication_claim(store, "L", object_type="proof_map_node", readiness="collaborator_ready")
    set_publication_claim(store, "L", object_type="proof_map_node", readiness="internal_draft")


def test_an_unknown_readiness_is_a_stable_error(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store)
    assert _gate_code(store, "L", target="disputed") == "INVALID_READINESS"


@pytest.mark.parametrize(
    "legacy, migrated",
    [("disputed", "internal_draft"), ("blocked", "internal_draft"), ("superseded", "withdrawn")],
)
def test_legacy_readiness_records_migrate(tmp_path: Path, legacy, migrated):
    claim = PublicationClaim.model_validate({"object_type": "proof_map_node", "object_id": "L", "readiness": legacy})
    assert claim.readiness.value == migrated
    assert claim.migrated_from == legacy
    assert any(legacy in note and migrated in note for note in claim.editorial_notes)

    # and a stored workspace carrying the old value loads, and keeps the migration once saved
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="claim", statement="l")
    state = load_publication_state(store)
    raw = state.model_dump(mode="json")
    raw["claims"] = [{"object_type": "proof_map_node", "object_id": "L", "readiness": legacy}]
    from proof_cli.storage import store_publication_state

    store_publication_state(store, state.project_id, json.dumps(raw), updated_at=state.updated_at)
    reloaded = get_publication_claim(store, "L", object_type="proof_map_node")
    assert reloaded.readiness.value == migrated


# -- 2. exports show both axes and withhold what is no longer accepted · current -----------


def _paper_ready_then_challenged(store) -> None:
    _accepted(store, "L")
    _to_ready(store, "L")
    _accepted(store, "M")
    _to_ready(store, "M")
    open_challenge(store, "L", opened_by="agent_b", rationale="missing assumption")


def test_a_paper_ready_node_challenged_later_is_withheld_and_flagged(tmp_path: Path):
    store = ensure_project(tmp_path)
    _paper_ready_then_challenged(store)

    paper = publication_paper_export(store)
    claims_section = paper.split("Withheld")[0]
    assert "M:" in claims_section and "L:" not in claims_section
    withheld = paper.split("Withheld")[1]
    assert "L" in withheld and "challenged" in withheld

    view = build_publication_view(store, PublicationAudience.paper)
    selection = next(s for s in view.selections if s.claim.object_id == "L")
    assert selection.visible is False and selection.withheld is True
    assert "integrity=challenged" in selection.reason

    bundle = build_publication_bundle(store)
    assert [claim["object_id"] for claim in bundle["claims"]] == ["M"]
    assert [item["object_id"] for item in bundle["withheld_claims"]] == ["L"]
    assert bundle["withheld_claims"][0]["integrity_state"] == "challenged"


def test_the_exports_show_both_axes_for_every_claim(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store, "M")
    _to_ready(store, "M")
    paper = publication_paper_export(store)
    supplement = publication_supplement_export(store)
    for text in (paper, supplement):
        line = next(line for line in text.splitlines() if line.startswith("- M:"))
        assert "acceptance=accepted" in line and "integrity=current" in line and "editorial" in line
    bundle = build_publication_bundle(store)
    assert bundle["claims"][0]["acceptance_state"] == "accepted"
    assert bundle["claims"][0]["integrity_state"] == "current"
    assert bundle["claims"][0]["track"] == "editorial"


def test_a_legacy_ready_theorem_contract_claim_is_withheld(tmp_path: Path):
    store = ensure_project(tmp_path)
    _theorem(store)
    state = load_publication_state(store)
    state.claims.append(PublicationClaim(object_type="theorem_contract", object_id="thm_legacy", readiness="paper_ready"))
    save_publication_state(store, state)
    bundle = build_publication_bundle(store)
    assert bundle["claims"] == []
    assert bundle["withheld_claims"][0]["object_id"] == "thm_legacy"


# -- 4. labels: editorial records apart from counted Human Review decisions ----------------


def test_the_bundle_separates_counted_decisions_from_editorial_reviews(tmp_path: Path):
    store = ensure_project(tmp_path)
    _accepted(store, "M")
    _to_ready(store, "M")
    _theorem(store)
    record_decided_review(store, "theorem_contract", "thm_legacy", ReviewGovernanceState.approved, reviewer_id="researcher")
    record_publication_release(store, audience="paper", approved_by=["researcher"])

    bundle = build_publication_bundle(store)
    records = bundle["review_records"]
    assert set(records) == {"human_review_decisions", "editorial_reviews", "not_counted"}
    assert [(row["object_id"], row["decision"]) for row in records["human_review_decisions"]] == [("M", "approved")]
    assert all(row["counted"] is True for row in records["human_review_decisions"])
    # nothing uncounted anywhere in the bundle reads "approved"
    for row in records["editorial_reviews"] + records["not_counted"]:
        assert "decision" not in row and row["counted"] is False
    assert "review_records" not in bundle["collaboration"]
    assert all(record["track"] == "editorial" for record in bundle["release_history"])


def test_an_uncounted_human_review_row_does_not_show_as_approved(tmp_path: Path, monkeypatch):
    store = ensure_project(tmp_path)
    _accepted(store, "M")
    _to_ready(store, "M")
    from proof_cli import authority

    monkeypatch.setattr(authority, "verify_decision_row", lambda store, row_id: authority.RowVerdict("invalid", reason="forged"))
    records = build_publication_bundle(store)["review_records"]
    assert records["human_review_decisions"] == []
    assert records["not_counted"][0]["object_id"] == "M"
    assert "decision" not in records["not_counted"][0]


# -- 5. --audience and the release_status default -------------------------------------------


def test_release_records_the_audience_it_was_given(tmp_path: Path):
    ensure_project(tmp_path)
    result = runner.invoke(app, ["publication", "release", "--root", str(tmp_path), "--audience", "supplement", "--approved-by", "ed", "--json"])
    assert result.exit_code == 0, result.output
    data = _envelope(result)["data"]
    assert data["audience"] == "supplement" and data["track"] == "editorial"


def test_set_without_release_status_records_no_approval(tmp_path: Path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="claim", statement="l")
    result = runner.invoke(
        app, ["publication", "set", "L", "collaborator_ready", "--root", str(tmp_path), "--title", "T", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert _envelope(result)["data"]["release_status"] is None
    assert load_publication_state(load_project(tmp_path)).release_history == []


# -- 6. the CLI contract: human-readable and --json -----------------------------------------


def _cli_project(tmp_path: Path) -> Path:
    store = ensure_project(tmp_path)
    _accepted(store, "L")
    create_node(store, node_id="T", kind="claim", statement="t")
    _theorem(store)
    return tmp_path


def _set(root: Path, node_id: str, readiness: str, *extra: str):
    return runner.invoke(app, ["publication", "set", node_id, readiness, "--root", str(root), *extra])


@pytest.mark.parametrize(
    "node_id, extra, code",
    [
        ("T", [], "INVALID_READINESS_TRANSITION"),
        ("ghost", [], "NODE_NOT_FOUND"),
        ("thm_legacy", ["--object-type", "theorem_contract"], "INVALID_READINESS_TRANSITION"),
        ("L", ["--object-type", "nonsense"], "INVALID_OBJECT_TYPE"),
    ],
)
def test_cli_set_failures_are_envelopes_with_a_non_zero_exit(tmp_path: Path, node_id, extra, code):
    root = _cli_project(tmp_path)
    result = _set(root, node_id, "paper_ready", *extra, "--json")
    assert result.exit_code == 1
    envelope = _envelope(result)
    assert envelope["ok"] is False and envelope["error"]["code"] == code and envelope["command"] == "publication.set"


def test_cli_set_gate_on_an_unreviewed_node(tmp_path: Path):
    root = _cli_project(tmp_path)
    assert _set(root, "T", "collaborator_ready", "--json").exit_code == 0
    result = _set(root, "T", "supplement_ready", "--json")
    assert result.exit_code == 1
    error = _envelope(result)["error"]
    assert error["code"] == "PUBLICATION_NOT_ACCEPTED" and error["acceptance_state"] == "unreviewed"
    human = _set(root, "T", "supplement_ready")
    assert human.exit_code == 1 and human.stdout.startswith("Error:")


def test_cli_set_theorem_contract_gate(tmp_path: Path):
    root = _cli_project(tmp_path)
    assert _set(root, "thm_legacy", "collaborator_ready", "--object-type", "theorem_contract").exit_code == 0
    result = _set(root, "thm_legacy", "supplement_ready", "--object-type", "theorem_contract", "--json")
    assert result.exit_code == 1 and _envelope(result)["error"]["code"] == "PUBLICATION_NO_ACCEPTANCE_AXIS"


def test_cli_set_human_and_json(tmp_path: Path):
    root = _cli_project(tmp_path)
    human = _set(root, "L", "collaborator_ready")
    assert human.exit_code == 0, human.output
    assert "editorial" in human.stdout.lower() and "not a human review decision" in human.stdout.lower()
    assert "acceptance=accepted" in human.stdout and "integrity=current" in human.stdout

    result = _set(root, "L", "supplement_ready", "--json")
    envelope = _envelope(result)
    assert envelope["ok"] is True and envelope["command"] == "publication.set" and envelope["schema_version"] == 1
    data = envelope["data"]
    assert data["readiness"] == "supplement_ready" and data["track"] == "editorial"
    assert data["acceptance_state"] == "accepted" and data["integrity_state"] == "current"


def test_cli_show_and_list_human_and_json(tmp_path: Path):
    root = _cli_project(tmp_path)
    _set(root, "L", "collaborator_ready")
    show = runner.invoke(app, ["publication", "show", "L", "--root", str(root)])
    assert show.exit_code == 0 and "collaborator_ready" in show.stdout and "editorial" in show.stdout
    show_json = _envelope(runner.invoke(app, ["publication", "show", "L", "--root", str(root), "--json"]))
    assert show_json["command"] == "publication.show" and show_json["data"][0]["readiness"] == "collaborator_ready"
    missing = runner.invoke(app, ["publication", "show", "ghost", "--root", str(root), "--json"])
    assert missing.exit_code == 1 and _envelope(missing)["error"]["code"] == "PUBLICATION_CLAIM_NOT_FOUND"

    listing = runner.invoke(app, ["publication", "list", "--root", str(root)])
    assert listing.exit_code == 0 and "acceptance=accepted" in listing.stdout
    listing_json = _envelope(runner.invoke(app, ["publication", "list", "--root", str(root), "--json"]))
    assert {item["object_id"] for item in listing_json["data"]} >= {"L", "T", "thm_legacy"}


def test_cli_view_human_and_json(tmp_path: Path):
    root = _cli_project(tmp_path)
    human = runner.invoke(app, ["publication", "view", "--root", str(root)])
    assert human.exit_code == 0 and "Publication workspace" in human.stdout
    data = _envelope(runner.invoke(app, ["publication", "view", "--root", str(root), "--json"]))["data"]
    assert data["audience"] == "paper" and "selections" in data


@pytest.mark.parametrize("fmt", ["paper", "supplement", "bundle", "manifest"])
def test_cli_export_human_and_json(tmp_path: Path, fmt):
    root = _cli_project(tmp_path)
    for step in ("collaborator_ready", "supplement_ready", "paper_ready"):
        assert _set(root, "L", step).exit_code == 0
    runner.invoke(app, ["challenge", "open", "L", "--root", str(root), "--opened-by", "agent_b", "--rationale", "gap"])
    human = runner.invoke(app, ["publication", "export", "--root", str(root), "--format", fmt])
    assert human.exit_code == 0, human.output
    envelope = _envelope(runner.invoke(app, ["publication", "export", "--root", str(root), "--format", fmt, "--json"]))
    assert envelope["ok"] is True and envelope["command"] == "publication.export"
    if fmt in ("paper", "supplement"):
        assert "Withheld" in human.stdout and "challenged" in human.stdout
        assert envelope["data"]["withheld_claims"][0]["object_id"] == "L"
        assert envelope["data"]["claims"] == []


def test_cli_export_bundle_respects_audience(tmp_path: Path):
    root = _cli_project(tmp_path)
    bundle = json.loads(runner.invoke(app, ["publication", "export", "--root", str(root), "--format", "bundle", "--audience", "supplement"]).stdout)
    assert bundle["audience"] == "supplement"
    bad = runner.invoke(app, ["publication", "export", "--root", str(root), "--format", "pdf", "--json"])
    assert bad.exit_code == 1 and _envelope(bad)["error"]["code"] == "UNSUPPORTED_FORMAT"


def test_cli_release_and_withdraw_human_and_json(tmp_path: Path):
    root = _cli_project(tmp_path)
    human = runner.invoke(app, ["publication", "release", "--root", str(root), "--approved-by", "ed"])
    assert human.exit_code == 0 and "editorial" in human.stdout.lower() and "git" in human.stdout.lower()
    release = _envelope(runner.invoke(app, ["publication", "release", "--root", str(root), "--audience", "supplement", "--json"]))["data"]

    withdrawn = runner.invoke(app, ["publication", "withdraw", release["id"], "--root", str(root), "--approved-by", "ed", "--json"])
    assert withdrawn.exit_code == 0, withdrawn.output
    data = _envelope(withdrawn)["data"]
    assert data["status"] == "withdrawn" and data["audience"] == "supplement" and data["withdrawn_by"] == ["ed"]
    assert data["track"] == "editorial"

    human_withdraw = runner.invoke(app, ["publication", "withdraw", release["bundle_id"], "--root", str(root)])
    assert human_withdraw.exit_code == 0 and "editorial" in human_withdraw.stdout.lower()

    missing = runner.invoke(app, ["publication", "withdraw", "nope", "--root", str(root), "--json"])
    assert missing.exit_code == 1 and _envelope(missing)["error"]["code"] == "RELEASE_NOT_FOUND"
    bad = runner.invoke(app, ["publication", "release", "--root", str(root), "--audience", "journal", "--json"])
    assert bad.exit_code == 1 and _envelope(bad)["error"]["code"] == "INVALID_AUDIENCE"
