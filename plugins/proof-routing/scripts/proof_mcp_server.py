from __future__ import annotations

import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

SERVER = FastMCP("Proof Routing")


def _effective_root(root: str | None) -> str | None:
    return root or None


def _run_proof_codex(*args: str, root: str | None = None) -> str:
    command = ["proof", "codex", *args]
    resolved_root = _effective_root(root)
    if resolved_root is not None:
        command.extend(["--root", resolved_root])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"Proof CLI command failed: {' '.join(command)}\n{detail}")
    return result.stdout.strip()


@SERVER.tool()
def doctor() -> str:
    """Check whether Proof CLI and proof-codex entrypoints are ready to use."""
    return _run_proof_codex("doctor", root=None)


@SERVER.tool()
def status(root: str | None = None) -> str:
    """Inspect the current proof workspace status."""
    return _run_proof_codex("status", root=root)


@SERVER.tool()
def init(root: str) -> str:
    """Initialize a proof workspace at the given root."""
    command = ["proof", "codex", "init", "--root", root]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"Proof CLI command failed: {' '.join(command)}\n{detail}")
    return result.stdout.strip()


@SERVER.tool()
def theorem_list(root: str | None = None) -> str:
    """List registered theorems in the selected workspace."""
    return _run_proof_codex("theorem", "list", root=root)


@SERVER.tool()
def theorem_show(theorem_id: str, root: str | None = None) -> str:
    """Show a registered theorem in the selected workspace."""
    return _run_proof_codex("theorem", "show", theorem_id, root=root)


@SERVER.tool()
def theorem_add(
    theorem_id: str,
    name: str,
    statement: str,
    assumptions: list[str] | None = None,
    exports: list[str] | None = None,
    notes: str | None = None,
    root: str | None = None,
) -> str:
    """Create a theorem through the Proof Codex wrapper."""
    args = ["theorem", "add", theorem_id, name, statement]
    for assumption in assumptions or []:
        args.extend(["--assumption", assumption])
    for exported in exports or []:
        args.extend(["--export", exported])
    if notes:
        args.extend(["--notes", notes])
    return _run_proof_codex(*args, root=root)


@SERVER.tool()
def obligation_list(root: str | None = None) -> str:
    """List open obligations in the selected workspace."""
    return _run_proof_codex("obligation", "list", root=root)


@SERVER.tool()
def obligation_add(
    goal_statement: str,
    required_for: str | None = None,
    source_step_id: str | None = None,
    root: str | None = None,
) -> str:
    """Add an obligation to the selected proof workspace."""
    args = ["obligation", "add", goal_statement]
    if required_for:
        args.extend(["--required-for", required_for])
    if source_step_id:
        args.extend(["--source-step-id", source_step_id])
    return _run_proof_codex(*args, root=root)


@SERVER.tool()
def blocker_list(root: str | None = None) -> str:
    """List active blockers in the selected workspace."""
    return _run_proof_codex("blocker", "list", root=root)


@SERVER.tool()
def blocker_add(
    description: str,
    scope: str | None = None,
    failure_type: str | None = None,
    root: str | None = None,
) -> str:
    """Add a blocker to the selected proof workspace."""
    args = ["blocker", "add", description]
    if scope:
        args.extend(["--scope", scope])
    if failure_type:
        args.extend(["--failure-type", failure_type])
    return _run_proof_codex(*args, root=root)


@SERVER.tool()
def search(query: str, root: str | None = None, limit: int = 10) -> str:
    """Run text search through the Proof Codex wrapper."""
    return _run_proof_codex("search", query, "--limit", str(limit), root=root)


@SERVER.tool()
def retrieve(query: str, root: str | None = None) -> str:
    """Run retrieval-first project search for a proof query."""
    return _run_proof_codex("retrieve", query, root=root)


@SERVER.tool()
def project_analyze(query: str = "", root: str | None = None, limit: int = 5) -> str:
    """Run project analysis through the Proof Codex wrapper."""
    args = ["project", "analyze"]
    if query:
        args.extend(["--query", query])
    args.extend(["--limit", str(limit)])
    return _run_proof_codex(*args, root=root)


@SERVER.tool()
def snapshot(note: str = "checkpoint", root: str | None = None) -> str:
    """Create a proof snapshot checkpoint."""
    return _run_proof_codex("snapshot", "--note", note, root=root)


def main() -> None:
    Path.cwd()
    SERVER.run()


if __name__ == "__main__":
    main()
