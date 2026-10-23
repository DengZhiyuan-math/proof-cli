"""What changed between two versions of a node, computed from their Review snapshots, never declared (ADR-0025 point 23,
#264): a role saying what kind of fix it made may say it wrongly; the snapshots cannot.

A change is to one or more of four parts:
- `statement`: what the document states before its proof — the statement, the node's assumptions, the definitions it is
  written in;
- `proof`: the proof itself and its Uses of dependencies, a file it inputs, a computation's program or outputs;
- `key-ideas`: the key-ideas summary;
- `citations or metadata`: the rest the document carries — what it cites and its bibliography, its own preamble lines,
  its comments, the shared preamble, a .bib file.

Which objection a version settles is said by the passed Verdict's endings (ADR-0025 point 9), not here.
"""

from __future__ import annotations

import re

from .key_ideas import KEY_IDEAS_FILE
from .node_check import strip_comments
from .proof_map import ProofMapError, require_node
from .storage import ProjectStore
from .vault import snapshot_dir, snapshot_folder_files

PARTS = STATEMENT, PROOF, KEY_IDEAS, CITATIONS = ("statement", "proof", "key-ideas", "citations or metadata")
_BIBLIOGRAPHY = re.compile(r"\\bibliography(?:style)?\s*\{[^}]*\}|\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.S)
# a citation wherever it stands (\cite, \citep, \parencite, ... with its notes): which work is cited is a citation's
# change, not the statement's or the proof's
_CITE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{[^}]*\}")
_BEGIN_DOCUMENT = re.compile(r"\\begin\{document\}")
_BEGIN_PROOF = re.compile(r"\\begin\{proof\}")
_END_DOCUMENT = re.compile(r"\\end\{document\}")


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _regions(tex: str) -> dict[str, str]:
    """proof.tex in its parts, each whitespace-normalized and its comments set aside: before its first proof
    (`statement`), from there to the end of the document (`proof`), and the rest (`citations or metadata`: what it
    cites, its bibliography, the lines before \\begin{document}, and what follows the document). A citation leaves its
    place marked, so moving one is still a change where it moved to."""
    stripped = strip_comments(tex)
    cited = [match.group(0) for match in _CITE.finditer(stripped)] + [match.group(0) for match in _BIBLIOGRAPHY.finditer(stripped)]
    body = _BIBLIOGRAPHY.sub(" ", _CITE.sub(r"\\cite{}", stripped))
    begin = _BEGIN_DOCUMENT.search(body)
    start = begin.end() if begin else 0
    proof = _BEGIN_PROOF.search(body, start)
    end = _END_DOCUMENT.search(body, start)
    proof_at = proof.start() if proof else (end.start() if end else len(body))
    end_at = end.start() if end else len(body)
    return {STATEMENT: _normal(body[start:proof_at]), PROOF: _normal(body[proof_at:end_at]),
            CITATIONS: _normal(" ".join((body[:start], body[end_at:], *cited)))}


def _part_of(rel: str) -> str:
    """The part a frozen file other than proof.tex belongs to."""
    if rel == KEY_IDEAS_FILE:
        return KEY_IDEAS
    if rel == "../preamble.tex" or rel.endswith(".bib"):
        return CITATIONS
    return PROOF


def _files(store: ProjectStore, node_id: str, version: int) -> dict[str, bytes]:
    files = snapshot_folder_files(snapshot_dir(store.root, node_id, version))
    if files is None:
        raise ProofMapError("SNAPSHOT_UNREADABLE", f"snapshot v{version} of {node_id} is missing or can't be read",
                            details={"node_id": node_id, "version": version})
    return files


def version_diff(store: ProjectStore, node_id: str, old: int, new: int) -> dict:
    """{"node_id", "from", "to", "parts": the parts that changed, in `PARTS` order, "files": {"added", "removed",
    "changed"}} between snapshots v`old` and v`new` of the node, from what they froze."""
    require_node(store, node_id)
    before, after = _files(store, node_id, old), _files(store, node_id, new)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(rel for rel in set(before) & set(after) if before[rel] != after[rel])
    parts: set[str] = set()
    for rel in (*added, *removed, *changed):
        if rel != "proof.tex":
            parts.add(_part_of(rel))
            continue
        was, now = (_regions(files[rel].decode("utf-8", errors="replace")) if rel in files else {} for files in (before, after))
        moved = {part for part in (STATEMENT, PROOF, CITATIONS) if was.get(part) != now.get(part)}
        parts |= moved or {CITATIONS}   # the same once comments are set aside: a comment changed
    return {"node_id": node_id, "from": old, "to": new, "parts": [part for part in PARTS if part in parts],
            "files": {"added": added, "removed": removed, "changed": changed}}


__all__ = ["PARTS", "version_diff"]
