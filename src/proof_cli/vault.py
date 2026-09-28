from __future__ import annotations

from pathlib import Path


def vault_dir(root: Path) -> Path:
    return root / "proofs"


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


def snapshots_on_disk(root: Path, node_id: str) -> dict[int, Path]:
    """Every `snapshots/v<N>.tex` actually present, by version, indexed or not."""
    folder = snapshot_path(root, node_id, 1).parent
    found: dict[int, Path] = {}
    for path in folder.glob("v*.tex") if folder.is_dir() else ():
        number = path.stem[1:]
        if number.isdigit():
            found[int(number)] = path
    return found


def build_pdf_path(root: Path, node_id: str) -> Path:
    """Where prism-local (default `outdir: build`) compiles the working proof.tex."""
    return vault_dir(root) / node_id / "build" / "proof.pdf"


def node_folder(root: Path, node_id: str) -> Path:
    return vault_dir(root) / node_id


_NOT_SOURCES = {"build", "snapshots"}


def build_is_current(root: Path, node_id: str) -> bool:
    """Whether prism-local's build/proof.pdf is at least as new as every source it may be built from:
    the node folder's files (not its build output, snapshots or reviews) and the shared preamble."""
    pdf = build_pdf_path(root, node_id)
    if not pdf.is_file():
        return False
    folder = node_folder(root, node_id)
    sources = [preamble_path(root)] + [
        path
        for path in folder.rglob("*")
        if path.is_file() and path.relative_to(folder).parts[0] not in _NOT_SOURCES and path.name != "reviews.jsonl"
    ]
    built = pdf.stat().st_mtime
    return all(source.stat().st_mtime <= built for source in sources if source.exists())


def write_working_proof(root: Path, *, node_id: str, kind: str, statement: str) -> None:
    """Create the project preamble and a node's working `proof.tex`, if missing. Never overwrites."""
    preamble = preamble_path(root)
    if not preamble.exists():
        preamble.parent.mkdir(parents=True, exist_ok=True)
        preamble.write_text(PREAMBLE, encoding="utf-8")
    ignore = vault_dir(root) / ".gitignore"
    if not ignore.exists():
        # build output is regenerated; what's reviewed is the snapshot (and its archived PDF)
        ignore.write_text("*/build/\n", encoding="utf-8")
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
