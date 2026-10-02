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
# a node folder's own folders no snapshot freezes and no export carries: regenerated build output
# and the agent's scratch. A snapshot doesn't freeze the frozen snapshots either; an export carries them
_NEVER_CARRIED = frozenset({"build", "scratch"})
_NOT_INPUTS = _NEVER_CARRIED | {"snapshots"}
# never frozen or carried, anywhere in a node folder: tool caches and bytecode (and every hidden
# folder: `.git`, `.venv`, `.pytest_cache`, …); never reported either: the decisions and the OS's metadata
_CACHE_FOLDERS = frozenset({"__pycache__"})
_QUIET = frozenset({"reviews.jsonl", ".DS_Store"})
_BYTECODE = (".pyc", ".pyo")

# The hidden files at a computation node's root that are inputs of its program (the researcher's
# allowlist, Q39): exactly these names, added to only explicitly. Every other dotfile and every
# hidden folder, at any depth and for either medium, is left out, and reported by path.
HIDDEN_INPUTS = frozenset({".python-version", ".tool-versions", ".nvmrc", ".node-version", ".ruby-version"})


def is_secret_name(name: str) -> bool:
    """A file that holds credentials: `.env`, `.env.*`, `.envrc`, `.netrc`."""
    return name in (".env", ".envrc", ".netrc") or name.startswith(".env.")


def is_secret_path(rel: str) -> bool:
    """Whether any part of `rel` is a secret's name: never frozen, never exported, whatever else
    allows it. A check of its own, before and apart from the allowlist, so that no addition to
    HIDDEN_INPUTS can ever let one in."""
    return any(is_secret_name(part) for part in PurePosixPath(rel).parts)


def _frozen_file(rel: PurePosixPath, *, computation: bool) -> bool:
    """Whether a file at `rel` (from the node folder, in a folder that is walked) is one a
    snapshot freezes: never a secret, bytecode or a hidden file, but a computation's allowlisted
    environment files at its root."""
    if is_secret_path(rel.as_posix()):
        return False
    if rel.name in _QUIET or rel.name.endswith(_BYTECODE):
        return False
    if rel.name.startswith("."):
        return computation and len(rel.parts) == 1 and rel.name in HIDDEN_INPUTS
    return True


class NodeFolderLinks(Exception):
    """A node folder holds symbolic links where a snapshot or an export would read: neither follows one."""

    def __init__(self, links: list[tuple[Path, bool]]):
        super().__init__(", ".join(str(path) for path, _ in links))
        self.links = links  # (the link, whether it dangles)


@dataclass
class _Scan:
    files: dict[str, Path]  # what is kept, by its path from the walked folder
    hidden: list[str]  # hidden paths left out, by path only (a folder with a trailing /): never read
    links: list[tuple[Path, bool]]  # symbolic links met where a file would be kept, and whether each dangles


def _scan(folder: Path, *, skip_top: frozenset[str], keep: Callable[[PurePosixPath], bool]) -> _Scan:
    """Walk `folder` in path order, as a snapshot and an export both do: not into `skip_top` at its
    top, `__pycache__` or a hidden folder anywhere; keeping each regular file `keep` accepts. An
    unreadable folder raises (`OSError`, its path as `filename`) rather than being skipped."""

    def fail(error: OSError) -> None:
        raise error

    scan = _Scan({}, [], [])
    for current, folders, files in os.walk(folder, onerror=fail):
        here = Path(current)
        walked = []
        for name in sorted(folders):
            rel = PurePosixPath((here / name).relative_to(folder).as_posix())
            if (len(rel.parts) == 1 and name in skip_top) or name in _CACHE_FOLDERS:
                continue
            if name.startswith("."):
                scan.hidden.append(f"{rel}/")
            elif (here / name).is_symlink():
                scan.links.append((here / name, not (here / name).exists()))
            else:
                walked.append(name)
        folders[:] = walked
        for name in sorted(files):
            path = here / name
            rel = PurePosixPath(path.relative_to(folder).as_posix())
            if not keep(rel):
                if name.startswith(".") and name not in _QUIET:
                    scan.hidden.append(rel.as_posix())
            elif path.is_symlink():
                scan.links.append((path, not path.exists()))
            elif path.is_file():
                scan.files[rel.as_posix()] = path
    scan.hidden.sort()
    return scan


def _working_scan(root: Path, node_id: str, medium: Medium | None) -> _Scan:
    folder = node_folder(root, node_id)
    if not folder.is_dir():
        return _Scan({}, [], [])
    computation = medium == Medium.computation
    return _scan(folder, skip_top=_NOT_INPUTS, keep=lambda rel: _frozen_file(rel, computation=computation))


def working_inputs(root: Path, node_id: str, medium: Medium | None = None) -> dict[str, Path]:
    """Every file a node's snapshot freezes, by its path from the node folder: the node's working
    sources (not its build output, snapshots, scratch folder, reviews, secrets, hidden files or
    folders but a computation's allowlisted environment files at its root, tool caches or
    bytecode, nor symbolic links) and, for a LaTeX document, the shared preamble, as
    "../preamble.tex" — a computation's program doesn't read it, so a preamble edit is no new
    program version. What a snapshot freezes and what a build must be newer than. An unreadable
    folder raises `OSError`."""
    inputs = dict(_working_scan(root, node_id, medium).files)
    if medium != Medium.computation and preamble_path(root).is_file():
        inputs["../preamble.tex"] = preamble_path(root)
    return inputs


def manifest_digest(entries: Mapping[str, str], executable: Iterable[str] = ()) -> str:
    """The SHA-256 a snapshot is known by: of its {path: SHA-256} entries, canonically serialised,
    with which of them are executable when any is (format 2). A snapshot with none — every LaTeX
    one, every one from before format 2 — is hashed exactly as format 1 hashed it."""
    marked = sorted(executable)
    body: object = {"executable": marked, "files": dict(entries)} if marked else dict(entries)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- inputs, outputs and the summary (the researcher's rule, 2026-10-02; Q40) --------------------
# A computation's snapshot freezes its inputs (scripts, allowlisted environment files, data), its
# outputs (`out/`) and its key-ideas summary, for the researcher's review. A later Run counts as
# Evidence only when its inputs match the frozen ones (#147): outputs and the summary don't count.

OUT_DIR = "out"
FrozenRole = Literal["input", "output", "summary"]


def frozen_role(rel: str) -> FrozenRole:
    """What a frozen path (from the node folder, as a manifest names it) is: `"output"` under
    `out/`, `"summary"` for the node's `key-ideas.md`, otherwise `"input"` of its proof."""
    if rel.startswith(OUT_DIR + "/"):
        return "output"
    if rel == KEY_IDEAS_FILE:
        return "summary"
    return "input"


def inputs_digest(entries: Mapping[str, str], executable: Iterable[str] = ()) -> str:
    """`manifest_digest` of the inputs alone: the entries, and executable bits, of role `"input"`."""
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
    skipped_hidden: tuple[str, ...] = ()  # the hidden paths left out, by path only (never read)

    def entries(self) -> dict[str, str]:
        return {rel: hashlib.sha256(data).hexdigest() for rel, data in self.files.items()}

    def digest(self) -> str:
        return manifest_digest(self.entries(), self.executable)

    def inputs_digest(self) -> str:
        return inputs_digest(self.entries(), self.executable)


def read_working_snapshot(root: Path, node_id: str, medium: Medium | None = None) -> SnapshotContents:
    """What the node's snapshot would freeze now, read once, with a computation's executable
    bits: what is hashed is exactly what is frozen. An unreadable file or folder raises
    `OSError` (its path as `filename`); a symbolic link where a file would be read raises
    `NodeFolderLinks`."""
    scan = _working_scan(root, node_id, medium)
    if scan.links:
        raise NodeFolderLinks(scan.links)
    paths = dict(scan.files)
    if medium != Medium.computation and preamble_path(root).is_file():
        paths["../preamble.tex"] = preamble_path(root)
    paths = {rel: path for rel, path in paths.items() if not is_secret_path(rel)}  # the hard deny, once more
    files = {rel: path.read_bytes() for rel, path in paths.items()}
    executable = frozenset(rel for rel, path in paths.items() if medium == Medium.computation and is_executable(path))
    return SnapshotContents(files, executable, tuple(scan.hidden))


def working_links(root: Path, node_id: str, medium: Medium | None = None) -> list[tuple[Path, bool]]:
    """The symbolic links a snapshot of the node would meet where it reads a file or folder (each with whether it
    dangles): what `read_working_snapshot` refuses with `NodeFolderLinks`. A Run's Evidence check (#147) refuses
    only those among the inputs; a link under `out/` is an output, and outputs may differ."""
    return list(_working_scan(root, node_id, medium).links)


def working_inputs_digest(root: Path, node_id: str, medium: Medium | None = None) -> str:
    """The inputs digest of the node folder as it is now: equal to a snapshot's
    `frozen_inputs_digest` exactly when no input changed since it was frozen (`out/` may have).
    Raises `OSError` on an unreadable file or folder."""
    return read_working_snapshot(root, node_id, medium).inputs_digest()


def is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def set_executable(path: Path) -> None:
    """Make `path` executable: an x bit for the user, group and others each where they may read it
    (0o644 becomes 0o755, 0o444 0o555); the write bits stay as they were, never granted."""
    mode = stat.S_IMODE(path.stat().st_mode)
    for read, run in ((stat.S_IRUSR, stat.S_IXUSR), (stat.S_IRGRP, stat.S_IXGRP), (stat.S_IROTH, stat.S_IXOTH)):
        if mode & read:
            mode |= run
    path.chmod(mode)


def _stored(rel: str) -> str:
    return f"{_SHARED}/{rel[3:]}" if rel.startswith("../") else f"{_NODE}/{rel}"


MANIFEST_FORMATS = (1, 2)
# set in a manifest an export stripped of withheld files, or an import found disagreeing with the
# bundle's executable flags: the snapshot is unverifiable, and the value says why (ADR-0015)
UNVERIFIABLE = "unverifiable"


def _manifest_names(manifest: object) -> tuple[list[str], list[str]]:
    """A snapshot manifest's file paths and its executable ones (none in format 1). Raises
    `ValueError`/`KeyError`/`TypeError`/`AttributeError` when it isn't well formed, or its
    `format` isn't one this proof-cli knows (1 or 2): an unknown manifest is unverifiable."""
    version = manifest.get("format")  # type: ignore[union-attr]
    if type(version) is not int or version not in MANIFEST_FORMATS:
        raise ValueError(f"unknown snapshot manifest format: {version!r}")
    if UNVERIFIABLE in manifest:  # type: ignore[operator]
        raise ValueError(f"the manifest is marked unverifiable: {manifest[UNVERIFIABLE]}")  # type: ignore[index]
    names = list(manifest["files"])  # type: ignore[index]
    executable = manifest.get("executable", [])  # type: ignore[union-attr]
    if not isinstance(executable, list) or not all(isinstance(rel, str) and rel in names for rel in executable):
        raise ValueError("the manifest's executable list names a file it doesn't freeze")
    if version == 1 and executable:
        raise ValueError("a format-1 manifest records no executable bit")
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
            set_executable(target)
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
    an edit to any frozen file, or to the executable list its manifest records, changes it. None
    if the snapshot is gone or unreadable, its manifest's format is unknown, or a file the
    manifest records as executable is no longer executable as stored. (A stored file that is
    executable but not recorded so is tolerated: some filesystems mark every file executable.)"""
    try:
        names, executable = _read_manifest(folder)
        entries = {rel: hashlib.sha256((folder / _stored(rel)).read_bytes()).hexdigest() for rel in names}
        if not all(is_executable(folder / _stored(rel)) for rel in executable):
            return None
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


def frozen_digests(folder: Path) -> tuple[str, str] | None:
    """A snapshot folder's SHA-256 and its inputs digest, together: what a Run's Evidence check is bound to,
    and what its inputs were compared with (#147). Exactly `snapshot_folder_digest` and
    `frozen_inputs_digest`; None if either can't be had (the snapshot is gone, unreadable, or lost a
    recorded executable bit). The record checks the bound hash against the snapshot once more."""
    snapshot, inputs = snapshot_folder_digest(folder), frozen_inputs_digest(folder)
    return (snapshot, inputs) if snapshot is not None and inputs is not None else None


def frozen_output_bytes(folder: Path) -> int:
    """How many bytes of `out/` a snapshot folder froze, as stored; 0 if it can't be read."""
    try:
        names, _ = _read_manifest(folder)
        return sum((folder / _stored(rel)).stat().st_size for rel in names if frozen_role(rel) == "output")
    except _UNREADABLE:
        return 0


def snapshot_digest_of(
    manifest: bytes | None,
    stored: Callable[[str], bytes | None],
    executable: Callable[[str], bool] | None = None,
) -> str | None:
    """`snapshot_folder_digest` over files that aren't on disk (an exchange bundle's, say):
    `manifest` is the snapshot's manifest.json, `stored(path)` a file by its path inside the
    snapshot folder and `executable(path)` whether the bundle carries it executable. None when
    the manifest is unreadable or marked unverifiable, a file it names is missing, or (with
    `executable`) a file's flag disagrees with the manifest's executable list, either way."""
    try:
        names, marked = _manifest_names(json.loads((manifest or b"").decode("utf-8")))
    except (*_UNREADABLE, UnicodeDecodeError):
        return None
    entries: dict[str, str] = {}
    for rel in names:
        data = stored(_stored(rel)) if isinstance(rel, str) else None
        if data is None:
            return None
        if executable is not None and executable(_stored(rel)) != (rel in marked):
            return None
        entries[rel] = hashlib.sha256(data).hexdigest()
    return manifest_digest(entries, marked)


def manifest_executables(manifest: bytes | None) -> list[str]:
    """The files a snapshot manifest records as executable, by their path inside the snapshot
    folder (`node/run.sh`); none when it can't be read."""
    try:
        return [_stored(rel) for rel in json.loads((manifest or b"").decode("utf-8")).get("executable", []) if isinstance(rel, str)]
    except (*_UNREADABLE, UnicodeDecodeError):
        return []


def mark_unverifiable(manifest: bytes, reason: str, *, without: Iterable[str] = ()) -> bytes:
    """`manifest` marked unverifiable for `reason`, and with no entry, hash or executable flag
    for the frozen files `without` (by their path from the node folder): what an export carries
    when it withholds them (ADR-0015), so that nothing in the bundle betrays their contents."""
    data = json.loads(manifest.decode("utf-8"))
    dropped = set(without)
    data["files"] = {rel: sha for rel, sha in data.get("files", {}).items() if rel not in dropped}
    if "executable" in data:
        data["executable"] = [rel for rel in data["executable"] if rel not in dropped]
    data[UNVERIFIABLE] = reason
    return (json.dumps(data, indent=1, sort_keys=True) + "\n").encode("utf-8")


@dataclass
class ExchangedFiles:
    files: dict[str, Path]  # by path from the project root
    # per snapshot folder (from the project root, with a trailing /) the frozen files it names
    # that the export leaves out — secrets, hidden or cache files an older rule froze — so the
    # snapshot no longer verifies where it is imported
    withheld: dict[str, list[str]]


def _carried(rel: PurePosixPath, computation: bool) -> bool:
    """Whether an export carries the file at `rel` in a node folder: by the snapshot's own rule
    (`_frozen_file`), applied inside a snapshot folder to the path it froze."""
    parts = rel.parts
    if parts[0] != "snapshots":
        return _frozen_file(rel, computation=computation)
    if len(parts) >= 4 and parts[2] == _NODE:
        return _frozen_file(PurePosixPath(*parts[3:]), computation=True)  # a computation it once was may freeze allowlisted files
    if len(parts) >= 4 and parts[2] == _SHARED:
        return _frozen_file(PurePosixPath(*parts[3:]), computation=False)
    return _frozen_file(PurePosixPath(rel.name), computation=False)


def exchanged_files(root: Path, node_id: str, medium: Medium | None = None) -> ExchangedFiles:
    """The files an exchange bundle carries for a node: its working sources and snapshots, walked
    and filtered as a snapshot is (no build output, scratch folder, `reviews.jsonl`, secret,
    hidden file or folder but a computation's allowlisted ones, tool cache or bytecode), and the
    frozen files of each snapshot it must leave out. An unreadable folder raises `OSError`; a
    symbolic link, `NodeFolderLinks`."""
    folder = node_folder(root, node_id)
    if not folder.is_dir():
        return ExchangedFiles({}, {})
    computation = medium == Medium.computation
    scan = _scan(folder, skip_top=_NEVER_CARRIED, keep=lambda rel: _carried(rel, computation))
    if scan.links:
        raise NodeFolderLinks(scan.links)
    withheld: dict[str, list[str]] = {}
    for rel in scan.files:
        parts = PurePosixPath(rel).parts
        if len(parts) == 3 and parts[0] == "snapshots" and parts[2] == SNAPSHOT_MANIFEST:
            try:
                names = list(json.loads(scan.files[rel].read_text(encoding="utf-8"))["files"])
            except (*_UNREADABLE, UnicodeDecodeError):
                continue  # carried as it is: the importer finds it unreadable, as here
            base = f"snapshots/{parts[1]}/"
            missing = sorted(name for name in names if isinstance(name, str) and base + _stored(name) not in scan.files)
            if missing:
                withheld[f"{folder.relative_to(root).as_posix()}/{base}"] = missing
    files = {path.relative_to(root).as_posix(): path for path in scan.files.values()}
    return ExchangedFiles(files, withheld)


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
# It runs in this folder. Write everything it produces (tables, figures, logs) into out/ and
# nowhere else: anything written outside out/ changes the program's own inputs, so its runs no
# longer match the frozen program and aren't recorded as Evidence. The review snapshot freezes
# the inputs (scripts, data, .python-version and the like; never .env or other secrets) and
# out/, and the researcher's Acceptance judges whether what was frozen establishes the
# statement. Exit 0 when the computation establishes it.
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
