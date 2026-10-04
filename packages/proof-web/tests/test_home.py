"""The Home (ADR-0017): the researcher's projects in front of the map, and the list behind it.

The list is one user-level file (`projects.json` under the test's own config home). The Home's
logic is driven through `HomeApp` directly; its HTTP layer, and the project pages it starts in
its own process, over a real socket.
"""

import http.client
import json
import shutil
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner

from _proofs import ensure_key_ideas
from proof_cli import projects
from proof_cli.cli import app
from proof_cli.proof_map import claim_node, create_node, request_review
from proof_cli.storage import ensure_project
from proof_web.home import HomeApp, HomeServer, home_origin, project_answering
from proof_web import home as home_module
from proof_web.server import RequestError, ReviewApp, project_origin

runner = CliRunner()


# -- the list ---------------------------------------------------------------------------------


def test_the_list_lives_in_the_user_config_home_and_lists_a_folder_once(tmp_path, monkeypatch):
    config = tmp_path / "config"
    monkeypatch.setenv(projects.USER_CONFIG_ENV_VAR, str(config))
    folder = tmp_path / "p"
    folder.mkdir()
    assert projects.list_registered() == []
    projects.register_project(folder)
    projects.register_project(str(folder) + "/.")  # another spelling of the same folder
    assert projects.projects_file() == config / "projects.json"
    (entry,) = projects.list_registered()
    assert entry["path"] == str(folder.resolve()) and entry["added_at"] and entry["opened_at"] is None


def test_opening_is_noted_and_the_last_opened_project_comes_first(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    projects.register_project(a)
    projects.register_project(b)
    projects.register_project(a, opened=True)
    assert [Path(e["path"]).name for e in projects.list_registered()] == ["a", "b"]
    assert projects.list_registered()[0]["opened_at"]


def test_forgetting_drops_the_entry_and_leaves_the_folder(tmp_path):
    folder = tmp_path / "p"
    ensure_project(folder)
    projects.register_project(folder)
    assert projects.forget_project(folder) is True
    assert projects.list_registered() == []
    assert projects.forget_project(folder) is False
    assert (folder / ".proof" / "project.sqlite3").exists()


def test_a_damaged_list_file_reads_as_empty(tmp_path):
    projects.projects_file().parent.mkdir(parents=True, exist_ok=True)
    projects.projects_file().write_text("{not json")
    assert projects.list_registered() == []
    projects.register_project(tmp_path)  # and is written afresh
    assert len(projects.list_registered()) == 1


def test_proof_init_lists_the_project(tmp_path):
    result = runner.invoke(app, ["init", "--root", str(tmp_path / "new")])
    assert result.exit_code == 0, result.output
    assert [e["path"] for e in projects.list_registered()] == [str((tmp_path / "new").resolve())]


# -- the cards ---------------------------------------------------------------------------------


@pytest.fixture
def home():
    home = HomeApp()
    yield home
    home.close()


def _project(root: Path, *, theorem=True):
    store = ensure_project(root)
    if theorem:
        create_node(store, node_id="lem", kind="lemma", statement="The partial sums are bounded")
        create_node(store, node_id="thm", kind="theorem", statement=r"Every bounded sequence in $\mathbb{R}$ has a convergent subsequence", dependencies=["lem"])
    projects.register_project(root)
    return store


def test_a_card_reads_the_project_live(tmp_path, home):
    store = _project(tmp_path / "bw")
    (card,) = home.projects()["projects"]
    assert card["name"] == "bw" and card["project_id"] == "proj_alpha" and card["error"] is None
    assert card["theorem"].startswith("Every bounded sequence")
    assert card["url"] == project_origin(store) and card["running"] is False
    assert card["counts"] == {"nodes": 2, "frontier": 1, "awaiting": 0, "accepted": 0, "fog": 0}
    # a review request moves the lemma from the frontier to what awaits the researcher
    claim_node(store, "lem", claimant_id="agent_a", session_id="s")
    ensure_key_ideas(store, "lem")
    request_review(store, "lem", requested_by="agent_a", rationale="scoped")
    (card,) = home.projects()["projects"]
    assert card["counts"]["frontier"] == 0 and card["counts"]["awaiting"] == 1


def test_a_project_without_a_theorem_says_so(tmp_path, home):
    _project(tmp_path / "empty", theorem=False)
    (card,) = home.projects()["projects"]
    assert card["theorem"] is None and card["counts"]["nodes"] == 0


def test_a_folder_that_is_gone_or_holds_no_project_is_still_listed_with_why(tmp_path, home):
    gone = tmp_path / "gone"
    _project(gone)
    shutil.rmtree(gone)
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.register_project(plain)
    cards = {c["name"]: c for c in home.projects()["projects"]}
    assert cards["gone"]["exists"] is False and "gone" in cards["gone"]["error"] and cards["gone"]["counts"] is None
    assert cards["plain"]["exists"] is True and cards["plain"]["project"] is False and "proof init" in cards["plain"]["error"]
    assert not (plain / ".proof").exists()  # listing never starts a project


# -- opening: the Home serves the project's own page, in its own process ------------------------


def _get(url: str, path: str):
    parts = urlsplit(url)
    conn = http.client.HTTPConnection("127.0.0.1", parts.port, timeout=10)
    conn.request("GET", path, headers={"Host": parts.netloc})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data)


def test_open_serves_the_project_on_its_own_origin_and_the_page_links_back_home(tmp_path, home):
    store = _project(tmp_path / "bw")
    opened = home.open({"path": str(tmp_path / "bw")})
    assert opened["url"] == project_origin(store)
    assert project_answering(store)
    status, state = _get(opened["url"], "/api/state")
    assert status == 200 and state["data"]["home"] == home_origin() and state["data"]["root"] == str(store.root)
    # opened again: the same page, and the opening is noted on the card
    assert home.open({"path": str(tmp_path / "bw")})["url"] == opened["url"]
    (card,) = home.projects()["projects"]
    assert card["running"] is True and card["opened_at"]
    # forgetting stops the page this process served
    assert home.forget({"path": str(tmp_path / "bw")}) == {"forgotten": True, "path": str((tmp_path / "bw").resolve())}
    assert not project_answering(store)
    assert home.projects()["projects"] == []


def test_a_project_started_again_at_the_same_path_gets_its_own_page_and_the_old_one_closes(tmp_path, home):
    """Review of ADR-0018: a page belongs to a project instance, not a folder. Deleting a project and starting
    another at the same path gave the new one the old origin, which no longer answered, and its nodes the old
    project's studios and runs."""
    folder = tmp_path / "bw"
    _project(folder)
    old_url = home.open({"path": str(folder)})["url"]
    old_server = home.hub._servers[projects.project_key(folder)][0]
    old_studio = old_server.app.studios.studio("lem")  # the old project's studio of its node "lem"

    shutil.rmtree(folder)
    new_store = _project(folder)  # another project, another instance id, at the same path
    assert project_origin(new_store) != old_url

    new_url = home.open({"path": str(folder)})["url"]

    assert new_url == project_origin(new_store) and project_answering(new_store)
    assert home.hub.url_of(projects.project_key(folder)) == new_url
    assert home_module._health(old_url) is None and old_server.app.studios._closed  # the old page and its studios are gone
    new_server = home.hub._servers[projects.project_key(folder)][0]
    assert new_server is not old_server and new_server.app.studios.studio("lem") is not old_studio
    # opened again: the same new page
    assert home.open({"path": str(folder)})["url"] == new_url


def test_opening_a_deleted_project_from_the_home_closes_its_old_page_and_says_so(tmp_path, home):
    """Review of ADR-0018 (second round): the public entry too — not only the hub — finds the project gone,
    closes the page it still served (its studios with it) and answers PROJECT_NOT_FOUND."""
    folder = tmp_path / "bw"
    _project(folder)
    old_url = home.open({"path": str(folder)})["url"]
    old_server = home.hub._servers[projects.project_key(folder)][0]
    old_server.app.studios.studio("lem")
    shutil.rmtree(folder)

    with pytest.raises(RequestError) as refused:
        home.open({"path": str(folder)})

    assert refused.value.code == "PROJECT_NOT_FOUND"
    assert home.hub.url_of(projects.project_key(folder)) is None and home_module._health(old_url) is None
    assert old_server.app.studios._closed
    (card,) = home.projects()["projects"]
    assert card["running"] is False


class _FakeStudios:
    def __init__(self):
        self.events, self.fail = [], None

    def detach(self):
        self.events.append("detach")

    def close(self):
        self.events.append("close")
        if self.fail is not None:
            raise self.fail


class _FakeServer:
    """A project page that binds nothing: what the hub does around a page is what is under test."""

    made = []

    def __init__(self, store, *, home_url=None):
        self.url, self.studios = project_origin(store), _FakeStudios()
        self.app = type("App", (), {})()
        self.app.studios = self.studios
        _FakeServer.made.append(self)

    def serve_forever(self):
        threading.Event().wait()

    def shutdown(self):
        pass

    def server_close(self):
        self.studios.close()


@pytest.fixture
def offline_home(monkeypatch):
    """A Home whose project pages bind nothing and never find a page already answering."""
    monkeypatch.setattr(home_module, "ReviewServer", _FakeServer)
    monkeypatch.setattr(home_module, "project_answering", lambda store: False)
    _FakeServer.made.clear()
    home = HomeApp()
    yield home
    home.close()


@pytest.mark.parametrize("how", ["forget", "close"])
def test_forget_and_the_homes_close_detach_a_page_whose_project_was_replaced(tmp_path, offline_home, how):
    """Review of ADR-0018 (third round): Forget and the Home closing retire a page the same way `open` does —
    detached first when the folder holds another project, so the old run gives nothing of the new one back."""
    folder = tmp_path / "bw"
    _project(folder)
    offline_home.open({"path": str(folder)})
    shutil.rmtree(folder)
    _project(folder)  # another project at the same path

    offline_home.forget({"path": str(folder)}) if how == "forget" else offline_home.close()

    (page,) = _FakeServer.made
    assert page.studios.events == ["detach", "close"]


def test_creating_a_project_where_a_deleted_one_was_still_served_retires_its_page_first(tmp_path, offline_home):
    """Review of ADR-0018 (fourth round): the new project starts only once the old page is detached and closed."""
    folder = tmp_path / "bw"
    _project(folder)
    offline_home.open({"path": str(folder)})
    shutil.rmtree(folder)

    created = offline_home.create({"path": str(folder)})

    (page,) = _FakeServer.made
    assert page.studios.events == ["detach", "close"] and created["path"] == str(folder.resolve())
    assert offline_home.hub.url_of(projects.project_key(folder)) is None and projects.is_project(folder)


def test_one_page_failing_to_close_does_not_leave_the_others_running(tmp_path, offline_home):
    for name in ("a", "b", "c"):
        _project(tmp_path / name)
        offline_home.open({"path": str(tmp_path / name)})
    first, second, third = _FakeServer.made
    first.studios.fail = RuntimeError("a run's release failed")

    with pytest.raises(RuntimeError):
        offline_home.close()

    assert second.studios.events == ["close"] and third.studios.events == ["close"]
    assert offline_home.hub.url_of(projects.project_key(tmp_path / "b")) is None


def test_forgetting_the_project_a_page_still_serves_closes_it_without_detaching(tmp_path, offline_home):
    """The same project: the run's release must still give the node back, so the page closes attached."""
    folder = tmp_path / "bw"
    _project(folder)
    offline_home.open({"path": str(folder)})

    offline_home.forget({"path": str(folder)})

    (page,) = _FakeServer.made
    assert page.studios.events == ["close"]


def test_a_page_already_served_elsewhere_is_used_as_it_is(tmp_path, home):
    from _review_client import serving

    store = _project(tmp_path / "bw")
    with serving(store) as client:
        assert home.open({"path": str(tmp_path / "bw")})["url"] == client.origin
        assert home.hub.url_of(projects.project_key(tmp_path / "bw")) is None  # not started a second time
        (card,) = home.projects()["projects"]
        assert card["running"] is True


def test_only_a_listed_project_opens(tmp_path, home):
    ensure_project(tmp_path / "unlisted")
    with pytest.raises(RequestError) as refused:
        home.open({"path": str(tmp_path / "unlisted")})
    assert refused.value.code == "PROJECT_UNKNOWN"
    projects.register_project(tmp_path / "missing")
    with pytest.raises(RequestError) as refused:
        home.open({"path": str(tmp_path / "missing")})
    assert refused.value.code == "PROJECT_NOT_FOUND"
    with pytest.raises(RequestError) as refused:
        home.open({})
    assert refused.value.code == "PATH_REQUIRED"


def test_a_page_served_on_its_own_has_no_home_link(tmp_path):
    store = ensure_project(tmp_path)
    assert ReviewApp(store).state()["home"] is None
    assert ReviewApp(store, home_url="http://localhost:1").state()["home"] == "http://localhost:1"


# -- add and create ---------------------------------------------------------------------------


def test_add_lists_an_existing_project_and_refuses_anything_else(tmp_path, home):
    ensure_project(tmp_path / "have")
    card = home.add({"path": str(tmp_path / "have")})
    assert card["name"] == "have" and card["counts"]["nodes"] == 0
    assert [c["name"] for c in home.projects()["projects"]] == ["have"]
    with pytest.raises(RequestError) as refused:
        home.add({"path": str(tmp_path / "nowhere")})
    assert refused.value.code == "FOLDER_NOT_FOUND"
    (tmp_path / "plain").mkdir()
    with pytest.raises(RequestError) as refused:
        home.add({"path": str(tmp_path / "plain")})
    assert refused.value.code == "NOT_A_PROJECT"
    assert not (tmp_path / "plain" / ".proof").exists()


def test_create_starts_a_project_as_init_does_and_lists_it(tmp_path, home):
    card = home.create({"path": str(tmp_path / "deep" / "new"), "project_id": "seq_2026"})
    assert card["project_id"] == "seq_2026" and card["counts"]["nodes"] == 0
    assert (tmp_path / "deep" / "new" / ".proof" / "project.sqlite3").exists()
    with pytest.raises(RequestError) as refused:
        home.create({"path": str(tmp_path / "deep" / "new")})
    assert refused.value.code == "ALREADY_A_PROJECT"
    with pytest.raises(RequestError) as refused:
        home.create({"path": str(tmp_path / "x"), "project_id": "  "})
    assert refused.value.code == "BAD_PROJECT_ID"
    assert home.create({"path": str(tmp_path / "default")})["project_id"] == "proj_alpha"


def test_a_tilde_names_the_home_folder(tmp_path, home, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    card = home.create({"path": "~/tilde"})
    assert card["path"] == str((tmp_path / "tilde").resolve())


# -- over HTTP: the same Host and Origin checks as a project page -----------------------------


@pytest.fixture
def served():
    """A Home on a free port, reached with the Host its fixed origin would have."""
    server = HomeServer(port=0)
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _request(server, method, path, body=None, *, host=None, origin="same"):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    headers = {"Host": host or urlsplit(home_origin()).netloc}
    if origin is not None:
        headers["Origin"] = home_origin() if origin == "same" else origin
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    data, headers_out = response.read(), dict(response.getheaders())
    conn.close()
    try:
        return response.status, json.loads(data), headers_out
    except ValueError:
        return response.status, data, headers_out


def test_the_home_page_and_its_api_answer_on_the_home_origin(served, tmp_path):
    ensure_project(tmp_path / "p")
    projects.register_project(tmp_path / "p")
    status, page, headers = _request(served, "GET", "/")
    assert status == 200 and b"Proof projects" in page and "Content-Security-Policy" in headers
    status, health, _ = _request(served, "GET", "/api/health")
    assert status == 200 and health["data"] == {"home": True, "origin": home_origin()}
    status, listed, _ = _request(served, "GET", "/api/projects")
    assert status == 200 and [c["name"] for c in listed["data"]["projects"]] == ["p"]
    status, answer, _ = _request(served, "GET", "/static/home.js")
    assert status == 200 and b"api/projects/open" in answer


def test_the_home_refuses_another_host_and_a_foreign_origin(served, tmp_path):
    status, answer, _ = _request(served, "GET", "/api/projects", host="127.0.0.1:1")
    assert status == 421 and answer["error"]["code"] == "WRONG_HOST"
    status, answer, _ = _request(served, "POST", "/api/projects/create", {"path": str(tmp_path / "x")}, origin="http://evil.example")
    assert status == 403 and answer["error"]["code"] == "WRONG_ORIGIN"
    assert not (tmp_path / "x").exists()
    status, answer, _ = _request(served, "POST", "/api/projects/nothing", {})
    assert status == 404


def test_opening_over_http_starts_the_page_and_says_where(served, tmp_path):
    store = ensure_project(tmp_path / "p")
    projects.register_project(tmp_path / "p")
    status, answer, _ = _request(served, "POST", "/api/projects/open", {"path": str(tmp_path / "p")})
    assert status == 200 and answer["data"]["url"] == project_origin(store)
    assert project_answering(store)
    status, answer, _ = _request(served, "POST", "/api/projects/open", {"path": str(tmp_path / "other")})
    assert status == 404 and answer["error"]["code"] == "PROJECT_UNKNOWN"
