from __future__ import annotations

from pathlib import Path

from proof_cli.domain import ProofObligationStatus
from proof_cli.obligations import derive_obligations
from proof_cli.proof_state import load_state
from proof_cli.reasoning import DownstreamUse, LemmaReasoningUnit, LocalObligation, TheoremReasoningGoal
from proof_cli.storage import ensure_project, list_events, list_obligations


def _sample_goal() -> TheoremReasoningGoal:
    return TheoremReasoningGoal(
        id="goal_main",
        theorem_id="thm_main",
        statement="show the theorem by composing a bridge lemma and a finish step",
        assumptions=["A"],
        exports=["C"],
        lemma_units=[
            LemmaReasoningUnit(
                id="lemma_bridge",
                theorem_id="thm_main",
                label="bridge lemma",
                statement="derive the bridge condition",
                local_obligations=[
                    LocalObligation(
                        id="obl_bridge_local",
                        statement="show the bridge continuity condition",
                        source_unit_id="lemma_bridge",
                        required_for="bridge lemma",
                    )
                ],
            )
        ],
        downstream_use=[
            DownstreamUse(
                id="use_corollary",
                label="corollary step",
                required_assumptions=["A", "B"],
                required_exports=["C", "D"],
                reasoning_path=["goal_main", "lemma_bridge", "use_corollary"],
                notes="downstream reuse of the theorem",
            )
        ],
    )


def test_theorem_goal_synthesizes_downstream_obligations() -> None:
    goal = _sample_goal()

    obligations = goal.synthesize_obligations(contract_assumptions=["A"], contract_exports=["C"])

    assert [obligation.id for obligation in obligations] == [
        "obl_bridge_local",
        "obl_goal_main__use_corollary__missing_assumption__b",
        "obl_goal_main__use_corollary__missing_export__d",
        "obl_goal_main__use_corollary__intermediate_claim__lemma_bridge",
    ]
    assert [obligation.required_for for obligation in obligations] == [
        "bridge lemma",
        "use_corollary",
        "use_corollary",
        "use_corollary",
    ]
    assert obligations[1].source_unit_id == "goal_main"
    assert obligations[2].source_unit_id == "goal_main"
    assert obligations[3].source_unit_id == "lemma_bridge"
    assert obligations[3].dependencies == [
        "downstream_use:use_corollary",
        "theorem_intent:goal_main",
        "use_note:downstream_reuse_of_the_theorem",
        "intermediate_claim:lemma_bridge",
    ]


def test_derive_obligations_persists_reviewable_open_state(tmp_path: Path) -> None:
    store = ensure_project(tmp_path)
    goal = _sample_goal()

    derived = derive_obligations(store, goal, contract_assumptions=["A"], contract_exports=["C"])
    stored = list_obligations(store)
    state = load_state(store)
    events = list_events(store)

    assert sorted(obligation.id for obligation in derived) == [obligation.id for obligation in stored]
    assert all(obligation.status == ProofObligationStatus.open for obligation in stored)
    assert all(obligation.blocking_reason is not None for obligation in stored)
    assert all(obligation.id in state.open_obligations for obligation in stored)
    assert any(event.kind == "obligation_synthesized" for event in events)
    assert any(event.entity_id == "obl_goal_main__use_corollary__missing_assumption__b" for event in events)
    assert stored[0].blocking_reason == "derived from bridge lemma"
    assert stored[1].blocking_reason == "derived from use_corollary"
