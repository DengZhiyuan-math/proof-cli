"""Seed legacy trust state for tests (#37).

The legacy reference-approval and theorem-trust commands are gone (ADR-0001,
ADR-0009): nothing agent-reachable can set them any more. Tests of the
retrieval, export and checker code that *reads* that legacy state still need
projects that hold it, as pre-#37 projects do — so they write it directly
through storage, the way such a project's database already contains it.
"""

from proof_cli.references import ReferenceReviewStatus, ReferenceSourceType, ReferenceTrustLevel
from proof_cli.storage import get_reference, store_reference


def _reference_trust_level(reference, review_status: ReferenceReviewStatus) -> ReferenceTrustLevel:
    # the trust level a legacy approval used to give a reference (retired by ADR-0012)
    if review_status != ReferenceReviewStatus.approved or reference.trust_level == ReferenceTrustLevel.foundational:
        return reference.trust_level
    if reference.source_type == ReferenceSourceType.standard_reference:
        return ReferenceTrustLevel.standard_reference
    return ReferenceTrustLevel.external_research_source


def seed_reference_review(store, reference_id: str, status: ReferenceReviewStatus):
    reference = get_reference(store, reference_id)
    approved = status == ReferenceReviewStatus.approved
    return store_reference(
        store,
        reference.model_copy(
            update={"review_status": status, "is_callable": approved, "trust_level": _reference_trust_level(reference, status)}
        ),
    )
