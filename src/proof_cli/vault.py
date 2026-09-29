from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable

from .key_ideas import KEY_IDEAS_FILE


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


def snapshot_dir(root: Path, node_id: str, version: int) -> Path:
    """A Review snapshot since ADR-0011: every input of the proof, frozen together (see `write_snapshot_folder`)."""
    return vault_dir(root) / node_id / "snapshots" / f"v{version}"


def archived_pdf_path(root: Path, node_id: str, version: int) -> Path:
    """The PDF archived with snapshot v<N>, beside it, for a folder snapshot and an old single-file one alike."""
    return vault_dir(root) / node_id / "snapshots" / f"v{version}.pdf"


def snapshots_on_disk(root: Path, node_id: str) -> dict[int, Path]:
    """Every version present in `snapshots/`, indexed or not: its `v<N>/` folder or `v<N>.tex`, or
    else a lone `v<N>.pdf` — whose number is taken too, so no new snapshot adopts a PDF of other text."""
    folder = snapshot_path(root, node_id, 1).parent
    found: dict[int, Path] = {}
    for path in sorted(folder.iterdir(), key=lambda p: p.suffix == ".pdf") if folder.is_dir() else ():
        number = path.stem[1:]
        if path.stem.startswith("v") and number.isdigit() and (path.is_dir() or path.suffix in (".tex", ".pdf")):
            found.setdefault(int(number), path)
    return found


# -- what a Review snapshot freezes (ADR-0011 point 5) --------------------------------------

SNAPSHOT_MANIFEST = "manifest.json"
# Inside a snapshot folder the node's files live under node/ and the shared preamble
# ("../preamble.tex" from the node folder) under shared/, beside the manifest: whatever the
# node's files are named, none can land on the manifest or the preamble (PR #78 review).
_NODE, _SHARED = "node", "shared"
# a node folder's own folders that are not inputs of its proof: output, frozen snapshots, the agent's scratch
_NOT_INPUTS = {"build", "snapshots", "scratch"}


def working_inputs(root: Path, node_id: str) -> dict[str, Path]:
    """Every input of a node's proof, by its path from the node folder: the node's working sources
    (not its build output, snapshots, scratch folder, reviews or hidden files) and the shared
    preamble, as "../preamble.tex". What a snapshot freezes and what a build must be newer than."""
    folder = node_folder(root, node_id)
    inputs: dict[str, Path] = {}
    for path in sorted(folder.rglob("*")) if folder.is_dir() else ():
        rel = path.relative_to(folder)
        if not path.is_file() or rel.parts[0] in _NOT_INPUTS or rel.name == "reviews.jsonl" or any(part.startswith(".") for part in rel.parts):
            continue
        inputs[rel.as_posix()] = path
    if preamble_path(root).is_file():
        inputs["../preamble.tex"] = preamble_path(root)
    return inputs


def manifest_digest(entries: dict[str, str]) -> str:
    """The SHA-256 a snapshot is known by: of its {path: SHA-256} entries, canonically serialised."""
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _stored(rel: str) -> str:
    return f"{_SHARED}/{rel[3:]}" if rel.startswith("../") else f"{_NODE}/{rel}"


def write_snapshot_folder(folder: Path, contents: dict[str, bytes]) -> dict[str, str]:
    """Freeze `contents` ({path from the node folder: bytes}) as one Review snapshot, with its
    manifest; the entries it records. Refuses to overwrite: a revision is a new version."""
    if folder.exists():
        raise FileExistsError(f"review snapshot already exists: {folder}")
    entries = {rel: hashlib.sha256(data).hexdigest() for rel, data in contents.items()}
    for rel, data in contents.items():
        target = folder / _stored(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (folder / SNAPSHOT_MANIFEST).write_text(json.dumps({"format": 1, "files": entries}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return entries


def snapshot_folder_files(folder: Path) -> dict[str, bytes] | None:
    """The files a snapshot folder froze, by their path from the node folder, as stored now;
    None when its manifest or any file it names can't be read (a damaged snapshot, shown as such)."""
    try:
        manifest = json.loads((folder / SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
        names = list(manifest["files"])
        return {rel: (folder / _stored(rel)).read_bytes() for rel in names if isinstance(rel, str) and (folder / _stored(rel)).is_file()}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def snapshot_folder_file(folder: Path, rel: str) -> bytes | None:
    """One file a snapshot folder froze, by its path from the node folder, as stored now; None
    when the snapshot didn't freeze it, or it can't be read. Reads only that file and the manifest."""
    try:
        manifest = json.loads((folder / SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
        return (folder / _stored(rel)).read_bytes() if rel in manifest["files"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def frozen_key_ideas(root: Path, file_path: str) -> bytes | None:
    """The key-ideas summary a Review snapshot froze (ADR-0013), by the snapshot's `file_path`;
    None for one that froze none: an older snapshot, a single-file one, or one that can't be read."""
    path = root / file_path
    return snapshot_folder_file(path.parent, KEY_IDEAS_FILE) if path.name == SNAPSHOT_MANIFEST else None


def snapshot_folder_digest(folder: Path) -> str | None:
    """The snapshot's SHA-256 recomputed from the files stored now, not read from its manifest:
    an edit to any frozen file changes it. None if the snapshot is gone or unreadable."""
    try:
        manifest = json.loads((folder / SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
        entries = {rel: hashlib.sha256((folder / _stored(rel)).read_bytes()).hexdigest() for rel in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return manifest_digest(entries)


def snapshot_digest_of(manifest: bytes | None, stored: Callable[[str], bytes | None]) -> str | None:
    """`snapshot_folder_digest` over files that aren't on disk (an exchange bundle's, say):
    `manifest` is the snapshot's manifest.json and `stored(path)` a file by its path inside
    the snapshot folder. None when the manifest is unreadable or a file it names is missing."""
    try:
        names = list(json.loads((manifest or b"").decode("utf-8"))["files"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    entries: dict[str, str] = {}
    for rel in names:
        data = stored(_stored(rel)) if isinstance(rel, str) else None
        if data is None:
            return None
        entries[rel] = hashlib.sha256(data).hexdigest()
    return manifest_digest(entries)


# what an exchange bundle leaves out of a node folder: regenerated output, the agent's scratch,
# and the node's recorded decisions, which count only where they were made (ADR-0010, #31)
_NOT_EXCHANGED = {"build", "scratch"}


def exchanged_files(root: Path, node_id: str) -> dict[str, Path]:
    """The files an exchange bundle carries for a node, by their path from the project root:
    its working sources, snapshots and archived PDFs, never its build output, scratch folder,
    hidden files or `reviews.jsonl`."""
    folder = node_folder(root, node_id)
    found: dict[str, Path] = {}
    for path in sorted(folder.rglob("*")) if folder.is_dir() else ():
        rel = path.relative_to(folder)
        if not path.is_file() or path.is_symlink() or rel.parts[0] in _NOT_EXCHANGED or rel.name == "reviews.jsonl":
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        found[path.relative_to(root).as_posix()] = path
    return found


def remove_snapshot(path: Path) -> None:
    """Undo a snapshot this request wrote (a folder or a file), when its transaction rolls back."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def build_pdf_path(root: Path, node_id: str) -> Path:
    """Where prism-local (default `outdir: build`) compiles the working proof.tex."""
    return vault_dir(root) / node_id / "build" / "proof.pdf"


def node_folder(root: Path, node_id: str) -> Path:
    return vault_dir(root) / node_id


def build_is_current(root: Path, node_id: str) -> bool:
    """Whether the studio's build/proof.pdf is at least as new as every input a snapshot freezes
    (`working_inputs`) that goes into the PDF: the node's working sources and the shared
    preamble, but not its key-ideas summary."""
    pdf = build_pdf_path(root, node_id)
    if not pdf.is_file():
        return False
    built = pdf.stat().st_mtime
    # the key-ideas summary is frozen with the proof but isn't compiled into its PDF (ADR-0013)
    inputs = {rel: path for rel, path in working_inputs(root, node_id).items() if rel != KEY_IDEAS_FILE}
    return all(source.stat().st_mtime <= built for source in inputs.values() if source.exists())


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
