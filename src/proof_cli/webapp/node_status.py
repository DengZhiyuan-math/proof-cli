"""A proof map node's one status, the word and colour every view shows for it (issue #157).

The map card, its legend, the tree, an imported result's page and the studio's node panel all
show the status this derives, sent with the node by `/api/map` and `/api/node`; none derives
its own. The three axes stay separate (ADR-0004) and are still shown beside it; this is only
the at-a-glance reading of them.

What needs the researcher comes first (a Challenge, a moved dependency, a decision that no
longer applies: one "attention" kind, the word saying which), then a rejected route, then the
frontier, the agent's run, a claim, a review request, blocked, accepted. The frontier is the
strongest signal (ADR-0008, CONTEXT.md): a node on it reads Ready whatever its workflow state,
Revision requested included. A frontier node with a warning reads the warning, and every view
shows its Ready mark beside it, never in its place (`frontier` is sent alongside).
"""

from __future__ import annotations

# the kinds, each a colour and an icon; the icons are drawn by studio/static/status.js
KINDS = ("ready", "claimed", "blocked", "review", "accepted", "rejected", "attention", "open")


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


def _run_where(run: dict) -> str:
    """Where the agent's run on the node is (spec #145): "Typesetter · step 4/5", "Prover · paused", "Numerics · needs you"."""
    role = _capitalised(str(run.get("role") or "")) or "Agent"
    if run.get("status") == "needs-human":
        return f"{role} · needs you"
    if run.get("step") and run.get("steps"):
        return f"{role} · step {run['step']}/{run['steps']}"
    return f"{role} · paused" if run.get("status") == "paused" else role


def node_status(node: dict) -> dict:
    """{"text", "kind"} for a node given as `/api/map` sends it: its three axes, `frontier`, `assignee` and `run`."""
    workflow, acceptance, integrity = node.get("workflow_state"), node.get("acceptance_state"), node.get("integrity_state")
    run = node.get("run")
    if integrity == "challenged":
        text, kind = "challenged", "attention"
    elif integrity == "potentially-stale":
        text, kind = "dependency changed", "attention"
    elif acceptance == "unverifiable":
        text, kind = "decision outdated", "attention"
    elif acceptance in ("rejected", "no-longer-callable"):
        text, kind = ("rejected" if acceptance == "rejected" else "no longer callable"), "rejected"
    elif node.get("frontier"):
        text, kind = "ready", "ready"
    elif run and run.get("status") != "idle":
        text, kind = _run_where(run), ("attention" if run.get("status") == "needs-human" else "claimed")
    elif node.get("assignee"):
        text, kind = str(node["assignee"]), "claimed"
    elif workflow == "review-needed":
        text, kind = "awaiting review", "review"
    elif workflow == "revision-requested":
        # off the frontier only when something else holds it: back to work, not awaiting review
        text, kind = "revision requested", "open"
    elif workflow == "blocked":
        text, kind = "blocked", "blocked"
    elif acceptance in ("accepted", "reviewed"):
        text, kind = acceptance, "accepted"
    elif acceptance == "trusted-by-rule":
        text, kind = "trusted by rule", "accepted"  # the rule names: on the axis chips and the hover
    else:
        text, kind = "open", "open"
    return {"text": _capitalised(text), "kind": kind}
