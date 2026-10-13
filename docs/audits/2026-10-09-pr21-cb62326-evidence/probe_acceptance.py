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

results = []
for first_split in (False, True):
    for ending in ('needs-human', 'done'):
        started = []
        nodes = [node('T', 'theorem', ['S', 'C1', 'C2'], ['C1', 'C2'] if first_split else ['S', 'C1', 'C2']), node('S'), node('C1'), node('C2')]
        runs = {n['id']: Run(n['id'], started) for n in nodes}
        c = coordinator(nodes, runs, split_before=[] if first_split else ['S'])
        for _ in range(5):
            c._step()
        assert started == ['S'], (first_split, ending, started)
        runs['T'].status = ending
        runs['T'].reason = 'the statement asks x > 0 and x <= 0' if ending == 'needs-human' else 'split into 2 Claim(s): C1, C2'
        c._step()
        if ending == 'needs-human':
            assert started == ['S'] and set(c.state.held) == {'C1', 'C2'} and 'T' in c.state.parked
        else:
            assert started == ['S', 'C1', 'C2'] and not c.state.held
        results.append({'first_split': first_split, 'ending': ending, 'started': started, 'held': list(c.state.held)})
print(json.dumps({'head': 'cb623269bbef89331f467b457f043090b2cf8d6c', 'results': results}, indent=2))
