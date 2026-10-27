"""Existing projects switch to the five states once, on first open (ADR-0025 point 26; decided in #259, built in #282).

No migration flow and no confirmation: the first open by this version converts what the old records say, once. Most
of it is a reading already (an Acceptance or a Reference review reads verified, a no-longer-callable import sealed
false, a Verdict from before the switch no check); what the switch writes is a researcher's Challenge for each Rejected
node something still rests on, the release of the agents' claims, and the Uses of dependencies definitions in the
shared preamble. Before it, one copy of the database is kept; after it, one entry says what changed and how many.
Synthetic projects only."""

import sqlite3
import threading
from pathlib import Path

from typer.testing import CliRunner

from _proofs import submit_proof
from _researcher import researcher
from proof_cli.cli import app
from proof_cli.domain import Challenge
from proof_cli.five_states_switch import BACKUP_FILE, SWITCH_EVENT, SWITCHED_KEY
from proof_cli.node_states import node_states, stopped_by
from proof_cli.proof_map import PROGRESS_EVENT, claim_node, create_node, get_node, list_challenges
from proof_cli.pursuit import project_progress, record_pursuit
from proof_cli.storage import (append_event, ensure_project, get_active_claim, insert_challenge, list_events, list_events_of_kind,
                                update_proof_map_node)
from proof_cli.vault import PREAMBLE, USES_PREAMBLE, preamble_path, read_working_snapshot

OLD_PREAMBLE = PREAMBLE.replace(USES_PREAMBLE, "")


def _old_project(root: Path):
    """A project as the version before the switch left it: each case #259 converts, and no switch recorded."""
    store = ensure_project(root)
    reviewer = researcher(store)

    def submitted(node_id: str) -> None:
        submit_proof(store, node_id, claimant_id="claude-code", scoping_rationale="scoped", content=f"proof of {node_id}")

    create_node(store, node_id="ACC", kind="lemma", statement="an accepted lemma")
    submitted("ACC")
    reviewer.decide_acceptance("ACC", "accept")
    create_node(store, node_id="IMP", kind="imported_result", statement="a reviewed import", source_locator="Theorem 1", source_version="v1")
    reviewer.decide_reference_review("IMP")
    create_node(store, node_id="GONE", kind="imported_result", statement="an import found wanting", source_locator="Theorem 2", source_version="v1")
    reviewer.decide_reference_review("GONE", "no-longer-callable", rationale="the source was retracted")
    create_node(store, node_id="HIST", kind="claim", statement="a rejected claim nothing rests on")
    submitted("HIST")
    reviewer.decide_acceptance("HIST", "reject", rationale="the route does not work")
    create_node(store, node_id="REJ", kind="claim", statement="a rejected claim something rests on")
    submitted("REJ")
    reviewer.decide_acceptance("REJ", "reject", rationale="step 3 fails for n = 1")
    create_node(store, node_id="USER", kind="lemma", statement="a lemma resting on REJ", dependencies=["REJ"])
    create_node(store, node_id="DOUBT", kind="claim", statement="a claim with an old Challenge")
    insert_challenge(store, Challenge(id="old-1", target_node_id="DOUBT", opened_by="claude-code", rationale="DOUBT may not hold"))
    create_node(store, node_id="PASSED", kind="claim", statement="a claim passed under the old rules")
    append_event(store, PROGRESS_EVENT, "PASSED: verdict passed", entity_id="PASSED",  # a Verdict from before Verdicts had ids
                 payload={"kind": "verdict", "role": "verifier", "by": "claude-code", "outcome": "passed", "note": "holds",
                          "inputs_sha256": read_working_snapshot(root, "PASSED").digest()})
    claim_node(store, "USER", claimant_id="claude-code")
    claim_node(store, "DOUBT", claimant_id="human")   # the researcher's own: no run holds it
    record_pursuit(store, "start", provider="claude")   # a Pursue that never ended
    preamble_path(root).write_text(OLD_PREAMBLE, encoding="utf-8")
    with store.connect() as conn:   # made before this version: no switch recorded
        conn.execute("DELETE FROM project_meta WHERE key = ?", (SWITCHED_KEY,))
        conn.commit()
    return store


def _states(store, node_id: str) -> tuple:
    states = node_states(store, node_id)
    return states.seal, states.statement_layer, states.proof_layer


def test_an_old_project_switches_on_first_open_as_the_researcher_decided(tmp_path: Path):
    _old_project(tmp_path)
    store = ensure_project(tmp_path)   # this version's first open

    # 1. Accepted nodes and reviewed imports are verified, read from their decisions; nothing is sealed
    assert _states(store, "ACC") == ("unsealed", "unchallenged", "expert-verified")
    assert _states(store, "IMP") == ("unsealed", "unchallenged", "expert-verified")
    assert _states(store, "GONE")[0] == "sealed-false"   # no longer callable: sealed false
    # 2. a Rejected node nothing rests on is history; one something rests on is the researcher's Challenge, with the reason
    assert list_challenges(store, target_node_id="HIST") == []
    (raised,) = list_challenges(store, target_node_id="REJ")
    assert (raised.opened_by, raised.kind, raised.rationale, raised.status.value) == ("human", None, "step 3 fails for n = 1", "open")
    assert stopped_by(store, "USER") == ["REJ"]   # the branch using it waits, until the Coordinator classifies it
    # 3. an open Challenge stays its raiser's, its words kept, its kind left for the Coordinator
    (old,) = list_challenges(store, target_node_id="DOUBT")
    assert (old.id, old.opened_by, old.kind, old.rationale) == ("old-1", "claude-code", None, "DOUBT may not hold")
    # 4. a Verdict passed under the old rules is no check: the Proof layer is incomplete
    assert _states(store, "PASSED") == ("unsealed", "unchallenged", "incomplete")
    # 6. runs from before are interrupted: the agents' claims released, the researcher's kept, the Pursue unended
    assert get_active_claim(store, "USER") is None and get_active_claim(store, "DOUBT").claimant_id == "human"
    assert [pursuit["status"] for pursuit in project_progress(store)] == ["interrupted"]
    # the Uses of dependencies' definitions join the preamble as the researcher left it
    preamble = preamble_path(tmp_path).read_text(encoding="utf-8")
    assert preamble.startswith(OLD_PREAMBLE) and USES_PREAMBLE in preamble

    # one copy of the database from before, and one entry saying what changed and how many
    with sqlite3.connect(tmp_path / BACKUP_FILE) as copy:
        assert copy.execute("SELECT COUNT(*) FROM challenges WHERE target_node_id = 'REJ'").fetchone() == (0,)
        assert copy.execute("SELECT COUNT(*) FROM project_meta WHERE key = ?", (SWITCHED_KEY,)).fetchone() == (0,)
    (entry,) = list_events_of_kind(store, SWITCH_EVENT)
    assert entry.payload["counts"] == {"verified": 2, "sealed_false": 1, "rejected_history": 1, "rejected_challenged": 1,
                                       "challenges_to_classify": 2, "verdicts_not_counted": 1, "claims_released": 1,
                                       "pursuits_interrupted": 1, "preamble_completed": 1}
    assert entry.payload["backup"] == BACKUP_FILE.as_posix() and "switched to the five states" in entry.message
    history = CliRunner().invoke(app, ["history", "--root", str(tmp_path)]).output
    assert "five_states_switch: switched to the five states (ADR-0025): 2 verified, 1 sealed false, 1 rejected history" in history


def test_a_second_open_changes_nothing(tmp_path: Path):
    _old_project(tmp_path)
    store = ensure_project(tmp_path)
    events, preamble, copy = len(list_events(store)), preamble_path(tmp_path).read_bytes(), (tmp_path / BACKUP_FILE).read_bytes()
    store = ensure_project(tmp_path)
    assert len(list_events(store)) == events and preamble_path(tmp_path).read_bytes() == preamble
    assert (tmp_path / BACKUP_FILE).read_bytes() == copy and len(list_challenges(store, target_node_id="REJ")) == 1


def test_a_sealed_rejected_node_and_one_rested_on_only_by_history_are_history(tmp_path: Path):
    """A seal is the researcher's word after the rejection, and a sealed node is never challenged (ADR-0025 point 14): a
    Rejected node under a seal is history, as is one only a node that is history rests on. Neither stops the switch."""
    store = _old_project(tmp_path)
    reviewer = researcher(store)
    create_node(store, node_id="OLD", kind="claim", statement="rested on only by a Rejected claim nothing rests on")
    create_node(store, node_id="TOP", kind="claim", statement="a Rejected claim nothing rests on")
    for node_id in ("OLD", "TOP"):
        submit_proof(store, node_id, claimant_id="claude-code", scoping_rationale="scoped", content=f"proof of {node_id}")
        reviewer.decide_acceptance(node_id, "reject", rationale="no route")
    update_proof_map_node(store, get_node(store, "TOP").model_copy(update={"dependencies": ["OLD"]}))   # the old map's edge
    reviewer.seal("USER", True, rationale="known")   # covers REJ, which USER rests on
    with store.connect() as conn:
        conn.execute("DELETE FROM project_meta WHERE key = ?", (SWITCHED_KEY,))
        conn.commit()
    store = ensure_project(tmp_path)
    assert list_challenges(store, target_node_id="REJ") == [] and list_challenges(store, target_node_id="OLD") == []
    (entry,) = list_events_of_kind(store, SWITCH_EVENT)
    assert (entry.payload["counts"]["rejected_history"], entry.payload["counts"]["rejected_challenged"]) == (4, 0)   # HIST, OLD, TOP, REJ


def test_a_new_project_has_nothing_to_switch(tmp_path: Path):
    store = ensure_project(tmp_path)
    store = ensure_project(tmp_path)
    assert list_events_of_kind(store, SWITCH_EVENT) == [] and not (tmp_path / BACKUP_FILE).exists()


def test_a_switch_that_fails_leaves_the_project_open_says_why_and_runs_on_the_next_open(tmp_path: Path, capsys):
    """An old project the switch can't convert still opens, as it is: a hand-edited cycle, say, which the switch's reading
    refuses. The open says why, every command still runs (the edit that removes the cycle among them), and the next open
    switches."""
    store = _old_project(tmp_path)
    create_node(store, node_id="ONE", kind="claim", statement="one half of a cycle")
    create_node(store, node_id="TWO", kind="claim", statement="the other half", dependencies=["ONE"])
    update_proof_map_node(store, get_node(store, "ONE").model_copy(update={"dependencies": ["TWO"]}))   # edited by hand: a cycle

    store = ensure_project(tmp_path)
    said = capsys.readouterr().err
    assert "five states" in said and "DEPENDENCY_CYCLE" in said and "ONE" in said
    assert list_events_of_kind(store, SWITCH_EVENT) == [] and preamble_path(tmp_path).read_text(encoding="utf-8") == OLD_PREAMBLE
    removed = CliRunner().invoke(app, ["node", "depend", "ONE", "--remove", "TWO", "--root", str(tmp_path), "--json"])
    assert removed.exit_code == 0, removed.output

    store = ensure_project(tmp_path)
    assert len(list_events_of_kind(store, SWITCH_EVENT)) == 1 and len(list_challenges(store, target_node_id="REJ")) == 1


def test_two_first_opens_at_once_switch_once_and_keep_one_whole_copy(tmp_path: Path):
    """The page and a command opening an old project together: both open, one switches, and the copy kept from before is
    whole, with nothing half-written left beside it."""
    _old_project(tmp_path)
    together, failed = threading.Barrier(2), []

    def first_open() -> None:
        together.wait()
        try:
            ensure_project(tmp_path)
        except Exception as exc:  # noqa: BLE001 - what the test is about
            failed.append(exc)

    opens = [threading.Thread(target=first_open) for _ in range(2)]
    for thread in opens:
        thread.start()
    for thread in opens:
        thread.join()

    assert failed == []
    assert len(list_events_of_kind(ensure_project(tmp_path), SWITCH_EVENT)) == 1
    with sqlite3.connect(tmp_path / BACKUP_FILE) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert copy.execute("SELECT COUNT(*) FROM project_meta WHERE key = ?", (SWITCHED_KEY,)).fetchone() == (0,)
    assert [path.name for path in (tmp_path / BACKUP_FILE).parent.iterdir() if path.name.startswith(BACKUP_FILE.name + ".")] == []
