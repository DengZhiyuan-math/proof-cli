"""Review decisions as git-tracked text, reviewed by a GitHub identity (ADR-0010, issues #53/#54).

Every Human Review decision on the proof map — an Acceptance, Reference
review, Evidence review, Lightweight re-review, Challenge dismissal or
Promote — is one JSON line in its node's `proofs/<node-id>/reviews.jsonl`,
naming what it decided on (the Review snapshot's SHA-256, the interface,
the pins, the Challenges it resolves). proof-cli commits that line together
with the snapshot it decides on, as the reviewer's own git identity; once
pushed, the commit on GitHub is the record of who decided what, and when.
Nothing is ever signed: the boundary against a cooperative agent is that no
CLI command, Codex route or MCP tool writes a decision, and git history is
where anything else would show.

Reads are cached per file (path, mtime, size), and the project's whole list
once per read scope (#43), so a derived axis computed over a whole map reads
each file once.

The project-level `proofs/trust-rules.jsonl` (ADR-0014) is a decision file of
the same line shape, read and written through the same layer: one line per
Trust rule decision (declare, amend, retire), folded by `trust_rules`.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import subprocess
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .domain import utc_now
from .storage import forget_reads, memoized_read
from .vault import vault_dir

REVIEWS_FILE = "reviews.jsonl"
# the project-level decision file of Trust rules (ADR-0014), beside the node folders
TRUST_RULES_FILE = "trust-rules.jsonl"


class DecisionKind(str, Enum):
    """Every Human Review decision kind on the proof map."""

    acceptance = "acceptance"
    reference_review = "reference_review"
    evidence_review = "evidence_review"
    dependency_revalidation = "dependency_revalidation"
    challenge_resolution = "challenge_resolution"
    promote = "promote"
    dependent_migration = "dependent_migration"
    # a Trust rule declared, amended or retired: a standing Reference review (ADR-0014)
    trust_rule = "trust_rule"


class PinnedDependency(BaseModel):
    target_node_id: str
    pinned_version: int | None = None
    pinned_fingerprint: str | None = None


class DecisionPayload(BaseModel):
    """What a decision was made on: the facts it is bound to (formerly the signed payload of ADR-0009)."""

    # an ADR-0009 payload carried chain heads, an instance id and a signature time: ignored
    model_config = ConfigDict(extra="ignore")

    kind: DecisionKind
    target_id: str
    decision: str
    rationale: str = ""
    candidate_proof_id: str | None = None
    candidate_proof_sha256: str | None = None
    # the accepted mathematical interface: for a local node its interface
    # fingerprint (statement, assumptions); for an imported result, its
    # statement and source
    interface_fingerprint: str | None = None
    dependency_pins: list[PinnedDependency] = Field(default_factory=list)
    # the Challenges this decision resolves, by id
    resolves_challenges: list[str] = Field(default_factory=list)
    # a dependent_migration: the nodes it moved off the withdrawn citation (#20)
    migrated_dependents: list[str] = Field(default_factory=list)
    # who wrote the key-ideas summary of the snapshot decided on (ADR-0013), as its record says
    key_ideas_drafted_by: str | None = None
    # a trust_rule's conditions (ADR-0014): `trust_rules.TrustCondition`, as JSON; empty for a retire
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class ReviewEntry(BaseModel):
    """One line of a node's `reviews.jsonl`."""

    seq: int
    id: str
    object_type: str
    object_id: str
    kind: str
    decision: str  # the recorded state: approved, rejected, revision_requested, reaffirmed, trusted, …
    reviewer: str
    rationale: str = ""
    decided_at: datetime = Field(default_factory=utc_now)
    payload: DecisionPayload | None = None
    # moved here from the SQLite review_history table (ADR-0010)
    migrated: bool = False
    # the key-ideas provenance of the snapshot decided on (ADR-0013), copied from the payload,
    # which the decision's binding covers; None for a decision on no snapshot
    key_ideas_drafted_by: str | None = None


# (kind, decision value) -> (object_type, recorded state)
DECISION_ROWS: dict[tuple[DecisionKind, str], tuple[str, str]] = {
    (DecisionKind.acceptance, "accept"): ("proof_map_node", "approved"),
    (DecisionKind.acceptance, "revision-requested"): ("proof_map_node", "revision_requested"),
    (DecisionKind.acceptance, "reject"): ("proof_map_node", "rejected"),
    (DecisionKind.reference_review, "reference-review"): ("proof_map_node", "approved"),
    (DecisionKind.reference_review, "no-longer-callable"): ("proof_map_node", "rejected"),
    (DecisionKind.evidence_review, "trusted"): ("evidence_check", "trusted"),
    (DecisionKind.evidence_review, "unusable"): ("evidence_check", "unusable"),
    (DecisionKind.dependency_revalidation, "reaffirmed"): ("proof_map_node", "reaffirmed"),
    (DecisionKind.challenge_resolution, "dismissed"): ("challenge", "dismissed"),
    (DecisionKind.promote, "promote"): ("proof_map_node", "approved"),
    # a no-longer-callable imported result's dependents moved onto its correction (#20)
    (DecisionKind.dependent_migration, "superseded"): ("proof_map_node", "superseded"),
    # a Trust rule's three decisions, recorded under the rule's name (ADR-0014)
    (DecisionKind.trust_rule, "declare"): ("trust_rule", "declare"),
    (DecisionKind.trust_rule, "amend"): ("trust_rule", "amend"),
    (DecisionKind.trust_rule, "retire"): ("trust_rule", "retire"),
}


def payload_decision_for(kind: str, object_type: str, recorded: str) -> str | None:
    """The decision value a recorded state of this kind stands for (the inverse of DECISION_ROWS)."""
    return next(
        (decision for (candidate, decision), row in DECISION_ROWS.items() if candidate.value == kind and row == (object_type, recorded)),
        None,
    )


# -- files ---------------------------------------------------------------------------


def reviews_path(root: Path, node_id: str) -> Path:
    return vault_dir(root) / node_id / REVIEWS_FILE


def trust_rules_path(root: Path) -> Path:
    """The project's Trust rule decisions (ADR-0014): one file, beside the node folders."""
    return vault_dir(root) / TRUST_RULES_FILE


_CACHE: dict[str, tuple[tuple[int, int], list[ReviewEntry], list[str]]] = {}


def _read_file(path: Path) -> tuple[list[ReviewEntry], list[str]]:
    """(entries, problems) of one reviews.jsonl; an unreadable line is a problem, never a crash."""
    stat = path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(str(path))
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]
    entries: list[ReviewEntry] = []
    problems: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(ReviewEntry.model_validate_json(line))
        except (ValidationError, ValueError):
            problems.append(f"{path.name} line {number}")
    _CACHE[str(path)] = (key, entries, problems)
    return entries, problems


@memoized_read
def load_entries(root: Path) -> tuple[list[ReviewEntry], list[str]]:
    """Every recorded decision in the project, oldest first, and any unreadable lines."""
    entries: list[ReviewEntry] = []
    problems: list[str] = []
    base = vault_dir(root)
    if not base.is_dir():
        return entries, problems
    for path in sorted(base.glob(f"*/{REVIEWS_FILE}")):
        file_entries, file_problems = _read_file(path)
        entries.extend(file_entries)
        problems.extend(f"{path.parent.name}/{problem}" for problem in file_problems)
    entries.sort(key=lambda entry: entry.seq)
    return entries, problems


def append_line(path: Path, entry: ReviewEntry) -> Path:
    """Append one decision line to a decision file (a node's reviews.jsonl, or the project's trust-rules.jsonl)."""
    forget_reads()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return path


def append_entry(root: Path, node_id: str, entry: ReviewEntry) -> Path:
    return append_line(reviews_path(root, node_id), entry)


def next_seq(root: Path) -> int:
    entries, _ = load_entries(root)
    return (entries[-1].seq if entries else 0) + 1


@memoized_read
def load_trust_rule_entries(root: Path) -> tuple[list[ReviewEntry], list[str]]:
    """Every Trust rule decision in the project, in file order, and any unreadable lines (ADR-0014)."""
    path = trust_rules_path(root)
    if not path.is_file():
        return [], []
    return _read_file(path)


def new_review_id() -> str:
    return f"review_{uuid.uuid4().hex[:12]}"


# -- the reviewer, and git ------------------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)


def git_identity(root: Path) -> str:
    """`Name <email>` from git config: the identity whose commits record the decisions."""
    try:
        name = _git(root, "config", "user.name").stdout.strip()
        email = _git(root, "config", "user.email").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = email = ""
    if name and email:
        return f"{name} <{email}>"
    return name or email or getpass.getuser()


def in_git_repo(root: Path) -> bool:
    try:
        return _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def commit_decision(root: Path, paths: list[Path], message: str) -> str | None:
    """Commit exactly `paths` as the configured git identity; the commit id, or None when not in a git repo.

    Never pushes, and never touches anything else that's staged. A failed
    commit leaves the decision recorded but *not yet committed*, which
    `uncommitted_review_files` reports.
    """
    if not in_git_repo(root):
        return None
    relative = [str(path.relative_to(root)) for path in paths if path.exists()]
    try:
        if _git(root, "add", "--", *relative).returncode != 0:
            return None
        if _git(root, "commit", "--quiet", "-m", message, "--", *relative).returncode != 0:
            return None
        return _git(root, "rev-parse", "HEAD").stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def uncommitted_review_files(root: Path) -> list[str]:
    """Decision files with decisions git doesn't have yet (all of them, outside a git repo):
    every node's reviews.jsonl and the project's trust-rules.jsonl."""
    base = vault_dir(root)
    files = sorted(str(path.relative_to(root)) for path in base.glob(f"*/{REVIEWS_FILE}")) if base.is_dir() else []
    if trust_rules_path(root).is_file():
        files.append(str(trust_rules_path(root).relative_to(root)))
    if not files or not in_git_repo(root):
        return files
    try:
        status = _git(root, "status", "--porcelain", "--", *files).stdout
    except (OSError, subprocess.SubprocessError):
        return files
    return sorted(line[3:].strip() for line in status.splitlines() if line.strip())


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def entry_json(entry: ReviewEntry) -> dict:
    return json.loads(entry.model_dump_json())
