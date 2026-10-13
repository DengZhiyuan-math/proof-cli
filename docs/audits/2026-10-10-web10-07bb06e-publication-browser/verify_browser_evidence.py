"""Check saved browser observations against #10's recovery contract."""
import json
from pathlib import Path

from proof_cli.pursuit import project_progress
from proof_cli.storage import ProjectStore

evidence = Path(__file__).resolve().parent


def browser(name):
    output = json.loads((evidence / f"{name}.json").read_text())
    assert output["success"], output
    return output["data"]["result"]


results = []
for prefix, status, reason in (
    ("ending", "stuck", "the Reader stated no Theorem"),
    ("reader-error", "stuck", "the Reader's turn failed: browser fixture: Reader failed to read the draft"),
    ("release-retry", "released", "stopped by the researcher"),
):
    for phase in ("before-refresh", "after-refresh", "after-restart"):
        observed = browser(f"{prefix}-{phase}")
        assert observed["view"]["status"] == status, observed
        assert observed["view"]["reason"] == reason, observed
        assert observed["text"] == f"{status} — {reason}", observed
        assert observed["stopHidden"], observed
    assert browser(f"{prefix}-after-restart")["view"]["recorded"] is True
    results.append(f"{prefix}: ending and reason survive refresh and process restart")

for phase in ("before-refresh", "after-refresh"):
    observed = browser(f"release-interrupted-{phase}")
    assert observed["view"]["status"] == "release-failed", observed
    assert "L1 is still claimed by claude-code" in observed["text"], observed
    assert observed["startHidden"] and not observed["stopHidden"], observed
interrupted = browser("release-interrupted-after-restart")
assert interrupted["view"]["status"] == "interrupted", interrupted
assert interrupted["view"]["last_phase"] == "release_failed", interrupted
assert "L1 is still claimed by claude-code" in interrupted["text"], interrupted
assert "a new Start rechecks claims" in interrupted["text"], interrupted
assert interrupted["stopHidden"], interrupted
results.append("release-interrupted: reason retained and Stop hidden after restart")

failed_retry = browser("release-retry-failed")
assert failed_retry["view"]["status"] == "release-failed" and not failed_retry["stopHidden"]
results.append("release-retry: first Stop fails; second Stop records released")
for name in ("record-error", "record-error-after-refresh"):
    observed = browser(name)
    assert "History not saved:" in observed["text"] and "browser fixture: disk full" in observed["text"]
    assert "disk full" in observed["view"]["record_error"]
results.append("record-error: visible History not saved survives same-hub refresh")
start_error = browser("start-record-error")
assert "PURSUIT_RECORD_FAILED" in start_error["message"]
assert start_error["view"]["status"] == "idle" and start_error["stopHidden"]
results.append("start-record-error: visible refusal and idle state")

histories = {}
for project in ("ending", "reader-error", "release-retry", "release-interrupted-v2", "record-error", "start-record-error"):
    root = Path("/private/tmp/proof-web10-acceptance/projects") / project
    histories[project] = project_progress(ProjectStore(root))
    if project != "start-record-error":
        assert len(histories[project]) == 1, histories[project]
assert histories["start-record-error"] == []
assert histories["release-interrupted-v2"][-1]["status"] == "interrupted"
assert not any(e["phase"] == "end" for e in histories["release-interrupted-v2"][-1]["events"])
phases = [e["phase"] for e in histories["release-retry"][-1]["events"]]
assert phases == ["start", "reader_end", "theorem", "stop", "release_failed", "stop", "end"], phases
assert histories["record-error"][-1]["status"] == "interrupted"
results.append("core histories: failed release has no end; retry adds one end; refused start adds no event")
(evidence / "project-histories.json").write_text(json.dumps(histories, indent=2) + "\n")
(evidence / "browser-results.json").write_text(json.dumps({"passed": results, "real_model_calls": 0}, indent=2) + "\n")
print("\n".join(results))
