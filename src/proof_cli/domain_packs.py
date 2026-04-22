from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
import uuid
from typing import Any

from pydantic import BaseModel, Field

from .domain import utc_now


class DomainPackReviewStatus(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    deprecated = "deprecated"


class DomainPackTrustLevel(str, Enum):
    temporary_admit = "temporary_admit"
    reviewed_reusable = "reviewed_reusable"
    domain_trusted = "domain_trusted"


class DomainPackLifecycleStatus(str, Enum):
    draft = "draft"
    installed = "installed"
    upgraded = "upgraded"
    blocked = "blocked"
    rejected = "rejected"


class DomainPackContent(BaseModel):
    theorem_templates: list[str] = Field(default_factory=list)
    method_templates: list[str] = Field(default_factory=list)
    omission_rules: list[str] = Field(default_factory=list)
    bug_patterns: list[str] = Field(default_factory=list)
    formalization_preferences: list[str] = Field(default_factory=list)
    debug_task_templates: list[str] = Field(default_factory=list)
    notation_conventions: list[str] = Field(default_factory=list)
    notes: str = ""


class DomainPackCompatibilityCheck(BaseModel):
    compatible: bool
    version_allowed: bool
    missing_project_tags: list[str] = Field(default_factory=list)
    missing_asset_ids: list[str] = Field(default_factory=list)
    missing_asset_kinds: list[str] = Field(default_factory=list)
    notation_profile_match: bool = True
    reason: str = ""
    notes: str = ""


class DomainPackCompatibility(BaseModel):
    required_project_tags: list[str] = Field(default_factory=list)
    required_asset_ids: list[str] = Field(default_factory=list)
    required_asset_kinds: list[str] = Field(default_factory=list)
    required_notation_profile: str = ""
    allowed_pack_versions: list[str] = Field(default_factory=list)
    notes: str = ""

    def evaluate(
        self,
        *,
        pack_version: str,
        project_id: str = "",
        project_tags: Sequence[str] = (),
        available_asset_ids: Sequence[str] = (),
        available_asset_kinds: Sequence[str] = (),
        notation_profile: str = "",
    ) -> DomainPackCompatibilityCheck:
        project_tags_set = set(project_tags)
        available_asset_ids_set = set(available_asset_ids)
        available_asset_kinds_set = set(available_asset_kinds)

        missing_project_tags = [tag for tag in self.required_project_tags if tag not in project_tags_set]
        missing_asset_ids = [asset_id for asset_id in self.required_asset_ids if asset_id not in available_asset_ids_set]
        missing_asset_kinds = [kind for kind in self.required_asset_kinds if kind not in available_asset_kinds_set]

        version_allowed = not self.allowed_pack_versions or pack_version in self.allowed_pack_versions
        notation_profile_match = not self.required_notation_profile or notation_profile == self.required_notation_profile

        reasons: list[str] = []
        if missing_project_tags:
            reasons.append(f"missing required project tag(s): {', '.join(missing_project_tags)}")
        if missing_asset_ids:
            reasons.append(f"missing required asset id(s): {', '.join(missing_asset_ids)}")
        if missing_asset_kinds:
            reasons.append(f"missing required asset kind(s): {', '.join(missing_asset_kinds)}")
        if not version_allowed:
            reasons.append(
                f"pack version {pack_version} is not in allowed versions: {', '.join(self.allowed_pack_versions)}"
            )
        if not notation_profile_match:
            reasons.append(
                f"notation profile {notation_profile or '<unset>'} does not match required profile {self.required_notation_profile}"
            )
        if project_id:
            reasons.append(f"evaluated for project {project_id}")
        if self.notes:
            reasons.append(self.notes)

        compatible = not (missing_project_tags or missing_asset_ids or missing_asset_kinds) and version_allowed and notation_profile_match
        return DomainPackCompatibilityCheck(
            compatible=compatible,
            version_allowed=version_allowed,
            missing_project_tags=missing_project_tags,
            missing_asset_ids=missing_asset_ids,
            missing_asset_kinds=missing_asset_kinds,
            notation_profile_match=notation_profile_match,
            reason="; ".join(reasons),
            notes=self.notes,
        )


class DomainPackInstallation(BaseModel):
    id: str = Field(default_factory=lambda: f"packinst_{uuid.uuid4().hex[:12]}")
    pack_id: str
    pack_name: str
    pack_version: str
    project_id: str
    status: DomainPackLifecycleStatus = DomainPackLifecycleStatus.installed
    review_status: DomainPackReviewStatus = DomainPackReviewStatus.pending_review
    trust_level: DomainPackTrustLevel = DomainPackTrustLevel.temporary_admit
    compatibility: DomainPackCompatibility
    compatibility_check: DomainPackCompatibilityCheck
    content_snapshot: DomainPackContent
    installed_by: str = "human"
    project_tags: list[str] = Field(default_factory=list)
    available_asset_ids: list[str] = Field(default_factory=list)
    available_asset_kinds: list[str] = Field(default_factory=list)
    notation_profile: str = ""
    source_pack_version: str = ""
    source_pack_review_status: DomainPackReviewStatus = DomainPackReviewStatus.pending_review
    source_pack_trust_level: DomainPackTrustLevel = DomainPackTrustLevel.temporary_admit
    supersedes_installation_id: str | None = None
    notes: str = ""
    installed_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def upgrade_from_pack(
        self,
        pack: "DomainPack",
        *,
        installed_by: str | None = None,
        notes: str = "",
    ) -> "DomainPackInstallation":
        upgraded = pack.install(
            project_id=self.project_id,
            installed_by=installed_by or self.installed_by,
            project_tags=self.project_tags,
            available_asset_ids=self.available_asset_ids,
            available_asset_kinds=self.available_asset_kinds,
            notation_profile=self.notation_profile,
            notes=notes or self.notes,
            supersedes_installation_id=self.id,
        )
        return upgraded.model_copy(
            update={
                "status": DomainPackLifecycleStatus.upgraded,
                "supersedes_installation_id": self.id,
                "updated_at": utc_now(),
            }
        )


class DomainPack(BaseModel):
    id: str
    name: str
    version: str
    summary: str = ""
    content: DomainPackContent = Field(default_factory=DomainPackContent)
    compatibility: DomainPackCompatibility = Field(default_factory=DomainPackCompatibility)
    review_status: DomainPackReviewStatus = DomainPackReviewStatus.pending_review
    trust_level: DomainPackTrustLevel = DomainPackTrustLevel.temporary_admit
    reviewed_by: str = "human"
    review_notes: str = ""
    reviewed_at: datetime | None = None
    origin_project_id: str = ""
    source_asset_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    supersedes_version: str | None = None
    notes: str = ""

    def _transition(self, **updates: Any) -> "DomainPack":
        update = dict(updates)
        update.setdefault("updated_at", utc_now())
        return self.model_copy(update=update)

    def is_installable(self) -> bool:
        return self.review_status == DomainPackReviewStatus.approved

    def approve(
        self,
        *,
        reviewer: str = "human",
        trust_level: DomainPackTrustLevel = DomainPackTrustLevel.reviewed_reusable,
        notes: str = "",
    ) -> "DomainPack":
        return self._transition(
            review_status=DomainPackReviewStatus.approved,
            trust_level=trust_level,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def reject(
        self,
        *,
        reviewer: str = "human",
        notes: str = "",
    ) -> "DomainPack":
        return self._transition(
            review_status=DomainPackReviewStatus.rejected,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def deprecate(
        self,
        *,
        reviewer: str = "human",
        notes: str = "",
    ) -> "DomainPack":
        return self._transition(
            review_status=DomainPackReviewStatus.deprecated,
            reviewed_by=reviewer,
            review_notes=notes,
            reviewed_at=utc_now(),
        )

    def upgrade(
        self,
        *,
        version: str,
        content: DomainPackContent | None = None,
        compatibility: DomainPackCompatibility | None = None,
        review_status: DomainPackReviewStatus | None = None,
        trust_level: DomainPackTrustLevel | None = None,
        reviewer: str | None = None,
        review_notes: str | None = None,
        notes: str = "",
    ) -> "DomainPack":
        update: dict[str, Any] = {
            "version": version,
            "supersedes_version": self.version,
            "content": content or self.content,
            "compatibility": compatibility or self.compatibility,
            "review_status": review_status or self.review_status,
            "trust_level": trust_level or self.trust_level,
            "notes": notes if notes else self.notes,
        }
        if reviewer is not None:
            update["reviewed_by"] = reviewer
        if review_notes is not None:
            update["review_notes"] = review_notes
        if reviewer is not None or review_notes is not None or review_status is not None:
            update["reviewed_at"] = utc_now()
        return self._transition(**update)

    def install(
        self,
        *,
        project_id: str,
        installed_by: str = "human",
        project_tags: Sequence[str] = (),
        available_asset_ids: Sequence[str] = (),
        available_asset_kinds: Sequence[str] = (),
        notation_profile: str = "",
        notes: str = "",
        supersedes_installation_id: str | None = None,
    ) -> DomainPackInstallation:
        if not self.is_installable():
            raise ValueError(
                f"domain pack {self.id} is not approved for installation: {self.review_status.value}"
            )

        compatibility_check = self.compatibility.evaluate(
            pack_version=self.version,
            project_id=project_id,
            project_tags=project_tags,
            available_asset_ids=available_asset_ids,
            available_asset_kinds=available_asset_kinds,
            notation_profile=notation_profile,
        )
        if not compatibility_check.compatible:
            raise ValueError(
                f"domain pack {self.id} is not compatible with project {project_id}: {compatibility_check.reason}"
            )

        return DomainPackInstallation(
            pack_id=self.id,
            pack_name=self.name,
            pack_version=self.version,
            project_id=project_id,
            review_status=self.review_status,
            trust_level=self.trust_level,
            compatibility=self.compatibility.model_copy(deep=True),
            compatibility_check=compatibility_check,
            content_snapshot=self.content.model_copy(deep=True),
            installed_by=installed_by,
            project_tags=list(project_tags),
            available_asset_ids=list(available_asset_ids),
            available_asset_kinds=list(available_asset_kinds),
            notation_profile=notation_profile,
            source_pack_version=self.version,
            source_pack_review_status=self.review_status,
            source_pack_trust_level=self.trust_level,
            supersedes_installation_id=supersedes_installation_id,
            notes=notes or self.notes,
        )
