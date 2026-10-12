import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent
stage = sys.argv[1]
out = ROOT / ('browser-' + stage)
out.mkdir(exist_ok=True)
sources = [ROOT / 'core/src', ROOT / 'core/packages/latex-agent/src', ROOT / 'agents/src', ROOT / 'web/src']
os.environ['PYTHONPATH'] = os.pathsep.join(map(str, sources))
os.environ['PROOF_CLI_CONFIG_HOME'] = str(out / 'user-config')
os.environ['PRISM_AGENTS'] = str(out / 'agents.json')
specs = {'claude': {'enabled': False}, 'codex': {'enabled': False}} if stage == 'candidate' else {'claude': {'bin': '/usr/bin/false'}, 'codex': {'bin': '/usr/bin/false'}}
(out / 'agents.json').write_text(json.dumps({'default': 'claude', 'providers': specs}))
for path in [*sources, ROOT / 'web/tests']:
    sys.path.insert(0, str(path))

from proof_cli.definitions import add_definition
from proof_cli.proof_map import create_node, list_nodes
from proof_cli.projects import register_project
from proof_cli.storage import ensure_project
from proof_web.home import HomeServer
from latex_agent.backends import load_backends
from _proofs import submit_proof

project = out / 'project'
store = ensure_project(project, project_id='ADR0021-' + stage + '-smoke')
if not list_nodes(store):
    add_definition(store, 'D', term='Smoke fixture', text='UI fixture only. No mathematical Acceptance.', created_by='smoke-fixture')
    create_node(store, node_id='C', kind='claim', statement='Smoke fixture claim.', definitions=['D'], created_by='smoke-fixture')
    create_node(store, node_id='T', kind='theorem', statement='Smoke fixture theorem.', dependencies=['C'], created_by='smoke-fixture')
    submit_proof(store, 'C', claimant_id='smoke-fixture', scoping_rationale='UI smoke fixture only', content='UI fixture. No mathematical claim is accepted.')
register_project(project)
providers, _, _ = load_backends()
assert not providers if stage == 'candidate' else all(p.bin() == '/usr/bin/false' for p in providers.values())
server = HomeServer()
info = {'pid': os.getpid(), 'url': server.url, 'project': str(project), 'provider_mode': 'disabled' if stage == 'candidate' else 'non-model CLI stand-ins', 'provider_bins': {k:p.bin() for k,p in providers.items()}, 'provider_ids': list(providers), 'heads': {key: subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT/key,text=True).strip() for key in ('core','agents','web')}, 'sources': {name: importlib.import_module(name).__file__ for name in ('proof_cli.proof_map', 'latex_agent.agent', 'proof_agents.proof_agent', 'proof_web.home')}}
(out / 'server.json').write_text(json.dumps(info, indent=2) + '\n')
print(json.dumps(info), flush=True)
stop = threading.Event()
signal.signal(signal.SIGINT, lambda *_: stop.set())
signal.signal(signal.SIGTERM, lambda *_: stop.set())
threading.Thread(target=server.serve_forever, daemon=True).start()
stop.wait()
server.shutdown()
server.server_close()
