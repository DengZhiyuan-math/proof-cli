import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from typer.testing import CliRunner
from proof_cli.cli import app
from proof_cli.proof_map import add_dependency, create_node, list_nodes, remove_dependency, split_node
from proof_cli.reviews import git_identity
from proof_cli.storage import ensure_project
from proof_agents.reader import ReaderContext

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web/tests'))
sys.path.insert(0, str(ROOT / 'core/tests'))
from _review_client import DirectClient
from test_reader_main_target import CompletedCoordinator, wait_for_end


def shared_live_dependency(base):
    store = ensure_project(base / 'shared')
    create_node(store, node_id='D', kind='lemma', statement='Shared support', created_by='reader')
    create_node(store, node_id='T', kind='theorem', statement='Main', created_by='human')
    split_node(store, 'T', [{'id': 'old', 'statement': 'Old route'}, {'id': 'current', 'statement': 'Current route'}], created_by='decomposer')
    split_node(store, 'old', [{'id': 'D1', 'statement': 'Old part'}, {'id': 'D2', 'statement': 'Old support'}], created_by='decomposer')
    add_dependency(store, 'old', 'D', edited_by='human')
    remove_dependency(store, 'T', 'old', edited_by='human')
    create_node(store, node_id='aside', kind='lemma', statement='Researcher separate work', dependencies=['D'], created_by='human')
    client = DirectClient(store)
    starts = []
    client.app.studios.coordinator = lambda node_id: CompletedCoordinator(node_id, starts)
    outputs = []
    initial_map = [{'id': n.id, 'by': n.created_by, 'deps': n.dependencies, 'derived_from': n.derived_from} for n in list_nodes(store)]
    try:
        for _ in range(2):
            status, answer = client.post('/api/pursue/start', {'provider': 'offline', 'limits': {'turns': 4, 'minutes': 1}})
            assert status == 200, answer
            outputs.append(wait_for_end(client))
        remove_dependency(store, 'old', 'D', edited_by='human')
        status, answer = client.post('/api/pursue/start', {'provider': 'offline', 'limits': {'turns': 4, 'minutes': 1}})
        assert status == 200, answer
        control = wait_for_end(client)
    finally:
        client.app.close()
    return {'initial_map': initial_map,
            'with_abandoned_shared_edge': outputs, 'without_abandoned_shared_edge_control': control, 'coordinator_starts': starts}


def rooted_identity(base):
    project = base / 'rooted'
    project.mkdir()
    subprocess.run(['git', 'init', '-q', str(project)], check=True)
    subprocess.run(['git', '-C', str(project), 'config', 'user.name', 'Rooted Researcher'], check=True)
    subprocess.run(['git', '-C', str(project), 'config', 'user.email', 'rooted@example.invalid'], check=True)
    store = ensure_project(project)
    create_node(store, node_id='T', kind='theorem', statement='Main', created_by='human')
    ident = git_identity(project)
    runner = CliRunner()
    env = {'PROOF_AGENT_ROLE': 'reader', 'PROOF_AGENT_NAME': ident, 'PROOF_ROOT': None}
    result = runner.invoke(app, ['node', 'create', 'rooted-alias', 'lemma', 'Unwired supporting result', '--root', str(project), '--json'], env=env)
    correct_env = ReaderContext(project, name=ident).env()
    corrected = runner.invoke(app, ['node', 'create', 'proper-context-alias', 'lemma', 'Another unwired result', '--json'], env=correct_env)
    client = DirectClient(store)
    starts = []
    client.app.studios.coordinator = lambda node_id: CompletedCoordinator(node_id, starts)
    try:
        status, answer = client.post('/api/pursue/start', {'provider': 'offline', 'limits': {'turns': 4, 'minutes': 1}})
        assert status == 200, answer
        ending = wait_for_end(client)
    finally:
        client.app.close()
    return {'project_identity': ident, 'cwd_identity': git_identity(Path.cwd()), 'root_flag_write': {'exit': result.exit_code, 'out': result.output},
            'actual_context_control': {'exit': corrected.exit_code, 'out': corrected.output}, 'ending': ending, 'coordinator_starts': starts}


with tempfile.TemporaryDirectory(prefix='spec-projects-', dir=ROOT / 'spec-probes') as temp:
    base = Path(temp)
    data = {'shared_dependency': shared_live_dependency(base), 'root_flag_identity': rooted_identity(base)}
    print(json.dumps(data, indent=2))
