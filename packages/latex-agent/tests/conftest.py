import pytest


@pytest.fixture(autouse=True)
def _isolated_agent_settings(tmp_path_factory, monkeypatch):
    """The agent panel's user-level settings file (backends.config_path) is the test's, never the developer's."""
    monkeypatch.setenv("PRISM_AGENTS", str(tmp_path_factory.mktemp("agents") / "agents.json"))
