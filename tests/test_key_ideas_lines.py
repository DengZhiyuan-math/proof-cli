"""A Windows-written summary has the same required fields as an LF summary."""

from proof_cli.key_ideas import parse


def test_crlf_summary_headings_are_recognized():
    text = "## 核心思路\nA finite cover.\n\n## 主要步骤\n1. Use compactness.\n"
    lf = parse(text)
    crlf = parse(text.replace("\n", "\r\n"))
    assert not crlf.missing
    assert crlf.fields == lf.fields
