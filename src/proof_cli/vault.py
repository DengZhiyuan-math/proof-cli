from __future__ import annotations

from pathlib import Path


def vault_dir(root: Path) -> Path:
    return root / "proofs"


def candidate_proof_path(root: Path, node_id: str, version: int) -> Path:
    """An ADR-0003 Markdown attempt (read-only history since ADR-0010)."""
    return vault_dir(root) / node_id / f"v{version}.md"


# -- ADR-0010: a node's proof is a standalone LaTeX document ----------------------------

PREAMBLE = r"""% Shared by every node's proof.tex (\input{../preamble}): packages, macros, theorem environments.
\usepackage{amsmath,amssymb,amsthm}
\newtheorem{theorem}{Theorem}
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{claim}[theorem]{Claim}
"""

_ENVIRONMENTS = {"theorem": "theorem", "lemma": "lemma", "claim": "claim"}


def preamble_path(root: Path) -> Path:
    return vault_dir(root) / "preamble.tex"


def working_proof_path(root: Path, node_id: str) -> Path:
    """The node's one working file: edited freely, never reviewed directly."""
    return vault_dir(root) / node_id / "proof.tex"


def snapshot_path(root: Path, node_id: str, version: int) -> Path:
    # in a subfolder: prism-local takes a folder's only top-level .tex as its main file
    return vault_dir(root) / node_id / "snapshots" / f"v{version}.tex"


def write_working_proof(root: Path, *, node_id: str, kind: str, statement: str) -> None:
    """Create the project preamble and a node's working `proof.tex`, if missing. Never overwrites."""
    preamble = preamble_path(root)
    if not preamble.exists():
        preamble.parent.mkdir(parents=True, exist_ok=True)
        preamble.write_text(PREAMBLE, encoding="utf-8")
    path = working_proof_path(root, node_id)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    environment = _ENVIRONMENTS.get(kind, "claim")
    path.write_text(
        "\\documentclass{amsart}\n"
        "\\input{../preamble}\n"
        "\\begin{document}\n\n"
        f"% Proof map node {node_id} ({kind}).\n"
        f"\\begin{{{environment}}}\n{statement}\n\\end{{{environment}}}\n\n"
        "\\begin{proof}\n% Write the proof here.\n\\end{proof}\n\n"
        "\\end{document}\n",
        encoding="utf-8",
    )


def write_snapshot(path: Path, content: bytes) -> None:
    """Write one immutable Review snapshot. Refuses to overwrite: a revision is a new version."""
    if path.exists():
        raise FileExistsError(f"review snapshot already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


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
