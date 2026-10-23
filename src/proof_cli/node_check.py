"""Mechanical checks of a node's working proof (issue #180): what a program can settle before any agent reads it.

A Proof agent's run spent turns on `ls`, `cat`, `grep error build/*.log` and reading `--help`: discovering the folder and
checking what needs no judgment. These checks are that work, done once, deterministically and read-only — does the
proof build and build cleanly, is the summary there with its four headings, does proof.tex's theorem environment state
what the node states and does the document give the definitions it names as the map has them, do its `\\input`s (and
theirs) stay in the folder, does its Uses of dependencies section have an entry for each dependency, each application
with its four fields (ADR-0025 point 23: the structure and the coverage only, whether each holds is the Verifier's). The run
gates the Verifier on them (an error sends the work back to the role that owns the files; the Verifier is briefed that
they passed and reads only the mathematics), and `proof node check` shows them to anyone. Nothing here is a
verification: whether a step holds is the Verifier's and the researcher's. A finding is a notice (`CHECK_*` in
errors.NOTICE_CODES), never a refusal, and never stops the researcher's own request-review.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .domain import ProofMapNodeKind, is_computation
from .key_ideas import FIELDS, KEY_IDEAS_FILE, parse
from .storage import ProjectStore, get_definition
from .vault import build_is_current, build_pdf_path, latex_text, log_errors, node_folder, preamble_path, run_script_path, working_entry_path

ERROR, NOTE = "error", "note"
# \input{file}, \input {file}, \input⏎{file}, and TeX's own \input file␣ (no braces); \include{file} too — not \includegraphics, \inputencoding
_INPUT = re.compile(r"\\(?:input|include)(?![A-Za-z@])\s*(?:\{([^}]*)\}|([^\s{}\\%]+))")
_ENVIRONMENTS = ("theorem", "lemma", "claim", "proposition", "corollary")
_ENV = re.compile(r"\\begin\{(" + "|".join(_ENVIRONMENTS) + r")\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}", re.S)
_UNDEFINED = re.compile(r"undefined (reference|citation)|There were undefined (references|citations)|Reference `[^']*' on page \d+ undefined|Citation `[^']*' on page \d+ undefined", re.I)
_ID_LIKE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
# how key-ideas.md's 主要步骤 names a node: `id` or \ref{id} (the Typesetter's guide: each step names the node it uses, by id).
# Not (id): (i), (ii), (a_n) are math, and can't be told from a name (#188).
_NAMED = re.compile(r"`([^`\s]+)`|\\(?:eq|c|auto)?ref\{([^}]+)\}")
MAX_INPUT_FILES = 50   # files read through \input, at most
# One display however it is written: the map's Markdown $$…$$, LaTeX's \[…\], and the unnumbered and numbered named
# environments the studio's rule asks for. The scaffold writes a statement's $$…$$ as equation* (vault.latex_text), and the
# form says nothing about what is stated. Not `\\[2pt]`, a line break; and a \label in a display says nothing either.
_DISPLAY = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<!\\)\\\[(.+?)(?<!\\)\\\]|\\begin\{(equation\*?|displaymath)\}(.*?)\\end\{\3\}", re.S)
_LABEL = re.compile(r"\\label\{[^}]*\}")
# the Uses of dependencies section (#256): its heading, the end of the proof it follows, what ends it, its entries, the
# start of each application of an entry used more than once, and the four fields of an application
_USES_HEADING = re.compile(r"\\section\*\{\s*Uses of dependencies\s*\}")
_PROOF_END = re.compile(r"\\end\{proof\}")
_SECTION_END = re.compile(r"\\(?:section|chapter)\*?\s*[\[{]|\\end\{document\}")
_DEPUSE = re.compile(r"\\begin\{depuse\}\s*\{([^}]*)\}(.*?)\\end\{depuse\}", re.S)
_APPLICATION = re.compile(r"\\application(?![A-Za-z@])")
USES_FIELDS = ("Substitution", "Premises", "Conclusion", "Constants")
_FIELD = re.compile(r"\\item\s*\[\s*(" + "|".join(USES_FIELDS) + r")\s*\]")


def _finding(code: str, level: str, message: str, path: str | None = None) -> dict:
    found = {"code": code, "level": level, "message": message}
    if path:
        found["path"] = path
    return found


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _comparable(text: str) -> str:
    """`text` as the statement and definition checks compare it: whitespace runs as one space, and each display as `\\[…\\]`."""
    def display(match: re.Match) -> str:
        inner = next(group for group in (match.group(1), match.group(2), match.group(4)) if group is not None)
        return " \\[" + _normal(_LABEL.sub("", inner)) + "\\] "

    return _normal(_DISPLAY.sub(display, text))


def _is_named(node_id: str, *texts: str) -> bool:
    """Whether one of `texts` names the node `node_id`, as an id stands on its own (not part of a longer one)."""
    pattern = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(node_id) + r"(?![A-Za-z0-9_.-])")
    return any(pattern.search(text) for text in texts if text)


def strip_comments(tex: str) -> str:
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


@dataclass
class Application:
    """One use of a dependency in its `depuse` entry: its id (`<dependency>/<n>`), its fields' texts by name (a field
    given twice has two), and its whole text."""
    id: str
    fields: dict[str, list[str]]
    text: str


@dataclass
class UsesEntry:
    """One `depuse` entry: the dependency it names, whether it stands in proof.tex's one Uses of dependencies section,
    its applications and whatever stands before its first `\\application` when it has several."""
    dependency: str
    in_section: bool
    applications: list[Application] = field(default_factory=list)
    prelude: str = ""


def parse_uses(tex: str) -> tuple[list[int], list[UsesEntry]]:
    """proof.tex's Uses of dependencies, read off its text (comments stripped): where each section heading stands, and
    every `depuse` entry, wherever it stands. An entry is in the section when there is exactly one and the entry stands
    between its heading and the next section or the end of the document."""
    headings = [match.start() for match in _USES_HEADING.finditer(tex)]
    span = (0, 0)
    if len(headings) == 1:
        end = _SECTION_END.search(tex, headings[0] + 1)
        span = (headings[0], end.start() if end else len(tex))
    entries = []
    for match in _DEPUSE.finditer(tex):
        entry = UsesEntry(dependency=match.group(1).strip(), in_section=span[0] <= match.start() < span[1])
        parts = _APPLICATION.split(match.group(2))
        bodies = parts if len(parts) == 1 else parts[1:]
        entry.prelude = "" if len(parts) == 1 else parts[0]
        for number, body in enumerate(bodies, start=1):
            marks = list(_FIELD.finditer(body))
            fields: dict[str, list[str]] = {}
            for at, mark in enumerate(marks):
                stop = marks[at + 1].start() if at + 1 < len(marks) else len(body)
                fields.setdefault(mark.group(1), []).append(body[mark.end():stop].strip())
            entry.applications.append(Application(id=f"{entry.dependency}/{number}", fields=fields, text=body.strip()))
        entries.append(entry)
    return headings, entries


def application_ids(tex: str) -> list[str]:
    """The ids of the applications proof.tex's Uses of dependencies section gives, in order: what a Verifier's verdict
    reports on, one line each (#256)."""
    return [application.id for entry in parse_uses(tex)[1] if entry.in_section for application in entry.applications]


def uses_findings(tex: str, dependencies: list[str], inputs: Sequence[str] = (), path: str = "proof.tex") -> list[dict]:
    """The Uses of dependencies section's structure and coverage (#256): with dependencies, exactly one section, after the
    proof, holding every entry; one entry per dependency and none for anything else; each application's four fields
    exactly once, none empty. `inputs` are the texts of the files proof.tex inputs, where no entry belongs."""
    headings, entries = parse_uses(tex)
    elsewhere = any(_DEPUSE.search(text) for text in inputs)
    if not dependencies and not entries and not elsewhere:
        return []
    findings = []
    proof_ends = [match.start() for match in _PROOF_END.finditer(tex)]
    if len(headings) != 1:
        findings.append(_finding("CHECK_USES_SECTION", ERROR, (f"proof.tex has {len(headings)} Uses of dependencies sections; it has exactly one" if headings else
                                                                "proof.tex has no Uses of dependencies section: after the proof, \\section*{Uses of dependencies} with one depuse entry per dependency"), path))
    elif not proof_ends or proof_ends[-1] > headings[0]:
        findings.append(_finding("CHECK_USES_SECTION", ERROR, "the Uses of dependencies section comes after the proof", path))
    stray = [entry.dependency for entry in entries if not entry.in_section]
    if len(headings) == 1 and (stray or elsewhere):
        findings.append(_finding("CHECK_USES_SECTION", ERROR, "every depuse entry stands in proof.tex's Uses of dependencies section"
                                 + (f"; {', '.join(stray)} does not" if stray else "; a file it inputs has one"), path))
    named = [entry.dependency for entry in entries]
    missing = [dependency for dependency in dependencies if dependency not in named]
    if missing and (headings or entries):   # with no section and no entry at all, the section's finding says it
        findings.append(_finding("CHECK_USES_MISSING", ERROR, f"no depuse entry for the dependenc{'ies' if len(missing) > 1 else 'y'} {', '.join(missing)}: "
                                 "each dependency, an imported result too, has one, saying how the proof uses it", path))
    twice = sorted({dependency for dependency in named if dependency in dependencies and named.count(dependency) > 1})
    if twice:
        findings.append(_finding("CHECK_USES_DUPLICATE", ERROR, f"more than one depuse entry for {', '.join(twice)}: one entry per dependency, "
                                 "each use of it an \\application in it", path))
    strangers = sorted({dependency for dependency in named if dependency not in dependencies})
    if strangers:
        findings.append(_finding("CHECK_USES_NOT_A_DEPENDENCY", ERROR, f"depuse entries name {', '.join(strangers)}, which the node does not rest on", path))
    problems = []
    for entry in entries:
        if entry.prelude.strip():
            problems.append(f"{entry.dependency} has fields or text before its first \\application")
        for application in entry.applications:
            if not application.fields and not application.text:
                problems.append(f"{application.id} is empty")
                continue
            for field_name in USES_FIELDS:
                given = application.fields.get(field_name, [])
                if not given:
                    problems.append(f"{application.id} lacks {field_name}")
                elif len(given) > 1:
                    problems.append(f"{application.id} has {field_name} {'twice' if len(given) == 2 else f'{len(given)} times'}")
                elif not given[0]:
                    problems.append(f"{application.id} leaves {field_name} empty")
    if problems:
        findings.append(_finding("CHECK_USES_FIELDS", ERROR, "; ".join(problems) + " (each application: Substitution, Premises, Conclusion and Constants, "
                                 "once each, none empty)", path))
    return findings


def uses_of(files: dict[str, bytes], dependencies: list[str], entry: str = "proof.tex") -> tuple[list[dict], list[str]]:
    """The Uses of dependencies as a verdict re-checks them (#256), off the very bytes its digest is of (the folder's
    files, by path; proof.tex is `entry`): the section's findings and its applications' ids. Only proof.tex is read,
    where the section and every entry stand; an entry in a file it inputs is the node check's to report, which follows
    the \\inputs (`check_node`), so the verdict never refuses what the check passed."""
    tex = strip_comments(files.get(entry, b"").decode("utf-8", errors="replace"))
    return uses_findings(tex, dependencies, path=entry), application_ids(tex)


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
            text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
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
    from .proof_map import list_nodes, require_node

    node = require_node(store, node_id)
    if node.kind == ProofMapNodeKind.imported_result:
        return []
    root = store.root
    folder = node_folder(root, node.id)
    findings: list[dict] = []
    if is_computation(node):
        script = run_script_path(root, node.id)
        if not script.is_file():
            findings.append(_finding("CHECK_RUN_SCRIPT_MISSING", ERROR, f"{script.name} is not in the node folder: the program is the candidate proof", script.name))
    else:
        proof = working_entry_path(root, node.id, node.medium)
        if not proof.is_file():
            findings.append(_finding("CHECK_PROOF_MISSING", ERROR, f"{proof.name} is not in the node folder", proof.name))
        else:
            sources = _sources(folder, proof, preamble_path(root), findings)
            stated = [_comparable(body) for _, body in _ENV.findall(sources.get(proof.name, ""))]
            if not stated:
                findings.append(_finding("CHECK_STATEMENT_MISMATCH", ERROR,
                                         "proof.tex has no theorem, lemma or claim environment stating the node's statement (a comment does not count)", proof.name))
            elif not any(_comparable(latex_text(node.statement)) in body for body in stated):
                findings.append(_finding("CHECK_STATEMENT_MISMATCH", ERROR,
                                         "the node's statement is not what proof.tex's theorem environment states; it must state exactly what the map has", proof.name))
            # the Definitions the statement is written in (ADR-0020), as the scaffold wrote them: the map's text, like the
            # statement, wherever proof.tex or a file it inputs gives it; the heading (the term's rendering) is not compared.
            # A restated definition (ADR-0021 point 6) leaves the document behind, and this is where that shows
            given = [_comparable(text) for text in sources.values()]
            named = [definition for definition in (get_definition(store, definition_id) for definition_id in node.definitions) if definition is not None]
            absent = [definition.id for definition in named if not any(_comparable(latex_text(definition.text)) in text for text in given)]
            if absent:
                many = len(absent) > 1
                findings.append(_finding("CHECK_DEFINITIONS_MISMATCH", ERROR,
                                         f"proof.tex does not give the definition{'s' if many else ''} {', '.join(absent)} as the map has {'them' if many else 'it'}: "
                                         "its Definitions section carries each definition the node names, word for word (`proof definition show <id>`)", proof.name))
            # the node's own assumptions (#266), as the definitions are: the map's text, word for word, wherever given
            unstated = [text for text in node.assumptions if not any(_comparable(latex_text(text)) in given_text for given_text in given)]
            if unstated:
                findings.append(_finding("CHECK_ASSUMPTIONS_MISMATCH", ERROR,
                                         f"proof.tex does not state the assumption{'s' if len(unstated) > 1 else ''} {'; '.join(unstated)} as the map has "
                                         f"{'them' if len(unstated) > 1 else 'it'}: its Assumptions section carries each of the node's assumptions, word for word", proof.name))
            # how the proof uses each dependency (ADR-0025 point 23): proof.tex's own Uses of dependencies section
            findings.extend(uses_findings(sources.get(proof.name, ""), list(node.dependencies),
                                          inputs=[text for rel, text in sources.items() if rel != proof.name], path=proof.name))
            pdf = build_pdf_path(root, node.id)
            log = pdf.with_suffix(".log")
            if not pdf.is_file():
                findings.append(_finding("CHECK_NOT_BUILT", ERROR, "proof.tex has not been compiled: compile it, and fix what fails, before the proof is read", "build/proof.pdf"))
            elif not build_is_current(root, node.id):
                findings.append(_finding("CHECK_BUILD_STALE", ERROR, "an input changed after the last build: compile again so the PDF and the log are of the proof as it stands", "build/proof.pdf"))
            if log.is_file():
                log_text = log.read_text(encoding="utf-8", errors="replace")
                bangs = log_errors(log_text)
                if bangs:
                    findings.append(_finding("CHECK_COMPILE_ERRORS", ERROR, f"the build log has {len(bangs)} error line(s); the first: {bangs[0][:160]}", "build/proof.log"))
                if _UNDEFINED.search(log_text):
                    findings.append(_finding("CHECK_UNDEFINED_REFERENCES", ERROR, "the build log reports undefined references or citations", "build/proof.log"))
    # a statement says all it needs itself (#261): another node named in it, or in an assumption, is a hint for the
    # Verifier, which fails a statement that needs a reading; it blocks nothing
    hinted = sorted(other.id for other in list_nodes(store) if other.id != node.id
                    and _is_named(other.id, node.statement, *node.assumptions))
    if hinted:
        findings.append(_finding("CHECK_NAMES_OTHER_NODE", NOTE, f"the statement or an assumption names {', '.join(hinted)}: a node states every "
                                 "condition it needs itself, in its statement, its assumptions or the definitions it names"))
    ideas = folder / KEY_IDEAS_FILE
    if not ideas.is_file():
        findings.append(_finding("CHECK_KEY_IDEAS_MISSING", ERROR, f"{KEY_IDEAS_FILE} is not in the node folder; the review starts from it, and request-review is refused without it", KEY_IDEAS_FILE))
    else:
        text = ideas.read_text(encoding="utf-8", errors="replace")
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
    findings.sort(key=lambda f: (f["level"] != ERROR, f["code"]))
    return findings


def errors_of(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("level") == ERROR]


def summary(findings: list[dict]) -> str:
    """One line for a work log or a briefing: the codes and messages, errors first."""
    if not findings:
        return "mechanical checks passed: the proof builds cleanly, the summary has its four headings, the statement and definitions are the node's"
    return "; ".join(f"{f['code']}: {f['message']}" for f in findings)


__all__ = ["ERROR", "NOTE", "USES_FIELDS", "Application", "UsesEntry", "application_ids", "check_node", "errors_of", "parse_uses", "strip_comments",
           "summary", "uses_findings", "uses_of"]
