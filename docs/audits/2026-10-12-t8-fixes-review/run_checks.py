"""Native audit checks of the six-commit synthetic candidate; no source edits."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

out = Path(__file__).resolve().parent
candidate = json.loads((out / "local-candidate.json").read_text())
repos = {k: Path(v["checkout"]) for k, v in candidate["repositories"].items()}
sources = [repos["core"] / "src", repos["core"] / "packages/latex-agent/src", repos["agents"] / "src", repos["web"] / "src"]
env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, sources)), "PYTHONDONTWRITEBYTECODE": "1"}
specs = {
    "core-affected": (repos["core"], ["tests/" + f for f in ("test_unfixed_text.py", "test_cli_contract.py", "test_cli_node.py", "test_definitions.py", "test_performance.py", "test_agent_attribution.py")]),
    "agents-full": (repos["agents"], ["tests"]),
    "web-full": (repos["web"], ["tests"]),
}


def run(item):
    name, (cwd, tests) = item
    xml = out / (name + ".xml")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(cwd / "pyproject.toml"), *tests, "--junitxml=" + str(xml)]
    start = time.monotonic()
    with (out / (name + ".log")).open("w") as log:
        process = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    suites = ET.parse(xml).getroot().iter("testsuite")
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.get(key, 0))
    return {"name": name, "command": cmd, "cwd": str(cwd), "exit": process.returncode, "seconds": time.monotonic() - start, **counts}


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, specs.items()))
    (out / "native-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    raise SystemExit(any(r["exit"] for r in results))
