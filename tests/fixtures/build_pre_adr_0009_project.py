"""Build tests/fixtures/pre_adr_0009_project with the code of `master` before #35.

Run it against a checkout of that code, not this one, e.g.:

    git archive <pre-#35 commit> src | tar -x -C /tmp/pre35
    PYTHONPATH=/tmp/pre35/src python tests/fixtures/build_pre_adr_0009_project.py tests/fixtures/pre_adr_0009_project

It records every decision kind a pre-ADR-0009 project can hold, unsigned,
and writes `master_axes.json` next to the project: how *that* code read
each node, so the re-sign test (#42) checks the project is restored to
exactly its previous axes rather than to values written into the test.
"""

import json
import shutil
import sys
from pathlib import Path

from proof_cli.proof_map import (
    claim_node,
    create_node,
    decide_acceptance,
    decide_evidence_review,
    decide_reference_review,
    dismiss_challenge,
    get_acceptance_state,
    get_integrity_state,
    get_node,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    open_challenge,
    promote_to_lemma,
    record_evidence_check,
    submit_candidate_proof,
)
from proof_cli.storage import ensure_project

root = Path(sys.argv[1])
if root.exists():
    shutil.rmtree(root)
store = ensure_project(root)


def submit(node_id, session="s1"):
    claim_node(store, node_id, claimant_id="agent_a", session_id=session)
    return submit_candidate_proof(
        store, node_id, claimant_id="agent_a", session_id=session, scoping_rationale="scoped", content=f"# Proof of {node_id}\n\nBy **induction**."
    )


create_node(store, node_id="acc", kind="lemma", statement="A holds")
proof = submit("acc")
decide_acceptance(store, "acc", "accept", confirmed=True)
check = record_evidence_check(store, proof.id, "passed", notes="all backends agree")
decide_evidence_review(store, check.id, "trusted", confirmed=True)

create_node(store, node_id="pro", kind="claim", statement="P holds")
submit("pro")
decide_acceptance(store, "pro", "accept", confirmed=True)
promote_to_lemma(store, "pro", confirmed=True)

create_node(store, node_id="rej", kind="claim", statement="R holds")
submit("rej")
decide_acceptance(store, "rej", "reject", confirmed=True)

create_node(store, node_id="rev", kind="claim", statement="V holds")
submit("rev")
decide_acceptance(store, "rev", "revision-requested", confirmed=True)

create_node(store, node_id="ref", kind="imported_result", statement="K holds", source_locator="doi:x", source_version="v1")
decide_reference_review(store, "ref", "reference-review", confirmed=True)

create_node(store, node_id="dis", kind="lemma", statement="D holds")
submit("dis")
decide_acceptance(store, "dis", "accept", confirmed=True)
challenge = open_challenge(store, "dis", opened_by="agent_b", rationale="step 2?")
dismiss_challenge(store, challenge.id, confirmed=True)

create_node(store, node_id="dep", kind="claim", statement="uses A and K", dependencies=["acc", "ref"])

axes = {}
for node_id in ("acc", "pro", "rej", "rev", "ref", "dis", "dep"):
    node = get_node(store, node_id)
    axes[node_id] = {
        "kind": node.kind.value,
        "acceptance": get_reference_review_state(store, node_id) if node.kind.value == "imported_result" else get_acceptance_state(store, node_id),
        "workflow": get_workflow_state(store, node_id),
        "integrity": get_integrity_state(store, node_id),
    }
axes["challenges"] = {c.id: c.status.value for c in list_challenges(store)}
(root / "master_axes.json").write_text(json.dumps(axes, indent=2, sort_keys=True))
print(json.dumps(axes, indent=2, sort_keys=True))
