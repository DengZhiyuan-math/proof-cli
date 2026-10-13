"""The same attribution P2 with checked and unchecked clauses on one line."""

import json
from pathlib import Path

import pytest

from probe_attribution import WEB, _checked, _imports, create_node, ensure_project, source_marks
from _review_client import DirectClient


@pytest.mark.parametrize("note", [
    "R: checked against the source; R2: unchecked against the source; source unavailable.",
    "R: checked against the source, whereas R2: unchecked against the source.",
])
def test_a_checked_import_is_not_marked_by_another_imports_unchecked_clause(tmp_path, note):
    store = ensure_project(tmp_path)
    _imports(store)
    create_node(store, node_id="L", kind="lemma", statement="L", dependencies=["R", "R2"], created_by="reader")
    _checked(store, note)
    actual_r, actual_r2 = source_marks(store, "R"), source_marks(store, "R2")
    client = DirectClient(store)
    try:
        node_review = client.get("/api/node/R")[1]["data"]["import_review"]
        card = next(p for p in client.get("/api/state")[1]["data"]["pending"] if p["node_id"] == "R")
        queue = next(i for i in client.get("/api/review-queue")[1]["data"]["items"] if i["kind"] == "imported" and i["node_id"] == "R")
        print(json.dumps({"note": note, "R_marks": len(actual_r), "R2_marks": len(actual_r2),
                          "R_node_marks": len(node_review["unchecked"]),
                          "R_card_marks": len(card["unchecked"]),
                          "R_queue_marks": len(queue["unchecked"])}, indent=2))
        assert actual_r == [], "R is explicitly checked; only the R2 clause carries an unchecked mark"
        assert len(actual_r2) == 1
    finally:
        client.app.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", "-s", "-c", str(WEB / "pyproject.toml"), str(Path(__file__).resolve())]))
