"""Mechanical checks of a node's working proof (issue #180): what a program can settle before any agent reads it.

A Proof agent's run spent turns on `ls`, `cat`, `grep error build/*.log` and reading `--help`: discovering the folder and
checking what needs no judgment. These checks are that work, done once, deterministically and read-only — does the
proof build and build cleanly, is the summary there with its four headings, does proof.tex's theorem environment state
what the node states, do its `\\input`s (and theirs) stay in the folder, is each dependency at least mentioned. The run
gates the Verifier on them (an error sends the work back to the role that owns the files; the Verifier is briefed that
they passed and reads only the mathematics), and `proof node check` shows them to anyone. Nothing here is a
verification: whether a step holds is the Verifier's and the researcher's. A finding is a notice (`CHECK_*` in
errors.NOTICE_CODES), never a refusal, and never stops the researcher's own request-review.
"""

from __future__ import annotations

import re
from pathlib import Path

from .domain import ProofMapNodeKind, is_computation
from .key_ideas import FIELDS, KEY_IDEAS_FILE, parse
from .storage import ProjectStore
from .vault import build_is_current, build_pdf_path, node_folder, preamble_path, run_script_path, working_entry_path

ERROR, NOTE = "error", "note"
# \input{file}, \input {file}, \input⏎{file}, and TeX's own \input file␣ (no braces); \include{file} too — not \includegraphics, \inputencoding
_INPUT = re.compile(r"\\(?:input|include)(?![A-Za-z@])\s*(?:\{([^}]*)\}|([^\s{}\\%]+))")
_ENVIRONMENTS = ("theorem", "lemma", "claim", "proposition", "corollary")
_ENV = re.compile(r"\\begin\{(" + "|".join(_ENVIRONMENTS) + r")\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}", re.S)
_UNDEFINED = re.compile(r"undefined (reference|citation)|There were undefined (references|citations)|Reference `[^']*' on page \d+ undefined|Citation `[^']*' on page \d+ undefined", re.I)
_ID_LIKE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
# how key-ideas.md's 主要步骤 names a node: `id`, (id) or \ref{id} (the Typesetter's guide: each step names the node it uses, by id)
_NAMED = re.compile(r"`([^`\s]+)`|\(([A-Za-z][A-Za-z0-9_.-]*)\)|\\(?:eq|c|auto)?ref\{([^}]+)\}")
MAX_INPUT_FILES = 50   # files read through \input, at most


def _finding(code: str, level: str, message: str, path: str | None = None) -> dict:
    found = {"code": code, "level": level, "message": message}
    if path:
        found["path"] = path
    return found


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _mentions(node_id: str, *texts: str) -> bool:
    pattern = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(node_id) + r"(?![A-Za-z0-9_.-])")
    return any(pattern.search(text) for text in texts if text)


def _strip_comments(tex: str) -> str:
    """The text without its comments: a `%` opens one unless an odd number of backslashes precedes it (`\\%` is a percent sign,
    `\\\\%` is a line break and then a comment), to the end of the line."""
    out: list[str] = []
    for line in tex.splitlines(keepends=True):
        backslashes = 0
        for index, char in enumerate(line):
            if char == "%" and backslashes % 2 == 0:
                out.append(line[:index] + ("\n" if line.endswith("\n") else ""))
                break
            backslashes = backslashes + 1 if char == "\\" else 0
        else:
            out.append(line)
    return "".join(out)


def _input_candidates(folder: Path, target: str) -> list[Path]:
    """Where TeX would look for `\\input{target}`: `target.tex` first, then `target` as written (so `part.v1` means `part.v1.tex`
    when that exists); the existing one, else both, for the outside check."""
    with_tex, as_is = folder / f"{target}.tex", folder / target
    if target.endswith(".tex"):
        return [as_is]
    for candidate in (with_tex, as_is):
        if candidate.exists() or candidate.is_symlink():
            return [candidate]
    return [with_tex, as_is]


def _sources(folder: Path, proof: Path, preamble: Path, findings: list[dict]) -> dict[str, str]:
    """proof.tex and every file it \\input's inside the node folder, each by its path from the folder, comments stripped:
    what the statement, the dependencies and the inputs are read from. An \\input that reaches outside the folder and the
    shared preamble — by its path, or through a link, with or without the `.tex` TeX adds — is a finding, wherever it
    stands; the preamble itself is not read."""
    folder_r, preamble_r = folder.resolve(), preamble.resolve()
    sources: dict[str, str] = {}
    queue = [proof]
    while queue and len(sources) < MAX_INPUT_FILES:
        path = queue.pop(0)
        resolved = path.resolve()
        rel = resolved.relative_to(folder_r).as_posix() if resolved.is_relative_to(folder_r) else path.name
        if rel in sources:
            continue
        try:
            text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:  # a file the check cannot read is not a file that passed
            findings.append(_finding("CHECK_INPUT_UNREADABLE", ERROR, f"{rel} could not be read ({exc.strerror or type(exc).__name__}): the checks cannot see what it inputs or states", rel))
            continue
        sources[rel] = text
        for match in _INPUT.finditer(text):
            target = (match.group(1) if match.group(1) is not None else match.group(2) or "").strip()
            if not target:
                continue
            for named in _input_candidates(folder, target):
                candidate = named.resolve()   # a link is followed, as TeX follows it
                if candidate == preamble_r:
                    continue
                if not candidate.is_relative_to(folder_r):
                    findings.append(_finding("CHECK_INPUT_OUTSIDE", ERROR, f"\\input{{{target}}} in {rel} reaches outside the node folder; only its own files and ../preamble may be input", rel))
                    break
                if candidate.is_file():
                    queue.append(candidate)
    return sources


def check_node(store: ProjectStore, node_id: str) -> list[dict]:
    """The findings on the node's working folder, errors first: `{"code", "level": "error"|"note", "message", "path"?}`.
    An imported result has no working proof and no findings. Read-only."""
    from .proof_map import get_node, list_nodes, require_node

    node = require_node(store, node_id)
    if node.kind == ProofMapNodeKind.imported_result:
        return []
    root = store.root
    folder = node_folder(root, node.id)
    findings: list[dict] = []
    texts: list[str] = []
    if is_computation(node):
        script = run_script_path(root, node.id)
        if not script.is_file():
            findings.append(_finding("CHECK_RUN_SCRIPT_MISSING", ERROR, f"{script.name} is not in the node folder: the program is the candidate proof", script.name))
        else:
            texts.append(script.read_text(encoding="utf-8", errors="replace"))
    else:
        proof = working_entry_path(root, node.id, node.medium)
        if not proof.is_file():
            findings.append(_finding("CHECK_PROOF_MISSING", ERROR, f"{proof.name} is not in the node folder", proof.name))
        else:
            sources = _sources(folder, proof, preamble_path(root), findings)
            texts.extend(sources.values())
            stated = [_normal(body) for _, body in _ENV.findall(sources.get(proof.name, ""))]
            if not stated:
                findings.append(_finding("CHECK_STATEMENT_MISMATCH", ERROR,
                                         "proof.tex has no theorem, lemma or claim environment stating the node's statement (a comment does not count)", proof.name))
            elif not any(_normal(node.statement) in body for body in stated):
                findings.append(_finding("CHECK_STATEMENT_MISMATCH", ERROR,
                                         "the node's statement is not what proof.tex's theorem environment states; it must state exactly what the map has", proof.name))
            pdf = build_pdf_path(root, node.id)
            log = pdf.with_suffix(".log")
            if not pdf.is_file():
                findings.append(_finding("CHECK_NOT_BUILT", ERROR, "proof.tex has not been compiled: compile it, and fix what fails, before the proof is read", "build/proof.pdf"))
            elif not build_is_current(root, node.id):
                findings.append(_finding("CHECK_BUILD_STALE", ERROR, "an input changed after the last build: compile again so the PDF and the log are of the proof as it stands", "build/proof.pdf"))
            if log.is_file():
                log_text = log.read_text(encoding="utf-8", errors="replace")
                bangs = [line.strip() for line in log_text.splitlines() if line.startswith("!")]
                if bangs:
                    findings.append(_finding("CHECK_COMPILE_ERRORS", ERROR, f"the build log has {len(bangs)} error line(s); the first: {bangs[0][:160]}", "build/proof.log"))
                if _UNDEFINED.search(log_text):
                    findings.append(_finding("CHECK_UNDEFINED_REFERENCES", ERROR, "the build log reports undefined references or citations", "build/proof.log"))
    ideas = folder / KEY_IDEAS_FILE
    if not ideas.is_file():
        findings.append(_finding("CHECK_KEY_IDEAS_MISSING", ERROR, f"{KEY_IDEAS_FILE} is not in the node folder; the review starts from it, and request-review is refused without it", KEY_IDEAS_FILE))
    else:
        text = ideas.read_text(encoding="utf-8", errors="replace")
        texts.append(text)
        parsed = parse(text)
        absent = [heading for key, heading in FIELDS if key not in parsed.fields]
        if absent:
            findings.append(_finding("CHECK_KEY_IDEAS_HEADINGS", ERROR, f"{KEY_IDEAS_FILE} lacks the heading(s) {', '.join(absent)}; it has exactly four: 核心思路, 主要步骤, 难点, 未覆盖", KEY_IDEAS_FILE))
        elif parsed.missing:
            findings.append(_finding("CHECK_KEY_IDEAS_EMPTY", ERROR, f"{KEY_IDEAS_FILE} leaves {', '.join(parsed.missing)} empty", KEY_IDEAS_FILE))
        known = {other.id for other in list_nodes(store)}
        named = {next(group for group in match.groups() if group) for match in _NAMED.finditer(parsed.fields.get("main_steps", ""))}
        unknown = sorted(name for name in named if _ID_LIKE.fullmatch(name) and name not in known)
        if unknown:
            findings.append(_finding("CHECK_KEY_IDEAS_UNKNOWN_NODE", NOTE, f"主要步骤 names {', '.join(unknown)} as a node, and no such node is on the map", KEY_IDEAS_FILE))
    for dep_id in node.dependencies:
        if get_node(store, dep_id) is not None and not _mentions(dep_id, *texts):
            findings.append(_finding("CHECK_DEPENDENCY_UNMENTIONED", NOTE, f"dependency {dep_id} is named neither in the proof nor in {KEY_IDEAS_FILE}: say where it is used, or drop the edge"))
    findings.sort(key=lambda f: (f["level"] != ERROR, f["code"]))
    return findings


def errors_of(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("level") == ERROR]


def summary(findings: list[dict]) -> str:
    """One line for a work log or a briefing: the codes and messages, errors first."""
    if not findings:
        return "mechanical checks passed: the proof builds cleanly, the summary has its four headings, the statement is the node's"
    return "; ".join(f"{f['code']}: {f['message']}" for f in findings)


__all__ = ["ERROR", "NOTE", "check_node", "errors_of", "summary"]
