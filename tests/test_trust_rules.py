"""Trust rules: a standing Reference review the researcher declares in advance (ADR-0014, issue #134).

A rule is a Human Review decision recorded in the project-level, git-tracked
`proofs/trust-rules.jsonl`; a node that meets one reads `trusted-by-rule`, derived and
never written. The tests here drive the service layer the proof map page calls, through
the `_researcher` helper, and assert only what is observable: the lines in the file, the
commit's author, a node's acceptance and workflow state, the error codes.
"""

import json
import subprocess
from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import Researcher, researcher
from proof_cli.proof_map import (
    ProofMapError,
    create_node,
    get_acceptance_state,
    get_blocked_reason,
    get_frontier,
    get_reference_review_state,
    get_workflow_state,
    list_challenges,
    list_integrity_warnings,
    open_challenge,
    trust_rule_events,
    trust_rule_impact,
    trust_rules_of,
    would_meet_trust_rules,
)
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference, store_reference
from proof_cli.trust_rules import get_trust_rule, list_trust_rules, trust_rule_history

RUDIN = ReferenceRecord(id="rudin", title="Principles of Mathematical Analysis", authors=["Walter Rudin"], year=1976,
                        source_type=ReferenceSourceType.textbook, identifier="isbn:0-07-054235-X")
PAPER = ReferenceRecord(id="paper", title="A result", authors=["A. Author"], year=2021,
                        source_type=ReferenceSourceType.research_paper, identifier="arXiv:2101.01234")
BLOG = ReferenceRecord(id="blog", title="A blog post", authors=["Someone"], year=2020, source_type=ReferenceSourceType.website, url="https://example.org")

TEXTBOOKS = [{"kind": "source_type_in", "values": ["textbook", "monograph", "standard_reference"]}]
SAME_SOURCE = [{"kind": "source_already_reviewed"}]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Ada Researcher")
    _git(tmp_path, "config", "user.email", "ada@example.org")
    return tmp_path


def _project(root: Path):
    store = ensure_project(root)
    for reference in (RUDIN, PAPER, BLOG):
        import_reference(store, reference)
    return store


def _imported(store, node_id, reference_id, *, version="3rd edition", locator="Theorem 3.6"):
    return create_node(store, node_id=node_id, kind="imported_result", statement=f"result {node_id}",
                       source_locator=locator, source_version=version, reference_id=reference_id)


def _lines(store) -> list[dict]:
    path = store.root / "proofs" / "trust-rules.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def _codes(store) -> list[str]:
    return [warning.code for warning in list_integrity_warnings(store)]


# -- declaring, amending and retiring a rule -------------------------------------------------


def test_declaring_a_rule_is_a_line_in_the_projects_trust_rules_jsonl(tmp_path: Path):
    store = _project(tmp_path)

    record = researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="classical results in standard textbooks")

    (line,) = _lines(store)
    assert (line["kind"], line["decision"], line["object_type"], line["object_id"]) == ("trust_rule", "declare", "trust_rule", "textbooks")
    assert line["id"] == record.id and line["seq"] == 1
    assert line["reviewer"] == "Researcher <researcher@example.org>"
    assert line["rationale"] == "classical results in standard textbooks"
    assert line["payload"]["target_id"] == "textbooks" and line["payload"]["conditions"] == TEXTBOOKS
    (rule,) = list_trust_rules(store)
    assert (rule.name, rule.rationale, [c.model_dump(mode="json") for c in rule.conditions]) == ("textbooks", "classical results in standard textbooks", TEXTBOOKS)


def test_a_rule_is_committed_as_the_reviewers_git_identity(tmp_path: Path):
    root = _repo(tmp_path)
    store = _project(root)
    (root / "unrelated.txt").write_text("staged, not part of the decision")
    _git(root, "add", "unrelated.txt")

    Researcher(store, reviewer_id=None).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    assert _git(root, "log", "-1", "--format=%an <%ae>").strip() == "Ada Researcher <ada@example.org>"
    assert set(_git(root, "show", "--name-only", "--format=", "HEAD").split()) == {"proofs/trust-rules.jsonl"}
    assert _git(root, "log", "-1", "--format=%s").strip() == "trust rule textbooks: declare"
    assert "A  unrelated.txt" in _git(root, "status", "--porcelain")
    assert _lines(store)[0]["reviewer"] == "Ada Researcher <ada@example.org>"
    assert "REVIEWS_NOT_COMMITTED" not in _codes(store)


def test_outside_a_git_repo_a_rule_is_still_recorded(tmp_path: Path):
    store = _project(tmp_path)
    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    assert [rule.name for rule in list_trust_rules(store)] == ["textbooks"]
    assert _lines(store)[0]["decision"] == "declare"


def test_a_rule_git_doesnt_have_yet_is_warned_about_like_any_decision(tmp_path: Path):
    root = _repo(tmp_path)
    store = _project(root)
    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    path = root / "proofs" / "trust-rules.jsonl"
    path.write_text(path.read_text() + "{not json\n")

    warnings = {warning.code: warning.details for warning in list_integrity_warnings(store)}
    assert warnings["REVIEWS_NOT_COMMITTED"]["path"] == "proofs/trust-rules.jsonl"
    assert warnings["REVIEW_LINE_UNREADABLE"]["line"] == "trust-rules.jsonl line 2"
    assert [rule.name for rule in list_trust_rules(store)] == ["textbooks"]  # the readable line still counts


def test_amending_keeps_the_name_and_adds_a_decision_with_the_new_rationale_and_conditions(tmp_path: Path):
    store = _project(tmp_path)
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    reviewer.amend_trust_rule("textbooks", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="monographs need a look after all")

    assert [(line["decision"], line["seq"]) for line in _lines(store)] == [("declare", 1), ("amend", 2)]
    (rule,) = list_trust_rules(store)
    assert rule.rationale == "monographs need a look after all"
    assert [c.model_dump(mode="json") for c in rule.conditions] == [{"kind": "source_type_in", "values": ["textbook"]}]
    assert [row["decision"] for row in trust_rule_history(store, "textbooks")] == ["declare", "amend"]


def test_retiring_a_rule_stops_it_counting_and_keeps_its_history_readable(tmp_path: Path):
    store = _project(tmp_path)
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    reviewer.retire_trust_rule("textbooks", rationale="reviewing each citation after all")

    assert list_trust_rules(store) == []
    retired = get_trust_rule(store, "textbooks")
    assert retired is not None and retired.retired
    assert [row["decision"] for row in trust_rule_history(store, "textbooks")] == ["declare", "retire"]
    assert [rule.name for rule in list_trust_rules(store, include_retired=True)] == ["textbooks"]


def test_a_retired_rules_name_cannot_be_used_again(tmp_path: Path):
    store = _project(tmp_path)
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    reviewer.retire_trust_rule("textbooks", rationale="done with it")

    with pytest.raises(ProofMapError) as taken:
        reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="again")
    assert taken.value.code == "TRUST_RULE_NAME_TAKEN"
    with pytest.raises(ProofMapError) as amend:
        reviewer.amend_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="again")
    assert amend.value.code == "TRUST_RULE_RETIRED"


@pytest.mark.parametrize("call, code", [
    (lambda r: r.declare_trust_rule("empty", conditions=[], rationale="trust everything"), "TRUST_RULE_EMPTY"),
    (lambda r: r.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="twice"), "TRUST_RULE_NAME_TAKEN"),
    (lambda r: r.declare_trust_rule("no-reason", conditions=TEXTBOOKS, rationale=""), "TRUST_RULE_RATIONALE_REQUIRED"),
    (lambda r: r.declare_trust_rule("bad name!", conditions=TEXTBOOKS, rationale="why"), "TRUST_RULE_INVALID_NAME"),
    (lambda r: r.declare_trust_rule("odd", conditions=[{"kind": "trust_level_is", "values": ["foundational"]}], rationale="why"), "TRUST_RULE_INVALID_CONDITION"),
    (lambda r: r.declare_trust_rule("odd", conditions=[{"kind": "source_type_in", "values": ["blog"]}], rationale="why"), "TRUST_RULE_INVALID_CONDITION"),
    (lambda r: r.declare_trust_rule("odd", conditions=[{"kind": "source_type_in", "values": []}], rationale="why"), "TRUST_RULE_INVALID_CONDITION"),
    (lambda r: r.amend_trust_rule("nothing", conditions=TEXTBOOKS, rationale="why"), "TRUST_RULE_NOT_FOUND"),
    (lambda r: r.retire_trust_rule("nothing", rationale="why"), "TRUST_RULE_NOT_FOUND"),
    (lambda r: r.amend_trust_rule("textbooks", conditions=[], rationale="why"), "TRUST_RULE_EMPTY"),
])
def test_a_rule_that_cannot_be_recorded_is_refused_with_its_code(tmp_path: Path, call, code):
    store = _project(tmp_path)
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    before = _lines(store)

    with pytest.raises(ProofMapError) as refused:
        call(reviewer)

    assert refused.value.code == code
    assert _lines(store) == before  # nothing was written


# -- what a rule does to a node ---------------------------------------------------------------


def test_an_imported_result_meeting_a_rule_reads_trusted_by_rule_with_the_rules_name(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    assert get_reference_review_state(store, "ref_bw") == "unreviewed"

    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule"
    assert trust_rules_of(store, "ref_bw") == ["textbooks"]
    assert get_acceptance_state(store, "ref_bw") == "unreviewed"  # the acceptance decision axis is untouched


def test_a_trusted_by_rule_dependency_unblocks_its_dependents_like_a_reviewed_one(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    create_node(store, node_id="clm_1", kind="claim", statement="uses it", dependencies=["ref_bw"])
    assert get_workflow_state(store, "clm_1") == "blocked"
    assert get_blocked_reason(store, "clm_1") == "not-accepted"

    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    assert get_workflow_state(store, "clm_1") == "open"
    assert [node.id for node in get_frontier(store)] == ["clm_1"]


def test_conditions_within_a_rule_all_have_to_hold_and_rules_each_count_on_their_own(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")  # a textbook with an ISBN, no DOI
    _imported(store, "ref_paper", "paper")  # a paper on the arXiv
    reviewer = researcher(store)

    reviewer.declare_trust_rule("textbooks-with-doi", conditions=[*TEXTBOOKS, {"kind": "identifier_has_doi"}], rationale="both")
    assert get_reference_review_state(store, "ref_bw") == "unreviewed"

    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="either")
    reviewer.declare_trust_rule("arxiv", conditions=[{"kind": "identifier_has_arxiv"}], rationale="preprints")
    assert trust_rules_of(store, "ref_bw") == ["textbooks"]
    assert trust_rules_of(store, "ref_paper") == ["arxiv"]
    assert get_reference_review_state(store, "ref_paper") == "trusted-by-rule"


@pytest.mark.parametrize("identifier, doi, arxiv", [
    ("10.1007/978-3-540-27752-1", True, False),
    ("doi:10.1090/S0002-9947-1985-0776393-6", True, False),
    ("https://doi.org/10.2307/1968726", True, False),
    ("arXiv:2101.01234", False, True),
    ("arXiv:2101.01234v2", False, True),
    ("math/0601001", False, True),
    ("https://arxiv.org/abs/2101.01234", False, True),
    ("https://arxiv.org/pdf/math.AG/0601001", False, True),
    ("isbn:0-07-054235-X", False, False),
    ("MR0385023", False, False),
    ("", False, False),
])
def test_doi_and_arxiv_are_recognised_by_pattern_from_the_identifier(tmp_path: Path, identifier, doi, arxiv):
    store = ensure_project(tmp_path)
    import_reference(store, ReferenceRecord(id="r", title="t", year=2000, identifier=identifier))
    _imported(store, "ref", "r")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("doi", conditions=[{"kind": "identifier_has_doi"}], rationale="resolvable")
    reviewer.declare_trust_rule("arxiv", conditions=[{"kind": "identifier_has_arxiv"}], rationale="resolvable")

    assert trust_rules_of(store, "ref") == [name for name, hit in (("doi", doi), ("arxiv", arxiv)) if hit]


def test_an_imported_result_without_a_reference_id_never_matches(tmp_path: Path):
    store = _project(tmp_path)
    create_node(store, node_id="legacy", kind="imported_result", statement="old", source_locator="Rudin, Thm 3.6", source_version="3rd")
    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    assert get_reference_review_state(store, "legacy") == "unreviewed" and trust_rules_of(store, "legacy") == []


def test_a_rule_reads_the_citations_fields_as_they_are_now(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule"

    store_reference(store, RUDIN.model_copy(update={"source_type": ReferenceSourceType.website}))

    assert get_reference_review_state(store, "ref_bw") == "unreviewed"


# -- `source already reviewed` ----------------------------------------------------------------


def test_source_already_reviewed_trusts_another_citation_of_the_same_source_at_the_same_version(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_a", "rudin", locator="Theorem 3.6")
    _imported(store, "ref_b", "rudin", locator="Theorem 7.8")  # same version, another theorem
    _imported(store, "ref_c", "rudin", locator="Theorem 3.6", version="2nd edition")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("same-source", conditions=SAME_SOURCE, rationale="one look per edition")
    assert get_reference_review_state(store, "ref_b") == "unreviewed"

    reviewer.decide_reference_review("ref_a", rationale="checked the edition")

    assert get_reference_review_state(store, "ref_a") == "reviewed"
    assert get_reference_review_state(store, "ref_b") == "trusted-by-rule"
    assert get_reference_review_state(store, "ref_c") == "unreviewed"  # another version: its own look


def test_source_already_reviewed_never_rests_on_another_trusted_by_rule_node(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_a", "rudin")
    _imported(store, "ref_b", "rudin", locator="Theorem 7.8")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    reviewer.declare_trust_rule("same-source", conditions=SAME_SOURCE, rationale="one look per edition")

    # both are trusted by the textbook rule; neither is an explicit review the other could rest on
    assert trust_rules_of(store, "ref_a") == ["textbooks"] and trust_rules_of(store, "ref_b") == ["textbooks"]


def test_a_no_longer_callable_citation_poisons_every_other_citation_of_that_source(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_a", "rudin")
    _imported(store, "ref_b", "rudin", locator="Theorem 7.8")
    _imported(store, "ref_c", "rudin", locator="Theorem 9.1")
    create_node(store, node_id="clm_1", kind="claim", statement="uses c", dependencies=["ref_c"])
    reviewer = researcher(store)
    reviewer.declare_trust_rule("same-source", conditions=SAME_SOURCE, rationale="one look per edition")
    reviewer.decide_reference_review("ref_a", rationale="checked")
    reviewer.decide_reference_review("ref_b", rationale="checked too")
    assert get_reference_review_state(store, "ref_c") == "trusted-by-rule" and get_workflow_state(store, "clm_1") == "open"

    reviewer.decide_reference_review("ref_b", "no-longer-callable", rationale="the edition has an error here")

    assert get_reference_review_state(store, "ref_c") == "unreviewed"
    assert get_workflow_state(store, "clm_1") == "blocked"


# -- precedence -------------------------------------------------------------------------------


def test_an_explicit_reference_review_takes_precedence_over_a_rule(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    reviewer.decide_reference_review("ref_bw", rationale="matched trust rule textbooks; reviewed explicitly")
    assert get_reference_review_state(store, "ref_bw") == "reviewed"
    assert trust_rules_of(store, "ref_bw") == ["textbooks"]  # still listed: the rule matches, the review counts

    reviewer.retire_trust_rule("textbooks", rationale="not needed")
    assert get_reference_review_state(store, "ref_bw") == "reviewed"


def test_no_longer_callable_is_final_whatever_the_rules_say(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.decide_reference_review("ref_bw", "no-longer-callable", rationale="wrong")
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    assert get_reference_review_state(store, "ref_bw") == "no-longer-callable"
    assert trust_rules_of(store, "ref_bw") == []


def test_a_rule_applies_when_the_explicit_review_no_longer_counts(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.decide_reference_review("ref_bw", rationale="checked")
    path = store.root / "proofs" / "ref_bw" / "reviews.jsonl"
    line = json.loads(path.read_text())
    line["payload"]["interface_fingerprint"] = "made on something else"  # a decision that no longer binds this node
    path.write_text(json.dumps(line) + "\n")
    assert get_reference_review_state(store, "ref_bw") == "unverifiable"

    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule"


# -- tightening or retiring a rule ------------------------------------------------------------


def _accepted_on(store, node_id, dependency):
    create_node(store, node_id=node_id, kind="claim", statement=f"{node_id} uses {dependency}", dependencies=[dependency])
    submit_proof(store, node_id, claimant_id="agent_a", scoping_rationale="scoped", content=f"\\begin{{proof}}{node_id}.\\end{{proof}}\n")
    researcher(store).decide_acceptance(node_id, "accept", rationale="fine")


def test_retiring_a_rule_blocks_unaccepted_dependents_and_leaves_accepted_ones_accepted(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    _accepted_on(store, "clm_done", "ref_bw")
    create_node(store, node_id="clm_open", kind="claim", statement="not yet", dependencies=["ref_bw"])
    assert get_workflow_state(store, "clm_open") == "open"

    reviewer.retire_trust_rule("textbooks", rationale="each citation gets a look")

    assert get_reference_review_state(store, "ref_bw") == "unreviewed"
    assert get_workflow_state(store, "clm_open") == "blocked"
    assert get_acceptance_state(store, "clm_done") == "accepted" and get_workflow_state(store, "clm_done") != "blocked"


def test_a_node_stays_trusted_while_one_of_several_matching_rules_remains(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    reviewer.declare_trust_rule("rudin", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="redundant")
    assert trust_rules_of(store, "ref_bw") == ["textbooks", "rudin"]

    reviewer.retire_trust_rule("rudin", rationale="redundant")

    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule" and trust_rules_of(store, "ref_bw") == ["textbooks"]


def test_the_impact_of_tightening_or_retiring_is_previewed_without_recording_anything(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    _imported(store, "ref_paper", "paper")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("wide", conditions=[{"kind": "source_type_in", "values": ["textbook", "research_paper"]}], rationale="wide")
    _accepted_on(store, "clm_done", "ref_bw")
    create_node(store, node_id="clm_open", kind="claim", statement="not yet", dependencies=["ref_paper"])

    retire = trust_rule_impact(store, "wide")
    assert retire == {"losing": ["ref_bw", "ref_paper"], "depended_on_by_accepted": ["ref_bw"], "gaining": []}
    tighten = trust_rule_impact(store, "wide", conditions=[{"kind": "source_type_in", "values": ["textbook"]}])
    assert tighten == {"losing": ["ref_paper"], "depended_on_by_accepted": [], "gaining": []}
    assert [row["decision"] for row in trust_rule_history(store, "wide")] == ["declare"]  # nothing recorded
    assert get_reference_review_state(store, "ref_paper") == "trusted-by-rule"


# -- Challenges, history and the reviewer's own decision ---------------------------------------


def test_a_challenge_on_a_trusted_by_rule_node_opens_and_is_resolved_only_explicitly(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")

    challenge = open_challenge(store, "ref_bw", opened_by="agent_b", rationale="the hypothesis differs in this edition")

    assert challenge.status.value == "open"
    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule"
    reviewer.amend_trust_rule("textbooks", conditions=[*TEXTBOOKS, {"kind": "identifier_has_doi"}], rationale="no rule answers a Challenge")
    reviewer.declare_trust_rule("textbooks-again", conditions=TEXTBOOKS, rationale="nor a new one")
    assert challenge.id in [c.id for c in list_challenges(store, status="open")]
    reviewer.decide_reference_review("ref_bw", rationale="matched trust rule textbooks; reviewed explicitly")
    assert get_reference_review_state(store, "ref_bw") == "reviewed"


def test_the_first_time_a_node_meets_a_rule_is_on_record_as_an_event_not_a_decision(tmp_path: Path):
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    reviewer.declare_trust_rule("rudin", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="again")
    get_reference_review_state(store, "ref_bw")  # reading the state again writes nothing
    _imported(store, "ref_later", "rudin", locator="Theorem 7.8")  # created after the rule: met on creation

    assert [(event.entity_id, event.payload["rule"]) for event in trust_rule_events(store)] == [("ref_bw", "textbooks"), ("ref_bw", "rudin"), ("ref_later", "textbooks"), ("ref_later", "rudin")]
    assert not (store.root / "proofs" / "ref_bw" / "reviews.jsonl").exists()
    reviewer.amend_trust_rule("rudin", conditions=[{"kind": "source_type_in", "values": ["textbook"]}], rationale="a change, not a first match")
    assert len(trust_rule_events(store)) == 4


def test_a_line_whose_conditions_this_version_cannot_read_is_warned_about_and_ignored(tmp_path: Path):
    """A hand-edited or later-vocabulary condition is a problem the warnings page names, never a crash on every read."""
    store = _project(tmp_path)
    _imported(store, "ref_bw", "rudin")
    reviewer = researcher(store)
    reviewer.declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    reviewer.declare_trust_rule("odd", conditions=[{"kind": "identifier_has_doi"}], rationale="edited below")
    path = store.root / "proofs" / "trust-rules.jsonl"
    lines = path.read_text().splitlines()
    lines[1] = lines[1].replace("identifier_has_doi", "author_is_famous")
    path.write_text("\n".join(lines) + "\n")

    assert [rule.name for rule in list_trust_rules(store)] == ["textbooks"]
    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule"
    (problem,) = [warning for warning in list_integrity_warnings(store) if warning.code == "REVIEW_LINE_UNREADABLE"]
    assert problem.details["line"].startswith("trust-rules.jsonl line 2")


# -- the decision file's name is not a node's -------------------------------------------------------


@pytest.mark.parametrize("node_id", ["trust-rules.jsonl", "TRUST-RULES.JSONL", "Trust-Rules.jsonl", "preamble.tex", "PREAMBLE.TEX"])
def test_the_vaults_own_file_names_cannot_name_a_node(tmp_path: Path, node_id):
    """A node folder of that name would stand where the file goes (`proofs/<name>`) — on a case-insensitive file
    system in any letter case: refused on creation, split and import."""
    from proof_cli.exchange import export_exchange_bundle, import_exchange_bundle, parse_bundle
    from proof_cli.proof_map import split_node

    store = _project(tmp_path)
    with pytest.raises(ProofMapError) as refused:
        create_node(store, node_id=node_id, kind="claim", statement="squatting")
    assert refused.value.code == "INVALID_NODE_ID" and not (store.root / "proofs" / node_id).is_dir()
    create_node(store, node_id="lem", kind="lemma", statement="L")
    with pytest.raises(ProofMapError) as split:
        split_node(store, "lem", [{"id": node_id, "statement": "half"}], created_by="agent_a")
    assert split.value.code == "INVALID_NODE_ID" and not (store.root / "proofs" / node_id).is_dir()
    other = ensure_project(tmp_path / "other")
    create_node(other, node_id="ok", kind="claim", statement="fine")
    bundle = parse_bundle(export_exchange_bundle(other).model_dump(mode="json"))
    bundle.proof_map_nodes[0].id = node_id
    with pytest.raises(ProofMapError) as imported:
        import_exchange_bundle(store, bundle)
    assert imported.value.code == "INVALID_NODE_ID"


def test_a_project_where_a_node_already_took_the_files_place_refuses_rules_instead_of_crashing(tmp_path: Path):
    """Built before ADR-0014, a project may hold a node named trust-rules.jsonl: reads see no rules, a declaration says why."""
    store = _project(tmp_path)
    (store.root / "proofs" / "trust-rules.jsonl").mkdir(parents=True)  # the node folder such a project has
    _imported(store, "ref_bw", "rudin")

    assert list_trust_rules(store) == [] and get_reference_review_state(store, "ref_bw") == "unreviewed"
    with pytest.raises(ProofMapError) as refused:
        researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    assert refused.value.code == "TRUST_RULES_FILE_BLOCKED"
    assert "REVIEWS_NOT_COMMITTED" not in _codes(store)


# -- an agent's import meets no rule (ADR-0022) -------------------------------------------------


def _agent_imported(store, node_id, reference_id, *, by="reader", version="3rd edition"):
    return create_node(store, node_id=node_id, kind="imported_result", statement=f"the reader's paraphrase of {node_id}",
                       source_locator="Theorem 3.6", source_version=version, reference_id=reference_id, created_by=by)


def test_an_imported_result_an_agent_created_meets_no_rule_but_shows_the_rules_it_would_meet(tmp_path: Path):
    store = _project(tmp_path)
    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    _agent_imported(store, "ref_agent", "rudin")
    _imported(store, "ref_human", "rudin")

    assert get_reference_review_state(store, "ref_agent") == "unreviewed"
    assert trust_rules_of(store, "ref_agent") == []
    assert would_meet_trust_rules(store, "ref_agent") == ["textbooks"]
    assert trust_rule_events(store, "ref_agent") == []
    # the researcher's own import is unchanged (ADR-0022 point 4)
    assert get_reference_review_state(store, "ref_human") == "trusted-by-rule"
    assert would_meet_trust_rules(store, "ref_human") == []


def test_the_nodes_author_decides_not_the_citations(tmp_path: Path):
    """A Reader import of a citation the researcher imported with a DOI, or of a source the researcher already
    reviewed, still needs its own Reference review (ADR-0022 point 2; the audit's two paths)."""
    store = _project(tmp_path)
    store_reference(store, ReferenceRecord(id="doi", title="A paper", year=2020, source_type=ReferenceSourceType.research_paper,
                                           identifier="10.1000/example", created_by="human"))
    researcher(store).declare_trust_rule("dois", conditions=[{"kind": "identifier_has_doi"}], rationale="published papers")
    researcher(store).declare_trust_rule("same-source", conditions=SAME_SOURCE, rationale="a source read once")
    researcher(store).declare_trust_rule("other", conditions=[{"kind": "source_type_in", "values": ["other"]}], rationale="anything")
    _imported(store, "ref_read", "paper", version="v1")
    researcher(store).decide_reference_review("ref_read", rationale="read it")
    _agent_imported(store, "ref_doi", "doi")
    _agent_imported(store, "ref_same", "paper", version="v1")

    assert get_reference_review_state(store, "ref_doi") == "unreviewed"
    assert get_reference_review_state(store, "ref_same") == "unreviewed"
    assert would_meet_trust_rules(store, "ref_same") == ["same-source"]


def test_an_agents_import_gains_standing_only_by_its_own_reference_review(tmp_path: Path):
    store = _project(tmp_path)
    researcher(store).declare_trust_rule("textbooks", conditions=TEXTBOOKS, rationale="standard textbooks")
    _agent_imported(store, "ref_agent", "rudin")
    create_node(store, node_id="clm_1", kind="claim", statement="uses it", dependencies=["ref_agent"])
    assert get_blocked_reason(store, "clm_1") == "not-accepted"
    assert trust_rule_impact(store, "textbooks") == {"losing": [], "depended_on_by_accepted": [], "gaining": []}

    researcher(store).decide_reference_review("ref_agent", rationale="read against Rudin 3.6")

    assert get_reference_review_state(store, "ref_agent") == "reviewed"
    assert get_workflow_state(store, "clm_1") == "open"
