"""The studio page is the studio's alone (ADR-0018): a host puts its parts in the page's host:* slots. Nothing of a
proof map — a node panel, a run pane, a review card, a "+" menu, a Work log tab bar — is in this package's page,
script or stylesheet; the page works with every slot empty."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "latex_agent" / "static"
HOST_IDS = ("node-section", "node-panel", "run-pane", "review-card", "plus-menu", "chat-plus", "tab-log", "tab-files", "centre-tabs")


def test_the_page_has_one_of_each_host_slot_and_none_of_the_hosts_markup():
    page = (STATIC / "index.html").read_text()
    for slot in ("brand", "sidebar", "centre-top", "centre-pane", "chat-foot", "chat-actions", "head"):
        assert page.count(f"<!-- host:{slot} -->") == 1, slot
    for host_id in HOST_IDS:
        assert f'id="{host_id}"' not in page, host_id
    assert "proof map" not in page.lower().replace("a host serving this page for a proof map node", "")
    assert 'id="editor-pane"' in page and 'id="pdf-pane"' in page and "<section id=\"editor-pane\" hidden>" not in page  # shown on their own


def test_the_stylesheet_styles_none_of_the_hosts_parts():
    css = (STATIC / "app.css").read_text()
    for selector in ("#node-panel", "#node-section", "#review-card", "#run-pane", "#centre-tabs", ".work-log", ".run-card", ".menu-item", ".chat-actions .plus"):
        assert selector not in css, selector
    assert "#centre {" in css and "#centre-body" in css  # the centre column itself is the page's layout


def test_the_script_needs_no_host_elements_for_the_centre():
    app = (STATIC / "app.js").read_text()
    centre = app[app.index("const hostTabs = "):app.index("async function loadConfig")]
    for host_id in ("#run-pane", "#tab-log", "#tab-files", "#centre-tabs"):
        for use in re.findall(re.escape(host_id) + r"\"\)[^;\n]*", centre):
            assert use.startswith(host_id + '")') and ("if (" in centre.split(use)[0].rsplit("\n", 1)[-1] or "const " in centre.split(use)[0].rsplit("\n", 1)[-1] or "?" in use or "||" in use), (host_id, use)
