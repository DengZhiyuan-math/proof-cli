"""The human side of a test: the researcher making Human Review decisions (ADR-0010).

Decisions are plain calls now — no passkey — made the way the proof map page
makes them. Methods mirror the service functions they call; the reviewer is
the git identity the test process has (or `reviewer_id` when set).
"""

from __future__ import annotations


class Researcher:
    def __init__(self, store, reviewer_id: str = "Researcher <researcher@example.org>") -> None:
        self.store = store
        self.reviewer_id = reviewer_id

    def _who(self, rationale: str) -> dict:
        return {"reviewer": self.reviewer_id, "rationale": rationale}

    def decide_acceptance(self, node_id: str, decision: str, *, rationale: str = ""):
        from proof_cli.proof_map import decide_acceptance

        return decide_acceptance(self.store, node_id, decision, **self._who(rationale))

    def decide_reference_review(self, node_id: str, decision: str = "reference-review", *, rationale: str = ""):
        from proof_cli.proof_map import decide_reference_review

        return decide_reference_review(self.store, node_id, decision, **self._who(rationale))

    def decide_evidence_review(self, check_id: str, decision: str, *, rationale: str = ""):
        from proof_cli.proof_map import decide_evidence_review

        return decide_evidence_review(self.store, check_id, decision, **self._who(rationale))

    def revalidate_dependency(self, node_id: str, target_node_id: str, *, rationale: str = ""):
        from proof_cli.proof_map import revalidate_dependency

        return revalidate_dependency(self.store, node_id, target_node_id, **self._who(rationale))

    def promote_to_lemma(self, node_id: str, *, rationale: str = ""):
        from proof_cli.proof_map import promote_to_lemma

        return promote_to_lemma(self.store, node_id, **self._who(rationale))

    def dismiss_challenge(self, challenge_id: str, *, rationale: str = ""):
        from proof_cli.proof_map import dismiss_challenge

        return dismiss_challenge(self.store, challenge_id, **self._who(rationale))


def researcher(store) -> Researcher:
    return Researcher(store)
