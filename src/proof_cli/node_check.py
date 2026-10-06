"""Mechanical checks of a node's working proof (issue #180): what a program can settle before any agent reads it.

A Proof agent's run spent turns on `ls`, `cat`, `grep error build/*.log` and reading `--help`: discovering the folder and
checking what needs no judgment. These checks are that work, done once, deterministically and read-only — does the
proof build and build cleanly, is the summary there with its four headings, does proof.tex state what the node states,
do its `\\input`s stay in the folder, is each dependency at least mentioned. The run gates the Verifier on them (an
error sends the work back to the role that owns the files; the Verifier is briefed that they passed and reads only the
mathematics), and `proof node check` shows them to anyone. Nothing here is a verification: whether a step holds is the
Verifier's and the researcher's. A finding is a notice, never a refusal, and never stops the researcher's own
request-review.
"""

from __future__ import annotations

import re

from .domain import ProofMapNodeKind, is_computation
from .key_ideas import FIELDS, KEY_IDEAS_FILE, parse
from .storage import ProjectStore
from .vault import build_is_current, build_pdf_path, node_folder, preamble_path, run_script_path, working_entry_path

ERROR, NOTE = "error", "note"
# the codes, as `errors.NOTICE_CODES` registers them: what each finding says
CHECK_CODES: dict[str, str] = {
    "CHECK_PROOF_MISSING": "the node's working proof.tex is not there (node check)",
    "CHECK_RUN_SCRIPT_MISSING": "a computation node's run.sh is not there (node check)",
    "CHECK_NOT_BUILT": "proof.tex has not been compiled: build/proof.pdf is missing (node check)",
    "CHECK_BUILD_STALE": "an input changed after the last build: compile again (node check)",
    "CHECK_COMPILE_ERRORS": "the last build's log has errors (`!` lines); the first is in the message (node check)",
    "CHECK_UNDEFINED_REFERENCES": "the last build's log reports undefined references or citations (node check)",
    "CHECK_STATEMENT_MISMATCH": "the node's statement, as the map has it, does not appear in proof.tex (node check)",
    "CHECK_INPUT_OUTSIDE": "proof.tex \\input's a file outside the node folder and the shared preamble (node check)",
    "CHECK_KEY_IDEAS_MISSING": "key-ideas.md is not there; request-review needs it (node check)",
    "CHECK_KEY_IDEAS_HEADINGS": "key-ideas.md lacks one of its four headings (node check)",
    "CHECK_KEY_IDEAS_EMPTY": "key-ideas.md has an empty required section (核心思路 or 主要步骤) (node check)",
    "CHECK_DEPENDENCY_UNMENTIONED": "a dependency of the node is named neither in proof.tex nor in key-ideas.md (node check)",
}
_INPUT = re.compile(r"\\input\{([^}]*)\}")
_UNDEFINED = re.compile(r"undefined (reference|citation)|There were undefined (references|citations)|Reference `[^']*' on page \d+ undefined|Citation `[^']*' on page \d+ undefined", re.I)


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


def check_node(store: ProjectStore, node_id: str) -> list[dict]:
    """The findings on the node's working folder, errors first: `{"code", "level": "error"|"note", "message", "path"?}`.
    An imported result has no working proof and no findings. Read-only."""
    from .proof_map import get_node, require_node

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
            tex = ""
        else:
            tex = proof.read_text(encoding="utf-8", errors="replace")
            texts.append(tex)
            if _normal(node.statement) not in _normal(tex):
                findings.append(_finding("CHECK_STATEMENT_MISMATCH", ERROR,
                                         "the node's statement is not in proof.tex as the map has it; the theorem environment must state exactly what the node states", proof.name))
            preamble = preamble_path(root).resolve()
            for match in _INPUT.finditer(tex):
                target = match.group(1).strip()
                candidate = (folder / target).resolve()
                if candidate.suffix == "":
                    candidate = candidate.with_suffix(".tex")
                inside = candidate == preamble or candidate.is_relative_to(folder.resolve())
                if not inside:
                    findings.append(_finding("CHECK_INPUT_OUTSIDE", ERROR, f"\\input{{{target}}} reaches outside the node folder; only its own files and ../preamble may be input", proof.name))
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
    for dep_id in node.dependencies:
        dep = get_node(store, dep_id)
        if dep is not None and not _mentions(dep_id, *texts):
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


__all__ = ["CHECK_CODES", "ERROR", "NOTE", "check_node", "errors_of", "summary"]
