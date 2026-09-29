from __future__ import annotations

import io

from rich.console import Console
from rich.table import Table

from .domain import CandidateProofRecord, Challenge, ClaimRecord, ProjectSnapshot, ProofMapNode


def _console() -> Console:
    """A console that only records: each renderer returns its text, and the caller prints it once (#34)."""
    return Console(record=True, width=100, file=io.StringIO())


def render_status(data: dict[str, object]) -> str:
    console = _console()
    console.rule("Proof Status")

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Project", str(data.get("project_id", "")))
    table.add_row("Current theorem", str(data.get("current_theorem") or "none"))
    table.add_row("Goals", ", ".join(data.get("open_goals", []) or []) or "none")
    table.add_row("Obligations", ", ".join(data.get("open_obligations", []) or []) or "none")
    table.add_row("Blockers", ", ".join(data.get("blockers", []) or []) or "none")
    table.add_row("Failed routes", ", ".join(data.get("failed_routes", []) or []) or "none")
    table.add_row("Recent results", ", ".join(data.get("recent_theorem_usage", []) or []) or "none")
    table.add_row(
        "Trust-sensitive calls",
        ", ".join(data.get("unresolved_trust_sensitive_calls", []) or []) or "none",
    )
    console.print(table)

    snapshot = data.get("latest_snapshot")
    if isinstance(snapshot, ProjectSnapshot):
        console.rule("Latest Snapshot")
        console.print(snapshot.model_dump_json(indent=2))
    return console.export_text()


def render_export(data: dict[str, object]) -> str:
    console = _console()
    console.rule("Proof Export")
    console.print(f"Project: {data.get('project_id')}")
    console.print(f"Current theorem: {data.get('current_theorem') or 'none'}")
    console.print("Proved: " + (", ".join(data.get("recent_theorem_usage", []) or []) or "none"))
    console.print("Assumed: " + (", ".join(data.get("open_goals", []) or []) or "none"))
    console.print("Open: " + (", ".join(data.get("open_obligations", []) or []) or "none"))
    console.print("Blockers: " + (", ".join(data.get("blockers", []) or []) or "none"))
    snapshot = data.get("latest_snapshot")
    if isinstance(snapshot, ProjectSnapshot):
        console.print("Snapshot:")
        console.print(snapshot.model_dump_json(indent=2))
    return console.export_text()


def render_proof_map_node(
    node: ProofMapNode,
    *,
    workflow_state: str | None = None,
    acceptance_state: str | None = None,
    integrity_state: str | None = None,
    blocked_reason: str | None = None,
    working_proof: str | None = None,
    snapshots: list[dict] | None = None,
    citation: dict | None = None,
) -> str:
    console = _console()
    console.rule(f"Proof Map Node: {node.id}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Kind", node.kind.value)
    if node.display_label:
        table.add_row("Display label", node.display_label)
    table.add_row("Statement", node.statement)
    table.add_row("Assumptions", ", ".join(node.assumptions) or "none")
    table.add_row("Dependencies", ", ".join(node.dependencies) or "none")
    if node.source_locator:
        table.add_row("Source locator", node.source_locator)
    if node.source_version:
        table.add_row("Source version", node.source_version)
    if node.trust_level:
        table.add_row("Trust level", node.trust_level.value)
    if citation is not None:
        # the ReferenceRecord this imported result links (issue #91)
        if citation["missing"]:
            table.add_row("Reference", f"{citation['reference_id']} (citation missing: no such reference here)")
        else:
            table.add_row("Reference", citation["reference_id"])
            table.add_row("Citation title", citation["title"])
            table.add_row("Citation authors", ", ".join(citation["authors"]) or "none")
            if citation["year"]:
                table.add_row("Citation year", str(citation["year"]))
            for label, key in (("Citation identifier", "identifier"), ("Citation url", "url")):
                if citation[key]:
                    table.add_row(label, citation[key])
    if node.derived_from:
        table.add_row("Derived from", node.derived_from)
    # Three independent, computed signals — never folded into one status word.
    if workflow_state is not None:
        table.add_row("Workflow state", workflow_state)
    if blocked_reason is not None:
        table.add_row("Blocked reason", blocked_reason)
    if acceptance_state is not None:
        table.add_row("Acceptance state", acceptance_state)
    if integrity_state is not None:
        table.add_row("Integrity state", integrity_state)
    if working_proof is not None:
        table.add_row("Working proof", working_proof)
    for snapshot in snapshots or []:
        current = " (current)" if snapshot["is_current"] else ""
        table.add_row(f"Snapshot v{snapshot['version']}", f"{snapshot['file_path']}{current} sha256={snapshot['sha256'] or '—'}")
    table.add_row("Created by", node.created_by)
    table.add_row("Created at", node.created_at.isoformat())
    console.print(table)
    return console.export_text()


def render_frontier(nodes: list[ProofMapNode]) -> str:
    console = _console()
    console.rule("Proof Frontier")
    if not nodes:
        console.print("No frontier nodes")
        return console.export_text()
    table = Table()
    table.add_column("id")
    table.add_column("kind")
    table.add_column("statement")
    for node in nodes:
        table.add_row(node.id, node.kind.value, node.statement)
    console.print(table)
    return console.export_text()


def render_claim(claim: ClaimRecord) -> str:
    console = _console()
    console.rule(f"Claim on {claim.node_id}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Claim id", claim.id)
    table.add_row("Claimant", claim.claimant_id)
    table.add_row("Session", claim.session_id)
    table.add_row("Claimed at", claim.claimed_at.isoformat())
    if claim.released_at is not None:
        table.add_row("Released at", claim.released_at.isoformat())
        table.add_row("Released by", claim.released_by or "")
        table.add_row("Release reason", claim.release_reason or "")
    console.print(table)
    return console.export_text()


def render_candidate_proof(record: CandidateProofRecord) -> str:
    console = _console()
    console.rule(f"Candidate Proof {record.node_id} v{record.version}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Candidate proof id", record.id)
    table.add_row("Node", record.node_id)
    table.add_row("Version", str(record.version))
    table.add_row("File", record.file_path)
    table.add_row("Current", "yes" if record.is_current else "no")
    table.add_row("Submitted by", record.submitted_by)
    table.add_row("Submitted at", record.created_at.isoformat())
    table.add_row("Scoping rationale", record.scoping_rationale)
    if record.resnapshot_after_loss is not None:
        table.add_row("Note", f"re-snapshot after loss of v{record.resnapshot_after_loss}; it needs its own review")
    if record.key_ideas_drafted_by is not None:
        table.add_row("Key ideas", f"drafted by {record.key_ideas_drafted_by}, confirmed by {record.submitted_by} in this request")
    console.print(table)
    return console.export_text()


def render_proof_map_node_list(nodes: list[ProofMapNode]) -> str:
    console = _console()
    console.rule("Proof Map Nodes")
    if not nodes:
        console.print("No proof map nodes")
        return console.export_text()
    table = Table()
    table.add_column("id")
    table.add_column("kind")
    table.add_column("statement")
    for node in nodes:
        table.add_row(node.id, node.kind.value, node.statement)
    console.print(table)
    return console.export_text()


def render_challenge(challenge: Challenge) -> str:
    console = _console()
    console.rule(f"Challenge {challenge.id}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Target", challenge.target_node_id)
    table.add_row("Status", challenge.status.value)
    table.add_row("Opened by", challenge.opened_by)
    table.add_row("Opened at", challenge.created_at.isoformat())
    table.add_row("Rationale", challenge.rationale or "none")
    if challenge.resolved_by:
        table.add_row("Resolved by", challenge.resolved_by)
    if challenge.resolved_at:
        table.add_row("Resolved at", challenge.resolved_at.isoformat())
    console.print(table)
    return console.export_text()


def render_challenge_list(challenges: list[Challenge]) -> str:
    console = _console()
    console.rule("Challenges")
    if not challenges:
        console.print("No challenges")
        return console.export_text()
    table = Table()
    table.add_column("id")
    table.add_column("target")
    table.add_column("status")
    table.add_column("opened_by")
    for challenge in challenges:
        table.add_row(challenge.id, challenge.target_node_id, challenge.status.value, challenge.opened_by)
    console.print(table)
    return console.export_text()

