"""proof-web's tests: the pages over the core, with the studio (latex-agent) and the run (proof-agents) inside.

They share proof-cli's test helpers (`_proofs`, `_researcher`, `fixtures/…`) from the checkout, so they run
from the repository root or from this folder; in a checkout of this package alone, copy those files beside this one.
"""

import sys
from pathlib import Path

import pytest

from latex_agent.httpbase import STATIC as STUDIO_STATIC

CORE_TESTS = Path(__file__).resolve().parents[3] / "tests"
if CORE_TESTS.is_dir() and str(CORE_TESTS) not in sys.path:
    sys.path.append(str(CORE_TESTS))


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    """Every test gets its own user-level config instead of the developer's real ~/.config."""
    monkeypatch.setenv("PROOF_CLI_CONFIG_HOME", str(tmp_path_factory.mktemp("user-config")))
    monkeypatch.setenv("PRISM_AGENTS", str(tmp_path_factory.mktemp("agents") / "agents.json"))
    # the JS harnesses (tests/js) load the studio page's scripts from latex-agent
    monkeypatch.setenv("STUDIO_STATIC", str(STUDIO_STATIC))


def pytest_configure(config):
    """`proof home`, `proof map open` and `proof map serve` on the CLI under test, as when this package is installed."""
    from proof_cli.cli import app, map_app, review_app
    from proof_web.cli import register

    register(app, map_app, review_app)
