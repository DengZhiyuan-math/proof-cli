from proof_cli.storage import ensure_project
from proof_cli.proof_map import create_node, record_progress, record_evidence_check
from _proofs import submit_proof
from _review_client import DirectClient

def test_reference_review_surfaces_the_dependents_unchecked_source_warning(tmp_path):
    store = ensure_project(tmp_path)
    create_node(store, node_id="R", kind="imported_result", statement="Bound", source_locator="arXiv:example, Thm 1", source_version="v1", created_by="reader")
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R"], created_by="reader")
    warning = "R: unchecked against the source; the cited work cannot be reached"
    record_progress(store, "L", role="verifier", by="a", verdict="passed", note=warning)
    proof = submit_proof(store, "L", claimant_id="a", scoping_rationale="scoped", content="Proof invoking R")
    record_evidence_check(store, proof.id, "passed", run_by="a/verifier", notes=warning)
    client = DirectClient(store)
    try:
        source = client.get("/api/node/R")[1]["data"]
        card = next(p for p in client.get("/api/state")[1]["data"]["pending"] if p["node_id"] == "R")
        assert warning in str(source) or warning in str(card), {"source_evidence": source["evidence_checks"], "source_dependents": source["dependents"], "card": card}
    finally:
        client.app.close()
