"""Exchange: move a proof project's records, and its Proof vault files, into another project (#31).

A bundle (`ExchangeBundle`) is one JSON document: the proof map (nodes, claims,
the Candidate proof index, pins, Challenges, Evidence checks), each node's
`proofs/<node-id>/` files (`vault_files`: working sources, `snapshots/v<N>/`
folders, archived PDFs), the shared `proofs/preamble.tex`, and the project's
side state (ProjectState, memory, collaboration, publication, governance and
the legacy contract/obligation/blocker/reference registry).

Import is a **merge in two phases**:

1. **Validate everything**, writing nothing: the bundle's schema, record id
   clashes with this project, the one-Theorem rule, dependencies, every
   Candidate proof `file_path` and vault file path (inside `proofs/<node-id>/`,
   relative, no `..`), each vault file's SHA-256, and each imported
   Candidate proof's snapshot against the SHA-256 its index row records.
   Any problem rejects the whole bundle (`ProofMapError`, every problem in
   `details["problems"]`).
2. **Write everything in one SQLite transaction.** A vault file that fails to
   write rolls the transaction back, and the files already written are removed.

What the merge keeps and what it never takes:

- **Local wins, record by record.** A node, contract, reference, comment,
  memory entry, publication claim (one per object) or governance record that
  exists here keeps its local version; the bundle's copy is counted in
  `kept_local`. ProjectState and the side documents merge per record through
  #39's transactional write paths. The local `project_id` is never rewritten.
- **No decision or trust crosses over.** Imported nodes arrive `unreviewed`: a
  node's `reviews.jsonl` never travels as a file (the source's decisions ride
  in `review_decisions`, recorded in the event log for reference, counting for
  nothing, ADR-0010), and an imported Candidate proof keeps no review record id
  or interface fingerprint. Contracts and references are reset to local
  defaults (legacy trust is retired, #50). Challenges arrive open. Trust rules
  (`proofs/trust-rules.jsonl`, ADR-0014) never travel either way: they are the
  researcher's own standing declarations, so an imported citation is trusted
  here only under a rule declared here.
- **Claims arrive released** and are listed in `released_claims`: an assignee
  in another project isn't working here.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import posixpath
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError

from .authority import list_decisions
from .collaboration import CollaborationState, import_review_records, load_collaboration, save_collaboration
from .domain import (
    BlockerRecord,
    BlockerStatus,
    CandidateProofRecord,
    Challenge,
    ChallengeStatus,
    ClaimRecord,
    DependencyPin,
    EvidenceCheck,
    ProofMapNode,
    ProofMapNodeKind,
    ProofObligation,
    ProofObligationStatus,
    ProjectSnapshot,
    ProjectState,
    TheoremContract,
    TheoremProvenanceKind,
    TheoremReviewState,
    utc_now,
)
from .governance import (
    ASSET_HISTORY_PREFIX,
    PACK_HISTORY_PREFIX,
    POLICY_HISTORY_PREFIX,
    GovernanceAssetRecord,
    GovernancePackRecord,
    GovernancePolicyRecord,
    list_domain_pack_records,
    list_policy_records,
    list_reusable_asset_records,
)
from .memory import HandoffSnapshot, LayeredMemory, latest_handoff_snapshot, load_memory, save_memory
from .proof_map import _SAFE_NODE_ID, ProofMapError, note_trust_rule_matches
from .proof_state import load_state, save_state
from .publication import PublicationWorkspace, load_publication_workspace, save_publication_workspace
from .references import ReferenceRecord, ReferenceReviewRecord
from .storage import (
    ProjectStore,
    append_event,
    ensure_project,
    import_reference_review,
    import_theorem_contract,
    insert_candidate_proof,
    insert_challenge,
    insert_claim,
    insert_evidence_check,
    insert_governance_record,
    insert_proof_map_node,
    list_all_candidate_proofs,
    list_all_claims,
    list_all_dependency_pins,
    list_all_evidence_checks,
    list_blockers,
    list_challenges,
    list_obligations,
    list_proof_map_nodes,
    list_reference_reviews,
    list_references,
    on_rollback,
    read_latest_snapshot,
    store_blocker,
    store_obligation,
    store_reference,
    store_snapshot,
    upsert_dependency_pin,
)
from .theorems import list_theorems
from .vault import SNAPSHOT_MANIFEST, exchanged_files, preamble_path, snapshot_digest_of

SHARED_PREAMBLE = "proofs/preamble.tex"
RELEASED_BY = "exchange-import"


class VaultFile(BaseModel):
    """One Proof vault file, by its path from the project root, with its SHA-256."""

    path: str
    sha256: str
    content_base64: str

    @classmethod
    def of(cls, path: str, data: bytes) -> "VaultFile":
        return cls(path=path, sha256=hashlib.sha256(data).hexdigest(), content_base64=base64.b64encode(data).decode("ascii"))


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
    proof_map_nodes: list[ProofMapNode] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    # the Candidate proof index; the snapshot files it points at are in vault_files
    candidate_proofs: list[CandidateProofRecord] = Field(default_factory=list)
    dependency_pins: list[DependencyPin] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    evidence_checks: list[EvidenceCheck] = Field(default_factory=list)
    # each node's proofs/<node-id>/ files (no reviews.jsonl, build/ or scratch/) and the shared preamble
    vault_files: list[VaultFile] = Field(default_factory=list)
    # The source project's Human Review decisions (its reviews.jsonl lines),
    # for reference only: they never count here (ADR-0010). A bundle from
    # before ADR-0010 carried signatures instead; they're ignored.
    review_decisions: list[dict] = Field(default_factory=list)


class ExchangeImportReport(BaseModel):
    bundle_id: str
    project_id: str  # this project's, which import never changes
    source_project_id: str = ""
    imported_sections: list[str] = Field(default_factory=list)
    rejected_sections: list[str] = Field(default_factory=list)
    written: dict[str, int] = Field(default_factory=dict)
    kept_local: dict[str, int] = Field(default_factory=dict)
    released_claims: list[dict[str, str]] = Field(default_factory=list)
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


# Every section import writes (or merges), whatever the bundle holds; inspect reports the same list.
IMPORTED_SECTIONS = (
    "project_state",
    "memory",
    "collaboration",
    "theorem_contracts",
    "obligations",
    "blockers",
    "references",
    "reference_reviews",
    "reusable_assets",
    "domain_packs",
    "policies",
    "proof_map_nodes",
    "claims",
    "candidate_proofs",
    "dependency_pins",
    "challenges",
    "evidence_checks",
    "vault_files",
)


# -- export ------------------------------------------------------------------------------


def _vault_files(store: ProjectStore, nodes: list[ProofMapNode]) -> list[VaultFile]:
    files: list[VaultFile] = []
    preamble = preamble_path(store.root)
    if preamble.is_file():
        files.append(VaultFile.of(SHARED_PREAMBLE, preamble.read_bytes()))
    for node in nodes:
        for rel, path in exchanged_files(store.root, node.id).items():
            files.append(VaultFile.of(rel, path.read_bytes()))
    return files


def export_exchange_bundle(store: ProjectStore, *, note: str = "") -> ExchangeBundle:
    state = load_state(store)
    nodes = list_proof_map_nodes(store)
    bundle = ExchangeBundle(
        project_id=state.project_id,
        note=note or "",
        project_state=state,
        latest_snapshot=read_latest_snapshot(store),
        handoff_snapshot=latest_handoff_snapshot(store),
        memory=load_memory(store),
        collaboration=load_collaboration(store),
        theorem_contracts=list_theorems(store),
        obligations=list_obligations(store),
        blockers=list_blockers(store),
        references=list_references(store),
        reference_reviews=list_reference_reviews(store),
        reusable_assets=list_reusable_asset_records(store),
        domain_packs=list_domain_pack_records(store),
        policies=list_policy_records(store),
        publication_workspace=load_publication_workspace(store),
        proof_map_nodes=nodes,
        claims=list_all_claims(store),
        candidate_proofs=list_all_candidate_proofs(store),
        dependency_pins=list_all_dependency_pins(store),
        challenges=list_challenges(store),
        evidence_checks=list_all_evidence_checks(store),
        vault_files=_vault_files(store, nodes),
    )
    bundle.review_decisions = [
        {key: (value.model_dump(mode="json") if hasattr(value, "model_dump") else value) for key, value in row.items()}
        for row in list_decisions(store)
    ]
    return bundle


# -- reading a bundle --------------------------------------------------------------------


def parse_bundle(source: str | bytes | dict[str, Any]) -> ExchangeBundle:
    """A bundle from its JSON (or an already-parsed dict): a bare bundle, or the envelope
    `proof exchange export --json` prints. Anything else is `MALFORMED_BUNDLE`."""
    data: Any = source
    if isinstance(source, (str, bytes)):
        try:
            data = json.loads(source)
        except ValueError as exc:
            raise ProofMapError("MALFORMED_BUNDLE", f"the bundle isn't JSON: {exc}") from None
    if isinstance(data, dict) and "schema_version" in data and isinstance(data.get("data"), dict):
        if data.get("ok") is False:
            raise ProofMapError("MALFORMED_BUNDLE", "the input is a failed command's envelope, not a bundle")
        data = data["data"]
    if not isinstance(data, dict):
        raise ProofMapError("MALFORMED_BUNDLE", "the bundle must be a JSON object")
    try:
        return ExchangeBundle.model_validate(data)
    except ValidationError as exc:
        errors = [{"at": ".".join(str(part) for part in error["loc"]), "message": error["msg"]} for error in exc.errors()[:20]]
        raise ProofMapError(
            "MALFORMED_BUNDLE",
            f"the bundle doesn't match the exchange schema ({exc.error_count()} problem(s), first at {errors[0]['at'] or 'the top'})",
            details={"problems": errors},
        ) from None


def bundle_to_json(bundle: ExchangeBundle) -> str:
    return bundle.model_dump_json(indent=2)


def bundle_from_json(bundle_json: str) -> ExchangeBundle:
    return parse_bundle(bundle_json)


def _coerce(bundle: ExchangeBundle | dict[str, Any] | str) -> ExchangeBundle:
    return bundle if isinstance(bundle, ExchangeBundle) else parse_bundle(bundle)


# -- inspect -----------------------------------------------------------------------------


def inspect_exchange_bundle(bundle: ExchangeBundle | dict[str, Any]) -> ExchangeInspectReport:
    """What importing `bundle` would carry over: `preserved` names exactly the sections import writes."""
    bundle = _coerce(bundle)
    preserved = list(IMPORTED_SECTIONS)
    rejected: list[str] = []
    workspace = bundle.publication_workspace
    section_counts = {
        "theorem_contracts": len(bundle.theorem_contracts),
        "obligations": len(bundle.obligations),
        "blockers": len(bundle.blockers),
        "references": len(bundle.references),
        "reference_reviews": len(bundle.reference_reviews),
        "reusable_assets": len(bundle.reusable_assets),
        "domain_packs": len(bundle.domain_packs),
        "policies": len(bundle.policies),
        "proof_map_nodes": len(bundle.proof_map_nodes),
        "claims": len(bundle.claims),
        "active_claims": sum(1 for claim in bundle.claims if claim.released_at is None),
        "candidate_proofs": len(bundle.candidate_proofs),
        "dependency_pins": len(bundle.dependency_pins),
        "challenges": len(bundle.challenges),
        "evidence_checks": len(bundle.evidence_checks),
        "vault_files": len(bundle.vault_files),
        "review_decisions": len(bundle.review_decisions),
        "publication_views": len(workspace.views) if workspace is not None else 0,
        "publication_states": len(workspace.states) if workspace is not None else 0,
        "publication_releases": len(workspace.release_records) if workspace is not None else 0,
        "publication_bundle_snapshots": len(workspace.bundle_snapshots) if workspace is not None else 0,
        "comments": len(bundle.collaboration.comments),
        "branches": len(bundle.collaboration.branches),
        "publications": len(bundle.collaboration.publications),
    }
    for section, present in (
        ("publication_workspace", workspace is not None),
        ("latest_snapshot", bundle.latest_snapshot is not None),
        ("handoff_snapshot", bundle.handoff_snapshot is not None),
    ):
        (preserved if present else rejected).append(section)
    return ExchangeInspectReport(
        bundle_id=bundle.id,
        project_id=bundle.project_id,
        preserved=preserved,
        rejected=rejected,
        section_counts=section_counts,
        note=bundle.note,
    )


# -- import, phase 1: validate everything, write nothing ----------------------------------


@dataclass
class _Plan:
    problems: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kept_local: dict[str, int] = field(default_factory=dict)
    nodes: list[ProofMapNode] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    released_claims: list[dict[str, str]] = field(default_factory=list)
    proofs: list[CandidateProofRecord] = field(default_factory=list)
    pins: list[DependencyPin] = field(default_factory=list)
    challenges: list[Challenge] = field(default_factory=list)
    checks: list[EvidenceCheck] = field(default_factory=list)
    contracts: list[TheoremContract] = field(default_factory=list)
    obligations: list[ProofObligation] = field(default_factory=list)
    blockers: list[BlockerRecord] = field(default_factory=list)
    references: list[ReferenceRecord] = field(default_factory=list)
    reference_reviews: list[ReferenceReviewRecord] = field(default_factory=list)
    governance: list[tuple[str, str, BaseModel]] = field(default_factory=list)  # (section, kind, record)
    files: list[tuple[str, bytes]] = field(default_factory=list)

    def problem(self, code: str, message: str, **details: Any) -> None:
        self.problems.append({"code": code, "message": message, **details})

    def keep(self, section: str, count: int = 1) -> None:
        if count:
            self.kept_local[section] = self.kept_local.get(section, 0) + count


R = TypeVar("R", bound=BaseModel)


def _new_only(plan: _Plan, section: str, records: list[R], local_ids: set[str], key: Callable[[R], str] = lambda record: record.id) -> list[R]:
    """The records not already here; the rest keep their local version."""
    fresh = [record for record in records if key(record) not in local_ids]
    plan.keep(section, len(records) - len(fresh))
    return fresh


def _unique_ids(plan: _Plan, section: str, records: list[BaseModel], local_ids: set[str]) -> None:
    """Records about to be written must not reuse an id this project, or the bundle itself, already uses."""
    seen: set[str] = set()
    for record in records:
        if record.id in local_ids or record.id in seen:
            where = "this project" if record.id in local_ids else "the bundle, twice"
            plan.problem("IMPORT_ID_CONFLICT", f"{section} id {record.id} is already used in {where}", section=section, id=record.id)
        seen.add(record.id)


def _path_problem(path: str) -> str | None:
    """Why `path` isn't a safe relative path inside `proofs/`, or None."""
    if not path or "\\" in path or "\x00" in path:
        return "not a plain relative path"
    pure = PurePosixPath(path)
    if pure.is_absolute():
        return "an absolute path"
    if ".." in pure.parts:
        return "contains '..'"
    if posixpath.normpath(path) != path:
        return "not a normalised path"
    if pure.parts[0] != "proofs":
        return "outside proofs/"
    return None


def _node_path_problem(path: str, node_id: str) -> str | None:
    problem = _path_problem(path)
    if problem is None and (len(PurePosixPath(path).parts) < 3 or PurePosixPath(path).parts[1] != node_id):
        problem = f"outside proofs/{node_id}/"
    return problem


def _plan_vault_files(store: ProjectStore, bundle: ExchangeBundle, plan: _Plan, new_ids: set[str], local_ids: set[str]) -> dict[str, bytes]:
    """Check each carried file; plan the writes. Returns every valid file of an imported node, by path."""
    carried: dict[str, bytes] = {}
    proofs_dir = (store.root / "proofs").resolve()
    for file in bundle.vault_files:
        path = file.path
        problem = _path_problem(path)
        parts = PurePosixPath(path).parts
        if problem is None and PurePosixPath(path).name == "reviews.jsonl":
            problem = "a reviews.jsonl: decisions travel in review_decisions, for reference only"
        if problem is None and path != SHARED_PREAMBLE:
            if len(parts) < 3:
                problem = "not inside a node's folder"
            elif parts[1] not in new_ids | local_ids:
                problem = f"in the folder of {parts[1]}, which isn't a node in the bundle"
        if problem is not None:
            plan.problem("INVALID_VAULT_PATH", f"vault file {path!r} is {problem}", path=path)
            continue
        if path in carried:
            plan.problem("MALFORMED_BUNDLE", f"vault file {path} appears twice", path=path)
            continue
        try:
            data = base64.b64decode(file.content_base64, validate=True)
        except (binascii.Error, ValueError):
            plan.problem("MALFORMED_BUNDLE", f"vault file {path} isn't valid base64", path=path)
            continue
        if hashlib.sha256(data).hexdigest() != file.sha256:
            plan.problem("VAULT_HASH_MISMATCH", f"vault file {path} doesn't match its SHA-256", path=path)
            continue
        if path != SHARED_PREAMBLE and parts[1] in local_ids:
            plan.keep("vault_files")  # a local node keeps its own folder
            continue
        carried[path] = data
        target = store.root / path
        if not target.resolve().is_relative_to(proofs_dir):
            plan.problem("INVALID_VAULT_PATH", f"vault file {path} would land outside proofs/ (through a link)", path=path)
        elif target.is_file():
            if target.read_bytes() == data:
                continue  # already here, byte for byte
            if path == SHARED_PREAMBLE:
                plan.keep("vault_files")
                plan.warnings.append(f"kept the local {SHARED_PREAMBLE}; the bundle's differs (each snapshot froze its own copy)")
            else:
                plan.problem("VAULT_FILE_CONFLICT", f"{path} already exists here with other content", path=path)
        elif target.exists() or any(parent.is_file() for parent in target.parents):
            plan.problem("VAULT_FILE_CONFLICT", f"{path} can't be written: something else is in the way", path=path)
        else:
            plan.files.append((path, data))
    return carried


def _check_snapshot(plan: _Plan, proof: CandidateProofRecord, carried: dict[str, bytes]) -> None:
    """The snapshot the index row names travels in the bundle, with the SHA-256 the row records."""
    if proof.file_path.endswith("/" + SNAPSHOT_MANIFEST):
        folder = proof.file_path.removesuffix(SNAPSHOT_MANIFEST)
        digest = snapshot_digest_of(carried.get(proof.file_path), lambda rel: carried.get(folder + rel))
    else:
        data = carried.get(proof.file_path)
        digest = hashlib.sha256(data).hexdigest() if data is not None else None
    if digest is None:
        plan.problem(
            "VAULT_FILE_MISSING",
            f"candidate proof {proof.id} names {proof.file_path}, which the bundle doesn't carry whole",
            candidate_proof_id=proof.id,
            path=proof.file_path,
        )
    elif proof.sha256 is not None and digest != proof.sha256:
        plan.problem(
            "VAULT_HASH_MISMATCH",
            f"candidate proof {proof.id}: {proof.file_path} doesn't match the SHA-256 its index records",
            candidate_proof_id=proof.id,
            path=proof.file_path,
        )


def _untrusted_contract(contract: TheoremContract) -> TheoremContract:
    """Legacy trust is retired (#50): an imported contract gets a new contract's defaults."""
    defaults = TheoremContract(id=contract.id, name=contract.name, statement=contract.statement)
    review_state = TheoremReviewState.candidate if contract.provenance_kind == TheoremProvenanceKind.imported else defaults.review_state
    return contract.model_copy(update={"status": defaults.status, "trust_level": defaults.trust_level, "review_state": review_state})


def _untrusted_reference(reference: ReferenceRecord) -> ReferenceRecord:
    defaults = ReferenceRecord(id=reference.id, title=reference.title, year=reference.year)
    return reference.model_copy(update={"review_status": defaults.review_status, "trust_level": defaults.trust_level, "is_callable": defaults.is_callable})


def _plan_import(store: ProjectStore, bundle: ExchangeBundle) -> _Plan:
    plan = _Plan()
    local_nodes = list_proof_map_nodes(store)
    local_ids = {node.id for node in local_nodes}

    # -- the proof map --
    seen: set[str] = set()
    for node in bundle.proof_map_nodes:
        if node.id in seen:
            plan.problem("IMPORT_ID_CONFLICT", f"node {node.id} appears twice in the bundle", section="proof_map_nodes", id=node.id)
        seen.add(node.id)
    plan.nodes = _new_only(plan, "proof_map_nodes", bundle.proof_map_nodes, local_ids)
    new_ids = {node.id for node in plan.nodes}
    for node in plan.nodes:
        if not _SAFE_NODE_ID.fullmatch(node.id):
            plan.problem("INVALID_NODE_ID", f"node id {node.id!r} isn't a plain folder name", node_id=node.id)
        missing = [dependency for dependency in node.dependencies if dependency not in local_ids | new_ids]
        if missing:
            plan.problem("DEPENDENCY_NOT_FOUND", f"node {node.id} depends on {', '.join(missing)}, in neither the bundle nor this project", node_id=node.id)
    theorems = [node.id for node in local_nodes if node.kind == ProofMapNodeKind.theorem] + [
        node.id for node in plan.nodes if node.kind == ProofMapNodeKind.theorem
    ]
    if len(theorems) > 1:
        plan.problem("DUPLICATE_THEOREM", f"a project has one Theorem; importing would make {', '.join(theorems)}", theorems=theorems)

    # a local node keeps its own history: the bundle's records about it are refused
    def about_new(section: str, records: list[R], node_of: Callable[[R], str]) -> list[R]:
        fresh = [record for record in records if node_of(record) in new_ids]
        plan.keep(section, len(records) - len(fresh))
        return fresh

    now = utc_now()
    claims = about_new("claims", bundle.claims, lambda claim: claim.node_id)
    _unique_ids(plan, "claims", claims, {claim.id for claim in list_all_claims(store)})
    for claim in claims:
        if claim.released_at is None:
            claim = claim.model_copy(
                update={"released_at": now, "released_by": RELEASED_BY, "release_reason": f"imported from {bundle.project_id}: a claim is released on import"}
            )
            plan.released_claims.append({"claim_id": claim.id, "node_id": claim.node_id, "claimant_id": claim.claimant_id})
        plan.claims.append(claim)

    proofs = about_new("candidate_proofs", bundle.candidate_proofs, lambda proof: proof.node_id)
    _unique_ids(plan, "candidate_proofs", proofs, {proof.id for proof in list_all_candidate_proofs(store)})
    versions: set[tuple[str, int]] = set()
    for proof in proofs:
        if (proof.node_id, proof.version) in versions:
            plan.problem("IMPORT_ID_CONFLICT", f"node {proof.node_id} has candidate proof version {proof.version} twice", section="candidate_proofs", id=proof.id)
        versions.add((proof.node_id, proof.version))
        problem = _node_path_problem(proof.file_path, proof.node_id)
        if problem is not None:
            plan.problem("INVALID_VAULT_PATH", f"candidate proof {proof.id}'s file_path {proof.file_path!r} is {problem}", candidate_proof_id=proof.id, path=proof.file_path)
        # a foreign Acceptance's traces: nothing was decided on this proof here
        plan.proofs.append(proof.model_copy(update={"review_record_id": None, "interface_fingerprint": None}))
    proofs_ok = not any(problem["code"] == "INVALID_VAULT_PATH" for problem in plan.problems)

    plan.pins = about_new("dependency_pins", bundle.dependency_pins, lambda pin: pin.node_id)
    _unique_ids(plan, "dependency_pins", plan.pins, {pin.id for pin in list_all_dependency_pins(store)})
    for pin in plan.pins:
        if pin.target_node_id not in local_ids | new_ids:
            plan.problem("DEPENDENCY_NOT_FOUND", f"pin {pin.id} names {pin.target_node_id}, in neither the bundle nor this project", node_id=pin.node_id)

    challenges = about_new("challenges", bundle.challenges, lambda challenge: challenge.target_node_id)
    _unique_ids(plan, "challenges", challenges, {challenge.id for challenge in list_challenges(store)})
    # an imported Challenge is open here: a foreign resolution resolves nothing locally
    plan.challenges = [
        challenge.model_copy(update={"status": ChallengeStatus.open, "resolved_by": None, "resolved_at": None, "resolution_review_id": None})
        for challenge in challenges
    ]

    proof_ids = {proof.id for proof in plan.proofs}
    plan.checks = [check for check in bundle.evidence_checks if check.candidate_proof_id in proof_ids]
    plan.keep("evidence_checks", len(bundle.evidence_checks) - len(plan.checks))
    _unique_ids(plan, "evidence_checks", plan.checks, {check.id for check in list_all_evidence_checks(store)})

    # -- the Proof vault --
    carried = _plan_vault_files(store, bundle, plan, new_ids, local_ids)
    if proofs_ok:
        for proof in plan.proofs:
            _check_snapshot(plan, proof, carried)

    # -- the legacy registry: records only, never trust --
    plan.contracts = [_untrusted_contract(c) for c in _new_only(plan, "theorem_contracts", bundle.theorem_contracts, {c.id for c in list_theorems(store)})]
    plan.obligations = [
        o.model_copy(update={"status": ProofObligationStatus.open}) if o.status == ProofObligationStatus.resolved else o
        for o in _new_only(plan, "obligations", bundle.obligations, {o.id for o in list_obligations(store)})
    ]
    plan.blockers = [
        b.model_copy(update={"status": BlockerStatus.active}) if b.status == BlockerStatus.resolved else b
        for b in _new_only(plan, "blockers", bundle.blockers, {b.id for b in list_blockers(store)})
    ]
    local_reference_ids = {r.id for r in list_references(store)}
    plan.references = [_untrusted_reference(r) for r in _new_only(plan, "references", bundle.references, local_reference_ids)]
    reviews = _new_only(plan, "reference_reviews", bundle.reference_reviews, {r.id for r in list_reference_reviews(store)})
    plan.reference_reviews = _new_only(plan, "reference_reviews", reviews, local_reference_ids, key=lambda review: review.reference_id)

    # -- governance records (#28), keyed by what they record --
    for section, kind, records, local, key in (
        ("reusable_assets", ASSET_HISTORY_PREFIX, bundle.reusable_assets, list_reusable_asset_records(store), lambda r: r.asset.id),
        ("domain_packs", PACK_HISTORY_PREFIX, bundle.domain_packs, list_domain_pack_records(store), lambda r: r.pack.id),
        ("policies", POLICY_HISTORY_PREFIX, bundle.policies, list_policy_records(store), lambda r: r.profile.id),
    ):
        for record in _new_only(plan, section, records, {key(r) for r in local}, key=key):
            plan.governance.append((section, kind, record))
    return plan


# -- import, phase 2: one transaction -----------------------------------------------------

M = TypeVar("M", bound=BaseModel)


def _record_key(item: Any) -> tuple[str, str]:
    ident = getattr(item, "id", None)
    if isinstance(ident, str):
        return ("id", ident)
    if isinstance(item, BaseModel):
        return ("value", item.model_dump_json())
    return ("value", json.dumps(item, sort_keys=True, default=str))


def _merge_list(local: list, incoming: list, key: Callable[[Any], Any] = _record_key) -> list:
    """Local records first and unchanged; then the bundle's records this project doesn't have."""
    seen = {key(item) for item in local}
    merged = list(local)
    for item in incoming:
        if key(item) not in seen:
            seen.add(key(item))
            merged.append(item)
    return merged


def _merge(local: M, incoming: M, *, keep: tuple[str, ...] = (), keys: dict[str, Callable[[Any], Any]] | None = None) -> M:
    """Per record, local wins: lists merge by record; a scalar is the bundle's only where the local one is unset."""
    update: dict[str, Any] = {}
    for name in type(local).model_fields:
        if name in keep:
            continue
        mine, theirs = getattr(local, name), getattr(incoming, name)
        if isinstance(mine, list):
            update[name] = _merge_list(mine, theirs, (keys or {}).get(name, _record_key))
        elif (mine is None or mine == "") and theirs not in (None, ""):
            update[name] = theirs
    return local.model_copy(update=update)


def _merge_collaboration(local: CollaborationState, incoming: CollaborationState) -> CollaborationState:
    # one comment thread per object: the bundle's comments on an object with a local thread join it
    local_threads = {(thread.object_type, thread.object_id): thread.id for thread in local.comment_threads}
    remap = {thread.id: local_threads[(thread.object_type, thread.object_id)] for thread in incoming.comment_threads if (thread.object_type, thread.object_id) in local_threads}
    incoming = incoming.model_copy(
        update={
            "comment_threads": [thread for thread in incoming.comment_threads if thread.id not in remap],
            "comments": [comment.model_copy(update={"thread_id": remap.get(comment.thread_id, comment.thread_id)}) for comment in incoming.comments],
            "review_records": [],
        }
    )
    return _merge(local, incoming, keep=("project_id", "version", "review_records"), keys={"policies": lambda policy: (policy.team_id, policy.name)})


def _write_vault_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _write_files(store: ProjectStore, files: list[tuple[str, bytes]]) -> None:
    """Write the planned vault files; if the transaction rolls back, each one written (and each folder made) goes."""
    for rel, data in files:
        target = store.root / rel
        made = [parent for parent in reversed(target.parents) if parent.is_relative_to(store.root) and not parent.exists()]

        def undo(target: Path = target, made: list[Path] = made) -> None:
            target.unlink(missing_ok=True)
            for folder in reversed(made):
                try:
                    folder.rmdir()
                except OSError:
                    pass

        on_rollback(store, undo)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_vault_file(target, data)


def _write_import(store: ProjectStore, bundle: ExchangeBundle, plan: _Plan) -> ExchangeImportReport:
    written: dict[str, int] = {}
    imported = list(IMPORTED_SECTIONS)
    rejected: list[str] = []
    with store.transaction():
        local_project_id = load_state(store).project_id
        save_state(
            store,
            _merge(load_state(store), bundle.project_state, keep=("project_id",)),
            event_kind="exchange_state_merged",
            message=f"merged project state from {bundle.project_id}",
        )
        memory = _merge(load_memory(store), bundle.memory, keep=("project_id", "version"))
        if bundle.handoff_snapshot is not None:
            memory.handoff_snapshots = _merge_list(memory.handoff_snapshots, [bundle.handoff_snapshot])
            imported.append("handoff_snapshot")
        else:
            rejected.append("handoff_snapshot")
        save_memory(store, memory)
        save_collaboration(store, _merge_collaboration(load_collaboration(store), bundle.collaboration))
        # only the non-trust-bearing reviews are appended; a decision is only ever made here (#33)
        _, refused_review_ids = import_review_records(store, bundle.collaboration.review_records)
        if bundle.publication_workspace is not None:
            save_publication_workspace(
                store,
                _merge(
                    load_publication_workspace(store),
                    bundle.publication_workspace,
                    keep=("project_id", "version", "created_at", "updated_at"),
                    keys={"claims": lambda claim: (claim.object_type, claim.object_id)},
                ),
            )
            imported.append("publication_workspace")
            if bundle.publication_workspace.bundle_snapshots:
                imported.append("publication_bundle_snapshots")
        else:
            rejected.append("publication_workspace")

        for contract in plan.contracts:
            import_theorem_contract(store, contract)
        for obligation in plan.obligations:
            store_obligation(store, obligation)
        for blocker in plan.blockers:
            store_blocker(store, blocker)
        for reference in plan.references:
            store_reference(store, reference)
        for review in plan.reference_reviews:
            import_reference_review(store, review)
        for section, kind, record in plan.governance:
            insert_governance_record(store, kind=kind, data=json.dumps(record.model_dump(mode="json"), sort_keys=True))
            written[section] = written.get(section, 0) + 1

        for node in plan.nodes:
            insert_proof_map_node(store, node)
        for claim in plan.claims:
            insert_claim(store, claim)
        for proof in plan.proofs:
            insert_candidate_proof(store, proof)
        for pin in plan.pins:
            upsert_dependency_pin(store, pin)
        for challenge in plan.challenges:
            insert_challenge(store, challenge)
        for check in plan.checks:
            insert_evidence_check(store, check)

        if bundle.latest_snapshot is not None:
            store_snapshot(store, bundle.latest_snapshot, replace=False)
            imported.append("latest_snapshot")
        else:
            rejected.append("latest_snapshot")
        if bundle.review_decisions:
            append_event(
                store,
                "exchange_foreign_decisions",
                f"{len(bundle.review_decisions)} Human Review decision(s) from {bundle.project_id}, kept for reference",
                payload={"bundle_id": bundle.id, "source_project_id": bundle.project_id, "decisions": bundle.review_decisions},
            )
        append_event(
            store,
            "exchange_imported",
            f"imported bundle {bundle.id} from {bundle.project_id}",
            payload={"bundle_id": bundle.id, "source_project_id": bundle.project_id, "released_claims": plan.released_claims},
        )
        # last: a file that fails to write rolls every write above back, and the files go with it
        _write_files(store, plan.files)

    written.update(
        {
            "theorem_contracts": len(plan.contracts),
            "obligations": len(plan.obligations),
            "blockers": len(plan.blockers),
            "references": len(plan.references),
            "reference_reviews": len(plan.reference_reviews),
            "proof_map_nodes": len(plan.nodes),
            "claims": len(plan.claims),
            "candidate_proofs": len(plan.proofs),
            "dependency_pins": len(plan.pins),
            "challenges": len(plan.challenges),
            "evidence_checks": len(plan.checks),
            "vault_files": len(plan.files),
        }
    )
    warnings = list(plan.warnings)
    if plan.kept_local:
        warnings.append(
            "not imported, the local version kept (it already exists here): "
            + ", ".join(f"{count} {section}" for section, count in plan.kept_local.items())
        )
    if plan.released_claims:
        warnings.append(f"{len(plan.released_claims)} claim(s) released on import: an assignee elsewhere isn't working here")
    if refused_review_ids:
        warnings.append(
            f"{len(refused_review_ids)} Human Review decision(s) not imported as decisions: they are only ever made "
            "locally, on the proof map page. The source's decisions are kept for reference in the event log, "
            "counting for nothing here"
        )
    if plan.contracts or plan.references:
        warnings.append("legacy contracts and references arrive with a new record's trust fields: legacy trust is retired (#50)")
    return ExchangeImportReport(
        bundle_id=bundle.id,
        project_id=local_project_id,
        source_project_id=bundle.project_id,
        imported_sections=imported,
        rejected_sections=rejected,
        written={section: count for section, count in written.items() if count},
        kept_local=dict(plan.kept_local),
        released_claims=plan.released_claims,
        warnings=warnings,
        snapshot_id=bundle.latest_snapshot.project_id if bundle.latest_snapshot is not None else None,
        note=bundle.note,
    )


def import_exchange_bundle(store: ProjectStore, bundle: ExchangeBundle | dict[str, Any] | str) -> ExchangeImportReport:
    """Merge `bundle` into this project: validate it whole, then write it in one transaction.

    Raises `ProofMapError` — `MALFORMED_BUNDLE`, `IMPORT_ID_CONFLICT`,
    `DUPLICATE_THEOREM`, `DEPENDENCY_NOT_FOUND`, `INVALID_NODE_ID`,
    `INVALID_VAULT_PATH`, `VAULT_FILE_MISSING`, `VAULT_HASH_MISMATCH` or
    `VAULT_FILE_CONFLICT`, the first problem's code, with every problem in
    `details["problems"]` — having written nothing.
    """
    bundle = _coerce(bundle)
    if not store.db_path.exists():
        store = ensure_project(store.root)
    plan = _plan_import(store, bundle)
    if plan.problems:
        first = plan.problems[0]
        more = f" (and {len(plan.problems) - 1} more problem(s))" if len(plan.problems) > 1 else ""
        raise ProofMapError(first["code"], f"bundle {bundle.id} not imported, nothing written: {first['message']}{more}", details={"problems": plan.problems})
    report = _write_import(store, bundle, plan)
    # imported citations and imported results may meet a rule declared here from the moment they land (ADR-0014)
    note_trust_rule_matches(store)
    return report


# -- output ------------------------------------------------------------------------------


def report_to_json(report: ExchangeImportReport | ExchangeInspectReport) -> str:
    return report.model_dump_json(indent=2)


def summarize_import_report(report: ExchangeImportReport) -> str:
    lines = [f"Imported bundle {report.bundle_id} from {report.source_project_id} into {report.project_id}"]
    lines.append("  written: " + (", ".join(f"{section}={count}" for section, count in report.written.items()) or "no new records"))
    lines.append("  merged: " + ", ".join(report.imported_sections))
    if report.kept_local:
        lines.append("  kept local: " + ", ".join(f"{section}={count}" for section, count in report.kept_local.items()))
    if report.rejected_sections:
        lines.append("  not in the bundle: " + ", ".join(report.rejected_sections))
    for claim in report.released_claims:
        lines.append(f"  Released claim {claim['claim_id']} on {claim['node_id']} (held by {claim['claimant_id']})")
    lines.extend(f"  warning: {warning}" for warning in report.warnings)
    return "\n".join(lines)


def summarize_inspect_report(report: ExchangeInspectReport) -> str:
    preserved = ", ".join(report.preserved) or "none"
    rejected = ", ".join(report.rejected) or "none"
    counts = ", ".join(f"{key}={value}" for key, value in sorted(report.section_counts.items()))
    return f"{report.bundle_id or 'latest'} (from {report.project_id}): preserved={preserved} rejected={rejected}\n  {counts}"


__all__ = [
    "ExchangeBundle",
    "ExchangeImportReport",
    "ExchangeInspectReport",
    "IMPORTED_SECTIONS",
    "VaultFile",
    "bundle_from_json",
    "bundle_to_json",
    "export_exchange_bundle",
    "import_exchange_bundle",
    "inspect_exchange_bundle",
    "parse_bundle",
    "report_to_json",
    "summarize_import_report",
    "summarize_inspect_report",
]
