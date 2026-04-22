from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Literal
import uuid

from pydantic import BaseModel, Field

from .domain import utc_now


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


class AutomationEvaluationMode(str, Enum):
    assisted = "assisted"
    non_assisted = "non_assisted"


class AutomationEvaluationRecord(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("eval"))
    benchmark_name: str
    scenario_id: str
    project_id: str
    task_type: str
    mode: AutomationEvaluationMode
    time_spent_minutes: float = Field(ge=0.0)
    obligations_resolved: int = Field(default=0, ge=0)
    false_positives: int = Field(default=0, ge=0)
    review_burden_minutes: float = Field(default=0.0, ge=0.0)
    stale_automation_count: int = Field(default=0, ge=0)
    repeated_error_reduction_count: int = Field(default=0, ge=0)
    reuse_hits: int = Field(default=0, ge=0)
    accepted_actions: int = Field(default=0, ge=0)
    rejected_actions: int = Field(default=0, ge=0)
    automation_actions: int = Field(default=0, ge=0)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def model_post_init(self, __context: object) -> None:
        if self.automation_actions == 0:
            object.__setattr__(self, "automation_actions", self.accepted_actions + self.rejected_actions)
        if self.automation_actions < self.accepted_actions + self.rejected_actions:
            raise ValueError("automation_actions cannot be smaller than accepted_actions + rejected_actions")

    @property
    def acceptance_rate(self) -> float:
        return _safe_divide(self.accepted_actions, self.automation_actions)

    @property
    def rejection_rate(self) -> float:
        return _safe_divide(self.rejected_actions, self.automation_actions)

    @property
    def stale_automation_rate(self) -> float:
        return _safe_divide(self.stale_automation_count, self.automation_actions)

    @property
    def false_positive_rate(self) -> float:
        return _safe_divide(self.false_positives, self.automation_actions)

    def total_work_units(self) -> int:
        return self.obligations_resolved + self.false_positives + self.repeated_error_reduction_count


class AutomationEvaluationSummary(BaseModel):
    record_count: int
    assisted_count: int
    non_assisted_count: int
    total_time_spent_minutes: float
    average_time_spent_minutes: float
    total_obligations_resolved: int
    total_false_positives: int
    total_review_burden_minutes: float
    total_stale_automation_count: int
    total_repeated_error_reduction_count: int
    total_reuse_hits: int
    total_accepted_actions: int
    total_rejected_actions: int
    total_automation_actions: int
    accepted_action_rate: float
    rejected_action_rate: float
    stale_automation_rate: float
    false_positive_rate: float
    repeated_error_reduction_rate: float
    notes: str = ""


class AutomationBenchmarkComparison(BaseModel):
    assisted_summary: AutomationEvaluationSummary
    non_assisted_summary: AutomationEvaluationSummary
    time_saved_minutes: float
    obligations_resolved_delta: int
    false_positive_reduction: int
    review_burden_reduction_minutes: float
    stale_automation_reduction: int
    repeated_error_reduction_delta: int
    reuse_frequency_delta: int
    accepted_actions_delta: int
    rejected_actions_delta: int
    overall_interpretation: Literal["assisted_better", "non_assisted_better", "mixed", "insufficient_data"] = "insufficient_data"
    notes: str = ""


class AutomationBenchmarkReplay(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("bench"))
    benchmark_name: str
    scenario_id: str
    project_ids: list[str] = Field(default_factory=list)
    records: list[AutomationEvaluationRecord] = Field(default_factory=list)
    overall_summary: AutomationEvaluationSummary
    assisted_summary: AutomationEvaluationSummary | None = None
    non_assisted_summary: AutomationEvaluationSummary | None = None
    comparison: AutomationBenchmarkComparison | None = None
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


def build_automation_evaluation_record(
    *,
    benchmark_name: str,
    scenario_id: str,
    project_id: str,
    task_type: str,
    mode: AutomationEvaluationMode,
    time_spent_minutes: float,
    obligations_resolved: int = 0,
    false_positives: int = 0,
    review_burden_minutes: float = 0.0,
    stale_automation_count: int = 0,
    repeated_error_reduction_count: int = 0,
    reuse_hits: int = 0,
    accepted_actions: int = 0,
    rejected_actions: int = 0,
    automation_actions: int | None = None,
    notes: str = "",
    tags: list[str] | None = None,
) -> AutomationEvaluationRecord:
    return AutomationEvaluationRecord(
        benchmark_name=benchmark_name,
        scenario_id=scenario_id,
        project_id=project_id,
        task_type=task_type,
        mode=mode,
        time_spent_minutes=time_spent_minutes,
        obligations_resolved=obligations_resolved,
        false_positives=false_positives,
        review_burden_minutes=review_burden_minutes,
        stale_automation_count=stale_automation_count,
        repeated_error_reduction_count=repeated_error_reduction_count,
        reuse_hits=reuse_hits,
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
        automation_actions=automation_actions or 0,
        notes=notes,
        tags=list(tags or []),
    )


def aggregate_automation_evaluations(
    records: list[AutomationEvaluationRecord],
    *,
    notes: str = "",
) -> AutomationEvaluationSummary:
    record_count = len(records)
    assisted_count = sum(1 for record in records if record.mode == AutomationEvaluationMode.assisted)
    non_assisted_count = record_count - assisted_count
    total_time_spent_minutes = sum(record.time_spent_minutes for record in records)
    total_obligations_resolved = sum(record.obligations_resolved for record in records)
    total_false_positives = sum(record.false_positives for record in records)
    total_review_burden_minutes = sum(record.review_burden_minutes for record in records)
    total_stale_automation_count = sum(record.stale_automation_count for record in records)
    total_repeated_error_reduction_count = sum(record.repeated_error_reduction_count for record in records)
    total_reuse_hits = sum(record.reuse_hits for record in records)
    total_accepted_actions = sum(record.accepted_actions for record in records)
    total_rejected_actions = sum(record.rejected_actions for record in records)
    total_automation_actions = sum(record.automation_actions for record in records)

    average_time_spent_minutes = _safe_divide(total_time_spent_minutes, record_count)
    accepted_action_rate = _safe_divide(total_accepted_actions, total_automation_actions)
    rejected_action_rate = _safe_divide(total_rejected_actions, total_automation_actions)
    stale_automation_rate = _safe_divide(total_stale_automation_count, total_automation_actions)
    false_positive_rate = _safe_divide(total_false_positives, total_automation_actions)
    repeated_error_reduction_rate = _safe_divide(total_repeated_error_reduction_count, total_automation_actions)

    return AutomationEvaluationSummary(
        record_count=record_count,
        assisted_count=assisted_count,
        non_assisted_count=non_assisted_count,
        total_time_spent_minutes=total_time_spent_minutes,
        average_time_spent_minutes=average_time_spent_minutes,
        total_obligations_resolved=total_obligations_resolved,
        total_false_positives=total_false_positives,
        total_review_burden_minutes=total_review_burden_minutes,
        total_stale_automation_count=total_stale_automation_count,
        total_repeated_error_reduction_count=total_repeated_error_reduction_count,
        total_reuse_hits=total_reuse_hits,
        total_accepted_actions=total_accepted_actions,
        total_rejected_actions=total_rejected_actions,
        total_automation_actions=total_automation_actions,
        accepted_action_rate=accepted_action_rate,
        rejected_action_rate=rejected_action_rate,
        stale_automation_rate=stale_automation_rate,
        false_positive_rate=false_positive_rate,
        repeated_error_reduction_rate=repeated_error_reduction_rate,
        notes=notes,
    )


def _mode_summary(records: list[AutomationEvaluationRecord], mode: AutomationEvaluationMode) -> AutomationEvaluationSummary | None:
    filtered = [record for record in records if record.mode == mode]
    if not filtered:
        return None
    return aggregate_automation_evaluations(filtered, notes=f"{mode.value} benchmark subset")


def _interpret_comparison(comparison: AutomationBenchmarkComparison) -> Literal["assisted_better", "non_assisted_better", "mixed", "insufficient_data"]:
    positive = 0
    negative = 0
    signals = [
        comparison.time_saved_minutes,
        comparison.false_positive_reduction,
        comparison.review_burden_reduction_minutes,
        comparison.stale_automation_reduction,
        comparison.obligations_resolved_delta,
        comparison.repeated_error_reduction_delta,
        comparison.reuse_frequency_delta,
        comparison.accepted_actions_delta,
        comparison.rejected_actions_delta,
    ]
    for value in signals:
        if value > 0:
            positive += 1
        elif value < 0:
            negative += 1

    if positive == 0 and negative == 0:
        return "insufficient_data"
    if positive >= 5 and negative <= 2:
        return "assisted_better"
    if negative >= 5 and positive <= 2:
        return "non_assisted_better"
    return "mixed"


def compare_automation_evaluations(
    assisted_summary: AutomationEvaluationSummary,
    non_assisted_summary: AutomationEvaluationSummary,
) -> AutomationBenchmarkComparison:
    comparison = AutomationBenchmarkComparison(
        assisted_summary=assisted_summary,
        non_assisted_summary=non_assisted_summary,
        time_saved_minutes=non_assisted_summary.average_time_spent_minutes - assisted_summary.average_time_spent_minutes,
        obligations_resolved_delta=assisted_summary.total_obligations_resolved - non_assisted_summary.total_obligations_resolved,
        false_positive_reduction=non_assisted_summary.total_false_positives - assisted_summary.total_false_positives,
        review_burden_reduction_minutes=non_assisted_summary.total_review_burden_minutes - assisted_summary.total_review_burden_minutes,
        stale_automation_reduction=non_assisted_summary.total_stale_automation_count - assisted_summary.total_stale_automation_count,
        repeated_error_reduction_delta=(
            assisted_summary.total_repeated_error_reduction_count
            - non_assisted_summary.total_repeated_error_reduction_count
        ),
        reuse_frequency_delta=assisted_summary.total_reuse_hits - non_assisted_summary.total_reuse_hits,
        accepted_actions_delta=assisted_summary.total_accepted_actions - non_assisted_summary.total_accepted_actions,
        rejected_actions_delta=non_assisted_summary.total_rejected_actions - assisted_summary.total_rejected_actions,
    )
    return comparison.model_copy(update={"overall_interpretation": _interpret_comparison(comparison)})


def replay_automation_benchmark(
    records: list[AutomationEvaluationRecord],
    *,
    benchmark_name: str | None = None,
    scenario_id: str | None = None,
    notes: str = "",
) -> AutomationBenchmarkReplay:
    if not records:
        if scenario_id is None:
            raise ValueError("scenario_id is required when replaying an empty benchmark")
        overall_summary = aggregate_automation_evaluations([], notes="empty benchmark replay")
        return AutomationBenchmarkReplay(
            benchmark_name=benchmark_name or scenario_id,
            scenario_id=scenario_id,
            records=[],
            overall_summary=overall_summary,
            notes=notes,
        )

    scenario_values = {record.scenario_id for record in records}
    if scenario_id is None:
        if len(scenario_values) != 1:
            raise ValueError("scenario_id must be provided when records span multiple scenarios")
        scenario_id = next(iter(scenario_values))
    elif any(record.scenario_id != scenario_id for record in records):
        raise ValueError("all records must match the requested scenario_id")

    benchmark_name = benchmark_name or records[0].benchmark_name or scenario_id
    overall_summary = aggregate_automation_evaluations(records, notes=f"benchmark replay for {benchmark_name}")
    assisted_summary = _mode_summary(records, AutomationEvaluationMode.assisted)
    non_assisted_summary = _mode_summary(records, AutomationEvaluationMode.non_assisted)
    comparison = None
    if assisted_summary is not None and non_assisted_summary is not None:
        comparison = compare_automation_evaluations(assisted_summary, non_assisted_summary)

    project_ids = []
    for record in records:
        if record.project_id not in project_ids:
            project_ids.append(record.project_id)

    return AutomationBenchmarkReplay(
        benchmark_name=benchmark_name,
        scenario_id=scenario_id,
        project_ids=project_ids,
        records=sorted(records, key=lambda record: (record.created_at, record.id)),
        overall_summary=overall_summary,
        assisted_summary=assisted_summary,
        non_assisted_summary=non_assisted_summary,
        comparison=comparison,
        notes=notes,
    )


def group_automation_evaluations_by_mode(
    records: list[AutomationEvaluationRecord],
) -> dict[AutomationEvaluationMode, list[AutomationEvaluationRecord]]:
    grouped: dict[AutomationEvaluationMode, list[AutomationEvaluationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.mode].append(record)
    return dict(grouped)


__all__ = [
    "AutomationBenchmarkComparison",
    "AutomationBenchmarkReplay",
    "AutomationEvaluationMode",
    "AutomationEvaluationRecord",
    "AutomationEvaluationSummary",
    "aggregate_automation_evaluations",
    "build_automation_evaluation_record",
    "compare_automation_evaluations",
    "group_automation_evaluations_by_mode",
    "replay_automation_benchmark",
]
