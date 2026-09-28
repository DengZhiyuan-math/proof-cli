"""Put a node's proof up for review in one step (#18).

The retired ADR-0003 `node submit` took the proof text and submitted it at
once; since ADR-0010 an agent edits the node's working `proof.tex` and then
requests review, which snapshots it. Tests that only need a node awaiting
review do both here.
"""

from proof_cli.proof_map import request_review
from proof_cli.vault import working_proof_path


def submit_proof(store, node_id: str, *, claimant_id: str, scoping_rationale: str, content: str, session_id: str = ""):
    working = working_proof_path(store.root, node_id)
    if working.parent.is_dir():  # an imported_result has none, and request_review refuses it
        working.write_text(content, encoding="utf-8")
    return request_review(store, node_id, requested_by=claimant_id, rationale=scoping_rationale)
