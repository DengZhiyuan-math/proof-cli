from __future__ import annotations

import io

from rich.console import Console
from rich.table import Table

from .domain import CandidateProofRecord, Challenge, ClaimRecord, ProjectSnapshot, ProofMapNode, is_computation


def _console() -> Console:
    """A console that only records: each renderer returns its text, and the caller prints it once (#34). Nothing here
    is Rich markup: a statement's `$f\\colon [a,b] \\to \\mathbb{R}$` is mathematics, and `[a,b]` must not be read as a
    style tag and dropped (as it was), nor `:sum:` as an emoji — so markup and emoji are off for every renderer."""
    return Console(record=True, width=100, file=io.StringIO(), markup=False, emoji=False)


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
    table.add_row("Failed routes (legacy)", ", ".join(data.get("failed_routes", []) or []) or "none")  # a dropped Proof fog item is the record now (spec #136)
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
    provisional: bool = False,
    conditional_on: list[str] | None = None,
    working_proof: str | None = None,
    snapshots: list[dict] | None = None,
    citation: dict | None = None,
    trust_rule: list[str] | None = None,
    crystallized_from: str | None = None,
    fog_near: list[str] | None = None,
    definitions: list[dict] | None = None,
) -> str:
    console = _console()
    console.rule(f"Proof Map Node: {node.id}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Kind", node.kind.value)
    if node.medium is not None:
        table.add_row("Medium", node.medium.value)  # what the candidate proof is made of (spec #145)
    if node.display_label:
        table.add_row("Display label", node.display_label)
    for definition in definitions or []:  # what the statement's symbols are, before the statement (ADR-0020)
        table.add_row(f"Definition {definition['id']}", f"{definition['term']}. {definition['text']}")
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
    if crystallized_from:
        # the fog item the node was stated from (ADR-0008, spec #136)
        table.add_row("Crystallized from", crystallized_from)
    if fog_near:
        table.add_row("Fog near", ", ".join(fog_near))
    # Three independent, computed signals — never folded into one status word.
    if workflow_state is not None:
        table.add_row("Workflow state", workflow_state)
    if blocked_reason is not None:
        table.add_row("Blocked reason", blocked_reason)
    if provisional:
        # rested on for work, never for trust (ADR-0021)
        table.add_row("Provisional", "yes: its statement may be used until the researcher decides it")
    if conditional_on:
        table.add_row("Conditional on", ", ".join(conditional_on))
    if acceptance_state is not None:
        table.add_row("Acceptance state", acceptance_state)
    if trust_rule:
        # the Trust rules an imported result meets (ADR-0014)
        table.add_row("Trust rule", ", ".join(trust_rule))
    if integrity_state is not None:
        table.add_row("Integrity state", integrity_state)
    if working_proof is not None:
        table.add_row("Run script" if is_computation(node) else "Working proof", working_proof)
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
        table.add_row(node.id, f"{node.kind.value} · computation" if is_computation(node) else node.kind.value, node.statement)
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
        table.add_row("Key ideas by", record.key_ideas_drafted_by)
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


def render_node_check(node_id: str, findings: list[dict]) -> str:
    """The mechanical checks of a node (issue #180): each finding's level, code and message; or that all passed."""
    console = _console()
    console.rule(f"Node check: {node_id}")
    if not findings:
        console.print("All checks passed: the proof builds cleanly, key-ideas.md has its four headings, the statement is the node's.")
        return console.export_text()
    table = Table()
    table.add_column("level")
    table.add_column("code")
    table.add_column("message")
    for finding in findings:
        table.add_row(str(finding.get("level")), str(finding.get("code")), str(finding.get("message")))
    console.print(table)
    return console.export_text()


def render_trust_rule_list(rules: list[dict]) -> str:
    """The Trust rules (ADR-0014): name, conditions, what each trusts now."""
    console = _console()
    console.rule("Trust Rules")
    if not rules:
        console.print("No trust rule is in force: every imported result needs its own Reference review.")
        return console.export_text()
    table = Table()
    table.add_column("name")
    table.add_column("conditions")
    table.add_column("trusting")
    table.add_column("rationale")
    for rule in rules:
        name = f"{rule['name']} (retired)" if rule.get("retired") else rule["name"]
        table.add_row(name, "; ".join(rule["conditions_text"]), ", ".join(rule["trusting"]) or "—", rule["rationale"])
    console.print(table)
    return console.export_text()


def render_trust_rule(rule: dict) -> str:
    """One Trust rule with every decision recorded under its name (`proof trust-rule show`)."""
    console = _console()
    console.rule(f"Trust Rule: {rule['name']}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Status", "retired" if rule.get("retired") else "in force")
    table.add_row("Rationale", rule["rationale"])
    table.add_row("Conditions", "; ".join(rule["conditions_text"]) or "none")
    table.add_row("Declared by", f"{rule['declared_by']} at {rule['declared_at']}")
    table.add_row("Trusting", ", ".join(rule["trusting"]) or "none")
    console.print(table)
    console.print("History")
    for row in rule.get("history", []):
        console.print(f"  {row['decided_at']} · {row['decision']} · {row['reviewer']} — {row['rationale']}")
    return console.export_text()


def _experiment_line(experiment: dict) -> str:
    where = f" · {experiment['path']}{' (missing)' if experiment.get('missing') else ''}" if experiment.get("path") else ""
    return f"#{experiment['seq']} {experiment['outcome']} — {experiment['summary']} ({experiment['run_by']}, {experiment['recorded_at']}){where}"


def render_fog_list(items: list[dict]) -> str:
    """The fog items (ADR-0008): id, status, near nodes, the latest Experiment, the text."""
    console = _console()
    console.rule("Proof Fog")
    if not items:
        console.print("No fog: everything known about is stated as a node.")
        return console.export_text()
    table = Table()
    table.add_column("id")
    table.add_column("status")
    table.add_column("near")
    table.add_column("latest experiment")
    table.add_column("text")
    for item in items:
        latest = item.get("latest_experiment")
        table.add_row(
            item["id"], item["status"], ", ".join(item["near"]) or "—",
            f"{latest['outcome']} — {latest['summary']}" if latest else "—", item["text"],
        )
    console.print(table)
    return console.export_text()


def render_fog_item(view: dict) -> str:
    """One fog item in full (`proof fog show`)."""
    console = _console()
    console.rule(f"Fog: {view['id']}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Text", view["text"])
    if view.get("notes"):
        table.add_row("Notes", view["notes"])
    table.add_row("Near", ", ".join(view["near"]) or "no node")
    table.add_row("Status", view["status"])
    if view["status"] == "dropped":
        table.add_row("Dropped", f"{view['dropped_by']} at {view['dropped_at']} — {view['reason']}")
    if view["status"] == "crystallized":
        table.add_row("Crystallized as", view["node_id"])
    table.add_row("Created", f"{view['created_by']} at {view['created_at']}")
    table.add_row("Folder", f"{view['folder']} ({'exists' if view['folder_exists'] else 'not created yet'})")
    console.print(table)
    console.print("Experiments (newest first)" if view["experiments"] else "No experiment recorded.")
    for experiment in view["experiments"]:
        console.print(f"  {_experiment_line(experiment)}")
    return console.export_text()


def render_fog_experiments(fog_id: str, experiments: list[dict]) -> str:
    console = _console()
    console.rule(f"Experiments on {fog_id}")
    if not experiments:
        console.print("No experiment recorded.")
    for experiment in experiments:
        console.print(_experiment_line(experiment))
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



def _shown(value) -> str:
    return ", ".join(str(item) for item in value) or "none" if isinstance(value, list) else str(value)


def _work_log_body(entry: dict) -> str:
    """One work log entry as a line's body: a plan, a step, a turn, a handoff, a verdict or an attempt
    (ADR-0019), or what the agent did through another `proof` command."""
    kind = entry.get("kind")
    if kind == "plan":
        return "plan: " + " → ".join(f"{i}. {step}" for i, step in enumerate(entry.get("plan") or [], start=1))
    if kind == "step":
        status = "needs a human decision" if entry.get("status") == "needs-human" else entry.get("status")
        return f"step {entry.get('step')} {status}" + (f" — {entry['note']}" if entry.get("note") else "")
    if kind == "turn":
        return f"turn {entry.get('turn')} (job {entry.get('job')}" + (f", session {entry['session_id']}" if entry.get("session_id") else "") + ")"
    if kind == "handoff":
        return f"handed off to {entry.get('to')}" + (f" — {entry['note']}" if entry.get("note") else "")
    if kind == "verdict":
        return f"verifier: {entry.get('outcome')}" + (f" — {entry['note']}" if entry.get("note") else "")
    if kind == "attempt":
        return f"attempt: {entry.get('goal')}" + (f" ({entry['method']})" if entry.get("method") else "") + f" failed on {entry.get('failed_on')}"
    if kind == "coordinator":
        return f"coordinator: {entry.get('note')}"
    if kind == "question":  # a Standing question (ADR-0021): the choice made, open until the researcher answers
        return f"chose {entry.get('question')} ({entry.get('id')})"
    if kind == "answer":
        return f"answered {entry.get('question_id')}: " + ("the choice stands" if entry.get("keep") else f"redirect — {entry.get('redirect')}")
    if kind == "split":
        return "split into " + ", ".join(entry.get("nodes") or [])
    if kind == "review-requested":
        return f"requested review of snapshot v{entry.get('version')}"
    if kind == "evidence":
        return f"Evidence check {entry.get('outcome')}"
    if kind == "fog":
        return f"fog {entry.get('fog_id')}: {entry.get('text')}"
    if kind == "experiment":
        return f"Experiment {entry.get('seq')} on {entry.get('fog_id')}: {entry.get('outcome')}"
    if kind in ("restated", "definition-edited"):  # ADR-0021 point 6: why, and what changed from what
        what = "restated" if kind == "restated" else f"definition {entry.get('definition_id')} edited"
        before, after = entry.get("from") or {}, entry.get("to") or {}
        changes = "; ".join(f"{key}: {_shown(before.get(key)) if key in before else '…'} → {_shown(value)}" for key, value in after.items())
        return f"{what}" + (f" — {entry['reason']}" if entry.get("reason") else "") + (f" ({changes})" if changes else "")
    if kind == "dependencies":
        return f"dependency {entry.get('change')}: {entry.get('dependency')}" + (" (resplit: the Decomposer took its own Claim back)" if entry.get("resplit") else "")
    return str(kind)


def render_work_log_entry(node_id: str, entry: dict) -> str:
    """The one line `proof node progress` answers a report with: who reported, on which node, and what."""
    if entry.get("kind") == "plan":  # how many steps, not the steps: the log has them
        body = f"plan of {len(entry.get('plan') or [])} step(s)" + (f" — {entry['note']}" if entry.get("note") else "")
    elif entry.get("kind") == "verdict":  # the role is already said: `verifier on N: verdict passed`
        body = f"verdict {entry.get('outcome')}" + (f" — {entry['note']}" if entry.get("note") else "")
    elif entry.get("kind") == "coordinator":  # no role: the Coordinator holds no node and takes no turn (ADR-0019 point 18)
        return f"coordinator on {node_id}: {entry.get('note')}"
    else:
        body = _work_log_body(entry)
    return f"{entry.get('role')} on {node_id}: {body}"


def render_work_log(node_id: str, log: list[dict]) -> str:
    """A node's work log (spec #145): the agent's plan, steps, verdicts and attempts, and what it did through `proof`, in time order."""
    console = _console()
    console.rule(f"Work log: {node_id}")
    if not log:
        console.print("No agent has reported on this node yet.")
        return console.export_text()
    for entry in log:
        when = str(entry.get("at", ""))[:16].replace("T", " ")
        who = f"{entry.get('role') or ''}{'·' if entry.get('role') and entry.get('by') else ''}{entry.get('by') or ''}"
        console.print(f"{when}  {who:<24} {_work_log_body(entry)}")
    return console.export_text()


def render_definition_list(items: list[dict]) -> str:
    """The project's Definitions (ADR-0020): id, term, the nodes that name it, the text."""
    console = _console()
    console.rule("Definitions")
    if not items:
        console.print("No definitions yet: `proof definition add <id> --term <term> <text>`.")
        return console.export_text()
    table = Table()
    table.add_column("id")
    table.add_column("term")
    table.add_column("named by")
    table.add_column("text")
    for item in items:
        table.add_row(item["id"], item["term"], ", ".join(item["used_by"]) or "— (editable)", item["text"])
    console.print(table)
    return console.export_text()


def render_project_progress(pursuits: list[dict]) -> str:
    """The project's Pursue history (`proof project progress`): each pursuit, its status and its events."""
    console = _console()
    console.rule("Project Pursue")
    if not pursuits:
        console.print("No project Pursue was recorded here.")
        return console.export_text()
    for pursuit in pursuits:
        console.print(f"{pursuit['pursuit_id']}  {pursuit['status']}  provider {pursuit['provider'] or '—'}  started {pursuit['started_at']}")
        if pursuit["reason"]:
            console.print(f"  {pursuit['reason']}")
        for event in pursuit["events"]:
            parts = [event["created_at"], event["phase"]]
            parts += [x for x in (event["outcome"], event["theorem"]) if x]
            line = "  · " + " ".join(parts)
            if event["reason"]:
                line += f": {event['reason']}"
            if event["budget"] is not None:
                line += f" (budget {event['budget']})"
            console.print(line)
    return console.export_text()


def render_definition(view: dict) -> str:
    """One definition in full (`proof definition show`)."""
    console = _console()
    console.rule(f"Definition: {view['id']}")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold")
    table.add_column("value")
    table.add_row("Term", view["term"])
    table.add_row("Text", view["text"])
    table.add_row("Named by", ", ".join(view["used_by"]) or "no node yet: it can still be edited or removed")
    table.add_row("Created by", view["created_by"])
    console.print(table)
    return console.export_text()
