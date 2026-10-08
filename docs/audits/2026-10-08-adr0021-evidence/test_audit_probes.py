"""Independent, offline probes of the pinned ADR-0021 integration."""
import time

import pytest

from proof_cli.proof_map import create_node, decide_trust_rule, get_reference_review_state
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference
from proof_agents.coordinator import ProjectPursuit, PursuitHooks
from proof_agents.proof_agent import ProofAgentContext
from proof_web.studios import StudioHub


@pytest.mark.parametrize("reuse", [False, True], ids=["default-other", "reuse-human-citation"])
def test_reader_import_must_not_gain_trust_without_own_review(tmp_path, reuse):
    store = ensure_project(tmp_path)
    if reuse:
        reference = ReferenceRecord(id="paper", title="Source", year=2020,
                                    source_type=ReferenceSourceType.research_paper,
                                    identifier="10.1000/example", created_by="human")
        conditions = [{"kind": "identifier_has_doi"}]
    else:
        reference = ReferenceRecord(id="paper", title="Source", year=2020, created_by="reader")
        conditions = [{"kind": "source_type_in", "values": ["other"]}]
    import_reference(store, reference)
    decide_trust_rule(store, "sources", "declare", conditions=conditions,
                      reviewer="Researcher <human@example.org>", rationale="the declared source class")
    # Same node-create arguments the Reader is permitted to use. No --identifier or --source-type.
    create_node(store, node_id="IMPORTED", kind="imported_result", statement="A Reader paraphrase",
                reference_id="paper", source_locator="Theorem 1", source_version="v1", created_by="reader")
    assert get_reference_review_state(store, "IMPORTED") == "unreviewed"


class RefusesRelease:
    def release(self):
        return {"error": "the node is still assigned", "code": "RELEASE_FAILED", "status": "release-failed"}


def test_project_stop_must_surface_coordinator_release_failure():
    pursuit = ProjectPursuit(PursuitHooks(read=lambda _: {}, theorems=lambda: ["T"],
                                        coordinator=lambda _: RefusesRelease()))
    pursuit.state.update(status="pursuing", current="T")
    result = pursuit.stop()
    assert result.get("code") == "RELEASE_FAILED", result
    assert result["status"] == "release-failed"


class BudgetCoordinator(RefusesRelease):
    def start(self, provider):
        return {"status": "budget"}

    def active(self):
        return False

    def view(self):
        return {"status": "budget", "reason": "budget spent; its run still owns a node"}


def test_next_theorem_waits_when_previous_release_failed():
    started = []
    class Tracked(BudgetCoordinator):
        def __init__(self, name):
            self.name = name
        def start(self, provider):
            started.append(self.name)
            return super().start(provider)
    coordinators = {name: Tracked(name) for name in ["T1", "T2"]}
    pursuit = ProjectPursuit(PursuitHooks(read=lambda _: {}, theorems=lambda: ["T1", "T2"],
                                        coordinator=coordinators.__getitem__))
    pursuit._loop("stub")
    assert started == ["T1"], started
    assert pursuit.view()["status"] == "release-failed"


def test_node_roles_can_read_the_definitions_created_by_reader(tmp_path):
    context = ProofAgentContext("T", tmp_path, role="verifier")
    args = context.claude_args(True)
    allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
    assert "Bash(proof definition list *)" in allowed
    assert "Bash(proof definition show *)" in allowed


def test_project_pursuit_ending_survives_a_new_hub(tmp_path):
    store = ensure_project(tmp_path)
    first = StudioHub(store)
    first._read_turn = lambda provider: {}
    first.pursuit_action("start", {"provider": "stub"})
    deadline = time.monotonic() + 2
    while first.pursuit().active() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert first.pursuit_view()["status"] == "stuck"
    first.close()
    second = StudioHub(store)
    try:
        assert second.pursuit_view()["status"] == "stuck"
    finally:
        second.close()
