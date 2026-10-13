"""Independent exact-source probes for #202's scope decisions and transaction."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from _researcher import researcher
from proof_cli import reference_edit
from proof_cli.proof_map import create_node, get_reference_review_state, get_workflow_state
from proof_cli.references import ReferenceRecord
from proof_cli.storage import ensure_project, get_reference, import_reference, list_events

evidence = Path(__file__).resolve().parent
root = Path(tempfile.mkdtemp(prefix="proof-core202-probe-", dir="/private/tmp"))
store = ensure_project(root)
before = import_reference(store, ReferenceRecord(id="citation", title="A work", authors=["A. Author"], year=2020,
                                              origin="old origin", bibliographic_source="old bibliography", created_by="human"))
create_node(store, node_id="R", kind="imported_result", statement="Result", source_locator="Theorem 1", source_version="v1",
            reference_id="citation", created_by="human")
create_node(store, node_id="C", kind="claim", statement="Uses R", dependencies=["R"])
researcher(store).declare_trust_rule("doi", conditions=[{"kind": "identifier_has_doi"}], rationale="synthetic rule")


def edit(*options):
    result = subprocess.run([sys.executable, "-B", "-m", "proof_cli.cli", "reference", "edit", "citation", *options,
                             "--root", str(root), "--json"], env={**os.environ, "PROOF_AGENT_NAME": "reader-probe"},
                            capture_output=True, text=True, check=True)
    envelope = json.loads(result.stdout)
    assert envelope["ok"], envelope
    return envelope["data"]


observations = []
after = edit("--origin", "corrected origin", "--bibliographic-source", "corrected bibliography", "--reason", "fix bibliography")
assert after["origin"] == "corrected origin" and after["bibliographic_source"] == "corrected bibliography"
assert after["id"] == before.id and after["created_by"] == before.created_by
assert get_reference(store, "citation").created_at == before.created_at
edits = [e for e in list_events(store) if e.kind == "reference_edited"]
assert edits[-1].payload["by"] == "reader-probe"
assert set(edits[-1].payload["fields"]) == {"origin", "bibliographic_source"}
observations.append({"case": "origin and bibliographic source", "result": "editable; provenance unchanged; actor and field diff recorded"})

assert get_reference_review_state(store, "R") == "unreviewed" and get_workflow_state(store, "C") == "blocked"
edit("--identifier", "doi:10.1000/browser202", "--reason", "complete the DOI")
assert get_reference_review_state(store, "R") == "trusted-by-rule" and get_workflow_state(store, "C") == "open"
edit("--identifier", "", "--reason", "remove the DOI")
assert get_reference_review_state(store, "R") == "unreviewed" and get_workflow_state(store, "C") == "blocked"
observations.append({"case": "agent edits researcher's citation", "result": "DOI add enables rule; DOI removal removes rule; editor is reader-probe"})

unchanged = get_reference(store, "citation")
original_append = reference_edit.append_event


def fails(*args, **kwargs):
    raise RuntimeError("synthetic event failure")


reference_edit.append_event = fails
try:
    try:
        reference_edit.edit_reference(store, "citation", {"title": "Must roll back"}, edited_by="reader-probe", reason="rollback probe")
    except RuntimeError as error:
        assert str(error) == "synthetic event failure"
    else:
        raise AssertionError("event failure did not propagate")
finally:
    reference_edit.append_event = original_append
assert get_reference(store, "citation") == unchanged
observations.append({"case": "event write fails", "result": "bibliographic update rolled back"})
output = {"project": str(root), "cases": observations}
(evidence / "scope-probe-results.json").write_text(json.dumps(output, indent=2) + "\n")
print(json.dumps(output, indent=2))
