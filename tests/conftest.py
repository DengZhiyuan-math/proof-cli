import pytest


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    """Every test gets its own user-level config instead of the developer's real ~/.config."""
    monkeypatch.setenv("PROOF_CLI_CONFIG_HOME", str(tmp_path_factory.mktemp("user-config")))
