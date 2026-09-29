"""Put a node's proof up for review in one step (#18).

The retired ADR-0003 `node submit` took the proof text and submitted it at
once; since ADR-0010 an agent edits the node's working `proof.tex` and then
requests review, which snapshots it. Tests that only need a node awaiting
review do both here. Since ADR-0013 a review request also needs the node's
key-ideas summary: `submit_proof` writes one unless the node already has it.
"""

from pathlib import Path

from proof_cli.proof_map import request_review
from proof_cli.vault import node_folder, working_proof_path

KEY_IDEAS = """\
## 核心思路

The bound follows from compactness of $[0, 1]$.

## 主要步骤

1. Cover the interval (uses lem_cover).
2. Take a finite subcover.
3. Bound each piece.

## 难点

The subcover's size must not depend on $\\varepsilon$.

## 未覆盖

无
"""


def write_key_ideas(store_or_root, node_id: str, text: str = KEY_IDEAS) -> Path:
    """The node's working key-ideas.md (ADR-0013), as its author or the proof agent writes it."""
    root = store_or_root if isinstance(store_or_root, Path) else store_or_root.root
    path = node_folder(root, node_id) / "key-ideas.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ensure_key_ideas(store_or_root, node_id: str) -> None:
    """The node's working key-ideas.md, written unless it already has one: what a review request needs."""
    root = store_or_root if isinstance(store_or_root, Path) else store_or_root.root
    if not (node_folder(root, node_id) / "key-ideas.md").exists():
        write_key_ideas(root, node_id)


def submit_proof(store, node_id: str, *, claimant_id: str, scoping_rationale: str, content: str, session_id: str = ""):
    working = working_proof_path(store.root, node_id)
    if working.parent.is_dir():  # an imported_result has none, and request_review refuses it
        working.write_text(content, encoding="utf-8")
        ensure_key_ideas(store, node_id)
    return request_review(store, node_id, requested_by=claimant_id, rationale=scoping_rationale)
