"""The Uses of dependencies section of a node's proof.tex, and its mechanical check (ADR-0025 point 23, #256, #281).

After the proof, proof.tex itself has one `\\section*{Uses of dependencies}`, and in it one `depuse` environment per
dependency, imported results included: its argument the dependency's id. Each use of the dependency is an application,
with exactly one non-empty Substitution, Premises, Conclusion and Constants; several applications each start with
`\\application`. The check settles the structure and the coverage only: whether the premises are all there and their
grounds right is the Verifier's.
"""

import pytest

from proof_cli.node_check import check_node
from proof_cli.proof_map import create_node
from proof_cli.storage import ensure_project
from proof_cli.vault import working_proof_path

SECTION = "\\section*{Uses of dependencies}\n"
FIELDS = ("\\item[Substitution] $g := f$.\n"
          "\\item[Premises] $g$ continuous on $[0,1]$ $\\leftarrow$ step~\\ref{step:cont}.\n"
          "\\item[Conclusion] $f$ is bounded on $[0,1]$.\n"
          "\\item[Constants] None.\n")


def _entry(dependency: str, *applications: str) -> str:
    """One depuse entry: its fields directly with one application, else each application after `\\application`."""
    body = applications[0] if len(applications) == 1 else "".join(f"\\application\n{fields}" for fields in applications)
    return f"\\begin{{depuse}}{{{dependency}}}\n{body}\\end{{depuse}}\n"


@pytest.fixture
def store(tmp_path):
    """N, a Claim, rests on L (a Lemma) and on R (an imported result); C is on the map, and N does not rest on it."""
    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="L", kind="lemma", statement="every continuous $g$ on $[0,1]$ is bounded")
    create_node(store, node_id="R", kind="imported_result", statement="a known bound", source_locator="Theorem 2", source_version="v1")
    create_node(store, node_id="C", kind="claim", statement="something else")
    create_node(store, node_id="N", kind="claim", statement="$f$ is bounded on $[0,1]$", dependencies=["L", "R"])
    return store


def _write(store, node_id: str, uses: str, *, before_proof: str = "") -> None:
    """The node's scaffolded proof.tex with a proof, `uses` after it (any Uses section the scaffold wrote replaced), and
    `before_proof` just ahead of the proof."""
    path = working_proof_path(store.root, node_id)
    tex = path.read_text()
    head, _, _ = tex.partition("\\begin{proof}")
    proof = "\\begin{proof}\n\\begin{enumerate}\n\\item\\label{step:cont} $f$ is continuous.\n\\end{enumerate}\n\\end{proof}\n\n"
    path.write_text(head + before_proof + proof + uses + "\\end{document}\n")


def _uses(findings: list[dict]) -> list[tuple[str, str]]:
    return [(f["code"], f["message"]) for f in findings if f["code"].startswith("CHECK_USES")]


def test_a_section_with_one_entry_per_dependency_passes(store):
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS))
    assert _uses(check_node(store, "N")) == []


def test_a_dependency_with_no_entry_is_an_error_naming_it(store):
    _write(store, "N", SECTION + _entry("L", FIELDS))
    (finding,) = [f for f in check_node(store, "N") if f["code"] == "CHECK_USES_MISSING"]
    assert finding["level"] == "error" and "R" in finding["message"]


def test_a_node_with_dependencies_needs_exactly_one_section_after_the_proof(store):
    _write(store, "N", "")
    assert [code for code, _ in _uses(check_node(store, "N"))] == ["CHECK_USES_SECTION"]
    _write(store, "N", SECTION + _entry("L", FIELDS) + SECTION + _entry("R", FIELDS))
    assert "CHECK_USES_SECTION" in [code for code, _ in _uses(check_node(store, "N"))]
    _write(store, "N", "", before_proof=SECTION + _entry("L", FIELDS) + _entry("R", FIELDS))   # before the proof
    assert "CHECK_USES_SECTION" in [code for code, _ in _uses(check_node(store, "N"))]


def test_the_section_comes_after_the_last_proof(store):
    """Not between two proofs: the section is the proof's account of its uses, after all of it."""
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS) + "\\begin{proof}\nThe second half.\n\\end{proof}\n")
    assert [code for code, _ in _uses(check_node(store, "N"))] == ["CHECK_USES_SECTION"]


def test_every_entry_is_in_the_section(store):
    stray = _entry("L", FIELDS)
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS), before_proof=stray)
    assert "CHECK_USES_SECTION" in [code for code, _ in _uses(check_node(store, "N"))]


def test_an_entry_in_a_file_proof_tex_inputs_is_an_error_and_one_in_a_file_it_does_not_is_nothing(store):
    """What the document holds is proof.tex and what it inputs; a stray file in the folder is not in it, for the check
    and for the verdict alike."""
    from proof_cli.vault import node_folder

    folder = node_folder(store.root, "N")
    (folder / "old.tex").write_text(_entry("L", FIELDS))
    _ready(store)
    assert _uses(check_node(store, "N")) == []
    _verdict(store, "passed", ALL_CHECKED)
    (folder / "part.tex").write_text(_entry("L", FIELDS))
    _write(store, "N", "\\input{part}\n" + SECTION + _entry("L", FIELDS) + _entry("R", FIELDS, FIELDS))
    assert [code for code, _ in _uses(check_node(store, "N"))] == ["CHECK_USES_SECTION"]


def test_an_entry_for_what_is_not_a_dependency_is_an_error(store):
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS) + _entry("C", FIELDS) + _entry("ghost", FIELDS))
    (finding,) = [f for f in check_node(store, "N") if f["code"] == "CHECK_USES_NOT_A_DEPENDENCY"]
    assert "C" in finding["message"] and "ghost" in finding["message"]


def test_two_entries_for_one_dependency_are_an_error(store):
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("L", FIELDS) + _entry("R", FIELDS))
    assert [code for code, _ in _uses(check_node(store, "N"))] == ["CHECK_USES_DUPLICATE"]


@pytest.mark.parametrize("fields, said", [
    (FIELDS.replace("\\item[Constants] None.\n", ""), "L/1 lacks Constants"),
    (FIELDS + "\\item[Premises] again.\n", "L/1 has Premises twice"),
    (FIELDS.replace("$f$ is bounded on $[0,1]$.", " "), "L/1 leaves Conclusion empty"),
])
def test_each_application_has_its_four_fields_exactly_once_and_not_empty(store, fields, said):
    _write(store, "N", SECTION + _entry("L", fields) + _entry("R", FIELDS))
    (finding,) = [f for f in check_node(store, "N") if f["code"] == "CHECK_USES_FIELDS"]
    assert said in finding["message"]


def test_several_applications_are_numbered_and_each_checked(store):
    _write(store, "N", SECTION + _entry("L", FIELDS, FIELDS.replace("\\item[Constants] None.\n", "")) + _entry("R", FIELDS))
    (finding,) = [f for f in check_node(store, "N") if f["code"] == "CHECK_USES_FIELDS"]
    assert "L/2 lacks Constants" in finding["message"] and "L/1" not in finding["message"]


def test_fields_before_the_first_application_and_an_empty_application_are_errors(store):
    mixed = f"\\begin{{depuse}}{{L}}\n\\item[Substitution] $g := f$.\n\\application\n{FIELDS}\\application\n{FIELDS}\\end{{depuse}}\n"
    _write(store, "N", SECTION + mixed + _entry("R", FIELDS))
    assert "before its first \\application" in " ".join(message for _, message in _uses(check_node(store, "N")))
    empty = f"\\begin{{depuse}}{{L}}\n\\application\n{FIELDS}\\application\n\\end{{depuse}}\n"
    _write(store, "N", SECTION + empty + _entry("R", FIELDS))
    assert "L/2 is empty" in " ".join(message for _, message in _uses(check_node(store, "N")))


def test_an_entry_in_a_comment_does_not_count(store):
    _write(store, "N", SECTION + _entry("L", FIELDS) + "".join(f"% {line}\n" for line in _entry("R", FIELDS).splitlines()))
    assert [code for code, _ in _uses(check_node(store, "N"))] == ["CHECK_USES_MISSING"]


def test_a_node_with_no_dependencies_needs_no_section(store):
    _write(store, "L", "")
    assert _uses(check_node(store, "L")) == []


def test_mentioning_a_dependency_is_no_longer_a_check_of_its_own(store):
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS))
    assert "CHECK_DEPENDENCY_UNMENTIONED" not in [f["code"] for f in check_node(store, "N")]


# -- the scaffold: what a new node's proof.tex, and a new project's preamble, start with (#256, #266) ----------------


def test_a_new_nodes_proof_tex_has_its_assumptions_and_the_uses_heading_after_the_proof(tmp_path):
    from proof_cli.vault import working_proof_path

    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="L", kind="lemma", statement="every continuous $g$ on $[0,1]$ is bounded")
    create_node(store, node_id="N", kind="claim", statement="$f$ is bounded on $[0,1]$", assumptions=["$f$ is continuous on $[0,1]$"],
                dependencies=["L"])
    tex = working_proof_path(store.root, "N").read_text()
    assert tex.index("\\section*{Assumptions}") < tex.index("$f$ is continuous on $[0,1]$") < tex.index("\\begin{claim}")
    assert tex.index("\\end{proof}") < tex.index("\\section*{Uses of dependencies}") < tex.index("\\end{document}")
    codes = [f["code"] for f in check_node(store, "N")]
    assert "CHECK_USES_MISSING" in codes and "CHECK_USES_SECTION" not in codes   # the heading is there; L's entry is the Prover's
    assert "CHECK_ASSUMPTIONS_MISMATCH" not in codes


def test_a_new_projects_preamble_defines_the_depuse_environment_and_application(tmp_path):
    from proof_cli.vault import preamble_path

    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="L", kind="lemma", statement="L holds")
    preamble = preamble_path(store.root).read_text()
    assert "\\newenvironment{depuse}" in preamble and "\\newcommand{\\application}" in preamble


# -- the node's own assumptions, checked as its statement is (#266), and other nodes named in it (#261) -------------


def test_the_nodes_assumptions_are_checked_as_its_statement_is(tmp_path):
    from proof_cli.vault import working_proof_path

    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="N", kind="claim", statement="$f$ is bounded", assumptions=["$f$ is continuous on $[0,1]$", "$f(0) = 0$"])
    path = working_proof_path(store.root, "N")
    assert "CHECK_ASSUMPTIONS_MISMATCH" not in [f["code"] for f in check_node(store, "N")]
    path.write_text(path.read_text().replace("$f(0) = 0$", "$f(0) = 1$"))
    (finding,) = [f for f in check_node(store, "N") if f["code"] == "CHECK_ASSUMPTIONS_MISMATCH"]
    assert finding["level"] == "error" and "f(0) = 0" in finding["message"]


def test_another_node_named_in_the_statement_or_an_assumption_is_a_note_and_the_node_is_still_created(tmp_path):
    """#261: a statement says all it needs itself; naming another node instead is flagged for the Verifier, never refused."""
    store = ensure_project(tmp_path / "project")
    create_node(store, node_id="lem-bound", kind="lemma", statement="every continuous $g$ on $[0,1]$ is bounded")
    create_node(store, node_id="clm-setup", kind="claim", statement="the setup holds")
    create_node(store, node_id="N", kind="claim", statement="under the hypotheses of lem-bound, $f$ is bounded",
                assumptions=["as in clm-setup"])
    (finding,) = [f for f in check_node(store, "N") if f["code"] == "CHECK_NAMES_OTHER_NODE"]
    assert finding["level"] == "note" and "lem-bound" in finding["message"] and "clm-setup" in finding["message"]


# -- a Verifier's verdict reports on each application, read off the same proof.tex (#256, #281) ---------------------

def _ready(store):
    """N's section complete: L used once, R twice."""
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS, FIELDS))


ALL_CHECKED = ["L/1: checked", "R/1: checked", "R/2: checked"]


def _verdict(store, outcome, lines, **more):
    from proof_cli.proof_map import record_progress

    return record_progress(store, "N", role="verifier", by="agent/verifier", verdict=outcome, application_lines=lines, **more)


def test_a_passing_verdict_says_each_application_was_checked(store):
    from proof_cli.node_states import node_states

    _ready(store)
    entry = _verdict(store, "passed", ALL_CHECKED)
    assert entry["applications"] == [{"id": "L/1", "objection": None}, {"id": "R/1", "objection": None}, {"id": "R/2", "objection": None}]
    assert node_states(store, "N").proof_layer == "checks-passed"


def test_a_proof_missing_a_dependencys_entry_cannot_record_a_passing_verdict_and_adding_it_can(store):
    """The ticket's first acceptance criterion: without a covering section, the Proof layer cannot reach checks passed."""
    from proof_cli.node_states import node_states
    from proof_cli.proof_map import ProofMapError

    _write(store, "N", SECTION + _entry("L", FIELDS))
    with pytest.raises(ProofMapError) as refused:
        _verdict(store, "passed", ["L/1: checked"])
    assert refused.value.code == "USES_INCOMPLETE" and "R" in refused.value.message
    assert node_states(store, "N").proof_layer == "incomplete"
    _write(store, "N", SECTION + _entry("L", FIELDS) + _entry("R", FIELDS))
    _verdict(store, "passed", ["L/1: checked", "R/1: checked"])
    assert node_states(store, "N").proof_layer == "checks-passed"


@pytest.mark.parametrize("edit", ["gains C", "loses R"])
def test_a_passing_check_stops_counting_when_the_node_gains_or_loses_a_dependency(store, edit):
    """The proof was checked with a use of each dependency the node had: one it has gained has no use there, and one
    it has lost is still used, resting on what the map no longer says it rests on. Nor does the verdict let an agent
    request review any more."""
    from proof_cli.node_states import node_states
    from _proofs import write_key_ideas
    from proof_cli.proof_map import ProofMapError, add_dependency, remove_dependency, request_review

    _ready(store)
    write_key_ideas(store, "N")
    passed = _verdict(store, "passed", ALL_CHECKED)
    assert node_states(store, "N").proof_layer == "checks-passed"
    if edit == "gains C":
        add_dependency(store, "N", "C")
    else:
        remove_dependency(store, "N", "R")
    assert node_states(store, "N").proof_layer == "incomplete"
    with pytest.raises(ProofMapError) as refused:
        request_review(store, "N", requested_by="agent", rationale="scoped", gated_by=passed["inputs_sha256"])
    assert refused.value.code == "VERDICT_STALE" and "other dependencies" in refused.value.message


@pytest.mark.parametrize("lines, named", [
    (["L/1: checked", "R/1: checked"], "R/2"),                                    # one left out
    (["L/1: checked", "R/1: checked", "R/2: checked", "R/2: checked"], "R/2"),    # one twice
    (["L/1: checked", "R/1: checked", "R/2: checked", "R/3: checked"], "R/3"),    # one the section does not have
])
@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_a_verdicts_lines_cover_each_application_exactly_once(store, lines, named, outcome):
    from proof_cli.proof_map import ProofMapError

    _ready(store)
    with pytest.raises(ProofMapError) as refused:
        _verdict(store, outcome, lines, **({"objections": ["step 2 omits a case"]} if outcome == "failed" else {}))
    assert refused.value.code == "APPLICATIONS_MISMATCH" and named in refused.value.message


def test_a_failed_verdict_names_an_applications_objection_by_its_number(store):
    from proof_cli.proof_map import ProofMapError

    _ready(store)
    entry = _verdict(store, "failed", ["L/1: checked", "R/1: objection 1", "R/2: checked"], objections=["R's premise is not met at $x = 0$"])
    assert entry["applications"][1] == {"id": "R/1", "objection": 1}
    with pytest.raises(ProofMapError) as refused:
        _verdict(store, "failed", ["L/1: objection 2", "R/1: checked", "R/2: checked"], objections=["one objection only"])
    assert refused.value.code == "APPLICATIONS_MISMATCH" and "objection 2" in refused.value.message


def test_a_passing_verdict_cannot_put_an_objection_on_an_application(store):
    from proof_cli.proof_map import ProofMapError

    _ready(store)
    with pytest.raises(ProofMapError) as refused:
        _verdict(store, "passed", ["L/1: checked", "R/1: objection 1", "R/2: checked"])
    assert refused.value.code == "PASSED_WITH_OBJECTIONS"


def test_a_line_that_is_not_an_application_and_its_reading_is_refused(store):
    from proof_cli.proof_map import ProofMapError

    _ready(store)
    with pytest.raises(ProofMapError) as refused:
        _verdict(store, "passed", ["L/1 fine", "R/1: checked", "R/2: checked"])
    assert refused.value.code == "INVALID_APPLICATION_LINE" and "L/1 fine" in refused.value.message


def test_a_node_with_no_dependencies_records_its_verdict_with_no_lines(store):
    from proof_cli.proof_map import record_progress

    _write(store, "L", "")
    assert record_progress(store, "L", role="verifier", by="agent/verifier", verdict="passed")["applications"] == []


def test_the_cli_takes_each_application_line(store):
    import json

    from typer.testing import CliRunner

    from proof_cli.cli import app

    _ready(store)
    lines = [arg for line in ALL_CHECKED for arg in ("--application-line", line)]
    result = CliRunner().invoke(app, ["node", "progress", "N", "--role", "verifier", "--by", "agent/verifier", "--verdict", "passed", *lines,
                                      "--json", "--root", str(store.root)])
    assert result.exit_code == 0, result.output
    assert [a["id"] for a in json.loads(result.output)["data"]["applications"]] == ["L/1", "R/1", "R/2"]


# -- what changed between two versions, computed from their snapshots, never declared (#264) ------------------------

DOCUMENT = ("\\documentclass{amsart}\n\\input{../preamble}\n\\begin{document}\n"
            "\\begin{claim}\n$f$ is bounded on $[0,1]$\n\\end{claim}\n\n"
            "\\begin{proof}\nBy compactness.\nSee \\cite[Theorem 2]{rudin}.\n\\end{proof}\n\n"
            + SECTION + _entry("L", FIELDS) + _entry("R", FIELDS)
            + "\\bibliographystyle{plain}\n\\end{document}\n")


def _version(store, tex: str, ideas: str | None = None) -> int:
    from _proofs import submit_proof
    from proof_cli.vault import node_folder

    if ideas is not None:
        (node_folder(store.root, "N") / "key-ideas.md").write_text(ideas)
    return submit_proof(store, "N", claimant_id="agent", scoping_rationale="scoped", content=tex).version


@pytest.mark.parametrize("change, parts", [
    (lambda tex: tex.replace("$f$ is bounded on $[0,1]$", "$f$ is bounded on $[0,2]$", 1), ["statement"]),   # the claim, not a Conclusion
    (lambda tex: tex.replace("By compactness.", "By compactness and a covering argument."), ["proof"]),
    (lambda tex: tex.replace("\\item[Constants] None.", "\\item[Constants] $C$ depends on $f$ only.", 1), ["proof"]),
    (lambda tex: tex.replace("\\bibliographystyle{plain}", "\\bibliographystyle{alpha}"), ["citations or metadata"]),
    (lambda tex: tex.replace("{rudin}", "{folland}"), ["citations or metadata"]),                    # which work is cited
    (lambda tex: tex.replace("$[0,1]$\n\\end{claim}", "$[0,2]$\n\\end{claim}").replace("By compactness.", "By Heine-Borel."), ["statement", "proof"]),
])
def test_the_diff_between_two_versions_names_the_parts_that_changed(store, change, parts):
    from proof_cli.version_diff import version_diff

    first = _version(store, DOCUMENT)
    second = _version(store, change(DOCUMENT))
    assert version_diff(store, "N", first, second)["parts"] == parts


def test_a_change_to_the_summary_alone_is_named_so(store):
    from proof_cli.vault import node_folder
    from proof_cli.version_diff import version_diff

    first = _version(store, DOCUMENT)
    ideas = (node_folder(store.root, "N") / "key-ideas.md").read_text()
    second = _version(store, DOCUMENT, ideas=ideas.replace("## 难点", "## 难点\nthe covering step\n", 1))
    diff = version_diff(store, "N", first, second)
    assert diff["parts"] == ["key-ideas"] and diff["files"]["changed"] == ["key-ideas.md"]


def test_the_cli_shows_the_diff(store):
    import json

    from typer.testing import CliRunner

    from proof_cli.cli import app

    first = _version(store, DOCUMENT)
    second = _version(store, DOCUMENT.replace("By compactness.", "By Heine-Borel."))
    result = CliRunner().invoke(app, ["node", "diff", "N", str(first), str(second), "--json", "--root", str(store.root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["parts"] == ["proof"]
    plain = CliRunner().invoke(app, ["node", "diff", "N", str(first), str(second), "--root", str(store.root)])
    assert plain.exit_code == 0 and "proof" in plain.output and f"v{first}" in plain.output
