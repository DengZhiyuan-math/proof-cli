"""Loading the studio never starts a usage probe for a hosted proof agent."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "latex_agent" / "static"
HARNESS = Path(__file__).parent / "js" / "usage_probe_harness.js"


def _load(**scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    done = subprocess.run(
        [node, str(HARNESS), str(STATIC / "app.js"), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _probes(requests):
    return [r for r in requests if r["url"] == "/api/agent/usage"]


def test_opening_a_hosted_studio_with_no_cached_usage_makes_no_model_call():
    page = _load(proof_agent=True)
    assert _probes(page["automatic"]) == []
    assert not any(r["url"].startswith("/api/agent/commands") for r in page["automatic"])
    assert 'id="quota-refresh"' in page["quota"]
    assert page["quotaHidden"] is False


@pytest.mark.parametrize("state", [
    {"provider": {"rate": {"at": 1}}},
    {"cache": {"chat.rate": {"at": 1}}},
    {"cache": {"chat.rate": {"unifiedWindows": {}}}},
])
def test_reloading_a_hosted_studio_never_probes_old_or_undated_usage(state):
    assert _probes(_load(proof_agent=True, **state)["automatic"]) == []


@pytest.mark.parametrize("cache", [{}, {"chat.rate": {"at": 1}}])
def test_standalone_studios_still_probe_missing_or_old_usage(cache):
    page = _load(proof_agent=False, cache=cache)
    assert _probes(page["automatic"]) == [
        {"url": "/api/agent/usage", "body": {"provider": "claude"}},
    ]


@pytest.mark.parametrize("hosted", [False, True])
def test_fresh_usage_needs_no_automatic_probe(hosted):
    page = _load(proof_agent=hosted, cache={"chat.rate": {"at": 2_000_000_000}})
    assert _probes(page["automatic"]) == []


def test_the_researcher_can_still_explicitly_refresh_hosted_usage():
    page = _load(proof_agent=True, manual=True)
    assert _probes(page["automatic"]) == []
    assert _probes(page["requests"]) == [
        {"url": "/api/agent/usage", "body": {"provider": "claude"}},
    ]
