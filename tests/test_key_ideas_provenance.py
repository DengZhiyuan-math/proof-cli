"""#221: an agent's review request cannot confirm a summary for the researcher."""
import json

from _proofs import write_key_ideas
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.proof_map import (
    create_node,
    list_candidate_proofs,
    record_key_ideas_draft,
    request_review,
)
from proof_cli.storage import ensure_project
from proof_cli.vault import working_proof_path


def test_agent_role_request_review_records_unconfirmed_summary(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="A bound")
    working_proof_path(store.root, "L").write_text("A proof")
    summary = write_key_ideas(store, "L").read_bytes()
    record_key_ideas_draft(store, "L", agent="prover", content=summary)
    result = CliRunner().invoke(app, ["node", "request-review", "L", "--root", str(tmp_path),
                                    "--rationale", "scoped", "--requested-by", "prover", "--json"],
                                env={"PROOF_AGENT_ROLE": "prover"})
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["key_ideas_drafted_by"] == "agent (not confirmed by author)"


def test_human_request_confirms_draft_and_later_agent_request_keeps_old_snapshot(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="A bound")
    working_proof_path(store.root, "L").write_text("A proof")
    summary = write_key_ideas(store, "L").read_bytes()
    record_key_ideas_draft(store, "L", agent="prover", content=summary)
    first = request_review(store, "L", requested_by="researcher", rationale="scoped")
    assert first.key_ideas_drafted_by == "agent (confirmed by author at request-review)"
    working_proof_path(store.root, "L").write_text("A changed proof")
    second = request_review(store, "L", requested_by="prover", requester_role="prover", rationale="scoped")
    assert second.key_ideas_drafted_by == "agent (not confirmed by author)"
    assert list_candidate_proofs(store, "L")[0].key_ideas_drafted_by == first.key_ideas_drafted_by


def test_agent_changed_summary_never_claims_an_author_edit(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="L", kind="lemma", statement="A bound")
    working_proof_path(store.root, "L").write_text("A proof")
    summary = write_key_ideas(store, "L").read_bytes()
    record_key_ideas_draft(store, "L", agent="typesetter", content=summary)
    write_key_ideas(store, "L", summary.decode().replace("compactness", "continuity"))
    record = request_review(store, "L", requested_by="prover", requester_role="prover", rationale="scoped")
    assert record.key_ideas_drafted_by == "agent (not confirmed by author)"
