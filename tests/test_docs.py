"""The written record matches ADR-0011 (#73): every earlier ADR it changes points at it, and the
glossary, README and agent skill describe the studio, the frozen snapshot and PROOF_ROOT."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ADR = REPO / "docs" / "adr"


def _status(name: str) -> str:
    text = next(ADR.glob(f"{name}-*.md")).read_text()
    return re.search(r"^\*\*Status\*\*:(.*?)(?:\n\n|\n#)", text, re.S | re.M).group(1)


def test_adr_0011_is_accepted():
    assert _status("0011").strip().startswith("accepted")


@pytest.mark.parametrize("name", ["0006", "0007", "0008", "0010"])
def test_every_adr_it_changes_points_at_adr_0011(name):
    assert "ADR-0011" in _status(name), name


@pytest.mark.parametrize("doc", ["CONTEXT.md", "README.md", ".agents/skills/proof-cli/SKILL.md"])
def test_the_docs_describe_the_studio_and_proof_root(doc):
    text = (REPO / doc).read_text()
    assert "studio" in text.lower() and "PROOF_ROOT" in text, doc
    assert "Open in prism-local" not in text and "proof codex" not in text, doc


@pytest.mark.parametrize("doc", ["CONTEXT.md", "README.md"])
def test_the_docs_describe_the_frozen_snapshot(doc):
    assert "snapshots/v<N>/" in (REPO / doc).read_text(), doc


def test_the_glossary_defines_the_studio_and_the_proof_agent():
    text = (REPO / "CONTEXT.md").read_text()
    assert "**Studio**:" in text and "**Proof agent**:" in text
    assert "Codex route or MCP tool" not in text


def test_adr_0012_retires_legacy_trust():
    """#90: only proof-map nodes answer what can be called; a reference is a citation."""
    assert _status("0012").strip().startswith("accepted")
    for name in ("0001", "0004", "0005"):
        assert "ADR-0012" in _status(name), name
    assert "freely re-reviewed" not in (REPO / "CONTEXT.md").read_text()
    assert "freely re-reviewed" not in next(ADR.glob("0005-*.md")).read_text()
    assert "approve_imported_result" not in next(ADR.glob("0002-*.md")).read_text()


@pytest.mark.parametrize("doc", ["README.md", "AGENTS.md"])
def test_the_docs_say_the_proof_map_answers_what_can_be_called(doc):
    text = (REPO / doc).read_text()
    assert "trusted references" not in text, doc
    assert "Reference review" in text and "ADR-0012" in text, doc
