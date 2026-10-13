import copy
import json
import runpy
import sys
from pathlib import Path

module = runpy.run_path(str(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('coordinator.py')))
Coordinator, CoordinatorHooks = module['Coordinator'], module['CoordinatorHooks']

class Run:
    def __init__(self, node_id, started):
        self.node_id, self.started = node_id, started
        self.status = 'running' if node_id == 'T' else 'idle'
        self.starts = 0
        self.reason = ''
    def view(self):
        return {'status': self.status, 'reason': self.reason, 'turns': 1 if self.node_id == 'T' else 0, 'started_at': 1.0}
    def start(self, provider, **kwargs):
        self.started.append(self.node_id)
        self.starts += 1
        self.status = 'running'
        return {'started_at': 2.0}

def node(node_id, kind='claim', dependencies=None, split_children=None):
    return {'id': node_id, 'kind': kind, 'dependencies': dependencies or [], 'split_children': split_children or [], 'has_run': True, 'accepted': False, 'provisional': False, 'workflow': 'open', 'claimed_by': None}

def coordinator(nodes, runs, subtree=None, split_before=None):
    c = Coordinator(CoordinatorHooks(subtree=subtree or (lambda: copy.deepcopy(nodes)), run=runs.__getitem__, budget=lambda: (5, 10.0), parallel=lambda: 4), 'T')
    c.state.status, c.state.name, c.state.provider = 'running', 'agent', 'claude'
    c.state.running, c.state.decomposed = ['T'], ['T']
    c.state.nodes = {'T': {'starts': 1, 'turns': 0, 'last': None, 'role': 'decomposer', 'split_before': split_before or [], 'started_at': 1.0}}
    return c

started = []
nodes = [node('T', 'theorem', ['S'], ['S']), node('S')]
runs = {n['id']: Run(n['id'], started) for n in nodes}
reads = 0

def subtree_with_interleaving():
    global reads
    snapshot = copy.deepcopy(nodes)
    reads += 1
    if reads == 1:
        # The map snapshot was taken. The provider now commits its split and ends,
        # before the Coordinator reads the parent's run status in _running().
        nodes[0]['dependencies'] += ['C1', 'C2']
        nodes[0]['split_children'] += ['C1', 'C2']
        for child in ('C1', 'C2'):
            nodes.append(node(child))
            runs[child] = Run(child, started)
        runs['T'].status = 'needs-human'
        runs['T'].reason = 'the statement asks x > 0 and x <= 0'
    return snapshot

c = coordinator(nodes, runs, subtree=subtree_with_interleaving, split_before=['S'])
c._step()
assert started == ['S']
c._step()
print(json.dumps({'head': 'cb623269bbef89331f467b457f043090b2cf8d6c', 'started': started, 'parked': c.state.parked, 'held': c.state.held, 'expected_started': ['S']}, indent=2))
assert started == ['S'] and set(c.state.held) == {'C1', 'C2'} and 'T' in c.state.parked, 'The ended Decomposer was parked against the earlier map snapshot. Its new Claims must still be held when the next map snapshot reveals them.'
