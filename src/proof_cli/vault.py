from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator, Literal, Mapping

from .domain import Medium
from .key_ideas import KEY_IDEAS_FILE, TEMPLATE_COMPUTATION as KEY_IDEAS_TEMPLATE_COMPUTATION


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
# never frozen, anywhere in a node folder: tool caches and bytecode (nor hidden folders: `.git`,
# `.pytest_cache`, `.venv` and the like), the decisions, and the OS's folder metadata
_CACHE_FOLDERS = {"__pycache__"}
_NEVER_FROZEN = {"reviews.jsonl", ".DS_Store"}
_BYTECODE = (".pyc", ".pyo")


def _skipped_folder(rel: PurePosixPath) -> bool:
    """A folder of the node folder whose files a snapshot never freezes: not walked at all."""
    return (len(rel.parts) == 1 and rel.name in _NOT_INPUTS) or rel.name.startswith(".") or rel.name in _CACHE_FOLDERS


def _frozen_file(rel: PurePosixPath, *, computation: bool) -> bool:
    """Whether a file at `rel` (from the node folder, in a folder that is walked) is an input a snapshot freezes."""
    if rel.name in _NEVER_FROZEN or rel.name.endswith(_BYTECODE):
        return False
    if rel.name.startswith("."):
        # a computation's hidden environment files at its root (.python-version, .envrc,
        # .tool-versions, …) are inputs of its program; a LaTeX document has none
        return computation and len(rel.parts) == 1
    return True


def _walk(folder: Path) -> Iterator[Path]:
    """Every file under `folder` in a folder a snapshot walks, in path order. An unreadable folder
    raises (`OSError`, its path as `filename`) rather than being skipped: a snapshot freezes all."""

    def fail(error: OSError) -> None:
        raise error

    for current, folders, files in os.walk(folder, onerror=fail):
        here = Path(current)
        folders[:] = sorted(name for name in folders if not _skipped_folder(PurePosixPath((here / name).relative_to(folder).as_posix())))
        for name in sorted(files):
            yield here / name


def working_inputs(root: Path, node_id: str, medium: Medium | None = None) -> dict[str, Path]:
    """Every input of a node's proof, by its path from the node folder: the node's working sources
    (not its build output, snapshots, scratch folder, reviews, hidden folders, tool caches or
    bytecode, nor hidden files but a computation's at its root) and, for a LaTeX document, the
    shared preamble, as "../preamble.tex" — a computation's program doesn't read it, so a
    preamble edit is no new program version. What a snapshot freezes and what a build must be
    newer than. An unreadable folder raises `OSError`."""
    folder = node_folder(root, node_id)
    computation = medium == Medium.computation
    inputs: dict[str, Path] = {}
    for path in _walk(folder) if folder.is_dir() else ():
        rel = PurePosixPath(path.relative_to(folder).as_posix())
        if path.is_file() and _frozen_file(rel, computation=computation):
            inputs[rel.as_posix()] = path
    if not computation and preamble_path(root).is_file():
        inputs["../preamble.tex"] = preamble_path(root)
    return inputs


def manifest_digest(entries: Mapping[str, str], executable: Iterable[str] = ()) -> str:
    """The SHA-256 a snapshot is known by: of its {path: SHA-256} entries, canonically serialised,
    with which of them are executable when any is (format 2). A snapshot with none — every LaTeX
    one, every one from before format 2 — is hashed exactly as format 1 hashed it."""
    marked = sorted(executable)
    body: object = {"executable": marked, "files": dict(entries)} if marked else dict(entries)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- inputs and outputs (the researcher's rule, 2026-10-02) -------------------------------------
# A computation's snapshot freezes its inputs (scripts, hidden environment files, data) and its
# outputs (`out/`). A later Run counts as Evidence only when its inputs match the frozen ones (#147).

OUT_DIR = "out"


def frozen_role(rel: str) -> Literal["input", "output"]:
    """Whether a frozen path (from the node folder, as a manifest names it) is an input of the
    node's proof or an output its program wrote: everything under `out/` is output."""
    return "output" if rel.startswith(OUT_DIR + "/") else "input"


def inputs_digest(entries: Mapping[str, str], executable: Iterable[str] = ()) -> str:
    """`manifest_digest` of the inputs alone: the entries, and executable bits, outside `out/`."""
    return manifest_digest(
        {rel: sha for rel, sha in entries.items() if frozen_role(rel) == "input"},
        [rel for rel in executable if frozen_role(rel) == "input"],
    )


@dataclass(frozen=True)
class SnapshotContents:
    """What a Review snapshot freezes, read once: each file's bytes by its path from the node
    folder, and which are executable — recorded for a computation only: on a LaTeX source the bit
    means nothing, and a LaTeX snapshot is hashed as it always was."""

    files: dict[str, bytes]
    executable: frozenset[str] = frozenset()

    def entries(self) -> dict[str, str]:
        return {rel: hashlib.sha256(data).hexdigest() for rel, data in self.files.items()}

    def digest(self) -> str:
        return manifest_digest(self.entries(), self.executable)

    def inputs_digest(self) -> str:
        return inputs_digest(self.entries(), self.executable)


def read_working_snapshot(root: Path, node_id: str, medium: Medium | None = None) -> SnapshotContents:
    """The node's `working_inputs`, read once, with a computation's executable bits: what is
    hashed is exactly what is frozen. An unreadable file or folder raises `OSError`, its path
    as `filename`."""
    paths = working_inputs(root, node_id, medium)
    files = {rel: path.read_bytes() for rel, path in paths.items()}
    executable = frozenset(rel for rel, path in paths.items() if medium == Medium.computation and is_executable(path))
    return SnapshotContents(files, executable)


def working_inputs_digest(root: Path, node_id: str, medium: Medium | None = None) -> str:
    """The inputs digest of the node folder as it is now: equal to a snapshot's
    `frozen_inputs_digest` exactly when no input changed since it was frozen (`out/` may have).
    Raises `OSError` on an unreadable file or folder."""
    return read_working_snapshot(root, node_id, medium).inputs_digest()


def is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def _stored(rel: str) -> str:
    return f"{_SHARED}/{rel[3:]}" if rel.startswith("../") else f"{_NODE}/{rel}"


def _manifest_names(manifest: object) -> tuple[list[str], list[str]]:
    """A snapshot manifest's file paths and its executable ones (none in format 1). Raises
    `ValueError`/`KeyError`/`TypeError`/`AttributeError` when it isn't well formed."""
    names = list(manifest["files"])  # type: ignore[index]
    executable = manifest.get("executable", [])  # type: ignore[union-attr]
    if not isinstance(executable, list) or not all(isinstance(rel, str) and rel in names for rel in executable):
        raise ValueError("the manifest's executable list names a file it doesn't freeze")
    return names, executable


def _read_manifest(folder: Path) -> tuple[list[str], list[str]]:
    return _manifest_names(json.loads((folder / SNAPSHOT_MANIFEST).read_text(encoding="utf-8")))


_UNREADABLE = (OSError, ValueError, KeyError, TypeError, AttributeError)


def write_snapshot_folder(folder: Path, contents: SnapshotContents) -> dict[str, str]:
    """Freeze `contents` as one Review snapshot, with its manifest (format 2: each file's SHA-256,
    and which are executable); the entries it records. A stored file keeps its executable bit.
    Refuses to overwrite: a revision is a new version."""
    if folder.exists():
        raise FileExistsError(f"review snapshot already exists: {folder}")
    entries = contents.entries()
    for rel, data in contents.files.items():
        target = folder / _stored(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if rel in contents.executable:
            target.chmod(target.stat().st_mode | 0o111)
    manifest = {"format": 2, "files": entries, "executable": sorted(contents.executable)}
    (folder / SNAPSHOT_MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
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
    an edit to any frozen file, or to the modes its manifest records, changes it. None if the
    snapshot is gone or unreadable."""
    try:
        names, executable = _read_manifest(folder)
        entries = {rel: hashlib.sha256((folder / _stored(rel)).read_bytes()).hexdigest() for rel in names}
    except _UNREADABLE:
        return None
    return manifest_digest(entries, executable)


def frozen_inputs_digest(folder: Path) -> str | None:
    """`inputs_digest` of a snapshot folder, recomputed from the files stored now: what a later
    Run's `working_inputs_digest` must equal for its inputs to be the frozen ones (#147). None if
    the snapshot is gone or unreadable."""
    try:
        names, executable = _read_manifest(folder)
        entries = {rel: hashlib.sha256((folder / _stored(rel)).read_bytes()).hexdigest() for rel in names if frozen_role(rel) == "input"}
    except _UNREADABLE:
        return None
    return inputs_digest(entries, executable)


def frozen_output_bytes(folder: Path) -> int:
    """How many bytes of `out/` a snapshot folder froze, as stored; 0 if it can't be read."""
    try:
        names, _ = _read_manifest(folder)
        return sum((folder / _stored(rel)).stat().st_size for rel in names if frozen_role(rel) == "output")
    except _UNREADABLE:
        return 0


def snapshot_digest_of(manifest: bytes | None, stored: Callable[[str], bytes | None]) -> str | None:
    """`snapshot_folder_digest` over files that aren't on disk (an exchange bundle's, say):
    `manifest` is the snapshot's manifest.json and `stored(path)` a file by its path inside
    the snapshot folder. None when the manifest is unreadable or a file it names is missing."""
    try:
        names, executable = _manifest_names(json.loads((manifest or b"").decode("utf-8")))
    except (*_UNREADABLE, UnicodeDecodeError):
        return None
    entries: dict[str, str] = {}
    for rel in names:
        data = stored(_stored(rel)) if isinstance(rel, str) else None
        if data is None:
            return None
        entries[rel] = hashlib.sha256(data).hexdigest()
    return manifest_digest(entries, executable)


# what an exchange bundle leaves out of a node folder: regenerated output, the agent's scratch,
# and the node's recorded decisions, which count only where they were made (ADR-0010, #31)
_NOT_EXCHANGED = {"build", "scratch"}


def exchanged_files(root: Path, node_id: str, medium: Medium | None = None) -> dict[str, Path]:
    """The files an exchange bundle carries for a node, by their path from the project root:
    its working sources, snapshots and archived PDFs, never its build output, scratch folder,
    hidden folders or `reviews.jsonl`, nor hidden files but those a snapshot froze and a
    computation's at its root (its environment files)."""
    folder = node_folder(root, node_id)
    found: dict[str, Path] = {}
    for path in sorted(folder.rglob("*")) if folder.is_dir() else ():
        rel = path.relative_to(folder)
        if not path.is_file() or path.is_symlink() or rel.parts[0] in _NOT_EXCHANGED or rel.name == "reviews.jsonl":
            continue
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        if rel.name.startswith(".") and not (rel.parts[0] == "snapshots" or (medium == Medium.computation and len(rel.parts) == 1)):
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
    inputs = {rel: path for rel, path in working_inputs(root, node_id, Medium.latex).items() if rel != KEY_IDEAS_FILE}
    return all(source.stat().st_mtime <= built for source in inputs.values() if source.exists())


def write_working_proof(root: Path, *, node_id: str, kind: str, statement: str) -> None:
    """Create the project preamble and a node's working `proof.tex`, if missing. Never overwrites."""
    preamble = preamble_path(root)
    if not preamble.exists():
        preamble.parent.mkdir(parents=True, exist_ok=True)
        preamble.write_text(PREAMBLE, encoding="utf-8")
    _ensure_vault_ignore(root)
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


def _ensure_vault_ignore(root: Path) -> None:
    """The vault's .gitignore, once: build output is regenerated; what's reviewed is the snapshot (and its archived PDF)."""
    ignore = vault_dir(root) / ".gitignore"
    if not ignore.exists():
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_text("*/build/\n", encoding="utf-8")


RUN_SCRIPT = "run.sh"
OUT_DIR = "out"
_RUN_SKELETON = """\
#!/usr/bin/env bash
# Proof map node {node_id} ({kind}), medium: computation.
# This script is the computation that is meant to establish the statement:
#   {statement}
# It runs in this folder. Write what it produces (tables, figures, logs) into out/ — the
# review snapshot freezes this folder, out/ included, and the researcher's Acceptance judges
# whether what was frozen establishes the statement. Exit 0 when the computation establishes it.
set -euo pipefail
mkdir -p out
echo "nothing computed yet" > out/run.log
exit 1
"""


def write_working_computation(root: Path, *, node_id: str, kind: str, statement: str) -> None:
    """Create a computation node's folder, if missing: an executable `run.sh` skeleton and a
    key-ideas skeleton — and no `proof.tex` (spec #145). Never overwrites."""
    _ensure_vault_ignore(root)
    folder = node_folder(root, node_id)
    folder.mkdir(parents=True, exist_ok=True)
    run = folder / RUN_SCRIPT
    if not run.exists():
        run.write_text(_RUN_SKELETON.format(node_id=node_id, kind=kind, statement=statement.replace("\n", " ")), encoding="utf-8")
        run.chmod(run.stat().st_mode | 0o111)
    key_ideas = folder / KEY_IDEAS_FILE
    if not key_ideas.exists():
        key_ideas.write_text(KEY_IDEAS_TEMPLATE_COMPUTATION, encoding="utf-8")


def run_script_path(root: Path, node_id: str) -> Path:
    return node_folder(root, node_id) / RUN_SCRIPT


PROJECT_CONFIG = "proof.toml"
LARGE_OUTPUT_MB = 50  # a notice, never a refusal, when a snapshot freezes more of out/ than this (spec #145)


def large_output_threshold(root: Path) -> int:
    """The bytes of frozen `out/` above which requesting review gives SNAPSHOT_LARGE_OUTPUT:
    `proof.toml`'s `[snapshot] large_output_mb`, else 50 MB."""
    try:
        configured = tomllib.loads((root / PROJECT_CONFIG).read_text(encoding="utf-8")).get("snapshot", {}).get("large_output_mb")
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        configured = None
    valid = isinstance(configured, (int, float)) and not isinstance(configured, bool) and configured >= 0
    return int((configured if valid else LARGE_OUTPUT_MB) * 1024 * 1024)


def working_entry_path(root: Path, node_id: str, medium: Medium | None) -> Path:
    """The file a node's work starts from, by its Medium (spec #145): a computation's run.sh, otherwise proof.tex."""
    return run_script_path(root, node_id) if medium == Medium.computation else working_proof_path(root, node_id)


def write_snapshot(path: Path, content: bytes) -> None:
    """Write one immutable Review snapshot. Refuses to overwrite: a revision is a new version."""
    if path.exists():
        raise FileExistsError(f"review snapshot already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
