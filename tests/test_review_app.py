"""The local review web app (issue #36), driven over plain HTTP.

The browser's part (navigator.credentials.create/get) is played by the
software authenticator; everything else is the real server, reached the way
a browser — or an agent `curl`ing it — would.
"""

import http.client
import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from _authenticator import Researcher, SoftwareAuthenticator, researcher
from proof_cli.authority import list_reviewer_keys, pinned_first_fingerprint, project_origin
from proof_cli.collaboration import list_review_records
from proof_cli.proof_map import (
    claim_node,
    create_node,
    get_acceptance_state,
    list_integrity_warnings,
    submit_candidate_proof,
)
from proof_cli.signing import (
    SignatureError,
    b64url_decode,
    public_key_fingerprint,
    verify_registration,
)
from proof_cli.storage import ensure_project
from proof_cli.webapp.server import ReviewServer


@pytest.fixture
def app(tmp_path: Path):
    store = ensure_project(tmp_path)
    server = ReviewServer(store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(server.url)
    yield store, client
    server.shutdown()
    server.server_close()


class Client:
    """What a browser on the app's page sends: the pinned Host and Origin, JSON bodies."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.netloc = urlsplit(origin).netloc

    def request(self, method: str, path: str, body=None, *, host: str | None = None, origin: str | None = "same", content_type="application/json"):
        port = urlsplit(self.origin).port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Host": host or self.netloc}
        if origin is not None:
            headers["Origin"] = self.origin if origin == "same" else origin
        payload = None
        if body is not None:
            payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
            headers["Content-Type"] = content_type
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            return response.status, json.loads(data)
        except ValueError:
            return response.status, data

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, body=None, **kwargs):
        return self.request("POST", path, {} if body is None else body, **kwargs)


def _submitted(store, node_id="clm_1"):
    create_node(store, node_id=node_id, kind="claim", statement=f"stmt {node_id}")
    claim_node(store, node_id, claimant_id="agent_a", session_id="s")
    return submit_candidate_proof(store, node_id, claimant_id="agent_a", session_id="s", scoping_rationale="scoped", content=f"# Proof of {node_id}\n\nBy **induction**.")


def _enroll_over_http(client: Client, authenticator: SoftwareAuthenticator, *, signer: SoftwareAuthenticator | None = None):
    status, begin = client.post("/api/enroll/begin", {"display_name": authenticator.display_name})
    assert status == 200, begin
    registration = authenticator.register(b64url_decode(begin["data"]["public_key"]["challenge"]), origin=client.origin)
    status, registered = client.post("/api/enroll/register", {"token": begin["data"]["token"], **registration})
    assert status == 200, registered
    to_sign = registered["data"]
    assertion = (signer or authenticator).assert_challenge(b64url_decode(to_sign["challenge"]), origin=client.origin)
    return client.post("/api/enroll/complete", {"token": to_sign["token"], "assertion": assertion.model_dump()})


def _sign(client: Client, authenticator: SoftwareAuthenticator, decisions: list[dict]):
    status, prepared = client.post("/api/prepare", {"decisions": decisions})
    assert status == 200, prepared
    to_sign = prepared["data"]
    assertion = authenticator.assert_challenge(b64url_decode(to_sign["challenge"]), origin=client.origin)
    return client.post("/api/decide", {"payloads": to_sign["payloads"], "batch": to_sign["batch"], "assertion": assertion.model_dump()})


# -- enrollment: only here, a real registration ceremony ------------------------------


def test_a_researcher_enrolls_a_passkey_and_accepts_a_node(app):
    store, client = app
    _submitted(store)
    passkey = SoftwareAuthenticator(display_name="MacBook Touch ID")

    status, enrolled = _enroll_over_http(client, passkey)

    assert status == 200, enrolled
    assert enrolled["data"]["fingerprint"] == public_key_fingerprint(passkey.public_key_spki)
    assert pinned_first_fingerprint(store) == enrolled["data"]["fingerprint"]
    state = client.get("/api/state")[1]["data"]
    assert [key["display_name"] for key in state["keys"]] == ["MacBook Touch ID"]
    assert [item["node_id"] for item in state["pending"]] == ["clm_1"]

    status, outcome = _sign(client, passkey, [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept", "rationale": "checked"}])

    assert status == 200 and outcome["data"]["results"][0]["ok"], outcome
    assert get_acceptance_state(store, "clm_1") == "accepted"


def test_a_second_passkey_is_enrolled_only_with_a_tap_from_the_first(app):
    store, client = app
    first, second = SoftwareAuthenticator(display_name="Touch ID"), SoftwareAuthenticator(display_name="YubiKey")
    _enroll_over_http(client, first)

    status, refused = _enroll_over_http(client, second)  # the new key vouching for itself
    assert status == 403 and refused["error"]["code"] == "ENROLLMENT_REFUSED"
    status, enrolled = _enroll_over_http(client, second, signer=first)
    assert status == 200, enrolled
    assert {key.display_name for key in list_reviewer_keys(store)} == {"Touch ID", "YubiKey"}


def test_the_registry_banner_can_only_be_cleared_with_a_tap(app):
    store, client = app
    first, second = SoftwareAuthenticator(display_name="Touch ID"), SoftwareAuthenticator(display_name="YubiKey")
    _enroll_over_http(client, first)
    _enroll_over_http(client, second, signer=first)
    assert client.get("/api/state")[1]["data"]["registry"]["acknowledged"] is False

    to_sign = client.post("/api/acknowledge/prepare")[1]["data"]
    status, refused = client.post("/api/acknowledge", {"payloads": to_sign["payloads"], "batch": to_sign["batch"]})
    assert status != 200 and client.get("/api/state")[1]["data"]["registry"]["acknowledged"] is False

    assertion = first.assert_challenge(b64url_decode(to_sign["challenge"]), origin=client.origin)
    status, acknowledged = client.post("/api/acknowledge", {"payloads": to_sign["payloads"], "batch": to_sign["batch"], "assertion": assertion.model_dump()})
    assert status == 200 and acknowledged["data"]["acknowledged"] is True


# -- one tap, N decisions -----------------------------------------------------------


def test_a_batch_of_decisions_needs_exactly_one_tap(app):
    store, client = app
    for node_id in ("clm_1", "clm_2", "clm_3"):
        _submitted(store, node_id)
    passkey = SoftwareAuthenticator(counter=True)
    _enroll_over_http(client, passkey)
    taps_before = passkey.sign_count

    status, outcome = _sign(
        client,
        passkey,
        [{"kind": "acceptance", "target_id": node_id, "decision": "accept"} for node_id in ("clm_1", "clm_2", "clm_3")],
    )

    assert status == 200 and all(result["ok"] for result in outcome["data"]["results"])
    assert passkey.sign_count - taps_before == 1
    assert {get_acceptance_state(store, node_id) for node_id in ("clm_1", "clm_2", "clm_3")} == {"accepted"}
    assert list_integrity_warnings(store) == []


# -- an agent with plain HTTP gets nowhere ---------------------------------------------


def _observable(store):
    return (
        [(r.id, r.decision.value) for r in list_review_records(store) if r.kind is not None],
        [key.fingerprint for key in list_reviewer_keys(store)],
        get_acceptance_state(store, "clm_1"),
    )


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/decide", {}),
        ("/api/decide", {"payloads": [], "batch": [], "assertion": {}}),
        ("/api/enroll/complete", {"token": "made-up", "assertion": {}}),
        ("/api/enroll/register", {"token": "made-up", "client_data_json": "", "attestation_object": ""}),
        ("/api/acknowledge", {}),
    ],
)
def test_a_write_without_a_valid_assertion_changes_nothing(app, path, body):
    store, client = app
    _submitted(store)
    researcher_key = SoftwareAuthenticator()
    _enroll_over_http(client, researcher_key)
    before = _observable(store)

    status, response = client.post(path, body)

    assert status >= 400 and response["ok"] is False
    assert _observable(store) == before


def test_an_agents_own_key_or_a_replayed_assertion_changes_nothing(app):
    store, client = app
    _submitted(store)
    researcher_key = SoftwareAuthenticator()
    _enroll_over_http(client, researcher_key)
    before = _observable(store)

    agent = SoftwareAuthenticator(display_name="agent")
    status, outcome = _sign(client, agent, [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept"}])
    assert status == 200 and outcome["data"]["results"][0]["error"]["code"] == "UNKNOWN_REVIEWER_KEY"

    # a genuine assertion over a *different* decision, submitted for this one
    other = client.post("/api/prepare", {"decisions": [{"kind": "acceptance", "target_id": "clm_1", "decision": "reject"}]})[1]["data"]
    assertion = researcher_key.assert_challenge(b64url_decode(other["challenge"]), origin=client.origin)
    accept = client.post("/api/prepare", {"decisions": [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept"}]})[1]["data"]
    status, outcome = client.post("/api/decide", {"payloads": accept["payloads"], "batch": accept["batch"], "assertion": assertion.model_dump()})
    assert not outcome["data"]["results"][0]["ok"]

    assert _observable(store) == before


def test_an_assertion_from_another_origin_is_refused(app):
    store, client = app
    _submitted(store)
    researcher_key = SoftwareAuthenticator()
    _enroll_over_http(client, researcher_key)
    prepared = client.post("/api/prepare", {"decisions": [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept"}]})[1]["data"]
    assertion = researcher_key.assert_challenge(b64url_decode(prepared["challenge"]), origin="http://localhost:1")

    outcome = client.post("/api/decide", {"payloads": prepared["payloads"], "batch": prepared["batch"], "assertion": assertion.model_dump()})[1]
    assert outcome["data"]["results"][0]["error"]["code"] == "ORIGIN_MISMATCH"
    assert get_acceptance_state(store, "clm_1") == "unreviewed"


def test_host_origin_and_content_type_are_checked(app):
    store, client = app
    assert client.get("/api/state", host="attacker.example:80")[0] == 421  # DNS rebinding
    assert client.post("/api/prepare", {}, origin=None)[0] == 403
    assert client.post("/api/prepare", {}, origin="http://evil.example")[0] == 403
    assert client.post("/api/prepare", b"decisions=x", content_type="application/x-www-form-urlencoded")[0] == 415


# -- the page shows exactly what's signed ----------------------------------------------


def test_the_node_page_shows_the_exact_text_whose_hash_is_signed(app):
    store, client = app
    proof = _submitted(store)
    status, view = client.get("/api/node/clm_1")
    assert status == 200
    shown = view["data"]["candidate_proof"]
    assert shown["text"] == (store.root / proof.file_path).read_text()
    prepared = client.post("/api/prepare", {"decisions": [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept"}]})[1]["data"]
    assert prepared["payloads"][0]["candidate_proof_sha256"] == shown["sha256"]


def test_integrity_warnings_show_next_to_their_node(app):
    store, client = app
    proof = _submitted(store)
    researcher(store).decide_acceptance("clm_1", "accept")
    path = store.root / proof.file_path
    path.write_text(path.read_text() + "\nedited after acceptance\n")

    view = client.get("/api/node/clm_1")[1]["data"]
    assert view["acceptance_state"] == "unverifiable"
    assert "DECISION_NO_LONGER_APPLIES" in [warning["code"] for warning in view["warnings"]]


def _tamper_rationale(store, value: str) -> None:
    """An in-place edit with every trigger dropped and put back: the row counts never change."""
    conn = sqlite3.connect(store.db_path)
    triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()
    for name, _ in triggers:
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("UPDATE review_history SET rationale = ? WHERE kind = 'acceptance' AND entry = 'decision'", (value,))
    for _, sql in triggers:
        conn.execute(sql)
    conn.commit()
    conn.close()


def test_a_long_running_app_never_serves_stale_trust_state(app):
    """Every request runs on a fresh thread; an edit made under the app is seen on the very next one (#36)."""
    store, client = app
    _submitted(store)
    passkey = SoftwareAuthenticator()
    _enroll_over_http(client, passkey)
    _sign(client, passkey, [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept", "rationale": "ok"}])

    for _ in range(25):
        assert client.get("/api/node/clm_1")[1]["data"]["acceptance_state"] == "accepted"
        _tamper_rationale(store, "tampered")
        assert client.get("/api/node/clm_1")[1]["data"]["acceptance_state"] == "unverifiable"
        _tamper_rationale(store, "ok")


def test_signing_refuses_a_proof_that_changed_since_it_was_viewed(app):
    store, client = app
    proof = _submitted(store)
    passkey = SoftwareAuthenticator()
    _enroll_over_http(client, passkey)
    viewed = client.get("/api/node/clm_1")[1]["data"]["candidate_proof"]["sha256"]

    path = store.root / proof.file_path
    path.write_text(path.read_text() + "\nslipped in after the researcher read it\n")

    status, refused = client.post(
        "/api/prepare",
        {"decisions": [{"kind": "acceptance", "target_id": "clm_1", "decision": "accept", "viewed_candidate_proof_sha256": viewed}]},
    )
    assert status == 409 and refused["error"]["code"] == "STALE_VIEW"


def test_editing_the_pin_file_cant_clear_the_registry_banner(app):
    import json as _json

    from proof_cli.authority import user_config_dir

    store, client = app
    first, second = SoftwareAuthenticator(display_name="Touch ID"), SoftwareAuthenticator(display_name="YubiKey")
    _enroll_over_http(client, first)
    _enroll_over_http(client, second, signer=first)
    pins_path = user_config_dir() / "reviewer-pins.json"
    pins = _json.loads(pins_path.read_text())
    entry = pins["projects"][str(store.root.resolve())]
    entry["acknowledgement"] = "forged"
    entry["acknowledged_registry_head"] = client.get("/api/state")[1]["data"]["registry"]["registry_head"]
    pins_path.write_text(_json.dumps(pins))

    assert client.get("/api/state")[1]["data"]["registry"]["acknowledged"] is False


@pytest.mark.parametrize(
    "headers, body, status",
    [
        ({"Content-Length": "-5"}, b"", 400),
        ({"Content-Length": "5000000"}, b"", 413),
        ({}, b"[1, 2]", 400),
        ({}, b'{"decisions": [42]}', 400),
    ],
)
def test_malformed_requests_get_an_error_response_not_a_dropped_connection(app, headers, body, status):
    _, client = app
    port = urlsplit(client.origin).port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("POST", "/api/prepare", skip_host=True)
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


@pytest.mark.parametrize(
    "attestation_object",
    [
        "gYGBgYGBgYGBgYGBgYGBgQ",  # arrays nested 17 deep
        "oYEBAQ",  # a map keyed by an array
        "o2NmbXRkbm9uZWdhdHRTdG10oGhhdXRoRGF0YQE",  # authData isn't bytes
    ],
)
def test_a_hostile_registration_is_refused_not_crashed_on(tmp_path: Path, attestation_object):
    store = ensure_project(tmp_path)
    origin = project_origin(store)
    registration = SoftwareAuthenticator().register(b"c" * 32, origin=origin)
    with pytest.raises(SignatureError) as exc_info:
        verify_registration(registration["client_data_json"], attestation_object, challenge=b"c" * 32, expected_origin=origin)
    assert exc_info.value.code == "MALFORMED_ASSERTION"


# -- WebAuthn details ------------------------------------------------------------------


def test_a_cloned_credential_shows_up_as_a_sign_count_regression(tmp_path: Path):
    store = ensure_project(tmp_path)
    for node_id in ("clm_1", "clm_2"):
        _submitted(store, node_id)
    passkey = SoftwareAuthenticator(counter=True)
    reviewer = Researcher(store, passkey)
    reviewer.decide_acceptance("clm_1", "accept")
    passkey.sign_count = 0  # a clone starts counting from an old value
    reviewer.decide_acceptance("clm_2", "accept")

    assert "SIGN_COUNT_REGRESSION" in [warning.code for warning in list_integrity_warnings(store)]


@pytest.mark.parametrize(
    "options, code",
    [
        ({"origin": "http://localhost:1"}, "ORIGIN_MISMATCH"),
        ({"flags": 0x41}, "USER_NOT_VERIFIED"),
        ({"rp_id": "evil.example"}, "RP_ID_MISMATCH"),
    ],
)
def test_a_registration_violating_the_relying_party_rules_is_refused(tmp_path: Path, options, code):
    store = ensure_project(tmp_path)
    origin = project_origin(store)
    challenge = b"c" * 32
    registration = SoftwareAuthenticator().register(challenge, **{"origin": origin, **options})
    with pytest.raises(SignatureError) as exc_info:
        verify_registration(**registration, challenge=challenge, expected_origin=origin)
    assert exc_info.value.code == code


def test_a_registration_yields_the_credentials_public_key(tmp_path: Path):
    for alg in (-7, -8):
        passkey = SoftwareAuthenticator(alg)
        registration = passkey.register(b"c" * 32, origin="http://localhost:20001")
        credential = verify_registration(**registration, challenge=b"c" * 32, expected_origin="http://localhost:20001")
        assert credential.public_key_spki == passkey.public_key_spki
        assert credential.credential_id == passkey.credential_id and credential.alg == alg
