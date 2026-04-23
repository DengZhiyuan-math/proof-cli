from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .collaboration import CollaborationState, load_collaboration, save_collaboration
from .domain import BlockerRecord, ProofObligation, ProjectSnapshot, ProjectState, TheoremContract, utc_now
from .domain_packs import DomainPack
from .publication import PublicationWorkspace, list_publication_bundle_snapshots, load_publication_workspace, save_publication_workspace
from .governance import GovernanceAssetRecord, GovernancePackRecord, GovernancePolicyRecord, list_domain_pack_records, list_policy_records, list_reusable_asset_records
from .memory import LayeredMemory, HandoffSnapshot, latest_handoff_snapshot, load_memory, save_memory
from .proof_state import load_state, save_state
from .references import ReferenceRecord, ReferenceReviewRecord
from .reusable_assets import ReusableAsset
from .storage import (
    ProjectStore,
    create_project,
    list_blockers,
    list_obligations,
    list_references,
    list_reference_reviews,
    read_latest_snapshot,
    store_blocker,
    store_contract,
    store_obligation,
    store_reference,
    store_snapshot,
)
from .theorems import list_theorems


class ExchangeBundle(BaseModel):
    id: str = Field(default_factory=lambda: f"bundle_{uuid.uuid4().hex[:12]}")
    project_id: str
    exported_at: datetime = Field(default_factory=utc_now)
    note: str = ""
    project_state: ProjectState
    latest_snapshot: ProjectSnapshot | None = None
    handoff_snapshot: HandoffSnapshot | None = None
    memory: LayeredMemory
    collaboration: CollaborationState
    theorem_contracts: list[TheoremContract] = Field(default_factory=list)
    obligations: list[ProofObligation] = Field(default_factory=list)
    blockers: list[BlockerRecord] = Field(default_factory=list)
    references: list[ReferenceRecord] = Field(default_factory=list)
    reference_reviews: list[ReferenceReviewRecord] = Field(default_factory=list)
    reusable_assets: list[GovernanceAssetRecord] = Field(default_factory=list)
    domain_packs: list[GovernancePackRecord] = Field(default_factory=list)
    policies: list[GovernancePolicyRecord] = Field(default_factory=list)
    publication_workspace: PublicationWorkspace | None = None


class ExchangeImportReport(BaseModel):
    bundle_id: str
    project_id: str
    imported_sections: list[str] = Field(default_factory=list)
    rejected_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    note: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ExchangeInspectReport(BaseModel):
    bundle_id: str | None = None
    project_id: str
    preserved: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    section_counts: dict[str, int] = Field(default_factory=dict)
    note: str = ""


def _contract_table_upsert(store: ProjectStore, contract: TheoremContract) -> None:
    with store.connect() as conn:
        conn.execute("UPDATE theorem_contracts SET is_current = 0 WHERE id = ?", (contract.id,))
        conn.execute(
            """
            INSERT INTO theorem_contracts(id, version, is_current, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id, version) DO UPDATE SET
              is_current = excluded.is_current,
              data = excluded.data,
              created_at = excluded.created_at,
              updated_at = excluded.updated_at
            """,
            (
                contract.id,
                contract.version,
                1,
                contract.model_dump_json(),
                contract.created_at.isoformat(),
                contract.updated_at.isoformat(),
            ),
        )
        conn.commit()


def _reference_upsert(store: ProjectStore, reference: ReferenceRecord) -> None:
    store_reference(store, reference)


def _reference_review_insert(store: ProjectStore, review: ReferenceReviewRecord) -> None:
    with store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reference_reviews(id, reference_id, data, created_at) VALUES (?, ?, ?, ?)",
            (review.id, review.reference_id, review.model_dump_json(), review.created_at.isoformat()),
        )
        conn.commit()


def export_exchange_bundle(store: ProjectStore, *, note: str = "") -> ExchangeBundle:
    state = load_state(store)
    memory = load_memory(store)
    collaboration = load_collaboration(store)
    publication_workspace = load_publication_workspace(store)
    bundle = ExchangeBundle(
        project_id=state.project_id,
        note=note or "",
        project_state=state,
        latest_snapshot=read_latest_snapshot(store),
        handoff_snapshot=latest_handoff_snapshot(store),
        memory=memory,
        collaboration=collaboration,
        theorem_contracts=list_theorems(store),
        obligations=list_obligations(store),
        blockers=list_blockers(store),
        references=list_references(store),
        reference_reviews=list_reference_reviews(store),
        reusable_assets=list_reusable_asset_records(store),
        domain_packs=list_domain_pack_records(store),
        policies=list_policy_records(store),
        publication_workspace=publication_workspace,
    )
    return bundle


def inspect_exchange_bundle(bundle: ExchangeBundle | dict[str, Any]) -> ExchangeInspectReport:
    if not isinstance(bundle, ExchangeBundle):
        bundle = ExchangeBundle.model_validate(bundle)
    preserved = [
        "project_state",
        "memory",
        "collaboration",
        "theorem_contracts",
        "obligations",
        "blockers",
        "references",
        "reusable_assets",
        "domain_packs",
        "policies",
    ]
    rejected: list[str] = []
    section_counts = {
        "theorem_contracts": len(bundle.theorem_contracts),
        "obligations": len(bundle.obligations),
        "blockers": len(bundle.blockers),
        "references": len(bundle.references),
        "reusable_assets": len(bundle.reusable_assets),
        "domain_packs": len(bundle.domain_packs),
        "policies": len(bundle.policies),
        "publication_views": len(bundle.publication_workspace.views) if bundle.publication_workspace is not None else 0,
        "publication_states": len(bundle.publication_workspace.states) if bundle.publication_workspace is not None else 0,
        "publication_releases": len(bundle.publication_workspace.release_records) if bundle.publication_workspace is not None else 0,
        "publication_bundle_snapshots": len(bundle.publication_workspace.bundle_snapshots) if bundle.publication_workspace is not None else 0,
        "comments": len(bundle.collaboration.comments),
        "branches": len(bundle.collaboration.branches),
        "publications": len(bundle.collaboration.publications),
    }
    if bundle.publication_workspace is None:
        rejected.append("publication_workspace")
    else:
        preserved.append("publication_workspace")
        if bundle.publication_workspace.bundle_snapshots:
            preserved.append("publication_bundle_snapshots")
    if bundle.latest_snapshot is None:
        rejected.append("latest_snapshot")
    if bundle.handoff_snapshot is None:
        rejected.append("handoff_snapshot")
    return ExchangeInspectReport(
        bundle_id=bundle.id,
        project_id=bundle.project_id,
        preserved=preserved,
        rejected=rejected,
        section_counts=section_counts,
        note=bundle.note,
    )


def import_exchange_bundle(store: ProjectStore, bundle: ExchangeBundle | dict[str, Any]) -> ExchangeImportReport:
    if not isinstance(bundle, ExchangeBundle):
        bundle = ExchangeBundle.model_validate(bundle)
    create_project(store.root, bundle.project_id)
    with store.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO project_meta(key, value) VALUES (?, ?)", ("project_id", bundle.project_id))
        conn.commit()
    save_state(store, bundle.project_state)
    save_memory(store, bundle.memory)
    save_collaboration(store, bundle.collaboration)
    if bundle.publication_workspace is not None:
        save_publication_workspace(store, bundle.publication_workspace)
    imported_sections: list[str] = ["project_state", "memory", "collaboration"]
    rejected_sections: list[str] = []

    for contract in bundle.theorem_contracts:
        _contract_table_upsert(store, contract)
    if bundle.theorem_contracts:
        imported_sections.append("theorem_contracts")

    for obligation in bundle.obligations:
        store_obligation(store, obligation)
    if bundle.obligations:
        imported_sections.append("obligations")

    for blocker in bundle.blockers:
        store_blocker(store, blocker)
    if bundle.blockers:
        imported_sections.append("blockers")

    for reference in bundle.references:
        _reference_upsert(store, reference)
    if bundle.references:
        imported_sections.append("references")

    for review in bundle.reference_reviews:
        _reference_review_insert(store, review)
    if bundle.reference_reviews:
        imported_sections.append("reference_reviews")

    if bundle.latest_snapshot is not None:
        store_snapshot(store, bundle.latest_snapshot)
        imported_sections.append("latest_snapshot")
    else:
        rejected_sections.append("latest_snapshot")

    if bundle.handoff_snapshot is not None:
        memory = load_memory(store)
        memory.handoff_snapshots.append(bundle.handoff_snapshot)
        save_memory(store, memory)
        imported_sections.append("handoff_snapshot")
    else:
        rejected_sections.append("handoff_snapshot")

    if bundle.publication_workspace is not None:
        imported_sections.append("publication_workspace")
        if bundle.publication_workspace.bundle_snapshots:
            imported_sections.append("publication_bundle_snapshots")
    else:
        rejected_sections.append("publication_workspace")

    return ExchangeImportReport(
        bundle_id=bundle.id,
        project_id=bundle.project_id,
        imported_sections=imported_sections,
        rejected_sections=rejected_sections,
        snapshot_id=bundle.latest_snapshot.project_id if bundle.latest_snapshot is not None else None,
        note=bundle.note,
    )


def bundle_to_json(bundle: ExchangeBundle) -> str:
    return bundle.model_dump_json(indent=2)


def bundle_from_json(bundle_json: str) -> ExchangeBundle:
    return ExchangeBundle.model_validate_json(bundle_json)


def report_to_json(report: ExchangeImportReport | ExchangeInspectReport) -> str:
    return report.model_dump_json(indent=2)


def summarize_import_report(report: ExchangeImportReport) -> str:
    imported = ", ".join(report.imported_sections) or "none"
    rejected = ", ".join(report.rejected_sections) or "none"
    return f"{report.bundle_id}: imported={imported} rejected={rejected}"


def summarize_inspect_report(report: ExchangeInspectReport) -> str:
    preserved = ", ".join(report.preserved) or "none"
    rejected = ", ".join(report.rejected) or "none"
    counts = ", ".join(f"{key}={value}" for key, value in sorted(report.section_counts.items()))
    return f"{report.bundle_id or 'latest'}: preserved={preserved} rejected={rejected} {counts}"


__all__ = [
    "ExchangeBundle",
    "ExchangeImportReport",
    "ExchangeInspectReport",
    "bundle_from_json",
    "bundle_to_json",
    "export_exchange_bundle",
    "import_exchange_bundle",
    "inspect_exchange_bundle",
    "report_to_json",
    "summarize_import_report",
    "summarize_inspect_report",
]
