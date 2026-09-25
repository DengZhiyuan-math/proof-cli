from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .collaboration import CollaborationState, load_collaboration, save_collaboration
from .domain import (
    BlockerRecord,
    CandidateProofRecord,
    Challenge,
    ClaimRecord,
    DependencyPin,
    EvidenceCheck,
    ProofMapNode,
    ProofObligation,
    ProjectSnapshot,
    ProjectState,
    TheoremContract,
    utc_now,
)
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
    import_reference_review,
    import_theorem_contract,
    insert_candidate_proof,
    insert_challenge,
    insert_claim,
    insert_evidence_check,
    insert_proof_map_node,
    list_all_candidate_proofs,
    list_all_claims,
    list_all_dependency_pins,
    list_all_evidence_checks,
    list_blockers,
    list_challenges,
    list_obligations,
    list_proof_map_nodes,
    list_references,
    list_reference_reviews,
    read_latest_snapshot,
    set_project_id,
    store_blocker,
    store_reference,
    store_obligation,
    store_snapshot,
    upsert_dependency_pin,
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
    # The new ProofMapNode model (issue #31). candidate_proofs is only the
    # index — id, version, file_path, fingerprint, etc; the proof text
    # itself lives in the git-tracked Proof vault (proofs/<node>/v<n>.md),
    # exchanged via git like the rest of the working tree, not through this
    # JSON bundle.
    proof_map_nodes: list[ProofMapNode] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    candidate_proofs: list[CandidateProofRecord] = Field(default_factory=list)
    dependency_pins: list[DependencyPin] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    evidence_checks: list[EvidenceCheck] = Field(default_factory=list)


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
        proof_map_nodes=list_proof_map_nodes(store),
        claims=list_all_claims(store),
        candidate_proofs=list_all_candidate_proofs(store),
        dependency_pins=list_all_dependency_pins(store),
        challenges=list_challenges(store),
        evidence_checks=list_all_evidence_checks(store),
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
        "proof_map_nodes",
        "claims",
        "candidate_proofs",
        "dependency_pins",
        "challenges",
        "evidence_checks",
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
        "proof_map_nodes": len(bundle.proof_map_nodes),
        "claims": len(bundle.claims),
        "candidate_proofs": len(bundle.candidate_proofs),
        "dependency_pins": len(bundle.dependency_pins),
        "challenges": len(bundle.challenges),
        "evidence_checks": len(bundle.evidence_checks),
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
    set_project_id(store, bundle.project_id)
    save_state(store, bundle.project_state)
    save_memory(store, bundle.memory)
    save_collaboration(store, bundle.collaboration)
    if bundle.publication_workspace is not None:
        save_publication_workspace(store, bundle.publication_workspace)
    imported_sections: list[str] = ["project_state", "memory", "collaboration"]
    rejected_sections: list[str] = []

    for contract in bundle.theorem_contracts:
        import_theorem_contract(store, contract)
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
        store_reference(store, reference)
    if bundle.references:
        imported_sections.append("references")

    for review in bundle.reference_reviews:
        import_reference_review(store, review)
    if bundle.reference_reviews:
        imported_sections.append("reference_reviews")

    for node in bundle.proof_map_nodes:
        insert_proof_map_node(store, node)
    if bundle.proof_map_nodes:
        imported_sections.append("proof_map_nodes")

    for claim in bundle.claims:
        insert_claim(store, claim)
    if bundle.claims:
        imported_sections.append("claims")

    for proof in bundle.candidate_proofs:
        insert_candidate_proof(store, proof)
    if bundle.candidate_proofs:
        imported_sections.append("candidate_proofs")

    for pin in bundle.dependency_pins:
        upsert_dependency_pin(store, pin)
    if bundle.dependency_pins:
        imported_sections.append("dependency_pins")

    for challenge in bundle.challenges:
        insert_challenge(store, challenge)
    if bundle.challenges:
        imported_sections.append("challenges")

    for check in bundle.evidence_checks:
        insert_evidence_check(store, check)
    if bundle.evidence_checks:
        imported_sections.append("evidence_checks")

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
