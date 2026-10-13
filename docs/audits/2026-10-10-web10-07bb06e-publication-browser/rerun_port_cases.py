"""Rerun only the 19 port cases unverified in the implementation's full-suite log."""
from pathlib import Path
import subprocess
import sys

evidence = Path(__file__).resolve().parent
old_log = evidence.parent / "2026-10-10-web10-07bb06e-evidence" / "full-suite-10-07bb06e.log"
cases = [line.split(" ", 1)[1].partition(" - ")[0]
         for line in old_log.read_text().splitlines()
         if line.startswith(("FAILED tests/", "ERROR tests/"))]
assert len(cases) == 19, cases
(evidence / "port-cases.txt").write_text("\n".join(cases) + "\n")
with (evidence / "port-cases-rerun.log").open("w") as output:
    result = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", *cases],
                            cwd="/private/tmp/proof-web10-acceptance/web", stdout=output, stderr=subprocess.STDOUT)
print((evidence / "port-cases-rerun.log").read_text())
raise SystemExit(result.returncode)
