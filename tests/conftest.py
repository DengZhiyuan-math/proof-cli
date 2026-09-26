import pytest

import _authenticator


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    """Every test gets its own user-level config (the Reviewer key pins,
    ADR-0009 point 5) instead of the developer's real ~/.config."""
    monkeypatch.setenv("PROOF_CLI_CONFIG_HOME", str(tmp_path_factory.mktemp("user-config")))
    _authenticator._RESEARCHERS.clear()
