"""Definitions (ADR-0020): the named text a node's statement is written in, named at creation and fixed, as the statement
is. They answer statements no one could read: a model's setting and its symbols crammed into one sentence or left
out, and Claims that said only "in the setting of" another node."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import definitions as D
from proof_cli.cli import app
from proof_cli.exchange import export_exchange_bundle, import_exchange_bundle
from proof_cli.proof_map import (
    ProofMapError,
    _interface_of,
    compute_interface_fingerprint,
    create_node,
    create_node_under_parent,
    get_node,
    split_node,
)
from proof_cli.storage import ensure_project
from proof_cli.vault import working_proof_path

runner = CliRunner()
UNIT = "A **simple graph** $G=(V,E)$ has $n\\in\\mathbb N_{>0}$ vertices; $E\\subseteq\\binom V2$ is its edge set."


def _code(call) -> str:
    with pytest.raises(ProofMapError) as caught:
        call()
    return caught.value.code


def test_a_node_names_its_definitions_and_its_document_opens_with_them(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "unit", term="Simple graph", text=UNIT)
    D.add_definition(store, "mean", term="Edge density", text="$d(G)=|E|/\\binom n2$.")
    node = create_node(store, node_id="T", kind="theorem", statement="$d$ satisfies the bound.", definitions=["unit", "mean", "unit"])
    assert get_node(store, "T").definitions == ["unit", "mean"]  # each once, in the order named
    tex = working_proof_path(tmp_path, "T").read_text()
    assert tex.index("\\section*{Definitions}") < tex.index("\\paragraph{Simple graph.}") < tex.index("\\paragraph{Edge density.}") < tex.index("\\begin{theorem}")
    assert [d.id for d in D.definitions_of(store, node)] == ["unit", "mean"]
    assert _code(lambda: create_node(store, node_id="X", kind="lemma", statement="s", definitions=["nowhere"])) == "DEFINITION_NOT_FOUND"
    assert get_node(store, "X") is None and not (tmp_path / "proofs" / "X").exists()  # refused: no node, no folder


def test_a_term_reads_as_written_in_its_latex_heading_and_keeps_its_maths(tmp_path: Path):
    """A term is a name, and the scaffold put it into `\\paragraph{<term>.}` as it was. A bare `_` there ("Index set I_k")
    stops the untouched document's build ("Missing $ inserted", then amsart's "Improper \\spacefactor"), and a Typesetter,
    who must leave that block alone, would have to rewrite it. Outside the term's own `$…$` maths, every character LaTeX
    reads as markup is escaped, so the heading shows the term exactly as the map does."""
    store = ensure_project(tmp_path)
    D.add_definition(store, "idx", term="Index set I_k", text="$I_k$ is an index set.")
    D.add_definition(store, "marks", term="Label L_{k,j} & 50% #1 ~^\\", text="$L$ is a label.")
    D.add_definition(store, "fam", term="Family $\\mathscr A_k$ of I_k", text="$\\mathscr A_k$ is a family.")
    D.add_definition(store, "shown", term="Display $$\\mathscr B$$", text="$\\mathscr B$ is a set.")
    create_node(store, node_id="T", kind="theorem", statement="$\\mathscr A_k$ covers $I_k$.", definitions=["idx", "marks", "fam", "shown"])
    tex = working_proof_path(tmp_path, "T").read_text()
    assert "\\paragraph{Index set I\\_k.} $I_k$ is an index set." in tex
    assert "\\paragraph{Label L\\_\\{k,j\\} \\& 50\\% \\#1 \\textasciitilde{}\\textasciicircum{}\\textbackslash{}.}" in tex
    assert "\\paragraph{Family $\\mathscr A_k$ of I\\_k.}" in tex  # its maths as written, the rest escaped
    assert "\\paragraph{Display $\\mathscr B$.}" in tex  # a heading holds no display: its maths go inline


def test_a_definition_is_editable_until_a_decision_relies_on_it_and_removable_until_a_node_names_it(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "unit", term="Simple graph", text=UNIT)
    assert D.edit_definition(store, "unit", text="A graph has $n$ vertices.").text == "A graph has $n$ vertices."
    assert _code(lambda: D.add_definition(store, "unit", term="t", text="x")) == "DEFINITION_ALREADY_EXISTS"
    assert _code(lambda: D.add_definition(store, "bad id", term="t", text="x")) == "INVALID_DEFINITION_ID"
    assert _code(lambda: D.add_definition(store, "empty", term=" ", text="x")) == "DEFINITION_EMPTY"
    create_node(store, node_id="L", kind="lemma", statement="s", definitions=["unit"])
    # named, but no decision relies on it yet (ADR-0021): an edit restates L, with a reason
    assert _code(lambda: D.edit_definition(store, "unit", text="something else")) == "RESTATE_REASON_REQUIRED"
    assert D.edit_definition(store, "unit", text="A graph has $n\\ge 1$ vertices.", reason="n is positive").text == "A graph has $n\\ge 1$ vertices."
    D.edit_definition(store, "unit", text="A graph has $n$ vertices.", reason="back")
    with pytest.raises(ProofMapError) as caught:
        D.remove_definition(store, "unit")
    assert caught.value.code == "DEFINITION_IN_USE" and caught.value.details == {"nodes": ["L"]}
    assert D.edit_definition(store, "unit", text="A graph has $n$ vertices.").text == "A graph has $n$ vertices."  # the same text: no change, no refusal
    D.add_definition(store, "spare", term="Spare", text="unused")
    D.remove_definition(store, "spare")
    assert _code(lambda: D.require_definition(store, "spare")) == "DEFINITION_NOT_FOUND"


def test_a_claim_is_written_in_its_parents_definitions(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "unit", term="Simple graph", text=UNIT)
    D.add_definition(store, "pair", term="Adjacent pair", text="Two vertices joined by an edge $e$.")
    create_node(store, node_id="T", kind="theorem", statement="s", definitions=["unit"])
    first, second = split_node(store, "T", [{"id": "C1", "statement": "a"}, {"id": "C2", "statement": "b", "definitions": ["pair"]}])
    assert first.definitions == ["unit"] and second.definitions == ["unit", "pair"]
    assert "\\paragraph{Simple graph.}" in working_proof_path(tmp_path, "C1").read_text()
    hung = create_node_under_parent(store, "T", node_id="C3", kind="claim", statement="c")
    assert hung.definitions == ["unit"]


def test_the_definitions_are_part_of_the_interface_and_a_node_naming_none_keeps_its_fingerprint(tmp_path: Path):
    store = ensure_project(tmp_path)
    D.add_definition(store, "unit", term="Simple graph", text=UNIT)
    plain = create_node(store, node_id="P", kind="lemma", statement="A implies B", assumptions=["A"])
    written = create_node(store, node_id="W", kind="lemma", statement="A implies B", assumptions=["A"], definitions=["unit"])
    assert _interface_of(plain) == compute_interface_fingerprint("A implies B", ["A"])  # as before ADR-0020
    assert _interface_of(written) != _interface_of(plain) and _interface_of(written) == compute_interface_fingerprint("A implies B", ["A"], ["unit"])


def test_the_cli_adds_lists_shows_and_names_definitions(tmp_path: Path):
    ensure_project(tmp_path)

    def run(*args: str, ok: bool = True) -> dict:
        result = runner.invoke(app, [*args, "--root", str(tmp_path), "--json"])
        envelope = json.loads(result.output)
        assert (result.exit_code == 0) == ok and envelope["ok"] == ok, result.output
        return envelope

    added = run("definition", "add", "unit", UNIT, "--term", "Simple graph")
    assert added["command"] == "definition.add" and added["data"]["used_by"] == []
    run("node", "create", "T", "theorem", "$G$ has no loops.", "--definition", "unit")
    shown = run("node", "show", "T")["data"]
    assert shown["definitions"] == ["unit"] and shown["definition_details"] == [{"id": "unit", "term": "Simple graph", "text": UNIT}]
    assert run("definition", "list")["data"][0]["used_by"] == ["T"]
    assert run("definition", "show", "unit")["data"]["used_by"] == ["T"]
    assert run("definition", "edit", "unit", "--text", "x", ok=False)["error"]["code"] == "RESTATE_REASON_REQUIRED"
    assert run("definition", "remove", "unit", ok=False)["error"]["code"] == "DEFINITION_IN_USE"
    run("definition", "add", "pair", "Two vertices.", "--term", "Adjacent pair")
    child = run("node", "split", "T", "--child", "C=one", "--definition", "pair")["data"][0]
    assert child["definitions"] == ["unit", "pair"]
    text = runner.invoke(app, ["node", "show", "T", "--root", str(tmp_path)]).output
    assert text.index("Definition unit") < text.index("Statement") and "Simple graph." in text


def test_a_definition_looked_up_under_an_id_there_is_none_of_names_the_ids_there_are(tmp_path: Path):
    """Looking a definition up (show, edit, remove) under an id there is none of names the ids there are and where to
    read them, so a guessed id is not answered with `proof definition add`; a statement naming a missing definition is
    still told to add it first."""
    ensure_project(tmp_path)

    def refused(*args: str) -> str:
        result = runner.invoke(app, [*args, "--root", str(tmp_path), "--json"])
        envelope = json.loads(result.output)
        assert result.exit_code == 1 and envelope["error"]["code"] == "DEFINITION_NOT_FOUND", result.output
        return envelope["error"]["message"]

    assert "has no definitions" in refused("definition", "show", "unit") and "definition add" not in refused("definition", "show", "unit")
    runner.invoke(app, ["definition", "add", "unit", UNIT, "--term", "Simple graph", "--root", str(tmp_path)])
    runner.invoke(app, ["definition", "add", "edge", "Two vertices joined.", "--term", "Edge", "--root", str(tmp_path)])
    for lookup in (("definition", "show", "units"), ("definition", "edit", "units", "--text", "x"), ("definition", "remove", "units")):
        message = refused(*lookup)
        assert "unit, edge" in message and "proof definition list --json" in message and "definition add" not in message, message
    assert "proof definition add" in refused("node", "create", "T", "theorem", "s", "--definition", "units")


def test_an_export_carries_the_definitions_and_an_import_refuses_one_that_says_otherwise(tmp_path: Path):
    source = ensure_project(tmp_path / "source")
    D.add_definition(source, "unit", term="Simple graph", text=UNIT)
    create_node(source, node_id="L", kind="lemma", statement="s", definitions=["unit"])
    bundle = export_exchange_bundle(source)
    assert [d.id for d in bundle.definitions] == ["unit"]

    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, json.loads(bundle.model_dump_json()))
    assert D.require_definition(target, "unit").text == UNIT and get_node(target, "L").definitions == ["unit"]

    other = ensure_project(tmp_path / "other")
    D.add_definition(other, "unit", term="Simple graph", text="something else")
    with pytest.raises(ProofMapError) as caught:
        import_exchange_bundle(other, json.loads(bundle.model_dump_json()))
    assert "DEFINITION_CONFLICT" in [problem["code"] for problem in caught.value.details["problems"]]
    assert get_node(other, "L") is None
