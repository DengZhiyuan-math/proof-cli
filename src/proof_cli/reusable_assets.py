from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .domain import utc_now


class ReusableAssetKind(str, Enum):
    theorem_contract = "theorem_contract"
    imported_reference_contract = "imported_reference_contract"
    proof_pattern = "proof_pattern"
    blocker_pattern = "blocker_pattern"
    repair_strategy = "repair_strategy"
    bug_archetype = "bug_archetype"
    verification_fragment = "verification_fragment"
    method_card = "method_card"
    domain_checklist = "domain_checklist"


class ReusableAssetReuseStatus(str, Enum):
    project_local = "project_local"
    private_experimental = "private_experimental"
    domain_shared = "domain_shared"
    approved_reusable = "approved_reusable"
    rejected = "rejected"
    deprecated = "deprecated"


class ReusableAssetTrustLevel(str, Enum):
    temporary_admit = "temporary_admit"
    project_verified = "project_verified"
    reviewed_reusable = "reviewed_reusable"
    domain_trusted = "domain_trusted"
    foundational = "foundational"


class ReusableAssetPayload(BaseModel):
    statement: str = ""
    assumptions: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    pattern_steps: list[str] = Field(default_factory=list)
    repair_steps: list[str] = Field(default_factory=list)
    bug_signals: list[str] = Field(default_factory=list)
    verification_targets: list[str] = Field(default_factory=list)
    method_steps: list[str] = Field(default_factory=list)
    checklist_items: list[str] = Field(default_factory=list)
    notes: str = ""


class ReusableAssetProvenance(BaseModel):
    origin_project_id: str = ""
    origin_asset_id: str = ""
    source_contract_ids: list[str] = Field(default_factory=list)
    source_reference_ids: list[str] = Field(default_factory=list)
    derived_from_asset_ids: list[str] = Field(default_factory=list)
    linked_blocker_ids: list[str] = Field(default_factory=list)
    linked_repair_ids: list[str] = Field(default_factory=list)
    linked_verification_fragment_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class ReusableAsset(BaseModel):
    id: str
    kind: ReusableAssetKind
    name: str
    summary: str = ""
    team_scope: str = ""
    payload: ReusableAssetPayload = Field(default_factory=ReusableAssetPayload)
    provenance: ReusableAssetProvenance = Field(default_factory=ReusableAssetProvenance)
    reuse_status: ReusableAssetReuseStatus = ReusableAssetReuseStatus.project_local
    trust_level: ReusableAssetTrustLevel = ReusableAssetTrustLevel.temporary_admit
    reviewed_by: str = "human"
    review_notes: str = ""
    reviewed_at: datetime | None = None
    version: int = 1
    supersedes_version: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def is_local(self) -> bool:
        return self.reuse_status == ReusableAssetReuseStatus.project_local

    def is_private(self) -> bool:
        return self.reuse_status == ReusableAssetReuseStatus.private_experimental

    def is_shared(self) -> bool:
        return self.reuse_status == ReusableAssetReuseStatus.domain_shared

    def is_approved(self) -> bool:
        return self.reuse_status == ReusableAssetReuseStatus.approved_reusable

    def is_reusable(self) -> bool:
        return self.reuse_status in {
            ReusableAssetReuseStatus.domain_shared,
            ReusableAssetReuseStatus.approved_reusable,
        }

    def _next_version(self, **changes) -> "ReusableAsset":
        update = dict(changes)
        update["version"] = self.version + 1
        update["supersedes_version"] = self.version
        update["updated_at"] = utc_now()
        return self.model_copy(update=update)

    def move_to_private_experimental(
        self,
        *,
        trust_level: ReusableAssetTrustLevel | None = None,
        reviewer: str = "human",
        notes: str = "",
    ) -> "ReusableAsset":
        return self._next_version(
            reuse_status=ReusableAssetReuseStatus.private_experimental,
            trust_level=trust_level or self.trust_level,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def publish_to_domain_shared(
        self,
        *,
        reviewer: str = "human",
        trust_level: ReusableAssetTrustLevel = ReusableAssetTrustLevel.reviewed_reusable,
        notes: str = "",
    ) -> "ReusableAsset":
        return self._next_version(
            reuse_status=ReusableAssetReuseStatus.domain_shared,
            trust_level=trust_level,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def approve_for_reuse(
        self,
        *,
        reviewer: str = "human",
        trust_level: ReusableAssetTrustLevel = ReusableAssetTrustLevel.domain_trusted,
        notes: str = "",
    ) -> "ReusableAsset":
        return self._next_version(
            reuse_status=ReusableAssetReuseStatus.approved_reusable,
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
    ) -> "ReusableAsset":
        return self._next_version(
            reuse_status=ReusableAssetReuseStatus.rejected,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def deprecate(
        self,
        *,
        reviewer: str = "human",
        notes: str = "",
    ) -> "ReusableAsset":
        return self._next_version(
            reuse_status=ReusableAssetReuseStatus.deprecated,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )
