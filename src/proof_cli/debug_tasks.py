from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field

from .bugs import ProofBugReport, ProofBugSeverity, ProofBugStatus, ProofBugType
from .domain import utc_now
from .evidence import EvidenceChain, EvidenceReviewRecommendation


class ProofDebugTaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ProofDebugTaskStatus(str, Enum):
    pending = "pending"
    triaged = "triaged"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    dismissed = "dismissed"


class ProofDebugTaskType(str, Enum):
    counterexample_search = "counterexample_search"
    boundary_check = "boundary_check"
    weakened_conclusion_review = "weakened_conclusion_review"
    missing_lemma_isolation = "missing_lemma_isolation"
    assumption_audit = "assumption_audit"
    export_grounding_review = "export_grounding_review"
    omission_gap_investigation = "omission_gap_investigation"
    dependency_cycle_break = "dependency_cycle_break"
    notation_alignment_review = "notation_alignment_review"
    evidence_reconciliation = "evidence_reconciliation"


class ProofDebugTaskTemplate(BaseModel):
    bug_type: ProofBugType
    task_type: ProofDebugTaskType
    title: str
    description: str
    candidate_repairs: list[str] = Field(default_factory=list)
    default_priority: ProofDebugTaskPriority = ProofDebugTaskPriority.medium


class ProofDebugTask(BaseModel):
    id: str = Field(default_factory=lambda: f"dbg_{uuid.uuid4().hex[:12]}")
    bug_report_id: str
    bug_type: str
    bug_status: ProofBugStatus
    task_type: ProofDebugTaskType
    title: str
    description: str
    priority: ProofDebugTaskPriority
    status: ProofDebugTaskStatus = ProofDebugTaskStatus.pending
    evidence_chain_id: str | None = None
    review_recommendation: EvidenceReviewRecommendation | None = None
    linked_contract_ids: list[str] = Field(default_factory=list)
    linked_obligation_ids: list[str] = Field(default_factory=list)
    linked_blocker_ids: list[str] = Field(default_factory=list)
    reasoning_path: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    candidate_repairs: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProofDebugTaskBatch(BaseModel):
    theorem_id: str | None = None
    tasks: list[ProofDebugTask] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def task_ids(self) -> list[str]:
        return [task.id for task in self.tasks]

    def priorities(self) -> list[str]:
        return [task.priority.value for task in self.tasks]


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _priority_for_report(report: ProofBugReport, template_priority: ProofDebugTaskPriority) -> ProofDebugTaskPriority:
    if report.status not in {ProofBugStatus.suspected, ProofBugStatus.under_review}:
        return ProofDebugTaskPriority.low
    severity_priority = {
        ProofBugSeverity.low: ProofDebugTaskPriority.low,
        ProofBugSeverity.medium: ProofDebugTaskPriority.medium,
        ProofBugSeverity.high: ProofDebugTaskPriority.high,
        ProofBugSeverity.critical: ProofDebugTaskPriority.critical,
    }[report.severity]
    return max(template_priority, severity_priority, key=_priority_rank)


def _priority_rank(priority: ProofDebugTaskPriority) -> int:
    return {
        ProofDebugTaskPriority.low: 0,
        ProofDebugTaskPriority.medium: 1,
        ProofDebugTaskPriority.high: 2,
        ProofDebugTaskPriority.critical: 3,
    }[priority]


def _templates_for_report(report: ProofBugReport) -> list[ProofDebugTaskTemplate]:
    if report.bug_type == ProofBugType.assumption_mismatch:
        return [
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.assumption_audit,
                title="Audit missing assumptions",
                description="Check the theorem contract and downstream use for any assumptions that are implied but not explicitly recorded.",
                candidate_repairs=[
                    "add the missing assumption to the contract",
                    "split the theorem into a weaker claim with explicit premises",
                ],
                default_priority=ProofDebugTaskPriority.high,
            ),
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.boundary_check,
                title="Check boundary cases for the missing assumptions",
                description="Look for inputs or subgoals that fail exactly at the missing assumption boundary.",
                candidate_repairs=[
                    "add a boundary lemma",
                    "restrict the theorem statement to the safe domain",
                ],
                default_priority=ProofDebugTaskPriority.medium,
            ),
        ]
    if report.bug_type == ProofBugType.export_overstretch:
        return [
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.export_grounding_review,
                title="Review export grounding",
                description="Verify whether the claimed exports are actually supported by grounded references or local proof steps.",
                candidate_repairs=[
                    "weaken the exported conclusion",
                    "attach the export to a grounded theorem or reference",
                ],
                default_priority=ProofDebugTaskPriority.high,
            ),
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.weakened_conclusion_review,
                title="Test a weakened conclusion",
                description="See whether a weaker conclusion is provable with the current evidence chain.",
                candidate_repairs=[
                    "replace the export with a narrower theorem statement",
                    "move the stronger claim behind an additional lemma",
                ],
                default_priority=ProofDebugTaskPriority.medium,
            ),
        ]
    if report.bug_type == ProofBugType.omitted_side_condition:
        return [
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.omission_gap_investigation,
                title="Investigate the omitted side condition",
                description="Locate the exact proof step where the omitted condition is needed and make it explicit.",
                candidate_repairs=[
                    "add the missing side condition to the proof state",
                    "isolate the step into a separate lemma",
                ],
                default_priority=ProofDebugTaskPriority.high,
            ),
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.missing_lemma_isolation,
                title="Isolate the missing lemma",
                description="Split the reasoning so the missing condition becomes a named obligation instead of an implicit gap.",
                candidate_repairs=[
                    "introduce a supporting lemma for the omitted step",
                    "make the obligation explicit before reuse",
                ],
                default_priority=ProofDebugTaskPriority.high,
            ),
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.counterexample_search,
                title="Search for a counterexample at the omission boundary",
                description="Try to break the proof at the omitted-condition boundary to confirm the gap is real.",
                candidate_repairs=[
                    "narrow the theorem scope",
                    "add the missing hypothesis before continuing",
                ],
                default_priority=ProofDebugTaskPriority.medium,
            ),
        ]
    if report.bug_type == ProofBugType.circular_dependency:
        return [
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.dependency_cycle_break,
                title="Break the dependency cycle",
                description="Trace the cycle and mark the first dependency that must become a lemma, import, or assumption instead of a recursive use.",
                candidate_repairs=[
                    "extract a non-circular helper lemma",
                    "replace the recursive dependency with a grounded result",
                ],
                default_priority=ProofDebugTaskPriority.critical,
            ),
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.missing_lemma_isolation,
                title="Isolate the missing acyclic lemma",
                description="Split the cycle into a new lemma so the main theorem no longer depends on itself indirectly.",
                candidate_repairs=[
                    "introduce an acyclic bridge lemma",
                    "move the shared reasoning into a lower-level contract",
                ],
                default_priority=ProofDebugTaskPriority.high,
            ),
        ]
    if report.bug_type == ProofBugType.notation_drift:
        return [
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.notation_alignment_review,
                title="Align notation with the tracked context",
                description="Compare the theorem statement against tracked symbols and definitions to find the drift source.",
                candidate_repairs=[
                    "rename the untracked symbol to a tracked one",
                    "add the missing symbol to the local context",
                ],
                default_priority=ProofDebugTaskPriority.medium,
            ),
            ProofDebugTaskTemplate(
                bug_type=report.bug_type,
                task_type=ProofDebugTaskType.evidence_reconciliation,
                title="Reconcile the evidence trail",
                description="Check whether the proof evidence uses a symbol or definition that never entered the local proof state.",
                candidate_repairs=[
                    "refresh the proof state before reuse",
                    "add the missing definition as a prerequisite",
                ],
                default_priority=ProofDebugTaskPriority.low,
            ),
        ]
    return [
        ProofDebugTaskTemplate(
            bug_type=report.bug_type,
            task_type=ProofDebugTaskType.evidence_reconciliation,
            title="Review the proof evidence",
            description="Inspect the suspicion trace and identify the next concrete repair-oriented follow-up.",
            candidate_repairs=[
                "collect additional evidence",
                "turn the suspicion into a named proof obligation",
            ],
            default_priority=ProofDebugTaskPriority.medium,
        )
    ]


def _task_from_template(
    report: ProofBugReport,
    template: ProofDebugTaskTemplate,
    *,
    evidence_chain: EvidenceChain | None = None,
) -> ProofDebugTask:
    priority = _priority_for_report(report, template.default_priority)
    return ProofDebugTask(
        bug_report_id=report.id,
        bug_type=report.bug_type.value,
        bug_status=report.status,
        task_type=template.task_type,
        title=template.title,
        description=template.description,
        priority=priority,
        status=ProofDebugTaskStatus.pending if report.status == ProofBugStatus.suspected else ProofDebugTaskStatus.triaged,
        evidence_chain_id=evidence_chain.id if evidence_chain is not None else None,
        review_recommendation=evidence_chain.review_recommendation if evidence_chain is not None else None,
        linked_contract_ids=_unique(report.linked_contract_ids),
        linked_obligation_ids=_unique(report.linked_obligation_ids),
        linked_blocker_ids=_unique(report.linked_blocker_ids),
        reasoning_path=_unique((evidence_chain.reasoning_path if evidence_chain is not None else report.reasoning_path) or [report.id]),
        missing_conditions=_unique((evidence_chain.missing_conditions if evidence_chain is not None else report.missing_conditions)),
        candidate_repairs=list(template.candidate_repairs),
        evidence=_unique((evidence_chain.evidence if evidence_chain is not None else report.evidence)),
    )


def generate_debug_tasks(
    reports: Iterable[ProofBugReport],
    evidence_chains: Iterable[EvidenceChain] | None = None,
) -> list[ProofDebugTask]:
    chain_by_report_id = {chain.bug_report_id: chain for chain in evidence_chains or []}
    tasks: list[ProofDebugTask] = []
    for report in reports:
        if report.status not in {ProofBugStatus.suspected, ProofBugStatus.under_review}:
            continue
        chain = chain_by_report_id.get(report.id)
        templates = _templates_for_report(report)
        for template in templates:
            tasks.append(_task_from_template(report, template, evidence_chain=chain))
    tasks.sort(key=lambda task: -_priority_rank(task.priority))
    return tasks


def debug_task_batch_from_reports(
    reports: Iterable[ProofBugReport],
    evidence_chains: Iterable[EvidenceChain] | None = None,
    *,
    theorem_id: str | None = None,
) -> ProofDebugTaskBatch:
    return ProofDebugTaskBatch(
        theorem_id=theorem_id,
        tasks=generate_debug_tasks(reports, evidence_chains=evidence_chains),
    )


def debug_tasks_to_json(tasks: Iterable[ProofDebugTask]) -> str:
    return ProofDebugTaskBatch(tasks=list(tasks)).model_dump_json(indent=2)


__all__ = [
    "ProofDebugTask",
    "ProofDebugTaskBatch",
    "ProofDebugTaskPriority",
    "ProofDebugTaskStatus",
    "ProofDebugTaskTemplate",
    "ProofDebugTaskType",
    "debug_task_batch_from_reports",
    "debug_tasks_to_json",
    "generate_debug_tasks",
]
