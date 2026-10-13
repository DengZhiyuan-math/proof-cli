import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
key, stage = sys.argv[1:]
repo = ROOT / key
sources = [ROOT / 'core/src', ROOT / 'core/packages/latex-agent/src', ROOT / 'agents/src', ROOT / 'web/src']
env = {**os.environ, 'PYTHONPATH': os.pathsep.join(map(str, sources)), 'PYTHONDONTWRITEBYTECODE': '1'}
name = f'{stage}-{key}'
xml = ROOT / 'logs' / f'{name}.xml'
cmd = [sys.executable, '-m', 'pytest', '-q', '-ra', '--durations=10', '-p', 'no:cacheprovider', '-c', str(repo / 'pyproject.toml'), '--junitxml=' + str(xml)]
started = time.monotonic()
with (ROOT / 'logs' / f'{name}.log').open('w') as log:
    result = subprocess.run(cmd, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
counts = {k: 0 for k in ('tests', 'failures', 'errors', 'skipped')}
skips = []
if xml.exists():
    tree = ET.parse(xml)
    for suite in tree.getroot().iter('testsuite'):
        for k in counts:
            counts[k] += int(suite.get(k, 0))
    for case in tree.getroot().iter('testcase'):
        skip = case.find('skipped')
        if skip is not None:
            skips.append({'class': case.get('classname'), 'name': case.get('name'), 'reason': skip.get('message')})
data = {'name': name, 'command': cmd, 'cwd': str(repo), 'exit': result.returncode, 'seconds': time.monotonic() - started, 'platform': platform.platform(), 'python': sys.version, 'heads': {}, **counts, 'skips': skips}
for k in ('core', 'agents', 'web'):
    data['heads'][k] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT/k, text=True).strip()
(ROOT / 'logs' / f'{name}.json').write_text(json.dumps(data, indent=2) + '\n')
print(json.dumps(data, indent=2))
raise SystemExit(result.returncode)
