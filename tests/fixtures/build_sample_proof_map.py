"""The sample proof map of spec #14: a reusable fixture, built the way a project really grows (issue #98).

    T (theorem) ── L1 (lemma) ── C1 (claim, split from L1) ── I (imported result, Reference-reviewed)
               │             └── C2 (claim, split from L1)
               └── L2 (lemma) ── C2                            <- the shared dependency: a diamond
    R (claim, derived_from T), Rejected: an abandoned route
    an open Challenge on L1

Only service operations, the `_proofs` helper an agent's "write proof.tex, request review" goes
through, and the `_researcher` helper, which calls the very functions the proof map page's
decisions call. No SQL. `build_sample_proof_map(root, copies=n)` repeats everything under T but
the theorem itself n times (ids suffixed `-2`, `-3`, …), a baseline to scale a performance test on.

Known gap (see the xfail in tests/test_sample_proof_map.py): no service gives an existing node a
dependency, and `split_node` ignores a child spec's `dependencies`, so the edge C1 -> I is asked for
here but not recorded. It changes no node's axes: I is Reference-reviewed and never challenged.

Run as a script to leave a copy of the sample project behind:

    PYTHONPATH=src python tests/fixtures/build_sample_proof_map.py /tmp/sample-map
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from proof_cli.proof_map import create_node, open_challenge, split_node
from proof_cli.storage import ProjectStore, ensure_project

AGENT = "agent_a"


@dataclass
class SampleProofMap:
    store: ProjectStore
    theorem: str
    copies: list[dict[str, str]]  # per copy: role ("L1", "C1", …) -> node id
    challenges: list[str] = field(default_factory=list)  # the open Challenge on each copy's L1

    def ids(self, role: str) -> list[str]:
        return [copy[role] for copy in self.copies]


def _prove(store: ProjectStore, node_id: str, decision: str = "accept") -> None:
    from _proofs import submit_proof
    from _researcher import researcher

    submit_proof(store, node_id, claimant_id=AGENT, scoping_rationale="scoped", content=f"\\begin{{proof}}{node_id}.\\end{{proof}}\n")
    researcher(store).decide_acceptance(node_id, decision, rationale=f"sample map: {decision} {node_id}")


def build_sample_proof_map(root: Path, *, copies: int = 1) -> SampleProofMap:
    from _researcher import researcher

    store = ensure_project(root)
    names = [{role: role if k == 1 else f"{role}-{k}" for role in ("L1", "L2", "C1", "C2", "I", "R")} for k in range(1, copies + 1)]

    for n in names:
        create_node(store, node_id=n["I"], kind="imported_result", statement=f"Known result {n['I']}", source_locator="doi:10.0000/sample", source_version="v1")
        researcher(store).decide_reference_review(n["I"], rationale="the published source checks out")

        create_node(store, node_id=n["L1"], kind="lemma", statement=f"Lemma {n['L1']}")
        split_node(
            store,
            n["L1"],
            [
                # `dependencies` is not honoured by split_node today (see the module docstring)
                {"id": n["C1"], "statement": f"First half of {n['L1']}", "dependencies": [n["I"]]},
                {"id": n["C2"], "statement": f"Second half of {n['L1']}"},
            ],
            created_by=AGENT,
        )
        create_node(store, node_id=n["L2"], kind="lemma", statement=f"Lemma {n['L2']}", dependencies=[n["C2"]])

    theorem = create_node(
        store, node_id="T", kind="theorem", statement="The main theorem", dependencies=[d for n in names for d in (n["L1"], n["L2"])]
    ).id
    for n in names:
        create_node(store, node_id=n["R"], kind="claim", statement=f"An approach to T via route {n['R']}", derived_from=theorem)

    for n in names:
        for node_id in (n["C1"], n["C2"], n["L1"], n["L2"]):
            _prove(store, node_id)
        _prove(store, n["R"], "reject")

    challenges = [open_challenge(store, n["L1"], opened_by="agent_b", rationale="is the second half's hypothesis really met?").id for n in names]

    # Proof fog (ADR-0008) lives outside the graph as its own list; it is deferred to the next
    # milestone, so there is nothing to build yet. Add the sample's fog items here once it lands.

    return SampleProofMap(store=store, theorem=theorem, copies=names, challenges=challenges)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for _proofs and _researcher
    built = build_sample_proof_map(Path(sys.argv[1]), copies=int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    print(f"sample proof map at {built.store.root}")
