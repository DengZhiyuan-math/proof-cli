from __future__ import annotations

from pathlib import Path


def vault_dir(root: Path) -> Path:
    return root / "proofs"


def candidate_proof_path(root: Path, node_id: str, version: int) -> Path:
    return vault_dir(root) / node_id / f"v{version}.md"


def write_candidate_proof_file(
    path: Path,
    *,
    id: str,
    node_id: str,
    version: int,
    submitted_by: str,
    created_at: str,
    scoping_rationale: str,
    content: str,
) -> None:
    """Write one immutable candidate proof file.

    Refuses to overwrite an existing file — a candidate proof, once written,
    is never edited in place; a revision is a new version, a new file.
    """
    if path.exists():
        raise FileExistsError(f"candidate proof file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rationale_block = "\n".join(f"  {line}" for line in scoping_rationale.splitlines() or [""])
    frontmatter = (
        "---\n"
        f"id: {id}\n"
        f"node_id: {node_id}\n"
        f"version: {version}\n"
        f"submitted_by: {submitted_by}\n"
        f"created_at: {created_at}\n"
        "scoping_rationale: |\n"
        f"{rationale_block}\n"
        "---\n\n"
    )
    path.write_text(frontmatter + content.rstrip("\n") + "\n", encoding="utf-8")


def read_candidate_proof_frontmatter(path: Path) -> dict[str, str]:
    """Parse the YAML frontmatter of a candidate proof file.

    Only understands the fixed field set this module writes (plain scalars
    plus one `|` block scalar for `scoping_rationale`) — sufficient for our
    own round-trip, not a general YAML parser.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} has no YAML frontmatter")
    end = text.index("\n---", 4)
    lines = text[4:end].splitlines()

    result: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "|":
            block: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                block.append(lines[i][2:] if lines[i].startswith("  ") else "")
                i += 1
            result[key] = "\n".join(block).rstrip("\n")
            continue
        result[key] = rest
        i += 1
    return result
