"""The renderers print a statement as it is: square brackets are mathematics, not Rich markup (issue #132's trial fixtures)."""

from proof_cli.domain import ProofMapNode, ProofMapNodeKind
from proof_cli.rendering import render_frontier, render_proof_map_node, render_proof_map_node_list

STATEMENT = "A continuous function $f\\colon [a,b] \\to \\mathbb{R}$ is bounded on [0,1]; see [bold] and :sum:."


def _node():
    return ProofMapNode(id="T2", kind=ProofMapNodeKind.lemma, statement=STATEMENT)


def test_a_statements_square_brackets_survive_every_table():
    for text in (render_frontier([_node()]), render_proof_map_node_list([_node()])):
        flat = " ".join(text.split())
        assert "[a,b]" in flat and "[0,1]" in flat and "[bold]" in flat and ":sum:" in flat, text


def test_the_node_card_keeps_them_too():
    text = render_proof_map_node(_node())
    flat = " ".join(text.split())
    assert "$f\\colon [a,b] \\to \\mathbb{R}$" in flat and "[bold]" in flat, text
