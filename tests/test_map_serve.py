"""`proof map serve` says why it couldn't bind its port (#160).

A port already taken is a page already running; a refused bind is a permission
or sandbox restriction, where `proof map open` would not help; anything else is
reported as it is.
"""

import errno
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_cli import errors
from proof_cli.cli import app
from proof_cli.storage import ensure_project
from proof_cli.webapp.server import ReviewServer

runner = CliRunner()

CASES = [
    (errno.EADDRINUSE, "REVIEW_PORT_IN_USE", "is it already running?"),
    (errno.EACCES, "REVIEW_PORT_NOT_PERMITTED", "isn't permitted"),
    (errno.EPERM, "REVIEW_PORT_NOT_PERMITTED", "isn't permitted"),
    (errno.EADDRNOTAVAIL, "REVIEW_PORT_UNAVAILABLE", "Can't assign requested address"),
]


def _refuse_bind(monkeypatch, code: int) -> None:
    def server_bind(self):
        raise OSError(code, "Can't assign requested address" if code == errno.EADDRNOTAVAIL else errno.errorcode[code])

    monkeypatch.setattr(ReviewServer, "server_bind", server_bind)


@pytest.mark.parametrize(("code", "error_code", "says"), CASES)
def test_a_failed_bind_says_why(tmp_path: Path, monkeypatch, code, error_code, says):
    ensure_project(tmp_path)
    _refuse_bind(monkeypatch, code)

    result = runner.invoke(app, ["map", "serve", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert says in result.stdout
    if code == errno.EADDRINUSE:
        assert "proof map open" in result.stdout
    else:
        assert "already running" not in result.stdout
        assert "proof map open" not in result.stdout
    if code in (errno.EACCES, errno.EPERM):
        assert "permission or sandbox restriction" in result.stdout


@pytest.mark.parametrize(("code", "error_code", "says"), CASES)
def test_a_failed_bind_under_json_is_one_envelope_with_a_registered_code(tmp_path: Path, monkeypatch, code, error_code, says):
    ensure_project(tmp_path)
    _refuse_bind(monkeypatch, code)

    result = runner.invoke(app, ["map", "serve", "--root", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "map.serve"
    assert payload["error"]["code"] == error_code
    assert error_code in errors.ERROR_CODES
    assert says in payload["error"]["message"]
    assert payload["error"]["errno"] == errno.errorcode[code]
