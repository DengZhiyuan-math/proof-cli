import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path('/private/tmp/proof-latest-audit-20261013-01a13595')
RUN_ROOT = Path(tempfile.mkdtemp(prefix='alias-run-', dir=ROOT / 'spec-probes'))
sys.path[:0] = [str(ROOT / 'core/tests'), str(ROOT / 'web/tests')]
from _researcher import researcher
from _review_client import DirectClient
from proof_agents.proof_agent import ProofAgentContext, agent_name
from proof_agents.reader import ReaderContext
from proof_cli.cli import app
from proof_cli.proof_map import create_node, get_node, get_reference_review_state
from proof_cli.reviews import git_identity
from proof_cli.storage import ensure_project
from typer.testing import CliRunner


def cli(root, args, env):
    result = CliRunner().invoke(app, args + ['--root', str(root), '--json'], env=env)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


answers = []
for mode in ('normal', 'human', 'git_identity'):
    root = RUN_ROOT / ('alias-project-' + mode)
    store = ensure_project(root)
    alias = 'reader' if mode == 'normal' else ('human' if mode == 'human' else git_identity(root))
    (root / 'proof.toml').write_text('[studio]\nagent_name = ' + json.dumps(alias) + '\n')
    create_node(store, node_id='T', kind='theorem', statement='Main', created_by='human')
    # Same CLI env used by Reader; no model or provider starts.
    reader = ReaderContext(root, name=agent_name(root, 'claude'))
    cli(root, ['node', 'create', 'orphan', 'lemma', 'Unattached agent work'], reader.env())
    client = DirectClient(store)
    starts = []
    done = SimpleNamespace(open_nodes=lambda: [], start=lambda *a, **k: starts.append('T') or {},
                           active=lambda: False, view=lambda: {'status': 'done', 'reason': 'offline stub', 'turns': 0})
    client.app.studios.coordinator = lambda node_id: done
    try:
        nodes = client.app.studios._pursuit_nodes()
        status, response = client.post('/api/pursue/start', {'provider': 'offline', 'limits': {'turns': 4, 'minutes': 1}})
        assert status == 200, response
        deadline = time.monotonic() + 5
        while True:
            view = client.get('/api/pursue')[1]['data']
            if view['status'] not in ('idle', 'reading', 'pursuing'):
                break
            assert time.monotonic() < deadline
            time.sleep(.01)
        answers.append({'case': mode, 'alias': alias, 'created_by': get_node(store, 'orphan').created_by,
                        'orphan_hook': next(n for n in nodes if n['id'] == 'orphan'),
                        'status': view['status'], 'reason': view['reason'], 'coordinator_starts': starts})
    finally:
        client.app.close()

root = RUN_ROOT / 'alias-trust-project'
store = ensure_project(root)
(root / 'proof.toml').write_text('[studio]\nagent_name = "human"\n')
create_node(store, node_id='T', kind='theorem', statement='Main', created_by='human')
researcher(store).declare_trust_rule('textbooks', conditions=[{'kind': 'source_type_in', 'values': ['textbook']}],
                                    rationale='synthetic offline fixture')
agent = ProofAgentContext('T', root, role='prover', name=agent_name(root, 'claude'))
cli(root, ['reference', 'import', 'r', 'Fixture textbook', '2020', '--author', 'Fixture', '--source-type', 'textbook'], agent.env())
cli(root, ['node', 'create', 'I', 'imported_result', 'Unreviewed agent statement', '--parent', 'T',
           '--reference-id', 'r', '--source-locator', 'Theorem 1', '--source-version', 'v1'], agent.env())
answers.append({'case': 'human_alias_trust', 'created_by': get_node(store, 'I').created_by,
                'reference_state': get_reference_review_state(store, 'I')})
serialized = json.dumps(answers, ensure_ascii=False, indent=2)
(RUN_ROOT / 'alias-result.json').write_text(serialized + '\n')
print(serialized)
