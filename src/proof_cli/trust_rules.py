"""Trust rules: a standing Reference review the researcher declares in advance (ADR-0014, issue #134).

A Trust rule says "any Imported result whose citation meets these conditions may be
depended on without a review of its own". It is a Human Review decision like every
other: declared, amended and retired only by the researcher, on the proof map page,
and recorded as one line of the project-level, git-tracked `proofs/trust-rules.jsonl`,
committed as the reviewer's git identity. The rule set in force is the file folded
from the start: `declare` creates a rule, `amend` replaces its rationale and
conditions under the same name, `retire` ends it and takes the name out of use.

A node that meets a rule gets no decision line: its state is derived every time it
is read (`proof_map.get_reference_review_state`, `trusted-by-rule`). The conditions
are a closed vocabulary ranked by who could fabricate them (ADR-0014 point 3):
`source already reviewed` rests on the researcher's own explicit decision on another
citation of the same source; `source_type in {…}`, `identifier has DOI` and
`identifier has arXiv` read the citation's typed metadata. Conditions within a rule
conjoin; rules disjoin. Never a condition: the node's own trust level, free text,
library folders.

This module holds the file, the fold, the vocabulary and the pure matcher. Reading a
node's state from the rules, and the impact of changing one, is `proof_map`'s.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .references import ReferenceRecord, ReferenceSourceType
from .reviews import (
    DecisionKind,
    DecisionPayload,
    ReviewEntry,
    append_line,
    commit_decision,
    git_identity,
    TRUST_RULES_FILE,
    load_trust_rule_entries,
    new_review_id,
    trust_rules_path,
)
from .storage import ProjectStore, after_commit, before_commit, memoized_read

TRUST_RULE_OBJECT_TYPE = "trust_rule"
TRUST_RULE_DECISIONS = ("declare", "amend", "retire")
# a rule's name appears on chips and in events, and never changes: a short plain token
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class TrustRuleError(Exception):
    """A rule that can't be recorded as asked; `code` is what the page and the CLI show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# -- the condition vocabulary (v1) ------------------------------------------------------


class TrustConditionKind(str, Enum):
    # agent-proof: rests on the researcher's explicit Reference review of another citation
    source_already_reviewed = "source_already_reviewed"
    # the citation's typed metadata, written by whoever imported it (ADR-0010's cooperative scope)
    source_type_in = "source_type_in"
    identifier_has_doi = "identifier_has_doi"
    identifier_has_arxiv = "identifier_has_arxiv"


class TrustCondition(BaseModel):
    """One condition of a rule: a kind from the closed vocabulary, and for `source_type_in` its set."""

    kind: TrustConditionKind
    values: list[str] = Field(default_factory=list)

    @field_validator("values")
    @classmethod
    def _distinct(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def _shape(self) -> TrustCondition:
        if self.kind == TrustConditionKind.source_type_in:
            if not self.values:
                raise ValueError("source_type_in needs at least one source type")
            unknown = [value for value in self.values if value not in {member.value for member in ReferenceSourceType}]
            if unknown:
                raise ValueError(f"not a source type: {', '.join(unknown)}")
        elif self.values:
            raise ValueError(f"{self.kind.value} takes no values")
        return self

    def describe(self) -> str:
        """The condition as the page and the CLI word it."""
        if self.kind == TrustConditionKind.source_already_reviewed:
            return "source already reviewed"
        if self.kind == TrustConditionKind.source_type_in:
            return f"source_type in {{{', '.join(self.values)}}}"
        if self.kind == TrustConditionKind.identifier_has_doi:
            return "identifier has DOI"
        return "identifier has arXiv"


# the source types a rule trusting them deserves a second look at (ADR-0014): a reminder, never a refusal
WEAK_SOURCE_TYPES = (ReferenceSourceType.website.value, ReferenceSourceType.other.value)


def parse_conditions(raw: Any) -> list[TrustCondition]:
    """The conditions a decision carries, validated; TRUST_RULE_INVALID_CONDITION says which one isn't."""
    if not isinstance(raw, list):
        raise TrustRuleError("TRUST_RULE_INVALID_CONDITION", "a rule's conditions are a list")
    conditions: list[TrustCondition] = []
    for item in raw:
        try:
            conditions.append(item if isinstance(item, TrustCondition) else TrustCondition.model_validate(item))
        except (ValidationError, ValueError, TypeError) as exc:
            raise TrustRuleError("TRUST_RULE_INVALID_CONDITION", f"not a trust-rule condition: {item!r} ({exc})") from exc
    return conditions


# -- the pure matcher ---------------------------------------------------------------------

# a DOI, bare or under a doi: prefix or a doi.org URL: 10.<registrant>/<suffix>
_DOI = re.compile(r"\b10\.\d{4,9}/\S+", re.IGNORECASE)
# a new-style arXiv id (2101.01234, optionally versioned) or an old-style one (math/0601001, math.AG/0601001)
_ARXIV_NEW = r"\d{4}\.\d{4,5}(?:v\d+)?"
_ARXIV_OLD = r"[a-z][a-z-]*(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
_ARXIV = re.compile(rf"(?:arxiv:\s*|arxiv\.org/(?:abs|pdf)/)(?:{_ARXIV_NEW}|{_ARXIV_OLD})|(?<![\w/]){_ARXIV_OLD}(?![\w/])", re.IGNORECASE)


def identifier_has_doi(identifier: str | None) -> bool:
    return bool(identifier) and _DOI.search(identifier) is not None


def identifier_has_arxiv(identifier: str | None) -> bool:
    return bool(identifier) and _ARXIV.search(identifier) is not None


class SiblingCitation(BaseModel):
    """Another imported result citing the same reference, with its *explicit* Reference review state."""

    node_id: str
    source_version: str | None
    explicit_state: str  # unreviewed, reviewed, unverifiable, no-longer-callable: never trusted-by-rule


def condition_holds(condition: TrustCondition, *, source_version: str | None, reference: ReferenceRecord, siblings: list[SiblingCitation]) -> bool:
    if condition.kind == TrustConditionKind.source_already_reviewed:
        same = [sibling for sibling in siblings if sibling.source_version == source_version]
        # a citation found no longer callable poisons the source: no other citation of it matches
        if any(sibling.explicit_state == "no-longer-callable" for sibling in same):
            return False
        return any(sibling.explicit_state == "reviewed" for sibling in same)
    if condition.kind == TrustConditionKind.source_type_in:
        return reference.source_type.value in condition.values
    if condition.kind == TrustConditionKind.identifier_has_doi:
        return identifier_has_doi(reference.identifier)
    return identifier_has_arxiv(reference.identifier)


def rule_matches(rule: TrustRule, *, source_version: str | None, reference: ReferenceRecord | None, siblings: list[SiblingCitation]) -> bool:
    """Whether a citation meets every condition of `rule`. A node with no citation meets nothing."""
    if reference is None or rule.retired or not rule.conditions:
        return False
    return all(condition_holds(condition, source_version=source_version, reference=reference, siblings=siblings) for condition in rule.conditions)


# -- the rules in force: the file, folded -----------------------------------------------------


class TrustRule(BaseModel):
    name: str
    rationale: str
    conditions: list[TrustCondition]
    declared_by: str
    declared_at: datetime
    # the newest decision on it (a declare, amend or retire)
    changed_by: str
    changed_at: datetime
    retired: bool = False

    def describe_conditions(self) -> list[str]:
        return [condition.describe() for condition in self.conditions]


def _readable(entry: ReviewEntry) -> list[TrustCondition] | None:
    """The conditions a line records, or None when the line isn't a trust-rule decision this vocabulary can read."""
    if entry.kind != DecisionKind.trust_rule.value or entry.payload is None or entry.decision not in TRUST_RULE_DECISIONS:
        return None
    try:
        return [TrustCondition.model_validate(item) for item in entry.payload.conditions] if entry.decision != "retire" else []
    except (ValidationError, ValueError, TypeError):
        return None  # a hand-edited or later-vocabulary condition: the line is a problem, never a crash


def _fold(entries: list[ReviewEntry]) -> dict[str, TrustRule]:
    rules: dict[str, TrustRule] = {}
    for entry in entries:
        conditions = _readable(entry)
        if conditions is None:
            continue
        name = entry.object_id
        if entry.decision == "declare" and name not in rules:
            rules[name] = TrustRule(name=name, rationale=entry.rationale, conditions=conditions, declared_by=entry.reviewer, declared_at=entry.decided_at,
                                    changed_by=entry.reviewer, changed_at=entry.decided_at)
        elif entry.decision == "amend" and name in rules and not rules[name].retired:
            rules[name] = rules[name].model_copy(update={"rationale": entry.rationale, "conditions": conditions, "changed_by": entry.reviewer, "changed_at": entry.decided_at})
        elif entry.decision == "retire" and name in rules and not rules[name].retired:
            rules[name] = rules[name].model_copy(update={"retired": True, "changed_by": entry.reviewer, "changed_at": entry.decided_at})
    return rules


@memoized_read
def _rules(store: ProjectStore) -> dict[str, TrustRule]:
    return _fold(load_trust_rule_entries(store.root)[0])


def list_trust_rules(store: ProjectStore, *, include_retired: bool = False) -> list[TrustRule]:
    """The rules in force, in declaration order; with `include_retired`, the retired ones too."""
    return [rule for rule in _rules(store).values() if include_retired or not rule.retired]


def get_trust_rule(store: ProjectStore, name: str) -> TrustRule | None:
    return _rules(store).get(name)


def trust_rule_history(store: ProjectStore, name: str) -> list[dict]:
    """Every decision recorded under `name`, oldest first, as the CLI and the page list them."""
    return [_row(entry) for entry in load_trust_rule_entries(store.root)[0] if entry.object_id == name and entry.kind == DecisionKind.trust_rule.value]


def unreadable_trust_rule_lines(store: ProjectStore) -> list[str]:
    """Lines of trust-rules.jsonl that are ignored: not JSON, or a decision this vocabulary can't read."""
    entries, problems = load_trust_rule_entries(store.root)
    unreadable = [f"{TRUST_RULES_FILE} line {number} (seq {entry.seq}: not a trust-rule decision this version reads)"
                  for number, entry in enumerate(entries, start=1) if _readable(entry) is None]
    return [*problems, *unreadable]


def _row(entry: ReviewEntry) -> dict:
    return {
        "id": entry.id,
        "seq": entry.seq,
        "name": entry.object_id,
        "decision": entry.decision,
        "reviewer": entry.reviewer,
        "rationale": entry.rationale,
        "decided_at": entry.decided_at.isoformat(),
        "conditions": list(entry.payload.conditions) if entry.payload is not None else [],
    }


# -- recording a decision -----------------------------------------------------------------------


class TrustRuleDecision(BaseModel):
    """What declaring, amending or retiring a rule recorded: the line, as the page reports it."""

    id: str
    name: str
    decision: str
    reviewer_id: str
    rationale: str
    conditions: list[TrustCondition]
    decided_at: datetime
    kind: str = DecisionKind.trust_rule.value


def check_rule_decision(store: ProjectStore, name: str, decision: str, *, conditions: list[TrustCondition] | None, rationale: str) -> list[TrustCondition]:
    """Why a decision on rule `name` can't be recorded (raised), or the conditions it records."""
    if decision not in TRUST_RULE_DECISIONS:
        raise TrustRuleError("INVALID_DECISION", f"'{decision}' is not a trust-rule decision; expected one of: {', '.join(TRUST_RULE_DECISIONS)}")
    if trust_rules_path(store.root).is_dir():
        # a project from before ADR-0014 may have a node of that name: its folder stands where the decision file goes
        raise TrustRuleError(
            "TRUST_RULES_FILE_BLOCKED",
            f"proofs/{TRUST_RULES_FILE} is a node's folder in this project, so no trust rule can be recorded here; "
            "move that node's work to a node under another id first",
        )
    if not _SAFE_NAME.fullmatch(name or ""):
        raise TrustRuleError("TRUST_RULE_INVALID_NAME", f"rule name {name!r} must be letters, digits, '.', '_' or '-', at most 64 characters")
    if not rationale.strip():
        raise TrustRuleError("TRUST_RULE_RATIONALE_REQUIRED", f"a trust-rule decision on {name} needs a rationale: why this class of citations can be relied on")
    existing = get_trust_rule(store, name)
    if decision == "declare":
        if existing is not None:
            raise TrustRuleError("TRUST_RULE_NAME_TAKEN", f"a trust rule named {name} already exists" + (" (retired; a name is never reused)" if existing.retired else ""))
    else:
        if existing is None:
            raise TrustRuleError("TRUST_RULE_NOT_FOUND", f"no trust rule is named {name}")
        if existing.retired:
            raise TrustRuleError("TRUST_RULE_RETIRED", f"trust rule {name} is retired, which is final; declare a new rule under a new name")
    if decision == "retire":
        return []
    resolved = parse_conditions(conditions if conditions is not None else [])
    if not resolved:
        raise TrustRuleError("TRUST_RULE_EMPTY", f"trust rule {name} needs at least one condition; a rule with none would trust every citation")
    return resolved


def record_rule_decision(
    store: ProjectStore, name: str, decision: str, *, conditions: list[TrustCondition], reviewer: str | None, rationale: str
) -> TrustRuleDecision:
    """Append the decision line to trust-rules.jsonl as the transaction commits, then commit it to git.

    Called inside the operation's `store.transaction()`, after `check_rule_decision`:
    the line lands under the write lock (ordered, rolled back with the operation) and
    is committed as the reviewer's identity once the transaction has committed, with
    the message `trust rule <name>: <decision>`. A failed commit leaves the rule
    recorded but not yet committed (REVIEWS_NOT_COMMITTED), like any other decision.
    """
    who = reviewer or git_identity(store.root)
    payload = DecisionPayload(kind=DecisionKind.trust_rule, target_id=name, decision=decision, rationale=rationale,
                              conditions=[condition.model_dump(mode="json") for condition in conditions])
    entry = ReviewEntry(seq=0, id=new_review_id(), object_type=TRUST_RULE_OBJECT_TYPE, object_id=name, kind=DecisionKind.trust_rule.value,
                        decision=decision, reviewer=who, rationale=rationale, payload=payload)
    path = trust_rules_path(store.root)
    message = f"trust rule {name}: {decision}\n\n{rationale}".rstrip()

    def _write() -> None:
        entries, _ = load_trust_rule_entries(store.root)
        entry.seq = (entries[-1].seq if entries else 0) + 1  # on the write lock: ordered within the file
        append_line(path, entry)

    before_commit(store, _write)
    after_commit(store, lambda: commit_decision(store.root, [path], message))
    return TrustRuleDecision(id=entry.id, name=name, decision=decision, reviewer_id=who, rationale=rationale, conditions=conditions, decided_at=entry.decided_at)

