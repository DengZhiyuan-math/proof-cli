"""Bounded read-only source audit of stale-cause history scans.

Writes only this audit's JSON output and a disposable /private/tmp project.
Project state is created through the official domain APIs. Source is pinned.
"""

import gc
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

SOURCE = Path("/Volumes/Codex-Workspace/live/home/zhdeng/proof-cli/.claude/worktrees/0021-stale-cause")
EXPECTED = "6d5cd700812f78b571693231bb629abefec53b65"
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
assert head == EXPECTED, (head, EXPECTED)
sys.path[:0] = [str(SOURCE / "src"), str(SOURCE / "tests")]

from proof_cli import definitions as definitions
from proof_cli import proof_map as proof_map
from proof_cli.storage import ensure_project, read_scope
from _proofs import submit_proof

NODE_COUNT = 100
PROGRESS_COUNT = 3000
REPEATS = 3
result = {
    "head": head,
    "source": str(SOURCE),
    "python": sys.version,
    "platform": platform.platform(),
    "stale_nodes": NODE_COUNT,
    "unrelated_progress_events": PROGRESS_COUNT,
    "repeats": REPEATS,
    "method": "Each sample uses a fresh read_scope; variants alternate. Official APIs create the temporary project. No browser, server, or provider call.",
    "samples": [],
}

with TemporaryDirectory(prefix="t8-standards-performance-", dir="/private/tmp") as temporary:
    start = perf_counter()
    store = ensure_project(Path(temporary))
    definitions.add_definition(store, "D", term="Parameter", text="old", created_by="reader-1")
    ids = [f"C{i}" for i in range(NODE_COUNT)]
    for node_id in ids:
        proof_map.create_node(store, node_id=node_id, kind="claim", statement="Claim", definitions=["D"], created_by="reader-1")
        submit_proof(store, node_id, claimant_id="prover-1", scoping_rationale="scoped", content="proof")
    proof_map.create_node(store, node_id="OTHER", kind="claim", statement="Unrelated", created_by="reader-1")
    with store.transaction():
        for number in range(PROGRESS_COUNT):
            proof_map.record_progress(store, "OTHER", role="prover", by="prover-1", step=1, status="done", note=f"Unrelated progress {number}")
    definitions.edit_definition(store, "D", text="new", edited_by="reader-1", reason="corrected")
    result["seed_seconds"] = perf_counter() - start

    original = proof_map.list_events
    result["history_events"] = len(original(store))
    calls = [0, 0]

    def counted_events(current_store):
        events = original(current_store)
        calls[0] += 1
        calls[1] += len(events)
        return events

    proof_map.list_events = counted_events
    for repeat in range(REPEATS):
        variants = (False, True) if repeat % 2 == 0 else (True, False)
        for include_cause in variants:
            gc.collect()
            calls[:] = [0, 0]
            start = perf_counter()
            with read_scope():
                for node_id in ids:
                    assert proof_map.get_integrity_state(store, node_id) == "potentially-stale"
                    if include_cause:
                        cause = proof_map.get_stale_cause(store, node_id)
                        assert cause["cause"] == "definition-edited" and cause["definition_id"] == "D"
            sample = {
                "repeat": repeat + 1,
                "variant": "integrity-and-cause" if include_cause else "integrity-only",
                "seconds": perf_counter() - start,
                "list_events_calls": calls[0],
                "event_records_read": calls[1],
            }
            result["samples"].append(sample)
            print(json.dumps(sample), flush=True)
    proof_map.list_events = original

baseline = statistics.median(s["seconds"] for s in result["samples"] if s["variant"] == "integrity-only")
enhanced = statistics.median(s["seconds"] for s in result["samples"] if s["variant"] == "integrity-and-cause")
result["median_integrity_seconds"] = baseline
result["median_integrity_and_cause_seconds"] = enhanced
result["median_added_seconds"] = enhanced - baseline
result["median_ratio"] = enhanced / baseline
result["qualification"] = "Synthetic bounded fixture of 100 independent stale snapshots and 3000 unrelated progress events. Measures domain reads, not full HTTP or browser latency; it demonstrates repeated history parsing, not a production SLA breach."
output = Path(__file__).with_name("standards-performance.json")
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"output": str(output), "baseline_median": baseline, "enhanced_median": enhanced, "added_seconds": enhanced - baseline, "ratio": enhanced / baseline}), flush=True)
