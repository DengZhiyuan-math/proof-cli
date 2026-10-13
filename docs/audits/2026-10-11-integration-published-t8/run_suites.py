"""Run the published integration sources on the macOS host."""
import concurrent.futures
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

out = Path(__file__).resolve().parent
manifest = json.loads((out / 'manifest.json').read_text())
repos = manifest['repositories']
paths = [repos['core']['sourcePath'] + '/src', repos['core']['sourcePath'] + '/packages/latex-agent/src', repos['agents']['sourcePath'] + '/src', repos['web']['sourcePath'] + '/src']
env = dict(os.environ, PYTHONPATH=os.pathsep.join(paths), PYTHONDONTWRITEBYTECODE='1')
probe = subprocess.check_output([sys.executable, '-c', 'import proof_cli,proof_agents,proof_web,latex_agent,json; print(json.dumps({m.__name__:m.__file__ for m in [proof_cli,proof_agents,proof_web,latex_agent]}))'], env=env, text=True)
(out / 'loaded-sources.json').write_text(probe)
(out / 'runtime.json').write_text(json.dumps({p: importlib.metadata.version(p) for p in ['pytest','pydantic','typer','rich','click']}, indent=2)+'\n')

def run(key):
    start = datetime.datetime.now(datetime.timezone.utc)
    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--junitxml=' + str(out / (key+'-suite.xml'))]
    with (out / (key+'-suite.log')).open('w') as log:
        result = subprocess.run(cmd, cwd=repos[key]['sourcePath'], env=env, stdout=log, stderr=subprocess.STDOUT)
    record = {'command':cmd, 'cwd':repos[key]['sourcePath'], 'exitCode':result.returncode, 'startedAt':start.isoformat(), 'endedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out / (key+'-suite-result.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(key, 'exit', result.returncode, 'log:', str(out / (key+'-suite.log')), flush=True)
    return key, record

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results = dict(pool.map(run, ['core','agents','web']))
(out / 'suite-results.json').write_text(json.dumps(results, indent=2)+'\n')
