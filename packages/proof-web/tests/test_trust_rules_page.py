"""Trust rules on the proof map page (ADR-0014, issue #134): the review page's Trusted by rule section, the
rules the manage sheet reads, the impact preview, and the three decisions recorded through `/api/decide`.

Driven through `ReviewApp` directly (`DirectClient`), like the other page tests.
"""

from pathlib import Path

import pytest

from _proofs import submit_proof
from _researcher import researcher
from _review_client import DirectClient, decide
from proof_cli.proof_map import create_node, get_reference_review_state, trust_rules_of
from proof_cli.references import ReferenceRecord, ReferenceSourceType
from proof_cli.storage import ensure_project, import_reference
from proof_cli.trust_rules import list_trust_rules

RUDIN = ReferenceRecord(id="rudin", title="Principles of Mathematical Analysis", authors=["Walter Rudin"], year=1976,
                        source_type=ReferenceSourceType.textbook, identifier="isbn:0-07-054235-X")
TEXTBOOKS = [{"kind": "source_type_in", "values": ["textbook", "monograph"]}]


@pytest.fixture
def page(tmp_path: Path):
    store = ensure_project(tmp_path)
    import_reference(store, RUDIN)
    yield store, DirectClient(store)


def _imported(store, node_id="ref_bw", locator="Theorem 3.6"):
    return create_node(store, node_id=node_id, kind="imported_result", statement=f"result {node_id}", source_locator=locator,
                       source_version="3rd edition", reference_id="rudin")


def _rule(client, name="textbooks", decision="declare", conditions=TEXTBOOKS, rationale="standard textbooks"):
    return decide(client, [{"kind": "trust_rule", "target_id": name, "decision": decision, "rationale": rationale, "conditions": conditions}])


# -- declaring from the page ---------------------------------------------------------------------


def test_a_rule_is_declared_through_the_pages_decide_api(page):
    store, client = page
    _imported(store)

    status, outcome = _rule(client)

    assert status == 200
    (result,) = outcome["data"]["results"]
    assert result["ok"] and result["target_id"] == "textbooks"
    assert (result["result"]["kind"], result["result"]["decision"], result["result"]["name"]) == ("trust_rule", "declare", "textbooks")
    assert [rule.name for rule in list_trust_rules(store)] == ["textbooks"]
    assert get_reference_review_state(store, "ref_bw") == "trusted-by-rule"


@pytest.mark.parametrize("decision, conditions, code", [
    ("declare", [], "TRUST_RULE_EMPTY"),
    ("declare", None, "TRUST_RULE_EMPTY"),
    ("amend", [{"kind": "identifier_has_doi"}], "TRUST_RULE_NOT_FOUND"),
    ("revoke", TEXTBOOKS, "INVALID_DECISION"),
])
def test_a_rule_the_page_cannot_record_is_refused_with_its_code(page, decision, conditions, code):
    store, client = page
    status, outcome = decide(client, [{"kind": "trust_rule", "target_id": "other", "decision": decision, "rationale": "why",
                                       **({"conditions": conditions} if conditions is not None else {})}])
    assert status == 200
    (result,) = outcome["data"]["results"]
    assert not result["ok"] and result["error"]["code"] == code
    assert list_trust_rules(store, include_retired=True) == []


def test_amending_and_retiring_from_the_page_change_what_the_nodes_read(page):
    store, client = page
    _imported(store)
    _rule(client)

    _, amended = _rule(client, decision="amend", conditions=[{"kind": "identifier_has_doi"}], rationale="an ISBN isn't enough")
    assert amended["data"]["results"][0]["ok"]
    assert get_reference_review_state(store, "ref_bw") == "unreviewed"

    _, retired = _rule(client, decision="retire", conditions=None, rationale="done")
    assert retired["data"]["results"][0]["ok"]
    assert list_trust_rules(store) == [] and list_trust_rules(store, include_retired=True)[0].retired


# -- what the review page shows ---------------------------------------------------------------------


def test_the_review_page_lists_trusted_by_rule_nodes_apart_from_what_awaits_the_researcher(page):
    store, client = page
    _imported(store, "ref_bw")
    _imported(store, "ref_other", locator="Theorem 7.8")
    create_node(store, node_id="ref_legacy", kind="imported_result", statement="no citation", source_locator="x", source_version="1")
    _rule(client)
    researcher(store).decide_reference_review("ref_other", rationale="looked at it myself")

    _, state = client.get("/api/state")

    assert [item["node_id"] for item in state["data"]["pending"]] == ["ref_legacy"]  # the only one awaiting a decision
    (trusted,) = state["data"]["trusted_by_rule"]
    assert trusted["node_id"] == "ref_bw" and trusted["trust_rule"] == ["textbooks"]
    assert trusted["citation"]["reference_id"] == "rudin"
    assert trusted["rationale"] == "matched trust rule textbooks; reviewed explicitly"
    assert set(trusted["bindings"]) == {"reference-review", "no-longer-callable"} and all(trusted["bindings"].values())


def test_reviewing_a_trusted_by_rule_node_explicitly_records_an_ordinary_reference_review(page):
    store, client = page
    _imported(store)
    _rule(client)
    _, state = client.get("/api/state")
    (trusted,) = state["data"]["trusted_by_rule"]

    status, outcome = decide(client, [{"kind": "reference_review", "target_id": "ref_bw", "decision": "reference-review",
                                       "rationale": trusted["rationale"], "binding": trusted["bindings"]["reference-review"]}])

    assert outcome["data"]["results"][0]["ok"]
    assert get_reference_review_state(store, "ref_bw") == "reviewed"
    _, after = client.get("/api/state")
    assert after["data"]["trusted_by_rule"] == []


def test_the_map_the_node_page_and_a_dependents_page_name_the_matching_rules(page):
    store, client = page
    _imported(store)
    create_node(store, node_id="clm_1", kind="claim", statement="uses it", dependencies=["ref_bw"])
    _rule(client)

    _, map_ = client.get("/api/map")
    (node,) = [n for n in map_["data"]["nodes"] if n["id"] == "ref_bw"]
    assert node["acceptance_state"] == "trusted-by-rule" and node["trust_rule"] == ["textbooks"]
    (claim,) = [n for n in map_["data"]["nodes"] if n["id"] == "clm_1"]
    assert claim["workflow_state"] == "open" and claim["frontier"]

    _, view = client.get("/api/node/ref_bw")
    assert view["data"]["acceptance_state"] == "trusted-by-rule" and view["data"]["trust_rule"] == ["textbooks"]
    (event,) = view["data"]["rule_events"]
    assert event["rule"] == "textbooks" and event["at"]
    assert view["data"]["history"] == []  # no decision line was written
    assert {d["decision"] for d in view["data"]["decisions"] if d["kind"] == "reference_review"} == {"reference-review", "no-longer-callable"}

    _, dependent = client.get("/api/node/clm_1")
    (dependency,) = dependent["data"]["dependencies"]
    assert dependency["trust_rule"] == ["textbooks"]


# -- the manage sheet -------------------------------------------------------------------------------


def test_the_rules_are_listed_with_their_history_and_what_they_trust(page):
    store, client = page
    _imported(store)
    _rule(client)
    _rule(client, name="old", rationale="retired soon")
    _rule(client, name="old", decision="retire", conditions=None, rationale="not needed")

    _, listed = client.get("/api/trust-rules")

    rules = {rule["name"]: rule for rule in listed["data"]["rules"]}
    assert set(rules) == {"textbooks", "old"}
    assert rules["textbooks"]["conditions_text"] == ["source_type in {textbook, monograph}"] and rules["textbooks"]["trusting"] == ["ref_bw"]
    assert not rules["textbooks"]["retired"] and rules["old"]["retired"] and rules["old"]["trusting"] == []
    assert [row["decision"] for row in rules["old"]["history"]] == ["declare", "retire"]
    assert listed["data"]["source_types"][0] == "standard_reference" and listed["data"]["weak_source_types"] == ["website", "other"]


def test_the_impact_of_a_change_is_previewed_before_it_is_recorded(page):
    store, client = page
    _imported(store)
    create_node(store, node_id="clm_done", kind="claim", statement="uses it", dependencies=["ref_bw"])
    _rule(client)
    submit_proof(store, "clm_done", claimant_id="agent_a", scoping_rationale="scoped", content="\\begin{proof}ok.\\end{proof}\n")
    researcher(store).decide_acceptance("clm_done", "accept", rationale="fine")

    status, preview = client.post("/api/trust-rules/preview", {"name": "textbooks", "decision": "retire"})
    assert status == 200 and preview["data"] == {"losing": ["ref_bw"], "depended_on_by_accepted": ["ref_bw"], "gaining": []}

    _, widened = client.post("/api/trust-rules/preview", {"name": "textbooks", "decision": "amend", "conditions": [{"kind": "source_type_in", "values": ["textbook", "website"]}]})
    assert widened["data"] == {"losing": [], "depended_on_by_accepted": [], "gaining": []}

    status, missing = client.post("/api/trust-rules/preview", {"name": "nothing", "decision": "retire"})
    assert status == 400 and missing["error"]["code"] == "TRUST_RULE_NOT_FOUND"
    assert trust_rules_of(store, "ref_bw") == ["textbooks"]  # nothing was recorded
