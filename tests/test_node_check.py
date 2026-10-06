"""The mechanical checks of a node's working proof (issue #180): what a program settles before any agent reads."""

import json
import os
import time

import pytest
from typer.testing import CliRunner

from proof_cli.cli import app
from proof_cli.node_check import check_node, errors_of, summary
from proof_cli.proof_map import create_node
from proof_cli.storage import ensure_project
from proof_cli.vault import node_folder

IDEAS = "## 核心思路\nby compactness\n## 主要步骤\n1. use L\n## 难点\n无\n## 未覆盖\n无\n"


@pytest.fixture
def project(tmp_path):
    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="L", kind="lemma", statement="the partial sums are bounded")
    create_node(store, node_id="N", kind="claim", statement="for every $n$ the bound holds", dependencies=["L"])
    return store


def _build(store, node_id, log="This is pdfTeX\nOutput written on proof.pdf (1 page).\n"):
    folder = node_folder(store.root, node_id)
    (folder / "build").mkdir(exist_ok=True)
    (folder / "build" / "proof.log").write_text(log)
    (folder / "build" / "proof.pdf").write_bytes(b"%PDF-1.4 stub")
    later = time.time() + 5  # newer than every input
    os.utime(folder / "build" / "proof.pdf", (later, later))


def _codes(findings):
    return [f["code"] for f in findings]


def test_a_fresh_node_is_not_built_and_has_no_summary_and_a_finished_one_passes(project):
    findings = check_node(project, "N")
    assert _codes(findings) == ["CHECK_KEY_IDEAS_MISSING", "CHECK_NOT_BUILT", "CHECK_DEPENDENCY_UNMENTIONED"]  # errors first, then the note
    assert [f["level"] for f in findings] == ["error", "error", "note"] and len(errors_of(findings)) == 2
    folder = node_folder(project.root, "N")
    (folder / "key-ideas.md").write_text(IDEAS)
    _build(project, "N")
    assert check_node(project, "N") == [] and summary([]).startswith("mechanical checks passed")


def test_each_break_is_named(project):
    folder = node_folder(project.root, "N")
    (folder / "key-ideas.md").write_text(IDEAS)
    _build(project, "N")
    tex = (folder / "proof.tex").read_text()
    # the statement is no longer the node's
    (folder / "proof.tex").write_text(tex.replace("for every $n$ the bound holds", "for some $n$ the bound holds"))
    _build(project, "N")
    assert "CHECK_STATEMENT_MISMATCH" in _codes(check_node(project, "N"))
    # whitespace and line breaks do not count as a mismatch
    (folder / "proof.tex").write_text(tex.replace("for every $n$ the bound holds", "for every $n$\n  the bound   holds"))
    _build(project, "N")
    assert "CHECK_STATEMENT_MISMATCH" not in _codes(check_node(project, "N"))
    # an \input outside the folder; ../preamble and a file of its own are fine
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "\\input{../../secrets}\\input{lemmas}\\begin{document}"))
    _build(project, "N")
    found = check_node(project, "N")
    assert _codes(found).count("CHECK_INPUT_OUTSIDE") == 1 and "../../secrets" in next(f["message"] for f in found if f["code"] == "CHECK_INPUT_OUTSIDE")
    (folder / "proof.tex").write_text(tex)
    # the build is older than the proof
    _build(project, "N")
    (folder / "proof.tex").write_text(tex + "% edited after the build\n")
    later = time.time() + 10  # the edit is newer than the build's PDF
    os.utime(folder / "proof.tex", (later, later))
    assert "CHECK_BUILD_STALE" in _codes(check_node(project, "N"))
    # the log has errors and undefined references
    _build(project, "N", log="! Undefined control sequence.\nl.4 \\foo\nLaTeX Warning: Reference `eq:1' on page 1 undefined on input line 9.\n")
    codes = _codes(check_node(project, "N"))
    assert "CHECK_COMPILE_ERRORS" in codes and "CHECK_UNDEFINED_REFERENCES" in codes
    assert "Undefined control sequence" in next(f["message"] for f in check_node(project, "N") if f["code"] == "CHECK_COMPILE_ERRORS")
    _build(project, "N")
    # the summary lacks a heading, or leaves a required one empty
    (folder / "key-ideas.md").write_text("## 核心思路\nx\n## 主要步骤\n1. L\n## 难点\n无\n")
    assert "CHECK_KEY_IDEAS_HEADINGS" in _codes(check_node(project, "N")) and "未覆盖" in summary(check_node(project, "N"))
    (folder / "key-ideas.md").write_text("## 核心思路\n\n## 主要步骤\n1. L\n## 难点\n无\n## 未覆盖\n无\n")
    assert "CHECK_KEY_IDEAS_EMPTY" in _codes(check_node(project, "N"))
    # the dependency is mentioned in the proof or the summary, as a word
    (folder / "key-ideas.md").write_text(IDEAS.replace("use L", "use the lemma"))
    assert "CHECK_DEPENDENCY_UNMENTIONED" in _codes(check_node(project, "N"))
    (folder / "proof.tex").write_text(tex.replace("% Write the proof here.", "By \\ref{L}, done."))
    _build(project, "N")
    assert "CHECK_DEPENDENCY_UNMENTIONED" not in _codes(check_node(project, "N"))
    (folder / "proof.tex").write_text(tex.replace("% Write the proof here.", "By LL, done."))  # another id's prefix is not a mention
    _build(project, "N")
    assert "CHECK_DEPENDENCY_UNMENTIONED" in _codes(check_node(project, "N"))


def test_a_computation_node_needs_its_program_and_an_imported_result_has_no_findings(project):
    create_node(project, node_id="C", kind="claim", statement="for n ≤ 10^4 …", medium="computation")
    folder = node_folder(project.root, "C")
    (folder / "key-ideas.md").write_text(IDEAS)
    assert check_node(project, "C") == []  # a program, no build to check
    (folder / "run.sh").unlink()
    assert _codes(check_node(project, "C")) == ["CHECK_RUN_SCRIPT_MISSING"]
    create_node(project, node_id="R", kind="imported_result", statement="a cited theorem", source_locator="doi:x", source_version="1")
    assert check_node(project, "R") == []


def test_the_cli_lists_the_findings_and_exits_one_on_an_error(project):
    runner = CliRunner()
    result = runner.invoke(app, ["node", "check", "N", "--root", str(project.root)])
    assert result.exit_code == 1 and "CHECK_KEY_IDEAS_MISSING" in result.output and "CHECK_NOT_BUILT" in result.output
    result = runner.invoke(app, ["node", "check", "N", "--root", str(project.root), "--json"])
    envelope = json.loads(result.output)
    assert result.exit_code == 1 and envelope["ok"] and envelope["command"] == "node.check"
    assert envelope["data"]["ok"] is False and [f["code"] for f in envelope["data"]["findings"]][:2] == ["CHECK_KEY_IDEAS_MISSING", "CHECK_NOT_BUILT"]
    folder = node_folder(project.root, "N")
    (folder / "key-ideas.md").write_text(IDEAS)
    _build(project, "N")
    result = runner.invoke(app, ["node", "check", "N", "--root", str(project.root)])
    assert result.exit_code == 0 and "All checks passed" in result.output
    result = runner.invoke(app, ["node", "check", "nope", "--root", str(project.root), "--json"])
    assert result.exit_code == 1 and json.loads(result.output)["ok"] is False


def test_the_audits_cases_comments_links_sub_files_the_environment_and_unknown_nodes(project):
    """Re-review of #180: a comment is not the proof; an \\input is followed into sub-files and through links, with TeX's suffix rule;
    the statement counts only inside a theorem environment; a step naming a node that is not on the map is noted."""
    folder = node_folder(project.root, "N")
    (folder / "key-ideas.md").write_text(IDEAS)
    tex = (folder / "proof.tex").read_text()
    # the statement only in a comment, the environment stating something else: a mismatch
    (folder / "proof.tex").write_text(tex.replace("for every $n$ the bound holds", "for some $n$ the bound holds") + "% for every $n$ the bound holds\n")
    _build(project, "N")
    assert "CHECK_STATEMENT_MISMATCH" in _codes(check_node(project, "N"))
    # an outside input in a comment is not an input; one in a sub-file is
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "% \\input{../../secrets}\n\\input{part}\\begin{document}"))
    (folder / "part.tex").write_text("\\input{../../elsewhere}\n")
    _build(project, "N")
    found = check_node(project, "N")
    outside = [f for f in found if f["code"] == "CHECK_INPUT_OUTSIDE"]
    assert len(outside) == 1 and "../../elsewhere" in outside[0]["message"] and outside[0]["path"] == "part.tex"
    # a link inside the folder to a file outside it, input without its suffix: found through the link
    (folder / "part.tex").write_text("")
    (project.root / "outside.tex").write_text("secret")
    (folder / "linked.tex").symlink_to(project.root / "outside.tex")
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "\\input{linked}\\begin{document}"))
    _build(project, "N")
    assert [f["message"] for f in check_node(project, "N") if f["code"] == "CHECK_INPUT_OUTSIDE"] and "linked" in check_node(project, "N")[0]["message"]
    (folder / "linked.tex").unlink()
    (folder / "proof.tex").write_text(tex)
    _build(project, "N")
    assert "CHECK_INPUT_OUTSIDE" not in _codes(check_node(project, "N"))  # ../preamble is fine
    # a step naming a node that does not exist, in any of the three spellings
    (folder / "key-ideas.md").write_text(IDEAS.replace("1. use L", "1. use `GHOST` and (L) and \\ref{PHANTOM}; the field is $\\mathbb{R}$"))
    notes = [f for f in check_node(project, "N") if f["code"] == "CHECK_KEY_IDEAS_UNKNOWN_NODE"]
    assert len(notes) == 1 and "GHOST, PHANTOM" in notes[0]["message"] and notes[0]["level"] == "note"
    (folder / "key-ideas.md").write_text(IDEAS)
    assert "CHECK_KEY_IDEAS_UNKNOWN_NODE" not in _codes(check_node(project, "N"))
    # the registry holds every code the checks raise, and nowhere else keeps a copy
    from proof_cli import errors, node_check

    assert not hasattr(node_check, "CHECK_CODES") and all(code in errors.NOTICE_CODES for code in {f["code"] for f in found})


def test_the_re_reviews_tex_cases_unreadable_sub_file_double_backslash_dotted_names_and_spacing(project):
    """Re-review of #180: a sub-file the check cannot read is a finding, not a pass; `\\\\%` is a line break then a comment; `part.v1`
    means `part.v1.tex` when it exists (TeX's rule); `\\input {x}`, `\\input⏎{x}` and TeX's `\\input x` are inputs."""
    from proof_cli.node_check import _strip_comments

    folder = node_folder(project.root, "N")
    (folder / "key-ideas.md").write_text(IDEAS)
    tex = (folder / "proof.tex").read_text()
    assert _strip_comments("a \\% b % c\n") == "a \\% b \n" and _strip_comments("x \\\\% \\input{../../out}\n") == "x \\\\\n"
    # an unreadable sub-file
    (folder / "part.tex").write_text("fine")
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "\\input{part}\\begin{document}"))
    _build(project, "N")
    assert "CHECK_INPUT_OUTSIDE" not in _codes(check_node(project, "N"))
    (folder / "part.tex").chmod(0)
    try:
        if os.access(folder / "part.tex", os.R_OK):
            pytest.skip("runs as a user that reads everything")
        found = check_node(project, "N")
        assert "CHECK_INPUT_UNREADABLE" in _codes(found) and next(f for f in found if f["code"] == "CHECK_INPUT_UNREADABLE")["path"] == "part.tex"
    finally:
        (folder / "part.tex").chmod(0o644)
    # a line break then a comment holding an outside input: the comment is a comment, the input is not one
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "a\\\\% \\input{../../out}\n\\begin{document}"))
    _build(project, "N")
    assert "CHECK_INPUT_OUTSIDE" not in _codes(check_node(project, "N"))
    # a dotted name: part.v1 is part.v1.tex, whose outside input is found
    (folder / "part.v1.tex").write_text("\\input{../../elsewhere}\n")
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "\\input{part.v1}\\begin{document}"))
    _build(project, "N")
    outside = [f for f in check_node(project, "N") if f["code"] == "CHECK_INPUT_OUTSIDE"]
    assert len(outside) == 1 and outside[0]["path"] == "part.v1.tex"
    # spacing and the brace-less form
    for form in ("\\input {../../out}", "\\input\n{../../out}", "\\input ../../out "):
        (folder / "proof.tex").write_text(tex.replace("\\begin{document}", form + "\\begin{document}"))
        _build(project, "N")
        assert "CHECK_INPUT_OUTSIDE" in _codes(check_node(project, "N")), form
    # a longer control word is not an input: \includegraphics{../x.png}, \inputencoding{latin1}
    (folder / "proof.tex").write_text(tex.replace("\\begin{document}", "\\includegraphics{../../fig.png}\\inputencoding{latin1}\\begin{document}"))
    _build(project, "N")
    assert "CHECK_INPUT_OUTSIDE" not in _codes(check_node(project, "N"))
    (folder / "proof.tex").write_text(tex)
    _build(project, "N")
    assert check_node(project, "N") == []
