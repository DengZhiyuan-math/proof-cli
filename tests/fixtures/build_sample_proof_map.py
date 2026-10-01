"""The sample proof map of spec #14: a reusable fixture, built the way a project really grows (issue #98).

    T (theorem) ── L1 (lemma) ── C1 (claim, split from L1) ── I (imported result, Reference-reviewed)
               │             └── C2 (claim, split from L1)
               └── L2 (lemma) ── C2                            <- the shared dependency: a diamond
    R (claim, derived_from T), Rejected: an abandoned route
    N (claim, derived_from T, medium computation): established by a program — run.sh, out/, a passed
       Evidence check — and Accepted on it (spec #145)
    I2 (imported result citing the same source as I, at the same version): Trusted by rule
       under the Trust rule `same-source` (`source already reviewed`, ADR-0014), never reviewed itself
    an open Challenge on L1
    Proof fog (ADR-0008, spec #136): one open item near L1 with a `supports` Experiment whose script is
       in L1's scratch/, and one dropped item near T

Only service operations, the `_proofs` helper an agent's "write proof.tex, request review" goes
through, and the `_researcher` helper, which calls the very functions the proof map page's
decisions call. No SQL. `build_sample_proof_map(root, copies=n)` repeats everything under T but
the theorem itself n times (ids suffixed `-2`, `-3`, …), a baseline to scale a performance test on.

Run as a script to leave a copy of the sample project behind:

    PYTHONPATH=src python tests/fixtures/build_sample_proof_map.py /tmp/sample-map
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from proof_cli.fog import add_fog, drop_fog, record_experiment
from proof_cli.proof_map import create_node, open_challenge, record_evidence_check, request_review, split_node
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ProjectStore, ensure_project, import_reference

AGENT = "agent_a"
# the one citation of the sample: I and I2 both link it (issue #91)
SOURCE = ReferenceRecord(id="sample-source", title="A Sample Monograph", authors=["S. Ample"], year=2001,
                         source_type=ReferenceSourceType.monograph, identifier="doi:10.0000/sample")
TRUST_RULE = "same-source"


@dataclass
class SampleProofMap:
    store: ProjectStore
    theorem: str
    copies: list[dict[str, str]]  # per copy: role ("L1", "C1", …) -> node id
    challenges: list[str] = field(default_factory=list)  # the open Challenge on each copy's L1

    def ids(self, role: str) -> list[str]:
        return [copy[role] for copy in self.copies]


def _write_key_ideas(store: ProjectStore, node_id: str) -> None:
    from _proofs import write_key_ideas

    write_key_ideas(store, node_id)


def _prove(store: ProjectStore, node_id: str, decision: str = "accept") -> None:
    from _proofs import submit_proof
    from _researcher import researcher

    submit_proof(store, node_id, claimant_id=AGENT, scoping_rationale="scoped", content=f"\\begin{{proof}}{node_id}.\\end{{proof}}\n")
    researcher(store).decide_acceptance(node_id, decision, rationale=f"sample map: {decision} {node_id}")


def build_sample_proof_map(root: Path, *, copies: int = 1) -> SampleProofMap:
    from _researcher import researcher

    store = ensure_project(root)
    import_reference(store, SOURCE)
    # one look per source and version (ADR-0014): I2 cites what I was reviewed for, and is trusted by that rule
    researcher(store).declare_trust_rule(TRUST_RULE, conditions=[{"kind": "source_already_reviewed"}], rationale="one look per source and edition")
    names = [{role: role if k == 1 else f"{role}-{k}" for role in ("L1", "L2", "C1", "C2", "I", "I2", "R", "N")} for k in range(1, copies + 1)]

    for n in names:
        create_node(store, node_id=n["I"], kind="imported_result", statement=f"Known result {n['I']}", source_locator="Theorem 1", source_version="v1", reference_id=SOURCE.id)
        researcher(store).decide_reference_review(n["I"], rationale="the published source checks out")
        create_node(store, node_id=n["I2"], kind="imported_result", statement=f"Known result {n['I2']}", source_locator="Theorem 2", source_version="v1", reference_id=SOURCE.id)

        create_node(store, node_id=n["L1"], kind="lemma", statement=f"Lemma {n['L1']}")
        split_node(
            store,
            n["L1"],
            [
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

    # a computation node (spec #145): its program and outputs are the candidate proof; a run is an Evidence check
    for n in names:
        create_node(store, node_id=n["N"], kind="claim", statement=f"For every n ≤ 10^4 the inequality of {n['N']} holds", derived_from=theorem, medium="computation")
        folder = root / "proofs" / n["N"]
        (folder / "run.sh").write_text("#!/usr/bin/env bash\nset -e\nmkdir -p out\npython3 check.py > out/table.csv\n")
        (folder / "check.py").write_text("print('n,ratio')\nfor k in (10, 100, 1000, 10000):\n    print(f'{k},{1 - 1 / k:.4f}')\n")
        (folder / "out").mkdir(exist_ok=True)
        (folder / "out" / "table.csv").write_text("n,ratio\n10,0.9000\n100,0.9900\n1000,0.9990\n10000,0.9999\n")
        _write_key_ideas(store, n["N"])
        proof = request_review(store, n["N"], requested_by=AGENT, rationale="a finite check: every n ≤ 10^4 is covered")
        record_evidence_check(store, proof.id, "passed", notes="exit 0: every n ≤ 10^4 checked", run_by=AGENT)
        researcher(store).decide_acceptance(n["N"], "accept", rationale="the program covers every case and its output is on record")

    for n in names:
        for node_id in (n["C1"], n["C2"], n["L1"], n["L2"]):
            _prove(store, node_id)
        _prove(store, n["R"], "reject")

    challenges = [open_challenge(store, n["L1"], opened_by="agent_b", rationale="is the second half's hypothesis really met?").id for n in names]

    # Proof fog (ADR-0008, spec #136): outside the graph, as its own list
    for n in names:
        item = add_fog(store, f"the constant in {n['L1']} is probably optimal, but 'optimal' is not yet a statement", near=[n["L1"]], created_by=AGENT)
        script = store.root / "proofs" / n["L1"] / "scratch" / "constant.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# checks the ratio for n <= 10**6\n")
        record_experiment(store, item.id, "supports", summary="n ≤ 10^6 checked one by one; the ratio tends to 1", run_by=AGENT, path=f"proofs/{n['L1']}/scratch/constant.py")
        given_up = add_fog(store, "generating functions by brute force", near=[theorem])
        drop_fog(store, given_up.id, reason="the coefficients grow too fast to estimate")

    return SampleProofMap(store=store, theorem=theorem, copies=names, challenges=challenges)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for _proofs and _researcher
    built = build_sample_proof_map(Path(sys.argv[1]), copies=int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    print(f"sample proof map at {built.store.root}")
