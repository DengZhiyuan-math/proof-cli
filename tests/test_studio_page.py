"""The studio page's own code (src/proof_cli/studio/static), driven through tests/js/studio_page_harness.js:
the agent's edits in the Files view (app.js) and the PDF's links (pdfview.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "js" / "studio_page_harness.js"


def _run(**scenario):
    if shutil.which("node") is None:
        pytest.skip("needs node")
    done = subprocess.run(["node", str(HARNESS), json.dumps(scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_agents_edit_is_offered_in_the_tab_bar_not_switched_to():
    """Seventh review: an edit the agent makes (AV.end, in an Ask turn or a run's turn through studioLive) leaves the
    researcher on the tab they are reading. The changed file's tab is added behind it and marked; opening it goes
    to the change, and a new Start clears the mark."""
    files = {"main.tex": "\\section{Intro}\nmine\n", "sec/a.tex": "one\ntwo\nthree\n"}
    edit = dict(case="agent-edit", files=files, active="main.tex", edited="sec/a.tex", old="two", new="TWO", after="one\nTWO\nthree\n")
    after_edit, opened = _run(**edit)
    assert after_edit["active"] == "main.tex" and after_edit["shown"] == files["main.tex"]  # still on the researcher's file
    assert after_edit["views"] == []  # and the centre was not switched either
    assert after_edit["tabs"] == ["main.tex", "sec/a.tex"]  # offered behind it
    assert 'agent-changed' in after_edit["tabbar"] and 'data-path="sec/a.tex"' in after_edit["tabbar"]
    tab = after_edit["tabbar"].split('data-path="sec/a.tex"')[0].rsplit("<div", 1)[1]
    assert "agent-changed" in tab and "active" not in tab.replace("agent-changed", "")
    assert opened["active"] == "sec/a.tex" and opened["shown"] == "one\nTWO\nthree\n" and opened["cursor"]["line"] == 1  # at the change
    assert "agent-changed" not in opened["tabbar"]  # seen: the mark goes
    _, restarted = _run(**edit, then="reset")
    assert restarted["active"] == "main.tex" and "sec/a.tex" in restarted["tabs"] and "agent-changed" not in restarted["tabbar"]


def test_an_edit_to_the_file_on_screen_stays_where_it_is():
    files = {"main.tex": "one\ntwo\n"}
    after_edit, _ = _run(case="agent-edit", files=files, active="main.tex", edited="main.tex", old="two", new="TWO", after="one\nTWO\n")
    assert after_edit["active"] == "main.tex" and after_edit["tabs"] == ["main.tex"] and "agent-changed" not in after_edit["tabbar"]


def test_a_pdfs_links_are_web_links_and_places_in_the_document_only():
    """Seventh review: pdfview.js draws a link for an http(s) URL or a destination in the document; anything else
    (javascript:, file:, data:, PDF.js's unvalidated `unsafeUrl`) is not a link."""
    rect = [0, 0, 10, 10]
    annots = [
        {"subtype": "Link", "rect": rect, "url": "https://arxiv.org/abs/1234.5678"},
        {"subtype": "Link", "rect": rect, "url": "http://example.org/a"},
        {"subtype": "Link", "rect": rect, "dest": "section.2"},
        {"subtype": "Link", "rect": rect, "unsafeUrl": "javascript:alert(1)"},
        {"subtype": "Link", "rect": rect, "unsafeUrl": "https://only.unsafe.example/"},
        {"subtype": "Link", "rect": rect, "url": "file:///etc/passwd"},
        {"subtype": "Link", "rect": rect, "url": "data:text/html,hi"},
        {"subtype": "Link", "rect": rect, "url": "mailto:someone@example.org"},
        {"subtype": "Widget", "rect": rect, "url": "https://not-a-link.example/"},
    ]
    links = _run(case="pdf-links", annots=annots)
    assert links == [
        {"href": "https://arxiv.org/abs/1234.5678", "dest": None, "target": "_blank"},
        {"href": "http://example.org/a", "dest": None, "target": "_blank"},
        {"href": "#", "dest": '"section.2"', "target": None},
    ]
