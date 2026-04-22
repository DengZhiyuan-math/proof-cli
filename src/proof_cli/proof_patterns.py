from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from .domain import utc_now
from .reusable_assets import (
    ReusableAsset,
    ReusableAssetKind,
    ReusableAssetPayload,
    ReusableAssetProvenance,
    ReusableAssetReuseStatus,
    ReusableAssetTrustLevel,
)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


class ProofPatternKind(str, Enum):
    proof_decomposition = "proof_decomposition"
    theorem_application = "theorem_application"
    dangerous_omission = "dangerous_omission"
    blocker_repair_pair = "blocker_repair_pair"
    formalization_recommendation = "formalization_recommendation"
    debug_workflow = "debug_workflow"


class ProofPatternReuseStatus(str, Enum):
    project_local = "project_local"
    private_experimental = "private_experimental"
    domain_shared = "domain_shared"
    approved_reusable = "approved_reusable"
    rejected = "rejected"
    deprecated = "deprecated"


class ProofPatternTrustLevel(str, Enum):
    temporary_admit = "temporary_admit"
    project_verified = "project_verified"
    reviewed_reusable = "reviewed_reusable"
    domain_trusted = "domain_trusted"
    foundational = "foundational"


class ProofPatternProvenance(BaseModel):
    origin_project_id: str = ""
    origin_pattern_id: str = ""
    source_contract_ids: list[str] = Field(default_factory=list)
    source_reference_ids: list[str] = Field(default_factory=list)
    linked_blocker_ids: list[str] = Field(default_factory=list)
    linked_repair_ids: list[str] = Field(default_factory=list)
    linked_verification_fragment_ids: list[str] = Field(default_factory=list)
    derived_from_pattern_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class ProofPatternPayload(BaseModel):
    decomposition_steps: list[str] = Field(default_factory=list)
    theorem_application_steps: list[str] = Field(default_factory=list)
    omission_signals: list[str] = Field(default_factory=list)
    blocker_signals: list[str] = Field(default_factory=list)
    repair_steps: list[str] = Field(default_factory=list)
    formalization_steps: list[str] = Field(default_factory=list)
    debug_steps: list[str] = Field(default_factory=list)
    notes: str = ""


class PatternLifecycleBase(BaseModel):
    id: str
    name: str
    summary: str = ""
    provenance: ProofPatternProvenance = Field(default_factory=ProofPatternProvenance)
    reuse_status: ProofPatternReuseStatus = ProofPatternReuseStatus.project_local
    trust_level: ProofPatternTrustLevel = ProofPatternTrustLevel.temporary_admit
    reviewed_by: str = "human"
    review_notes: str = ""
    reviewed_at: datetime | None = None
    version: int = 1
    supersedes_version: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def _next_version(self, **changes) -> "PatternLifecycleBase":
        update = dict(changes)
        update["version"] = self.version + 1
        update["supersedes_version"] = self.version
        update["updated_at"] = utc_now()
        return self.model_copy(update=update)

    def is_local(self) -> bool:
        return self.reuse_status == ProofPatternReuseStatus.project_local

    def is_private(self) -> bool:
        return self.reuse_status == ProofPatternReuseStatus.private_experimental

    def is_shared(self) -> bool:
        return self.reuse_status == ProofPatternReuseStatus.domain_shared

    def is_approved(self) -> bool:
        return self.reuse_status == ProofPatternReuseStatus.approved_reusable

    def is_reusable(self) -> bool:
        return self.reuse_status in {
            ProofPatternReuseStatus.domain_shared,
            ProofPatternReuseStatus.approved_reusable,
        }

    def move_to_private_experimental(
        self,
        *,
        trust_level: ProofPatternTrustLevel | None = None,
        reviewer: str = "human",
        notes: str = "",
    ) -> "PatternLifecycleBase":
        return self._next_version(
            reuse_status=ProofPatternReuseStatus.private_experimental,
            trust_level=trust_level or self.trust_level,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def publish_to_domain_shared(
        self,
        *,
        reviewer: str = "human",
        trust_level: ProofPatternTrustLevel = ProofPatternTrustLevel.reviewed_reusable,
        notes: str = "",
    ) -> "PatternLifecycleBase":
        return self._next_version(
            reuse_status=ProofPatternReuseStatus.domain_shared,
            trust_level=trust_level,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def approve_for_reuse(
        self,
        *,
        reviewer: str = "human",
        trust_level: ProofPatternTrustLevel = ProofPatternTrustLevel.domain_trusted,
        notes: str = "",
    ) -> "PatternLifecycleBase":
        return self._next_version(
            reuse_status=ProofPatternReuseStatus.approved_reusable,
            trust_level=trust_level,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def reject_reuse(
        self,
        *,
        reviewer: str = "human",
        notes: str = "",
    ) -> "PatternLifecycleBase":
        return self._next_version(
            reuse_status=ProofPatternReuseStatus.rejected,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def deprecate(
        self,
        *,
        reviewer: str = "human",
        notes: str = "",
    ) -> "PatternLifecycleBase":
        return self._next_version(
            reuse_status=ProofPatternReuseStatus.deprecated,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def reuse_for_project(
        self,
        *,
        project_id: str,
        reviewer: str = "human",
        notes: str = "",
        linked_contract_ids: list[str] | None = None,
        linked_blocker_ids: list[str] | None = None,
        linked_repair_ids: list[str] | None = None,
    ) -> "PatternLifecycleBase":
        provenance = self.provenance.model_copy(
            update={
                "origin_project_id": self.provenance.origin_project_id or project_id,
                "derived_from_pattern_ids": _unique([*self.provenance.derived_from_pattern_ids, self.id]),
                "source_contract_ids": _unique([*self.provenance.source_contract_ids, *(linked_contract_ids or [])]),
                "linked_blocker_ids": _unique([*self.provenance.linked_blocker_ids, *(linked_blocker_ids or [])]),
                "linked_repair_ids": _unique([*self.provenance.linked_repair_ids, *(linked_repair_ids or [])]),
                "notes": notes or self.provenance.notes,
            }
        )
        return self._next_version(
            provenance=provenance,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )


class BlockerRepairPair(PatternLifecycleBase):
    kind: Literal["blocker_repair_pair"] = "blocker_repair_pair"
    blocker_id: str
    blocker_summary: str = ""
    repair_strategy: str = ""
    repair_steps: list[str] = Field(default_factory=list)
    linked_pattern_ids: list[str] = Field(default_factory=list)
    linked_contract_ids: list[str] = Field(default_factory=list)
    linked_verification_fragment_ids: list[str] = Field(default_factory=list)
    notes: str = ""

    def to_reusable_asset(self) -> ReusableAsset:
        return ReusableAsset(
            id=self.id,
            kind=ReusableAssetKind.blocker_pattern,
            name=self.name,
            summary=self.summary or self.blocker_summary,
            payload=ReusableAssetPayload(
                pattern_steps=self.repair_steps,
                repair_steps=self.repair_steps,
                notes=self.notes or self.review_notes or self.repair_strategy,
            ),
            provenance=ReusableAssetProvenance(
                origin_project_id=self.provenance.origin_project_id,
                origin_asset_id=self.provenance.origin_pattern_id,
                source_contract_ids=_unique([*self.provenance.source_contract_ids, *self.linked_contract_ids]),
                source_reference_ids=self.provenance.source_reference_ids,
                derived_from_asset_ids=self.provenance.derived_from_pattern_ids,
                linked_blocker_ids=_unique([*self.provenance.linked_blocker_ids, self.blocker_id]),
                linked_repair_ids=_unique([*self.provenance.linked_repair_ids, self.id]),
                linked_verification_fragment_ids=_unique(
                    [*self.provenance.linked_verification_fragment_ids, *self.linked_verification_fragment_ids]
                ),
                notes=self.provenance.notes or self.notes,
            ),
            reuse_status=ReusableAssetReuseStatus(self.reuse_status.value),
            trust_level=ReusableAssetTrustLevel(self.trust_level.value),
            reviewed_by=self.reviewed_by,
            review_notes=self.review_notes,
            reviewed_at=self.reviewed_at,
            version=self.version,
            supersedes_version=self.supersedes_version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ProofPattern(PatternLifecycleBase):
    kind: ProofPatternKind
    payload: ProofPatternPayload = Field(default_factory=ProofPatternPayload)
    blocker_repair_pairs: list[BlockerRepairPair] = Field(default_factory=list)

    def to_reusable_asset(self) -> ReusableAsset:
        linked_blocker_ids = _unique(
            [
                *self.provenance.linked_blocker_ids,
                *(pair.blocker_id for pair in self.blocker_repair_pairs),
            ]
        )
        linked_repair_ids = _unique(
            [
                *self.provenance.linked_repair_ids,
                *(pair.id for pair in self.blocker_repair_pairs),
            ]
        )
        repair_steps = [
            *self.payload.repair_steps,
            *(step for pair in self.blocker_repair_pairs for step in pair.repair_steps),
        ]
        pattern_steps = [
            *self.payload.decomposition_steps,
            *self.payload.theorem_application_steps,
            *self.payload.debug_steps,
        ]
        asset_kind = ReusableAssetKind.proof_pattern
        if self.kind == ProofPatternKind.blocker_repair_pair:
            asset_kind = ReusableAssetKind.blocker_pattern
        elif self.kind == ProofPatternKind.dangerous_omission:
            asset_kind = ReusableAssetKind.bug_archetype
        elif self.kind == ProofPatternKind.formalization_recommendation:
            asset_kind = ReusableAssetKind.method_card

        return ReusableAsset(
            id=self.id,
            kind=asset_kind,
            name=self.name,
            summary=self.summary,
            payload=ReusableAssetPayload(
                statement=self.summary,
                assumptions=[],
                exports=[],
                pattern_steps=pattern_steps,
                repair_steps=repair_steps,
                bug_signals=[*self.payload.omission_signals, *self.payload.blocker_signals],
                verification_targets=self.payload.formalization_steps,
                method_steps=self.payload.theorem_application_steps,
                checklist_items=self.payload.debug_steps,
                notes=self.payload.notes,
            ),
            provenance=ReusableAssetProvenance(
                origin_project_id=self.provenance.origin_project_id,
                origin_asset_id=self.provenance.origin_pattern_id,
                source_contract_ids=self.provenance.source_contract_ids,
                source_reference_ids=self.provenance.source_reference_ids,
                derived_from_asset_ids=self.provenance.derived_from_pattern_ids,
                linked_blocker_ids=linked_blocker_ids,
                linked_repair_ids=linked_repair_ids,
                linked_verification_fragment_ids=self.provenance.linked_verification_fragment_ids,
                notes=self.provenance.notes,
            ),
            reuse_status=ReusableAssetReuseStatus(self.reuse_status.value),
            trust_level=ReusableAssetTrustLevel(self.trust_level.value),
            reviewed_by=self.reviewed_by,
            review_notes=self.review_notes,
            reviewed_at=self.reviewed_at,
            version=self.version,
            supersedes_version=self.supersedes_version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_reusable_asset(
        cls,
        asset: ReusableAsset,
        *,
        kind: ProofPatternKind = ProofPatternKind.proof_decomposition,
        blocker_repair_pairs: list[BlockerRepairPair] | None = None,
    ) -> "ProofPattern":
        return cls(
            id=asset.id,
            kind=kind,
            name=asset.name,
            summary=asset.summary,
            payload=ProofPatternPayload(
                decomposition_steps=list(asset.payload.pattern_steps),
                theorem_application_steps=list(asset.payload.method_steps),
                omission_signals=list(asset.payload.bug_signals),
                blocker_signals=list(asset.payload.bug_signals),
                repair_steps=list(asset.payload.repair_steps),
                formalization_steps=list(asset.payload.verification_targets),
                debug_steps=list(asset.payload.checklist_items),
                notes=asset.payload.notes,
            ),
            blocker_repair_pairs=list(blocker_repair_pairs or []),
            provenance=ProofPatternProvenance(
                origin_project_id=asset.provenance.origin_project_id,
                origin_pattern_id=asset.provenance.origin_asset_id,
                source_contract_ids=list(asset.provenance.source_contract_ids),
                source_reference_ids=list(asset.provenance.source_reference_ids),
                linked_blocker_ids=list(asset.provenance.linked_blocker_ids),
                linked_repair_ids=list(asset.provenance.linked_repair_ids),
                linked_verification_fragment_ids=list(asset.provenance.linked_verification_fragment_ids),
                derived_from_pattern_ids=list(asset.provenance.derived_from_asset_ids),
                notes=asset.provenance.notes,
            ),
            reuse_status=ProofPatternReuseStatus(asset.reuse_status.value),
            trust_level=ProofPatternTrustLevel(asset.trust_level.value),
            reviewed_by=asset.reviewed_by,
            review_notes=asset.review_notes,
            reviewed_at=asset.reviewed_at,
            version=asset.version,
            supersedes_version=asset.supersedes_version,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
        )

