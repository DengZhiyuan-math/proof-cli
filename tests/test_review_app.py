"""The proof map page (issues #36, #55, ADR-0010): what it shows, and how decisions are recorded from it.

The page's logic is driven through `ReviewApp` directly (`DirectClient`, no
socket). The HTTP layer itself — Host/Origin/content-type checks, error
responses, headers — is driven over a real socket, as a browser or an agent
`curl`ing it would.
"""

import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from _proofs import ensure_key_ideas
from _researcher import researcher
from _review_client import DirectClient, decide, serving
from proof_cli.proof_map import create_node, get_acceptance_state, request_review
from proof_cli.storage import ensure_project, get_active_claim


@pytest.fixture
def page(tmp_path: Path):
    store = ensure_project(tmp_path)
    yield store, DirectClient(store)


@pytest.fixture
def http_app(tmp_path: Path):
    store = ensure_project(tmp_path)
    with serving(store) as client:
        yield store, client


def _awaiting(store, node_id="clm_1"):
    create_node(store, node_id=node_id, kind="claim", statement=r"$(f * g) * h = f * (g * h)$")
    working = store.root / "proofs" / node_id / "proof.tex"
    working.write_text(working.read_text().replace("% Write the proof here.", "- x^2 \\le 0 fails; take $(f * g) * h$."))
    ensure_key_ideas(store, node_id)
    return request_review(store, node_id, requested_by="agent_a", rationale="scoped")


# -- what the page shows -----------------------------------------------------------------


def test_the_home_page_lists_what_awaits_review_with_its_exact_snapshot(page):
    store, client = page
    snapshot = _awaiting(store)

    state = client.get("/api/state")[1]["data"]

    (pending,) = state["pending"]
    assert pending["node_id"] == "clm_1"
    assert pending["candidate_proof"]["text"] == (store.root / snapshot.file_path).parent.joinpath("node", "proof.tex").read_text()  # the frozen proof.tex (#71)
    assert pending["candidate_proof"]["sha256"] == snapshot.sha256
    assert state["reviewer"]  # whose decisions these will be


def test_the_node_page_shows_the_exact_latex_never_a_rendering(page):
    store, client = page
    snapshot = _awaiting(store)

    view = client.get("/api/node/clm_1")[1]["data"]

    assert view["candidate_proof"]["text"] == (store.root / snapshot.file_path).parent.joinpath("node", "proof.tex").read_text()
    assert "(f * g) * h" in view["candidate_proof"]["text"] and "- x^2" in view["candidate_proof"]["text"]
    static = Path(__file__).parent.parent / "src" / "proof_cli" / "webapp" / "static" / "app.js"
    assert "renderMarkdown" not in static.read_text()


def test_integrity_warnings_show_next_to_their_node(page):
    store, client = page
    snapshot = _awaiting(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    path = store.root / snapshot.file_path
    path.write_text(path.read_text() + "\n% edited after acceptance\n")

    view = client.get("/api/node/clm_1")[1]["data"]
    assert view["acceptance_state"] == "unverifiable"
    assert "DECISION_NO_LONGER_APPLIES" in [warning["code"] for warning in view["warnings"]]


# -- recording decisions -----------------------------------------------------------------


def test_a_decision_recorded_from_the_page_counts(page):
    store, client = page
    snapshot = _awaiting(store)

    status, outcome = decide(
        client, [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept", "rationale": "checked", "viewed_candidate_proof_sha256": snapshot.sha256}]
    )

    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome
    assert get_acceptance_state(store, "clm_1") == "accepted"
    assert not client.get("/api/state")[1]["data"]["pending"]


def test_several_decisions_are_recorded_in_one_request(page):
    store, client = page
    _awaiting(store, "clm_1")
    _awaiting(store, "clm_2")

    _, outcome = decide(
        client,
        [
            {"kind": "acceptance", "target_id": "clm_1", "decision": "accept"},
            {"kind": "acceptance", "target_id": "clm_2", "decision": "revision-requested", "rationale": "step 3?"},
        ],
    )

    assert [result["ok"] for result in outcome["data"]["results"]] == [True, True]
    assert (get_acceptance_state(store, "clm_1"), get_acceptance_state(store, "clm_2")) == ("accepted", "unreviewed")


def test_a_snapshot_changed_since_it_was_viewed_is_refused(page):
    store, client = page
    snapshot = _awaiting(store)
    viewed = client.get("/api/node/clm_1")[1]["data"]["candidate_proof"]["sha256"]
    path = store.root / snapshot.file_path
    path.write_text(path.read_text() + "\n% slipped in after the researcher read it\n")

    _, outcome = decide(client, [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept", "viewed_candidate_proof_sha256": viewed}])

    assert outcome["data"]["results"][0]["error"]["code"] == "STALE_VIEW"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


@pytest.mark.parametrize(
    "body, code",
    [({}, "NO_DECISIONS"), ({"decisions": []}, "NO_DECISIONS"), ({"decisions": [42]}, "MALFORMED_DECISION"), ({"decisions": [{"kind": "acceptance"}]}, "MALFORMED_DECISION")],
)
def test_a_malformed_decision_is_refused(page, body, code):
    _, client = page
    status, refused = client.post("/api/decide", body)
    assert (status, refused["error"]["code"]) == (400, code)


def test_a_long_running_page_never_serves_stale_state(page):
    """Nothing is cached across requests: an edit made under the page shows on the next one."""
    store, client = page
    snapshot = _awaiting(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    path = store.root / snapshot.file_path
    original = path.read_text()

    for _ in range(5):
        assert client.get("/api/node/clm_1")[1]["data"]["acceptance_state"] == "accepted"
        path.write_text(original + "% tampered\n")
        assert client.get("/api/node/clm_1")[1]["data"]["acceptance_state"] == "unverifiable"
        path.write_text(original)


# -- the HTTP layer, over a real socket ---------------------------------------------------


def test_host_origin_and_content_type_are_checked(http_app):
    _, client = http_app
    assert client.get("/api/state", host="attacker.example:80")[0] == 421  # DNS rebinding
    assert client.post("/api/decide", {}, origin=None)[0] == 403
    assert client.post("/api/decide", {}, origin="http://evil.example")[0] == 403
    assert client.post("/api/decide", b"decisions=x", content_type="application/x-www-form-urlencoded")[0] == 415


def test_a_decision_over_http_counts(http_app):
    store, client = http_app
    _awaiting(store)
    status, outcome = decide(client, [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept"}])
    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_the_page_and_its_script_are_served_with_a_strict_policy(http_app):
    _, client = http_app
    port = urlsplit(client.origin).port
    for path in ("/", "/static/app.js", "/static/shared/mathtext.js", "/static/shared/vendor/katex.min.js", "/static/shared/vendor/fonts/KaTeX_Main-Regular.woff2"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path, headers={"Host": client.netloc})
        response = conn.getresponse()
        response.read()
        assert response.status == 200
        assert "default-src 'self'" in response.getheader("Content-Security-Policy")
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        conn.close()


@pytest.mark.parametrize(
    "headers, body, status",
    [
        ({"Content-Length": "-5"}, b"", 400),
        ({"Content-Length": "5000000"}, b"", 413),
        ({}, b"[1, 2]", 400),
        ({}, b'{"decisions": [42]}', 400),
    ],
)
def test_malformed_requests_get_an_error_response_not_a_dropped_connection(http_app, headers, body, status):
    _, client = http_app
    port = urlsplit(client.origin).port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("POST", "/api/decide", skip_host=True)
    conn.putheader("Host", client.netloc)
    conn.putheader("Origin", client.origin)
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", headers.get("Content-Length", str(len(body))))
    conn.endheaders()
    if body:
        conn.send(body)
    response = conn.getresponse()
    assert response.status == status
    assert json.loads(response.read())["ok"] is False
    conn.close()


def test_a_pdf_is_served_as_a_pdf_for_the_browsers_own_viewer(http_app):
    store, client = http_app
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    pdf = store.root / "proofs" / "lem" / "build" / "proof.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.5 built\n")
    port = urlsplit(client.origin).port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/node/lem/pdf/build", headers={"Host": client.netloc})
    response = conn.getresponse()
    assert (response.status, response.getheader("Content-Type"), response.read()) == (200, "application/pdf", b"%PDF-1.5 built\n")
    assert response.getheader("Content-Security-Policy") is None
    conn.close()
    assert client.get("/api/node/lem/pdf/snapshot")[0] == 404


def test_the_node_panel_and_node_creation_are_refused_from_another_origin(http_app):
    store, client = http_app
    create_node(store, node_id="lem", kind="lemma", statement="Base")
    assert client.post("/api/node/lem/claim", {}, origin="http://evil.example")[0] == 403
    assert client.post("/api/node/lem/claim", {}, origin=None)[0] == 403
    assert client.post("/api/nodes", {"node_id": "x", "kind": "claim", "statement": "X"}, origin="http://evil.example")[0] == 403
    # a new citation from the node form (#154): no passkey, but the same-origin check as every write (ADR-0007)
    assert client.post("/api/references", {"reference_id": "r", "title": "T", "year": 2000}, origin="http://evil.example")[0] == 403
    assert client.get("/api/references")[0] == 200
    assert get_active_claim(store, "lem") is None
    assert client.post("/api/node/lem/claim", {})[0] == 200  # from the page itself


# -- a node's studio sits behind the same checks (ADR-0011, #69) ---------------------


def test_a_node_studio_is_behind_the_pages_host_and_origin_checks(http_app):
    store, client = http_app
    create_node(store, node_id="S1", kind="claim", statement="s")
    proof = store.root / "proofs" / "S1" / "proof.tex"
    before = proof.read_text()

    assert client.get("/studio/S1/api/tree", host="attacker.example:80")[0] == 421  # DNS rebinding
    assert client.get("/studio/S1/api/tree", origin="https://attacker.example")[0] == 403  # another site
    save = {"path": "proof.tex", "content": "overwritten\n", "base_mtime": None, "force": True}
    assert client.post("/studio/S1/api/file", save, origin="https://attacker.example")[0] == 403
    assert client.post("/studio/S1/api/file", save, origin=None)[0] == 403
    assert proof.read_text() == before

    status, tree = client.get("/studio/S1/api/tree", origin=None)  # the page's own GETs send no Origin
    assert status == 200 and {f["path"] for f in tree["files"]} == {"proof.tex"}
    assert client.post("/studio/S1/api/file", save)[0] == 200
    assert proof.read_text() == "overwritten\n"


def test_a_node_studio_page_is_served_with_its_policy(http_app):
    store, client = http_app
    create_node(store, node_id="S1", kind="claim", statement="s")
    port = urlsplit(client.origin).port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/studio/S1/", headers={"Host": client.netloc})
    response = conn.getresponse()
    response.read()
    conn.close()
    assert response.status == 200
    policy = response.getheader("Content-Security-Policy")
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
