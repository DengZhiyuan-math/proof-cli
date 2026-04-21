from __future__ import annotations

from proof_cli.reasoning import (
    ContractAdequacyCheck,
    DownstreamUse,
    LemmaReasoningUnit,
    LocalObligation,
    ReasoningProject,
    TheoremReasoningGoal,
)


def test_theorem_goal_decomposes_into_lemma_units_and_local_obligations() -> None:
    goal = TheoremReasoningGoal(
        id="goal_main",
        theorem_id="thm_main",
        statement="show the theorem by composing two lemmas",
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
                        id="obl_bridge_1",
                        statement="show the hidden continuity condition",
                        source_unit_id="lemma_bridge",
                        required_for="bridge lemma",
                    ),
                ],
            ),
            LemmaReasoningUnit(
                id="lemma_finish",
                theorem_id="thm_main",
                label="finish lemma",
                statement="close the final step",
                local_obligations=[
                    LocalObligation(
                        id="obl_finish_1",
                        statement="reuse the bridge conclusion locally",
                        source_unit_id="lemma_finish",
                        required_for="finish lemma",
                    ),
                ],
            ),
        ],
    )

    decomposition = goal.decompose()

    assert decomposition.theorem_goal.id == "goal_main"
    assert [lemma.id for lemma in decomposition.lemma_units] == ["lemma_bridge", "lemma_finish"]
    assert [obligation.id for obligation in decomposition.local_obligations] == [
        "obl_bridge_1",
        "obl_finish_1",
    ]
    assert decomposition.reasoning_unit_ids() == [
        "goal_main",
        "lemma_bridge",
        "lemma_finish",
        "obl_bridge_1",
        "obl_finish_1",
    ]


def test_contract_adequacy_evaluates_against_downstream_use() -> None:
    downstream_use = [
        DownstreamUse(
            id="use_corollary",
            label="corollary step",
            required_assumptions=["A"],
            required_exports=["C"],
            reasoning_path=["goal_main", "lemma_bridge", "use_corollary"],
        ),
    ]

    adequate = ContractAdequacyCheck.evaluate(
        contract_id="thm_main",
        contract_assumptions=["A"],
        contract_exports=["C"],
        downstream_use=downstream_use,
    )

    assert adequate.adequate is True
    assert adequate.review_recommendation == "accept"
    assert adequate.required_assumptions == ["A"]
    assert adequate.required_exports == ["C"]
    assert adequate.missing_conditions == []
    assert adequate.reasoning_path == ["goal_main", "lemma_bridge", "use_corollary"]

    fragile = ContractAdequacyCheck.evaluate(
        contract_id="thm_main",
        contract_assumptions=[],
        contract_exports=["C"],
        downstream_use=downstream_use,
    )

    assert fragile.adequate is False
    assert fragile.review_recommendation == "block"
    assert fragile.missing_assumptions == ["A"]
    assert fragile.missing_conditions == ["missing assumption: A"]


def test_reasoning_artifacts_round_trip_as_persistable_project_objects() -> None:
    project = ReasoningProject(
        project_id="proj_1",
        theorem_goals=[
            TheoremReasoningGoal(
                id="goal_main",
                theorem_id="thm_main",
                statement="compose theorem-level intent into local units",
                assumptions=["A"],
                exports=["C"],
                lemma_units=[
                    LemmaReasoningUnit(
                        id="lemma_bridge",
                        theorem_id="thm_main",
                        label="bridge lemma",
                        statement="bridge the local condition",
                    ),
                ],
                downstream_use=[
                    DownstreamUse(
                        id="use_bridge",
                        label="bridge use",
                        required_assumptions=["A"],
                        required_exports=["C"],
                        reasoning_path=["goal_main", "lemma_bridge"],
                    )
                ],
            )
        ],
        adequacy_checks=[
            ContractAdequacyCheck.evaluate(
                contract_id="thm_main",
                contract_assumptions=["A"],
                contract_exports=["C"],
                downstream_use=[
                    DownstreamUse(
                        id="use_bridge",
                        label="bridge use",
                        required_assumptions=["A"],
                        required_exports=["C"],
                        reasoning_path=["goal_main", "lemma_bridge"],
                    )
                ],
            )
        ],
    )

    payload = project.model_dump_json()
    reloaded = ReasoningProject.model_validate_json(payload)

    assert reloaded == project
    assert reloaded.theorem_goals[0].decompose().local_obligations == []
    assert reloaded.all_reasoning_units() == ["goal_main", "lemma_bridge"]
