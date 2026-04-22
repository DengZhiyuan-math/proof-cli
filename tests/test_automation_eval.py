from __future__ import annotations

import pytest

from proof_cli.automation_eval import (
    AutomationEvaluationMode,
    aggregate_automation_evaluations,
    build_automation_evaluation_record,
    compare_automation_evaluations,
    group_automation_evaluations_by_mode,
    replay_automation_benchmark,
)


def _assisted_record(
    *,
    benchmark_name: str = "phase5-compounding",
    scenario_id: str = "scenario_uniformity",
    project_id: str = "proj_alpha",
    time_spent_minutes: float = 10.0,
    obligations_resolved: int = 4,
    false_positives: int = 1,
    review_burden_minutes: float = 2.0,
    stale_automation_count: int = 0,
    repeated_error_reduction_count: int = 2,
    reuse_hits: int = 3,
    accepted_actions: int = 4,
    rejected_actions: int = 0,
) -> object:
    return build_automation_evaluation_record(
        benchmark_name=benchmark_name,
        scenario_id=scenario_id,
        project_id=project_id,
        task_type="theorem_application_checks",
        mode=AutomationEvaluationMode.assisted,
        time_spent_minutes=time_spent_minutes,
        obligations_resolved=obligations_resolved,
        false_positives=false_positives,
        review_burden_minutes=review_burden_minutes,
        stale_automation_count=stale_automation_count,
        repeated_error_reduction_count=repeated_error_reduction_count,
        reuse_hits=reuse_hits,
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
    )


def _baseline_record(
    *,
    benchmark_name: str = "phase5-compounding",
    scenario_id: str = "scenario_uniformity",
    project_id: str = "proj_beta",
    time_spent_minutes: float = 18.0,
    obligations_resolved: int = 2,
    false_positives: int = 3,
    review_burden_minutes: float = 4.0,
    stale_automation_count: int = 2,
    repeated_error_reduction_count: int = 0,
    reuse_hits: int = 1,
    accepted_actions: int = 2,
    rejected_actions: int = 2,
) -> object:
    return build_automation_evaluation_record(
        benchmark_name=benchmark_name,
        scenario_id=scenario_id,
        project_id=project_id,
        task_type="theorem_application_checks",
        mode=AutomationEvaluationMode.non_assisted,
        time_spent_minutes=time_spent_minutes,
        obligations_resolved=obligations_resolved,
        false_positives=false_positives,
        review_burden_minutes=review_burden_minutes,
        stale_automation_count=stale_automation_count,
        repeated_error_reduction_count=repeated_error_reduction_count,
        reuse_hits=reuse_hits,
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
    )


def test_automation_evaluation_record_serializes_explicit_metrics() -> None:
    record = _assisted_record()
    reloaded = type(record).model_validate_json(record.model_dump_json())

    assert reloaded == record
    assert record.mode == AutomationEvaluationMode.assisted
    assert record.automation_actions == 4
    assert record.acceptance_rate == pytest.approx(1.0)
    assert record.rejection_rate == pytest.approx(0.0)
    assert record.false_positive_rate == pytest.approx(0.25)
    assert record.stale_automation_rate == pytest.approx(0.0)
    assert record.total_work_units() == 7


def test_automation_evaluation_summary_aggregates_counts_and_rates() -> None:
    records = [
        _assisted_record(),
    _assisted_record(
            project_id="proj_gamma",
            time_spent_minutes=11.0,
            obligations_resolved=2,
            false_positives=0,
            review_burden_minutes=1.0,
            repeated_error_reduction_count=1,
            reuse_hits=2,
            accepted_actions=3,
        ),
        _baseline_record(),
    ]

    summary = aggregate_automation_evaluations(records, notes="aggregate the benchmark set")
    reloaded = type(summary).model_validate_json(summary.model_dump_json())

    assert reloaded == summary
    assert summary.record_count == 3
    assert summary.assisted_count == 2
    assert summary.non_assisted_count == 1
    assert summary.total_time_spent_minutes == pytest.approx(39.0)
    assert summary.average_time_spent_minutes == pytest.approx(13.0)
    assert summary.total_obligations_resolved == 8
    assert summary.total_false_positives == 4
    assert summary.total_review_burden_minutes == pytest.approx(7.0)
    assert summary.total_stale_automation_count == 2
    assert summary.total_repeated_error_reduction_count == 3
    assert summary.total_reuse_hits == 6
    assert summary.total_accepted_actions == 9
    assert summary.total_rejected_actions == 2
    assert summary.total_automation_actions == 11
    assert summary.accepted_action_rate == pytest.approx(9 / 11)
    assert summary.rejected_action_rate == pytest.approx(2 / 11)
    assert summary.stale_automation_rate == pytest.approx(2 / 11)
    assert summary.false_positive_rate == pytest.approx(4 / 11)
    assert summary.repeated_error_reduction_rate == pytest.approx(3 / 11)


def test_automation_benchmark_replay_compares_assisted_and_non_assisted_work() -> None:
    records = [
        _assisted_record(),
        _assisted_record(
            project_id="proj_gamma",
            time_spent_minutes=11.0,
            obligations_resolved=2,
            false_positives=0,
            review_burden_minutes=1.0,
            stale_automation_count=0,
            repeated_error_reduction_count=1,
            reuse_hits=2,
            accepted_actions=3,
        ),
        _baseline_record(),
    ]

    replay = replay_automation_benchmark(records, scenario_id="scenario_uniformity", notes="replay benchmark")
    reloaded = type(replay).model_validate_json(replay.model_dump_json())

    assert reloaded == replay
    assert replay.benchmark_name == "phase5-compounding"
    assert replay.scenario_id == "scenario_uniformity"
    assert replay.project_ids == ["proj_alpha", "proj_gamma", "proj_beta"]
    assert replay.overall_summary.record_count == 3
    assert replay.assisted_summary is not None
    assert replay.non_assisted_summary is not None
    assert replay.comparison is not None
    assert replay.comparison.time_saved_minutes == pytest.approx(7.5)
    assert replay.comparison.false_positive_reduction == 2
    assert replay.comparison.review_burden_reduction_minutes == pytest.approx(1.0)
    assert replay.comparison.stale_automation_reduction == 2
    assert replay.comparison.obligations_resolved_delta == 4
    assert replay.comparison.accepted_actions_delta == 5
    assert replay.comparison.rejected_actions_delta == 2
    assert replay.comparison.overall_interpretation == "assisted_better"


def test_automation_benchmark_replay_supports_empty_runs_and_mode_grouping() -> None:
    replay = replay_automation_benchmark([], scenario_id="scenario_empty")

    assert replay.scenario_id == "scenario_empty"
    assert replay.overall_summary.record_count == 0
    assert replay.comparison is None

    grouped = group_automation_evaluations_by_mode(
        [
            _assisted_record(),
            _baseline_record(),
        ]
    )

    assert set(grouped) == {
        AutomationEvaluationMode.assisted,
        AutomationEvaluationMode.non_assisted,
    }
    assert len(grouped[AutomationEvaluationMode.assisted]) == 1
    assert len(grouped[AutomationEvaluationMode.non_assisted]) == 1


def test_automation_benchmark_replay_rejects_mixed_scenarios_without_a_scenario_id() -> None:
    with pytest.raises(ValueError, match="scenario_id must be provided"):
        replay_automation_benchmark(
            [
                _assisted_record(scenario_id="scenario_one"),
                _baseline_record(scenario_id="scenario_two"),
            ]
        )
